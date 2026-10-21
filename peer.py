#!/usr/bin/env python3
"""
peer.py - one end of the tunnel, plus the live dashboard (http://localhost:8080).

What happens, in order:
  1. DISCOVERING  We register with the rendezvous server. The server replies with
                  our PUBLIC endpoint (what our NAT turned us into) and, once the
                  other peer is in the same room, the other peer's endpoints.
  2. PUNCHING     Both peers fire small "punch" packets at each other's public
                  (and LAN) endpoint at the same time. See _tick_punch() for why
                  this opens a path through both NATs.
  3. DIRECT       A packet from the peer arrived straight from the peer (not via
                  the server). The hole is open; traffic flows peer-to-peer.
  4. RELAY        Punching timed out. Traffic is wrapped and sent via the server,
                  which forwards it. Slower, but works through any NAT.
  5. RECONNECTING We were DIRECT but keepalives stopped arriving. Traffic moves
                  to the relay at once while we try to punch again; we end up
                  back in DIRECT (path restored) or RELAY (fallback).

Everything runs on ONE UDP socket. That matters: the NAT mapping the server
observed belongs to this socket's port, so punch packets must leave from the
very same socket or they would get a different public port.
"""

import argparse
import asyncio
import base64
import collections
import json
import logging
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("peer")

DISCOVERING = "DISCOVERING"
PUNCHING = "PUNCHING"
DIRECT = "DIRECT"
RELAY = "RELAY"
RECONNECTING = "RECONNECTING"

REGISTER_INTERVAL = 2.0    # re-register: keeps our NAT mapping to the server alive
KEEPALIVE_INTERVAL = 1.0   # ping the peer on the active path
DIRECT_DEAD_AFTER = 3.5    # no direct packet for this long => direct path is dead
PUNCH_INTERVAL = 0.25      # one punch burst every 250 ms while punching
SERVER_DEAD_AFTER = 6.0
TICK = 0.1

DASHBOARD_FILE = Path(__file__).with_name("dashboard.html")


def now():
    return time.monotonic()


def make_udp_socket(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if sys.platform == "win32":
        # Without this, an ICMP "port unreachable" (common while punching at a
        # port that isn't open yet) makes Windows fail the next recv with
        # WSAECONNRESET. See rendezvous_server.py for the same fix.
        sock.ioctl(socket.SIO_UDP_CONNRESET, False)
    sock.bind((host, port))
    sock.setblocking(False)
    return sock


def resolve(hostport, default_port):
    host, _, port = hostport.rpartition(":") if ":" in hostport else (hostport, "", default_port)
    info = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_DGRAM)
    return info[0][4][:2]


def guess_lan_ip(server_addr):
    # "Connecting" a UDP socket sends nothing; it just makes the OS pick the
    # outgoing interface, whose address is our LAN IP. Peers on the same LAN
    # can reach each other on this address even if their router can't hairpin.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(server_addr)
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def fmt(addr):
    return f"{addr[0]}:{addr[1]}" if addr else "-"


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, on_packet):
        self.on_packet = on_packet

    def datagram_received(self, data, addr):
        self.on_packet(data, addr)

    def error_received(self, exc):
        log.debug("socket error (ignored): %s", exc)


