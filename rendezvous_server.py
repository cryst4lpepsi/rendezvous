#!/usr/bin/env python3
"""
rendezvous_server.py - the "introducer" and fallback relay.

WHY A SERVER AT ALL?
  Machines behind home routers (NATs) cannot simply connect to each other:
  none of them knows the others' PUBLIC address, and each NAT drops
  unsolicited inbound packets. So every peer first talks OUT to this server,
  which has a public IP. When a UDP packet leaves a NAT, the NAT creates a
  temporary mapping  (private ip:port) <-> (public ip:port).  The server sees
  the packet arrive from that PUBLIC ip:port, which is exactly the address the
  other peers need to aim at. The server tells every peer in a room about every
  other peer ("introduction"), and each pair then tries to punch a hole.

  If direct punching fails for a pair (symmetric NAT, strict firewall), the
  server also acts as a RELAY for that pair: it forwards packets between them.
  This always works because every peer already has an open NAT mapping towards
  the server (kept alive by re-registering every couple of seconds).

  The server also hands out a VIRTUAL IP (10.77.0.x by default) to each peer in
  a room. Those are the addresses of the virtual LAN adapters.

PROTOCOL
  Control messages are JSON, one per datagram (first byte is "{"):
    peer -> server  {"t":"register", "room", "id", "name", "local":[ip,port], "want_ip"}
    server -> peer  {"t":"registered", "public":[ip,port], "vip", "prefix"}
    server -> peer  {"t":"peer", "id", "name", "public", "local", "vip"}  <- one per other peer
    server -> peer  {"t":"peer_left", "id"}
    peer -> server  {"t":"relay", "room", "from", "to", "inner":{...}}
    server -> peer  {"t":"relayed", "from", "inner":{...}}
    peer -> server  {"t":"bye", "room", "id"}
    server -> peer  {"t":"error", "reason"}

  Virtual-LAN data is binary, to keep it small and fast (no JSON, no base64):
    peer -> server  0x02 | to_id (3 bytes) | ip packet
    server -> peer  0x03 | from_id (3 bytes) | ip packet
  The server works out who sent a 0x02 packet from its source address, so a
  packet can only be relayed on behalf of a registered peer.

Also serves a tiny read-only HTTP status page (JSON) for debugging.

Pure standard library: copy this single file to any box with Python 3.8+ and run it.
"""

import argparse
import ipaddress
import json
import logging
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("server")

PEER_TIMEOUT = 10.0     # seconds without a register/relay before a peer is forgotten
MAX_PEERS_PER_ROOM = 8
MAX_DATAGRAM = 65535

BIN_RELAY = 0x02        # peer -> server
BIN_RELAYED = 0x03      # server -> peer

# STUN (RFC 5389) binding requests: "what address do my packets come from?"
# Used when a player hosts from behind CGNAT (see hosting.py).
STUN_MAGIC = b"\x21\x12\xa4\x42"


def stun_request(tid):
    return b"\x00\x01\x00\x00" + STUN_MAGIC + tid


def parse_stun_response(data):
    """Returns (transaction_id, (ip, port)) for a STUN success response, else None."""
    if len(data) < 20 or data[0:2] != b"\x01\x01" or data[4:8] != STUN_MAGIC:
        return None
    tid, pos, end = data[8:20], 20, 20 + int.from_bytes(data[2:4], "big")
    mapped = None
    while pos + 4 <= min(end, len(data)):
        atype, alen = int.from_bytes(data[pos:pos + 2], "big"), int.from_bytes(data[pos + 2:pos + 4], "big")
        val = data[pos + 4:pos + 4 + alen]
        if atype in (0x0020, 0x8020) and len(val) >= 8 and val[1] == 1:  # XOR-MAPPED-ADDRESS, IPv4
            port = int.from_bytes(val[2:4], "big") ^ 0x2112
            ip = bytes(a ^ b for a, b in zip(val[4:8], STUN_MAGIC))
            return tid, (socket.inet_ntoa(ip), port)
        if atype == 0x0001 and len(val) >= 8 and val[1] == 1:  # MAPPED-ADDRESS (old servers)
            mapped = (socket.inet_ntoa(val[4:8]), int.from_bytes(val[2:4], "big"))
        pos += 4 + alen + (-alen % 4)
    return (tid, mapped) if mapped else None


