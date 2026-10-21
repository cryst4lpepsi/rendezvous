"""
wintun_smoke.py - check the virtual adapter on a real machine (run as admin/root).

Creates the adapter, gives it 10.77.0.9/24, and pretends to be a remote player
at 10.77.0.50 by reading and writing raw packets:
  1. outbound unicast   OS sends UDP to 10.77.0.50   -> we must read it from the adapter
  2. outbound broadcast 255.255.255.255 + 10.77.0.255 -> must come out of the adapter
  3. outbound multicast 224.0.2.60 (Minecraft LAN)  -> must come out of the adapter
  4. inbound UDP        we inject 10.77.0.50 -> 10.77.0.9:5000, a socket must receive it
  5. inbound ping       we inject an ICMP echo request, the OS must answer through the adapter
Exit code 1 if anything fails.
"""
import queue
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import vnet  # noqa: E402

ME, REMOTE = "10.77.0.9", "10.77.0.50"
packets = queue.Queue()


def csum(b):
    if len(b) % 2:
        b += b"\0"
    s = sum(struct.unpack(f"!{len(b) // 2}H", b))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def ipv4(src, dst, proto, payload):
    hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), 1, 0, 64, proto, 0,
                      socket.inet_aton(src), socket.inet_aton(dst))
    return hdr[:10] + struct.pack("!H", csum(hdr)) + hdr[12:] + payload


def udp(src, dst, sport, dport, data):
    return ipv4(src, dst, 17, struct.pack("!HHHH", sport, dport, 8 + len(data), 0) + data)  # checksum 0 = none


def icmp_echo(src, dst, ident, seq, data):
    h = struct.pack("!BBHHH", 8, 0, 0, ident, seq) + data
    return ipv4(src, dst, 1, h[:2] + struct.pack("!H", csum(h)) + h[4:])


def wait_for(pred, timeout=4.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            p = packets.get(timeout=max(0.05, end - time.time()))
        except queue.Empty:
            break
        if len(p) >= 20 and p[0] >> 4 == 4 and pred(p):
            return p
    return None


def is_udp_to(dst, port, payload):
    def f(p):
        ihl = (p[0] & 0xF) * 4
        return p[9] == 17 and p[16:20] == socket.inet_aton(dst) and \
            struct.unpack("!H", p[ihl + 2:ihl + 4])[0] == port and p[ihl + 8:] == payload
    return f


def main():
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)

    t0 = time.time()
    a = vnet.open_adapter()
    a.start(packets.put)
    a.set_address(ME, 24)
    print(f"adapter '{a.name}' ({a.kind}) up as {ME}/24 in {time.time() - t0:.1f}s", flush=True)
    time.sleep(3)  # let the interface settle (Windows assigns the address asynchronously)
    while not packets.empty():
        packets.get()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ME))
    except OSError:
        pass

    # Windows may still be finishing the interface setup: a game would simply
    # resend, so allow a few tries and say which one got through.
    for attempt in range(1, 4):
        s.sendto(b"unicast-test", (REMOTE, 4000))
        if wait_for(is_udp_to(REMOTE, 4000, b"unicast-test"), timeout=2.0) is not None:
            check("outbound unicast to 10.77.0.50", True, f"(attempt {attempt})")
            break
    else:
        check("outbound unicast to 10.77.0.50", False, "(3 attempts)")

    s.sendto(b"subnet-bcast", ("10.77.0.255", 4445))
    check("outbound subnet broadcast 10.77.0.255", wait_for(is_udp_to("10.77.0.255", 4445, b"subnet-bcast")) is not None)

    # A game that doesn't pick an interface: relies on the adapter being preferred (metric 1).
    s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s2.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for name, dst, data in (("limited broadcast 255.255.255.255", "255.255.255.255", b"limited-bcast"),
                            ("multicast 224.0.2.60", "224.0.2.60", b"[MOTD]smoke[/MOTD][AD]25565[/AD]")):
        try:
            s2.sendto(data, (dst, 4445))
            check(f"outbound {name} (unbound socket)", wait_for(is_udp_to(dst, 4445, data)) is not None)
        except OSError as e:
            check(f"outbound {name} (unbound socket)", False, f"send failed: {e}")

    r = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r.bind((ME, 5000))
    r.settimeout(4)
    a.write(udp(REMOTE, ME, 6000, 5000, b"inbound-test"))
    try:
        data, src = r.recvfrom(100)
        check("inbound UDP injected into adapter", data == b"inbound-test", f"from {src}")
    except socket.timeout:
        check("inbound UDP injected into adapter", False, "(nothing received - firewall?)")

    a.write(icmp_echo(REMOTE, ME, 0x4242, 1, b"ping-test"))
    reply = wait_for(lambda p: p[9] == 1 and p[16:20] == socket.inet_aton(REMOTE) and p[20] == 0)
    check("OS answers ping through the adapter", reply is not None)

    a.close()
    print(f"{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
