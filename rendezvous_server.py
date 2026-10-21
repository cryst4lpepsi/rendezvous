#!/usr/bin/env python3
"""
rendezvous_server.py - the "introducer" and fallback relay.

WHY A SERVER AT ALL?
  Two machines behind home routers (NATs) cannot simply connect to each other:
  neither knows the other's PUBLIC address, and each NAT drops unsolicited
  inbound packets. So both peers first talk OUT to this server, which has a
  public IP. When a UDP packet leaves a NAT, the NAT creates a temporary
  mapping  (private ip:port) <-> (public ip:port).  The server sees the packet
  arrive from that PUBLIC ip:port, which is exactly the address the other peer
  needs to aim at. The server just tells each peer the other's public
  endpoint ("introduction"), and the peers then try to punch a hole directly.

  If direct punching fails (e.g. symmetric NAT, strict firewall), the server
  also acts as a RELAY: a peer wraps a packet in {"t":"relay", ...}, the server
  unwraps it and forwards it to the other peer in the same room. This always
  works because both peers already have an open NAT mapping towards the server
  (kept alive by re-registering every couple of seconds).

PROTOCOL (JSON over UDP, one message per datagram)
  peer -> server  {"t":"register", "room", "id", "name", "local":[ip,port]}
  server -> peer  {"t":"registered", "public":[ip,port]}   <- your public endpoint
  server -> peer  {"t":"peer", "id", "name", "public", "local"} <- the other peer
  server -> peer  {"t":"peer_left", "id"}
  peer -> server  {"t":"relay", "room", "from", "inner":{...}}
  server -> peer  {"t":"relayed", "from", "inner":{...}}
  peer -> server  {"t":"bye", "room", "id"}
  server -> peer  {"t":"error", "reason"}

Also serves a tiny read-only HTTP status page (JSON) for debugging.

Pure standard library: copy this single file to any box with Python 3.8+ and run it.
"""

import argparse
import json
import logging
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("server")

PEER_TIMEOUT = 10.0     # seconds without a register/relay before a peer is forgotten
MAX_PEERS_PER_ROOM = 2  # this tool is strictly point-to-point
MAX_DATAGRAM = 65535


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


class PeerRecord:
    def __init__(self, pid, name, public, local):
        self.id = pid
        self.name = name
        self.public = public            # (ip, port) as WE observe it = their NAT's public mapping
        self.local = local              # (ip, port) the peer reports for itself (LAN address)
        self.first_seen = time.time()
        self.last_seen = time.time()

    def info(self):
        return {"t": "peer", "id": self.id, "name": self.name,
                "public": list(self.public), "local": list(self.local) if self.local else None}


class Room:
    def __init__(self, code):
        self.code = code
        self.peers = {}  # id -> PeerRecord
        self.relayed_packets = 0
        self.relayed_bytes = 0

    def others(self, pid):
        return [p for p in self.peers.values() if p.id != pid]