class Peer:
    def __init__(self, args):
        self.args = args
        self.server_addr = resolve(args.server, 9000)
        self.room = args.room
        self.my_id = secrets.token_hex(3)
        self.name = args.name or f"peer-{self.my_id}"
        self.punch_timeout = args.punch_timeout
        self.relay_retry = args.relay_retry

        self.state = DISCOVERING
        self.state_since = now()
        self.peer = None           # {"id","name","public":(ip,port),"local":(ip,port)}
        self.direct_addr = None    # the peer address that actually answered a punch
        self.public_addr = None    # our public endpoint, as reported by the server
        self.local_addr = None

        # demo switches
        self.forced_relay = False      # operator pinned the path to RELAY
        self.blackhole = args.block_direct  # simulate a dead direct path: drop all non-server packets

        self.punch_round_start = 0.0
        self.punch_round_attempts = 0
        self.punch_attempts_total = 0
        self.last_punch = 0.0

        self.last_direct_rx = 0.0
        self.last_relay_rx = 0.0
        self.last_server_rx = 0.0
        self.server_ok = None
        self.relay_silent_warned = False
        self.last_register = 0.0
        self.last_ping = 0.0
        self.ping_seq = 0
        self.pending_pings = {}        # seq -> (sent_at, path)
        self.rtt_ms = None
        self.rtt_path = None
        self.rtt_history = collections.deque(maxlen=60)  # (wall_time, rtt_ms, path)

        self.stats = collections.Counter()
        self.events = collections.deque(maxlen=300)
        self.chat = collections.deque(maxlen=100)
        self.event_seq = 0
        self.seen_ctl = collections.deque(maxlen=50)
        self.clients = set()           # one asyncio.Queue per open dashboard

        self.transport = None
        self.app_transport = None
        self.app_reply_addr = None     # passthrough: where to send tunneled app packets
        self._tasks = []
        self._last_push = 0.0
        self.started = now()

    # ================================================================ startup
    async def start(self):
        loop = asyncio.get_running_loop()
        sock = make_udp_socket(self.args.bind, self.args.udp_port)
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: _Proto(self._on_datagram), sock=sock)
        port = sock.getsockname()[1]
        self.local_addr = (guess_lan_ip(self.server_addr), port)
        self.event("info", f"{self.name} up: UDP socket bound to port {port}, "
                           f"room '{self.room}', rendezvous {fmt(self.server_addr)}")

        if self.args.app_listen or self.args.app_target:
            await self._start_passthrough(loop)
        if self.blackhole:
            self.event("warn", "--block-direct: all direct packets will be dropped (relay only)")

        self._register()
        self._tasks.append(asyncio.create_task(self._ticker()))

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        if self.transport:
            self._send_raw({"t": "bye", "room": self.room, "id": self.my_id}, self.server_addr)
            self.transport.close()

    async def _start_passthrough(self, loop):
        # Passthrough: a plain UDP app (game, iperf, netcat) talks to a local
        # port; we carry its datagrams through the tunnel to the other side.
        if self.args.app_listen:
            sock = make_udp_socket("127.0.0.1", self.args.app_listen)
            where = f"listening for app traffic on 127.0.0.1:{self.args.app_listen}"
        else:
            sock = make_udp_socket("0.0.0.0", 0)
            self.app_reply_addr = resolve(self.args.app_target, 0)
            where = f"delivering tunneled app traffic to {self.args.app_target}"
        self.app_transport, _ = await loop.create_datagram_endpoint(
            lambda: _Proto(self._on_app_datagram), sock=sock)
        self.event("info", f"passthrough: {where}")

    # ============================================================ event bus
    def event(self, level, msg):
        """Timestamped event: printed to the console AND pushed to dashboards."""
        self.event_seq += 1
        ev = {"type": "event", "id": self.event_seq, "ts": time.time(), "level": level, "msg": msg}
        self.events.append(ev)
        log.info("%-5s %s", level.upper(), msg)
        self.broadcast(ev)

    def broadcast(self, obj):
        for q in list(self.clients):
            try:
                q.put_nowait(obj)
            except asyncio.QueueFull:
                pass  # slow dashboard; it will resync from the next state push

    def push_state(self):
        self._last_push = now()
        self.broadcast(self.snapshot())

    def active_path(self):
        if self.peer is None:
            return None
        return "direct" if self.state == DIRECT else "relay"

    def snapshot(self):
        t = now()
        p = self.peer
        return {
            "type": "state",
            "state": self.state,
            "path": self.active_path(),
            "in_state_s": round(t - self.state_since, 1),
            "room": self.room,
            "me": {"id": self.my_id, "name": self.name,
                   "public": fmt(self.public_addr), "local": fmt(self.local_addr)},
            "peer": None if p is None else {"id": p["id"], "name": p["name"],
                                            "public": fmt(p["public"]), "local": fmt(p["local"])},
            "direct_addr": fmt(self.direct_addr),
            "server": fmt(self.server_addr),
            "server_ok": self.server_ok,
            "rtt_ms": self.rtt_ms,
            "rtt_path": self.rtt_path,
            "rtt_history": list(self.rtt_history),
            "stats": dict(self.stats),
            "punch": {"round": self.punch_round_attempts, "total": self.punch_attempts_total,
                      "elapsed": round(t - self.punch_round_start, 2) if self.state in (PUNCHING, RECONNECTING) else None,
                      "timeout": self.punch_timeout},
            "direct_silence_s": round(t - self.last_direct_rx, 2) if self.last_direct_rx else None,
            "dead_after": DIRECT_DEAD_AFTER,
            "forced_relay": self.forced_relay,
            "blackhole": self.blackhole,
        }

    # ========================================================= state machine
    def set_state(self, new, reason, level="info"):
        if new == self.state:
            return
        old, self.state, self.state_since = self.state, new, now()
        if new in (PUNCHING, RECONNECTING):
            self.punch_round_start = now()
            self.punch_round_attempts = 0
            self.last_punch = 0.0
        self.relay_silent_warned = False
        if new == DIRECT:
            self.last_direct_rx = now()
        self.event(level, f"{old} -> {new}: {reason}")
        self.broadcast({"type": "transition", "from": old, "to": new})
        self.push_state()

    def start_punching(self, reason, notify=True, reconnect=False):
        """Begin a punch round. Hole punching only works if BOTH sides send at
        roughly the same time, so unless the peer asked us to do this, we ask it
        to punch too (via the relay, which always works)."""
        if self.peer is None:
            return
        target = RECONNECTING if reconnect else PUNCHING
        if self.state == target:
            self.punch_round_start, self.punch_round_attempts = now(), 0
        else:
            self.set_state(target, reason, "warn" if reconnect else "info")
        if notify:
            self._send_ctl("punch_now")

    def _direct_evidence(self, addr, why):
        """A valid packet from the peer arrived over the DIRECT path."""
        if self.forced_relay:
            return
        if self.state in (PUNCHING, RECONNECTING, RELAY):
            # Peer-reflexive address: we lock onto whatever address the packet
            # actually came from, which may differ from what the server told us
            # (e.g. the peer is on our LAN, or its NAT chose another port).
            self.direct_addr = addr
            restored = self.state == RECONNECTING
            self.set_state(DIRECT, f"{why} from {fmt(addr)} - "
                                   f"{'direct path restored' if restored else 'hole punched, traffic now peer-to-peer'}",
                           "good")
        elif self.state == DIRECT and addr != self.direct_addr:
            self.event("info", f"peer's direct address moved {fmt(self.direct_addr)} -> {fmt(addr)}")
            self.direct_addr = addr

    async def _ticker(self):
        while True:
            try:
                self._tick()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(TICK)

    def _tick(self):
        t = now()
        if t - self.last_register >= REGISTER_INTERVAL:
            self._register()

        # Is the rendezvous server still answering?
        server_ok = bool(self.last_server_rx) and (t - self.last_server_rx) < SERVER_DEAD_AFTER
        if server_ok and self.server_ok is not True:
            if self.server_ok is False:
                self.event("good", "rendezvous server reachable again")
            self.server_ok = True
        elif not server_ok and self.server_ok is not False:
            if self.server_ok is True or t - self.started > SERVER_DEAD_AFTER:
                self.event("bad", f"rendezvous server {fmt(self.server_addr)} not responding")
                self.server_ok = False

        if self.peer is not None:
            if self.state in (PUNCHING, RECONNECTING):
                self._tick_punch(t)
            elif self.state == DIRECT:
                # Keepalive watchdog: the peer pings us every second over the
                # direct path. Silence for DIRECT_DEAD_AFTER means the NAT
                # mapping expired, a router rebooted, wifi changed, ... Move
                # traffic to the relay immediately and try to punch again.
                silence = t - self.last_direct_rx
                if silence > DIRECT_DEAD_AFTER:
                    self.start_punching(f"keepalive lost: no direct packet for {silence:.1f}s, "
                                        f"traffic moved to relay while re-punching", reconnect=True)
            elif self.state == RELAY:
                if (not self.forced_relay and self.relay_retry > 0
                        and t - self.state_since > self.relay_retry):
                    self.start_punching(f"periodic retry: {self.relay_retry:.0f}s on relay, trying direct again")
                # Measure relay silence from when we switched, not from the last
                # (possibly ancient) relayed packet.
                if (t - max(self.last_relay_rx, self.state_since) > SERVER_DEAD_AFTER
                        and not self.relay_silent_warned):
                    self.relay_silent_warned = True
                    self.event("bad", "relay path silent: no packet from peer via server")

            if t - self.last_ping >= KEEPALIVE_INTERVAL:
                self._send_ping()

        for seq, (sent, _) in list(self.pending_pings.items()):
            if t - sent > 5:
                del self.pending_pings[seq]

        if t - self._last_push >= 0.25:
            self.push_state()

    def _tick_punch(self, t):
        """
        UDP HOLE PUNCHING, the core trick.

        A typical NAT lets an inbound packet in only if it matches a mapping
        created by an OUTBOUND packet: "I sent to X:x from my port p, so I'll
        accept packets from X:x to p for a while".

        So: peer A sends a punch to B's public endpoint. B's NAT has never seen
        A, so it drops it. BUT the act of sending created a mapping in A's NAT
        that now allows packets from B. Meanwhile B does the same towards A.
        Whichever punch arrives second finds the other NAT already open, gets
        through, and is answered with punch_ack. Both sides then see a packet
        that came directly from the other peer: the path is open.

        It works for "cone" NATs, where our public ip:port is the same no
        matter who we send to (so the endpoint the server saw is valid for the
        peer too). It fails for symmetric NATs, which pick a new public port
        for every destination; then we time out and use the relay.

        We punch every candidate: the public endpoint (different networks),
        the LAN endpoint (same network, router may not support hairpinning),
        and the last address that worked (fast path on reconnect).
        """
        if t - self.last_punch >= PUNCH_INTERVAL:
            self.last_punch = t
            self.punch_round_attempts += 1
            self.punch_attempts_total += 1
            cands = []
            for c in (self.direct_addr, self.peer["public"], self.peer["local"]):
                if c and c not in cands:
                    cands.append(c)
            msg = self._pmsg("punch", n=self.punch_round_attempts)
            for c in cands:
                self._send_direct(msg, c, "punch")
            self.event("info", f"punch attempt {self.punch_round_attempts} -> "
                               f"{', '.join(fmt(c) for c in cands)}"
                               f"{' (dropped: direct path blocked)' if self.blackhole else ''}")
            self.broadcast({"type": "punch", "n": self.punch_round_attempts})
        if t - self.punch_round_start > self.punch_timeout:
            self.set_state(RELAY, f"hole punching timed out after {self.punch_round_attempts} attempts "
                                  f"({self.punch_timeout:.0f}s) - falling back to relay via server", "warn")

    # ================================================================ sending
    def _send_raw(self, msg, addr):
        data = json.dumps(msg, separators=(",", ":")).encode()
        try:
            self.transport.sendto(data, addr)
        except OSError as e:
            log.debug("sendto %s failed: %s", fmt(addr), e)
        return len(data)

    def _pmsg(self, t, **kw):
        # Every peer-to-peer message carries the room code and our id; the
        # receiver drops anything that doesn't match (our "room-code check").
        return {"t": t, "room": self.room, "from": self.my_id, **kw}

    def _register(self):
        self.last_register = now()
        self._send_raw({"t": "register", "room": self.room, "id": self.my_id, "name": self.name,
                        "local": list(self.local_addr)}, self.server_addr)
        log.debug("-> server: register")

    def _send_direct(self, msg, addr, what=None):
        if self.blackhole:
            log.debug("BLACKHOLE drop outbound %s to %s", msg["t"], fmt(addr))
            return
        n = self._send_raw(msg, addr)
        self.stats["tx_bytes"] += n
        self.stats["tx_direct_bytes"] += n
        self.stats["tx_packets"] += 1
        log.debug("-> direct %s: %s", fmt(addr), what or msg["t"])

    def _send_relay(self, msg):
        n = self._send_raw({"t": "relay", "room": self.room, "from": self.my_id, "inner": msg},
                           self.server_addr)
        self.stats["tx_bytes"] += n
        self.stats["tx_relay_bytes"] += n
        self.stats["tx_packets"] += 1
        log.debug("-> relay via server: %s", msg["t"])

    def _send_peer(self, msg):
        """Send on whatever path is active right now. Returns the path used."""
        path = self.active_path()
        if path == "direct":
            self._send_direct(msg, self.direct_addr)
        elif path == "relay":
            self._send_relay(msg)
        return path

    def _send_ping(self):
        self.last_ping = now()
        self.ping_seq += 1
        path = self._send_peer(self._pmsg("ping", seq=self.ping_seq))
        self.pending_pings[self.ping_seq] = (now(), path)
        self.broadcast({"type": "pulse", "path": path, "dir": "out"})

    def _send_ctl(self, op):
        # Control messages go via the relay (always available) AND direct if we
        # have it; the receiver de-duplicates by id.
        msg = self._pmsg("ctl", op=op, cid=secrets.token_hex(4))
        self._send_relay(msg)
        if self.state == DIRECT and self.direct_addr:
            self._send_direct(msg, self.direct_addr)

    # ============================================================== receiving
    def _on_datagram(self, data, addr):
        try:
            msg = json.loads(data)
            if not isinstance(msg, dict):
                raise ValueError
        except ValueError:
            log.debug("drop: garbage datagram from %s", fmt(addr))
            return

        if addr == self.server_addr:
            self.last_server_rx = now()
            if msg.get("t") == "relayed":
                inner = msg.get("inner")
                if isinstance(inner, dict):
                    self.stats["rx_bytes"] += len(data)
                    self.stats["rx_relay_bytes"] += len(data)
                    self.stats["rx_packets"] += 1
                    self.last_relay_rx = now()
                    if self.relay_silent_warned and self.state == RELAY:
                        self.relay_silent_warned = False
                        self.event("good", "relay path alive again")
                    self._on_peer_msg(inner, "relay", None)
            else:
                self._on_server_msg(msg)
            return

        # Anything not from the server came over the direct path.
        if self.blackhole:
            log.debug("BLACKHOLE drop inbound %s from %s", msg.get("t"), fmt(addr))
            return
        self.stats["rx_bytes"] += len(data)
        self.stats["rx_direct_bytes"] += len(data)
        self.stats["rx_packets"] += 1
        self._on_peer_msg(msg, "direct", addr)

    def _on_server_msg(self, msg):
        t = msg.get("t")
        if t == "registered":
            pub = tuple(msg["public"])
            if pub != self.public_addr:
                self.event("good" if self.public_addr is None else "warn",
                           f"registered with rendezvous; our public endpoint is {fmt(pub)}"
                           + ("" if pub[0] != self.local_addr[0] else " (same as local: no NAT in between)"))
                self.public_addr = pub
                if self.peer is None:
                    self.event("info", f"waiting for a peer to join room '{self.room}'...")
        elif t == "peer":
            pub = tuple(msg["public"])
            loc = tuple(msg["local"]) if msg.get("local") else None
            if self.peer is None or self.peer["id"] != msg["id"]:
                if self.peer is not None:
                    self.event("warn", f"peer changed: {self.peer['name']} replaced by {msg['name']}")
                self.peer = {"id": msg["id"], "name": msg["name"], "public": pub, "local": loc}
                self.direct_addr = None
                self.last_direct_rx = 0.0
                self.forced_relay = False
                self.event("good", f"peer discovered: {msg['name']} public={fmt(pub)} local={fmt(loc)}")
                self.start_punching("got peer's endpoints from rendezvous, both sides punch now")
            elif self.peer["public"] != pub or self.peer["local"] != loc:
                self.event("warn", f"peer endpoint changed {fmt(self.peer['public'])} -> {fmt(pub)}")
                self.peer.update(public=pub, local=loc)
                if self.state != DIRECT and not self.forced_relay:
                    self.start_punching("peer endpoint changed")
        elif t == "peer_left":
            if self.peer and self.peer["id"] == msg.get("id"):
                self._peer_gone("server says peer left")
        elif t == "error":
            self.event("bad", f"server error: {msg.get('reason')}")
        else:
            log.debug("drop: unknown server message %r", t)

    def _peer_gone(self, why):
        name = self.peer["name"]
        self.peer = None
        self.direct_addr = None
        self.rtt_ms = None
        self.pending_pings.clear()
        self.set_state(DISCOVERING, f"{name} gone ({why}); waiting for a peer", "bad")

    def _on_peer_msg(self, msg, path, addr):
        if msg.get("room") != self.room:
            log.debug("drop %s from %s: wrong room code", msg.get("t"), fmt(addr) if addr else "relay")
            return
        if self.peer is None or msg.get("from") != self.peer["id"]:
            log.debug("drop %s via %s: sender %r is not our peer", msg.get("t"), path, msg.get("from"))
            return
        t = msg.get("t")
        if path == "direct":
            self.last_direct_rx = now()
        log.debug("<- %s %s: %s", path, fmt(addr) if addr else "server", t)

        if t == "punch":
            if self.forced_relay:
                log.debug("ignoring punch: relay is forced")
                return
            # Answer to the exact address the punch came from: that is the hole.
            self._send_direct(self._pmsg("punch_ack", n=msg.get("n")), addr, "punch_ack")
            self._direct_evidence(addr, f"received punch #{msg.get('n')}")
        elif t == "punch_ack":
            self._direct_evidence(addr, f"punch #{msg.get('n')} answered")
        elif t == "ping":
            # Reply on the same path the ping came in on, so RTT measures that path.
            pong = self._pmsg("pong", seq=msg.get("seq"))
            if path == "direct":
                self._send_direct(pong, addr)
                self._direct_evidence(addr, "keepalive")
            else:
                self._send_relay(pong)
        elif t == "pong":
            sent = self.pending_pings.pop(msg.get("seq"), None)
            if sent:
                self.rtt_ms = round((now() - sent[0]) * 1000, 2)
                self.rtt_path = path
                self.rtt_history.append((round(time.time(), 2), self.rtt_ms, path))
                self.broadcast({"type": "pulse", "path": path, "dir": "in"})
            if path == "direct":
                self._direct_evidence(addr, "keepalive reply")
        elif t == "chat":
            entry = {"type": "chat", "ts": time.time(), "who": self.peer["name"], "mine": False,
                     "text": str(msg.get("text", ""))[:2000], "path": path}
            self.chat.append(entry)
            self.broadcast(entry)
            self.broadcast({"type": "pulse", "path": path, "dir": "in", "big": True})
            log.info("CHAT  <%s via %s> %s", self.peer["name"], path.upper(), entry["text"])
        elif t == "app":
            self._deliver_app(msg, path)
        elif t == "ctl":
            if msg.get("cid") in self.seen_ctl:
                return
            self.seen_ctl.append(msg.get("cid"))
            self._on_ctl(msg.get("op"))
        else:
            log.debug("drop: unknown peer message %r", t)

    def _on_ctl(self, op):
        name = self.peer["name"]
        if op == "force_relay":
            self.forced_relay = True
            self.set_state(RELAY, f"{name} forced relay mode", "warn")
        elif op == "repunch":
            self.forced_relay = False
            self.blackhole = False
            self.start_punching(f"{name} requested a re-punch", notify=False)
        elif op == "punch_now":
            # The peer started a punch round; join it so both NATs open together.
            if self.forced_relay:
                return
            if self.state == DIRECT:
                self.start_punching(f"{name} lost the direct path, re-punching together",
                                    notify=False, reconnect=True)
            elif self.state == RELAY:
                self.start_punching(f"{name} is retrying direct, punching together", notify=False)

    # ===================================================== operator commands
    def command(self, cmd, text=None):
        if cmd == "chat":
            return self.send_chat(text or "")
        if self.peer is None:
            self.event("warn", f"'{cmd}' ignored: no peer connected yet")
            return
        if cmd == "force_relay":
            self.event("warn", "operator: FORCE RELAY")
            self._send_ctl("force_relay")
            self.forced_relay = True
            self.set_state(RELAY, "forced by operator", "warn")
        elif cmd == "repunch":
            self.event("info", "operator: FORCE RE-PUNCH (clears forced relay / dropped path on both sides)")
            self.forced_relay = False
            self.blackhole = False
            self._send_ctl("repunch")
            self.start_punching("operator requested re-punch", notify=False)
        elif cmd == "drop_direct":
            # We do NOT change state here on purpose: the keepalive watchdog has
            # to notice the silence by itself, exactly like a real failure.
            self.blackhole = True
            self.event("bad", "operator: DROP DIRECT PATH - all direct packets now discarded "
                              f"(watchdog should notice within {DIRECT_DEAD_AFTER}s)")
            self.push_state()
        else:
            self.event("warn", f"unknown command {cmd!r}")

    def send_chat(self, text):
        text = text.strip()
        if not text:
            return
        if self.peer is None:
            self.event("warn", "chat not sent: no peer connected")
            return
        path = self._send_peer(self._pmsg("chat", text=text[:2000]))
        entry = {"type": "chat", "ts": time.time(), "who": self.name, "mine": True, "text": text, "path": path}
        self.chat.append(entry)
        self.broadcast(entry)
        self.broadcast({"type": "pulse", "path": path, "dir": "out", "big": True})
        log.info("CHAT  <%s via %s> %s", self.name, path.upper(), text)

    # ============================================================ passthrough
    def _on_app_datagram(self, data, addr):
        if self.args.app_listen:
            self.app_reply_addr = addr  # reply to whichever local app talked to us last
        if self.peer is None:
            return
        self._send_peer(self._pmsg("app", b64=base64.b64encode(data).decode()))
        self.stats["app_tx_packets"] += 1

    def _deliver_app(self, msg, path):
        if not self.app_transport or not self.app_reply_addr:
            log.debug("drop app packet: passthrough not configured or no local app yet")
            return
        try:
            self.app_transport.sendto(base64.b64decode(msg.get("b64", "")), self.app_reply_addr)
            self.stats["app_rx_packets"] += 1
        except (ValueError, OSError) as e:
            log.debug("app deliver failed: %s", e)


