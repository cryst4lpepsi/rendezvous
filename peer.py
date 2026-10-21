#!/usr/bin/env python3
"""
peer.py - one player's node: tunnels to every other player in the network,
an optional virtual LAN adapter, and the live dashboard (http://localhost:8080).

Each OTHER player gets its own Link with its own state machine:
  1. DISCOVERING  We register with the rendezvous server. It replies with our
                  PUBLIC endpoint (what our NAT turned us into), our virtual IP,
                  and the endpoints of every other player in the network.
  2. PUNCHING     We and that player fire small "punch" packets at each other's
                  public (and LAN) endpoint at the same time. See _tick_punch()
                  for why this opens a path through both NATs.
  3. DIRECT       A packet arrived straight from the player (not via the
                  server). The hole is open; traffic flows peer-to-peer.
  4. RELAY        Punching timed out. Traffic for this player goes via the
                  server, which forwards it. Slower, but works through any NAT.
  5. RECONNECTING We were DIRECT but keepalives stopped arriving. Traffic moves
                  to the relay at once while we punch again; we end up back in
                  DIRECT (path restored) or RELAY (fallback).
With 4 players you have 3 links, and each can be on a different path.

Everything runs on ONE UDP socket. That matters: the NAT mapping the server
observed belongs to this socket's port, so punch packets must leave from the
very same socket or they would get a different public port.

Wire format on that socket:
  JSON (first byte "{")      control: register, punch, ping, chat, ...
  0x01 | from_id | ip packet virtual-LAN packet sent directly to a peer
  0x02 | to_id   | ip packet virtual-LAN packet sent to the server for relaying
  0x03 | from_id | ip packet virtual-LAN packet relayed by the server
"""

import argparse
import asyncio
import collections
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

from rendezvous_server import STUN_MAGIC, disable_udp_connreset, parse_stun_response, stun_request

log = logging.getLogger("peer")

DISCOVERING = "DISCOVERING"
PUNCHING = "PUNCHING"
DIRECT = "DIRECT"
RELAY = "RELAY"
RECONNECTING = "RECONNECTING"

REGISTER_INTERVAL = 2.0    # re-register: keeps our NAT mapping to the server alive
KEEPALIVE_INTERVAL = 1.0   # ping each peer on its active path
DIRECT_DEAD_AFTER = 3.5    # no direct packet for this long => direct path is dead
PUNCH_INTERVAL = 0.25      # one punch burst every 250 ms while punching
SERVER_DEAD_AFTER = 6.0
TICK = 0.1

BIN_DIRECT, BIN_RELAY, BIN_RELAYED = 0x01, 0x02, 0x03

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DASHBOARD_FILE = RESOURCE_DIR / "dashboard.html"


def now():
    return time.monotonic()


def make_udp_socket(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Punching at a port that isn't open yet often triggers ICMP "port
    # unreachable"; on Windows that would break the next recv. See the helper.
    disable_udp_connreset(sock)
    sock.bind((host, port))
    sock.setblocking(False)
    return sock


def resolve(hostport, default_port):
    host, _, port = hostport.strip().rpartition(":") if ":" in hostport else (hostport.strip(), "", default_port)
    info = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_DGRAM)
    return info[0][4][:2]


def guess_lan_ip(server_addr):
    # "Connecting" a UDP socket sends nothing; it just makes the OS pick the
    # outgoing interface, whose address is our LAN IP. Peers on the same LAN
    # can reach each other on this address even if their router can't hairpin.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # A server on this machine (we are hosting) would give 127.0.0.1;
        # ask about the internet route instead to get the real LAN address.
        s.connect(("8.8.8.8", 53) if server_addr[0].startswith("127.") else server_addr)
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


class Link:
    """Our connection to ONE other player, with its own state machine."""

    def __init__(self, info, blackhole):
        self.id = info["id"]
        self.raw_id = bytes.fromhex(self.id)
        self.name = info["name"]
        self.vip = info.get("vip")
        self.public = tuple(info["public"])
        self.local = tuple(info["local"]) if info.get("local") else None

        self.state = DISCOVERING
        self.state_since = now()
        self.direct_addr = None    # the address that actually answered a punch
        self.direct_addr_seen = 0.0
        self.forced_relay = False  # operator pinned this link to RELAY
        self.blackhole = blackhole # simulate a dead direct path: drop all direct packets

        self.punch_round_start = 0.0
        self.punch_round_attempts = 0
        self.punch_attempts_total = 0
        self.last_punch = 0.0
        self.last_direct_rx = 0.0
        self.last_relay_rx = 0.0
        self.relay_silent_warned = False
        self.last_ping = 0.0
        self.ping_seq = 0
        self.pending_pings = {}    # seq -> (sent_at, path)
        self.rtt_ms = None
        self.rtt_path = None
        self.rtt_history = collections.deque(maxlen=60)  # (wall_time, rtt_ms, path)
        self.stats = collections.Counter()
        self.last_data_pulse = {"in": 0.0, "out": 0.0}

    @property
    def vip_bytes(self):
        return ipaddress.IPv4Address(self.vip).packed if self.vip else None

    def path(self):
        return "direct" if self.state == DIRECT else "relay"

    def candidates(self):
        # Every address we might reach this peer on: the last one that worked
        # (fast path on reconnect), its public endpoint (different networks)
        # and its LAN endpoint (same network, router may not support hairpinning).
        out = []
        for c in (self.direct_addr, self.public, self.local):
            if c and c not in out:
                out.append(c)
        return out

    def snapshot(self):
        t = now()
        return {
            "id": self.id, "name": self.name, "vip": self.vip,
            "state": self.state, "path": self.path(),
            "in_state_s": round(t - self.state_since, 1),
            "public": fmt(self.public), "local": fmt(self.local), "direct_addr": fmt(self.direct_addr),
            "rtt_ms": self.rtt_ms, "rtt_path": self.rtt_path, "rtt_history": list(self.rtt_history),
            "stats": dict(self.stats),
            "punch": {"round": self.punch_round_attempts, "total": self.punch_attempts_total,
                      "elapsed": round(t - self.punch_round_start, 2) if self.state in (PUNCHING, RECONNECTING) else None},
            "direct_silence_s": round(t - self.last_direct_rx, 2) if self.last_direct_rx else None,
            "forced_relay": self.forced_relay, "blackhole": self.blackhole,
        }


