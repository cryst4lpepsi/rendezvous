"""
hosting.py - lets any player HOST a network from the app, no cloud server needed.

When you click "Host", your app:
  1. starts the rendezvous server inside the app (same code as rendezvous_server.py),
  2. asks your home router to forward its UDP port to this PC, using UPnP
     (the same mechanism games and consoles use to "open NAT"),
  3. makes a 10-digit JOIN CODE from your public address. Friends type your
     network name + that code into "Join". Nothing else is involved: the code
     itself tells their app where you are.

If the router doesn't do UPnP, you can forward the port by hand, or everyone can
use a rendezvous server on a cloud VM instead (rendezvous_server.py).
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree

import rendezvous_server

log = logging.getLogger("hosting")

SSDP_ADDR = ("239.255.255.250", 1900)
WAN_SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2",
                "urn:schemas-upnp-org:service:WANIPConnection:1",
                "urn:schemas-upnp-org:service:WANPPPConnection:1")


# ================================================================ join codes
DEFAULT_PORT = 9000


def room_for(network):
    """Network names are case-insensitive: "Friday" and "friday" are one network."""
    return " ".join((network or "").split()).lower()


def _key(network):
    return int.from_bytes(hashlib.sha256(room_for(network).encode()).digest()[:4], "big")


def make_code(network, ip, port=DEFAULT_PORT):
    """
    The host's join code: its public IPv4 address (a 32-bit number, so it fits
    in 10 digits) scrambled with the network name. A friend who types the same
    network name gets the address back; no lookup service is needed. A port
    other than 9000 is added as ":port".
    """
    code = f"{int(ipaddress.IPv4Address(ip)) ^ _key(network):010d}"
    return code if port == DEFAULT_PORT else f"{code}:{port}"


def format_code(code):
    """1234567890 -> "123 456 7890", 123456 -> "123 456" (easier to read out or type)."""
    digits, _, port = code.partition(":")
    if len(digits) == 6:
        return f"{digits[:3]} {digits[3:]}"
    return f"{digits[:3]} {digits[3:6]} {digits[6:]}" + (f" :{port}" if port else "")


def parse_code(network, text):
    """Returns (ip, port) for a code typed by a friend, or raises ValueError."""
    t = re.sub(r"[\s.\-]", "", text or "")
    digits, _, port = t.partition(":")
    if not digits.isdigit() or len(digits) != 10 or (port and not port.isdigit()):
        raise ValueError("the code is 10 digits, like 123 456 7890")
    n = int(digits)
    if n >= 2 ** 32:
        raise ValueError("that code isn't valid, check the digits")
    if not room_for(network):
        raise ValueError("enter the network name too")
    ip = str(ipaddress.IPv4Address(n ^ _key(network)))
    return ip, int(port) if port else DEFAULT_PORT


def find_on_lan(network, port=DEFAULT_PORT, timeout=1.2):
    """
    Ask the local network "is anyone hosting <network>?" (UDP broadcast). This
    is how friends in the host's own home find it, since many routers can't
    route back to their own public address. Returns "ip:port" or None.
    """
    lan = lan_ip_towards("8.8.8.8")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.bind((lan or "0.0.0.0", 0))  # send out of the real network card, not the virtual one
    except OSError:
        s.bind(("0.0.0.0", 0))
    msg = json.dumps({"t": "find", "room": room_for(network)}).encode()
    targets = ["255.255.255.255"]
    if lan:
        targets.append(str(ipaddress.ip_network(f"{lan}/24", strict=False).broadcast_address))
    for target in targets:
        try:
            s.sendto(msg, (target, port))
        except OSError:
            pass
    s.settimeout(0.2)
    end = time.time() + timeout
    try:
        while time.time() < end:
            try:
                data, addr = s.recvfrom(2048)
            except (socket.timeout, ConnectionResetError):
                continue
            try:
                m = json.loads(data)
            except ValueError:
                continue
            if isinstance(m, dict) and m.get("t") == "here" and m.get("room") == room_for(network):
                return f"{addr[0]}:{addr[1]}"
    finally:
        s.close()
    return None


def is_private(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return a.is_private or a.is_loopback or a.is_link_local or a in ipaddress.ip_network("100.64.0.0/10")


def lan_ip_towards(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


# ======================================================== router port opening
class PortMapError(Exception):
    pass


UPnPError = PortMapError  # older name

# Requests to the router must never go through a proxy configured on the PC.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def default_gateway():
    """The home router's LAN address (where UPnP / NAT-PMP live), or None."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["route", "print", "-4", "0.0.0.0"], capture_output=True, text=True,
                                 creationflags=0x08000000).stdout
            lan, best = lan_ip_towards("8.8.8.8"), None
            for line in out.splitlines():
                f = line.split()
                if len(f) >= 5 and f[0] == "0.0.0.0" and f[1] == "0.0.0.0" and f[2][0].isdigit():
                    metric = int(f[4]) if f[4].isdigit() else 9999
                    score = (f[3] != lan, metric)  # prefer the route of our real network card
                    if best is None or score < best[0]:
                        best = (score, f[2])
            return best[1] if best else None
        with open("/proc/net/route") as fh:
            for line in fh.readlines()[1:]:
                f = line.split()
                if f[1] == "00000000" and int(f[3], 16) & 2:  # default route with a gateway
                    return socket.inet_ntoa(struct.pack("<I", int(f[2], 16)))
    except (OSError, ValueError, IndexError):
        pass
    return None