class RendezvousServer:
    def __init__(self, host, port):
        self.sock = make_udp_socket(host, port)
        self.rooms = {}
        self.lock = threading.Lock()   # the HTTP status thread reads self.rooms
        self.started = time.time()
        self._last_expire = 0.0

    # ------------------------------------------------------------------ io
    def send(self, msg, addr):
        try:
            self.sock.sendto(json.dumps(msg, separators=(",", ":")).encode(), addr)
        except OSError as e:
            log.debug("send to %s failed: %s", addr, e)

    def serve_forever(self):
        self.sock.settimeout(1.0)
        log.info("UDP rendezvous/relay listening on %s:%d", *self.sock.getsockname())
        while True:
            try:
                data, addr = self.sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                self.expire()
                continue
            except ConnectionResetError:
                continue  # stray ICMP on Windows; harmless
            try:
                msg = json.loads(data)
                if not isinstance(msg, dict):
                    raise ValueError("not an object")
            except ValueError:
                log.debug("drop: non-JSON datagram from %s", addr)
                continue
            with self.lock:
                self.handle(msg, addr, len(data))
                self.expire()

    # ------------------------------------------------------------ handlers
    def handle(self, msg, addr, size):
        t = msg.get("t")
        if t == "register":
            self.on_register(msg, addr)
        elif t == "relay":
            self.on_relay(msg, addr, size)
        elif t == "bye":
            self.on_bye(msg, addr)
        else:
            log.debug("drop: unknown message type %r from %s", t, addr)

    def on_register(self, msg, addr):
        code, pid = str(msg.get("room", "")), str(msg.get("id", ""))
        if not code or not pid:
            return self.send({"t": "error", "reason": "register needs room and id"}, addr)
        local = tuple(msg["local"]) if msg.get("local") else None
        room = self.rooms.setdefault(code, Room(code))
        rec = room.peers.get(pid)

        if rec is None:
            if len(room.peers) >= MAX_PEERS_PER_ROOM:
                log.warning("room %r full, rejecting %s from %s", code, pid, addr)
                return self.send({"t": "error", "reason": f"room '{code}' already has 2 peers"}, addr)
            rec = room.peers[pid] = PeerRecord(pid, str(msg.get("name") or pid), addr, local)
            log.info("[%s] REGISTER %s (%s) public=%s:%d local=%s",
                     code, rec.name, pid, addr[0], addr[1], local)
            changed = True
        else:
            # Same peer re-registering (keepalive). If its public address moved,
            # its NAT re-mapped it (or it switched networks) - tell the other side.
            changed = rec.public != addr or rec.local != local
            if changed:
                log.info("[%s] %s endpoint changed %s -> %s", code, rec.name, rec.public, addr)
            rec.public, rec.local = addr, local
            rec.last_seen = time.time()
            log.debug("[%s] keepalive register from %s", code, rec.name)

        # Tell the peer what its public endpoint looks like from the outside.
        self.send({"t": "registered", "public": list(addr), "room": code}, addr)

        # Introduction: give each peer the other's endpoints. We re-send the
        # other peer's info on every register so a lost packet is self-healing.
        for other in room.others(pid):
            self.send(other.info(), addr)
            if changed:
                log.info("[%s] INTRODUCE %s <-> %s", code, rec.name, other.name)
                self.send(rec.info(), other.public)

    def on_relay(self, msg, addr, size):
        code, pid = str(msg.get("room", "")), str(msg.get("from", ""))
        room = self.rooms.get(code)
        sender = room.peers.get(pid) if room else None
        # Simple anti-abuse check: only relay for a registered peer, and only
        # if the packet really comes from the address it registered from.
        if sender is None or sender.public != addr:
            log.debug("drop relay: %s from %s is not a registered peer of room %r", pid, addr, code)
            return
        sender.last_seen = time.time()
        out = {"t": "relayed", "from": pid, "inner": msg.get("inner")}
        for other in room.others(pid):
            self.send(out, other.public)
            room.relayed_packets += 1
            room.relayed_bytes += size
            log.debug("[%s] RELAY %d bytes %s -> %s (%s)", code, size, sender.name, other.name,
                      (msg.get("inner") or {}).get("t"))

    def on_bye(self, msg, addr):
        code, pid = str(msg.get("room", "")), str(msg.get("id", ""))
        room = self.rooms.get(code)
        if room and pid in room.peers and room.peers[pid].public == addr:
            self.remove(room, pid, "said bye")

    # ---------------------------------------------------------- lifecycle
    def remove(self, room, pid, why):
        rec = room.peers.pop(pid)
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
                "rooms": {
                    code: {
                        "relayed_packets": r.relayed_packets,
                        "relayed_bytes": r.relayed_bytes,
                        "peers": [{"id": p.id, "name": p.name, "public": "%s:%d" % p.public,
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
    ap.add_argument("--verbose", "-v", action="store_true", help="log every packet decision")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s.%(msecs)03d [server] %(message)s", datefmt="%H:%M:%S")
    server = RendezvousServer(args.host, args.port)
    if args.http_port:
        start_http(server, args.host, args.http_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
