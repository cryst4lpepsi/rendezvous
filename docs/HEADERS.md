# CN viva revision: every header and packet format

Sizes are in **bytes (B)** unless marked **bits (b)**. ★ = most likely to be asked.

## 0. The big picture: encapsulation

| Layer | PDU name | Header added | Typical size |
|---|---|---|---|
| Application | message / data | HTTP, DNS, DHCP… | varies |
| Transport | **segment** (TCP) / **user datagram** (UDP) | TCP / UDP | 20–60 / 8 |
| Network | **packet / datagram** | IPv4 / IPv6 | 20–60 / 40 |
| Data link | **frame** | Ethernet header + trailer | 14 + 4 (FCS) |
| Physical | **bits** | preamble + SFD | 8 |

**A web request on the wire:**
`[Preamble 7 | SFD 1] [Eth 14] [IPv4 20] [TCP 20] [HTTP …] [FCS 4]`

**A DNS query on the wire:**
`[Eth 14] [IPv4 20] [UDP 8] [DNS 12 + question] [FCS 4]`

---

## 1. Data link layer

### ★ Ethernet frame (IEEE 802.3 / Ethernet II)
| Field | Size | Notes |
|---|---|---|
| Preamble | 7 B | 10101010… for clock synchronization (added by the physical layer) |
| SFD (Start Frame Delimiter) | 1 B | 10101011, "frame starts now" |
| Destination MAC | 6 B | FF:FF:FF:FF:FF:FF = broadcast |
| Source MAC | 6 B | |
| Type (Ethernet II) / Length (802.3) | 2 B | ≥ 0x0600 = EtherType; ≤ 1500 = length |
| Data + padding | **46–1500 B** | padded up to 46 |
| FCS (Frame Check Sequence) | 4 B | **CRC-32** |

- Frame size (without preamble/SFD): **min 64 B, max 1518 B**. MTU = 1500.
- **EtherTypes**:
  - **0x0800** IPv4;
  - **0x0806** ARP;
  - **0x8035** RARP;
  - **0x86DD** IPv6;
  - **0x8100** VLAN tag.
- **802.1Q VLAN tag** (4 B, inserted after the source MAC): TPID 0x8100 (16 b),
  PCP priority (3 b), DEI (1 b), **VLAN ID (12 b) → 4094 VLANs**.

### IEEE 802.11 (Wi-Fi) frame
| Frame Control | Duration/ID | Address 1 | Address 2 | Address 3 | Sequence Control | Address 4 | Body | FCS |
|---|---|---|---|---|---|---|---|---|
| 2 | 2 | 6 | 6 | 6 | 2 | 6 | 0–2312 | 4 |

- The header is 30 B. The 4 addresses are receiver, transmitter, source and
  destination; which is which depends on the To-DS / From-DS bits.
- Frame types:
  - **Management**: beacon, probe request/response, authentication,
    association.
  - **Control**: **RTS, CTS, ACK**.
  - **Data**.

### HDLC frame
| Flag | Address | Control | Information | FCS | Flag |
|---|---|---|---|---|---|
| 01111110 | 1 B+ | 1–2 B | variable | 2 or 4 B | 01111110 |

- Uses **bit stuffing**: after five 1s, insert a 0.
- Three frame types:
  - **I-frame** (information): carries data, with N(S)/N(R) sequence
    numbers.
  - **S-frame** (supervisory): **RR** (receive ready), **RNR** (receive not
    ready), **REJ** (reject, i.e. Go-Back-N), **SREJ** (selective reject,
    i.e. Selective Repeat).
  - **U-frame** (unnumbered): link management (SABM, UA, DISC).

### PPP frame
| Flag 0x7E | Address 0xFF | Control 0x03 | Protocol 2 B | Payload | FCS 2/4 B | Flag 0x7E |
|---|---|---|---|---|---|---|

- Uses **byte stuffing**.
- Protocol values: **0x0021** IPv4, **0xC021 LCP** (link setup), **0x8021
  IPCP** (IP config), **0xC023 PAP**, **0xC223 CHAP** (authentication).

### ★ ARP / RARP packet (28 B, directly inside Ethernet)
| Field | Size | Value |
|---|---|---|
| Hardware type | 2 | 1 = Ethernet |
| Protocol type | 2 | 0x0800 = IPv4 |
| Hardware length | 1 | 6 |
| Protocol length | 1 | 4 |
| **Operation** | 2 | **1 = ARP request, 2 = ARP reply, 3 = RARP request, 4 = RARP reply** |
| Sender MAC | 6 | |
| Sender IP | 4 | |
| Target MAC | 6 | all 0s in a request (that's what we're asking for) |
| Target IP | 4 | |