# ==================================================================== web app
def build_app(peer: Peer):
    app = FastAPI(title="rendezvous peer dashboard")

    @app.get("/")
    def index():
        return HTMLResponse(DASHBOARD_FILE.read_text(encoding="utf-8"))

    @app.get("/api/state")
    def state():
        return JSONResponse({**peer.snapshot(), "events": list(peer.events), "chat": list(peer.chat)})

    @app.post("/api/cmd")
    async def cmd(body: dict):
        peer.command(body.get("cmd"), body.get("text"))
        return {"ok": True, "state": peer.state}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q = asyncio.Queue(maxsize=1000)
        peer.clients.add(q)
        try:
            await sock.send_json({"type": "hello", "events": list(peer.events), "chat": list(peer.chat)})
            await sock.send_json(peer.snapshot())

            async def pump():
                while True:
                    await sock.send_json(await q.get())

            sender = asyncio.create_task(pump())
            try:
                while True:
                    m = await sock.receive_json()
                    peer.command(m.get("cmd"), m.get("text"))
            finally:
                sender.cancel()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            peer.clients.discard(q)

    return app


def stdin_chat(loop, peer):
    """Anything typed in the peer's terminal is sent as chat."""
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            return
        loop.call_soon_threadsafe(peer.send_chat, line)