class UPnP:
    """
    Minimal UPnP Internet Gateway Device client (stdlib only):
      find the router with SSDP, read its description, then call
      GetExternalIPAddress / AddPortMapping / DeletePortMapping over SOAP.
    """
    name = "UPnP"
    SEARCH_TARGETS = ("urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                      "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
                      "urn:schemas-upnp-org:service:WANIPConnection:1",
                      "urn:schemas-upnp-org:service:WANPPPConnection:1",
                      "upnp:rootdevice")
    # Where common routers publish their description, for routers that don't
    # answer searches (miniupnpd/OpenWrt, FRITZ!Box, many TP-Link/Netgear, ...).
    KNOWN_DESCRIPTIONS = ("http://{gw}:5000/rootDesc.xml", "http://{gw}:49000/igddesc.xml",
                          "http://{gw}:1900/igd.xml", "http://{gw}:1780/InternetGatewayDevice.xml",
                          "http://{gw}:5431/dyndev/uuid", "http://{gw}:2048/etc/linuxigd/gatedesc.xml")

    def __init__(self, control_url, service, router_host):
        self.control_url = control_url
        self.service = service
        self.router_host = router_host
        self.lan_ip = lan_ip_towards(router_host)
        self.mapped = []  # (external_port, protocol, internal_port)

    @classmethod
    def discover(cls, timeout=3.0):
        lan, gw = lan_ip_towards("8.8.8.8"), default_gateway()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((lan or "", 0))  # use the real network card, not the virtual one
        except OSError:
            pass
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        if lan:
            try:
                # Our virtual adapter is the preferred route for multicast (that's
                # how game discovery reaches the other players): send the search
                # out of the real card or the router never hears it.
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(lan))
            except OSError:
                pass
        s.settimeout(0.25)
        # Ask everyone (multicast) and the router directly (unicast), a few
        # times: SSDP is plain UDP and packets get lost.
        targets = [SSDP_ADDR] + ([(gw, 1900)] if gw else [])
        locations, end, next_round, rounds = [], time.time() + timeout, 0.0, 0
        while time.time() < end:
            if time.time() >= next_round and rounds < 3:
                rounds += 1
                next_round = time.time() + 0.9
                for st in cls.SEARCH_TARGETS:
                    msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                           f"MX: 2\r\nST: {st}\r\n\r\n").encode()
                    for t in targets:
                        try:
                            s.sendto(msg, t)
                        except OSError:
                            pass
            try:
                data, _ = s.recvfrom(4096)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:
                break
            m = re.search(rb"(?im)^location:\s*(\S+)", data)
            if m and m.group(1).decode() not in locations:
                locations.append(m.group(1).decode())
                if gw and urllib.parse.urlparse(locations[-1]).hostname == gw and rounds >= 1:
                    end = min(end, time.time() + 0.5)  # the router answered: don't wait much longer
        s.close()
        if gw:  # router first, then known description URLs
            locations.sort(key=lambda u: urllib.parse.urlparse(u).hostname != gw)
            locations += [u.format(gw=gw) for u in cls.KNOWN_DESCRIPTIONS]
        for loc in locations:
            try:
                found = cls._from_description(loc)
            except (OSError, ElementTree.ParseError, ValueError) as e:
                log.debug("UPnP description %s unusable: %s", loc, e)
                continue
            if found:
                return found
        raise PortMapError("no UPnP answer from the router")

    @classmethod
    def _from_description(cls, location):
        xml = _DIRECT.open(location, timeout=1.5).read()
        root = ElementTree.fromstring(xml)
        ns = {"d": root.tag[1:].split("}")[0]} if root.tag.startswith("{") else {"d": ""}
        base = root.findtext("d:URLBase", default="", namespaces=ns) or location
        for svc in root.iter(f"{{{ns['d']}}}service" if ns["d"] else "service"):
            stype = svc.findtext("d:serviceType", default="", namespaces=ns)
            if stype in WAN_SERVICES:
                ctrl = urllib.parse.urljoin(base, svc.findtext("d:controlURL", default="", namespaces=ns))
                return cls(ctrl, stype, urllib.parse.urlparse(location).hostname)
        return None

    def _soap(self, action, args):
        body = "".join(f"<{k}>{v}</{k}>" for k, v in args)
        envelope = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                    f'<u:{action} xmlns:u="{self.service}">{body}</u:{action}></s:Body></s:Envelope>').encode()
        req = urllib.request.Request(self.control_url, data=envelope, headers={
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{self.service}#{action}"'})
        try:
            return _DIRECT.open(req, timeout=5).read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            code = re.search(r"<errorCode>(\d+)</errorCode>", text)
            desc = re.search(r"<errorDescription>([^<]*)</errorDescription>", text)
            raise PortMapError(f"{action} refused ({code.group(1) if code else e.code} "
                               f"{desc.group(1) if desc else ''})".strip()) from None
        except OSError as e:
            raise PortMapError(f"{action} failed: {e}") from None

    def external_ip(self):
        m = re.search(r"<NewExternalIPAddress>([^<]*)<", self._soap("GetExternalIPAddress", []))
        if not m or not m.group(1):
            raise PortMapError("router did not report its public IP")
        return m.group(1)

    def _add(self, ext, protocol, internal_port, lease):
        self._soap("AddPortMapping", [
            ("NewRemoteHost", ""), ("NewExternalPort", ext), ("NewProtocol", protocol),
            ("NewInternalPort", internal_port), ("NewInternalClient", self.lan_ip),
            ("NewEnabled", 1), ("NewPortMappingDescription", f"Rendezvous {protocol} {internal_port}"),
            ("NewLeaseDuration", lease)])

    def add_mapping(self, internal_port, protocol="UDP", tries=10):
        """Forward a public port to (this PC, internal_port). Prefers the same
        port number; returns the external port actually mapped."""
        if not self.lan_ip:
            raise PortMapError("cannot work out this PC's LAN address")
        last = None
        for ext in [internal_port] + [internal_port + i for i in range(1, tries)]:
            for lease in (3600, 0):  # some routers only accept permanent (0) leases
                try:
                    self._add(ext, protocol, internal_port, lease)
                    self.mapped.append((ext, protocol, internal_port))
                    return ext
                except PortMapError as e:
                    last = e
                    if "725" not in str(e):  # 725 = OnlyPermanentLeasesSupported -> retry with 0
                        break
        raise last

    def refresh(self):
        """Renew the leases before they run out (they last an hour)."""
        for ext, proto, internal in self.mapped:
            for lease in (3600, 0):
                try:
                    self._add(ext, proto, internal, lease)
                    break
                except PortMapError as e:
                    if "725" not in str(e):
                        log.info("UPnP renewal of %s/%s failed: %s", ext, proto, e)
                        break

    def remove_all(self):
        for ext, proto, _ in self.mapped:
            try:
                self._soap("DeletePortMapping", [("NewRemoteHost", ""), ("NewExternalPort", ext),
                                                 ("NewProtocol", proto)])
            except PortMapError as e:
                log.debug("could not remove mapping %s/%s: %s", ext, proto, e)
        self.mapped = []


class NatPmp:
    """
    NAT-PMP (RFC 6886): the port-opening protocol of Apple routers, also spoken
    by many routers that have UPnP turned off or don't do UPnP at all
    (and by PCP routers, which answer NAT-PMP requests). Plain UDP to the
    router on port 5351.
    """
    name = "NAT-PMP"
    PORT = 5351

    def __init__(self, gateway):
        self.gateway = gateway
        self.mapped = []  # (internal_port, external_port)

    @classmethod
    def discover(cls):
        gw = default_gateway()
        if not gw:
            raise PortMapError("no default gateway found for NAT-PMP")
        m = cls(gw)
        m.external_ip()  # raises if the router doesn't speak NAT-PMP
        return m

    def _request(self, payload, opcode):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((lan_ip_towards(self.gateway) or "", 0))
            for wait in (0.25, 0.5, 1.0):  # RFC 6886: resend with doubling timeouts
                s.sendto(payload, (self.gateway, self.PORT))
                s.settimeout(wait)
                end = time.time() + wait
                while time.time() < end:
                    try:
                        data, addr = s.recvfrom(64)
                    except (socket.timeout, ConnectionResetError):
                        break
                    if addr[0] == self.gateway and len(data) >= 8 and data[1] == opcode:
                        result = struct.unpack("!H", data[2:4])[0]
                        if result:
                            raise PortMapError(f"NAT-PMP refused (result code {result})")
                        return data
        except OSError as e:
            raise PortMapError(f"NAT-PMP failed: {e}") from None
        finally:
            s.close()
        raise PortMapError("no NAT-PMP answer from the router")

    def external_ip(self):
        return socket.inet_ntoa(self._request(b"\x00\x00", 128)[8:12])

    def _map(self, internal, external, lifetime):
        r = self._request(struct.pack("!BBHHHI", 0, 1, 0, internal, external, lifetime), 129)
        return struct.unpack("!H", r[10:12])[0]

    def add_mapping(self, internal_port, protocol="UDP", tries=1):
        ext = self._map(internal_port, internal_port, 3600)
        self.mapped.append((internal_port, ext))
        return ext

    def refresh(self):
        for internal, ext in self.mapped:
            try:
                self._map(internal, ext, 3600)
            except PortMapError as e:
                log.info("NAT-PMP renewal of %s failed: %s", ext, e)

    def remove_all(self):
        for internal, _ in self.mapped:
            try:
                self._map(internal, 0, 0)
            except PortMapError:
                pass
        self.mapped = []


def open_router_ports(ports):
    """
    Ask the router to forward `ports` (UDP) to this PC: UPnP first, then NAT-PMP.
    Returns (mapper, public_ip, {port: external_port}) or raises PortMapError
    with what was tried.
    """
    errors = []
    for cls in (UPnP, NatPmp):
        try:
            mapper = cls.discover()
            public_ip = mapper.external_ip()
            mapped = {ports[0]: mapper.add_mapping(ports[0])}
            for extra in ports[1:]:
                try:
                    mapped[extra] = mapper.add_mapping(extra)
                except PortMapError as e:
                    log.info("could not forward port %s: %s", extra, e)
            return mapper, public_ip, mapped
        except PortMapError as e:
            errors.append(f"{cls.name}: {e}")
    raise PortMapError("; ".join(errors))


def allow_app_through_firewall():
    """
    Windows Firewall blocks programs from receiving connections until they are
    allowed. A forwarded router port is no use if Windows then drops the
    packets, so allow this program (needs admin; harmless if already allowed).
    """
    if sys.platform != "win32":
        return False
    from vnet import _run
    _run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=Rendezvous app"], check=False)
    r = _run(["netsh", "advfirewall", "firewall", "add", "rule", "name=Rendezvous app", "dir=in",
              "action=allow", f"program={sys.executable}", "protocol=UDP", "profile=any", "enable=yes"],
             check=False)
    return r.returncode == 0


# ======================================== hosting behind CGNAT: STUN + mailbox
# When no router port can be opened (the provider's CGNAT, or UPnP off), the
# host can still be reached by hole punching. Two free public services are used
# only to swap addresses, never for game traffic:
#   STUN    - "which public address do my packets come from?"
#   ntfy.sh - a public message board, used as a mailbox: the host posts its
#             address there, a joining friend posts "I'm here, my address is
#             ...", and both sides then punch through their NATs.
# Messages are encrypted with a key made from the network name + code; the
# mailbox name is a hash of them too, so the service sees only noise.
MAILBOX_URL = os.environ.get("RENDEZVOUS_MAILBOX", "https://ntfy.sh").rstrip("/")
STUN_SERVERS = os.environ.get("RENDEZVOUS_STUN", "stun.l.google.com:19302,stun.cloudflare.com:3478")
SHORT_CODE_DIGITS = 6


def stun_servers():
    """The STUN servers as resolved (ip, port) addresses."""
    out = []
    for item in STUN_SERVERS.split(","):
        host, _, port = item.strip().rpartition(":")
        try:
            out.append(socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_DGRAM)[0][4][:2])
        except (OSError, ValueError):
            continue
    return out


def stun_probe():
    """This PC's public address from a fresh socket (diagnostics / tests)."""
    from rendezvous_server import parse_stun_response, stun_request
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    try:
        for addr in stun_servers():
            tid = os.urandom(12)
            try:
                s.sendto(stun_request(tid), addr)
                r = parse_stun_response(s.recvfrom(2048)[0])
                if r and r[0] == tid:
                    return r[1]
            except OSError:
                continue
    finally:
        s.close()
    return None


def new_short_code():
    return f"{secrets.randbelow(10 ** SHORT_CODE_DIGITS):0{SHORT_CODE_DIGITS}d}"


class Mailbox:
    def __init__(self, room, code):
        seed = f"rendezvous|{room}|{code}".encode()
        self.topic = "rzv" + hashlib.sha256(b"topic|" + seed).hexdigest()[:32]
        self._kenc = hashlib.sha256(b"enc|" + seed).digest()
        self._kmac = hashlib.sha256(b"mac|" + seed).digest()
        self.url = f"{MAILBOX_URL}/{self.topic}"

    def _stream(self, nonce, n):
        out, i = b"", 0
        while len(out) < n:  # SHA-256 in counter mode as the keystream
            out += hashlib.sha256(self._kenc + nonce + i.to_bytes(4, "big")).digest()
            i += 1
        return out[:n]

    def seal(self, obj):
        nonce = os.urandom(12)
        pt = json.dumps(obj, separators=(",", ":")).encode()
        ct = bytes(a ^ b for a, b in zip(pt, self._stream(nonce, len(pt))))
        tag = hmac.new(self._kmac, nonce + ct, hashlib.sha256).digest()[:16]
        return base64.urlsafe_b64encode(nonce + tag + ct).decode()

    def unseal(self, text):
        try:
            raw = base64.urlsafe_b64decode(text)
            nonce, tag, ct = raw[:12], raw[12:28], raw[28:]
            if not hmac.compare_digest(tag, hmac.new(self._kmac, nonce + ct, hashlib.sha256).digest()[:16]):
                return None
            obj = json.loads(bytes(a ^ b for a, b in zip(ct, self._stream(nonce, len(ct)))))
            return obj if isinstance(obj, dict) else None
        except (ValueError, TypeError):
            return None

    def publish(self, obj):
        req = urllib.request.Request(self.url, data=self.seal(obj).encode(), method="POST",
                                     headers={"Content-Type": "text/plain", "User-Agent": "Rendezvous"})
        urllib.request.urlopen(req, timeout=10).read()

    def _messages(self, lines):
        for line in lines:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("event") == "message":
                obj = self.unseal(m.get("message", ""))
                if obj is not None:
                    yield m.get("id"), obj

    def fetch(self, since="12h"):
        req = urllib.request.Request(f"{self.url}/json?poll=1&since={since}", headers={"User-Agent": "Rendezvous"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return [obj for _, obj in self._messages(r.read().decode(errors="replace").splitlines())]

    def listen(self, on_message, stop):
        """Call on_message(obj) for every new message, until `stop` is set."""
        def run():
            since = str(int(time.time()) - 5)
            while not stop.is_set():
                try:
                    req = urllib.request.Request(f"{self.url}/json?since={since}", headers={"User-Agent": "Rendezvous"})
                    with urllib.request.urlopen(req, timeout=90) as r:
                        for mid, obj in self._messages(iter(r.readline, b"")):
                            since = mid or since
                            if stop.is_set():
                                return
                            on_message(obj)
                except OSError as e:
                    log.debug("mailbox stream: %s", e)
                stop.wait(3)
        threading.Thread(target=run, name="mailbox", daemon=True).start()


class PunchHost:
    """Keeps a CGNAT host reachable: announces its address in the mailbox and
    punches toward every friend who knocks."""

    def __init__(self, info, room, code):
        self.info = info
        self.server = info["server"].server
        self.mailbox = Mailbox(room, code)
        self.code = code
        self.stop = threading.Event()
        self.endpoint = None
        self.symmetric = False
        self.error = None
        self.knocks = 0

    def start(self):
        """Blocking. Returns True when the host is announced."""
        eps = [ep for ep in (self.server.stun(a) for a in stun_servers()[:2]) if ep]
        if not eps:
            self.error = "couldn't reach a STUN server to learn this PC's public address"
            return False
        self.endpoint = eps[0]
        # The same public port towards two different servers = the NAT keeps
        # one mapping per socket ("cone"): punching works. Different ports =
        # "symmetric" NAT: punching will most likely fail.
        self.symmetric = len(eps) > 1 and eps[0][1] != eps[1][1]
        self.server.public_ip = self.endpoint[0]
        try:
            self.announce()
        except OSError as e:
            self.error = f"couldn't reach the mailbox service ({MAILBOX_URL}): {e}"
            return False
        self.mailbox.listen(self._on_message, self.stop)
        threading.Thread(target=self._keepalive, name="punch-keepalive", daemon=True).start()
        return True

    def announce(self):
        lan = self.info["lan_ip"]
        self.mailbox.publish({"t": "host", "ep": list(self.endpoint),
                              "lan": [lan, self.info["server"].port] if lan else None, "ts": int(time.time())})

    def _on_message(self, obj):
        ep = obj.get("ep")
        if obj.get("t") == "knock" and isinstance(ep, list) and len(ep) == 2:
            self.knocks += 1
            log.info("knock from %s at %s:%s - punching toward it", obj.get("name"), ep[0], ep[1])
            self.server.punch_toward((str(ep[0]), int(ep[1])))

    def _keepalive(self):
        """Keep the NAT mapping alive (they expire after ~30 s idle on many
        NATs) and re-announce if the public address changes."""
        last_announce = time.time()
        while not self.stop.wait(20):
            servers = stun_servers()
            ep = self.server.stun(servers[0]) if servers else None
            changed = bool(ep) and ep != self.endpoint
            if changed:
                log.info("public address changed %s -> %s, re-announcing", self.endpoint, ep)
                self.endpoint = ep
                self.server.public_ip = ep[0]
            if changed or time.time() - last_announce > 600:  # ntfy keeps messages ~12 h
                try:
                    self.announce()
                    last_announce = time.time()
                except OSError as e:
                    log.info("mailbox re-announce failed: %s", e)

    def close(self):
        self.stop.set()


def parse_any(network, text):
    """A code typed by a friend: 10 digits = the host's address (direct), 6
    digits = a mailbox code (host behind CGNAT). Raises ValueError."""
    if not room_for(network):
        raise ValueError("enter the network name too")
    digits = re.sub(r"[\s.\-]", "", text or "").partition(":")[0]
    if digits.isdigit() and len(digits) == SHORT_CODE_DIGITS and ":" not in (text or ""):
        return {"kind": "mailbox", "code": digits}
    if digits.isdigit() and len(digits) == 10:
        ip, port = parse_code(network, text)
        return {"kind": "address", "ip": ip, "port": port}
    raise ValueError(f"the code is {SHORT_CODE_DIGITS} or 10 digits, like 123 456 or 123 456 7890")


# ============================================================ embedded server
class EmbeddedServer:
    """The rendezvous server, running on a thread inside the host's app."""

    def __init__(self, port, room):
        self.server = rendezvous_server.RendezvousServer("0.0.0.0", port, "10.77.0.0/24")
        self.server.only_room = room  # this server is for the host's network only
        self.port = self.server.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._run, name="rendezvous-server", daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.server.serve_forever()
        except OSError:
            pass  # socket closed by stop()

    def stop(self):
        self.server.running = False
        self.thread.join(2)
        self.server.sock.close()


RENEW_EVERY = 20 * 60  # router leases last an hour; renew well before


def _renew_loop(info):
    while not info["stop"].wait(RENEW_EVERY):
        mapper = info.get("mapper")
        if mapper:
            mapper.refresh()


def start_hosting(port, room, peer_udp_port, use_upnp=True, punch_code=None):
    """
    Blocking (run it off the UI/event-loop thread). Starts the embedded server
    and tries to make it reachable from the internet. Returns a dict:
      server: EmbeddedServer, mapper: UPnP/NatPmp or None, public_ip, server_port,
      status: human-readable reachability summary, reachable: True/False/None
    """
    server = EmbeddedServer(port, room)
    info = {"server": server, "mapper": None, "public_ip": None, "server_port": server.port,
            "lan_ip": lan_ip_towards("8.8.8.8"), "gateway": default_gateway(),
            "reachable": None, "status": "", "stop": threading.Event(), "use_upnp": use_upnp,
            "peer_udp_port": peer_udp_port, "room": room, "mode": None, "punch": None,
            "punch_code": punch_code or new_short_code()}
    info["firewall"] = allow_app_through_firewall()
    map_ports(info)
    threading.Thread(target=_renew_loop, args=(info,), name="port-renewal", daemon=True).start()
    return info


def map_ports(info):
    """(Re)try opening the router ports. Also used by the "Try again" button."""
    server = info["server"]
    error = "automatic port opening is turned off in the app"
    if info["use_upnp"]:
        if info.get("mapper"):
            info["mapper"].remove_all()
            info["mapper"] = None
        try:
            mapper, public_ip, mapped = open_router_ports([server.port, info["peer_udp_port"]])
            info.update(mapper=mapper, public_ip=public_ip, server_port=mapped[server.port])
            if info["peer_udp_port"] in mapped:
                # The host's own tunnel port is forwarded too: every player can
                # reach the host directly, no hole punching needed for that link.
                server.server.overrides[info["peer_udp_port"]] = (public_ip, mapped[info["peer_udp_port"]])
            error = None
        except PortMapError as e:
            error = str(e)
    server.server.public_ip = info["public_ip"]

    gw = info["gateway"] or "your router"
    if info["mapper"] and info["public_ip"] and not is_private(info["public_ip"]):
        info["reachable"], info["mode"] = True, "direct"
        info["status"] = (f"Router port opened automatically ({info['mapper'].name}): UDP {info['server_port']} "
                          f"is open, friends anywhere can join.")
        if info["punch"]:  # no need for the mailbox any more
            info["punch"].close()
            info["punch"] = None
        return info

    info["reachable"] = False
    if info["mapper"] and info["public_ip"]:
        why = "your internet provider uses CGNAT"
        info["detail"] = (f"the router's internet address {info['public_ip']} is not a public one (CGNAT); "
                          f"nothing on the router can change that")
    else:
        why = "your router's port isn't open"
        info["detail"] = (f"router port not opened: {error}. To host without the online services: open "
                          f"http://{gw}, turn on UPnP and click Try again, or forward UDP {server.port} to "
                          f"{info['lan_ip'] or 'this PC'}")
    # Fall back to hole punching, with STUN + the mailbox to swap addresses.
    if not info["punch"] or info["punch"].error:
        ph = PunchHost(info, info["room"], info["punch_code"])
        ph.start()
        info["punch"] = ph
    ph = info["punch"]
    if ph.error:
        info["mode"] = "lan"
        info["status"] = (f"Only friends on your home network can join: {why}, and the online fallback "
                          f"failed ({ph.error}). Let a friend with a normal connection host.")
    else:
        info["mode"] = "punch"
        if not info["public_ip"] or is_private(info["public_ip"]):
            info["public_ip"] = ph.endpoint[0]
        info["status"] = (f"Online through hole punching ({why}). Friends connect straight to you; the free "
                          f"services STUN and ntfy.sh only help swap addresses."
                          + (" Warning: your connection changes ports for every destination (symmetric NAT), "
                             "so punching will probably fail; if friends can't connect, let someone else host."
                             if ph.symmetric else ""))
    return info


def stop_hosting(info):
    if not info:
        return
    info["stop"].set()
    if info.get("punch"):
        info["punch"].close()
    if info.get("mapper"):
        info["mapper"].remove_all()
    info["server"].stop()
