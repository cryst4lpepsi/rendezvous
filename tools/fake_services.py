#!/usr/bin/env python3
"""
fake_services.py - local stand-ins for the two public services a host behind
CGNAT uses (see hosting.py), so the hole-punching path can be tested in the
NAT lab without internet access:

  - a tiny ntfy.sh-compatible mailbox: POST /<topic>, GET /<topic>/json?poll=1&since=..,
    GET /<topic>/json?since=.. (streaming)
  - STUN binding responders (XOR-MAPPED-ADDRESS) on the given addresses

  python3 tools/fake_services.py --http 203.0.113.10:8080 --stun 203.0.113.10:3478 --stun 203.0.113.11:3478
Then point the app at them:
  RENDEZVOUS_MAILBOX=http://203.0.113.10:8080 RENDEZVOUS_STUN=203.0.113.10:3478,203.0.113.11:3478
"""
import argparse
import json
import socket
import struct
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAGIC = b"\x21\x12\xa4\x42"
messages = {}  # topic -> list of message dicts
cond = threading.Condition()
counter = [0]


def stun_responder(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host, port))
    while True:
        data, (ip, p) = s.recvfrom(2048)
        if len(data) < 20 or data[0:2] != b"\x00\x01" or data[4:8] != MAGIC:
            continue
        val = struct.pack("!BBH", 0, 1, p ^ 0x2112) + bytes(a ^ b for a, b in zip(socket.inet_aton(ip), MAGIC))
        attr = struct.pack("!HH", 0x0020, len(val)) + val
        s.sendto(b"\x01\x01" + struct.pack("!H", len(attr)) + MAGIC + data[8:20] + attr, (ip, p))


def after(msgs, since):
    if since in (None, "", "all"):
        return list(msgs)
    if since[-1:] in "smhd" and since[:-1].isdigit():
        horizon = time.time() - int(since[:-1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[since[-1]]
        return [m for m in msgs if m["time"] >= horizon]
    if since.isdigit() and len(since) >= 9:
        return [m for m in msgs if m["time"] >= int(since)]
    ids = [m["id"] for m in msgs]
    return msgs[ids.index(since) + 1:] if since in ids else list(msgs)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_POST(self):
        topic = self.path.strip("/").split("/")[0]
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        with cond:
            counter[0] += 1
            m = {"id": f"m{counter[0]}", "time": int(time.time()), "event": "message", "topic": topic,
                 "message": body}
            messages.setdefault(topic, []).append(m)
            cond.notify_all()
        self._send(json.dumps(m) + "\n")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        topic = u.path.strip("/").split("/")[0]
        q = urllib.parse.parse_qs(u.query)
        since = q.get("since", [None])[0]
        with cond:
            pending = after(messages.get(topic, []), since)
        if "poll" in q:
            return self._send("".join(json.dumps(m) + "\n" for m in pending))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        sent = {m["id"] for m in pending}
        try:
            self.wfile.write((json.dumps({"event": "open", "topic": topic}) + "\n").encode())
            for m in pending:
                self.wfile.write((json.dumps(m) + "\n").encode())
            self.wfile.flush()
            while True:
                with cond:
                    cond.wait(25)
                    new = [m for m in messages.get(topic, []) if m["id"] not in sent]
                for m in new or [{"event": "keepalive"}]:
                    sent.add(m.get("id"))
                    self.wfile.write((json.dumps(m) + "\n").encode())
                self.wfile.flush()
        except OSError:
            pass

    def _send(self, text):
        data = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", required=True, help="host:port for the mailbox")
    ap.add_argument("--stun", action="append", default=[], help="host:port for a STUN responder (repeatable)")
    a = ap.parse_args()
    for item in a.stun:
        h, p = item.rsplit(":", 1)
        threading.Thread(target=stun_responder, args=(h, int(p)), daemon=True).start()
    h, p = a.http.rsplit(":", 1)
    print(f"fake mailbox on http://{a.http}, STUN on {', '.join(a.stun)}", flush=True)
    ThreadingHTTPServer((h, int(p)), Handler).serve_forever()


if __name__ == "__main__":
    main()
