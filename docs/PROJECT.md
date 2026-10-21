# Rendezvous: project explainer, demo script and viva notes

## 1. What it is, in plain words

Some games (Minecraft Java "Open to LAN", older RTS and shooter games, many
indie co-op games) only find each other on a **local network**: PCs plugged
into the same home router. Friends in different houses can't play those games
together, because the internet sits between them.

**Rendezvous makes the internet look like one home network.** It's the same
kind of tool as Radmin VPN or Hamachi:

1. One friend opens the app and clicks **Host a network**. They pick a name,
   for example `Friday Games`, and the app shows a short code like `661 958`.
2. The others click **Join a network** and type the name and the code.
3. Each PC gets a pretend network card with an address like `10.77.0.2`.
   Windows and the games believe all the PCs are on the same LAN. Minecraft's
   "Open to LAN" world shows up in everyone's Multiplayer list on its own.

The hard part is that home routers block anything coming in from the internet
that the PC didn't ask for. The app works around that in layers, best first:

| situation | what the app does | how traffic flows |
|---|---|---|
| Host's router allows automatic port opening (UPnP / NAT-PMP) | opens a port, gives a **10-digit code** that encodes the host's address | directly between PCs |
| Host is behind the provider's shared address (**CGNAT**), or the router won't open a port | uses **hole punching**: both sides send to each other at the same moment so both routers let the replies in. Gives a **6-digit code** | directly between PCs |
| One side's router scrambles ports on every connection (**symmetric NAT**), so punching can't work | reaches the host through a **TURN relay** if one is available (see below), and the other players through the host. Without a relay: someone else hosts, or a small cloud server is used | through the host / relay |
| Two players can't reach each other directly even inside the network | that pair's packets go **through the host's server** (RELAY) | through the host |

Each pair of players picks its own path and switches automatically if a path
dies. The window shows every connection live: green **DIRECT**, amber
**RELAY**, blue **PUNCHING**, and so on.

**Radmin VPN** does the same job with its own company's servers in the
middle. Rendezvous runs the meeting point on the host's PC instead, so there's
no account and no company server. It only uses two free public services
(STUN, a "what's my address" service, and ntfy.sh, a message board) to swap
addresses when the host is behind CGNAT. For players who can't punch through
to a CGNAT host, it can also use a TURN relay. Honest note: the free public
relays it tries didn't answer in our last tests, so in practice this needs
your own relay (`RENDEZVOUS_TURN`). The simpler fixes are to let someone else
host, or to run `rendezvous_server.py` on a free cloud VM. That is exactly
the job Radmin's company servers do.

## 2. The parts

```
   friend's PC                      host's PC                         friend's PC
 ┌──────────────┐            ┌─────────────────────────┐            ┌──────────────┐
 │ game         │            │ game                    │            │ game         │
 │  │ 10.77.0.2 │            │  │ 10.77.0.1            │            │  │ 10.77.0.3 │
 │ Wintun       │            │ Wintun                  │            │ Wintun       │
 │ adapter      │            │ adapter                 │            │ adapter      │
 │  │           │  DIRECT    │  │                      │  DIRECT    │  │           │
 │ peer engine ─┼────────────┼─ peer engine ───────────┼────────────┼─ peer engine │
 │              │◄──────────────────────── DIRECT ────────────────────►            │
 │              │  register  │ rendezvous + relay      │  register  │              │
 │              ├───────────►│ server (built in)       │◄───────────┤              │
 └──────────────┘            └─────────────────────────┘            └──────────────┘
```

| file | role |
|---|---|
| `app.py` | The window (Qt): Host / Join dialogs, the live map of players, the chat, the Force Relay / Re-punch / Drop Direct buttons. |
| `peer.py` | The engine. One UDP socket. One state machine per other player. Moves packets between the virtual adapter and the right path. |
| `rendezvous_server.py` | The meeting point: introduces players, hands out `10.77.0.x` addresses, relays packets when a direct path doesn't exist. Python standard library only. |
| `hosting.py` | Everything about hosting from home: UPnP and NAT-PMP port opening, the codes, LAN discovery, STUN, the encrypted mailbox, the TURN client. |
| `vnet.py` | The virtual network card: Wintun on Windows (the driver WireGuard uses), `/dev/net/tun` on Linux. |

