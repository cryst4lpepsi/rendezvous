#!/usr/bin/env python3
"""
app.py - the desktop app (what Rendezvous.exe runs). A native Qt window, no browser.

Same engine as peer.py, set up like Radmin VPN / Hamachi:
  - creates the virtual LAN adapter (needs administrator rights),
  - a "Join network" dialog, and remembers the last network,
  - a live view of every connection: who is DIRECT, who is on RELAY, punch
    attempts, keepalives, and buttons to force path changes for a demo,
  - one copy at a time; closing the window leaves the network and removes the adapter.
Settings and a log file live in %APPDATA%\\Rendezvous.

Threads: Qt owns the main thread. The engine (peer.Peer, asyncio) runs in a
background thread. Engine -> UI: every event/state update is emitted as a Qt
signal (Qt queues it onto the UI thread). UI -> engine: commands are handed to
the asyncio loop with call_soon_threadsafe.
"""

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap, QShortcut)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTextEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

import hosting
import peer

log = logging.getLogger("app")

BG, CARD, CARD2, LINE = "#0a0e14", "#111821", "#0d131b", "#1e2936"
TEXT, MUTED, FAINT = "#e6edf3", "#8b98a5", "#3a4756"
GREEN, AMBER, CYAN, RED, SLATE = "#22c55e", "#f59e0b", "#38bdf8", "#f43f5e", "#94a3b8"
STATE_COLOR = {"DIRECT": GREEN, "RELAY": AMBER, "PUNCHING": CYAN, "RECONNECTING": RED,
               "DISCOVERING": SLATE, "GONE": RED}
RANK = {"RECONNECTING": 4, "PUNCHING": 3, "DISCOVERING": 2, "RELAY": 1, "DIRECT": 0}
SHORT = {"DIRECT": "DIRECT", "RELAY": "RELAY", "PUNCHING": "PUNCH", "RECONNECTING": "RECONN", "DISCOVERING": "NEW"}
INSTANCE_NAME = "RendezvousVirtualLAN"


def app_dir():
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.path.expanduser("~/.config")
    d = Path(base or Path.home()) / "Rendezvous"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fmt_bytes(n):
    n = n or 0
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB" if n < 1048576 else f"{n / 1048576:.2f} MB"


def rgba(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def worst_state(peers):
    return max((p["state"] for p in peers), key=lambda s: RANK.get(s, 0), default=None)


# ===================================================================== engine
class Engine(QObject):
    """Runs peer.Peer on its own asyncio thread and relays its updates as a signal."""
    message = Signal(object)

    def __init__(self, args):
        super().__init__()
        self.args = args
        self.loop = None
        self.peer = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="engine", daemon=True)

    def start(self):
        self.thread.start()
        self.ready.wait(20)

    def _run(self):
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("engine crashed")
            self.message.emit({"type": "fatal", "error": traceback.format_exc()})
        finally:
            self.ready.set()

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        p = self.peer = peer.Peer(self.args)
        p.listeners.append(self.message.emit)
        await p.start()
        peer.autojoin(p, self.args)
        if self.args.api:  # JSON API + web dashboard, used by automated tests
            asyncio.ensure_future(peer.serve_http(p, self.args))
        self.ready.set()
        await p.stopped.wait()
        await p.stop()

    def command(self, **m):
        if self.loop and self.peer:
            self.loop.call_soon_threadsafe(self.peer.command, m)

    def shutdown(self):
        if self.loop and self.peer and self.thread.is_alive():
            self.loop.call_soon_threadsafe(self.peer.quit)
            self.thread.join(6)


