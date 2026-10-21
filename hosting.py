"""
hosting.py - lets any player HOST a network from the app, no cloud server needed.

When you click "Host", your app:
  1. starts the rendezvous server inside the app (same code as rendezvous_server.py),
  2. asks your home router to forward its UDP port to this PC, using UPnP
     (the same mechanism games and consoles use to "open NAT"),
  3. builds an INVITE CODE: your public address + network name + password,
     packed into one string your friends paste into "Join".

If the router doesn't do UPnP, you can forward the port by hand, or everyone can
use a rendezvous server on a cloud VM instead (rendezvous_server.py).
"""

import base64
import ipaddress
import json
import logging
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree

import rendezvous_server

log = logging.getLogger("hosting")

INVITE_PREFIX = "RZ1-"
SSDP_ADDR = ("239.255.255.250", 1900)
WAN_SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2",
                "urn:schemas-upnp-org:service:WANIPConnection:1",
                "urn:schemas-upnp-org:service:WANPPPConnection:1")


# ================================================================ invite codes
def make_invite(server, network, password="", lan=None):
    """One copy-pasteable string with everything a friend needs to join.
    `lan` is the host's LAN address, tried when the public one doesn't answer
    (friends in the same house, behind a router without NAT loopback)."""
    d = {"s": server, "n": network, "p": password}
    if lan and lan != server:
        d["l"] = lan
    raw = json.dumps(d, separators=(",", ":")).encode()
    return INVITE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_invite(code):
    """Returns {"server", "network", "password", "alt"} or raises ValueError."""
    code = re.sub(r"\s+", "", code or "")
    if not code.upper().startswith(INVITE_PREFIX):
        raise ValueError("an invite code starts with RZ1-")
    body = code[len(INVITE_PREFIX):]
    try:
        d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return {"server": str(d["s"]), "network": str(d["n"]), "password": str(d.get("p", "")),
                "alt": str(d["l"]) if d.get("l") else None}
    except (ValueError, KeyError, TypeError):
        raise ValueError("this invite code is damaged - copy it again") from None