## 3. How a connection comes up, step by step

1. **Host starts.** The app starts the built-in server on UDP 9000. It asks
   the router to forward that port, first with UPnP and then with NAT-PMP, and
   adds a Windows Firewall rule for itself.
   - **Port opened:** the code is the public IPv4 address (a 32-bit number, so
     at most 10 digits) XOR-scrambled with a hash of the network name.
   - **No port:** the server asks two STUN servers "what address do you see
     me at?", from its own socket. It posts the answer, encrypted, to an
     ntfy.sh topic whose name is a hash of name + code.
2. **Friend joins.** First a quick broadcast on the friend's own LAN, in case
   the host is in the same house. Otherwise:
   - **10-digit code:** decode the address and go.
   - **6-digit code:** read the host's address from the mailbox, learn the
     friend's own public address by STUN, and post a "knock" with it. The
     host's server sends packets toward the knock while the friend sends
     toward the host. Each router sees outgoing traffic first, so it lets the
     replies in.
3. **Register.** The friend's engine sends `register` to the server. The
   server answers with a virtual IP and the list of the other players with
   their public and LAN addresses. It tells the existing players about the
   newcomer.
4. **Per-player state machine**, for every pair:
   - `DISCOVERING`: we know the player exists, but not yet how to reach them.
   - `PUNCHING`: both sides send `punch` packets to each other's public and
     LAN addresses every 250 ms. The server tells both to start at the same
     moment (`punch_now`).
   - `DIRECT`: a `punch_ack` came back. Keepalive pings every second keep the
     router's door open.
   - `RELAY`: punching didn't work within 5 s, so packets go through the
     server. Every 30 s it quietly tries direct again.
   - `RECONNECTING`: the direct path went silent for 3.5 s (the router forgot
     the mapping, Wi-Fi changed). Traffic falls back to the relay at once
     while it re-punches.
5. **Game traffic.** The game sends to `10.77.0.3`. Windows routes it into the
   Wintun adapter. The engine reads the raw IP packet, looks up which player
   owns `10.77.0.3`, and sends `0x01 + my id + packet` on the direct path, or
   `0x02 + their id + packet` to the server. The other side writes the packet
   into its adapter and the game receives it. Broadcasts (`255.255.255.255`,
   `10.77.0.255`) and multicast (`224.x.x.x`, Minecraft uses `224.0.2.60:4445`)
   go to every player. That's what makes LAN game lists work.

## 4. Things done to make it "just work" (like Radmin)

- **Always administrator.** The exe carries the admin flag (CI checks it). Run
  from source, the app relaunches itself as admin. Without admin rights it
  still runs, with chat but no virtual LAN, and says so.
- **Adapter set up for games.** Interface metric 1 so broadcasts and multicast
  prefer it. MTU 1280, so a game packet plus our header never needs
  fragmenting. A firewall rule lets the whole `10.77.0.0/24` network in.
  The adapter is marked a **Private** network. Otherwise a game whose
  firewall prompt was answered with the default ("Private" ticked) would be
  *blocked* on it, and block rules win over allow rules.
- **Port opening.** UPnP with three discovery rounds and a unicast query
  straight to the gateway, then NAT-PMP. Leases renewed every 20 minutes.
  **Try again** button after you enable UPnP on the router. Removed again on
  exit.
- **CGNAT.** STUN + encrypted mailbox + coordinated hole punching. The host
  re-checks its public address every 20 s and re-posts it if it changes. The
  code never changes.