class Peer:
    def __init__(self, args):
        self.args = args
        self.punch_timeout = args.punch_timeout
        self.relay_retry = args.relay_retry
        self.config_path = Path(args.config) if args.config else None
        self.config = self._load_config()

        self.joined = False
        self.server_addr = None
        self.network = None      # network name shown to the user
        self.password = ""
        self.server_candidates = []  # [address as typed, fallback (host's LAN address)]
        self.server_index = 0
        self.hosting = None      # set while we host the network (see hosting.py)
        self.code = None         # join code of the current network (10 or 6 digits), if it has one
        self.hosting_busy = False
        self._stun_waiters = {}  # STUN transaction id -> future
        self.last_host_stun = 0.0
        self.join_patience = 6.0  # seconds a code join waits for the host before giving up
        self.server_ever_ok = False
        self.room = None         # what the server matches on: "network/password"
        self.my_id = None
        self.my_raw_id = None
        self.name = args.name or self.config.get("name") or socket.gethostname()
        self.public_addr = None  # our public endpoint, as reported by the server
        self.local_addr = None
        self.vip = None
        self.prefix = None
        self.links = {}          # peer id -> Link
        self.vip_links = {}      # virtual ip (4 bytes) -> Link

        self.last_server_rx = 0.0
        self.server_ok = None
        self.joined_at = 0.0
        self.last_register = 0.0

        self.vnet = None
        self.vnet_status = "off"     # off | starting | up | error
        self.vnet_detail = "virtual LAN disabled (demo/chat mode)"
        self.vnet_stats = collections.Counter()

        self.events = collections.deque(maxlen=400)
        self.chat = collections.deque(maxlen=100)
        self.event_seq = 0
        self.seen_ctl = collections.deque(maxlen=200)
        self.clients = set()           # one asyncio.Queue per open web dashboard
        self.listeners = []            # callables(obj) for in-process UIs (the desktop app)
        self.http_server = None        # uvicorn.Server, if the web dashboard is running
        self.stopped = None            # asyncio.Event, set by quit()

        self.loop = None
        self.transport = None
        self.udp_port = None
        self._tasks = []
        self._last_push = 0.0

    # ================================================================ config
    def _load_config(self):
        if self.config_path and self.config_path.is_file():
            try:
                return json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return {}

    def _save_config(self, **kw):
        self.config.update(kw)
        if self.config_path:
            try:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                self.config_path.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
            except OSError as e:
                log.warning("could not save settings: %s", e)

    # ================================================================ startup
    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.stopped = asyncio.Event()
        sock = make_udp_socket(self.args.bind, self.args.udp_port)
        self.transport, _ = await self.loop.create_datagram_endpoint(
            lambda: _Proto(self._on_datagram), sock=sock)
        self.udp_port = sock.getsockname()[1]
        self.event("info", f"{self.name} up: UDP tunnel socket on port {self.udp_port}")
        if self.args.vlan:
            await self._start_vnet()
            if sys.platform == "win32":  # let punches and players in (Windows Firewall)
                import hosting
                await self.loop.run_in_executor(None, hosting.allow_app_through_firewall)
        self._tasks.append(asyncio.create_task(self._ticker()))

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        if self.hosting:  # close the router port before exiting
            import hosting
            info, self.hosting = self.hosting, None
            await self.loop.run_in_executor(None, hosting.stop_hosting, info)
        if self.joined:
            self.leave(quiet=True)
        if self.vnet:
            await self.loop.run_in_executor(None, self.vnet.close)
        if self.transport:
            self.transport.close()

    async def _start_vnet(self):
        import vnet
        self.vnet_status, self.vnet_detail = "starting", "creating virtual adapter..."
        try:
            self.vnet = await self.loop.run_in_executor(None, vnet.open_adapter)
        except vnet.VnetError as e:
            self.vnet_status, self.vnet_detail = "error", str(e)
            self.event("bad", f"virtual LAN unavailable: {e}. Tunnel and chat still work.")
            return
        except Exception as e:  # unexpected driver/ctypes failure: keep the app usable
            log.exception("virtual adapter failed")
            self.vnet_status, self.vnet_detail = "error", f"{type(e).__name__}: {e}"
            self.event("bad", f"virtual LAN unavailable: {e}")
            return
        self.vnet.start(lambda pkt: self.loop.call_soon_threadsafe(self._on_tun_packet, pkt))
        self.vnet_detail = f"adapter '{self.vnet.name}' ready ({self.vnet.kind}), waiting for an address"
        self.event("good", f"virtual adapter '{self.vnet.name}' created")

    async def _assign_vip(self, vip, prefix):
        if not self.vnet:
            return
        self.vnet_status, self.vnet_detail = "starting", f"assigning {vip}/{prefix}..."
        self.push_state()
        try:
            await self.loop.run_in_executor(None, self.vnet.set_address, vip, prefix)
        except Exception as e:
            self.vnet_status, self.vnet_detail = "error", f"could not set address: {e}"
            self.event("bad", self.vnet_detail)
            return
        if vip == self.vip:
            self.vnet_status, self.vnet_detail = "up", f"adapter '{self.vnet.name}' is {vip}/{prefix}"
            self.event("good", f"virtual LAN up: this PC is {vip} - games can reach the others "
                               f"on their 10.x addresses and see LAN broadcasts")
        self.push_state()

    # ================================================================ join/leave
    def join(self, server, network, password="", name=None, remember=True, alt=None, room=None):
        if self.joined:
            self.leave(quiet=True, keep_hosting=True)
        network = (network or "").strip()
        if not network:
            self.event("warn", "enter a network name to join")
            return False
        server = (server or "127.0.0.1:9000").strip()
        try:
            self.server_addr = resolve(server, 9000)
        except (OSError, ValueError) as e:
            self.event("bad", f"cannot resolve server '{server}': {e}")
            return False
        self.server_candidates = [server] + ([alt] if alt and alt != server else [])
        self.join_patience = 6.0
        self.server_ever_ok = False
        if not room:
            self.code = None  # joined by server address: no join code
        self.server_index = 0
        self.password = password
        if name and name.strip():
            self.name = name.strip()[:32]
        self.network = network
        self.room = room or (f"{network}/{password}" if password else network)
        self.my_id = secrets.token_hex(3)
        self.my_raw_id = bytes.fromhex(self.my_id)
        self.local_addr = (guess_lan_ip(self.server_addr), self.udp_port)
        self.public_addr = None
        self.joined, self.joined_at = True, now()
        self.server_ok = None
        if remember:
            self._save_config(mode="join", server=server, alt=alt, network=network, password=password,
                              name=self.name, autojoin=True)
        self.event("info", f"joining network '{network}' via rendezvous {fmt(self.server_addr)} as {self.name}")
        self._register()
        self.push_state()
        return True

    def leave(self, quiet=False, keep_hosting=False):
        if self.hosting and not keep_hosting:
            import hosting
            info, self.hosting = self.hosting, None
            self.loop.run_in_executor(None, hosting.stop_hosting, info)
            if not quiet:
                self.event("warn", "stopped hosting: the network is closed for everyone")
        if not self.joined:
            self.push_state()
            return
        self._send_raw({"t": "bye", "room": self.room, "id": self.my_id}, self.server_addr)
        for link in list(self.links.values()):
            self._drop_link(link, "we left the network", quiet=True)
        self.joined = False
        if not quiet:
            self._save_config(autojoin=False)
            self.event("warn", f"left network '{self.network}'")
        self.push_state()

    def host(self, network, name=None, port=9000, use_upnp=True, remember=True):
        """Host a network: run the rendezvous server in this app, open the
        router port with UPnP, then join it ourselves."""
        if self.hosting_busy:
            return
        asyncio.ensure_future(self._host(network, name, port, use_upnp, remember))

    async def _host(self, network, name, port, use_upnp, remember):
        import hosting
        network = " ".join((network or "").split())
        if not network:
            self.event("warn", "enter a network name to host")
            return
        self.hosting_busy = True
        self.leave(quiet=True)
        self.push_state()
        room = hosting.room_for(network)
        self.event("info", f"hosting '{network}': starting the rendezvous server on UDP {port}"
                           + (" and asking the router to open it (UPnP)..." if use_upnp else "..."))
        info, err = None, None
        for p in range(port, port + 10):  # next free port if this one is taken
            try:
                # Same network as last time: keep the 6-digit code friends already have.
                keep = self.config.get("punch_code") if hosting.room_for(self.config.get("network")) == room else None
                info = await self.loop.run_in_executor(None, hosting.start_hosting, p, room, self.udp_port,
                                                       use_upnp, keep)
                break
            except OSError as e:
                err = e
        self.hosting_busy = False
        if info is None:
            self.event("bad", f"could not start hosting: {err}")
            self.push_state()
            return
        self.hosting = info
        self.code = self._host_code(network, info)
        if info["mode"] == "punch":
            await self._refresh_host_stun()
        self.event("good" if info["mode"] in ("direct", "punch") else "warn", info["status"])
        if info.get("detail") and info["mode"] != "direct":
            self.event("info", f"details: {info['detail']}")
        if remember:
            self._save_config(mode="host", network=network, name=(name or self.name), host_port=port,
                              upnp=use_upnp, autojoin=True, punch_code=info["punch_code"])
        self.join(f"127.0.0.1:{info['server'].port}", network, "", name, remember=False, room=room)
        self.event("good", f"hosting - friends join with network name '{network}' and code "
                           f"{hosting.format_code(self.code)}")

    @staticmethod
    def _host_code(network, info):
        # Port open: the code IS our public address (10 digits, nothing else
        # needed). Behind CGNAT / closed port: a 6-digit mailbox code. Neither:
        # the LAN address, which still works for friends at home.
        import hosting
        if info["mode"] == "punch":
            return info["punch_code"]
        return hosting.make_code(network, info["public_ip"] or info["lan_ip"] or "127.0.0.1",
                                 info["server_port"] if info["mode"] == "direct" else info["server"].port)

    async def stun_self(self):
        """Our tunnel socket's public address, asked from a STUN server."""
        import hosting
        for addr in await self.loop.run_in_executor(None, hosting.stun_servers):
            tid = secrets.token_bytes(12)
            fut = self._stun_waiters[tid] = self.loop.create_future()
            try:
                for wait in (0.7, 1.4):
                    self.transport.sendto(stun_request(tid), addr)
                    try:
                        return await asyncio.wait_for(asyncio.shield(fut), wait)
                    except asyncio.TimeoutError:
                        continue
            finally:
                self._stun_waiters.pop(tid, None)
        return None

    async def _refresh_host_stun(self):
        """Host behind CGNAT: tell our own server where players can reach our
        tunnel socket, and keep that NAT mapping alive."""
        self.last_host_stun = now()
        ep = await self.stun_self()
        if ep and self.hosting:
            self.hosting["server"].server.overrides[self.udp_port] = ep

    def retry_ports(self):
        """The "Try again" button: ask the router to open the port again (after
        the user turned UPnP on, for example)."""
        if self.hosting and not self.hosting_busy:
            asyncio.ensure_future(self._retry_ports())

    async def _retry_ports(self):
        import hosting
        info = self.hosting
        self.hosting_busy = True
        self.event("info", "asking the router to open the port again (UPnP, then NAT-PMP)...")
        self.push_state()
        info["use_upnp"] = True
        try:
            await self.loop.run_in_executor(None, hosting.map_ports, info)
        finally:
            self.hosting_busy = False
        if self.hosting is not info:
            return
        old, self.code = self.code, self._host_code(self.network, info)
        if info["mode"] == "punch":
            await self._refresh_host_stun()
        self.event("good" if info["mode"] in ("direct", "punch") else "warn", info["status"])
        if self.code != old:
            self.event("warn", f"the join code changed: it is now {hosting.format_code(self.code)}")
        self.push_state()

    def join_code(self, network, code, name=None, remember=True):
        """Join a friend's network with its name and code (6 or 10 digits)."""
        import hosting
        network = " ".join((network or "").split())
        try:
            parsed = hosting.parse_any(network, code)
        except ValueError as e:
            self.event("bad", f"join code: {e}")
            self.broadcast({"type": "join_failed", "reason": str(e)})
            return False
        if parsed["kind"] == "mailbox":
            asyncio.ensure_future(self._join_mailbox(network, parsed["code"], name, remember))
        else:
            asyncio.ensure_future(self._join_code(network, code, parsed["ip"], parsed["port"], name, remember))
        return True

    async def _find_on_lan(self, network, port):
        import hosting
        if os.environ.get("RENDEZVOUS_NO_LAN_DISCOVERY"):  # tests: force the internet path
            return None
        self.event("info", f"looking for '{network}' on this network first...")
        found = await self.loop.run_in_executor(None, hosting.find_on_lan, network, port)
        if found:
            self.event("good", f"found the host on this network at {found}")
        return found

    async def _join_mailbox(self, network, code, name, remember):
        """6-digit code: the host is behind CGNAT. Look up its address in the
        mailbox, tell it ours ("knock"), and punch through both NATs."""
        import hosting
        room = hosting.room_for(network)
        if remember:
            self._save_config(mode="code", network=network, code=code, name=(name or self.name), autojoin=True)
        found = await self._find_on_lan(network, hosting.DEFAULT_PORT)
        if found:
            self.join(found, network, "", name, remember=False, room=room)
            self.code = code
            return

        def fail(reason):
            self.event("bad", reason)
            self._save_config(autojoin=False)
            self.broadcast({"type": "join_failed", "reason": reason})

        mailbox = hosting.Mailbox(room, code)
        self.event("info", "looking up the host online (ntfy.sh mailbox)...")
        try:
            hosts = [m for m in await self.loop.run_in_executor(None, mailbox.fetch)
                     if m.get("t") == "host" and isinstance(m.get("ep"), list) and len(m["ep"]) == 2]
        except OSError as e:
            return fail(f"couldn't reach the online lookup ({hosting.MAILBOX_URL}): {e}")
        if not hosts:
            return fail("no host is online with that network name and code - check both, and that the "
                        "host has Rendezvous open")
        ep = hosts[-1]["ep"]  # the newest announcement
        mine = await self.stun_self()
        if not mine:
            return fail("couldn't reach a STUN server to learn this PC's public address")
        self.event("info", f"host is at {ep[0]}:{ep[1]}; we are {mine[0]}:{mine[1]} - knocking and punching")
        self.join(f"{ep[0]}:{ep[1]}", network, "", name, remember=False, room=room)
        self.code = code
        self.join_patience = 25.0  # punching through two NATs takes a few rounds
        asyncio.ensure_future(self._knock(mailbox, mine))

    async def _knock(self, mailbox, mine):
        """Tell the host (through the mailbox) where to punch towards, a few
        times until its server answers."""
        for wait in (0, 3, 3, 4, 5):
            await asyncio.sleep(wait)
            if not self.joined or self.server_ok:
                return
            try:
                await self.loop.run_in_executor(None, mailbox.publish,
                                                {"t": "knock", "ep": list(mine), "name": self.name})
            except OSError as e:
                log.info("knock failed: %s", e)

    async def _join_code(self, network, code, ip, port, name, remember):
        import hosting
        found = await self._find_on_lan(network, port)
        public = f"{ip}:{port}"
        self.code = re.sub(r"[\s.\-]", "", code)
        if remember:
            self._save_config(mode="code", network=network, code=self.code, name=(name or self.name), autojoin=True)
        # Same home as the host: use its LAN address (the public one may not
        # loop back through the router). Otherwise the address from the code.
        self.join(found or public, network, "", name, remember=False, alt=public if found else None,
                  room=hosting.room_for(network))

    # ============================================================ event bus
    def event(self, level, msg, link=None):
        """Timestamped event: printed to the console AND pushed to dashboards."""
        if link is not None:
            msg = f"[{link.name}] {msg}"
        self.event_seq += 1
        ev = {"type": "event", "id": self.event_seq, "ts": time.time(), "level": level, "msg": msg,
              "peer": link.id if link else None}
        self.events.append(ev)
        log.info("%-5s %s", level.upper(), msg)
        self.broadcast(ev)

    def broadcast(self, obj):
        for fn in self.listeners:
            fn(obj)
        for q in list(self.clients):
            try:
                q.put_nowait(obj)
            except asyncio.QueueFull:
                pass  # slow dashboard; it will resync from the next state push

    def push_state(self):
        self._last_push = now()
        self.broadcast(self.snapshot())

    def snapshot(self):
        tot = collections.Counter()
        for l in self.links.values():
            tot.update(l.stats)
        return {
            "type": "state",
            "joined": self.joined,
            "network": self.network,
            "server": fmt(self.server_addr),
            "server_ok": self.server_ok,
            "me": {"id": self.my_id, "name": self.name, "vip": self.vip,
                   "public": fmt(self.public_addr), "local": fmt(self.local_addr)},
            "vnet": {"enabled": bool(self.args.vlan), "status": self.vnet_status, "detail": self.vnet_detail,
                     "stats": dict(self.vnet_stats)},
            "peers": [l.snapshot() for l in self.links.values()],
            "totals": dict(tot),
            "punch_timeout": self.punch_timeout,
            "dead_after": DIRECT_DEAD_AFTER,
            "hosting": None if not self.hosting else {
                "status": self.hosting["status"], "reachable": self.hosting["reachable"],
                "public_ip": self.hosting["public_ip"], "port": self.hosting["server_port"],
                "mode": self.hosting["mode"],
                "knocks": self.hosting["punch"].knocks if self.hosting.get("punch") else 0},
            "hosting_busy": self.hosting_busy,
            "code": self.code,
            "code_display": self._code_display(),
            "saved": {k: self.config.get(k, "") for k in ("server", "network", "name", "mode")}
                     | {"has_password": bool(self.config.get("password"))},
            "app_mode": bool(self.args.app_mode),
        }

    # ========================================================= state machine
    def set_state(self, link, new, reason, level="info"):
        if new == link.state:
            return
        old, link.state, link.state_since = link.state, new, now()
        if new in (PUNCHING, RECONNECTING):
            link.punch_round_start = now()
            link.punch_round_attempts = 0
            link.last_punch = 0.0
        link.relay_silent_warned = False
        if new == DIRECT:
            link.last_direct_rx = link.direct_addr_seen = now()
        self.event(level, f"{old} -> {new}: {reason}", link)
        self.broadcast({"type": "transition", "peer": link.id, "name": link.name, "from": old, "to": new})
        self.push_state()

    def start_punching(self, link, reason, notify=True, reconnect=False):
        """Begin a punch round with one peer. Hole punching only works if BOTH
        sides send at roughly the same time, so unless the peer asked us to do
        this, we ask it to punch too (via the relay, which always works)."""
        target = RECONNECTING if reconnect else PUNCHING
        if link.state == target:
            link.punch_round_start, link.punch_round_attempts = now(), 0
        else:
            self.set_state(link, target, reason, "warn" if reconnect else "info")
        if notify:
            self._send_ctl(link, "punch_now")

    def _direct_evidence(self, link, addr, why):
        """A valid packet from this peer arrived over the DIRECT path."""
        if link.forced_relay:
            return
        if link.state in (PUNCHING, RECONNECTING, RELAY):
            # Peer-reflexive address: we lock onto whatever address the packet
            # actually came from, which may differ from what the server told us
            # (e.g. the peer is on our LAN, or its NAT chose another port).
            link.direct_addr = addr
            restored = link.state == RECONNECTING
            self.set_state(link, DIRECT, f"{why} from {fmt(addr)} - "
                                         f"{'direct path restored' if restored else 'hole punched, traffic now peer-to-peer'}",
                           "good")
        elif link.state == DIRECT:
            # A peer on our LAN can answer from more than one address (its LAN
            # IP and, via the router, its public one). Stick with the address
            # we use and only move if it has gone quiet.
            t = now()
            if addr == link.direct_addr:
                link.direct_addr_seen = t
            elif t - link.direct_addr_seen > 2.0:
                self.event("info", f"direct address moved {fmt(link.direct_addr)} -> {fmt(addr)}", link)
                link.direct_addr, link.direct_addr_seen = addr, t

    async def _ticker(self):
        while True:
            try:
                self._tick()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(TICK)

    def _tick(self):
        t = now()
        if self.hosting and self.hosting["mode"] == "punch" and t - self.last_host_stun > 20:
            asyncio.ensure_future(self._refresh_host_stun())
        if self.joined:
            if t - self.last_register >= REGISTER_INTERVAL:
                self._register()
            self._tick_server(t)
            for link in list(self.links.values()):
                self._tick_link(link, t)
        if t - self._last_push >= 0.25:
            self.push_state()

    def _tick_server(self, t):
        server_ok = bool(self.last_server_rx) and (t - self.last_server_rx) < SERVER_DEAD_AFTER \
            and self.last_server_rx >= self.joined_at
        if server_ok:
            self.server_ever_ok = True
        if server_ok and self.server_ok is not True:
            if self.server_ok is False:
                self.event("good", "rendezvous server reachable again")
            self.server_ok = True
        elif (not server_ok and self.server_ok is None and len(self.server_candidates) > 1
              and t - self.joined_at > 4 and self.server_index + 1 < len(self.server_candidates)):
            # Never got an answer: try the next address from the invite (the
            # host's LAN address, for friends on the same network).
            self.server_index += 1
            addr = self.server_candidates[self.server_index]
            try:
                self.server_addr = resolve(addr, 9000)
            except (OSError, ValueError):
                return
            self.joined_at = t
            self.local_addr = (guess_lan_ip(self.server_addr), self.udp_port)
            self.event("warn", f"no answer from the public address, trying the host's LAN address {addr}")
            self._register()
        elif (not self.server_ever_ok and self.code and not self.hosting
              and self.server_index + 1 >= len(self.server_candidates) and t - self.joined_at > self.join_patience):
            # Joined with a code and the host never answered: stop sending.
            # (A mistyped 10-digit code decodes to some random address.)
            if self.join_patience > 6:
                reason = ("couldn't punch through to the host: one of your two connections blocks hole "
                          "punching (symmetric NAT). Let someone else host, or use a rendezvous server")
            else:
                reason = ("couldn't reach the host - check the network name and code, "
                          "and that the host has Rendezvous open")
            self.event("bad", reason)
            self.leave(quiet=True)
            self._save_config(autojoin=False)
            self.broadcast({"type": "join_failed", "reason": reason})
        elif not server_ok and self.server_ok is not False:
            if self.server_ok is True or t - self.joined_at > SERVER_DEAD_AFTER:
                self.event("bad", f"rendezvous server {fmt(self.server_addr)} not responding "
                                  f"(check the address and that UDP {self.server_addr[1]} is open)")
                self.server_ok = False

    def _tick_link(self, link, t):
        if link.state in (PUNCHING, RECONNECTING):
            self._tick_punch(link, t)
        elif link.state == DIRECT:
            # Keepalive watchdog: the peer pings us every second over the
            # direct path. Silence for DIRECT_DEAD_AFTER means the NAT mapping
            # expired, a router rebooted, wifi changed, ... Move traffic to the
            # relay immediately and try to punch again.
            silence = t - link.last_direct_rx
            if silence > DIRECT_DEAD_AFTER:
                self.start_punching(link, f"keepalive lost: no direct packet for {silence:.1f}s, "
                                          f"traffic moved to relay while re-punching", reconnect=True)
        elif link.state == RELAY:
            if not link.forced_relay and self.relay_retry > 0 and t - link.state_since > self.relay_retry:
                self.start_punching(link, f"periodic retry: {self.relay_retry:.0f}s on relay, trying direct again")
            # Measure relay silence from when we switched, not from the last
            # (possibly ancient) relayed packet.
            if t - max(link.last_relay_rx, link.state_since) > SERVER_DEAD_AFTER and not link.relay_silent_warned:
                link.relay_silent_warned = True
                self.event("bad", "relay path silent: no packet from this peer via server", link)

        if t - link.last_ping >= KEEPALIVE_INTERVAL:
            self._send_ping(link)
        for seq, (sent, _) in list(link.pending_pings.items()):
            if t - sent > 5:
                del link.pending_pings[seq]

    def _tick_punch(self, link, t):
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

        With several players this runs independently for every pair.
        """
        if t - link.last_punch >= PUNCH_INTERVAL:
            link.last_punch = t
            link.punch_round_attempts += 1
            link.punch_attempts_total += 1
            cands = link.candidates()
            msg = self._pmsg("punch", n=link.punch_round_attempts)
            for c in cands:
                self._send_direct(link, msg, c, "punch")
            self.event("info", f"punch attempt {link.punch_round_attempts} -> "
                               f"{', '.join(fmt(c) for c in cands)}"
                               f"{' (dropped: direct path blocked)' if link.blackhole else ''}", link)
            self.broadcast({"type": "punch", "peer": link.id, "n": link.punch_round_attempts})
        if t - link.punch_round_start > self.punch_timeout:
            self.set_state(link, RELAY, f"hole punching timed out after {link.punch_round_attempts} attempts "
                                        f"({self.punch_timeout:.0f}s) - falling back to relay via server", "warn")

    def quit(self):
        if self.stopped:
            self.stopped.set()
        if self.http_server:
            self.http_server.should_exit = True

    # ================================================================ sending
    def _send_raw(self, data, addr):
        if isinstance(data, dict):
            data = json.dumps(data, separators=(",", ":")).encode()
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
                        "local": list(self.local_addr), "want_ip": self.config.get("vip")}, self.server_addr)
        log.debug("-> server: register")

    def _send_direct(self, link, msg, addr, what=None):
        if link.blackhole:
            log.debug("BLACKHOLE drop outbound %s to %s", what or "packet", fmt(addr))
            return
        n = self._send_raw(msg, addr)
        link.stats["tx_bytes"] += n
        link.stats["tx_direct_bytes"] += n
        link.stats["tx_packets"] += 1
        log.debug("-> direct %s %s: %s", link.name, fmt(addr), what or (msg.get("t") if isinstance(msg, dict) else "data"))

    def _send_relay(self, link, msg):
        if isinstance(msg, dict):
            data = {"t": "relay", "room": self.room, "from": self.my_id, "to": link.id, "inner": msg}
        else:
            data = bytes([BIN_RELAY]) + link.raw_id + msg
        n = self._send_raw(data, self.server_addr)
        link.stats["tx_bytes"] += n
        link.stats["tx_relay_bytes"] += n
        link.stats["tx_packets"] += 1
        log.debug("-> relay to %s: %s", link.name, msg.get("t") if isinstance(msg, dict) else "data")

    def _send_peer(self, link, msg):
        """Send on whatever path is active for this peer. Returns the path used."""
        if link.state == DIRECT:
            self._send_direct(link, msg, link.direct_addr)
            return "direct"
        self._send_relay(link, msg)
        return "relay"

    def _send_ping(self, link):
        link.last_ping = now()
        link.ping_seq += 1
        path = self._send_peer(link, self._pmsg("ping", seq=link.ping_seq))
        link.pending_pings[link.ping_seq] = (now(), path)
        self.broadcast({"type": "pulse", "peer": link.id, "path": path, "dir": "out"})

    def _send_ctl(self, link, op):
        # Control messages go via the relay (always available) AND direct if we
        # have it; the receiver de-duplicates by id.
        msg = self._pmsg("ctl", op=op, cid=secrets.token_hex(4))
        self._send_relay(link, msg)
        if link.state == DIRECT and link.direct_addr:
            self._send_direct(link, msg, link.direct_addr)

    # ============================================================ virtual LAN
    def _on_tun_packet(self, pkt):
        """
        The OS sent an IP packet into our virtual adapter. Decide which
        player(s) it is for, by its destination address:
          10.77.0.x of a player        -> that player only
          broadcast / multicast        -> every player (this is how LAN game
                                          discovery reaches the others)
          anything else                -> drop
        """
        if len(pkt) < 20 or pkt[0] >> 4 != 4:
            self.vnet_stats["dropped_non_ipv4"] += 1  # IPv6 isn't routed on the virtual LAN
            return
        if pkt[9] == 2:
            return  # IGMP membership chatter: meaningless across the tunnel
        dst = pkt[16:20]
        link = self.vip_links.get(dst)
        if link is not None:
            self._send_vlan(link, pkt)
        elif dst == b"\xff\xff\xff\xff" or dst == self._bcast or 224 <= dst[0] <= 239:
            self.vnet_stats["tx_broadcast"] += 1
            for link in list(self.links.values()):
                self._send_vlan(link, pkt)
        else:
            self.vnet_stats["dropped_no_route"] += 1

    @property
    def _bcast(self):
        if not self.vip:
            return None
        return ipaddress.ip_network(f"{self.vip}/{self.prefix}", strict=False).broadcast_address.packed

    def _send_vlan(self, link, pkt):
        if link.state == DIRECT and link.direct_addr:
            self._send_direct(link, bytes([BIN_DIRECT]) + self.my_raw_id + pkt, link.direct_addr)
            path = "direct"
        else:
            self._send_relay(link, pkt)
            path = "relay"
        link.stats["vlan_tx_packets"] += 1
        link.stats["vlan_tx_bytes"] += len(pkt)
        self._data_pulse(link, path, "out")

    def _deliver_vlan(self, link, pkt, path):
        # Anti-spoofing: a player may only send packets from its own virtual IP.
        if len(pkt) < 20 or pkt[12:16] != link.vip_bytes:
            log.debug("drop vlan packet from %s: wrong source address", link.name)
            return
        link.stats["vlan_rx_packets"] += 1
        link.stats["vlan_rx_bytes"] += len(pkt)
        self._data_pulse(link, path, "in")
        if self.vnet and self.vnet_status == "up":
            self.vnet.write(pkt)

    def _data_pulse(self, link, path, direction):
        t = now()
        if t - link.last_data_pulse[direction] > 0.15:  # don't flood the dashboard
            link.last_data_pulse[direction] = t
            self.broadcast({"type": "pulse", "peer": link.id, "path": path, "dir": direction, "data": True})

    # ============================================================== receiving
    def _on_datagram(self, data, addr):
        if data[:1] == b"\x01" and data[4:8] == STUN_MAGIC:  # answer to stun_self()
            r = parse_stun_response(data)
            fut = self._stun_waiters.get(r[0]) if r else None
            if fut and not fut.done():
                fut.set_result(r[1])
            return
        if not data or not self.joined:
            return
        kind = data[0]
        if addr == self.server_addr:
            self.last_server_rx = now()
            if kind == BIN_RELAYED:
                link = self._link_by_raw(data[1:4])
                if link:
                    self._count_rx(link, len(data), "relay")
                    link.last_relay_rx = now()
                    self._deliver_vlan(link, data[4:], "relay")
                return
            msg = self._parse(data, addr)
            if msg is None:
                return
            if msg.get("t") == "relayed":
                link = self.links.get(msg.get("from"))
                inner = msg.get("inner")
                if link and isinstance(inner, dict):
                    self._count_rx(link, len(data), "relay")
                    link.last_relay_rx = now()
                    self._on_peer_msg(link, inner, "relay", None)
            else:
                self._on_server_msg(msg)
            return

        # Anything not from the server came over a direct path.
        if kind == BIN_DIRECT:
            link = self._link_by_raw(data[1:4])
            # Only accept data from an address we punched with this peer.
            if not link or link.blackhole or addr not in link.candidates():
                log.debug("drop direct vlan packet from %s", fmt(addr))
                return
            self._count_rx(link, len(data), "direct")
            link.last_direct_rx = now()
            self._deliver_vlan(link, data[4:], "direct")
            return
        msg = self._parse(data, addr)
        if msg is None:
            return
        link = self.links.get(msg.get("from"))
        if link is None or msg.get("room") != self.room:
            log.debug("drop %s from %s: unknown sender or wrong room code", msg.get("t"), fmt(addr))
            return
        if link.blackhole:
            log.debug("BLACKHOLE drop inbound %s from %s", msg.get("t"), fmt(addr))
            return
        self._count_rx(link, len(data), "direct")
        self._on_peer_msg(link, msg, "direct", addr)

    def _parse(self, data, addr):
        try:
            msg = json.loads(data)
            if isinstance(msg, dict):
                return msg
        except ValueError:
            pass
        log.debug("drop: garbage datagram from %s", fmt(addr))
        return None

    def _link_by_raw(self, raw):
        for link in self.links.values():
            if link.raw_id == raw:
                return link
        return None

    def _count_rx(self, link, n, path):
        link.stats["rx_bytes"] += n
        link.stats[f"rx_{path}_bytes"] += n
        link.stats["rx_packets"] += 1

    def _on_server_msg(self, msg):
        t = msg.get("t")
        if t == "registered":
            pub = tuple(msg["public"])
            if pub != self.public_addr:
                self.event("good" if self.public_addr is None else "warn",
                           f"registered with rendezvous; our public endpoint is {fmt(pub)}"
                           + ("" if pub[0] != self.local_addr[0] else " (same as local: no NAT in between)"))
                self.public_addr = pub
                if not self.links:
                    self.event("info", f"waiting for other players to join '{self.network}'...")
            vip, prefix = msg.get("vip"), msg.get("prefix", 24)
            if vip and vip != self.vip:
                self.vip, self.prefix = vip, prefix
                self._save_config(vip=vip)
                self.event("good", f"virtual IP assigned: {vip}")
                asyncio.ensure_future(self._assign_vip(vip, prefix))
        elif t == "peer":
            link = self.links.get(msg["id"])
            if link is None:
                link = Link(msg, blackhole=self.args.block_direct)
                self.links[link.id] = link
                if link.vip:
                    self.vip_links[link.vip_bytes] = link
                self.event("good", f"player joined: public={fmt(link.public)} local={fmt(link.local)} "
                                   f"virtual IP={link.vip}", link)
                self.start_punching(link, "got endpoints from rendezvous, both sides punch now")
            else:
                pub = tuple(msg["public"])
                loc = tuple(msg["local"]) if msg.get("local") else None
                if link.public != pub or link.local != loc:
                    self.event("warn", f"endpoint changed {fmt(link.public)} -> {fmt(pub)}", link)
                    link.public, link.local = pub, loc
                    if link.state != DIRECT and not link.forced_relay:
                        self.start_punching(link, "peer endpoint changed")
        elif t == "peer_left":
            link = self.links.get(msg.get("id"))
            if link:
                self._drop_link(link, "left the network")
        elif t == "error":
            reason = msg.get("reason") or "error"
            self.event("bad", f"server error: {reason}")
            if not self.links and not self.hosting:
                # Wrong password / network full: stop retrying, tell the UI.
                self.leave(quiet=True)
                self._save_config(autojoin=False)
                self.broadcast({"type": "join_failed", "reason": reason})
        else:
            log.debug("drop: unknown server message %r", t)

    def _drop_link(self, link, why, quiet=False):
        self.links.pop(link.id, None)
        if link.vip:
            self.vip_links.pop(link.vip_bytes, None)
        if not quiet:
            self.event("bad", f"{link.state} -> gone: {why}", link)
            self.broadcast({"type": "transition", "peer": link.id, "name": link.name, "from": link.state, "to": "GONE"})
        self.push_state()

    def _on_peer_msg(self, link, msg, path, addr):
        if msg.get("room") != self.room or msg.get("from") != link.id:
            log.debug("drop %s via %s: wrong room code or sender", msg.get("t"), path)
            return
        t = msg.get("t")
        if path == "direct":
            link.last_direct_rx = now()
        log.debug("<- %s %s %s: %s", path, link.name, fmt(addr) if addr else "server", t)

        if t == "punch":
            if link.forced_relay:
                log.debug("ignoring punch: relay is forced")
                return
            # Answer to the exact address the punch came from: that is the hole.
            self._send_direct(link, self._pmsg("punch_ack", n=msg.get("n")), addr, "punch_ack")
            self._direct_evidence(link, addr, f"received punch #{msg.get('n')}")
        elif t == "punch_ack":
            self._direct_evidence(link, addr, f"punch #{msg.get('n')} answered")
        elif t == "ping":
            # Reply on the same path the ping came in on, so RTT measures that path.
            pong = self._pmsg("pong", seq=msg.get("seq"))
            if path == "direct":
                self._send_direct(link, pong, addr)
                self._direct_evidence(link, addr, "keepalive")
            else:
                self._send_relay(link, pong)
        elif t == "pong":
            sent = link.pending_pings.pop(msg.get("seq"), None)
            if sent:
                link.rtt_ms = round((now() - sent[0]) * 1000, 2)
                link.rtt_path = path
                link.rtt_history.append((round(time.time(), 2), link.rtt_ms, path))
                self.broadcast({"type": "pulse", "peer": link.id, "path": path, "dir": "in"})
            if path == "direct":
                self._direct_evidence(link, addr, "keepalive reply")
        elif t == "chat":
            entry = {"type": "chat", "ts": time.time(), "who": link.name, "mine": False,
                     "text": str(msg.get("text", ""))[:2000], "path": path}
            self.chat.append(entry)
            self.broadcast(entry)
            self.broadcast({"type": "pulse", "peer": link.id, "path": path, "dir": "in", "big": True})
            log.info("CHAT  <%s via %s> %s", link.name, path.upper(), entry["text"])
        elif t == "ctl":
            if msg.get("cid") in self.seen_ctl:
                return
            self.seen_ctl.append(msg.get("cid"))
            self._on_ctl(link, msg.get("op"))
        else:
            log.debug("drop: unknown peer message %r", t)

    def _on_ctl(self, link, op):
        if op == "force_relay":
            link.forced_relay = True
            self.set_state(link, RELAY, "peer forced relay mode", "warn")
        elif op == "repunch":
            link.forced_relay = False
            link.blackhole = False
            self.start_punching(link, "peer requested a re-punch", notify=False)
        elif op == "punch_now":
            # The peer started a punch round; join it so both NATs open together.
            if link.forced_relay:
                return
            if link.state == DIRECT:
                self.start_punching(link, "peer lost the direct path, re-punching together",
                                    notify=False, reconnect=True)
            elif link.state == RELAY:
                self.start_punching(link, "peer is retrying direct, punching together", notify=False)

    # ===================================================== operator commands
    def command(self, m):
        cmd = m.get("cmd")
        if cmd == "join":
            pw = m.get("password")
            if pw is None:  # "keep the saved password"
                pw = self.config.get("password") or ""
            return self.join(m.get("server"), m.get("network"), pw, m.get("name"), alt=m.get("alt"))
        if cmd == "retry_ports":
            return self.retry_ports()
        if cmd == "join_code":
            return self.join_code(m.get("network"), m.get("code"), m.get("name"))
        if cmd == "host":
            return self.host(m.get("network"), m.get("name"), int(m.get("port") or 9000), bool(m.get("upnp", True)))
        if cmd == "rejoin":
            return self.resume()
        if cmd == "leave":
            return self.leave()
        if cmd == "quit":
            self.event("warn", "quitting")
            return self.quit()
        if cmd == "chat":
            return self.send_chat(m.get("text") or "")
        targets = [self.links[m["peer"]]] if m.get("peer") in self.links else list(self.links.values())
        if not targets:
            self.event("warn", f"'{cmd}' ignored: no other players connected")
            return
        for link in targets:
            if cmd == "force_relay":
                self.event("warn", "operator: FORCE RELAY", link)
                self._send_ctl(link, "force_relay")
                link.forced_relay = True
                self.set_state(link, RELAY, "forced by operator", "warn")
            elif cmd == "repunch":
                self.event("info", "operator: FORCE RE-PUNCH (clears forced relay / dropped path on both sides)", link)
                link.forced_relay = False
                link.blackhole = False
                self._send_ctl(link, "repunch")
                self.start_punching(link, "operator requested re-punch", notify=False)
            elif cmd == "drop_direct":
                # We do NOT change state here on purpose: the keepalive watchdog
                # has to notice the silence by itself, exactly like a real failure.
                link.blackhole = True
                self.event("bad", "operator: DROP DIRECT PATH - all direct packets now discarded "
                                  f"(watchdog should notice within {DIRECT_DEAD_AFTER}s)", link)
            else:
                self.event("warn", f"unknown command {cmd!r}")
                return
        self.push_state()

    def _code_display(self):
        import hosting
        return hosting.format_code(self.code) if self.code and self.joined else None

    def resume(self):
        """Reconnect to the remembered network (host it again if we hosted it)."""
        c = self.config
        if c.get("mode") == "host":
            self.host(c.get("network"), c.get("name"), int(c.get("host_port") or 9000), bool(c.get("upnp", True)))
        elif c.get("mode") == "code" and c.get("code"):
            self.join_code(c.get("network"), c["code"], c.get("name"))
        elif c.get("network"):
            self.join(c.get("server"), c.get("network"), c.get("password") or "", c.get("name"), alt=c.get("alt"))

    def send_chat(self, text):
        text = text.strip()
        if not text:
            return
        if not self.links:
            self.event("warn", "chat not sent: no other players connected")
            return
        paths = {}
        for link in self.links.values():
            path = self._send_peer(link, self._pmsg("chat", text=text[:2000]))
            paths[link.name] = path
            self.broadcast({"type": "pulse", "peer": link.id, "path": path, "dir": "out", "big": True})
        uniq = set(paths.values())
        entry = {"type": "chat", "ts": time.time(), "who": self.name, "mine": True, "text": text,
                 "path": uniq.pop() if len(uniq) == 1 else "mixed", "paths": paths}
        self.chat.append(entry)
        self.broadcast(entry)
        log.info("CHAT  <%s> %s", self.name, text)


# ==================================================================== web app
def build_app(peer: Peer):
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="rendezvous peer dashboard")

    @app.get("/")
    def index():
        return HTMLResponse(DASHBOARD_FILE.read_text(encoding="utf-8"))

    @app.get("/api/state")
    def state():
        return JSONResponse({**peer.snapshot(), "events": list(peer.events), "chat": list(peer.chat)})

    @app.post("/api/cmd")
    async def cmd(body: dict):
        peer.command(body)
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q = asyncio.Queue(maxsize=2000)
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
                    peer.command(await sock.receive_json())
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
        except (EOFError, KeyboardInterrupt, RuntimeError):
            return
        loop.call_soon_threadsafe(peer.send_chat, line)


def autojoin(peer, args):
    """Host or join from the command line, else resume the remembered network,
    else (plain peer.py only) the zero-config local demo."""
    if args.host:
        peer.host(args.room or "demo", args.name, args.host_port, use_upnp=not args.no_upnp, remember=False)
    elif args.code:
        peer.join_code(args.room or "demo", args.code, args.name, remember=False)
    elif args.server or args.room:
        peer.join(args.server or "127.0.0.1:9000", args.room or "demo", args.password or "", remember=False)
    elif peer.config.get("autojoin") and peer.config.get("network"):
        peer.resume()
    elif not args.app_mode:
        peer.join("127.0.0.1:9000", "demo", remember=False)


async def serve_http(peer, args):
    """The web dashboard + JSON API. Returns when quit() is called or on Ctrl+C."""
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(build_app(peer), host=args.http_host, port=args.http_port,
                                           log_level="warning", lifespan="off",
                                           log_config=None))  # we configure logging; also safe with no console
    peer.http_server = server
    url = f"http://127.0.0.1:{args.http_port}/" if args.http_host in ("127.0.0.1", "0.0.0.0") \
        else f"http://{args.http_host}:{args.http_port}/"
    peer.event("info", f"dashboard on {url}" + ("" if args.app_mode else "  (type in this terminal to chat)"))

    async def announce():
        while not server.started:
            await asyncio.sleep(0.05)
        if args.open:
            import webbrowser
            webbrowser.open(url)

    asyncio.ensure_future(announce())
    await server.serve()


async def run(args):
    peer = Peer(args)
    await peer.start()
    autojoin(peer, args)
    if sys.stdin and sys.stdin.isatty():
        threading.Thread(target=stdin_chat, args=(asyncio.get_running_loop(), peer), daemon=True).start()
    try:
        await serve_http(peer, args)
    finally:
        await peer.stop()


def build_parser():
    ap = argparse.ArgumentParser(description="P2P UDP overlay / virtual LAN peer with live dashboard")
    ap.add_argument("--server", help="rendezvous server host:port (default 127.0.0.1:9000)")
    ap.add_argument("--room", help="network name; all players must use the same one (default 'demo')")
    ap.add_argument("--password", help="network password (optional, must match)")
    ap.add_argument("--name", help="display name (default: computer name)")
    ap.add_argument("--host", action="store_true",
                    help="host the network: run the rendezvous server in this process (with --room/--password)")
    ap.add_argument("--host-port", type=int, default=9000, help="UDP port when hosting (default 9000)")
    ap.add_argument("--no-upnp", action="store_true", help="when hosting, don't ask the router to open the port")
    ap.add_argument("--code", help="join a hosted network with its 10-digit code (network name in --room)")
    ap.add_argument("--vlan", action="store_true",
                    help="create the virtual LAN adapter (needs admin/root) so LAN games can see each other")
    ap.add_argument("--bind", default="0.0.0.0", help="UDP bind address")
    ap.add_argument("--udp-port", type=int, default=0, help="UDP tunnel port (default: any free port)")
    ap.add_argument("--http-host", default="127.0.0.1", help="dashboard bind address")
    ap.add_argument("--http-port", type=int, default=8080, help="dashboard port (default 8080)")
    ap.add_argument("--punch-timeout", type=float, default=5.0, help="seconds to punch before relay fallback")
    ap.add_argument("--relay-retry", type=float, default=30.0,
                    help="while on relay, retry direct every N seconds (0 = never)")
    ap.add_argument("--block-direct", action="store_true",
                    help="simulate a NAT that can't be punched: drop all direct packets from the start")
    ap.add_argument("--config", help="settings file to remember the last network (used by the app)")
    ap.add_argument("--open", action="store_true", help="open the dashboard in a browser")
    ap.add_argument("--verbose", "-v", action="store_true", help="log every packet decision")
    ap.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)  # set by relaunch_as_admin()
    ap.set_defaults(app_mode=False)
    return ap


def setup_logging(verbose, logfile=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # Windows consoles + non-ASCII chat
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    if logfile:
        Path(logfile).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers or None,
                        format="%(asctime)s.%(msecs)03d [%(name)s] %(message)s", datefmt="%H:%M:%S")
    for noisy in ("asyncio", "uvicorn", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main():
    args = build_parser().parse_args()
    if args.vlan:
        import vnet
        if vnet.relaunch_as_admin():
            return  # the administrator copy takes over
    setup_logging(args.verbose)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
