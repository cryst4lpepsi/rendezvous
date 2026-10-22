# Viva prep: Computer Networks, through the Rendezvous project

How to use this:
1. Learn the **project paragraph** (section 1) almost word for word.
2. Learn the **map** (section 2). Examiners love "which layer does your project work at?".
3. Go through each unit's questions (sections 3–7). Every answer is short enough
   to say out loud. Where the project uses a concept, there's a **Project link**
   line: say it. It shows you understand the theory, not just the syllabus.
4. Section 8 is the glossary of every abbreviation and buzzword.
5. Section 9 has worked numericals (CRC, Hamming, subnetting, checksum, ALOHA).
6. Every header and packet format, field by field: [HEADERS.md](HEADERS.md).

---

## 1. The project in one paragraph

**Say this (about 1 minute):**

> Our project, **Rendezvous**, is a peer-to-peer virtual LAN, similar to Radmin
> VPN or Hamachi. Games like Minecraft's "Open to LAN" only find each other on a
> local network, because they announce themselves with **broadcast and
> multicast** packets that routers never forward to the internet. Rendezvous
> gives every player's PC a **virtual network adapter** with a private address
> like 10.77.0.2. It captures the **IP packets** the game sends, wraps them in
> **UDP**, and delivers them to the other players over the internet. The hard
> part is **NAT**: home routers drop incoming packets nobody inside asked for.
> We solve that in layers. First we ask the router to open a port
> (**UPnP / NAT-PMP**). If that's impossible (for example behind the provider's
> **CGNAT**), both sides learn their public address from a **STUN** server and
> do **UDP hole punching**: both send at the same moment, so both routers let
> the replies in. If even that fails (**symmetric NAT**), traffic is **relayed**
> through the host. Each pair of players runs a small **state machine**
> (Discovering → Punching → Direct / Relay → Reconnecting), with keepalives and
> a watchdog that switches to the relay within 3.5 seconds if the direct path
> dies. Everything is shown live in a desktop app, built as a single Windows
> **.exe** and tested automatically on real Windows machines.

**30-second version:**

> It's our own Radmin VPN. It makes PCs in different houses behave as if they
> were on one LAN, so LAN games work over the internet. It captures IP packets
> from a virtual network card, sends them over UDP, and gets through home
> routers with UPnP, STUN and UDP hole punching, falling back to a relay when
> a direct path is impossible.

**If asked "what did *you* learn / what's new here":**

> Real NAT traversal. Simulating NAT types in Linux network namespaces showed
> us why cone NATs can be punched and symmetric NATs can't. Also why we carry
> TCP inside UDP rather than inside TCP, and how LAN discovery depends on
> broadcast and multicast, which is a network-layer detail most people never
> see.

---

## 2. Map: which syllabus topic appears where in the project

| Layer / unit | Where it shows up in Rendezvous |
|---|---|
| **Physical (Unit I)** | None of our own; we run over whatever link exists (Wi-Fi, Ethernet, mobile). The virtual adapter is a *software* NIC with no physical layer. |
| **Data link (Unit II)** | Wintun is a **TUN** (layer 3) adapter: no Ethernet frames, no MAC addresses, no ARP. A **TAP** adapter would be layer 2. Our MTU of 1280 is chosen so our packets never exceed the real link's 1500-byte Ethernet payload. |
| **Network (Unit III)** | We read raw **IPv4 headers**: version nibble, protocol byte (1 ICMP, 2 IGMP, 6 TCP, 17 UDP), destination address (bytes 16–19). We "route" by destination IP: a player's 10.77.0.x goes to that player, while **broadcast** (255.255.255.255, 10.77.0.255) and **multicast (Class D, 224–239)** go to everyone. **NAT**, private addressing, **CIDR /24**, **ICMP** ping and the interface **metric** are all used. IPv6 is dropped. |
| **Transport (Unit IV)** | Everything travels in **UDP**. **One socket** carries many conversations: we **demultiplex** by the first byte of each datagram and by the sender's address. Games' **TCP** connections ride *inside* our UDP, with no TCP-over-TCP. Keepalives, timeouts and retries are ours. |
| **Application (Unit V)** | **UPnP** = SSDP discovery + **HTTP**/SOAP control of the router. The mailbox is **HTTPS**. **DNS** resolves the STUN/TURN/mailbox servers. Our server hands out virtual IPs much like **DHCP**. JSON control messages form our own application protocol. |

---

## 3. Unit I: Fundamentals of networking and data communication

**Q. Analog vs digital signal?**
An analog signal varies continuously (a sine wave, voice). A digital signal has
a limited set of discrete levels (0/1).

**Q. Analog-to-analog conversion: what and why?**
Putting an analog message onto a higher-frequency analog **carrier**, so it
can travel through a band-pass medium (radio). Three types:
- **AM** (amplitude modulation): the carrier's amplitude follows the signal.
- **FM** (frequency modulation): the frequency changes.
- **PM** (phase modulation): the phase changes.

**Q. Digital-to-analog conversion?**
Representing bits by changing a carrier wave:
- **ASK** (amplitude shift keying);
- **FSK** (frequency shift keying);
- **PSK** (phase shift keying);
- **QAM** (quadrature amplitude modulation: amplitude *and* phase together,
  many bits per symbol; used in Wi-Fi and cable modems).

Bit rate = baud rate × bits per symbol.

**Q. Digital-to-digital conversion: line coding, block coding, scrambling?**
- **Line coding** turns bits into voltage levels:
  - **NRZ-L**: level = bit.
  - **NRZ-I**: a 1 = invert the level.
  - **Manchester**: transition in the middle of each bit (used by 10 Mbps
    Ethernet).
  - **Differential Manchester**.
  - **AMI / bipolar**: 1s alternate +/−.

  Goals: self-clocking (synchronization), no DC component.
- **Block coding** (mB/nB, e.g. **4B/5B**, **8B/10B**): replace each m-bit
  group with an n-bit code (n > m). The extra bits guarantee enough
  transitions for synchronization and allow some error detection.
- **Scrambling** (**B8ZS**, **HDB3**): replace long runs of zeros with a
  special pattern, to keep the receiver synchronized *without* increasing the
  bandwidth (used with AMI).

**Q. Analog-to-digital: PCM?**
**Pulse Code Modulation** has three steps:
1. **Sampling** at a rate of at least twice the highest frequency (**Nyquist**:
   fs ≥ 2·fmax; telephone voice: 4 kHz → 8000 samples/s).
2. **Quantization**: round each sample to one of 2ⁿ levels. This adds
   quantization error.
3. **Encoding** each level as n bits.

Example: 8000 samples/s × 8 bits = 64 kbps (a digital phone channel, DS0).
Alternative: **Delta modulation** sends only up/down (1 bit per sample).

**Q. Types of networks?**
**PAN** (personal, Bluetooth), **LAN** (local: home, office, campus), **MAN**
(metropolitan: city), **WAN** (wide: countries, the internet).
*Project link:* we make a WAN behave like a LAN. That's an **overlay network**:
a virtual network built on top of another one.

**Q. Network architectures?**
- **Client–server**: central server, clients request (web, email).
- **Peer-to-peer (P2P)**: every node is both client and server (BitTorrent).

