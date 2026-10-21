"""
vnet.py - the virtual network adapter that makes remote PCs look like they are
on your LAN.

The tunnel in peer.py moves datagrams between PCs. To make GAMES see each
other, the operating system needs a network interface whose packets we can
grab and inject. That is a TUN device: a virtual NIC with no cable, where
  - every IP packet the OS sends to it (game traffic to 10.77.0.x, LAN
    broadcasts, multicast discovery) is handed to us instead of a wire, and
  - every packet we write to it looks to the OS like it arrived from the LAN.
peer.py reads packets from here, sends them through the tunnel to the right
peer, and that peer writes them into its own adapter.

Backends
  Windows: Wintun (wintun.dll, the signed driver from the WireGuard project).
           Creating the adapter needs administrator rights.
  Linux:   /dev/net/tun (needs root / CAP_NET_ADMIN). Used for testing.
"""

import hashlib
import io
import ipaddress
import logging
import os
import platform
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

log = logging.getLogger("vnet")

ADAPTER_NAME = "Rendezvous"
MTU = 1280  # small enough that packet + tunnel header never needs IP fragmentation

WINTUN_URL = "https://www.wintun.net/builds/wintun-0.14.1.zip"
WINTUN_ZIP_SHA256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51"
# A fixed GUID means Windows sees the same adapter (and the same network
# profile / firewall category) every time, instead of "Network 2, 3, 4...".
ADAPTER_GUID = uuid.UUID("6f0d2a52-1c8e-4b8a-9a77-52454e44455a")


class VnetError(Exception):
    """A user-facing problem setting up the adapter (shown on the dashboard)."""


def open_adapter(name=ADAPTER_NAME):
    if sys.platform == "win32":
        return WintunAdapter(name)
    if sys.platform.startswith("linux"):
        return LinuxTun(name)
    raise VnetError(f"virtual adapter not supported on {sys.platform}")


class _Base:
    kind = "?"

    def __init__(self, name):
        self.name = name
        self.ip = None
        self.prefix = None
        self._running = False
        self._thread = None

    def start(self, on_packet):
        """Start a reader thread that calls on_packet(bytes) for every packet
        the OS sends into the adapter (called from that thread)."""
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, args=(on_packet,),
                                        name="vnet-reader", daemon=True)
        self._thread.start()

    def stop_reader(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)


def _run(cmd, check=True):
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: no console flashing up
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    log.debug("$ %s -> %d %s%s", " ".join(cmd), r.returncode, r.stdout.strip(), r.stderr.strip())
    if check and r.returncode != 0:
        raise VnetError(f"'{' '.join(cmd[:4])} ...' failed: {(r.stdout + r.stderr).strip()[:200]}")
    return r


# ====================================================================== Linux
class LinuxTun(_Base):
    kind = "tun"
    TUNSETIFF = 0x400454CA
    IFF_TUN = 0x0001
    IFF_NO_PI = 0x1000  # no extra 4-byte header: we get bare IP packets, like Wintun

    def __init__(self, name):
        super().__init__(name)
        import fcntl
        try:
            self.fd = os.open("/dev/net/tun", os.O_RDWR)
            fcntl.ioctl(self.fd, self.TUNSETIFF, struct.pack("16sH", name.encode(), self.IFF_TUN | self.IFF_NO_PI))
        except PermissionError:
            raise VnetError("creating a TUN device needs root (run with sudo)") from None
        except OSError as e:
            raise VnetError(f"could not create TUN device: {e}") from None
        _run(["ip", "link", "set", name, "mtu", str(MTU), "up"])

    def set_address(self, ip, prefix):
        _run(["ip", "addr", "flush", "dev", self.name])
        _run(["ip", "addr", "add", f"{ip}/{prefix}", "dev", self.name])
        # Send multicast (game discovery, e.g. Minecraft's 224.0.2.60) and
        # 255.255.255.255 broadcasts into the virtual LAN. Same trade-off as Radmin/Hamachi: it wins over the real NIC.
        _run(["ip", "route", "replace", "224.0.0.0/4", "dev", self.name], check=False)
        _run(["ip", "route", "replace", "255.255.255.255/32", "dev", self.name], check=False)
        self.ip, self.prefix = ip, prefix

    def _read_loop(self, on_packet):
        import select
        while self._running:
            r, _, _ = select.select([self.fd], [], [], 0.5)
            if r:
                try:
                    on_packet(os.read(self.fd, 65535))
                except OSError:
                    break

    def write(self, pkt):
        try:
            os.write(self.fd, pkt)
        except OSError as e:
            log.debug("tun write failed: %s", e)

    def close(self):
        self.stop_reader()
        try:
            os.close(self.fd)
        except OSError:
            pass


# ==================================================================== Windows
def _wintun_dll_path():
    """Find wintun.dll next to the exe/script; download it (hash-checked) if missing."""
    arch = {"AMD64": "amd64", "x86_64": "amd64", "ARM64": "arm64", "x86": "x86"}.get(platform.machine(), "amd64")
    dirs = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent, Path(__file__).resolve().parent, Path.cwd()]
    for d in dirs:
        if str(d) and (d / "wintun.dll").is_file():
            return d / "wintun.dll"
    target = Path(__file__).resolve().parent / "wintun.dll"
    log.info("wintun.dll not found, downloading %s", WINTUN_URL)
    try:
        data = urllib.request.urlopen(WINTUN_URL, timeout=30).read()
    except OSError as e:
        raise VnetError(f"wintun.dll missing and download failed ({e}). "
                        f"Get {WINTUN_URL} and put bin/{arch}/wintun.dll next to the program.") from None
    digest = hashlib.sha256(data).hexdigest()
    if digest != WINTUN_ZIP_SHA256:
        raise VnetError(f"downloaded Wintun archive has the wrong SHA-256 ({digest}); refusing to load it")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        target.write_bytes(z.read(f"wintun/bin/{arch}/wintun.dll"))
    return target