- **Symmetric NAT.** Detected (two STUN servers see different ports). When
  the host has a TURN relay, the joiner alternates between the host's direct
  address and the relay address. Players that can't punch each other use the
  host as relay. The host keeps trying to get a relay every 5 minutes.
- **Same house.** LAN broadcast discovery, because many routers can't loop
  traffic back to their own public address (no "hairpin NAT").
- **Watchdog.** Silence on a direct path for 3.5 s means it's dead: switch to
  relay immediately, then try to punch again.
- **One copy only.** A second launch brings the first window to the front.
- **Remembers you.** The last network is rejoined (or re-hosted) next launch.
- **Logs.** `%APPDATA%\Rendezvous\`, plus `Rendezvous-console.exe` that shows
  the log live.

## 5. Demo script (about 5 minutes)

**Option A: one laptop, no admin.** Double-click `run_demo.bat`. It starts a
server and three players (alice, bob, carol), each with a web view.

1. All three links go `PUNCHING → DIRECT` within a second or two.
2. Select bob, press **Force Relay**: the link turns amber (`RELAY`). Send a
   chat message: it still arrives, through the server.
3. Press **Re-punch**: back to `DIRECT`.
4. Press **Drop Direct** on carol: the watchdog notices within 3.5 s and you
   see `RECONNECTING → DIRECT`. Chat keeps working throughout.

**Option B: two PCs, real game.**

1. PC 1: `Rendezvous.exe` → **Host a network** → `Friday Games` → **Start
   hosting**. Show the Invite window: the code, and the colour that says which
   method it picked.
2. PC 2, ideally on a phone hotspot so it's genuinely another network:
   **Join a network** → name + code. Show it turn `DIRECT` (or `RELAY`, and
   explain why).
3. `ping 10.77.0.1` from PC 2.
4. Minecraft Java, same version on both: PC 1 opens a world → Esc → **Open to
   LAN**. PC 2 → Multiplayer: the world appears under "LAN worlds". Join it.
5. During play, press **Force Relay** on PC 2: the game keeps running and the
   map shows the path change. **Re-punch** to go back.

Before the demo:
- Accept the admin prompt. On first run, allow Minecraft (Java) through the
  Windows Firewall prompt on the host, for both Private and Public networks.
- If the Invite window shows ⚠, use the phone hotspot trick: let the PC whose
  connection gives a ✓ host.
- Have `run_demo.bat` ready as a backup that needs no network at all.

## 6. Troubleshooting and workarounds

| symptom | cause | workaround |
|---|---|---|
| ⚠ "Your router didn't open the port automatically" | UPnP off on the router | Turn UPnP on in the router page, then **Try again**. Or forward UDP 9000. Or let another friend host. The app tries hole punching (6-digit code) on its own first. |
| Router address `100.64.x.x – 100.127.x.x` | provider CGNAT | Nothing needed: the app uses hole punching and gives a 6-digit code. |
| Friend: "couldn't punch through … symmetric NAT" | strict NAT on one side, and the TURN relay unreachable | Let someone else host. Or run `rendezvous_server.py` on any machine with a public IP (a free cloud VM) and use **Using a rendezvous server instead?** Or set your own TURN server with `RENDEZVOUS_TURN=host:port:user:pass`. |
| One player stays `RELAY` | their network blocks punching (mobile data, university Wi-Fi) | Works as is, slightly higher ping. |
| Friends see the world but can't join it | the host once answered the game's firewall prompt with "Private only", so Windows blocks it on Public networks | The app marks the virtual LAN as a **Private** network, so this normally can't happen. If the log says it couldn't, open *Windows Security → Firewall → Allow an app*, find **Java(TM) Platform SE binary** (Minecraft Java) or the game, and tick **Public** too. |
| Game doesn't list the LAN world | game's own firewall prompt was denied; different game versions | Allow the game in Windows Firewall. Check versions match. Use **Direct connect** to `10.77.0.x` (Minecraft LAN worlds use a random port shown in chat on the host). |
| LAN list stays empty, but `ping 10.77.0.x` works | another VPN (Radmin VPN, Hamachi, ZeroTier) also claims to be the preferred network, so the game's broadcast goes out there | Quit the other VPN or disable its adapter while playing. Or use the game's **Direct connect** with the host's `10.77.0.x` address. |
| "Virtual LAN unavailable" | admin prompt declined | Restart and accept it. |
| SmartScreen "Windows protected your PC" | exe isn't code-signed | **More info → Run anyway**. |
| Antivirus deletes the exe | unsigned one-file Python exe (a common false positive) | Restore and allow it, or run from source: `py -m pip install -r requirements.txt`, then `py app.py`. |
| Joined, but can't ping | Windows set the adapter as "Public" with a strict third-party firewall | The app adds its own allow rule. Check the third-party firewall too. |

## 7. Viva points

**What problem does it solve?**
LAN-only games need all PCs on one local network. Over the internet, NAT
routers block unsolicited incoming packets, so two home PCs can't even start
talking. The project builds a virtual LAN on top of the internet, with
automatic NAT traversal, like Radmin VPN or Hamachi.

**What is NAT, and why does it block us?**
A home router shares one public IP between all the devices in the house. When
a PC sends a packet out, the router records a mapping (inside address and port
↔ public port) and lets replies to that mapping back in. Packets for which no
mapping exists are dropped. So nobody outside can reach you first.

**What is UDP hole punching?**
Both peers learn each other's public address and port from a third party, the
rendezvous server. Then both send UDP packets to each other at about the same
time. Each router sees an outgoing packet first, creates a mapping, and then
accepts the other side's packets as "replies". It works for cone NATs, where
the public port stays the same whatever the destination.

**Why UDP and not TCP?**
UDP has no connection setup, so simultaneous sends just work. TCP hole
punching needs a simultaneous open, which many NATs handle badly. Games mostly
use UDP anyway. TCP game traffic (Minecraft uses TCP) is simply carried inside
our UDP packets.

**What is symmetric NAT, and what do you do about it?**
The router picks a new public port for every destination. The port the server
saw is not the port the other peer would see, so punching misses. We detect it
by asking two STUN servers and comparing the ports they report. Then we fall
back to a relay: the host's server, or a TURN relay when the host is behind
CGNAT. Port prediction is possible but unreliable, so it's left out.

**What is CGNAT?**
The internet provider puts many customers behind one more NAT (addresses
`100.64.0.0/10`). No router setting can open a port, because the outer NAT
belongs to the provider. The app detects this from the router's reported
address, then uses STUN plus the mailbox plus hole punching.

**What are STUN and TURN?**
- **STUN** (RFC 5389): "tell me my public address". One request, one reply
  that contains the address and port the server saw (XOR-encoded).
- **TURN** (RFC 5766): a relay server. You allocate an address on it, give
  permission to specific peers, and it forwards packets both ways. It's the
  fallback when nothing direct works. WebRTC (video calls in the browser) uses
  exactly the same pair.

**How can a 10-digit code be enough, with no server lookup?**
An IPv4 address is 32 bits, at most 4,294,967,295: 10 digits. The code is the
address XOR the first 4 bytes of SHA-256(network name). The name acts as a
key, and the code by itself doesn't show the IP. It is obfuscation, not
security, and the docs say so.

**Where does the 6-digit code come from, and is the mailbox safe?**
It's random. The mailbox topic is a hash of name + code, and the messages are
encrypted (a SHA-256 keystream) and authenticated (HMAC-SHA256) with a key
derived from name + code. ntfy.sh only sees random bytes. Only addresses go
through it, never game traffic.

**Why a state machine?**
Each pair of players can be in a different situation, and paths change at run
time. Five explicit states (`DISCOVERING`, `PUNCHING`, `DIRECT`, `RELAY`,
`RECONNECTING`) make every transition and timer clear, logged and visible on
screen. The demo buttons force transitions to prove each one works.

**How is a dead path detected?**
Pings every 1 s on the active path. 3.5 s without any packet from that peer
means the path is dead, so the link switches to relay immediately
(`RECONNECTING`) and re-punches. On the server side, peers that send nothing
for 10 s are removed.

**How do packets get from the game to the other PC?**
Through a TUN device (Wintun): a virtual network card that hands raw IP
packets to our program instead of to a cable. We read the destination IP, look
up the owning peer, add a 4-byte header (type + peer id), and send it over
UDP. The receiver strips the header and writes the packet into its own
adapter. This is how VPNs work (OpenVPN, WireGuard), at layer 3.

**Why do LAN game lists work?**
Games announce themselves with broadcast or multicast packets. The engine
copies those to every player. The adapter gets interface metric 1, so Windows
sends broadcasts and multicast through it. Minecraft Java multicasts to
`224.0.2.60:4445`. A test checks that exact packet arriving through the
adapter on real Windows.

**Why MTU 1280?**
Internet paths usually carry 1500 bytes. Our UDP + IP headers plus the 4-byte
tunnel header must fit, or packets get fragmented or dropped. 1280 is the IPv6
minimum and leaves a safe margin.

**Why not just use a central server for everything?**
Relaying all traffic costs bandwidth and adds latency (two hops). Direct paths
give the lowest ping. The relay exists only as the fallback, and it runs on
the host's own PC.

**Security: what's protected and what isn't?**
- Joining needs the network name plus the code (and an optional password).
  Every message carries the network's identity, and strangers' packets are
  dropped. Packets are only accepted from addresses we punched with, or from
  the server.
- Game traffic is **not encrypted**. A production version would add a key
  exchange (Noise / WireGuard).

**How was it tested?**
- **Linux network namespaces as a NAT lab** (`tools/natlab.sh`): real
  MASQUERADE routers, symmetric-NAT mode, a CGNAT mode with a provider NAT, a
  miniupnpd router for UPnP / NAT-PMP, and a coturn TURN server. Results: cone
  → DIRECT; symmetric → RELAY; CGNAT host → 6-digit code with a full DIRECT
  mesh; symmetric friend of a CGNAT host → in through TURN.
- **GitHub Actions on real Windows:** the Wintun adapter (ping, broadcasts,
  multicast, Minecraft LAN packet), a three-peer mesh, the built exe joining a
  network, the admin flag, the firewall rule, real STUN and ntfy.sh, and a
  screenshot of the window.

**Limits, honestly**
- No encryption of game traffic.
- IPv4 only, 8 players.
- Depends on the free STUN and ntfy services in the CGNAT case. The free
  TURN relays it tries were down in our tests, so a symmetric-NAT friend of a
  CGNAT host needs a relay you provide, or a different host. All of
  them can be swapped with environment variables (`RENDEZVOUS_STUN`,
  `RENDEZVOUS_MAILBOX`, `RENDEZVOUS_TURN`).
- Unsigned exe.
- Python costs more CPU than a native tool, but it's plenty fast for games
  (~15 MB/s TCP measured).

**What would you add next?**
WireGuard-style encryption, IPv6, port prediction for symmetric NAT, a
signed installer, and a small always-on server (like Radmin's) so nobody has
to host.

## 8. Glossary

- **LAN**: local network, the PCs on one router.
- **NAT**: the router's address sharing.
- **CGNAT**: the provider's extra NAT.
- **UPnP / NAT-PMP**: ways for a program to ask the router to open a port.
- **STUN**: "what's my public address" service.
- **TURN**: a relay server for when direct paths fail.
- **TUN / Wintun**: a virtual network card that passes IP packets to a program.
- **Hole punching**: both sides sending first so both routers let the other in.
- **Relay**: sending via a third machine.
- **Multicast / broadcast**: one-to-many packets that LAN games use to announce
  themselves.