def disable_udp_connreset(sock):
    """
    Windows quirk: if we send to a port that answers with ICMP "port
    unreachable" (a peer that just exited, a punch at a port that isn't open
    yet), the NEXT recvfrom() on this socket fails with WSAECONNRESET.
    Turning off SIO_UDP_CONNRESET makes UDP behave like it does on Linux/macOS.

    Python's socket.ioctl() only accepts a few control codes and this isn't
    one of them, so we call WSAIoctl from ws2_32.dll directly.
    """
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    SIO_UDP_CONNRESET = 0x9800000C  # _WSAIOW(IOC_VENDOR, 12)
    try:
        ws2 = ctypes.WinDLL("ws2_32")
        ws2.WSAIoctl.argtypes = [ctypes.c_size_t, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                 ctypes.c_void_p, ctypes.c_void_p]
        ws2.WSAIoctl.restype = ctypes.c_int
        flag = wintypes.BOOL(False)
        returned = wintypes.DWORD(0)
        if ws2.WSAIoctl(sock.fileno(), SIO_UDP_CONNRESET, ctypes.byref(flag), ctypes.sizeof(flag),
                        None, 0, ctypes.byref(returned), None, None) != 0:
            raise OSError(ws2.WSAGetLastError(), "WSAIoctl(SIO_UDP_CONNRESET) failed")
    except (OSError, AttributeError) as e:
        # Not fatal: the receive loops also tolerate ConnectionResetError.
        log.warning("could not disable UDP connection-reset errors: %s", e)