class WintunAdapter(_Base):
    kind = "wintun"
    ERROR_NO_MORE_ITEMS = 259
    ERROR_HANDLE_EOF = 38
    RING_CAPACITY = 0x400000  # 4 MiB packet ring between us and the driver

    def __init__(self, name):
        super().__init__(name)
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes

        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise VnetError("creating the virtual adapter needs administrator rights "
                            "(right-click > Run as administrator)")
        path = _wintun_dll_path()
        dll = self.dll = ctypes.WinDLL(str(path), use_last_error=True)
        H = ctypes.c_void_p
        dll.WintunCreateAdapter.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
        dll.WintunCreateAdapter.restype = H
        dll.WintunOpenAdapter.argtypes = [wintypes.LPCWSTR]
        dll.WintunOpenAdapter.restype = H
        dll.WintunCloseAdapter.argtypes = [H]
        dll.WintunCloseAdapter.restype = None
        dll.WintunStartSession.argtypes = [H, wintypes.DWORD]
        dll.WintunStartSession.restype = H
        dll.WintunEndSession.argtypes = [H]
        dll.WintunEndSession.restype = None
        dll.WintunGetReadWaitEvent.argtypes = [H]
        dll.WintunGetReadWaitEvent.restype = wintypes.HANDLE
        dll.WintunReceivePacket.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
        dll.WintunReceivePacket.restype = ctypes.c_void_p
        dll.WintunReleaseReceivePacket.argtypes = [H, ctypes.c_void_p]
        dll.WintunReleaseReceivePacket.restype = None
        dll.WintunAllocateSendPacket.argtypes = [H, wintypes.DWORD]
        dll.WintunAllocateSendPacket.restype = ctypes.c_void_p
        dll.WintunSendPacket.argtypes = [H, ctypes.c_void_p]
        dll.WintunSendPacket.restype = None
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.k32.WaitForSingleObject.restype = wintypes.DWORD

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]
        f = ADAPTER_GUID.fields
        guid = GUID(f[0], f[1], f[2], (ctypes.c_ubyte * 8)(*ADAPTER_GUID.bytes[8:]))

        # Reuse an adapter left over from a crash, otherwise create one.
        self.adapter = dll.WintunOpenAdapter(name) or dll.WintunCreateAdapter(name, "Rendezvous", ctypes.byref(guid))
        if not self.adapter:
            raise VnetError(f"could not create the Wintun adapter (Windows error {ctypes.get_last_error()})")
        self.session = dll.WintunStartSession(self.adapter, self.RING_CAPACITY)
        if not self.session:
            err = ctypes.get_last_error()
            dll.WintunCloseAdapter(self.adapter)
            raise VnetError(f"could not start the Wintun session (Windows error {err})")
        self.read_event = dll.WintunGetReadWaitEvent(self.session)
        self._send_lock = threading.Lock()

    def set_address(self, ip, prefix):
        mask = str(ipaddress.ip_network(f"0.0.0.0/{prefix}").netmask)
        subnet = str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
        # The interface can take a moment to appear after creation: retry.
        for attempt in range(20):
            r = _run(["netsh", "interface", "ipv4", "set", "address", f"name={self.name}", "source=static",
                      f"address={ip}", f"mask={mask}", "gateway=none"], check=False)
            if r.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise VnetError(f"could not assign {ip} to the adapter: {(r.stdout + r.stderr).strip()[:200]}")
        # Metric 1 = preferred interface, so LAN broadcasts (255.255.255.255)
        # and multicast discovery go out through the virtual LAN. This is the
        # same trick Radmin VPN / Hamachi rely on.
        _run(["netsh", "interface", "ipv4", "set", "interface", f"interface={self.name}", "metric=1"], check=False)
        _run(["netsh", "interface", "ipv4", "set", "subinterface", self.name, f"mtu={MTU}", "store=active"], check=False)
        # New adapters land in the "Public" firewall profile, which blocks games
        # from accepting connections. Allow inbound traffic from the virtual LAN only.
        _run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=Rendezvous VLAN"], check=False)
        _run(["netsh", "advfirewall", "firewall", "add", "rule", "name=Rendezvous VLAN", "dir=in",
              "action=allow", "protocol=any", f"remoteip={subnet}"], check=False)
        self.ip, self.prefix = ip, prefix

    def _read_loop(self, on_packet):
        ct, dll = self.ct, self.dll
        size = ct.c_ulong(0)
        while self._running:
            p = dll.WintunReceivePacket(self.session, ct.byref(size))
            if p:
                data = ct.string_at(p, size.value)
                dll.WintunReleaseReceivePacket(self.session, p)
                on_packet(data)
                continue
            err = ct.get_last_error()
            if err == self.ERROR_NO_MORE_ITEMS:
                self.k32.WaitForSingleObject(self.read_event, 250)
            elif err == self.ERROR_HANDLE_EOF:
                log.warning("Wintun adapter is shutting down")
                break
            else:
                log.error("WintunReceivePacket failed (Windows error %d)", err)
                break

    def write(self, pkt):
        ct = self.ct
        with self._send_lock:
            p = self.dll.WintunAllocateSendPacket(self.session, len(pkt))
            if not p:
                log.debug("Wintun send ring full, dropping packet")
                return
            ct.memmove(p, pkt, len(pkt))
            self.dll.WintunSendPacket(self.session, p)

    def close(self):
        self.stop_reader()
        if self.session:
            self.dll.WintunEndSession(self.session)
            self.session = None
        if self.adapter:
            self.dll.WintunCloseAdapter(self.adapter)  # removes the adapter we created
            self.adapter = None