# =================================================================== topology
class Topology(QWidget):
    """The live picture: you, the rendezvous server, every player, and the path
    each link is using right now. Drawn in a 1000x500 virtual canvas."""
    selected = Signal(object)

    ME = QPointF(150, 280)
    SRV = QPointF(500, 92)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 300)
        self.s = None
        self.sel = None
        self.nodes = {}     # id -> dict(pos, r, direct, relay paths)
        self.anims = []     # moving packets and bursts
        self.phase = 0.0
        self.banner = None  # (text, color, started)
        self.timer = QTimer(self, interval=33, timeout=self._frame)
        self.timer.start()

    # ------------------------------------------------------------- state
    def set_state(self, s):
        self.s = s
        ids = [p["id"] for p in s["peers"]]
        if ids != list(self.nodes):
            self._layout(ids)

    def _layout(self, ids):
        self.nodes = {}
        n = len(ids)
        r = 46 if n <= 2 else 36 if n <= 4 else 27
        top, bottom = 100, 430
        for i, pid in enumerate(ids):
            pos = QPointF(760, 280 if n == 1 else top + i * (bottom - top) / (n - 1))
            direct = QPainterPath(self.ME)
            direct.lineTo(pos)
            relay = QPainterPath(self.ME)
            top_y = self.SRV.y() + 34
            relay.cubicTo(QPointF(self.ME.x() + 60, self.ME.y() - 150), QPointF(self.SRV.x() - 150, top_y),
                          QPointF(self.SRV.x(), top_y))
            relay.cubicTo(QPointF(self.SRV.x() + 150, top_y), QPointF(pos.x() - 60, max(30, pos.y() - 150)), pos)
            self.nodes[pid] = {"pos": pos, "r": r, "direct": direct, "relay": relay}

    def peer(self, pid):
        if not self.s:
            return None
        return next((p for p in self.s["peers"] if p["id"] == pid), None)

    # -------------------------------------------------------- animations
    def pulse(self, m):
        nd, p = self.nodes.get(m.get("peer")), self.peer(m.get("peer"))
        if not nd or not p or not m.get("path") or not self.isVisible():
            return
        path = nd["direct"] if m["path"] == "direct" else nd["relay"]
        r = 10 if m.get("big") else 4.5 if m.get("data") else 6
        dur = 0.65 if m["path"] == "direct" else 1.0
        out = m.get("dir") == "out"
        if m["path"] == "direct" and p["blackhole"]:  # dies at the X
            self._add(path, 0 if out else 1, 0.5, dur / 2, RED, r, burst=RED)
        else:
            self._add(path, 0 if out else 1, 1 if out else 0, dur, GREEN if m["path"] == "direct" else AMBER, r)

    def punch(self, m):
        nd, p = self.nodes.get(m.get("peer")), self.peer(m.get("peer"))
        if nd and p and self.isVisible():
            color = RED if p["state"] == "RECONNECTING" or p["blackhole"] else CYAN
            self._add(nd["direct"], 0, 0.5 if p["blackhole"] else 0.42, 0.42, color, 6, burst=color)

    def transition(self, m):
        self.banner = (f"{m.get('name')}: {m['from']} → {m['to']}", STATE_COLOR.get(m["to"], SLATE), time.time())
        nd = self.nodes.get(m.get("peer"))
        if not nd:
            return
        if m["to"] == "DIRECT":
            self._burst(self.ME, GREEN, 62, 110, 0.8)
            self._burst(nd["pos"], GREEN, nd["r"], nd["r"] + 50, 0.8)
        elif m["to"] == "RELAY":
            self._burst(self.SRV, AMBER, 40, 130, 0.8)
        elif m["to"] == "RECONNECTING":
            self._burst(nd["direct"].pointAtPercent(0.5), RED, 10, 80, 0.7)

    def _add(self, path, a, b, dur, color, r, burst=None):
        self.anims.append({"kind": "pkt", "path": path, "a": a, "b": b, "t0": time.time(), "dur": dur,
                           "color": QColor(color), "r": r, "burst": burst})

    def _burst(self, pt, color, r0, r1, dur):
        self.anims.append({"kind": "burst", "pt": QPointF(pt), "t0": time.time(), "dur": dur,
                           "color": QColor(color), "r0": r0, "r1": r1})

    def _frame(self):
        self.phase = (self.phase + 0.9) % 1000
        now = time.time()
        keep = []
        for a in self.anims:
            if now - a["t0"] < a["dur"]:
                keep.append(a)
            elif a["kind"] == "pkt" and a["burst"]:
                self._burst(a["path"].pointAtPercent(a["b"]), a["burst"], 4, 22, 0.4)
                keep.append(self.anims[-1])
        self.anims = keep[-300:]
        self.update()

    # ----------------------------------------------------------- painting
    def _transform(self):
        scale = min(self.width() / 1000, self.height() / 500)
        return scale, (self.width() - 1000 * scale) / 2, (self.height() - 500 * scale) / 2

    def mousePressEvent(self, e):
        scale, ox, oy = self._transform()
        x, y = (e.position().x() - ox) / scale, (e.position().y() - oy) / scale
        for pid, nd in self.nodes.items():
            if (x - nd["pos"].x()) ** 2 + (y - nd["pos"].y()) ** 2 <= (nd["r"] + 8) ** 2:
                self.selected.emit(pid)
                return
        self.selected.emit(None)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(CARD))
        s = self.s
        scale, ox, oy = self._transform()
        p.translate(ox, oy)
        p.scale(scale, scale)
        if not s:
            p.end()
            return
        peers = s["peers"]
        blink = int(time.time() * 4) % 2 == 0

        # server
        any_relay = any(x["state"] != "DIRECT" for x in peers)
        box = QRectF(self.SRV.x() - 125, self.SRV.y() - 36, 250, 70)
        pen = QPen(QColor(RED if s["server_ok"] is False else AMBER if any_relay and s["joined"] else FAINT), 3)
        if s["server_ok"] is False:
            pen.setStyle(Qt.DashLine)

        # links (under the nodes)
        for x in peers:
            nd = self.nodes.get(x["id"])
            if nd:
                self._draw_link(p, nd, x, blink)

        p.setPen(pen)
        p.setBrush(QColor(CARD2))
        p.drawRoundedRect(box, 16, 16)
        self._text(p, QRectF(box.x(), box.y() + 12, box.width(), 22), "RENDEZVOUS · RELAY", TEXT, 14, True,
                   Qt.AlignHCenter, spacing=2)
        where = (f"on this PC · UDP {s['hosting']['port']}" if s.get("hosting") else s["server"])
        self._text(p, QRectF(box.x(), box.y() + 36, box.width(), 20),
                   where + ("   ✕ unreachable" if s["server_ok"] is False else ""), MUTED, 13,
                   align=Qt.AlignHCenter, mono=True)

        # you
        worst = worst_state(peers)
        self._node(p, self.ME, 60, STATE_COLOR[worst] if worst else SLATE, 1.2)
        self._text(p, QRectF(self.ME.x() - 100, self.ME.y() - 90, 200, 18), "YOU", MUTED, 12, True, Qt.AlignHCenter,
                   spacing=3)
        self._text(p, QRectF(self.ME.x() - 150, self.ME.y() + 68, 300, 30), s["me"]["name"], TEXT, 22, True,
                   Qt.AlignHCenter)
        self._text(p, QRectF(self.ME.x() - 150, self.ME.y() + 98, 300, 22), s["me"]["vip"] or "", MUTED, 15,
                   align=Qt.AlignHCenter, mono=True)

        # players
        for x in peers:
            nd = self.nodes.get(x["id"])
            if not nd:
                continue
            pos, r = nd["pos"], nd["r"]
            color = STATE_COLOR.get(x["state"], SLATE)
            self._node(p, pos, r, color, r / 50, thick=7 if self.sel == x["id"] else 4)
            tx = pos.x() + r + 12
            fs = 20 if r > 40 else 16 if r > 30 else 14
            self._text(p, QRectF(tx, pos.y() - fs - 10, 200, fs + 8), x["name"], TEXT, fs, True)
            self._text(p, QRectF(tx, pos.y() - 2, 200, 18), x["vip"] or "", MUTED, 13, mono=True)
            rtt = f"  {x['rtt_ms']:.1f} ms" if x["rtt_ms"] is not None else ""
            self._text(p, QRectF(tx, pos.y() + 16, 220, 16), x["state"] + rtt, color, 11, True, spacing=1.5)

        if not peers:
            pen = QPen(QColor(SLATE), 3, Qt.DashLine)
            pen.setDashOffset(-self.phase / 6)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.setOpacity(0.45)
            p.drawEllipse(QPointF(760, 280), 50, 50)
            msg = "waiting for players…" if s["joined"] else "not connected"
            self._text(p, QRectF(610, 345, 300, 30), msg, MUTED, 18, align=Qt.AlignHCenter)
            p.setOpacity(1)

        # moving packets and bursts
        now = time.time()
        for a in self.anims:
            k = min(1.0, (now - a["t0"]) / a["dur"])
            if a["kind"] == "pkt":
                e = 2 * k * k if k < 0.5 else 1 - (-2 * k + 2) ** 2 / 2
                pt = a["path"].pointAtPercent(max(0.0, min(1.0, a["a"] + (a["b"] - a["a"]) * e)))
                p.setOpacity(1 if k < 0.85 else (1 - k) / 0.15)
                p.setPen(Qt.NoPen)
                p.setBrush(a["color"])
                p.drawEllipse(pt, a["r"], a["r"])
            else:
                p.setOpacity(1 - k)
                p.setPen(QPen(a["color"], 3))
                p.setBrush(Qt.NoBrush)
                rr = a["r0"] + (a["r1"] - a["r0"]) * k
                p.drawEllipse(a["pt"], rr, rr)
        p.setOpacity(1)

        # transition banner, bottom centre
        if self.banner and now - self.banner[2] < 2.4:
            text, color, t0 = self.banner
            p.setOpacity(min(1.0, (2.4 - (now - t0)) / 0.3))
            f = QFont(self.font())
            f.setPixelSize(26)
            f.setBold(True)
            w = QFontMetrics(f).horizontalAdvance(text) + 50
            rect = QRectF(500 - w / 2, 430, w, 54)
            p.setPen(QPen(QColor(color), 2))
            p.setBrush(QColor(BG))
            p.drawRoundedRect(rect, 14, 14)
            p.setFont(f)
            p.drawText(rect, Qt.AlignCenter, text)
            p.setOpacity(1)
        p.end()

    def _draw_link(self, p, nd, x, blink):
        st = x["state"]
        direct, relay = nd["direct"], nd["relay"]

        def track(path, color=FAINT, width=2.5, opacity=0.5):
            pen = QPen(QColor(color), width, Qt.CustomDashLine)
            pen.setDashPattern([2.4, 4])
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.setOpacity(opacity)
            p.drawPath(path)
            p.setOpacity(1)

        def active(path, color, opacity=1.0, glow=True):
            p.setBrush(Qt.NoBrush)
            if glow:
                p.setOpacity(0.14 * opacity)
                p.setPen(QPen(QColor(color), 16, Qt.SolidLine, Qt.RoundCap))
                p.drawPath(path)
            p.setOpacity(opacity)
            p.setPen(QPen(QColor(color), 4, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            dots = QPen(QColor(color), 7, Qt.CustomDashLine, Qt.RoundCap)
            dots.setDashPattern([0.01, 3.2])
            dots.setDashOffset(-self.phase / 7)
            p.setPen(dots)
            p.drawPath(path)
            p.setOpacity(1)

        if st == "DIRECT":
            track(relay, opacity=0.18)
            active(direct, GREEN)
        else:
            active(relay, AMBER, 1.0 if st == "RELAY" else 0.4, glow=st == "RELAY")
            if st == "PUNCHING":
                track(direct, CYAN, 3, 1 if blink else 0.3)
            elif st == "RECONNECTING":
                track(direct, RED, 3.5, 1 if blink else 0.3)
            else:
                track(direct)
        if x["blackhole"]:
            m = direct.pointAtPercent(0.5)
            p.setPen(QPen(QColor(RED), 6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(m + QPointF(-14, -14), m + QPointF(14, 14))
            p.drawLine(m + QPointF(14, -14), m + QPointF(-14, 14))

    def _node(self, p, c, r, color, icon_scale, thick=4):
        p.setPen(QPen(QColor(color), thick))
        p.setBrush(QColor(CARD2))
        p.drawEllipse(c, r, r)
        p.save()
        p.translate(c)
        p.scale(icon_scale, icon_scale)
        p.setPen(QPen(QColor(TEXT), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-24, -20, 48, 31), 3, 3)
        base = QPainterPath(QPointF(-32, 18))
        for pt in ((32, 18), (26, 11), (-26, 11)):
            base.lineTo(*pt)
        base.closeSubpath()
        p.drawPath(base)
        p.restore()

    def _text(self, p, rect, text, color, size, bold=False, align=Qt.AlignLeft, mono=False, spacing=0):
        f = QFont("Consolas" if mono else self.font().family())
        if mono:
            f.setStyleHint(QFont.Monospace)
        f.setPixelSize(size)
        f.setBold(bold)
        if spacing:
            f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(rect, align | Qt.AlignVCenter, text)


# ================================================================ join dialog
class StartDialog(QDialog):
    """Host a network, or join one with its name and code."""

    def __init__(self, parent, saved, my_name, page="choose"):
        super().__init__(parent)
        self.setWindowTitle("Rendezvous")
        self.setMinimumWidth(500)
        self.result_cmd = None
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.addWidget(self.stack)
        name = saved.get("name") or my_name or ""

        # --- page 0: choose
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        t = QLabel("Play LAN games over the internet")
        t.setObjectName("dialogTitle")
        v.addWidget(t)
        sub = QLabel("One player hosts a network and gets a short code. "
                     "Everyone else joins with the network name and that code.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        v.addWidget(sub)
        for title, text, page_i in (("Host a network", "Create a network on this PC and invite your friends.", 1),
                                    ("Join a network", "Enter the network name and code a friend gave you.", 2)):
            b = QPushButton(f"{title}\n{text}")
            b.setObjectName("choice")
            b.setMinimumHeight(74)
            b.clicked.connect(lambda _=False, i=page_i: self.stack.setCurrentIndex(i))
            v.addWidget(b)
        v.addStretch(1)
        self.stack.addWidget(w)

        # --- page 1: host
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Host a network")
        t.setObjectName("dialogTitle")
        v.addWidget(t)
        f = QFormLayout()
        self.h_net = QLineEdit(saved.get("network") or "")
        self.h_net.setPlaceholderText("friday-games")
        self.h_name = QLineEdit(name)
        self.h_name.setMaxLength(32)
        f.addRow("Network name", self.h_net)
        f.addRow("Your name", self.h_name)
        v.addLayout(f)
        self.h_upnp = QCheckBox("Open the port on my router automatically (UPnP)")
        self.h_upnp.setChecked(True)
        v.addWidget(self.h_upnp)
        note = QLabel("You'll get a code to give your friends. Keep Rendezvous open while you "
                      "play: the network runs on this PC.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)
        v.addWidget(self._buttons("Start hosting", self._host))
        self.stack.addWidget(w)

        # --- page 2: join
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Join a network")
        t.setObjectName("dialogTitle")
        v.addWidget(t)
        f = QFormLayout()
        self.j_net = QLineEdit(saved.get("network") if saved.get("mode") == "code" else "")
        self.j_net.setPlaceholderText("the host's network name")
        self.j_code = QLineEdit()
        self.j_code.setPlaceholderText("123 456  or  123 456 7890")
        self.j_code.setObjectName("code")
        self.j_name = QLineEdit(name)
        self.j_name.setMaxLength(32)
        f.addRow("Network name", self.j_net)
        f.addRow("Code", self.j_code)
        f.addRow("Your name", self.j_name)
        v.addLayout(f)
        self.j_manual = QCheckBox("Using a rendezvous server instead? Enter its address")
        v.addWidget(self.j_manual)
        man = QWidget()
        mf = QFormLayout(man)
        mf.setContentsMargins(0, 0, 0, 0)
        self.j_server = QLineEdit(saved.get("server") if saved.get("mode") == "join" else "")
        self.j_server.setPlaceholderText("203.0.113.10:9000")
        self.j_pass = QLineEdit()
        self.j_pass.setEchoMode(QLineEdit.Password)
        self.j_pass.setPlaceholderText("optional")
        mf.addRow("Server", self.j_server)
        mf.addRow("Password", self.j_pass)
        man.setVisible(False)
        self.j_manual.toggled.connect(man.setVisible)
        self.j_manual.toggled.connect(lambda on: self.j_code.setEnabled(not on))
        v.addWidget(man)
        v.addStretch(1)
        v.addWidget(self._buttons("Join", self._join))
        self.stack.addWidget(w)

        self.err = QLabel()
        self.err.setObjectName("error")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        self.stack.currentChanged.connect(lambda _: self.err.clear())
        self.stack.setCurrentIndex({"host": 1, "join": 2}.get(page, 0))

    def _buttons(self, ok_text, ok):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 10, 0, 0)
        back = QPushButton("Back")
        back.setObjectName("small")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        h.addWidget(back)
        h.addStretch(1)
        go = QPushButton(ok_text)
        go.setObjectName("primary")
        go.setDefault(True)
        go.clicked.connect(ok)
        h.addWidget(go)
        return row

    def _host(self):
        net = self.h_net.text().strip()
        if not net:
            return self.err.setText("Give your network a name.")
        self.result_cmd = {"cmd": "host", "network": net, "name": self.h_name.text().strip(),
                           "upnp": self.h_upnp.isChecked()}
        self.accept()

    def _join(self):
        name = self.j_name.text().strip()
        net = self.j_net.text().strip()
        if not net:
            return self.err.setText("Enter the network name.")
        if self.j_manual.isChecked():
            server = self.j_server.text().strip()
            host_, _, port = server.partition(":")
            if not host_ or " " in server or (port and not port.isdigit()):
                return self.err.setText("Server should look like 203.0.113.10:9000")
            self.result_cmd = {"cmd": "join", "server": server if ":" in server else server + ":9000",
                               "network": net, "password": self.j_pass.text(), "name": name}
        else:
            try:
                hosting.parse_any(net, self.j_code.text())
            except ValueError as e:
                return self.err.setText(f"Check the code: {e}.")
            self.result_cmd = {"cmd": "join_code", "network": net, "code": self.j_code.text(), "name": name}
        self.accept()


class ShareDialog(QDialog):
    """What the host tells friends: the network name and the code."""

    def __init__(self, parent, network, code, hosting_info, on_retry=None):
        super().__init__(parent)
        self.setWindowTitle("Invite friends")
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(10)
        t = QLabel("Invite friends")
        t.setObjectName("dialogTitle")
        v.addWidget(t)
        how = QLabel("Your friends open Rendezvous, click <b>Join a network</b> and enter:")
        how.setObjectName("muted")
        how.setWordWrap(True)
        v.addWidget(how)
        grid = QFormLayout()
        grid.setHorizontalSpacing(18)
        net = QLabel(esc(network))
        net.setObjectName("shareValue")
        net.setTextInteractionFlags(Qt.TextSelectableByMouse)
        codel = QLabel(esc(code))
        codel.setObjectName("shareCode")
        codel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addRow("Network name", net)
        grid.addRow("Code", codel)
        v.addLayout(grid)
        if hosting_info:
            mode = hosting_info.get("mode")
            col = {"direct": GREEN, "punch": CYAN}.get(mode, AMBER)
            st = QLabel(("\u2713 " if mode in ("direct", "punch") else "\u26a0 ") + esc(hosting_info["status"]))
            st.setWordWrap(True)
            st.setMinimumWidth(470)
            st.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            st.setStyleSheet(f"border-left: 3px solid {col}; background: {rgba(col, 0.1)}; "
                             f"padding: 8px 10px; border-radius: 6px;")
            v.addWidget(st)
        warn = QLabel("Anyone with the network name and code can join, so only share them with friends.")
        warn.setObjectName("muted")
        warn.setWordWrap(True)
        v.addWidget(warn)
        row = QHBoxLayout()
        if hosting_info and hosting_info.get("mode") != "direct" and on_retry:
            retry = QPushButton("Try again")
            retry.setObjectName("small")
            retry.setToolTip("Ask the router to open the port again, e.g. after turning on UPnP")
            retry.clicked.connect(on_retry)
            retry.clicked.connect(self.accept)
            row.addWidget(retry)
        copy = QPushButton("Copy")
        copy.setObjectName("primary")
        done = QLabel()
        done.setObjectName("muted")

        def do_copy():
            QApplication.clipboard().setText(f"Rendezvous network: {network}\nCode: {code}")
            done.setText("Copied ✓")
        copy.clicked.connect(do_copy)
        row.addWidget(copy)
        row.addWidget(done)
        row.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("small")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)


# ================================================================ main window
class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.s = None
        self.sel = None
        self.events = []
        self.join_prompted = False
        self.invite_shown_for = None
        self.reopen_invite = False
        self.was_busy = False
        self.setWindowTitle("Rendezvous")
        self.resize(1440, 900)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(10)

        # header
        head = QHBoxLayout()
        brand = QLabel("RENDEZVOUS")
        brand.setObjectName("brand")
        head.addWidget(brand)
        self.meta = QLabel("not connected")
        self.meta.setObjectName("muted")
        head.addWidget(self.meta)
        head.addStretch(1)
        self.b_relay = self._button("Force Relay", AMBER, "force_relay", "R")
        self.b_punch = self._button("Re-punch", CYAN, "repunch", "P")
        self.b_drop = self._button("Drop Direct", RED, "drop_direct", "D")
        for b in (self.b_relay, self.b_punch, self.b_drop):
            head.addWidget(b)
        self.target = QLabel()
        self.target.setObjectName("muted")
        head.addWidget(self.target)
        self.join_btn = QPushButton("Host or join\u2026")
        self.join_btn.setObjectName("primary")
        self.join_btn.clicked.connect(lambda: self.open_join())
        head.addWidget(self.join_btn)
        self.invite_btn = QPushButton("Invite friends\u2026")
        self.invite_btn.setObjectName("primary")
        self.invite_btn.clicked.connect(self.open_invite)
        head.addWidget(self.invite_btn)
        self.badge = QLabel("OFFLINE")
        self.badge.setObjectName("badge")
        head.addWidget(self.badge)
        outer.addLayout(head)

        # top: topology | side panel
        vsplit = QSplitter(Qt.Vertical)
        hsplit = QSplitter(Qt.Horizontal)
        self.topo = Topology()
        self.topo.selected.connect(self.select)
        hsplit.addWidget(self._card(self.topo, None, margins=0))

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        me = QFrame()
        me.setObjectName("box")
        ml = QVBoxLayout(me)
        row = QHBoxLayout()
        lbl = QLabel("THIS PC")
        lbl.setObjectName("caps")
        row.addWidget(lbl)
        row.addStretch(1)
        self.copy_btn = QPushButton("Copy IP")
        self.copy_btn.setObjectName("small")
        self.copy_btn.clicked.connect(self.copy_ip)
        row.addWidget(self.copy_btn)
        self.leave_btn = QPushButton("Leave")
        self.leave_btn.setObjectName("small")
        self.leave_btn.clicked.connect(lambda: self.engine.command(cmd="leave"))
        row.addWidget(self.leave_btn)
        ml.addLayout(row)
        self.ip = QLabel("–")
        self.ip.setObjectName("bigip")
        self.ip.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ml.addWidget(self.ip)
        self.vstatus = QLabel()
        self.vstatus.setWordWrap(True)
        self.vstatus.setObjectName("vstatus")
        ml.addWidget(self.vstatus)
        self.kv = QLabel()
        self.kv.setObjectName("muted")
        self.kv.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ml.addWidget(self.kv)
        sl.addWidget(me)

        lbl = QLabel("PLAYERS")
        lbl.setObjectName("caps")
        sl.addWidget(lbl)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Player", "Virtual IP", "Status", "RTT", "Out", "In"])
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAlternatingRowColors(False)
        hdr = self.table.header()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setStretchLastSection(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.itemSelectionChanged.connect(self._table_selected)
        sl.addWidget(self.table, 1)

        self.detail = QLabel()
        self.detail.setObjectName("detail")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sl.addWidget(self.detail)
        self.meter = QProgressBar()
        self.meter.setTextVisible(False)
        self.meter.setMaximumHeight(8)
        self.meter.setToolTip("Direct keepalive: time since the last direct packet (dead after 3.5 s)")
        sl.addWidget(self.meter)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("hint")
        sl.addWidget(self.hint)
        hsplit.addWidget(self._card(side, None))
        hsplit.setSizes([900, 500])
        vsplit.addWidget(hsplit)

        # bottom: event log | chat
        bsplit = QSplitter(Qt.Horizontal)
        logw = QWidget()
        ll = QVBoxLayout(logw)
        ll.setContentsMargins(0, 0, 0, 0)
        lh = QHBoxLayout()
        lbl = QLabel("EVENT LOG")
        lbl.setObjectName("caps")
        lh.addWidget(lbl)
        lh.addStretch(1)
        self.show_punch = QCheckBox("show punch attempts")
        self.show_punch.toggled.connect(self._rebuild_log)
        lh.addWidget(self.show_punch)
        ll.addLayout(lh)
        self.log = QTextEdit(readOnly=True)
        self.log.document().setMaximumBlockCount(800)
        ll.addWidget(self.log)
        bsplit.addWidget(self._card(logw, None))

        chatw = QWidget()
        cl = QVBoxLayout(chatw)
        cl.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("CHAT")
        lbl.setObjectName("caps")
        cl.addWidget(lbl)
        self.chat = QTextEdit(readOnly=True)
        cl.addWidget(self.chat)
        crow = QHBoxLayout()
        self.chat_in = QLineEdit()
        self.chat_in.setPlaceholderText("Message everyone in the network…")
        self.chat_in.returnPressed.connect(self.send_chat)
        crow.addWidget(self.chat_in)
        send = QPushButton("Send")
        send.setObjectName("plain")
        send.clicked.connect(self.send_chat)
        crow.addWidget(send)
        cl.addLayout(crow)
        bsplit.addWidget(self._card(chatw, None))
        bsplit.setSizes([900, 500])
        vsplit.addWidget(bsplit)
        vsplit.setSizes([560, 300])
        outer.addWidget(vsplit, 1)

        self.status_v = QLabel()
        self.status_s = QLabel()
        self.statusBar().addWidget(self.status_v, 1)
        self.statusBar().addPermanentWidget(self.status_s)

        menu = self.menuBar().addMenu("&Network")
        menu.addAction(QAction("&Host a network\u2026", self, triggered=lambda: self.open_join("host")))
        menu.addAction(QAction("&Join a network\u2026", self, shortcut=QKeySequence("Ctrl+J"),
                               triggered=lambda: self.open_join("join")))
        menu.addAction(QAction("&Invite friends\u2026", self, triggered=self.open_invite))
        menu.addAction(QAction("&Leave network", self, triggered=lambda: self.engine.command(cmd="leave")))
        menu.addSeparator()
        menu.addAction(QAction("Open &log folder", self, triggered=self.open_logs))
        menu.addSeparator()
        menu.addAction(QAction("&Quit", self, shortcut=QKeySequence("Ctrl+Q"), triggered=self.close))
        for key, cmd in (("R", "force_relay"), ("P", "repunch"), ("D", "drop_direct")):
            QShortcut(QKeySequence(key), self, activated=lambda c=cmd: self._demo(c)).setContext(Qt.WindowShortcut)

        engine.message.connect(self.on_message)

    # ----------------------------------------------------------- widgets
    def _card(self, widget, title, margins=12):
        f = QFrame()
        f.setObjectName("card")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(margins, margins, margins, margins)
        lay.addWidget(widget)
        return f

    def _button(self, text, color, cmd, key):
        b = QPushButton(f"{text}  [{key}]")
        b.setObjectName("demo")
        b.setStyleSheet(f"QPushButton#demo {{ background: {color}; }}")
        b.setToolTip("Applies to the selected player, or to every player if none is selected")
        b.clicked.connect(lambda: self._demo(cmd))
        return b

    def _demo(self, cmd):
        if self.chat_in.hasFocus() or not self.s or not self.s["peers"]:
            return
        if self.sel:
            self.engine.command(cmd=cmd, peer=self.sel)
        else:
            self.engine.command(cmd=cmd)

    # ---------------------------------------------------------- messages
    def on_message(self, m):
        t = m.get("type")
        if t == "state":
            self.render(m)
        elif t == "event":
            self.add_event(m)
        elif t == "chat":
            self.add_chat(m)
        elif t == "transition":
            self.topo.transition(m)
        elif t == "pulse":
            self.topo.pulse(m)
        elif t == "punch":
            self.topo.punch(m)
        elif t == "join_failed":
            QMessageBox.warning(self, "Couldn't join", f"The network refused to let you in: {m['reason']}.")
            self.open_join("join")
        elif t == "fatal":
            QMessageBox.critical(self, "Rendezvous stopped", m["error"][-1500:])

    def render(self, s):
        first = self.s is None
        self.s = s
        peers = s["peers"]
        if self.sel and not any(p["id"] == self.sel for p in peers):
            self.select(None)
        self.topo.set_state(s)

        worst = worst_state(peers)
        counts = {}
        for p in peers:
            counts[p["state"]] = counts.get(p["state"], 0) + 1
        summary = " · ".join(f"{v} {SHORT[k]}" for k, v in sorted(counts.items(), key=lambda kv: -RANK[kv[0]]))
        text = "OFFLINE" if not s["joined"] else summary or "WAITING"
        color = STATE_COLOR[worst] if s["joined"] and worst else SLATE
        self.badge.setText(text)
        self.badge.setStyleSheet(f"color: {color}; border-color: {color}; background: {rgba(color, 0.13)};")
        self.setWindowTitle(f"Rendezvous — {text}")
        me = s["me"]
        self.meta.setText(f"network <b style='color:{TEXT}'>{esc(s['network'])}</b> &nbsp;·&nbsp; you are "
                          f"<b style='color:{TEXT}'>{esc(me['name'])}</b>" if s["joined"] else "not connected")
        self.join_btn.setVisible(not s["joined"] and not s["hosting_busy"])
        self.invite_btn.setVisible(bool(s["joined"] and s["code_display"]))
        self.leave_btn.setVisible(s["joined"])
        self.leave_btn.setText("Stop hosting" if s["hosting"] else "Leave")
        self.copy_btn.setEnabled(bool(me["vip"]))
        for b in (self.b_relay, self.b_punch, self.b_drop):
            b.setEnabled(bool(peers))
        sel = next((p for p in peers if p["id"] == self.sel), None)
        self.target.setText(f"→ {sel['name']}" if sel else ("→ all players" if peers else ""))

        self.ip.setText(me["vip"] or ("…" if s["joined"] else "–"))
        v = s["vnet"]
        vcol = {"up": GREEN, "starting": CYAN, "error": RED}.get(v["status"], FAINT)
        vtext = (f"Virtual LAN up · {v['detail']}" if v["status"] == "up" else
                 f"Virtual LAN unavailable: {v['detail']}" if v["status"] == "error" else v["detail"])
        self.vstatus.setText(vtext)
        self.vstatus.setStyleSheet(f"border-left: 3px solid {vcol}; background: {rgba(vcol, 0.1)};")
        srv = s["server"] + (" \u2713" if s["server_ok"] else " \u2715" if s["server_ok"] is False else "")
        h = s["hosting"]
        if s["hosting_busy"]:
            role = f"<b style='color:{CYAN}'>Setting up hosting\u2026</b> asking the router to open the port"
        elif h:
            role = {"direct": f"<b style='color:{GREEN}'>HOSTING</b> \u00b7 reachable from the internet",
                    "punch": f"<b style='color:{CYAN}'>HOSTING</b> \u00b7 online through hole punching"
                             + (f" \u00b7 {h['knocks']} knock(s)" if h.get("knocks") else ""),
                    }.get(h.get("mode"), f"<b style='color:{AMBER}'>HOSTING</b> \u00b7 home network only "
                                         f"(see Invite friends)")
        elif s["joined"]:
            role = f"<b style='color:{TEXT}'>JOINED</b>"
        else:
            role = "not connected"
        self.kv.setText(f"{role}<br>Network: <b style='color:{TEXT}'>{esc(s['network'] or '-')}</b><br>"
                        f"Public endpoint: <b style='color:{TEXT}'>{esc(me['public'])}</b><br>"
                        f"Rendezvous: <b style='color:{TEXT}'>{esc(srv)}</b>")
        self.status_v.setText(vtext)
        self.status_s.setText(f"server {srv}   ·   public {me['public']}")

        self._render_table(peers)
        self._render_detail(sel, s)
        if self.reopen_invite and self.was_busy and not s["hosting_busy"]:
            self.reopen_invite = False
            QTimer.singleShot(200, self.open_invite)
        self.was_busy = s["hosting_busy"]
        if h and self.invite_shown_for != s["network"] and s["code_display"]:
            self.invite_shown_for = s["network"]  # just started hosting: show the code once
            QTimer.singleShot(300, self.open_invite)
        if not s["joined"]:
            self.hint.setText("Not connected. Click <b>Host or join\u2026</b> to create a network or join a friend's.")
        elif v["status"] == "up":
            self.hint.setText("<b>To play:</b> host a LAN game on one PC; the others find it in their LAN list, "
                              "or connect to the host's <b>10.77.0.x</b> address.")
        else:
            self.hint.setText("The tunnel works, but games won't see each other until the virtual LAN is up "
                              "(run as administrator).")

        if first and not s["joined"] and not self.join_prompted:
            self.join_prompted = True
            QTimer.singleShot(200, lambda: self.open_join())

    def _render_table(self, peers):
        existing = {self.table.topLevelItem(i).data(0, Qt.UserRole): self.table.topLevelItem(i)
                    for i in range(self.table.topLevelItemCount())}
        ids = [p["id"] for p in peers]
        for pid, item in existing.items():
            if pid not in ids:
                self.table.takeTopLevelItem(self.table.indexOfTopLevelItem(item))
        for p in peers:
            item = existing.get(p["id"])
            if item is None:
                item = QTreeWidgetItem(self.table)
                item.setData(0, Qt.UserRole, p["id"])
            state = p["state"] + (" (forced)" if p["forced_relay"] else "") + (" ✕" if p["blackhole"] else "")
            rtt = f"{p['rtt_ms']:.1f} ms" if p["rtt_ms"] is not None else "–"
            for col, val in enumerate((p["name"], p["vip"] or "", state, rtt,
                                       fmt_bytes(p["stats"].get("tx_bytes")), fmt_bytes(p["stats"].get("rx_bytes")))):
                if item.text(col) != val:
                    item.setText(col, val)
            item.setForeground(2, QBrush(QColor(STATE_COLOR.get(p["state"], SLATE))))
            item.setForeground(3, QBrush(QColor(GREEN if p["rtt_path"] == "direct" else AMBER if p["rtt_path"] else TEXT)))
            f = item.font(0)
            f.setBold(True)
            item.setFont(0, f)
            item.setFont(2, f)
            mono = QFont("Consolas")
            mono.setStyleHint(QFont.Monospace)
            item.setFont(1, mono)

    def _render_detail(self, p, s):
        if not p:
            self.detail.setText(f"<span style='color:{MUTED}'>Select a player for details. The buttons at the top "
                                f"act on the selected player, or on everyone.</span>" if s["peers"] else "")
            self.meter.setVisible(False)
            return
        st = p["stats"]
        watching = p["state"] in ("DIRECT", "RECONNECTING") and p["direct_silence_s"] is not None
        punch = f"punches {p['punch']['total']}"
        if p["punch"]["elapsed"] is not None:
            punch += f" (round {p['punch']['round']}, {p['punch']['elapsed']:.1f}s / {s['punch_timeout']:.0f}s)"
        path = f"direct via {p['direct_addr']}" if p["state"] == "DIRECT" else "relayed by the server"
        self.detail.setText(
            f"<b style='color:{TEXT}; font-size:15px'>{esc(p['name'])}</b> "
            f"<span style='color:{STATE_COLOR.get(p['state'], SLATE)}'><b>{p['state']}</b></span> "
            f"for {p['in_state_s']:.0f}s<br>"
            f"<span style='font-family:Consolas,monospace'>public {esc(p['public'])} · local {esc(p['local'])}<br>"
            f"{path} · {punch}<br>"
            f"LAN packets out/in {st.get('vlan_tx_packets', 0)} / {st.get('vlan_rx_packets', 0)}"
            + (f" · last direct packet {p['direct_silence_s']:.1f}s ago" if watching else "") + "</span>")
        self.meter.setVisible(True)
        frac = min(1.0, p["direct_silence_s"] / s["dead_after"]) if watching else 0
        self.meter.setValue(int(frac * 100))
        col = RED if frac > 0.7 else AMBER if frac > 0.4 else GREEN
        self.meter.setStyleSheet(f"QProgressBar::chunk {{ background: {col}; }}")

    def select(self, pid):
        self.sel = pid
        self.topo.sel = pid
        self.table.blockSignals(True)
        self.table.clearSelection()
        for i in range(self.table.topLevelItemCount()):
            it = self.table.topLevelItem(i)
            if it.data(0, Qt.UserRole) == pid:
                it.setSelected(True)
        self.table.blockSignals(False)
        if self.s:
            self.render(self.s)

    def _table_selected(self):
        items = self.table.selectedItems()
        self.select(items[0].data(0, Qt.UserRole) if items else None)

    # --------------------------------------------------------- log + chat
    def add_event(self, ev):
        self.events.append(ev)
        self.events = self.events[-800:]
        if "punch attempt" in ev["msg"] and not self.show_punch.isChecked():
            return
        self._append_event(ev)

    def _append_event(self, ev):
        color = {"good": GREEN, "warn": AMBER, "bad": RED}.get(ev["level"], TEXT)
        msg = esc(ev["msg"]).replace(" -&gt; ", " → ")
        body = msg.split("] ", 1)[-1]
        is_transition = body.split(":", 1)[0].count("→") == 1 and body.split(" ", 1)[0].isupper()
        if is_transition:
            msg = f"<b>{msg}</b>"
        if "punch attempt" in ev["msg"]:
            color = MUTED
        ts = time.strftime("%H:%M:%S", time.localtime(ev["ts"])) + f".{int(ev['ts'] * 1000) % 1000:03d}"
        sb = self.log.verticalScrollBar()
        stick = sb.value() >= sb.maximum() - 30
        self.log.append(f"<span style='color:{MUTED}; font-family:Consolas,monospace'>{ts}</span>&nbsp;&nbsp;"
                        f"<span style='color:{color if ev['level'] != 'info' or is_transition else TEXT}'>{msg}</span>")
        if stick:
            sb.setValue(sb.maximum())

    def _rebuild_log(self):
        self.log.clear()
        for ev in self.events:
            if "punch attempt" in ev["msg"] and not self.show_punch.isChecked():
                continue
            self._append_event(ev)

    def add_chat(self, m):
        path = m.get("path") or ""
        col = {"direct": GREEN, "relay": AMBER}.get(path, CYAN)
        ts = time.strftime("%H:%M", time.localtime(m["ts"]))
        who = "you" if m.get("mine") else m["who"]
        self.chat.append(f"<span style='color:{MUTED}'>{ts}</span> <b>{esc(who)}</b> "
                         f"<span style='color:{col}; font-size:11px'><b>[{path.upper()}]</b></span> {esc(m['text'])}")

    def send_chat(self):
        t = self.chat_in.text().strip()
        if t:
            self.engine.command(cmd="chat", text=t)
            self.chat_in.clear()

    # ------------------------------------------------------------ actions
    def open_join(self, page="choose"):
        saved = (self.s or {}).get("saved", {})
        d = StartDialog(self, saved, (self.s or {}).get("me", {}).get("name"), page)
        accepted = d.exec() == QDialog.Accepted and d.result_cmd
        cmd = d.result_cmd
        d.deleteLater()  # free the dialog on Qt's side now, not at interpreter exit
        if accepted:
            self.engine.command(**cmd)

    def open_invite(self):
        if self.s and self.s.get("code_display"):
            d = ShareDialog(self, self.s["network"], self.s["code_display"], self.s["hosting"],
                            on_retry=self.retry_ports)
            d.exec()
            d.deleteLater()

    def retry_ports(self):
        self.reopen_invite = True  # show the result when the router has answered
        self.engine.command(cmd="retry_ports")

    def copy_ip(self):
        if self.s and self.s["me"]["vip"]:
            QApplication.clipboard().setText(self.s["me"]["vip"])
            self.statusBar().showMessage(f"Copied {self.s['me']['vip']}", 2000)

    def open_logs(self):
        if sys.platform == "win32":
            os.startfile(app_dir())

    def closeEvent(self, e):
        self.statusBar().showMessage("Leaving the network…")
        QApplication.processEvents()
        self.engine.shutdown()
        e.accept()


# ====================================================================== style
STYLE = f"""
* {{ font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QMenuBar {{ background: {BG}; }} QMenuBar::item:selected {{ background: {LINE}; }}
QMenu {{ background: {CARD}; border: 1px solid {LINE}; }} QMenu::item:selected {{ background: {LINE}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#box {{ background: {CARD2}; border: 1px solid {LINE}; border-radius: 10px; }}
QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 20px; font-weight: 800; letter-spacing: 3px; }}
QLabel#muted, QLabel#detail {{ color: {MUTED}; }}
QLabel#caps {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 2px; }}
QLabel#badge {{ font-size: 18px; font-weight: 800; padding: 5px 16px; border: 2px solid; border-radius: 17px; }}
QLabel#bigip {{ font-family: Consolas, monospace; font-size: 32px; font-weight: 800; }}
QLabel#vstatus {{ padding: 6px 10px; border-radius: 6px; }}
QLabel#hint {{ color: {MUTED}; background: {CARD2}; border: 1px dashed {LINE}; border-radius: 8px; padding: 8px 10px; }}
QLabel#dialogTitle {{ font-size: 22px; font-weight: 800; }}
QLabel#error {{ color: {RED}; }}
QPushButton {{ border: 0; border-radius: 8px; padding: 8px 14px; font-weight: 700; }}
QPushButton#demo {{ color: {BG}; }}
QPushButton#demo:disabled {{ background: {LINE}; color: {FAINT}; }}
QPushButton#plain, QDialogButtonBox QPushButton {{ background: {TEXT}; color: {BG}; }}
QPushButton#primary {{ background: {CYAN}; color: {BG}; padding: 9px 18px; }}
QPushButton#choice {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; text-align: left;
                      padding: 12px 16px; font-size: 15px; }}
QPushButton#choice:hover {{ border-color: {CYAN}; background: #142131; }}
QLabel#shareValue {{ font-size: 20px; font-weight: 700; }}
QLabel#shareCode {{ font-family: Consolas, monospace; font-size: 34px; font-weight: 800; color: {CYAN}; }}
QLineEdit#code {{ font-family: Consolas, monospace; font-size: 18px; letter-spacing: 2px; }}
QPushButton#small {{ background: transparent; border: 1px solid {LINE}; color: {MUTED}; padding: 3px 10px; font-weight: 500; }}
QPushButton#small:hover {{ color: {TEXT}; border-color: {FAINT}; }}
QPushButton:hover {{ padding-top: 7px; padding-bottom: 9px; }}
QLineEdit {{ background: {CARD2}; border: 1px solid {LINE}; border-radius: 8px; padding: 8px 10px; }}
QLineEdit:focus {{ border-color: {CYAN}; }}
QTextEdit {{ background: {CARD2}; border: 1px solid {LINE}; border-radius: 8px; padding: 4px; }}
QTreeWidget {{ background: {CARD2}; border: 1px solid {LINE}; border-radius: 8px; outline: 0; }}
QTreeWidget::item {{ padding: 6px 4px; border-bottom: 1px solid {LINE}; }}
QTreeWidget::item:selected {{ background: #1b2a3a; }}
QHeaderView::section {{ background: {CARD2}; color: {MUTED}; border: 0; border-bottom: 1px solid {LINE};
                        padding: 6px 4px; font-size: 11px; font-weight: 700; }}
QProgressBar {{ background: {LINE}; border: 0; border-radius: 3px; }}
QProgressBar::chunk {{ background: {GREEN}; border-radius: 3px; }}
QCheckBox {{ color: {MUTED}; }}
QSplitter::handle {{ background: {BG}; }}
QStatusBar {{ background: {BG}; color: {MUTED}; }} QStatusBar QLabel {{ color: {MUTED}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def make_icon():
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(BG))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(8, 8, 240, 240, 52, 52)
    p.setPen(QPen(QColor(GREEN), 16, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(70, 160, 186, 160)
    p.setPen(QPen(QColor(AMBER), 12, Qt.SolidLine, Qt.RoundCap))
    path = QPainterPath(QPointF(70, 160))
    path.cubicTo(QPointF(80, 70), QPointF(176, 70), QPointF(186, 160))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.setPen(QPen(QColor(TEXT), 10))
    p.setBrush(QColor(BG))
    for x in (70, 186):
        p.drawEllipse(QPointF(x, 160), 30, 30)
    p.setBrush(QColor(AMBER))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(128, 94), 16, 16)
    p.end()
    return QIcon(pm)


def fatal(msg):
    try:
        (app_dir() / "crash.log").write_text(msg, encoding="utf-8")
    except OSError:
        pass
    try:
        QMessageBox.critical(None, "Rendezvous failed to start", msg[-1500:])
    except Exception:
        print(msg, file=sys.stderr)


def main():
    ap = peer.build_parser()
    ap.add_argument("--no-vlan", action="store_true", help="don't create the virtual adapter (chat/demo only)")
    ap.add_argument("--api", action="store_true", help="also serve the JSON API / web dashboard on --http-port (tests)")
    ap.add_argument("--screenshot", help=argparse.SUPPRESS)  # testing aid: "file.png:seconds"
    args = ap.parse_args()
    args.app_mode = True
    args.vlan = not args.no_vlan
    args.config = args.config or str(app_dir() / "config.json")
    if args.vlan:
        import vnet
        if vnet.relaunch_as_admin():  # always run as administrator: needed for the virtual network
            return 0
    peer.setup_logging(args.verbose, logfile=app_dir() / "rendezvous.log")

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Rendezvous")
    app.setStyle("Fusion")
    pal = app.palette()
    for role, col in ((QPalette.Window, BG), (QPalette.Base, CARD2), (QPalette.Text, TEXT),
                      (QPalette.WindowText, TEXT), (QPalette.Button, CARD), (QPalette.ButtonText, TEXT),
                      (QPalette.Highlight, "#1b2a3a"), (QPalette.HighlightedText, TEXT)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)
    app.setWindowIcon(make_icon())

    # One copy at a time (a second one would fight over the adapter): if one is
    # already running, ask it to come to the front and exit.
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE_NAME)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(INSTANCE_NAME)
    server = QLocalServer()
    server.listen(INSTANCE_NAME)

    engine = Engine(args)
    win = MainWindow(engine)
    engine.start()

    def bring_to_front():
        server.nextPendingConnection()
        win.showNormal()
        win.raise_()
        win.activateWindow()

    server.newConnection.connect(bring_to_front)
    win.show()

    if args.screenshot:  # testing aid: "path.png:seconds"
        path, _, delay = args.screenshot.rpartition(":")
        def shot():
            win.grab().save(path)
            dlg = QApplication.activeModalWidget()
            if dlg:
                dlg.grab().save(path.replace(".png", "-dialog.png"))
                dlg.reject()
            win.close()
        QTimer.singleShot(int(float(delay) * 1000), shot)
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        fatal(traceback.format_exc())
        sys.exit(1)