async def amain(args):
    peer = Peer(args)
    await peer.start()
    if sys.stdin and sys.stdin.isatty():
        threading.Thread(target=stdin_chat, args=(asyncio.get_running_loop(), peer), daemon=True).start()
    url = f"http://{'localhost' if args.http_host in ('127.0.0.1', '0.0.0.0') else args.http_host}:{args.http_port}"
    peer.event("info", f"dashboard on {url}  (type in this terminal to chat)")
    if args.open:
        import webbrowser
        webbrowser.open(url)
    server = uvicorn.Server(uvicorn.Config(build_app(peer), host=args.http_host, port=args.http_port,
                                           log_level="warning", lifespan="off"))
    try:
        await server.serve()
    finally:
        await peer.stop()


def main():
    ap = argparse.ArgumentParser(description="P2P UDP overlay peer with live dashboard")
    ap.add_argument("--server", default="127.0.0.1:9000", help="rendezvous server host:port")
    ap.add_argument("--room", default="demo", help="room code; both peers must use the same one")
    ap.add_argument("--name", help="display name (default: random)")
    ap.add_argument("--bind", default="0.0.0.0", help="UDP bind address")
    ap.add_argument("--udp-port", type=int, default=0, help="UDP tunnel port (default: any free port)")
    ap.add_argument("--http-host", default="127.0.0.1", help="dashboard bind address")
    ap.add_argument("--http-port", type=int, default=8080, help="dashboard port (default 8080)")
    ap.add_argument("--punch-timeout", type=float, default=5.0, help="seconds to punch before relay fallback")
    ap.add_argument("--relay-retry", type=float, default=30.0,
                    help="while on relay, retry direct every N seconds (0 = never)")
    ap.add_argument("--block-direct", action="store_true",
                    help="simulate a NAT that can't be punched: drop all direct packets from the start")
    ap.add_argument("--app-listen", type=int, metavar="PORT",
                    help="passthrough: accept a local UDP app on 127.0.0.1:PORT and tunnel it")
    ap.add_argument("--app-target", metavar="HOST:PORT",
                    help="passthrough: deliver tunneled app packets to this UDP address")
    ap.add_argument("--open", action="store_true", help="open the dashboard in a browser")
    ap.add_argument("--verbose", "-v", action="store_true", help="log every packet decision")
    args = ap.parse_args()
    if args.app_listen and args.app_target:
        ap.error("use --app-listen on one peer and --app-target on the other, not both")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # Windows consoles + non-ASCII chat
        sys.stderr.reconfigure(errors="replace")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s.%(msecs)03d [%(name)s] %(message)s", datefmt="%H:%M:%S")
    for noisy in ("asyncio", "uvicorn", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