*Project link:* **hybrid**. A small server only *introduces* the players
(rendezvous), then traffic flows peer to peer. The server is used as a relay
only when a direct path is impossible.

**Q. Topologies?**
- **Bus**: one shared cable; one break kills it.
- **Star**: all nodes connect to a central hub/switch; most common.
- **Ring**: token passing.
- **Mesh**: every node linked to every other; n(n−1)/2 links, very reliable.
- **Tree**: hierarchy of stars.
- **Hybrid**.

*Project link:* players form a **full mesh** of direct links (8 players → 28
links). When a pair can't connect directly, that pair falls back to a **star**
through the host.

**Q. Transmission media?**
- **Guided (wired)**:
  - twisted pair (UTP/STP; Cat5e/Cat6, RJ-45);
  - coaxial (cable TV);
  - **optical fiber** (light, total internal reflection; highest bandwidth,
    immune to electromagnetic interference).
- **Unguided (wireless)**: radio waves (Wi-Fi), microwaves (point-to-point,
  satellite), infrared (short range, line of sight).

**Q. Networking devices, with layer?**

| Device | Layer | Notes |
|---|---|---|
| Repeater | 1 | regenerates the signal |
| Hub | 1 | multiport repeater; sends to all ports; one collision domain |
| Bridge | 2 | connects LAN segments, filters by MAC |
| Switch | 2 | multiport bridge; learns MACs; each port its own collision domain |
| Router | 3 | forwards by IP; separates broadcast domains |
| Gateway | up to 7 | protocol conversion |
| Access point | 2 | wireless to wired |
| Modem | 1 | modulator-demodulator |

*Project link:* a home "router" is really a router + switch + access point +
**NAT** + DHCP server in one box. Our rendezvous server acts like a *virtual
switch*: it knows which virtual IP lives at which public address.

**Q. OSI model: the 7 layers, top to bottom?**

| # | Layer | Job | Data unit | Examples |
|---|---|---|---|---|
| 7 | Application | services for the user | data | HTTP, DNS, SMTP |
| 6 | Presentation | format, encryption, compression | data | TLS, JPEG, ASCII |
| 5 | Session | open/manage/close sessions, checkpoints | data | RPC, NetBIOS |
| 4 | Transport | process to process, reliability, ports | **segment** (TCP) / **datagram** (UDP) | TCP, UDP |
| 3 | Network | logical addressing, routing | **packet** | IP, ICMP |
| 2 | Data link | framing, MAC addressing, error detection | **frame** | Ethernet, Wi-Fi |
| 1 | Physical | bits on the medium | **bits** | cables, signals |

Mnemonic (top down): "**All People Seem To Need Data Processing**".
Bottom up: "**Please Do Not Throw Sausage Pizza Away**".

**Q. TCP/IP model vs OSI?**
TCP/IP has 4 layers:
- **Application** = OSI 5 + 6 + 7;
- **Transport**;
- **Internet** (IP);
- **Network access / Link** = OSI 1 + 2.

Some books use 5 layers and split Link into Data Link + Physical. OSI is a
reference model; TCP/IP is what the internet actually runs. **Encapsulation**:
each layer adds its own header going down, and removes it going up.

*Project link:* our system is **encapsulation in action**. A game's IP packet
gets our 4-byte header, then a UDP header, then a new IP header, then a
Wi-Fi/Ethernet frame. This is called **tunneling**, and it's how every VPN
works.

**Q. Ethernet standards?**
IEEE **802.3**. Name format: speed + BASE (baseband) + medium.
- **10BASE-T** (10 Mbps, twisted pair);
- **100BASE-TX** (Fast Ethernet);
- **1000BASE-T** (Gigabit);
- **10GBASE-T**;
- fiber variants: -SX, -LX.

Wi-Fi is IEEE **802.11** (a/b/g/n/ac/ax). Classic Ethernet used CSMA/CD;
switched full-duplex Ethernet has no collisions.

---

## 4. Unit II: Data Link Layer

**Q. Services of the data link layer?**
- **Framing**: dividing the bit stream into frames (byte or bit stuffing).
- **Physical (MAC) addressing**.
- **Flow control**.
- **Error control** (detection plus retransmission).
- **Access control**: who may use a shared medium.

Two sublayers: **LLC** (logical link control) and **MAC** (media access
control).

**Q. Types of errors?**
- **Single-bit error**: one bit flipped.
- **Burst error**: two or more bits flipped in a row. Burst length = from the
  first to the last corrupted bit. More common, because noise lasts longer
  than one bit.

**Q. Redundancy, detection vs correction?**
We add redundant bits. **Detection** only knows something is wrong and asks
for a resend; **correction** finds and fixes the bit (FEC: forward error
correction).

**Q. Block coding for error control?**
- Split data into **datawords** of k bits and map each to a **codeword** of
  n bits (n > k). Only 2ᵏ of the 2ⁿ patterns are valid; an invalid pattern
  means an error.
- **Hamming distance** d(x, y) = number of differing bits = the number of 1s
  in x XOR y.
- **d_min** = the smallest distance between any two codewords.
  - To **detect** s errors: d_min ≥ s + 1.
  - To **correct** t errors: d_min ≥ 2t + 1.

**Q. Parity check?**
Add one bit so the number of 1s is even (even parity). It detects any odd
number of errors and misses an even number. **2-D parity** (rows + columns) can
detect more, and correct a single error.

**Q. CRC (Cyclic Redundancy Check)?**
- Sender and receiver agree on a **generator polynomial** of degree r
  (r + 1 bits).
- The sender appends r zeros to the data and divides by the generator with
  **modulo-2 division** (XOR, no carries). The **remainder** (r bits) replaces
  the zeros; that remainder is the CRC.
- The receiver divides the whole codeword by the generator: remainder 0 = no
  error detected.
- Detects all single-bit errors, all odd numbers of errors (if x+1 is a
  factor), and all bursts of length ≤ r.
- Ethernet uses **CRC-32** in the FCS field.

Worked example in section 9.

**Q. Hamming code?**
- A **single-error-correcting** code. Parity bits sit at positions that are
  powers of two (1, 2, 4, 8, …). The parity bit at position p covers every
  position whose binary index has that bit set.
- Number of parity bits r: **2ʳ ≥ m + r + 1** (m data bits). For 4 data bits,
  r = 3 → the (7,4) Hamming code.
- At the receiver, recomputing the checks gives the **syndrome**. Read in
  binary, it is the *position* of the wrong bit (0 = no error).

Worked example in section 9.

**Q. Checksum?**
The **Internet checksum**:
1. Split the data into 16-bit words and add them with **one's-complement**
   arithmetic (wrap the carry around).
2. Complement the result; that is the checksum.
3. The receiver adds everything, checksum included: all 1s = OK
   (complemented: 0).

Used in the IPv4 header, TCP, UDP and ICMP. It's weaker than CRC (e.g. it
can't detect swapped words) but cheap in software.
*Project link:* the outer UDP/IP headers of our tunnel packets carry these
checksums. For *security* we use **HMAC** (a keyed cryptographic hash) in the
mailbox messages. A checksum catches accidents; an HMAC catches tampering.

