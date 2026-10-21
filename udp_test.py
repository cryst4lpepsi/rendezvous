#!/usr/bin/env python3
"""
udp_test.py - tiny UDP tool to prove passthrough mode works (Windows has no netcat).

  python udp_test.py echo 5555                 # a "game server": echoes every datagram
  python udp_test.py send 127.0.0.1:7000       # a "game client": sends a numbered packet
                                               # every second and prints the echo + RTT
"""
import socket
import sys
import time


def echo(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", port))
    print(f"echoing UDP on port {port}")
    while True:
        data, addr = s.recvfrom(65535)
        print(f"echo {len(data)} bytes back to {addr[0]}:{addr[1]}: {data[:60]!r}")
        s.sendto(data, addr)


def send(target, count):
    host, port = target.rsplit(":", 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.0)
    ok = 0
    for i in range(1, count + 1):
        t0 = time.perf_counter()
        s.sendto(f"packet {i} @ {time.strftime('%H:%M:%S')}".encode(), (host, int(port)))
        try:
            data, _ = s.recvfrom(65535)
            ok += 1
            print(f"reply {data.decode(errors='replace')!r} rtt={(time.perf_counter() - t0) * 1000:.1f} ms")
        except (socket.timeout, ConnectionResetError):
            print(f"packet {i}: no reply")
        time.sleep(1)
    print(f"{ok}/{count} replies")
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("echo", "send"):
        sys.exit(__doc__)
    if sys.argv[1] == "echo":
        echo(int(sys.argv[2]))
    else:
        sys.exit(0 if send(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 5) else 1)
