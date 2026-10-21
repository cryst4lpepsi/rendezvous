#!/usr/bin/env python3
"""
app.py - the desktop app (what Rendezvous.exe runs).

Same engine as peer.py, set up like Radmin VPN / Hamachi:
  - creates the virtual LAN adapter (needs administrator rights),
  - shows a "join network" screen and remembers the last network,
  - opens the dashboard in its own window (Microsoft Edge in app mode, which
    every Windows 10/11 PC has; falls back to the default browser),
  - quits when that window is closed, and allows only one copy at a time.
Settings and a log file live in %APPDATA%\\Rendezvous.
"""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import traceback
import webbrowser
from pathlib import Path

import peer


def app_dir():
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.path.expanduser("~/.config")
    d = Path(base or Path.home()) / "Rendezvous"
    d.mkdir(parents=True, exist_ok=True)
    return d


def free_port(start):
    for port in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def find_edge():
    candidates = [shutil.which("msedge")]
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        if os.environ.get(env):
            candidates.append(os.path.join(os.environ[env], "Microsoft", "Edge", "Application", "msedge.exe"))
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def open_window(url):
    edge = find_edge()
    if edge:
        # --app gives a plain window with no tabs or address bar; a separate
        # profile directory keeps it independent from the user's own Edge.
        subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={app_dir() / 'window'}",
                          "--window-size=1500,950", "--no-first-run", "--no-default-browser-check"])
    else:
        webbrowser.open(url)


def already_running():
    """One copy at a time: a second copy would fight over the adapter. If one
    is running, just bring up its window."""
    if sys.platform != "win32":
        return False
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\RendezvousVirtualLAN")
    if ctypes.windll.kernel32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return False
    try:
        open_window((app_dir() / "url.txt").read_text().strip())
    except OSError:
        pass
    return True


def fatal(msg):
    try:
        (app_dir() / "crash.log").write_text(msg, encoding="utf-8")
    except OSError:
        pass
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg[-1500:], "Rendezvous failed to start", 0x10)
    else:
        print(msg, file=sys.stderr)


def main():
    ap = peer.build_parser()
    ap.add_argument("--no-vlan", action="store_true", help="don't create the virtual adapter (chat/demo only)")
    ap.add_argument("--no-window", action="store_true", help="don't open a window; keep running until Ctrl+C")
    args = ap.parse_args()
    args.app_mode = True
    args.vlan = not args.no_vlan
    args.exit_when_closed = not args.no_window
    args.config = args.config or str(app_dir() / "config.json")
    args.http_port = free_port(args.http_port)
    peer.setup_logging(args.verbose, logfile=app_dir() / "rendezvous.log")

    if already_running():
        return

    def ready(url):
        (app_dir() / "url.txt").write_text(url)
        if not args.no_window:
            open_window(url)

    try:
        asyncio.run(peer.run(args, on_ready=ready))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        fatal(traceback.format_exc())
        sys.exit(1)