**Q. Flow control vs error control?**
- **Flow control**: don't overwhelm the receiver (pace the sender).
- **Error control**: detect and recover lost or damaged frames (ACKs,
  timeouts, retransmission: **ARQ**, Automatic Repeat reQuest).

**Q. Stop-and-Wait ARQ?**
Send one frame and wait for its ACK; resend on timeout. Sequence numbers 0/1.
Simple but inefficient on long links.

**Q. Sliding window: Go-Back-N vs Selective Repeat?**

| | Go-Back-N (GBN) | Selective Repeat (SR) |
|---|---|---|
| Sender window | up to **2ᵐ − 1** | up to **2ᵐ⁻¹** |
| Receiver window | **1** (accepts only in order) | same as sender (buffers out-of-order) |
| On a lost frame | resend that frame **and all after it** | resend **only** the lost frame |
| ACKs | cumulative | individual (+ NAK) |
| Trade-off | simple receiver, wastes bandwidth on errors | efficient, complex receiver |

(m = bits in the sequence number.)

Why is the SR window only half? With a bigger window, after lost ACKs the
receiver couldn't tell a new frame from a retransmitted old one with the same
number.

**Q. Channel allocation?**
- **Static**: FDM, TDM. Fixed share; wasteful for bursty traffic.
- **Dynamic**: allocate on demand, through multiple-access protocols.

**Q. Multiple access protocols: classes?**
1. **Random access**: ALOHA, CSMA, CSMA/CD, CSMA/CA.
2. **Controlled access**: reservation, polling, token passing.
3. **Channelization**: **FDMA** (frequency), **TDMA** (time), **CDMA** (codes).

**Q. ALOHA?**
- **Pure ALOHA**: send whenever you have data; on a collision (no ACK), wait a
  random time and resend. Vulnerable time = 2 × T_fr. Max throughput
  **18.4%** (S = G·e⁻²ᴳ, maximum at G = 0.5).
- **Slotted ALOHA**: send only at the start of time slots. Vulnerable time =
  T_fr. Max throughput **36.8%** (S = G·e⁻ᴳ, maximum at G = 1).

**Q. CSMA (Carrier Sense Multiple Access)?**
"Listen before talk." Persistence methods:
- **1-persistent**: send as soon as the line is idle.
- **Non-persistent**: if busy, wait a random time, then sense again.
- **p-persistent**: if idle, send with probability p.

Collisions still happen because of propagation delay.

**Q. CSMA/CD (Collision Detection)?**
Used by classic wired Ethernet.
- Listen; send; *keep listening while sending*.
- If a collision is detected, stop, send a **jam signal**, then wait a
  **binary exponential backoff** (random 0…2ᵏ−1 slot times after the k-th
  collision).
- A frame must last at least the round-trip time (T_fr ≥ 2 × T_prop) so a
  collision is detected while still sending. That's why Ethernet has a
  **64-byte minimum frame** (at 10 Mbps).

**Q. CSMA/CA (Collision Avoidance)?**
Used by **Wi-Fi**. A wireless station can't hear collisions while sending, so
it tries to *avoid* them:
- **IFS** (inter-frame space) waits: DIFS, SIFS;
- a random **contention window**;
- an **ACK** for every frame;
- optional **RTS/CTS** handshake, which solves the **hidden terminal
  problem**.

**Q. Ethernet frame format (IEEE 802.3)?**

| Preamble | SFD | Destination MAC | Source MAC | Type/Length | Data + padding | FCS (CRC-32) |
|---|---|---|---|---|---|---|
| 7 B | 1 B | 6 B | 6 B | 2 B | 46–1500 B | 4 B |

- Preamble = 10101010… for synchronization. **SFD** = start frame delimiter
  (10101011).
- Frame size (without preamble + SFD): **min 64 B, max 1518 B**.
- **MTU** = 1500 B (the maximum payload).
- A **MAC address** is 48 bits (e.g. 3C-52-82-1A-7F-01). The first 24 bits =
  manufacturer (**OUI**). FF-FF-FF-FF-FF-FF = broadcast.

*Project link:* we choose **MTU 1280** for the virtual adapter. Each game
packet is wrapped in our 4-byte header + UDP 8 + IP 20 = +32 bytes, and must
still fit in a 1500-byte Ethernet payload (and the smaller MTUs of some mobile
or PPPoE links), so it is never **fragmented**.

**Q. Why TUN and not TAP? (good trap question)**
A **TAP** device carries Ethernet *frames* (layer 2): MACs, ARP, any protocol.
A **TUN** device carries IP *packets* (layer 3). We chose TUN (Wintun):
- less overhead;
- no ARP traffic;
- simpler routing by IP address.

The cost: non-IP protocols (e.g. IPX, used by some 1990s games) aren't
carried. Hamachi offers a layer-2 mode for those.

---

## 5. Unit III: Network Layer

**Q. Services of the network layer?**
- **Logical addressing** (IP);
- **routing** (choosing paths);
- **forwarding** (moving a packet to the right output);
- **packetizing**;
- **fragmentation**;
- host-to-host delivery (the transport layer does process-to-process).

Best-effort and connectionless in IP.

**Q. IPv4 header fields?**
The header is 20–60 bytes:

| Field | Meaning |
|---|---|
| Version | 4 |
| IHL | header length, in 4-byte words |
| DSCP / ToS | priority, QoS |
| Total length | header + data, max 65,535 |
| Identification, Flags (DF, MF), Fragment offset | fragmentation |
| TTL (time to live) | decremented by each router; 0 → dropped, ICMP time exceeded |
| Protocol | 1 = ICMP, 2 = IGMP, 6 = TCP, 17 = UDP |
| Header checksum | |
| Source IP, Destination IP | |
| Options | |