- An ARP request is sent to the **broadcast** MAC; the reply is **unicast**.
- EtherType: ARP **0x0806**, RARP **0x8035**.

---

## 2. Network layer

### ★ IPv4 header (20–60 B)
| Field | Bits | Notes |
|---|---|---|
| Version | 4 | = 4 |
| IHL (header length) | 4 | in 4-byte words: 5 → 20 B, 15 → 60 B |
| DSCP + ECN (formerly ToS) | 6 + 2 | priority / QoS, congestion notification |
| Total length | 16 | header + data, max **65,535** |
| Identification | 16 | same for all fragments of one datagram |
| Flags | 3 | reserved, **DF** (don't fragment), **MF** (more fragments) |
| Fragment offset | 13 | in **8-byte units** |
| **TTL** (time to live) | 8 | −1 per router; 0 → drop + ICMP time exceeded (Linux 64, Windows 128) |
| **Protocol** | 8 | **1 ICMP, 2 IGMP, 6 TCP, 17 UDP**, 41 IPv6-in-IPv4, 50 ESP, 51 AH, **89 OSPF** |
| Header checksum | 16 | covers the **header only**; recomputed at each router (TTL changes) |
| Source IP | 32 | |
| Destination IP | 32 | |
| Options | 0–40 B | record route, timestamp, source routing |

**Fragmentation example.** A 4000-B datagram (20 B header + 3980 B data) over
MTU 1500. Each fragment carries at most 1480 B of data (a multiple of 8):

| Fragment | Data bytes | Offset (÷8) | MF |
|---|---|---|---|
| 1 | 0–1479 (1480) | 0 | 1 |
| 2 | 1480–2959 (1480) | 185 | 1 |
| 3 | 2960–3979 (1020) | 370 | 0 |

### ★ IPv6 base header (fixed 40 B)
| Field | Bits | Notes |
|---|---|---|
| Version | 4 | = 6 |
| Traffic class | 8 | like DSCP |
| Flow label | 20 | identifies a flow (real-time traffic) |
| Payload length | 16 | excludes the 40-B base header |
| **Next header** | 8 | the next extension header or upper protocol (6 TCP, 17 UDP, **58 ICMPv6**) |
| Hop limit | 8 | = TTL |
| Source address | 128 | |
| Destination address | 128 | |

- Removed compared with IPv4: **checksum, fragmentation fields, options, IHL**.
- **Extension headers** (chained by Next header): Hop-by-Hop (0), Routing (43),
  **Fragment (44)**, ESP (50), AH (51), Destination Options (60); 59 = no next
  header.
- Only the **source** fragments in IPv6, using the Fragment extension header.

### ★ ICMP message (inside IP, protocol 1)
| Type 8 b | Code 8 b | Checksum 16 b | Rest of header 32 b | Data |
|---|---|---|---|---|

- For echo, the rest of the header = **Identifier (16) + Sequence number (16)**.
- For error messages, the data = **the original IP header + the first 8 bytes**
  of the datagram that caused the error.

| Type | Meaning | Codes / use |
|---|---|---|
| **0** | Echo reply | ping |
| **3** | Destination unreachable | 0 network, 1 host, 2 protocol, **3 port**, **4 fragmentation needed but DF set** |
| 4 | Source quench | (deprecated) congestion |
| **5** | Redirect | better route exists |
| **8** | Echo request | ping |
| **11** | Time exceeded | 0 TTL expired (**traceroute**), 1 fragment reassembly timeout |
| 12 | Parameter problem | bad header |
| 13 / 14 | Timestamp request / reply | |

There are two classes: **error-reporting** messages (3, 4, 5, 11, 12) and
**query** messages (0/8, 13/14).

### IGMP (protocol 2)
- Fields: Type, Max response time, Checksum, Group address (8 B in v2).
- Types: membership **query**, **report** (join), **leave**.
- Hosts use it to tell routers which multicast groups they've joined.

### RIP message (UDP 520)
- Header (4 B): **Command** (1 = request, 2 = response), Version, 2 zero bytes.
- Then **up to 25 route entries, 20 B each**: address family 2, route tag 2
  (v2), IP address 4, subnet mask 4 (v2), next hop 4 (v2), **metric 4
  (1–15, 16 = infinity)**.
- RIPv1 has no mask (classful). RIPv2 adds the mask (classless) and
  authentication.

### OSPF header (24 B, IP protocol 89)
- Fields: Version 1, **Type 1**, Packet length 2, **Router ID 4**, **Area ID 4**,
  Checksum 2, Auth type 2, Authentication 8.

| Type | Packet | Purpose |
|---|---|---|
| 1 | **Hello** | discover neighbors, keep them alive |
| 2 | **DBD** (Database Description) | summary of the link-state database |
| 3 | **LSR** (Link State Request) | ask for specific LSAs |
| 4 | **LSU** (Link State Update) | carries **LSAs** |
| 5 | **LSAck** | acknowledge LSAs |

**LSA types**: 1 Router, 2 Network, 3 Summary, 4 ASBR summary, 5 AS-external.

### BGP header (19 B, over TCP 179)
- Fields: **Marker 16 B** (all 1s), Length 2 B, **Type 1 B**.

| Type | Message | Purpose |
|---|---|---|
| 1 | **OPEN** | start a session (AS number, hold time, BGP ID) |
| 2 | **UPDATE** | advertise/withdraw routes + path attributes (AS_PATH, NEXT_HOP, ORIGIN, LOCAL_PREF, MED) |
| 3 | **NOTIFICATION** | error; closes the session |
| 4 | **KEEPALIVE** | header only (19 B) |
| 5 | ROUTE-REFRESH | ask for routes again |

---

## 3. Transport layer

### ★ UDP header (8 B)
| Source port | Destination port | Length | Checksum |
|---|---|---|---|
| 16 b | 16 b | 16 b (header + data, min 8) | 16 b |

- The checksum is optional in IPv4 (0 = unused) and mandatory in IPv6.
- It covers a **pseudo-header** (source IP, destination IP, zero, protocol 17,
  UDP length) + the UDP header + data. The TCP checksum works the same way.

### ★ TCP segment header (20–60 B)
| Field | Bits | Notes |
|---|---|---|
| Source port | 16 | |
| Destination port | 16 | |
| **Sequence number** | 32 | number of the **first byte** of this segment's data |
| **Acknowledgment number** | 32 | **next byte expected** (valid when ACK = 1) |
| HLEN (data offset) | 4 | in 4-byte words (5 → 20 B, 15 → 60 B) |
| Reserved | 6 | textbook (modern TCP uses 2 for ECN: **CWR, ECE**) |
| Flags | 6 | **URG ACK PSH RST SYN FIN** |
| **Window size** | 16 | receive window, rwnd (flow control) |
| Checksum | 16 | with pseudo-header; mandatory |
| Urgent pointer | 16 | valid when URG = 1 |
| Options | 0–40 B | **MSS** (kind 2), window scale (3), SACK-permitted (4), SACK (5), timestamps (8), NOP (1), end (0) |

**Flags:**
- **SYN**: synchronize sequence numbers (open).
- **ACK**: the ack number is valid.
- **FIN**: finish (close).
- **RST**: reset/abort.
- **PSH**: push data to the application now.
- **URG**: urgent data.

**Segment "types" by flag:** SYN, SYN+ACK, ACK, FIN, FIN+ACK, RST, data
(PSH+ACK).

**Handshakes:**
- Open (3-way): **SYN (seq=x) → SYN+ACK (seq=y, ack=x+1) → ACK (ack=y+1)**.
- Close (4-way): **FIN → ACK, FIN → ACK**, then TIME_WAIT (2 × MSL).
- A SYN and a FIN each use up **one** sequence number even with no data.

### RTP header (12 B fixed, over UDP)
| Field | Bits | Notes |
|---|---|---|
| V (version) | 2 | = 2 |
| P (padding) | 1 | |
| X (extension) | 1 | |
| CC (CSRC count) | 4 | |
| M (marker) | 1 | e.g. end of a video frame |
| **PT (payload type)** | 7 | which codec |
| **Sequence number** | 16 | detect loss/reordering |
| **Timestamp** | 32 | playout timing, jitter |
| **SSRC** | 32 | synchronization source (the stream's id) |
| CSRC list | 0–15 × 32 | contributing sources (mixers) |

**RTCP packet types**: **200 SR** (sender report), **201 RR** (receiver
report), **202 SDES** (source description), **203 BYE**, **204 APP**.

---

## 4. Application layer

### ★ DHCP message (UDP: server 67, client 68)
| Field | Size | Notes |
|---|---|---|
| op | 1 | 1 = request (client), 2 = reply (server) |
| htype / hlen | 1 / 1 | 1 = Ethernet / 6 |
| hops | 1 | used by relay agents |
| **xid** | 4 | transaction ID |
| secs / flags | 2 / 2 | flags: broadcast bit |
| ciaddr | 4 | client's current IP |
| **yiaddr** | 4 | "**your**" IP, the one being offered |
| siaddr | 4 | server IP |
| giaddr | 4 | relay agent (gateway) IP |
| chaddr | 16 | client MAC |
| sname / file | 64 / 128 | server name / boot file |
| magic cookie | 4 | 99.130.83.99 |
| options | variable | see below |

- The fixed part is **236 B** + 4 B cookie.
- **Option 53, message type**:
  - **1 DISCOVER, 2 OFFER, 3 REQUEST, 5 ACK** (= **DORA**);
  - 4 DECLINE, 6 NAK, 7 RELEASE, 8 INFORM.
- Other options: 1 subnet mask, **3 router (gateway)**, **6 DNS server**,
  **51 lease time**, 50 requested IP, 54 server identifier.

### ★ DNS message (UDP/TCP 53)
**Header (12 B):**

| ID 16 b | Flags 16 b | QDCOUNT | ANCOUNT | NSCOUNT | ARCOUNT |
|---|---|---|---|---|---|

- **Flags**:
  - **QR** (1 b: 0 query, 1 response);
  - Opcode (4 b);
  - **AA** (authoritative answer);
  - **TC** (truncated → retry over TCP);
  - **RD** (recursion desired);
  - **RA** (recursion available);
  - Z (3 b);
  - **RCODE** (4 b: 0 NoError, 2 ServFail, **3 NXDOMAIN** = name doesn't
    exist).
- **Sections**:
  - **Question**: QNAME, QTYPE, QCLASS.
  - **Answer**, **Authority**, **Additional**: these hold resource records
    (**RRs**).
- **RR format**: NAME, TYPE, CLASS (IN), **TTL** (32 b), RDLENGTH, RDATA.
- **Record types**:
  - **A** (IPv4), **AAAA** (IPv6);
  - **CNAME** (alias), **MX** (mail server, with preference);
  - **NS** (name server), **PTR** (reverse lookup);
  - **SOA** (zone authority), **TXT**.

### ★ HTTP messages (TCP 80 / 443)
**Request:**
```
GET /index.html HTTP/1.1          <- request line: method, URL, version
Host: www.example.com             <- headers
User-Agent: Mozilla/5.0
Accept: text/html
Connection: keep-alive
                                   <- blank line (CRLF)
[body: only for POST/PUT]
```
**Response:**
```
HTTP/1.1 200 OK                    <- status line: version, code, phrase
Content-Type: text/html
Content-Length: 1234
Set-Cookie: id=42
                                   <- blank line
<html>...</html>                   <- body
```
- Methods: GET, POST, PUT, DELETE, HEAD, PATCH, OPTIONS.
- Status codes:
  - 1xx info;
  - **2xx success** (200 OK, 201 Created);
  - **3xx redirect** (301 moved, 302 found, 304 not modified);
  - **4xx client error** (400, 401 unauthorized, 403 forbidden, **404 not
    found**);
  - **5xx server error** (500, 502 bad gateway, 503 unavailable).
- Common headers:
  - request: Host, User-Agent, Accept, Cookie, Authorization,
    If-Modified-Since;
  - response: Server, Content-Type, Content-Length, Set-Cookie, Location,
    Last-Modified, Cache-Control.

### FTP (TCP 21 control, 20 data in active mode)
- **Commands**: USER, PASS, CWD, PWD, LIST, **RETR** (download), **STOR**
  (upload), DELE, MKD, **PORT** (active), **PASV** (passive), TYPE (A ASCII /
  I binary), QUIT.
- **Replies** (3-digit):
  - **150** opening data connection;
  - **200** OK;
  - **220** service ready;
  - **221** goodbye;
  - **226** transfer complete;
  - **230** logged in;
  - **331** need password;
  - **425** can't open data connection;
  - **530** not logged in.
- Reply classes: 1xx preliminary, 2xx done, 3xx need more, 4xx temporary
  error, 5xx permanent error.

### TELNET (TCP 23)
- Commands are sent inside the data stream, each prefixed by **IAC** (255).
- Option negotiation: **WILL (251), WON'T (252), DO (253), DON'T (254)**;
  SB/SE (sub-negotiation).
- Options include ECHO and SUPPRESS-GO-AHEAD.
- Uses **NVT** (network virtual terminal) encoding.

### SMTP (TCP 25 / 587)
- **Commands**: **HELO/EHLO, MAIL FROM:, RCPT TO:, DATA**, (message ending with
  a line holding just `.`), **QUIT**, RSET, VRFY, NOOP.
- **Replies**:
  - **220** service ready;
  - **250** OK;
  - **354** start mail input;
  - **221** closing;
  - 421 not available;
  - **550** mailbox unavailable.
- **Email message format** (RFC 5322): headers (**From, To, Cc, Subject, Date,
  Message-ID**), a blank line, then the body.

### MIME headers
- The headers:
  - **MIME-Version: 1.0**;
  - **Content-Type** (type/subtype, e.g. text/plain, text/html, image/jpeg,
    audio/mpeg, video/mp4, application/pdf, **multipart/mixed** with a
    boundary, message/rfc822);
  - **Content-Transfer-Encoding** (7bit, 8bit, binary, **base64**,
    quoted-printable);
  - Content-ID;
  - Content-Description;
  - Content-Disposition (attachment; filename=…).
- The 7 top-level types: text, image, audio, video, application, multipart,
  message.

### POP3 (TCP 110 / 995) and IMAP (TCP 143 / 993)
- **POP3** commands: USER, PASS, **STAT**, **LIST**, **RETR**, **DELE**, QUIT.
  Replies are **+OK** / **-ERR**. Modes: delete vs keep.
- **IMAP** commands: LOGIN, **SELECT** (a folder), **FETCH**, STORE (set
  flags like \Seen), SEARCH, COPY, LOGOUT. Every command carries a **tag**
  (e.g. A001), and replies are tagged **OK / NO / BAD**.

### SNMP (UDP 161 agent, 162 traps)
- **Message** = version + **community string** (v1/v2c "password") + **PDU**.
- **PDU fields**: PDU type, **request ID**, **error status**, **error index**,
  **variable bindings** (list of **OID = value**).
- **PDU types**:
  - **GetRequest**, **GetNextRequest** (walk a table);
  - **GetBulkRequest** (v2);
  - **SetRequest**;
  - **Response** (GetResponse);
  - **Trap** (agent → manager, unasked);
  - **InformRequest** (an acknowledged trap, v2).
- Encoded with **ASN.1 / BER**. Objects live in the **MIB**, e.g. sysUpTime,
  ifInOctets.

---

## 5. Numbers to remember

| Thing | Size |
|---|---|
| Ethernet header / trailer | 14 B / 4 B (CRC-32) |
| Ethernet payload | 46–1500 B; frame 64–1518 B |
| MAC address | 48 b (6 B) |
| VLAN tag | 4 B; VLAN ID 12 b |
| ARP packet | 28 B |
| IPv4 header | 20–60 B; address 32 b |
| IPv6 header | 40 B fixed; address 128 b |
| ICMP header | 8 B |
| UDP header | 8 B |
| TCP header | 20–60 B |
| RTP header | 12 B |
| DNS header | 12 B |
| DHCP fixed part | 236 B (+4 cookie) |
| OSPF header | 24 B |
| BGP header | 19 B |
| RIP | 4 B header + 20 B per route, ≤ 25 routes |
| Max IP datagram | 65,535 B |
| Max ports | 65,535 (16 b) |

## 6. Ports to remember

| Port | Protocol | | Port | Protocol |
|---|---|---|---|---|
| 20/21 | FTP data/control | | 110 | POP3 |
| 22 | SSH | | 143 | IMAP |
| 23 | TELNET | | 161/162 | SNMP / traps |
| 25 | SMTP | | 179 | BGP (TCP) |
| 53 | DNS | | 443 | HTTPS |
| 67/68 | DHCP server/client | | 520 | RIP (UDP) |
| 69 | TFTP | | 587 | SMTP submission |
| 80 | HTTP | | 993 / 995 | IMAPS / POP3S |