def make_udp_socket(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    disable_udp_connreset(sock)
    sock.bind((host, port))
    return sock


def _private(ip):
    a = ipaddress.ip_address(ip)
    return a.is_private or a.is_loopback or a.is_link_local


class PeerRecord:
    def __init__(self, pid, name, public, local, vip):
        self.id = pid
        self.raw_id = bytes.fromhex(pid)  # 3 bytes, used in binary frames
        self.name = name
        self.public = public            # (ip, port) as WE observe it = their NAT's public mapping
        self.local = local              # (ip, port) the peer reports for itself (LAN address)
        self.vip = vip                  # virtual LAN address we assigned
        self.first_seen = time.time()
        self.last_seen = time.time()

    def info(self, public=None):
        return {"t": "peer", "id": self.id, "name": self.name, "vip": self.vip,
                "public": list(public or self.public), "local": list(self.local) if self.local else None}


class Room:
    def __init__(self, code):
        self.code = code
        self.peers = {}  # id -> PeerRecord
        self.relayed_packets = 0
        self.relayed_bytes = 0

    def others(self, pid):
        return [p for p in self.peers.values() if p.id != pid]

    def by_raw_id(self, raw):
        for p in self.peers.values():
            if p.raw_id == raw:
                return p
        return None


class RendezvousServer:
    def __init__(self, host, port, subnet):
        self.sock = make_udp_socket(host, port)
        self.subnet = ipaddress.ip_network(subnet)
        self.rooms = {}
        self.by_addr = {}  # public (ip, port) -> (Room, PeerRecord), for binary relay
        self.lock = threading.Lock()   # the HTTP status thread reads self.rooms
        self.started = time.time()
        self._last_expire = 0.0
        self.running = True
        # Used when a player hosts the server inside the app (see hosting.py):
        self.only_room = None   # serve just this network
        self.public_ip = None   # the host's public IP, to describe peers that sit on the host's LAN
        self.overrides = {}     # port of a peer on this machine -> its port-forwarded (ip, port)
        self._stun_waiting = {}  # transaction id -> [threading.Event, result]

    # ------------------------------------------------------------------ io
    def send(self, msg, addr):
        self.send_raw(json.dumps(msg, separators=(",", ":")).encode(), addr)

    def send_raw(self, data, addr):
        try:
            self.sock.sendto(data, addr)
        except OSError as e:
            log.debug("send to %s failed: %s", addr, e)

    def serve_forever(self):
        self.sock.settimeout(1.0)
        log.info("UDP rendezvous/relay listening on %s:%d, virtual LAN %s",
                 *self.sock.getsockname(), self.subnet)
        while self.running:
            try:
                data, addr = self.sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                with self.lock:
                    self.expire()
                continue
            except ConnectionResetError:
                continue  # stray ICMP on Windows; harmless
            except OSError:
                if not self.running:
                    break
                raise
            stun = parse_stun_response(data) if data[:1] == b"\x01" else None
            if stun:
                waiter = self._stun_waiting.get(stun[0])
                if waiter:
                    waiter[1] = stun[1]
                    waiter[0].set()
                continue
            with self.lock:
                if data and data[0] == BIN_RELAY:
                    self.on_binary_relay(data, addr)
                else:
                    try:
                        msg = json.loads(data)
                        if not isinstance(msg, dict):
                            raise ValueError("not an object")
                    except ValueError:
                        log.debug("drop: unparseable datagram from %s", addr)
                        continue
                    self.handle(msg, addr, len(data))
                self.expire()

    def stun(self, server_addr, timeout=2.0):
        """Ask a STUN server, from this server's own socket, which public
        address our packets come from. Called from another thread."""
        import os
        tid = os.urandom(12)
        waiter = self._stun_waiting[tid] = [threading.Event(), None]
        try:
            for wait in (timeout / 3, timeout * 2 / 3):  # one resend
                self.sock.sendto(stun_request(tid), server_addr)
                if waiter[0].wait(wait):
                    return waiter[1]
        except OSError as e:
            log.debug("STUN to %s failed: %s", server_addr, e)
        finally:
            self._stun_waiting.pop(tid, None)
        return None

    def punch_toward(self, addr, count=20, every=0.3):
        """Hole punching for a host behind CGNAT: a player who wants in told us
        its public address (through the mailbox); sending to it opens our NAT
        for that player's packets, while its own packets open its side."""
        def run():
            for _ in range(count):
                if not self.running:
                    return
                self.send({"t": "hi"}, addr)
                time.sleep(every)
        threading.Thread(target=run, name="punch-toward", daemon=True).start()

    # ------------------------------------------------------------ handlers
    def handle(self, msg, addr, size):
        t = msg.get("t")
        if t == "register":
            self.on_register(msg, addr)
        elif t == "relay":
            self.on_relay(msg, addr, size)
        elif t == "bye":
            self.on_bye(msg, addr)
        elif t == "find":
            # LAN discovery (see hosting.find_on_lan): answer if we host that network.
            if self.only_room is not None and msg.get("room") == self.only_room:
                self.send({"t": "here", "room": self.only_room}, addr)
        else:
            log.debug("drop: unknown message type %r from %s", t, addr)

    def endpoint_for(self, rec, viewer=None):
        """
        The address other players should use to reach `rec`. Normally that is
        simply where its packets came from. But when the server runs inside the
        host's app, the host (and anyone on the host's LAN) registers from a
        local address that means nothing to players outside, so we hand those
        players the host's public IP instead (and the forwarded port, if UPnP
        set one up for it).
        """
        ip, port = rec.public
        if not self.public_ip or not _private(ip) or (viewer is not None and _private(viewer.public[0])):
            return rec.public
        if ipaddress.ip_address(ip).is_loopback and port in self.overrides:
            return self.overrides[port]
        return (self.public_ip, port)

    def assign_vip(self, room, want):
        """Hand out the lowest free host address, or the one the peer asks for
        (it remembers its last address so players keep the same IP)."""
        taken = {p.vip for p in room.peers.values()}
        hosts = [str(h) for h in self.subnet.hosts()]
        if want in hosts and want not in taken:
            return want
        for h in hosts:
            if h not in taken:
                return h
        return None

    def on_register(self, msg, addr):
        code, pid = str(msg.get("room", "")), str(msg.get("id", ""))
        try:
            if not code or len(bytes.fromhex(pid)) != 3:
                raise ValueError
        except ValueError:
            return self.send({"t": "error", "reason": "register needs a room and a 6-hex-digit id"}, addr)
        local = tuple(msg["local"]) if msg.get("local") else None
        if self.only_room is not None and code != self.only_room:
            return self.send({"t": "error", "reason": "wrong network name or password"}, addr)
        room = self.rooms.setdefault(code, Room(code))
        rec = room.peers.get(pid)

        if rec is None:
            if len(room.peers) >= MAX_PEERS_PER_ROOM:
                log.warning("room %r full, rejecting %s from %s", code, pid, addr)
                return self.send({"t": "error", "reason": f"network is full ({MAX_PEERS_PER_ROOM} players)"}, addr)
            vip = self.assign_vip(room, msg.get("want_ip"))
            rec = room.peers[pid] = PeerRecord(pid, str(msg.get("name") or pid)[:32], addr, local, vip)
            self.by_addr[addr] = (room, rec)
            log.info("[%s] REGISTER %s (%s) public=%s:%d local=%s vip=%s",
                     code, rec.name, pid, addr[0], addr[1], local, vip)
            changed = True
        else:
            # Same peer re-registering (keepalive). If its public address moved,
            # its NAT re-mapped it (or it switched networks) - tell the others.
            changed = rec.public != addr or rec.local != local
            if changed:
                log.info("[%s] %s endpoint changed %s -> %s", code, rec.name, rec.public, addr)
                self.by_addr.pop(rec.public, None)
                self.by_addr[addr] = (room, rec)
            rec.public, rec.local = addr, local
            rec.last_seen = time.time()
            log.debug("[%s] keepalive register from %s", code, rec.name)

        # Tell the peer what its public endpoint looks like from the outside,
        # and which virtual IP it owns.
        self.send({"t": "registered", "public": list(self.endpoint_for(rec)), "room": code,
                   "vip": rec.vip, "prefix": self.subnet.prefixlen}, addr)

        # Introduction: give each peer every other peer's endpoints. We re-send
        # on every register so a lost packet is self-healing.
        for other in room.others(pid):
            self.send(other.info(self.endpoint_for(other, rec)), addr)
            if changed:
                log.info("[%s] INTRODUCE %s <-> %s", code, rec.name, other.name)
                self.send(rec.info(self.endpoint_for(rec, other)), other.public)

    def _sender(self, code, pid, addr):
        room = self.rooms.get(code)
        sender = room.peers.get(pid) if room else None
        # Simple anti-abuse check: only relay for a registered peer, and only
        # if the packet really comes from the address it registered from.
        if sender is None or sender.public != addr:
            return None, None
        sender.last_seen = time.time()
        return room, sender

    def on_relay(self, msg, addr, size):
        room, sender = self._sender(str(msg.get("room", "")), str(msg.get("from", "")), addr)
        if sender is None:
            log.debug("drop relay from %s: not a registered peer", addr)
            return
        out = json.dumps({"t": "relayed", "from": sender.id, "inner": msg.get("inner")},
                         separators=(",", ":")).encode()
        to = msg.get("to")
        targets = [room.peers[to]] if to in room.peers else ([] if to else room.others(sender.id))
        for other in targets:
            if other.id == sender.id:
                continue
            self.send_raw(out, other.public)
            room.relayed_packets += 1
            room.relayed_bytes += size
            log.debug("[%s] RELAY %d bytes %s -> %s (%s)", room.code, size, sender.name, other.name,
                      (msg.get("inner") or {}).get("t"))

    def on_binary_relay(self, data, addr):
        entry = self.by_addr.get(addr)
        if entry is None or len(data) < 5:
            log.debug("drop binary relay from %s: not a registered peer", addr)
            return
        room, sender = entry
        sender.last_seen = time.time()
        target = room.by_raw_id(data[1:4])
        if target is None or target is sender:
            return
        self.send_raw(bytes([BIN_RELAYED]) + sender.raw_id + data[4:], target.public)
        room.relayed_packets += 1
        room.relayed_bytes += len(data)

    def on_bye(self, msg, addr):
        code, pid = str(msg.get("room", "")), str(msg.get("id", ""))
        room = self.rooms.get(code)
        if room and pid in room.peers and room.peers[pid].public == addr:
            self.remove(room, pid, "said bye")

    # ---------------------------------------------------------- lifecycle
    def remove(self, room, pid, why):
        rec = room.peers.pop(pid)
        if self.by_addr.get(rec.public, (None, None))[1] is rec:
            del self.by_addr[rec.public]
        log.info("[%s] LEAVE %s (%s)", room.code, rec.name, why)
        for other in room.peers.values():
            self.send({"t": "peer_left", "id": pid}, other.public)
        if not room.peers:
            del self.rooms[room.code]

    def expire(self):
        now = time.time()
        if now - self._last_expire < 1.0:
            return
        self._last_expire = now
        for room in list(self.rooms.values()):
            for pid, rec in list(room.peers.items()):
                if now - rec.last_seen > PEER_TIMEOUT:
                    self.remove(room, pid, f"timed out after {PEER_TIMEOUT:.0f}s")

    def status(self):
        with self.lock:
            return {
                "uptime_s": round(time.time() - self.started),
                "subnet": str(self.subnet),
                "rooms": {
                    # room codes double as passwords, so only show the network name part
                    code.split("/")[0]: {
                        "relayed_packets": r.relayed_packets,
                        "relayed_bytes": r.relayed_bytes,
                        "peers": [{"id": p.id, "name": p.name, "vip": p.vip, "public": "%s:%d" % p.public,
                                   "local": "%s:%d" % p.local if p.local else None,
                                   "last_seen_s_ago": round(time.time() - p.last_seen, 1)}
                                  for p in r.peers.values()],
                    } for code, r in self.rooms.items()
                },
            }


def start_http(server, host, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(server.status(), indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info("HTTP status page on http://%s:%d/", host, port)


def main():
    ap = argparse.ArgumentParser(description="Rendezvous + relay server for peer.py")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=9000, help="UDP port (default 9000)")
    ap.add_argument("--http-port", type=int, default=9001, help="HTTP status port (default 9001, 0 = off)")
    ap.add_argument("--subnet", default="10.77.0.0/24", help="virtual LAN subnet (default 10.77.0.0/24)")
    ap.add_argument("--verbose", "-v", action="store_true", help="log every packet decision")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s.%(msecs)03d [server] %(message)s", datefmt="%H:%M:%S")
    server = RendezvousServer(args.host, args.port, args.subnet)
    if args.http_port:
        start_http(server, args.host, args.http_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
