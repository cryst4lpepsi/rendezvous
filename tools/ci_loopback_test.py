"""
ci_loopback_test.py - end-to-end test on one machine (used by CI on Windows).

Starts the rendezvous server and three peers on loopback, then checks that
every pair reaches DIRECT, that Force Relay / Re-punch work, and that chat
arrives. Optionally (--exe PATH) also launches the built app and checks it
joins and brings up its virtual LAN.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import hosting  # noqa: E402
PY = sys.executable
procs = []


def start(args, log):
    f = open(ROOT / log, "w")
    p = subprocess.Popen(args, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    procs.append(p)
    return p


def api(port, path="/api/state", body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


def wait(cond, timeout, what):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = cond()
            if last is True:
                print(f"[PASS] {what}", flush=True)
                return True
        except OSError as e:
            last = e
        time.sleep(0.5)
    print(f"[FAIL] {what} (last: {last})", flush=True)
    return False


def states(port):
    return sorted(p["state"] for p in api(port)["peers"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", help="also test this built Rendezvous executable")
    args = ap.parse_args()
    ok = []
    start([PY, "rendezvous_server.py", "--port", "9100", "--http-port", "0"], "ci-server.log")
    time.sleep(1)
    ports = {"alice": 8180, "bob": 8181, "carol": 8182}
    for name, port in ports.items():
        start([PY, "peer.py", "--server", "127.0.0.1:9100", "--room", "ci", "--name", name,
               "--http-port", str(port)], f"ci-{name}.log")

    for name, port in ports.items():
        ok.append(wait(lambda port=port: states(port) == ["DIRECT", "DIRECT"], 20,
                       f"{name} reaches DIRECT with both other peers"))

    api(8180, "/api/cmd", {"cmd": "force_relay"})
    ok.append(wait(lambda: states(8180) == ["RELAY", "RELAY"], 5, "alice Force Relay -> both links RELAY"))
    api(8180, "/api/cmd", {"cmd": "chat", "text": "ci hello"})
    ok.append(wait(lambda: any(c["text"] == "ci hello" and c["path"] == "relay" for c in
                               json.loads(urllib.request.urlopen("http://127.0.0.1:8181/api/state").read())["chat"]),
                   5, "chat from alice arrives at bob via relay"))
    api(8180, "/api/cmd", {"cmd": "repunch"})
    ok.append(wait(lambda: states(8180) == ["DIRECT", "DIRECT"], 8, "Re-punch -> back to DIRECT"))

    # Host mode, no separate server: one peer hosts, another joins with network name + code.
    start([PY, "peer.py", "--host", "--no-upnp", "--host-port", "9300", "--room", "Host CI",
           "--name", "hoster", "--http-port", "8380"], "ci-hoster.log")
    ok.append(wait(lambda: bool(api(8380)["code"]), 20, "host mode: hoster gets a 10-digit code"))
    code = api(8380)["code"]
    print(f"       code: {api(8380)['code_display']}", flush=True)
    ok.append(len(code.split(":")[0]) == 10 and code.split(":")[0].isdigit())
    start([PY, "peer.py", "--room", "host ci", "--code", code, "--name", "joiner", "--http-port", "8381"],
          "ci-joiner.log")
    ok.append(wait(lambda: states(8381) == ["DIRECT"] and states(8380) == ["DIRECT"], 20,
                   "host mode: joiner connects with network name + code, DIRECT both ways"))
    start([PY, "peer.py", "--room", "not the name", "--code", code, "--name", "intruder", "--http-port", "8382"],
          "ci-intruder.log")
    ok.append(wait(lambda: api(8382)["joined"] is False and len(api(8380)["peers"]) == 1, 20,
                   "host mode: wrong network name doesn't get in, and gives up"))

    if sys.platform == "win32":
        gw = hosting.default_gateway()
        print(f"       default gateway from 'route print': {gw}", flush=True)
        ok.append(bool(gw))
        print(f"[{'PASS' if ok[-1] else 'FAIL'}] Windows: router address found", flush=True)
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=Rendezvous app"],
                           capture_output=True, text=True)
        ok.append(r.returncode == 0 and "Rendezvous app" in r.stdout)
        print(f"[{'PASS' if ok[-1] else 'FAIL'}] Windows: hosting added the firewall rule for the app", flush=True)

    if args.exe:
        # The app is a Qt window; --api adds the JSON API so the test can watch it.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        start([args.exe, "--api", "--server", "127.0.0.1:9100", "--room", "ci", "--name", "exe",
               "--http-port", "8190"], "ci-exe.log")
        ok.append(wait(lambda: len(api(8190)["peers"]) == 3 and all(p["state"] == "DIRECT" for p in api(8190)["peers"]),
                       40, "built exe joins and goes DIRECT with all 3 peers"))
        ok.append(wait(lambda: api(8190)["vnet"]["status"] == "up", 30,
                       "built exe brings up its virtual LAN adapter"))
        print("exe vnet:", api(8190)["vnet"], flush=True)
        try:
            html = urllib.request.urlopen("http://127.0.0.1:8190/", timeout=3).read()
            ok.append(b"Join a network" in html)
            print(f"[{'PASS' if ok[-1] else 'FAIL'}] built exe serves the dashboard", flush=True)
        except OSError as e:
            ok.append(False)
            print(f"[FAIL] built exe serves the dashboard: {e}")

    for p in procs:
        if sys.platform == "win32":
            # A one-file exe is a launcher plus a child process: kill the whole tree.
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            p.terminate()
    time.sleep(1)
    print(f"{sum(ok)}/{len(ok)} checks passed")
    if not all(ok):
        for log in sorted(ROOT.glob("ci-*.log")):
            print(f"----- {log.name} (tail)\n" + "\n".join(log.read_text(errors="replace").splitlines()[-25:]))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