*Project link:* our code literally reads these. `pkt[0] >> 4` must be 4
(otherwise it's IPv6 and dropped), `pkt[9] == 2` means IGMP (ignored), and
`pkt[16:20]` is the destination used to pick which player gets the packet.

**Q. IPv4 vs IPv6?**

| | IPv4 | IPv6 |
|---|---|---|
| Address | 32 bits, dotted decimal (192.168.1.5) | **128 bits**, hex with colons (2001:db8::1) |
| Addresses | ~4.3 billion | 3.4 × 10³⁸ |
| Header | 20–60 B, variable, has a checksum | **40 B fixed**, no checksum, extension headers |
| Fragmentation | by routers and the sender | **sender only** (path MTU discovery) |
| Broadcast | yes | **no**: multicast and **anycast** instead |
| Configuration | manual / DHCP | **SLAAC** (auto) / DHCPv6 |
| Security | IPsec optional | IPsec designed in |
| NAT | widely used | not needed |

Transition: **dual stack**, **tunneling** (6to4), **translation** (NAT64).

**Q. Classful addressing?**

| Class | First bits | First octet | Default mask | Use |
|---|---|---|---|---|
| A | 0 | 0–127 | /8 (255.0.0.0) | huge networks |
| B | 10 | 128–191 | /16 | medium |
| C | 110 | 192–223 | /24 | small |
| D | 1110 | **224–239** | none | **multicast** |
| E | 1111 | 240–255 | none | reserved |

127.x.x.x = **loopback**. Problem: wasteful (a Class B with 65,534 hosts given
to an org that needs 2,000), so it was replaced by classless addressing.

*Project link:* Minecraft's LAN announcement goes to **224.0.2.60**, a
**Class D multicast** address. Our virtual LAN uses **10.77.0.0/24** from the
private Class A block 10.0.0.0/8.

**Q. Private addresses (RFC 1918) and special ranges?**
- Private: **10.0.0.0/8**, **172.16.0.0/12**, **192.168.0.0/16**. Not routed on
  the internet; need NAT.
- **100.64.0.0/10** = shared address space for **CGNAT** (RFC 6598).
- 169.254.0.0/16 = link-local (APIPA, when DHCP fails).
- 0.0.0.0 = "this host / any address"; 255.255.255.255 = limited broadcast.

**Q. Classless addressing and CIDR?**
**CIDR** (Classless Inter-Domain Routing): the network/host split can be at any
bit, written as a **prefix**, e.g. 200.10.20.0/22.
- Number of addresses = **2^(32 − n)**.
- First address = network address; last = broadcast; usable hosts = 2^(32−n) − 2.
- Lets ISPs aggregate routes (**supernetting / route summarization**), so
  routing tables shrink.

**Q. Subnetting: how?**
Borrow host bits to create more, smaller networks. Mask = n ones then zeros.
Network address = IP AND mask. Worked example in section 9.
*Project link:* 10.77.0.0/24 → mask 255.255.255.0, 256 addresses, 254 usable,
broadcast **10.77.0.255**. We forward that directed broadcast to every player.

**Q. NAT (Network Address Translation)?**
- The router replaces the private source address (and port) of outgoing
  packets with its public address and a port, and records the mapping in a
  table. Replies to that public port are translated back.
- **PAT / NAPT** (port address translation) lets a whole house share one
  public IP.
- Side effect: **unsolicited incoming packets are dropped**, since there is no
  mapping. That's the whole problem our project solves.
- NAT types:
  - **Full cone**: once a mapping exists, anyone can send to it.
  - **Restricted cone**: only IPs we've sent to can reply.
  - **Port-restricted cone**: only the exact IP:port we sent to.
  - **Symmetric**: a *new* public port for every destination. Hole punching
    fails, because the port the server saw isn't the one the peer will see.
- **CGNAT** (carrier-grade NAT): the ISP adds another NAT layer and gives
  customers 100.64.x.x addresses. No router setting can open a port.

*Project link:* we detect symmetric NAT by asking **two different STUN
servers** for our public address. Different ports in the answers = symmetric.

**Q. ARP and RARP?**
- **ARP** (Address Resolution Protocol): IP address → MAC address on a LAN.
  The request is a **broadcast** ("who has 192.168.1.1?"), the reply is
  **unicast**. Results are cached in the ARP table (`arp -a`).
- **RARP** (Reverse ARP): MAC → IP, for diskless machines at boot. Obsolete;
  replaced by **BOOTP** then **DHCP**.

*Project link:* our TUN adapter is layer 3, so there's no ARP. Our server does
a similar job one level up: it maps each **virtual IP → the player's public
IP:port**, like an ARP table for the overlay.

**Q. ICMP (Internet Control Message Protocol)?**
- Error reporting and diagnostics for IP; carried inside IP (protocol 1).
- Error messages:
  - **destination unreachable** (type 3);
  - **time exceeded** (11: TTL hit 0, used by **traceroute / tracert**);
  - **redirect** (5);
  - parameter problem.
- Query messages: **echo request (8) / echo reply (0)** = **ping**.

*Project link:* our Windows test injects an ICMP echo request into the virtual
adapter and checks that Windows answers with an echo reply (type 0). We also
use `ping 10.77.0.1` as the first live check.

**Q. Routing vs forwarding?**
- **Routing** = building the table (the control plane, routing protocols).
- **Forwarding** = looking up each packet's destination in the table and
  sending it out (the data plane).

**Longest prefix match** wins.

**Q. Distance-vector routing?**
- Each router keeps a table of {destination, distance, next hop} and
  periodically sends its **whole table to its neighbors**. Each router
  computes paths with the **Bellman–Ford** equation:
  D(x,y) = min over neighbors v of { c(x,v) + D(v,y) }.
- Knows only neighbors ("routing by rumor").
- Problem: **count-to-infinity** (slow reaction to a link failure).
- Fixes: **split horizon**, **poison reverse**, hold-down timers, a maximum
  hop count.

**Q. Link-state routing?**
- Each router floods **LSAs/LSPs** (its links and costs) to *all* routers, so
  everyone builds the full map, then runs **Dijkstra's shortest path** from
  itself.
- Converges faster, no count-to-infinity.
- Uses more memory/CPU and floods updates.

**Q. RIP vs OSPF vs BGP?**

| | RIP | OSPF | BGP |
|---|---|---|---|
| Type | distance vector | link state | **path vector** |
| Scope | inside an AS (IGP) | inside an AS (IGP) | **between ASes** (EGP); the internet's protocol |
| Metric | **hop count**, max 15 (16 = unreachable) | **cost** (based on bandwidth) | policies, AS-path length |
| Updates | full table every **30 s** | on change (+ refresh), hello packets | incremental, on change |
| Transport | UDP port **520** | directly on IP (protocol **89**) | TCP port **179** |
| Algorithm | Bellman–Ford | Dijkstra; **areas**, backbone area 0 | best path by attributes, loop-free via the AS path |
| Use | small networks | large enterprise | ISPs |

**AS** = autonomous system: one organization's network, identified by an
**ASN**.

*Project link:* our "routing" is a one-hop overlay. For each player we pick
between two paths, **direct** or **via relay**, using liveness (keepalives) as
the metric, and **fail over** automatically. Locally, we set the virtual
adapter's **interface metric to 1** so Windows prefers it for broadcast and
multicast.

---

## 6. Unit IV: Transport Layer

**Q. Services of the transport layer?**
- **Process-to-process** delivery (using **port numbers**);
- multiplexing/demultiplexing;
- optionally reliability, ordering, **flow control** and **congestion
  control** (TCP).
- Segmentation and reassembly.

**Q. Multiplexing and demultiplexing?**
- **Multiplexing** (sender): many applications send through one network
  layer; each segment is tagged with port numbers.
- **Demultiplexing** (receiver): deliver each segment to the right socket by
  port.
  - **UDP**: by (destination IP, destination port).
  - **TCP**: by the **4-tuple** (source IP, source port, destination IP,
    destination port).

*Project link:* we do **application-level multiplexing on a single UDP
socket**. Control messages, punches, keepalives, chat and game packets for up
to 7 other players all share **one port**. The first byte says what it is:
- `{` = JSON control;
- `0x01` = direct game packet;
- `0x02` / `0x03` = relayed game packet.

The sender's address plus a 3-byte player id say who it's from.

**Q. Port number ranges?**
- **Well-known**: 0–1023 (HTTP 80, HTTPS 443, DNS 53, SSH 22).
- **Registered**: 1024–49151.
- **Dynamic / ephemeral**: 49152–65535 (temporary client ports).

*Project link:* our server uses UDP **9000**; Minecraft Java's LAN discovery
uses UDP **4445**.

**Q. What is a socket?**
An endpoint for communication = **IP address + port** (+ protocol). The socket
API calls:
- `socket()`, `bind()`;
- TCP: `listen()`, `accept()`, `connect()`, `send()` / `recv()`;
- UDP: `sendto()` / `recvfrom()`;
- `close()`.

*Project link:* each player has one UDP socket. We use
`sendto`/`recvfrom`, `SO_BROADCAST`, and `IP_ADD_MEMBERSHIP` (joining a
multicast group) in the tests. On Windows we also turn off
`SIO_UDP_CONNRESET`, otherwise an ICMP "port unreachable" makes the next
`recvfrom` fail. That was a real bug we fixed.

**Q. UDP (User Datagram Protocol)?**
- **Connectionless**, unreliable, no ordering, no flow or congestion control,
  **message-oriented**.
- Tiny **8-byte header**: source port, destination port, length, checksum.
- Low latency.
- Used by DNS, DHCP, SNMP, TFTP, RTP, VoIP, **online games**, QUIC.

**Q. Why did your project use UDP and not TCP?**
1. **Hole punching** works naturally with UDP: both sides just send. TCP needs
   a simultaneous open, which many NATs handle badly.
2. **No TCP-over-TCP**: the games' own TCP connections (Minecraft uses TCP)
   travel *inside* our tunnel. If the tunnel were TCP too, a loss would make
   *both* layers retransmit and back off. Delays snowball ("TCP meltdown").
   With UDP outside, only the inner TCP does reliability, which is correct.
3. Low latency for real-time games, and broadcast/multicast exist only in UDP.

**Q. RTP (Real-time Transport Protocol)?**
- Carries **real-time audio/video** over **UDP**.
- Header adds a **sequence number** (detect loss, reorder), a **timestamp**
  (playout timing, jitter), a **payload type** (codec) and an **SSRC**
  (source id).
- Companion **RTCP** sends quality reports (loss, jitter).
- Used in VoIP, video calls, WebRTC.

*Project link:* WebRTC (browser video calls) uses **exactly** our NAT toolkit:
STUN + TURN + hole punching (combined in a framework called **ICE**).

**Q. TCP: services and features?**
- **Connection-oriented**;
- **reliable** (ACKs + retransmission);
- **in-order byte stream**;
- **full-duplex**;
- **flow control**, **congestion control**;
- point-to-point.

**Q. TCP segment header?**
- Source port, destination port;
- **sequence number** (number of the first byte in the segment);
- **acknowledgment number** (next byte expected);
- header length (20–60 B);
- flags: **URG, ACK, PSH, RST, SYN, FIN**;
- **window size** (receive window, for flow control);
- checksum, urgent pointer, options (MSS, window scale, SACK, timestamps).

**Q. TCP three-way handshake?**
1. Client → Server: **SYN**, seq = x.
2. Server → Client: **SYN + ACK**, seq = y, ack = x + 1.
3. Client → Server: **ACK**, ack = y + 1.

Purpose: agree on initial sequence numbers in both directions and confirm both
can send and receive. Closing: **FIN → ACK, FIN → ACK** (four-way; can be
three with FIN+ACK). **TIME_WAIT** = 2 × MSL. A **SYN flood** attack abuses
half-open connections (defense: SYN cookies).

*Project link (analogy):* our punch is a handshake too. Each side sends
`punch`, and the link is DIRECT only after a `punch_ack` proves packets flow
both ways.

**Q. Flow control and buffering?**
- The receiver advertises its free buffer space (**rwnd**, the receive
  window) in every segment. The sender keeps unacknowledged data ≤ rwnd.
  It's a **sliding window**.
- Window 0 → the sender stops and sends **window probes**.

**Q. Silly window syndrome?**
- Lots of tiny segments waste bandwidth (a 40-byte header for 1 byte of data).
- **Sender side** (the application writes 1 byte at a time): **Nagle's
  algorithm**. Send the first byte, then buffer until the ACK arrives or a
  full MSS is ready.
- **Receiver side** (the application reads slowly, advertises tiny windows):
  **Clark's solution**, which advertises 0 until there's room for an MSS or
  half the buffer. Also **delayed ACK**.

**Q. Congestion control in TCP?**
- **cwnd** (congestion window) limits the sender. Effective window =
  min(cwnd, rwnd).
- **Slow start**: cwnd starts at 1 MSS and **doubles every RTT** (exponential)
  until **ssthresh**.
- **Congestion avoidance**: then +1 MSS per RTT (linear). This is **AIMD**:
  additive increase, multiplicative decrease.
- On a **timeout** (severe): ssthresh = cwnd / 2, cwnd = 1, back to slow start
  (**Tahoe**).
- On **3 duplicate ACKs** (mild): **fast retransmit** + **fast recovery**:
  ssthresh = cwnd / 2, cwnd = ssthresh (**Reno**).
- Modern variants: CUBIC, BBR.

**Q. Leaky bucket vs token bucket (traffic shaping)?**
- **Leaky bucket**: packets go into a bucket (queue) and leak out at a
  **constant rate**; overflow is dropped. It turns bursty traffic into a
  smooth flow, but allows **no bursts**.
- **Token bucket**: tokens are added at rate r up to capacity b; sending a
  packet uses a token. It allows **bursts up to b** while limiting the average
  rate to r, and saves up credit when idle. More flexible.
- They are often combined: token bucket then leaky bucket.

**Q. QoS (Quality of Service)?**
- Flow characteristics: **reliability, delay (latency), jitter (variation in
  delay), bandwidth**.
- Techniques:
  - scheduling: FIFO, priority queuing, **weighted fair queuing**;
  - **traffic shaping** (leaky/token bucket);
  - admission control;
  - **resource reservation**.
- Models:
  - **IntServ** (per-flow reservation with **RSVP**);
  - **DiffServ** (mark packets with DSCP classes; routers give each class a
    treatment).

*Project link:* games care most about **delay and jitter**, which is why we
prefer a **direct** path (one hop) over the relay (two hops), and why we use
UDP. Our relay has no bandwidth limit, so a token bucket per player would be
a natural improvement.

---

## 7. Unit V: Application Layer

**Q. DHCP (Dynamic Host Configuration Protocol)?**
- Automatically gives a host its IP address, **subnet mask**, **default
  gateway** and **DNS server**, for a **lease** time.
- The **DORA** process:
  1. **D**iscover: client broadcast, "any DHCP server?";
  2. **O**ffer: the server offers an IP;
  3. **R**equest: the client asks for that IP (broadcast, so other servers
     know);
  4. **A**cknowledge: the server confirms.
- UDP ports **67** (server) and **68** (client). Renewal at 50% of the lease.
- **DHCP relay agent** for other subnets. Successor of BOOTP/RARP.

*Project link:* our rendezvous server does a **DHCP-like job** for the
virtual LAN. When a player registers, it hands out the lowest free address in
10.77.0.0/24. A returning player asks for its previous address and gets it if
free, just like a DHCP client requesting its old lease.

**Q. HTTP (HyperText Transfer Protocol)?**
- Request/response, **stateless** (state via **cookies**), over TCP port
  **80**. **HTTPS** = HTTP over TLS, port **443**.
- **Methods**: GET, POST, PUT, DELETE, HEAD, PATCH, OPTIONS.
- **Status codes**:
  - 1xx informational;
  - **2xx success** (200 OK);
  - **3xx redirect** (301, 302, 304 Not Modified);
  - **4xx client error** (400, 401, 403, **404 Not Found**);
  - **5xx server error** (500, 503).
- **Non-persistent** (HTTP/1.0: one object per TCP connection) vs
  **persistent** (HTTP/1.1 keep-alive, pipelining).
- **HTTP/2** (binary, multiplexed streams), **HTTP/3** (over QUIC/UDP).
- Proxies and caches.

*Project link:*
- **UPnP** port opening sends **SOAP** (XML) messages to the router over
  **HTTP POST**, after finding the router with **SSDP** (HTTP-like messages
  over UDP multicast 239.255.255.250:1900).
- The mailbox uses **HTTPS** POST/GET to ntfy.sh.
- The demo dashboard is HTTP + **WebSocket**.

**Q. FTP (File Transfer Protocol)?**
- Uses **two TCP connections**: **control** on port **21** (commands like
  USER, PASS, RETR, STOR, LIST; persistent) and **data** on port **20**
  (active mode, one per file).
- Control is "**out-of-band**".
- **Active mode**: the server connects back to the client.
- **Passive mode**: the client connects to a server port. That's what works
  through NAT/firewalls.
- Plaintext → SFTP / FTPS for security. **TFTP** = trivial FTP over UDP 69.

*Project link (great point):* FTP active mode breaks through NAT because the
client puts its *private* IP inside the command, and the server can't connect
to it. Routers need an **ALG** (application-level gateway) to rewrite it. Same
family of problem as ours.

**Q. TELNET?**
- Remote terminal login, TCP port **23**. Uses **NVT** (network virtual
  terminal) to hide terminal differences.
- **Sends everything, including passwords, in plaintext**, so it was replaced
  by **SSH** (port 22, encrypted).

**Q. SMTP, POP3, IMAP?**
- **SMTP** (Simple Mail Transfer Protocol): a **push** protocol that
  sends mail from client to server and server to server. TCP port **25** (587
  for submission with auth, 465 for SMTPS). Commands: HELO/EHLO, MAIL FROM,
  RCPT TO, DATA, QUIT.
- **POP3** (Post Office Protocol v3): a **pull** protocol that downloads mail
  to the device and usually **deletes it from the server**. Port **110** (995
  with TLS). Simple, offline-friendly, bad for multiple devices.
- **IMAP** (Internet Message Access Protocol): a **pull** protocol that
  **keeps mail on the server**, with folders and read/unread state synced
  across devices. Port **143** (993 with TLS).
- Path of an email: sender's client → (SMTP) → sender's mail server → (SMTP)
  → receiver's mail server → (POP3/IMAP) → receiver's client.
  - **MUA** = mail user agent (the client).
  - **MTA** = mail transfer agent (the server).

**Q. MIME?**
**Multipurpose Internet Mail Extensions**. SMTP only carries 7-bit ASCII text;
MIME lets email carry other languages, HTML, images and attachments.
- Headers: **MIME-Version**, **Content-Type** (e.g. text/html, image/jpeg,
  multipart/mixed), **Content-Transfer-Encoding** (**base64**,
  quoted-printable), Content-Disposition.
- MIME types are also used by HTTP (`Content-Type`).

**Q. DNS (Domain Name System)?**
- Translates names to IP addresses. A **distributed, hierarchical** database:
  - **root** servers (13 named root servers, many copies);
  - **TLD** servers (.com, .in, .org);
  - **authoritative** servers for each domain;
  - the **local/recursive resolver** (your ISP or 8.8.8.8).
- **Recursive** query: the resolver does all the work. **Iterative**: each
  server refers you onward. Answers are **cached** for their **TTL**.
- Records:
  - **A** (IPv4), **AAAA** (IPv6);
  - **CNAME** (alias), **MX** (mail server), **NS** (name server);
  - **PTR** (reverse lookup), **TXT**, **SOA**.
- Uses UDP port **53** (TCP for zone transfers and large answers).
- Tools: `nslookup`, `dig`.

*Project link:* the app resolves stun.l.google.com, ntfy.sh and the TURN
servers with DNS (`getaddrinfo`). A real DNS failure showed up in our tests:
a relay hostname that didn't exist gave **getaddrinfo error 11001**, Windows'
"host not found".

**Q. SNMP (Simple Network Management Protocol)?**
- Monitors and manages network devices.
  - The **manager** (NMS) queries **agents** on devices.
  - Data is organized in the **MIB** (Management Information Base), each item
    named by an **OID**.
  - Rules: **SMI**.
- Operations: **GET**, GET-NEXT, GET-BULK, **SET**, **TRAP** (the agent alerts
  the manager unasked), INFORM.
- UDP ports **161** (agent) and **162** (traps). v1/v2c use community strings
  (plaintext); **v3** adds authentication and encryption.

**Q. Which protocols use TCP and which UDP?**
- **TCP**: HTTP/HTTPS, FTP, TELNET, SSH, SMTP, POP3, IMAP, BGP.
- **UDP**: DNS (mostly), DHCP, SNMP, TFTP, RIP, RTP, NTP, STUN, our tunnel.

---

## 8. Glossary: every short form and buzzword

### From the project

| Term | Full form | What it means (one line) |
|---|---|---|
| **LAN** | Local Area Network | computers in one home/office connected through one router or switch |
| **Virtual LAN** | | a LAN that exists in software, spread over the internet. ⚠ Not the same as **VLAN** (IEEE 802.1Q tags that split one switch into several LANs). Examiners may test this. |
| **VPN** | Virtual Private Network | an encrypted or private network tunnelled over the public internet. Ours is "VPN-like", but game traffic isn't encrypted. |
| **Overlay network** | | a network built on top of another (ours runs on top of the internet) |
| **P2P** | Peer-to-Peer | computers talk directly, without a central server in the middle |
| **Rendezvous server** | | "meeting point" server that introduces peers and tells them each other's addresses |
| **Relay** | | sending traffic through a middle machine when a direct path is impossible |
| **NAT** | Network Address Translation | the router's address sharing; blocks unsolicited incoming packets |
| **CGNAT** | Carrier-Grade NAT | the ISP's own extra NAT; customers get 100.64.x.x addresses and can't open ports |
| **Cone / Symmetric NAT** | | cone keeps one public port per socket (punchable); symmetric uses a new port per destination (not punchable) |
| **Hole punching** | | both peers send to each other at the same time so both NATs create mappings and let the other in |
| **STUN** | Session Traversal Utilities for NAT | server that tells you your public IP:port as the internet sees it |
| **TURN** | Traversal Using Relays around NAT | standard relay server for when direct connection fails |
| **ICE** | Interactive Connectivity Establishment | the WebRTC framework that combines STUN + TURN + candidate checking; our approach is a simplified version |
| **UPnP** | Universal Plug and Play | lets a program ask the router to forward a port automatically |
| **IGD** | Internet Gateway Device | the UPnP "profile" a router implements for port mapping |
| **SSDP** | Simple Service Discovery Protocol | how UPnP finds the router (UDP multicast 239.255.255.250:1900) |
| **SOAP** | Simple Object Access Protocol | XML messages over HTTP; UPnP uses it to send the "add port mapping" command |
| **NAT-PMP** | NAT Port Mapping Protocol | Apple's simpler alternative to UPnP (UDP port 5351) |
| **Port forwarding** | | a router rule: "send incoming traffic on port X to this PC" |
| **Keepalive** | | small periodic packet that keeps a NAT mapping open and proves the path is alive |
| **Watchdog** | | timer that declares a path dead after silence (3.5 s for us) |
| **State machine** | | a program that is always in one named state and moves between states on events |
| **TUN / TAP** | tunnel / network tap | virtual network cards: TUN carries IP packets (layer 3), TAP carries Ethernet frames (layer 2) |
| **Wintun** | | the TUN driver for Windows (made by the WireGuard project) that we use |
| **NIC** | Network Interface Card | a network adapter, real or virtual |
| **Tunneling / Encapsulation** | | putting one packet inside another (a game's IP packet inside our UDP packet) |
| **MTU** | Maximum Transmission Unit | the largest packet a link carries (Ethernet 1500 B; our adapter 1280 B) |
| **MSS** | Maximum Segment Size | the largest TCP payload (MTU − 40 bytes) |
| **Fragmentation** | | splitting a packet that's too big for a link; we avoid it with a small MTU |
| **Unicast / Broadcast / Multicast / Anycast** | | to one host / to all hosts on the network / to a subscribed group / to the nearest of a group |
| **IGMP** | Internet Group Management Protocol | how hosts join multicast groups; we ignore it inside the tunnel |
| **Interface metric** | | Windows' preference number for an adapter; lower = preferred (ours is 1) |
| **Firewall** | | filters packets by rules; Windows Firewall has Private/Public **profiles** |
| **Network profile** | | Windows labels each network Private (trusted) or Public (strict); we mark ours Private |
| **Mailbox (ntfy.sh)** | | free public message service we use to swap addresses for 6-digit codes |
| **SHA-256** | Secure Hash Algorithm, 256-bit | one-way hash; we use it to scramble codes and derive keys |
| **HMAC** | Hash-based Message Authentication Code | a keyed hash that proves a message wasn't tampered with |
| **XOR** | exclusive OR | bit operation; reversible, so it's used to scramble the 10-digit code and in encryption |
| **CTR mode** | Counter mode | turns a hash or cipher into a stream cipher by hashing a counter |
| **Latency / RTT** | Round-Trip Time | time for a packet to go and come back (what `ping` shows) |
| **Jitter** | | variation in latency; bad for games and voice |
| **Throughput / Bandwidth** | | how much data per second gets through / the link's capacity |
| **RFC** | Request for Comments | the official internet standards documents (e.g. RFC 5389 = STUN) |
| **IETF / IEEE** | Internet Engineering Task Force / Institute of Electrical and Electronics Engineers | write internet protocols (RFCs) / write LAN standards (802.3, 802.11) |
| **IANA** | Internet Assigned Numbers Authority | assigns port numbers, protocol numbers, address blocks |
| **API** | Application Programming Interface | a defined way for programs to talk to each other |
| **JSON** | JavaScript Object Notation | the text format of our control messages ({"t": "punch", …}) |
| **GUI** | Graphical User Interface | the app's window |
| **Qt / PySide6** | | the cross-platform GUI toolkit / its official Python binding |
| **PyInstaller** | | packs a Python program into a single .exe |
| **UAC** | User Account Control | Windows' admin-permission prompt (needed to create a network adapter) |
| **CI** | Continuous Integration | automatic build + test on every change (GitHub Actions on real Windows) |
| **DLL** | Dynamic Link Library | a Windows code library (wintun.dll) |
| **netsh** | network shell | Windows command-line tool for addresses, firewall rules and so on |
| **Namespace (Linux netns)** | | an isolated copy of the network stack; we used them to build fake routers for testing |

### From the syllabus

| Short form | Full form |
|---|---|
| AM / FM / PM | Amplitude / Frequency / Phase Modulation |
| ASK / FSK / PSK | Amplitude / Frequency / Phase Shift Keying |
| QAM | Quadrature Amplitude Modulation |
| PCM | Pulse Code Modulation |
| NRZ-L / NRZ-I | Non-Return-to-Zero Level / Inverted |
| AMI | Alternate Mark Inversion |
| B8ZS / HDB3 | Bipolar with 8-Zero Substitution / High-Density Bipolar 3-zero |
| 4B/5B, 8B/10B | block codes: 4 data bits → 5 code bits, 8 → 10 |
| FDM / TDM / WDM | Frequency / Time / Wavelength Division Multiplexing |
| FDMA / TDMA / CDMA | Frequency / Time / Code Division Multiple Access |
| PAN / LAN / MAN / WAN | Personal / Local / Metropolitan / Wide Area Network |
| OSI | Open Systems Interconnection (ISO's 7-layer model) |
| ISO | International Organization for Standardization |
| TCP/IP | Transmission Control Protocol / Internet Protocol |
| UTP / STP | Unshielded / Shielded Twisted Pair |
| MAC | Media Access Control (address: 48-bit hardware address) |
| LLC | Logical Link Control |
| OUI | Organizationally Unique Identifier (first 24 bits of a MAC) |
| SFD / FCS | Start Frame Delimiter / Frame Check Sequence |
| CRC | Cyclic Redundancy Check |
| FEC | Forward Error Correction |
| ARQ | Automatic Repeat reQuest |
| ACK / NAK | Acknowledgment / Negative Acknowledgment |
| GBN / SR | Go-Back-N / Selective Repeat |
| CSMA | Carrier Sense Multiple Access |
| CSMA/CD / CSMA/CA | … with Collision Detection / Collision Avoidance |
| RTS / CTS | Request To Send / Clear To Send |
| IFS / DIFS / SIFS | (Distributed / Short) Inter-Frame Space |
| IPv4 / IPv6 | Internet Protocol version 4 / 6 |
| CIDR | Classless Inter-Domain Routing |
| VLSM | Variable Length Subnet Mask |
| NAT / PAT / NAPT | Network / Port / Network Address & Port Translation |
| ARP / RARP | Address Resolution Protocol / Reverse ARP |
| BOOTP | Bootstrap Protocol |
| ICMP | Internet Control Message Protocol |
| TTL | Time To Live |
| DSCP / ToS | Differentiated Services Code Point / Type of Service |
| DF / MF | Don't Fragment / More Fragments (IPv4 flags) |
| SLAAC | Stateless Address Autoconfiguration (IPv6) |
| AS / ASN | Autonomous System / AS Number |
| IGP / EGP | Interior / Exterior Gateway Protocol |
| DV / LS | Distance Vector / Link State |
| RIP | Routing Information Protocol |
| OSPF | Open Shortest Path First |
| LSA | Link-State Advertisement |
| BGP | Border Gateway Protocol |
| UDP | User Datagram Protocol |
| RTP / RTCP | Real-time Transport Protocol / RTP Control Protocol |
| SYN / ACK / FIN / RST / PSH / URG | Synchronize / Acknowledge / Finish / Reset / Push / Urgent (TCP flags) |
| rwnd / cwnd / ssthresh | receive window / congestion window / slow-start threshold |
| AIMD | Additive Increase, Multiplicative Decrease |
| QoS | Quality of Service |
| IntServ / DiffServ / RSVP | Integrated Services / Differentiated Services / Resource Reservation Protocol |
| WFQ | Weighted Fair Queuing |
| DHCP / DORA | Dynamic Host Configuration Protocol / Discover-Offer-Request-Acknowledge |
| HTTP / HTTPS | HyperText Transfer Protocol (Secure) |
| URL | Uniform Resource Locator |
| TLS / SSL | Transport Layer Security / Secure Sockets Layer (older) |
| FTP / TFTP / SFTP | File Transfer Protocol / Trivial FTP / SSH FTP |
| SSH | Secure Shell |
| NVT | Network Virtual Terminal (TELNET) |
| SMTP | Simple Mail Transfer Protocol |
| POP3 | Post Office Protocol version 3 |
| IMAP | Internet Message Access Protocol |
| MIME | Multipurpose Internet Mail Extensions |
| MUA / MTA | Mail User Agent / Mail Transfer Agent |
| DNS | Domain Name System |
| TLD / FQDN | Top-Level Domain / Fully Qualified Domain Name |
| SNMP | Simple Network Management Protocol |
| MIB / OID / SMI | Management Information Base / Object Identifier / Structure of Management Information |
| NMS | Network Management Station |

---

## 9. Worked numericals (practice these on paper)

**CRC.** Data = 1001, generator = 1011 (x³ + x + 1, degree 3).
- Append 3 zeros: 1001**000**.
- Divide with XOR:
  - 1001000 XOR 1011000 = 0010000;
  - 0010000 XOR 0010110 = 0000**110**.
- Remainder = **110**, so the transmitted codeword = 1001**110**.
- Check at the receiver:
  - 1001110 XOR 1011000 = 0010110;
  - 0010110 XOR 0010110 = 0000000.
- Remainder 0 → no error.

**Hamming (7,4), even parity.** Data bits 1011 go in positions 3, 5, 6, 7
(d3=1, d5=0, d6=1, d7=1).

1. Work out the parity bits:
   - P1 covers positions 1, 3, 5, 7 → d3+d5+d7 = 1+0+1 = 2 (even) → **P1 = 0**.
   - P2 covers 2, 3, 6, 7 → 1+1+1 = 3 (odd) → **P2 = 1**.
   - P4 covers 4, 5, 6, 7 → 0+1+1 = 2 → **P4 = 0**.
2. Codeword (positions 1–7) = **0 1 1 0 0 1 1** = 0110011.
3. Suppose bit 6 flips in transit, giving 0110001. The receiver rechecks:
   - C1 (1, 3, 5, 7) = 0+1+0+1 = even → 0;
   - C2 (2, 3, 6, 7) = 1+1+0+1 = odd → 1;
   - C4 (4, 5, 6, 7) = 0+0+0+1 = odd → 1.
4. Syndrome C4 C2 C1 = **110 = 6**, so bit 6 is wrong. Flip it back.

**Internet checksum (16-bit words, shown in 4-bit chunks for practice).**
- Words: 0110, 1010, 1111 (4-bit version).
- 0110 + 1010 = 1 0000 → wrap the carry: 0000 + 1 = 0001.
- 0001 + 1111 = 1 0000 → wrap: 0001.
- Checksum = complement = **1110**.
- Receiver: sum of all words plus the checksum = 1111 → complement 0000 → OK.

**Subnetting.** Split 192.168.1.0/24 into 4 equal subnets.
- Borrow 2 bits → /26, mask 255.255.255.192, 64 addresses each, **62 usable**.
- Subnets: .0–.63, .64–.127, .128–.191, .192–.255.
  - Network addresses: .0, .64, .128, .192.
  - Broadcast addresses: .63, .127, .191, .255.

**Which subnet is 172.16.45.130/20 in?**
- /20 → mask 255.255.240.0. The third octet goes in blocks of 16.
- 45 is in the block 32–47 → network **172.16.32.0/20**.
- Broadcast **172.16.47.255**.
- Hosts 172.16.32.1 – 172.16.47.254 (4094 usable).

**Our own network.** 10.77.0.0/24 → mask 255.255.255.0, network 10.77.0.0,
broadcast 10.77.0.255, usable 10.77.0.1–10.77.0.254 (254 hosts; we cap a
network at 8 players).

**ALOHA.**
- Frame time 1 ms, load G = 0.5 frames per frame time:
  - **pure ALOHA**: S = 0.5·e⁻¹ ≈ 0.184 → 18.4%;
  - **slotted ALOHA** at G = 1: S = e⁻¹ ≈ 0.368 → 36.8%.
- Bandwidth 200 kbps, frame 200 bits:
  - T_fr = 1 ms;
  - pure ALOHA vulnerable time = 2 ms; slotted = 1 ms.

**Nyquist / PCM.** Voice up to 4 kHz → sample at ≥ 8 kHz. With 8 bits per
sample → 64 kbps.

**CSMA/CD minimum frame.** At 10 Mbps, the slot time is 51.2 µs (512 bit
times) → minimum frame = 512 bits = **64 bytes**.

---

## 10. Likely "project" questions in a CN viva, with short answers

- **Which OSI layer does your project work at?** We read and forward
  **layer 3** (IP) packets, transport them over **layer 4** (UDP), and the
  control protocol is **layer 7** (application). It's a layer-3 tunnel / VPN.
- **Is it secure?** Joining needs the network name and the code, and packets
  from unknown addresses are dropped. Game traffic isn't encrypted; the next
  step would be WireGuard-style encryption.
- **What happens if a direct path drops mid-game?** Keepalives stop arriving.
  After 3.5 s the watchdog switches that player to the relay (RECONNECTING),
  and the game keeps running while we re-punch. The inner TCP retransmits
  anything lost.
- **Why does Minecraft's LAN list work?** The game multicasts to
  224.0.2.60:4445. We copy every multicast/broadcast packet to all players.
  The adapter has interface metric 1, so Windows sends multicast through it.
- **How many players / what speed?** Up to 8 per network (a full mesh of 28
  links). TCP through the tunnel measured about 15 MB/s, far more than games
  need.
- **What was the hardest bug?**
  - Windows' `SIO_UDP_CONNRESET` behavior.
  - Windows Firewall blocking games on "Public" networks: we mark the adapter
    Private.
  - Routers that can't loop back to their own public IP (hairpin NAT): we
    discover hosts in the same house by LAN broadcast.
- **How did you test NAT without many routers?** Linux **network
  namespaces** with iptables MASQUERADE as fake home routers, including
  symmetric NAT and CGNAT modes, plus automated tests on real Windows in CI.