def is_private(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return a.is_private or a.is_loopback or a.is_link_local or a in ipaddress.ip_network("100.64.0.0/10")


def lan_ip_towards(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


# ======================================================================= UPnP
class UPnPError(Exception):
    pass


class UPnP:
    """
    Minimal UPnP Internet Gateway Device client (stdlib only):
      discover the router with SSDP, read its description, then call
      GetExternalIPAddress / AddPortMapping / DeletePortMapping over SOAP.
    """

    def __init__(self, control_url, service, router_host):
        self.control_url = control_url
        self.service = service
        self.router_host = router_host
        self.lan_ip = lan_ip_towards(router_host)
        self.mapped = []  # (external_port, protocol)

    @classmethod
    def discover(cls, timeout=2.5):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        # Send the search out of the real network card. Our virtual adapter
        # is the preferred route for multicast (that's how game discovery
        # reaches the other players), so without this the router never hears it.
        lan = lan_ip_towards("8.8.8.8")
        if lan:
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(lan))
            except OSError:
                pass
        s.settimeout(0.5)
        try:
            for st in ("urn:schemas-upnp-org:device:InternetGatewayDevice:1", "upnp:rootdevice"):
                msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                       f"MX: 2\r\nST: {st}\r\n\r\n").encode()
                s.sendto(msg, SSDP_ADDR)
        except OSError as e:
            raise UPnPError(f"cannot send UPnP discovery: {e}") from None
        locations, end = [], time.time() + timeout
        while time.time() < end:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            m = re.search(rb"(?im)^location:\s*(\S+)", data)
            if m and m.group(1).decode() not in locations:
                locations.append(m.group(1).decode())
        s.close()
        for loc in locations:
            try:
                found = cls._from_description(loc)
            except (OSError, ElementTree.ParseError, ValueError) as e:
                log.debug("UPnP device %s unusable: %s", loc, e)
                continue
            if found:
                return found
        raise UPnPError("no UPnP router answered (UPnP may be turned off on the router)")

    @classmethod
    def _from_description(cls, location):
        xml = urllib.request.urlopen(location, timeout=4).read()
        root = ElementTree.fromstring(xml)
        ns = {"d": root.tag[1:].split("}")[0]} if root.tag.startswith("{") else {"d": ""}
        base = root.findtext("d:URLBase", default="", namespaces=ns) or location
        for svc in root.iter(f"{{{ns['d']}}}service" if ns["d"] else "service"):
            stype = svc.findtext("d:serviceType", default="", namespaces=ns)
            if stype in WAN_SERVICES:
                ctrl = urllib.parse.urljoin(base, svc.findtext("d:controlURL", default="", namespaces=ns))
                return cls(ctrl, stype, urllib.parse.urlparse(location).hostname)
        return None

    def _soap(self, action, args):
        body = "".join(f"<{k}>{v}</{k}>" for k, v in args)
        envelope = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                    f'<u:{action} xmlns:u="{self.service}">{body}</u:{action}></s:Body></s:Envelope>').encode()
        req = urllib.request.Request(self.control_url, data=envelope, headers={
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{self.service}#{action}"'})
        try:
            return urllib.request.urlopen(req, timeout=5).read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            code = re.search(r"<errorCode>(\d+)</errorCode>", text)
            desc = re.search(r"<errorDescription>([^<]*)</errorDescription>", text)
            raise UPnPError(f"{action} refused ({code.group(1) if code else e.code} "
                            f"{desc.group(1) if desc else ''})".strip()) from None
        except OSError as e:
            raise UPnPError(f"{action} failed: {e}") from None

    def external_ip(self):
        m = re.search(r"<NewExternalIPAddress>([^<]*)<", self._soap("GetExternalIPAddress", []))
        if not m or not m.group(1):
            raise UPnPError("router did not report its public IP")
        return m.group(1)

    def add_mapping(self, internal_port, protocol="UDP", tries=10):
        """Forward a public port to (this PC, internal_port). Prefers the same
        port number; returns the external port actually mapped."""
        if not self.lan_ip:
            raise UPnPError("cannot work out this PC's LAN address")
        last = None
        for ext in [internal_port] + [internal_port + i for i in range(1, tries)]:
            for lease in (3600, 0):  # some routers only accept permanent (0) leases
                try:
                    self._soap("AddPortMapping", [
                        ("NewRemoteHost", ""), ("NewExternalPort", ext), ("NewProtocol", protocol),
                        ("NewInternalPort", internal_port), ("NewInternalClient", self.lan_ip),
                        ("NewEnabled", 1), ("NewPortMappingDescription", f"Rendezvous {protocol} {internal_port}"),
                        ("NewLeaseDuration", lease)])
                    self.mapped.append((ext, protocol))
                    return ext
                except UPnPError as e:
                    last = e
                    if "725" not in str(e):  # 725 = OnlyPermanentLeasesSupported -> retry with 0
                        break
        raise last

    def remove_all(self):
        for ext, proto in self.mapped:
            try:
                self._soap("DeletePortMapping", [("NewRemoteHost", ""), ("NewExternalPort", ext),
                                                 ("NewProtocol", proto)])
            except UPnPError as e:
                log.debug("could not remove mapping %s/%s: %s", ext, proto, e)
        self.mapped = []


def public_ip_from_web():
    """Fallback when UPnP is unavailable: ask a 'what is my IP' service."""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            ip = urllib.request.urlopen(url, timeout=5).read().decode().strip()
            ipaddress.ip_address(ip)
            return ip
        except (OSError, ValueError):
            continue
    return None


# ============================================================ embedded server
class EmbeddedServer:
    """The rendezvous server, running on a thread inside the host's app."""

    def __init__(self, port, room):
        self.server = rendezvous_server.RendezvousServer("0.0.0.0", port, "10.77.0.0/24")
        self.server.only_room = room  # this server is for the host's network only
        self.port = self.server.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._run, name="rendezvous-server", daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.server.serve_forever()
        except OSError:
            pass  # socket closed by stop()

    def stop(self):
        self.server.running = False
        self.thread.join(2)
        self.server.sock.close()


def start_hosting(port, room, peer_udp_port, use_upnp=True):
    """
    Blocking (run it off the UI/event-loop thread). Starts the embedded server
    and tries to make it reachable from the internet. Returns a dict:
      server: EmbeddedServer, upnp: UPnP or None, public_ip, server_port,
      status: human-readable reachability summary, reachable: True/False/None
    """
    server = EmbeddedServer(port, room)
    info = {"server": server, "upnp": None, "public_ip": None, "server_port": server.port,
            "lan_ip": lan_ip_towards("8.8.8.8"), "reachable": None, "status": ""}
    upnp_err = "UPnP is turned off in the app"
    if use_upnp:
        try:
            up = UPnP.discover()
            info["public_ip"] = up.external_ip()
            ext = up.add_mapping(server.port)
            info["server_port"] = ext
            # Also forward the host's own tunnel port: then every player can
            # reach the host directly, no hole punching needed for that link.
            try:
                peer_ext = up.add_mapping(peer_udp_port)
                server.server.overrides[peer_udp_port] = (info["public_ip"], peer_ext)
            except UPnPError as e:
                log.info("could not forward the tunnel port: %s", e)
            info["upnp"] = up
        except UPnPError as e:
            upnp_err = str(e)
    if not info["public_ip"]:
        info["public_ip"] = public_ip_from_web()
    server.server.public_ip = info["public_ip"]

    if info["upnp"] and info["public_ip"] and not is_private(info["public_ip"]):
        info["reachable"] = True
        info["status"] = f"Router port forwarding set up automatically (UPnP): UDP {info['server_port']} is open."
    elif info["upnp"] and info["public_ip"]:
        info["reachable"] = False
        info["status"] = (f"Your router's internet address ({info['public_ip']}) is not public - your provider "
                          f"probably uses CGNAT. Friends outside your home can't reach you; use a rendezvous "
                          f"server on a cloud VM instead (Advanced).")
    else:
        info["status"] = (f"Couldn't open the port automatically ({upnp_err}). Friends on your own network can "
                          f"join. For friends over the internet, forward UDP {server.port} on your router to "
                          f"this PC ({info['lan_ip'] or 'this PC'}), or use a cloud rendezvous server.")
    return info


def stop_hosting(info):
    if not info:
        return
    if info.get("upnp"):
        info["upnp"].remove_all()
    info["server"].stop()
