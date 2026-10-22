# Computer Networks: syllabus viva revision (third-year CSE)

Pure syllabus, standard textbook level (Forouzan *Data Communications and
Networking*, Tanenbaum *Computer Networks*). Answers are short enough to say
out loud. ★ = asked in almost every viva.

Contents: Unit I – Unit V questions, then **Differences** (section 6),
**Formulas** (section 7) and **Numericals** (section 8). For field-by-field
header formats, see [HEADERS.md](HEADERS.md).

---

## Unit I: Fundamentals of networking and data communication

### Basics
- ★ **Data communication?** Exchange of data between two devices through a
  transmission medium. Five components: **message, sender, receiver, medium,
  protocol**.
- **Characteristics of a good system?** Delivery, accuracy, timeliness, low
  jitter.
- ★ **Protocol?** A set of rules governing communication. Its key elements
  are **syntax** (format), **semantics** (meaning) and **timing** (when, how
  fast).
- **Standard?** An agreed specification (de facto or de jure). Standards
  bodies: ISO, ITU-T, IEEE, ANSI, IETF (RFCs).
- **Transmission modes:**
  - **Simplex**: one way (keyboard, TV).
  - **Half-duplex**: both ways, one at a time (walkie-talkie).
  - **Full-duplex**: both ways at once (telephone).
- **Serial vs parallel:** one bit at a time over one line vs n bits at once
  over n lines. Serial transmission can be **asynchronous** (start/stop bits
  per byte), **synchronous** (continuous bit stream, framed) or
  **isochronous** (guaranteed fixed rate, for real-time media).
- **Signals:**
  - Analog = continuous; digital = discrete.
  - **Periodic** signals repeat; **aperiodic** ones don't.
  - A sine wave is described by **amplitude, frequency, phase**.
  - **Wavelength** = propagation speed / frequency.
- **Bandwidth?**
  - In hertz: the range of frequencies a channel passes.
  - In bits per second: the maximum data rate.
- ★ **Bit rate vs baud rate:** bits per second vs **signal elements per
  second**. Bit rate = baud rate × bits per signal element (log₂L).
- **Transmission impairments:**
  - **Attenuation**: loss of energy; amplifiers fix it; measured in dB.
  - **Distortion**: the signal's shape changes, because different
    frequencies travel at different speeds.
  - **Noise**: thermal, induced, **crosstalk**, impulse.
- **SNR** (signal-to-noise ratio) = signal power / noise power.
  SNR_dB = 10 log₁₀ SNR.
- **Performance measures:**
  - bandwidth, **throughput** (actual rate achieved);
  - **latency** = propagation + transmission + queuing + processing delay;
  - **bandwidth-delay product** (bits that "fill the pipe");
  - **jitter** (variation in delay).

### Analog-to-analog conversion (modulating an analog signal)
- **Why?** To send a low-frequency (baseband) analog signal over a band-pass
  channel such as radio, at the carrier frequency.
- **AM** (amplitude modulation): the carrier amplitude follows the message.
  Bandwidth **B_AM = 2B**.
- **FM** (frequency modulation): the carrier frequency varies.
  **B_FM = 2(1 + β)B**, by Carson's rule. Less affected by noise than AM.
- **PM** (phase modulation): the phase varies. **B_PM = 2(1 + β)B**.
  Needs simpler hardware than FM.

### Digital-to-analog conversion (shift keying)
- ★ The four types:
  - **ASK** (amplitude shift keying): amplitude levels represent bits. Very
    noise-sensitive. OOK (on-off keying) is binary ASK.
  - **FSK** (frequency shift keying): different frequencies represent bits.
  - **PSK** (phase shift keying): different phases. **BPSK** = 2 phases,
    **QPSK** = 4 phases = 2 bits per symbol.
  - **QAM** (quadrature amplitude modulation): amplitude **and** phase
    together, many bits per symbol (16-QAM = 4 bits). Used by modems,
    Wi-Fi and cable.
- **Constellation diagram**: plots each signal element as a point (amplitude
  = distance from the center, phase = angle).
- **Bandwidth**:
  - ASK and PSK: B = (1 + d)·S, where d is a filtering factor (0–1) and S is
    the baud rate.
  - FSK: B = (1 + d)·S + 2Δf.

### Digital-to-digital conversion
- ★ **Line coding** converts bits into a digital signal. Desired properties:
  no **DC component**, **self-synchronization** (a clock that can be
  recovered), built-in error detection, low bandwidth.
  - **Unipolar NRZ**: 0 = 0 V, 1 = +V. Has a DC component; obsolete.
  - **Polar**:
    - **NRZ-L**: level = bit.
    - **NRZ-I**: a 1 = invert the level, a 0 = no change.
    - **RZ**: returns to zero in the middle of the bit; 3 levels.
    - **Manchester**: transition in the middle of every bit (Forouzan: 0 =
      high-to-low, 1 = low-to-high). Used by 10 Mbps Ethernet.
    - **Differential Manchester**: always a middle transition; a 0 = an
      *extra* transition at the start of the bit. Used by token ring.

    Manchester types are self-clocking with no DC, but need **twice the
    bandwidth**.
  - **Bipolar**:
    - **AMI** (alternate mark inversion): 0 = 0 V, 1s alternate +/−.
    - **Pseudoternary**: the reverse.

    No DC component, but long runs of 0s lose synchronization.
  - **Multilevel**: 2B1Q, 8B6T, 4D-PAM5.
  - **Multitransition**: MLT-3.
- ★ **Block coding** (mB/nB): replace m-bit groups with n-bit codes (n > m).
  The redundancy guarantees synchronization (no long 0-runs) and detects some
  errors.
  - **4B/5B** is used with NRZ-I in Fast Ethernet; **8B/10B** in Gigabit
    Ethernet.
  - The steps: **division** into groups, **substitution**, then **line
    coding**.
- ★ **Scrambling**: replaces long zero runs *without* increasing the
  bandwidth (unlike block coding). Used with AMI.
  - **B8ZS**: 8 zeros → 000VB0VB (V = violation, B = bipolar pulse).
  - **HDB3**: 4 zeros → 000V or B00V, chosen so the number of non-zero
    pulses since the last substitution stays even.

### Analog-to-digital conversion
- ★ **PCM (Pulse Code Modulation)**: three steps.
  1. **Sampling** (**PAM**): ideal, natural or flat-top.
     **Nyquist theorem: f_s ≥ 2 × f_max**.
  2. **Quantization**: map each sample to one of L = 2ⁿ levels. This causes
     **quantization error**.
     **SNR_dB = 6.02 n_b + 1.76**.
  3. **Encoding**: each level becomes n_b bits.
     **Bit rate = f_s × n_b**.
- Example: voice, 4 kHz → 8000 samples/s × 8 bits = **64 kbps**.
- **Non-uniform quantization (companding)**: μ-law (USA) or A-law (Europe).
- **Delta modulation (DM)**: sends 1 bit per sample (up or down). Simpler,
  but suffers **slope overload** and **granular noise**. **Adaptive DM**
  varies the step size.

### Types of networks and architectures
- ★ By size:
  - **PAN** (personal, ~10 m, Bluetooth);
  - **LAN** (building/campus, one organization, high speed);
  - **MAN** (city, e.g. cable TV);
  - **WAN** (country/world; point-to-point or switched; the internet is a
    network of networks).
- **Switching:**
  - **Circuit switching**: a dedicated path is reserved first (telephone).
  - **Packet switching**: no reservation. Either **datagram** (each packet
    routed independently, as on the internet) or **virtual circuit** (a
    path is set up first and packets follow it, e.g. ATM, Frame Relay).
  - **Message switching**: store-and-forward of whole messages.
- ★ **Architectures:**
  - **Client–server**: a central server provides services; clients request
    them. Easy to manage, but a single point of failure.
  - **Peer-to-peer**: every node is both client and server. Scalable, no
    central point, harder to manage and secure.
- **Internet structure:** backbone ISPs → regional ISPs → local ISPs →
  customers. **IXPs** (internet exchange points) interconnect them.

### Topologies
- ★ The topologies:
  - **Mesh**: every device is linked to every other. **n(n−1)/2 links**,
    with n−1 ports per device. Robust and private, but expensive.
  - **Star**: everything links to a central hub/switch. Easy to install;
    the hub is a single point of failure. Most common in LANs.
  - **Bus**: one backbone cable with taps. Cheap, but a break kills it, and
    it's hard to troubleshoot.
  - **Ring**: each device links to two neighbors; a **token** travels around.
    A break can disable it (fixed with a dual ring).
  - **Tree** (hierarchical stars) and **hybrid**.
- Physical topology = how devices are wired; logical topology = how data
  flows.

### Transmission media
- ★ **Guided (wired):**
  - **Twisted pair**: UTP or STP. Twisting cancels noise and crosstalk.
    Categories Cat 5e/6/6a; **RJ-45** connector; 100 m limit.
  - **Coaxial**: a central conductor + shield. Cable TV, old Ethernet
    (10Base2/10Base5); BNC connector.
  - **Optical fiber**: light by **total internal reflection** (a core with a
    higher refractive index than the cladding). Modes: **multimode**
    (step-index or graded-index) and **single-mode** (long distance). Huge
    bandwidth, immune to EMI, light, secure; but costly and fragile.
- **Unguided (wireless):**
  - **Radio waves** (3 kHz–1 GHz, omnidirectional, AM/FM radio);
  - **Microwaves** (1–300 GHz, unidirectional, line of sight, satellite,
    cellular);
  - **Infrared** (300 GHz–400 THz, short range, can't pass walls; remotes).

### Networking devices
- ★ Device by layer:

  | Device | Layer | Does |
  |---|---|---|
  | **Repeater** | 1 | regenerates the signal (doesn't amplify noise) to extend distance |
  | **Hub** | 1 | multiport repeater; sends every frame to all ports |
  | **Bridge** | 2 | joins LAN segments, filters by MAC address, learning table |
  | **Switch** | 2 | multiport bridge; forwards only to the destination port; full duplex |
  | **Router** | 3 | forwards packets between networks by IP address, using a routing table |
  | **Gateway** | up to 7 | translates between different protocols / architectures |
  | **Modem** | 1 | modulates/demodulates digital ↔ analog |
  | **Access point** | 2 | connects wireless devices to a wired LAN |
  | **NIC** | 1–2 | network interface card; has the MAC address |

- **Collision domain vs broadcast domain:**
  - A hub is one collision domain.
  - A switch makes each port its own collision domain, but it's still one
    broadcast domain.
  - A router separates broadcast domains.
  - **VLANs** split a switch into several broadcast domains.
- **Layer-3 switch**: a switch that also routes between VLANs.

### OSI model
- ★ The **7 layers** and their jobs:
  1. **Physical**: bits, signals, cables, connectors, data rate,
     synchronization, topology.
  2. **Data link**: **framing**, physical (MAC) addressing, **flow control**,
     **error control**, **access control**. Hop-to-hop (node-to-node)
     delivery.
  3. **Network**: **logical (IP) addressing**, **routing**. Source-to-
     destination (host-to-host) delivery.
  4. **Transport**: **process-to-process** delivery, port addressing,
     segmentation/reassembly, connection control, end-to-end flow and error
     control.
  5. **Session**: dialog control (half/full duplex), **synchronization
     (checkpoints)**.
  6. **Presentation**: **translation** (character codes), **encryption**,
     **compression**.
  7. **Application**: user services (email, file transfer, web, directory).
- Mnemonics: bottom to top "**P**lease **D**o **N**ot **T**hrow **S**ausage
  **P**izza **A**way"; top to bottom "**A**ll **P**eople **S**eem **T**o
  **N**eed **D**ata **P**rocessing".
- ★ **Peer-to-peer process**: each layer talks logically to the same layer on
  the other machine, through headers.
- **Encapsulation**: going down, each layer adds a header (the data link
  layer also adds a trailer). Going up, they're stripped.
- **PDU names**: data → **segment** → **packet/datagram** → **frame** →
  **bits**.
- **Addresses by layer**:
  - data link: **physical/MAC** (48-bit);
  - network: **logical/IP**;
  - transport: **port** (16-bit);
  - application: **specific addresses** (email address, URL).

### TCP/IP reference model
- ★ The layers: **Application** (= OSI 5–7), **Transport** (TCP, UDP,
  SCTP), **Internet** (IP, ICMP, IGMP, ARP), **Network access / Link**
  (= OSI 1–2). Some books use 5 layers and split the last into data link +
  physical.
- ★ **OSI vs TCP/IP:**
  - OSI is a **reference model**, defined *before* its protocols, with 7
    layers and a clear service/interface/protocol split.
  - TCP/IP is a **practical** model, defined *after* its protocols, with 4
    (or 5) layers. It's what the internet uses.
  - OSI supports connectionless + connection-oriented at the network layer,
    and only connection-oriented at transport. TCP/IP is connectionless at
    the network layer and offers both at transport.

### Ethernet standards (IEEE 802.3)
- ★ Naming: speed + **BASE** (baseband) + medium/distance.

  | Generation | Standards |
  |---|---|
  | **Standard Ethernet (10 Mbps)** | **10Base5** (thick coax, 500 m, bus), **10Base2** (thin coax, 185 m), **10Base-T** (UTP, 100 m, star), **10Base-F** (fiber, 2 km). Manchester encoding, CSMA/CD |
  | **Fast Ethernet (100 Mbps)** | **100Base-TX** (Cat5 UTP), **100Base-FX** (fiber), 100Base-T4. 4B/5B coding. Autonegotiation |
  | **Gigabit (1 Gbps)** | **1000Base-SX/LX** (fiber), 1000Base-CX, **1000Base-T** (Cat5e). 8B/10B coding |
  | **10 Gigabit** | 10GBase-SR/LR/ER (fiber), 10GBase-T. Full duplex only, no CSMA/CD |

- **Wireless LAN** = IEEE **802.11** (a/b/g/n/ac/ax; uses CSMA/CA).
  **Bluetooth** = 802.15.
- The 802 family: **802.2** LLC, **802.3** Ethernet, **802.5** token ring,
  **802.11** Wi-Fi, **802.1Q** VLAN.

---

## Unit II: Data Link Layer

### Services
- ★ The services:
  - **Framing** (fixed-size or variable-size; byte stuffing or bit stuffing);
  - **addressing** (MAC);
  - **flow control**;
  - **error control**;
  - **media access control**.
- ★ **Two sublayers:** **LLC** (logical link control: flow and error
  control, 802.2) and **MAC** (media access control: who transmits on the
  shared medium).
- **Byte stuffing**: add an ESC byte before any flag or ESC byte found in the
  data.
- **Bit stuffing**: after five consecutive 1s, insert a 0 (so the flag
  01111110 never appears in the data).
- Services can be connectionless (unacknowledged or acknowledged) or
  connection-oriented.

### Errors
- ★ **Single-bit error**: one bit changes. Rare in serial transmission.
- ★ **Burst error**: two or more bits change. **Burst length** = from the
  first corrupted bit to the last. More likely, because noise lasts longer
  than one bit.
- **Redundancy**: extra bits are added to detect or correct errors.
- **Detection vs correction:** detection only knows there's an error;
  correction finds and fixes it (**FEC**, forward error correction).
  Correction needs more redundancy.
- **Retransmission** (ARQ) vs **FEC**.

### Block coding (error detection/correction)
- ★ The idea:
  - Split data into **datawords** (k bits) and map each to a **codeword**
    (n bits, n = k + r).
  - Only 2ᵏ of the 2ⁿ patterns are valid. Receiving an invalid codeword means
    an error.
- ★ **Hamming distance** d(x, y) = the number of positions where the bits
  differ = the number of 1s in (x ⊕ y).
- ★ **Minimum Hamming distance (d_min)** of a code:
  - detect up to s errors → **d_min = s + 1**;
  - correct up to t errors → **d_min = 2t + 1**.
- **Linear block code**: the XOR of any two codewords is also a codeword.
  d_min = the minimum weight of the non-zero codewords.
- **Simple parity check code**: n = k + 1, d_min = 2. Detects an odd number
  of errors.
- **Two-dimensional parity**: rows + columns. Detects more, and corrects a
  single error.

### ★ CRC (Cyclic Redundancy Check)
- A **cyclic code**: rotating a codeword gives another codeword.
- Sender:
  1. Pick a **generator (divisor)** of r + 1 bits (degree r).
  2. Append r zeros to the data.
  3. Divide by the generator with **modulo-2 division** (XOR, no carries).
  4. The r-bit **remainder** replaces the zeros. That remainder is the CRC.
- Receiver: divide the received codeword by the same generator. **Remainder
  0** (zero syndrome) = no error detected.
- Polynomial view: data = message polynomial, divisor = **generator
  polynomial** g(x).
- A good generator:
  - has **at least two terms** (detects all single-bit errors);
  - has the factor **(x + 1)** (detects all odd numbers of errors);
  - with degree r, detects **all burst errors of length ≤ r**.
- Standards: **CRC-32** (Ethernet), CRC-16, CRC-CCITT. Done in hardware with
  shift registers.

### ★ Hamming code
- A **single-bit error-correcting** code.
- Choose r so that **2ʳ ≥ m + r + 1** (m data bits). Example: m = 4 → r = 3
  → the **Hamming (7,4)** code, with d_min = 3.
- **Parity bits** go at positions **1, 2, 4, 8…** (powers of 2). Parity bit
  p covers every position whose binary index has that bit set:
  - P1 covers 1, 3, 5, 7, 9…;
  - P2 covers 2, 3, 6, 7, 10, 11…;
  - P4 covers 4–7, 12–15…;
  - P8 covers 8–15.
- The receiver recomputes the checks and gets the **syndrome**. Read in
  binary, the syndrome is the **position of the bad bit** (0 = no error);
  flip that bit to correct it.
- For bursts: **interleave** several Hamming codewords.

### ★ Checksum
- Used by the internet (IP header, TCP, UDP, ICMP). Steps:
  1. **Sender**: divide the data into 16-bit words and add them with
     **one's-complement arithmetic** (wrap any carry around and add it
     back).
  2. **Complement** the sum; that's the checksum. Send it with the data.
  3. **Receiver**: add all the words, checksum included. Complement the
     result: **0 = accept**, otherwise reject.
- Weaker than CRC (e.g. it doesn't detect reordered words), but easy in
  software. Improved versions: Fletcher and Adler checksums.

### Flow and error control: ARQ protocols
- ★ **Flow control** = the sender mustn't overwhelm the receiver.
  **Error control** = detect and retransmit lost or damaged frames, using
  **ARQ** (Automatic Repeat reQuest): ACK, timer, retransmission.
- ★ **Stop-and-Wait ARQ:**
  - Send one frame, start a timer, wait for its ACK. Resend on timeout.
  - Sequence numbers modulo 2 (0, 1). The ACK number = the *next* frame
    expected.
  - Sender window = receiver window = 1.
  - Efficiency = **1 / (1 + 2a)**, where **a = T_p / T_t** (propagation
    delay / transmission time).
  - Poor on long or fast links.
- **Pipelining**: send several frames before any ACK arrives. That's what
  sliding window does.
- ★ **Go-Back-N ARQ (GBN):**
  - **Sender window ≤ 2ᵐ − 1**; **receiver window = 1** (accepts only in
    order and discards out-of-order frames).
  - **Cumulative ACK**. One timer, for the oldest outstanding frame.
  - On timeout or error: **resend that frame and all frames after it**.
  - Efficiency = N / (1 + 2a).
- ★ **Selective Repeat ARQ (SR):**
  - **Sender window = receiver window ≤ 2ᵐ⁻¹**.
  - The receiver **buffers out-of-order frames**. A **NAK** asks for one
    specific frame.
  - **Only the lost frame is resent**. A timer per frame.
  - Efficient on noisy links; more complex receiver and more buffers.
- **Why is the window ≤ 2ᵐ⁻¹ in SR?** A larger window lets old
  (retransmitted) and new frames share the same sequence number when ACKs
  are lost, so the receiver would accept a duplicate as new data.
- **Why ≤ 2ᵐ − 1 in GBN?** With 2ᵐ, if all ACKs are lost the sender
  resends frame 0. The receiver, now expecting a *new* frame 0, accepts the
  duplicate.
- **Piggybacking**: carry an ACK inside an outgoing data frame, to save
  bandwidth (full-duplex links).
- **HDLC** (High-level Data Link Control):
  - Bit-oriented, with flag 01111110.
  - Frame types: **I** (information), **S** (supervisory: RR, RNR, REJ,
    SREJ), **U** (unnumbered).
  - Modes: NRM, ABM.
- **PPP** (Point-to-Point Protocol): byte-oriented. LCP sets up the link;
  NCPs (e.g. IPCP) configure the network layer; PAP/CHAP authenticate.

### Channel allocation and multiple access
- ★ **Channel allocation problem**: how to share one broadcast channel among
  many users.
  - **Static**: **FDM/TDM**, fixed shares. Wasteful when traffic is bursty.
  - **Dynamic**: allocate on demand. Assumptions: independent stations,
    single channel, collisions detectable, continuous or slotted time,
    carrier sense or not.
- ★ **Multiple access protocols, three classes:**
  1. **Random access** (contention, no station has priority): ALOHA, CSMA,
     CSMA/CD, CSMA/CA.
  2. **Controlled access**:
     - **Reservation**: reserve a slot before sending.
     - **Polling**: a primary station asks each secondary in turn
       (select/poll).
     - **Token passing**: only the holder of the token sends (token ring).
  3. **Channelization**:
     - **FDMA**: frequency bands;
     - **TDMA**: time slots;
     - **CDMA**: everyone sends at once with different orthogonal codes
       (Walsh codes).

### ★ ALOHA
- Origin: University of Hawaii, 1970, radio.
- **Pure ALOHA:**
  - Send whenever you have a frame. If no ACK arrives (collision), wait a
    random **backoff** time (K × T_p or K × T_fr, K from 0..2ⁿ−1) and resend.
  - **Vulnerable time = 2 × T_fr**.
  - **Throughput S = G·e⁻²ᴳ**; **maximum 18.4% at G = 0.5**.
- **Slotted ALOHA:**
  - Time is divided into slots of T_fr. Frames may start only at slot
    boundaries.
  - **Vulnerable time = T_fr**.
  - **S = G·e⁻ᴳ**; **maximum 36.8% at G = 1**.
- G = the average number of frames generated per frame time.

### ★ CSMA (Carrier Sense Multiple Access)
- "**Listen before talk**". This reduces collisions but can't remove them,
  because of **propagation delay**. Vulnerable time = T_p.
- **Persistence methods**:
  - **1-persistent**: if the line is idle, send immediately. Highest
    collision chance (Ethernet).
  - **Non-persistent**: if busy, wait a random time, then sense again. Fewer
    collisions, more idle time.
  - **p-persistent** (slotted channels): if idle, send with probability p,
    or defer to the next slot with probability 1 − p.

### ★ CSMA/CD (Collision Detection): wired Ethernet
- The procedure:
  1. Sense the line.
  2. Send while **monitoring** it.
  3. If a collision is detected, stop at once and send a **jam signal** (so
     everyone knows).
  4. **Binary exponential backoff**: after the n-th collision, wait K × slot
     time, with K random in 0..2ⁿ − 1 (n capped at 10). Give up after 15
     attempts.
- ★ **Minimum frame size**: the sender must still be transmitting when news
  of a collision returns. So **T_fr ≥ 2 × T_p**, i.e. **L_min = 2 × T_p ×
  bandwidth**.
  - 10 Mbps Ethernet: slot time 51.2 µs = 512 bits = **64 bytes**.
- Not used in full-duplex switched Ethernet, which has no collisions.

### ★ CSMA/CA (Collision Avoidance): Wi-Fi (802.11)
- **Why not CD?**
  - A wireless station can't listen while transmitting (its own signal is
    far stronger than the colliding one).
  - The **hidden terminal problem**: two stations can't hear each other but
    both reach the access point.
- **Avoidance techniques:**
  - **IFS** (inter-frame space): wait DIFS after the channel goes idle; SIFS
    before an ACK or CTS (SIFS < DIFS, so they get priority).
  - **Contention window**: a random number of slots, doubled after failures.
    The timer pauses while the channel is busy.
  - **ACK** for every frame (no ACK = collision assumed).
  - **RTS/CTS** handshake: reserves the channel and solves hidden terminals.
  - **NAV** (network allocation vector): the reserved duration, which
    others respect.
- **Exposed terminal problem**: a station wrongly defers because it hears a
  transmission that wouldn't actually interfere.

### ★ Ethernet frame format (802.3)
| Preamble | SFD | Dest addr | Src addr | Length/Type | Data + pad | CRC |
|---|---|---|---|---|---|---|
| 7 B | 1 B | 6 B | 6 B | 2 B | 46–1500 B | 4 B |

- **Preamble** = alternating 1s/0s, for synchronization. **SFD** = 10101011.
  Both are added by the physical layer.
- **Minimum frame 64 B** (needed for CSMA/CD), **maximum 1518 B** (both
  without preamble/SFD). MTU = 1500.
- **MAC address**: 48 bits (6 bytes), hexadecimal, e.g. 4A:30:10:21:10:1A.
  The first 3 bytes are the **OUI** (vendor).
  - **Unicast**: the first byte's LSB is 0.
  - **Multicast**: that LSB is 1.
  - **Broadcast**: all 1s, FF:FF:FF:FF:FF:FF.
- Bytes are sent left to right, and bits within a byte LSB first.

---

## Unit III: Network Layer

### Services
- ★ The services:
  - **Packetizing**;
  - **routing** (finding the best path);
  - **forwarding** (sending a packet to the right output interface, using
    the forwarding table);
  - **logical addressing**;
  - **fragmentation**;
  - error control (header checksum only);
  - **congestion control**;
  - quality of service;
  - security.
- **Routing vs forwarding**: routing builds the table (control plane);
  forwarding uses it for each packet (data plane).
- The internet's network layer is **connectionless datagram**, best-effort
  delivery (unreliable).

### ★ Internet Protocol
- **IPv4**: 32-bit addresses; datagram header 20–60 B. Protocol field values:
  1 = ICMP, 2 = IGMP, 6 = TCP, 17 = UDP, 89 = OSPF.
- ★ **Fragmentation:**
  - A datagram larger than the next link's **MTU** is split. Each fragment
    has its own header with the same **Identification**, the **MF** flag
    (more fragments) and a **fragment offset** (in 8-byte units).
  - The **DF** (don't fragment) flag forbids it; if set, the router drops
    the packet and sends ICMP "fragmentation needed".
  - Reassembly happens **only at the destination**.
- **TTL**: decremented at each router; at 0 the packet is dropped
  (prevents loops).
- **Header checksum**: covers only the header; recomputed at every router.

### ★ IPv6
- **Why?** IPv4 address exhaustion, plus a better header format, built-in
  security, QoS (flow label) and autoconfiguration.
- **128-bit** addresses in hexadecimal colon notation:
  2001:0DB8:0000:0000:0000:FF00:0042:8329 → **2001:DB8::FF00:42:8329**.
  Drop leading zeros; **::** replaces one run of zero groups, **only once**.
- **Address types**:
  - **unicast** (global, link-local FE80::/10, unique-local);
  - **multicast** (FF00::/8);
  - **anycast** (delivered to the nearest of a group).
  - **No broadcast**.
- **Header**: fixed **40 B**, no checksum, no fragmentation at routers (only
  the source fragments), **extension headers** chained by "Next header".
- **Autoconfiguration**: **SLAAC** or DHCPv6.
- ★ **Transition IPv4 → IPv6**:
  - **dual stack** (run both);
  - **tunneling** (IPv6 packets inside IPv4);
  - **header translation** (NAT64).
- Loopback is **::1**.

### ★ Classful addressing
| Class | Leading bits | First octet | Default mask | Networks | Hosts per network |
|---|---|---|---|---|---|
| **A** | 0 | 0–127 | 255.0.0.0 (/8) | 2⁷ = 128 (126 usable) | 2²⁴ − 2 = 16,777,214 |
| **B** | 10 | 128–191 | 255.255.0.0 (/16) | 2¹⁴ = 16,384 | 2¹⁶ − 2 = 65,534 |
| **C** | 110 | 192–223 | 255.255.255.0 (/24) | 2²¹ = 2,097,152 | 2⁸ − 2 = 254 |
| **D** | 1110 | 224–239 | none | **multicast** | |
| **E** | 1111 | 240–255 | none | reserved | |

- **Netid / hostid** split.
  - **Network address**: hostid all 0s.
  - **Directed broadcast**: hostid all 1s.
  - **Limited broadcast**: 255.255.255.255.
  - **Loopback**: 127.0.0.0/8 (127.0.0.1).
  - **0.0.0.0**: "this host".
- ★ **Private ranges** (RFC 1918):
  - **10.0.0.0/8** (class A);
  - **172.16.0.0 – 172.31.255.255** (/12, class B);
  - **192.168.0.0/16** (class C).
- **APIPA** (link-local): 169.254.0.0/16.
- ★ **Why classful failed:** **address depletion** and **waste**. Class A and
  B blocks were far too big for most organizations, and Class C far too
  small (only 254 hosts).

### ★ Classless addressing, CIDR, subnetting
- **CIDR** (Classless Inter-Domain Routing): **variable-length blocks**,
  written in slash notation **a.b.c.d/n**, where n = prefix length (the
  network bits).
- For a block /n:
  - number of addresses **N = 2^(32−n)**;
  - **first address** = IP AND mask (the network address);
  - **last address** = IP OR (NOT mask) (the broadcast address);
  - usable hosts = N − 2.
- **Rules for a block**:
  - the number of addresses is a power of 2;
  - the first address is divisible by the block size;
  - the addresses are contiguous.
- ★ **Subnetting**: borrow host bits to split a network into smaller
  **subnets**. s borrowed bits → 2ˢ subnets; h remaining host bits → 2ʰ − 2
  hosts each. Benefits: less broadcast traffic, security, organization.
- **VLSM** (variable-length subnet masks): subnets of different sizes from
  one block. Allocate the largest first.
- ★ **Supernetting / route aggregation (summarization)**: combine several
  contiguous small blocks into one bigger prefix, so routing tables shrink.
  ISPs do this.
- **Longest prefix match**: when several routing entries match, the most
  specific (longest mask) wins.

### ★ NAT (Network Address Translation)
- **Why?** IPv4 shortage. A whole private network shares **one (or a few)
  public IPs**.
- **How?** The router rewrites the **source** address of outgoing packets to
  its public address and records the mapping in a **translation table**.
  Replies are translated back to the private address.
- **PAT/NAPT** (port address translation): the table also uses **port
  numbers**, so many hosts share one public IP (home routers).
- Types:
  - **static NAT**: one-to-one, fixed;
  - **dynamic NAT**: from a pool of public addresses;
  - **PAT / overloading**.
- **Drawbacks**:
  - breaks the end-to-end principle;
  - **outside hosts can't start connections** to inside hosts (needs port
    forwarding);
  - problems for protocols that put IP addresses inside the payload (FTP
    needs an **ALG**);
  - extra processing.

### ★ ARP and RARP
- **ARP** (Address Resolution Protocol): finds the **MAC address for a known
  IP address**, on the local network.
  1. Check the **ARP cache**.
  2. If it's not there, **broadcast** an ARP request ("who has IP x? tell
     y").
  3. The owner replies by **unicast** with its MAC.
  4. Cache the result (with a timeout).
- **Proxy ARP**: a router answers for hosts on another network.
- **Gratuitous ARP**: announcing your own IP, to detect conflicts or update
  caches.
- **RARP** (Reverse ARP): finds the **IP address for a known MAC**. Used by
  diskless workstations at boot. Obsolete, replaced by **BOOTP** and then
  **DHCP**. Why: RARP requests can't cross routers, and RARP gives only an
  IP (no mask or gateway).

### ★ ICMP (Internet Control Message Protocol)
- **Why?** IP has no error reporting and no diagnostic queries. ICMP is
  carried inside IP (protocol 1). It reports errors but **does not correct
  them**.
- **Error-reporting messages**:
  - **destination unreachable** (type 3: network, host, protocol, **port**,
    fragmentation needed);
  - **source quench** (4, congestion; deprecated);
  - **time exceeded** (11: TTL = 0, or fragments not reassembled in time);
  - **parameter problem** (12);
  - **redirect** (5: a better next-hop router exists).
- **No ICMP error is sent**:
  - about an ICMP error message;
  - for a fragment other than the first;
  - for multicast or broadcast packets;
  - for special addresses (127.x, 0.0.0.0).
- **Query messages**:
  - **echo request (8) / reply (0)**, used by `ping`;
  - **timestamp request / reply (13/14)**;
  - router solicitation / advertisement.
- **Tools**:
  - **ping**: echo; checks reachability and RTT.
  - **traceroute / tracert**: sends packets with TTL = 1, 2, 3… Each router
    answers "time exceeded", which reveals the path.
- **IGMP** (Internet Group Management Protocol): hosts tell local routers
  which **multicast groups** they've joined (membership query, report,
  leave).

### ★ Routing algorithms
- **Static vs dynamic routing**: static routes are entered by hand (small,
  stable networks); dynamic routes are learned by routing protocols, which
  adapt to failures.
- **Goal**: find the **least-cost path**. Cost can be hops, delay or
  bandwidth.
- **Distance-Vector (DV) routing:**
  - Each router knows only its **neighbors**. It keeps a **distance vector**
    (cost to every destination + next hop) and **periodically shares its
    whole vector with its neighbors**.
  - Each router updates with the **Bellman–Ford equation**:
    **Dₓ(y) = minᵥ { c(x,v) + Dᵥ(y) }**.
  - "Routing by rumor". Simple, but **slow convergence**.
  - ★ **Count-to-infinity problem**: after a link fails, two routers keep
    increasing their costs by learning stale routes from each other.
  - Fixes:
    - **define infinity** (e.g. 16);
    - **split horizon**: don't advertise a route back to the neighbor you
      learned it from;
    - **poison reverse**: advertise it back with cost infinity;
    - hold-down timers;
    - triggered updates.
- **Link-State (LS) routing:**
  - Each router learns the **complete topology**.
    1. Discover neighbors (hello packets).
    2. Measure link costs.
    3. Build an **LSP/LSA** (its links and costs).
    4. **Flood** it to *all* routers (reliable flooding, with sequence
       numbers and ages).
    5. Every router builds the same **link-state database**, then runs
       **Dijkstra's shortest-path algorithm** to build a **shortest-path
       tree** with itself as the root.
  - Fast convergence, no count-to-infinity. More memory, CPU and flooding
    overhead.
- **Path-vector routing**: like DV, but advertises the **whole path** (the
  list of ASes). Loops are prevented by rejecting paths that already contain
  your own AS. Policy-based. Used by BGP.

### ★ Routing in the internet: RIP, OSPF, BGP
- **Autonomous System (AS)**: a network under one administration (an ISP, a
  large company), identified by an **ASN**.
  - **Intra-domain** (inside an AS, **IGP**): RIP, OSPF.
  - **Inter-domain** (between ASes, **EGP**): BGP.
- **RIP** (Routing Information Protocol):
  - Distance vector. Metric = **hop count**; **max 15**, **16 = infinity**,
    so it's only for small networks.
  - Sends its full table every **30 s** over **UDP port 520**. Timers:
    periodic 30 s, expiration 180 s, garbage collection 120 s.
  - **RIPv1**: classful (no mask), broadcast.
  - **RIPv2**: classless (carries the mask), multicast 224.0.0.9,
    authentication.
- **OSPF** (Open Shortest Path First):
  - Link state; **Dijkstra**. Metric = **cost** (e.g. inversely related to
    bandwidth). Runs directly over IP (protocol **89**).
  - Divides the AS into **areas**. **Area 0 = backbone**; the others connect
    to it. **ABRs** (area border routers) summarize between areas.
  - **Hello** packets find neighbors and elect a **DR/BDR** (designated
    router / backup) on broadcast networks.
  - Five packet types: Hello, DBD, LSR, LSU, LSAck.
  - Fast convergence, classless (VLSM), authentication, equal-cost
    multipath.
- **BGP** (Border Gateway Protocol):
  - **Path vector**; the routing protocol **of the internet** (BGP-4).
  - Runs over **TCP port 179** (reliable sessions between **BGP
    speakers/peers**). **eBGP** = between ASes; **iBGP** = inside an AS.
  - Messages: **OPEN, UPDATE, KEEPALIVE, NOTIFICATION**.
  - Picks routes by **policy** and path attributes (AS_PATH, NEXT_HOP,
    LOCAL_PREF, MED, ORIGIN), not just shortest path.
  - Loop prevention: reject routes whose AS_PATH contains its own AS.

---

## Unit IV: Transport Layer

### Services
- ★ The services:
  - **Process-to-process (end-to-end) delivery**, using **port numbers**;
  - **multiplexing/demultiplexing**;
  - segmentation and reassembly;
  - **connection control** (connectionless or connection-oriented);
  - **flow control**, **error control**, **congestion control**;
  - (QoS).
- **Host-to-host vs process-to-process**: IP delivers to the computer; the
  transport layer delivers to the right *program* on that computer.
- ★ **Port numbers** (16-bit, 0–65535):
  - **Well-known 0–1023** (assigned by IANA: HTTP 80…);
  - **registered 1024–49151**;
  - **dynamic / ephemeral 49152–65535** (temporary client ports).

### Multiplexing, demultiplexing, sockets
- ★ **Multiplexing** (at the sender): collect data from many processes and
  add transport headers with port numbers, through one network layer.
- ★ **Demultiplexing** (at the receiver): deliver each segment to the
  correct process/socket using the header fields.
  - **UDP** (connectionless): by **destination IP + destination port**.
  - **TCP** (connection-oriented): by the **4-tuple** (source IP, source
    port, destination IP, destination port). That's why a web server has one
    socket per client on port 80.
- ★ **Socket**: the interface between a process and the transport layer;
  one endpoint of a connection.
  - **Socket address = IP address + port number**.
  - A connection is identified by a pair of socket addresses.
- **Socket API** (Berkeley sockets):

  | Side | Calls |
  |---|---|
  | TCP server | `socket()` → `bind()` → `listen()` → `accept()` → `recv()/send()` → `close()` |
  | TCP client | `socket()` → `connect()` → `send()/recv()` → `close()` |
  | UDP | `socket()` → `bind()` → `sendto()/recvfrom()` |

  Socket types: **SOCK_STREAM** (TCP), **SOCK_DGRAM** (UDP), SOCK_RAW.

### ★ UDP (User Datagram Protocol)
- Connectionless and unreliable: **no handshake, no ACKs, no ordering, no
  flow or congestion control**. Message-oriented (keeps message
  boundaries).
- **8-byte header**: source port, destination port, total length, checksum.
  The checksum is optional in IPv4 and includes a **pseudo-header**.
- **Why use it?** Speed, low overhead, no connection delay. Good for small
  request/response, real time (loss is acceptable, delay isn't), and
  multicast/broadcast.
- **Applications**: **DNS, DHCP, SNMP, TFTP, RIP, RTP/VoIP, video
  streaming, online games**.

### ★ RTP (Real-time Transport Protocol)
- Carries **real-time audio/video**; runs over **UDP** (an even port).
- It doesn't guarantee delivery or timing itself. It gives the application
  what it needs:
  - **sequence number**: detect loss and reorder;
  - **timestamp**: playback timing and jitter control (with a jitter
    buffer);
  - **payload type**: which codec;
  - **SSRC**: which source.
- **RTCP** (RTP Control Protocol), on the next odd port, sends periodic
  reports (loss, jitter, delay) for **QoS feedback** and synchronization.
  Packet types: SR, RR, SDES, BYE, APP.
- Used in VoIP, video conferencing, WebRTC, with SIP for call setup.

### ★ TCP (Transmission Control Protocol): services and features
- **Services**:
  - process-to-process communication;
  - a **stream delivery service** (a byte stream, not messages; uses
    send/receive buffers);
  - **full-duplex**;
  - **connection-oriented**;
  - **reliable**;
  - multiplexing.
- **Features**:
  - **byte numbering**: every byte has a number, and the sequence number =
    the number of the first byte in the segment;
  - **cumulative ACK number** = the next byte expected;
  - flow control (sliding window), error control, congestion control;
  - initial sequence number (ISN) chosen randomly.
- **Segment header**: 20–60 bytes. Ports, sequence number, ACK number,
  header length, **flags** (URG, ACK, PSH, RST, SYN, FIN), **window size**,
  checksum, urgent pointer, options (MSS, window scale, SACK, timestamps).

### ★ TCP connection management
- **Three-way handshake** (connection establishment):
  1. Client → **SYN**, seq = x. Consumes one sequence number; no data.
  2. Server → **SYN + ACK**, seq = y, ack = x + 1.
  3. Client → **ACK**, ack = y + 1. This one may carry data.
- **Why three and not two?** Both sides must agree on *both* initial
  sequence numbers, and this prevents old duplicate SYNs from opening false
  connections.
- **SYN flooding attack**: many fake SYNs fill the server's half-open
  connection table. Defense: **SYN cookies**.
- **Data transfer**: pushing (PSH), urgent data (URG).
- **Connection termination:**
  - **Four-way**: FIN → ACK, FIN → ACK. Or **three-way**: FIN, FIN+ACK, ACK.
  - **Half-close**: one side stops sending but keeps receiving.
  - **TIME-WAIT = 2 × MSL** (maximum segment lifetime): makes sure the last
    ACK arrived and old duplicates have died out.
- **RST**: abort or deny a connection.
- **TCP states**:
  - CLOSED, LISTEN, SYN-SENT, SYN-RCVD, **ESTABLISHED**;
  - FIN-WAIT-1, FIN-WAIT-2, CLOSE-WAIT, LAST-ACK, CLOSING, **TIME-WAIT**.

### ★ Flow control and buffering
- **Sliding window**:
  - The receiver advertises **rwnd** (receive window = free buffer space) in
    every segment.
  - The sender may have at most rwnd bytes unacknowledged.
  - The window **opens** (new space advertised), **closes** (data
    acknowledged) and **shrinks** (discouraged).
- Both sides keep **send and receive buffers**, because the application
  writes and reads at its own pace.
- **Zero window**: the sender stops and the **persistence timer** sends
  **window probes**, so a lost window update can't cause deadlock.
- **TCP error control**: checksum, ACKs and retransmission. A segment is
  retransmitted on **RTO expiry** (retransmission timeout, computed from
  the RTT estimate) or after **3 duplicate ACKs** (**fast retransmit**).
- **TCP timers**: **retransmission**, **persistence**, **keepalive**,
  **TIME-WAIT**.

### ★ Silly window syndrome
- **The problem**: tiny segments (e.g. 1 byte of data with 40 bytes of
  headers) waste bandwidth.
- **Caused by the sender** (the application writes 1 byte at a time) → fix
  with **Nagle's algorithm**:
  - send the first piece immediately;
  - then buffer until an ACK arrives *or* there's a full **MSS** to send.
- **Caused by the receiver** (the application reads 1 byte at a time and
  advertises tiny windows) → two fixes:
  - **Clark's solution**: advertise a window of 0 until there's room for a
    full MSS or half the buffer is free;
  - **delayed acknowledgment**: hold ACKs briefly (≤ 500 ms) so the window
    can grow.

### ★ Congestion control
- **Congestion**: the load is more than the network can handle, so queues
  overflow, packets are lost, delay rises and throughput collapses.
- **Flow control vs congestion control**: flow control protects the
  **receiver**; congestion control protects the **network**.
- General approaches:
  - **open-loop** (prevention): retransmission, window, ACK and discard
    policies, admission control;
  - **closed-loop** (removal): **backpressure**, **choke packets**,
    implicit signaling (losses, delays), explicit signaling (ECN).
- ★ **TCP congestion control:**
  - Sender window = **min(rwnd, cwnd)**, where **cwnd** = the congestion
    window.
  - **Slow start**: cwnd starts at **1 MSS** and grows by 1 MSS per ACK, so
    it **doubles every RTT** (exponential). This continues until it reaches
    **ssthresh** (slow-start threshold).
  - **Congestion avoidance**: after ssthresh, cwnd grows by **1 MSS per RTT**
    (linear, additive increase).
  - **Congestion detection**:
    - **Timeout** (severe): ssthresh = cwnd / 2, **cwnd = 1 MSS**, restart
      slow start. This is **TCP Tahoe**'s behavior on every loss.
    - **3 duplicate ACKs** (mild): **fast retransmit** the lost segment,
      then **fast recovery**: ssthresh = cwnd / 2, **cwnd = ssthresh**
      (+3), and continue with congestion avoidance. This is **TCP Reno**.
  - Together this is **AIMD** (additive increase, multiplicative decrease),
    which gives the "**saw-tooth**" graph of cwnd over time.
- **Leaky bucket vs token bucket** (traffic shaping):
  - ★ **Leaky bucket**: a queue with a hole. Packets enter at any rate but
    **leave at a constant rate**; when the bucket is full, packets are
    **discarded**. It **smooths bursts completely** (rigid output).
    Implemented as a FIFO queue releasing a fixed number of bytes per tick.
  - ★ **Token bucket**: tokens are added at rate **r**, up to capacity
    **b**. Sending a packet (or byte) uses a token; no tokens = wait.
    - It **allows bursts** (up to b), saves up credit while idle, and
      limits the long-term average rate to r.
    - Tokens are discarded when the bucket is full; packets are not.
    - Max burst duration **S = b / (M − r)**, where M = the maximum output
      rate.
  - They're often combined: a token bucket followed by a leaky bucket.

### ★ Quality of Service (QoS)
- **Flow characteristics**: **reliability, delay, jitter, bandwidth**.
- **Techniques to improve QoS**:
  - **Scheduling**: FIFO queuing; **priority queuing** (a risk of
    starvation); **weighted fair queuing** (classes share by weight).
  - **Traffic shaping**: leaky bucket, token bucket.
  - **Admission control**: accept a flow only if the network can serve it.
  - **Resource reservation**.
- **Models**:
  - **IntServ** (Integrated Services): **per-flow** reservation using
    **RSVP**, with guaranteed or controlled-load service. Doesn't scale.
  - **DiffServ** (Differentiated Services): packets are marked with a
    **DSCP** class at the edge, and core routers apply **per-hop behaviors**
    (expedited forwarding, assured forwarding). Scalable.

---

## Unit V: Application Layer

### ★ DHCP (Dynamic Host Configuration Protocol)
- **Purpose**: automatically assigns the **IP address, subnet mask, default
  gateway and DNS server**, for a **lease** time. Removes manual
  configuration and reuses addresses. Successor of **BOOTP**.
- Client–server over **UDP: server port 67, client port 68**.
- **DORA**:
  1. **DHCPDISCOVER**: the client **broadcasts**, since it has no IP yet
     (source 0.0.0.0, destination 255.255.255.255).
  2. **DHCPOFFER**: the server offers an IP.
  3. **DHCPREQUEST**: the client requests the chosen offer (broadcast, so
     other servers know theirs was declined).
  4. **DHCPACK**: the server confirms. **DHCPNAK** = refuse.
- **Lease renewal**: at **T1 = 50%** of the lease, renew with the same
  server; at **T2 = 87.5%**, rebind with any server; at expiry, release the
  address. Others: DHCPRELEASE, DHCPDECLINE, DHCPINFORM.
- **Allocation**: static (manual), automatic (permanent), **dynamic**
  (leased).
- **DHCP relay agent**: forwards DHCP broadcasts to a server on another
  subnet, because routers don't forward broadcasts.
- **Client states**: INIT, SELECTING, REQUESTING, BOUND, RENEWING,
  REBINDING.

### ★ HTTP (HyperText Transfer Protocol)
- The protocol of the **World Wide Web**. Client (browser) / server, over
  **TCP port 80**; **HTTPS** = HTTP over **TLS**, port **443**.
- ★ **Stateless**: the server keeps no memory of previous requests.
  **Cookies** add state (sessions, carts, logins). A cookie is set with
  **Set-Cookie** and sent back with **Cookie**.
- ★ **Non-persistent vs persistent connections:**
  - **Non-persistent** (HTTP/1.0): a new TCP connection **per object**.
    Each object costs **2 RTT** + transmission time.
  - **Persistent** (HTTP/1.1 default, keep-alive): one connection for many
    objects. With **pipelining**, several requests are sent without
    waiting.
- **Request message** = request line (**method, URL, version**) + header
  lines + a blank line + body.
- **Methods**: **GET** (retrieve), **POST** (send data), **HEAD** (headers
  only), **PUT** (upload/replace), **DELETE**, PATCH, OPTIONS, TRACE,
  CONNECT.
- **Response message** = status line (**version, status code, phrase**) +
  headers + a blank line + body.
- ★ **Status codes**:
  - **1xx** informational;
  - **2xx success** (200 OK, 201 Created, 204 No Content);
  - **3xx redirection** (301 Moved Permanently, 302 Found, 304 Not
    Modified);
  - **4xx client error** (400 Bad Request, 401 Unauthorized, 403 Forbidden,
    **404 Not Found**);
  - **5xx server error** (500 Internal Server Error, 502 Bad Gateway, 503
    Service Unavailable).
- **Web caching / proxy server**: answers from a cache if it can.
  **Conditional GET** (If-Modified-Since → 304) avoids resending unchanged
  objects.
- **URL** = protocol://host:port/path.
- **HTTP/2**: binary, multiplexed streams, header compression, server push.
  **HTTP/3**: over **QUIC** (UDP).

### ★ FTP (File Transfer Protocol)
- Copies files between hosts over TCP, with **two separate connections**:
  - **control connection** on **port 21**: commands and replies; stays open
    for the whole session;
  - **data connection** on **port 20** (active mode): opened and closed
    **for each file** transfer.
- This is called "**out-of-band**" control.
- **Why two connections?** Commands and replies are short and interactive;
  file data is large and bulky. Keeping them separate keeps control
  responsive.
- **Active vs passive mode**:
  - Active: the client sends **PORT**, and the server connects *to the
    client* from port 20.
  - Passive (**PASV**): the server opens a port and the client connects to
    it. Passive works through **firewalls/NAT**.
- **Commands**: USER, PASS, LIST, RETR (get), STOR (put), DELE, MKD, CWD,
  QUIT. **Reply codes**: 3 digits (220, 230, 331, 150, 226, 425, 530).
- **File types**: ASCII, EBCDIC, image (binary). **Transmission modes**:
  stream, block, compressed.
- **Anonymous FTP**: user "anonymous".
- **TFTP**: trivial FTP over UDP 69. No authentication or listing.
- **Security**: FTP is plaintext → **SFTP** (over SSH) or **FTPS** (over
  TLS).

### ★ TELNET
- **TErminaL NETwork**: **remote login**, giving the user a terminal on a
  remote machine. TCP **port 23**. Client/server.
- **Local vs remote login**: a local terminal talks to the OS directly;
  remote keystrokes go through the TELNET client → TCP → the TELNET server
  → a pseudo-terminal driver.
- **NVT** (Network Virtual Terminal): a universal character set, so
  different computers and terminals interoperate. Both ends translate to
  and from NVT.
- **Control characters** are sent in-band after **IAC** (interpret as
  command, 255).
- **Option negotiation** uses **WILL, WON'T, DO, DON'T** (e.g. echo,
  terminal type).
- **Modes**: default (half-duplex, line at a time), character, line.
- **Drawback**: **everything, including passwords, is sent in plaintext**.
  Replaced by **SSH** (port 22, encrypted).

### ★ Email: SMTP, POP3, IMAP, MIME
- **Architecture**:
  - **UA** (user agent: Outlook, Thunderbird);
  - **MTA** (message transfer agent: the mail server, which sends);
  - **MAA** (message access agent: lets the user fetch mail).
- **SMTP** (Simple Mail Transfer Protocol):
  - A **push** protocol: UA → sender's server → receiver's server. TCP
    **port 25** (587 for submission).
  - Three phases: connection establishment, mail transfer, connection
    termination.
  - Commands: **HELO/EHLO, MAIL FROM, RCPT TO, DATA, QUIT**, RSET, VRFY.
    Replies: 220, 250, 354, 221.
  - Only **7-bit ASCII**, hence MIME.
- **Why not SMTP to read mail?** SMTP is push-only, and the user's PC isn't
  always on. So the server stores the mail, and the user **pulls** it with
  POP3 or IMAP.
- **POP3** (Post Office Protocol v3):
  - TCP **port 110**.
  - **Download** mail to the client, then usually **delete it from the
    server** (delete mode; there's also a keep mode).
  - Simple, works offline, but bad for multiple devices. No folders on the
    server.
- **IMAP4** (Internet Message Access Protocol):
  - TCP **port 143**.
  - **Mail stays on the server**: folders, read/unread flags, search,
    download parts of a message (headers first).
  - Synced across devices; more server storage.
- ★ **MIME** (Multipurpose Internet Mail Extensions):
  - A supplement that lets email carry **non-ASCII text, other languages,
    images, audio, video and attachments**. It converts them to 7-bit ASCII
    for SMTP and back.
  - Five headers:
    - **MIME-Version**;
    - **Content-Type** (text/plain, text/html, image/jpeg, video/mp4,
      application/pdf, **multipart/mixed**, message/rfc822);
    - **Content-Transfer-Encoding** (7bit, 8bit, binary, **base64**,
      **quoted-printable**);
    - **Content-ID**;
    - **Content-Description**.
- **Base64**: every 3 bytes become 4 printable characters (+33% size).
- **Web-based mail** (Gmail) uses HTTP between the browser and the server,
  and SMTP between servers.

### ★ DNS (Domain Name System)
- **Purpose**: maps **host names to IP addresses** (and the reverse), so
  people use names, not numbers.
- A **distributed, hierarchical database**. Client/server.
- **UDP port 53** for queries (TCP 53 for **zone transfers** or answers over
  512 bytes).
- **Name space**: an inverted tree; labels of up to 63 characters, a full
  name of up to 255.
  - **Domain** = a subtree.
  - **FQDN** (fully qualified domain name) ends with a dot (www.example.com.).
    A **PQDN** is partial.
- **Hierarchy of servers**:
  - **Root servers** (13 logical root servers, many copies);
  - **TLD servers**:
    - **generic** (.com, .org, .edu);
    - **country** (.in, .uk);
    - **inverse** (in-addr.arpa, for reverse lookup).
  - **Authoritative servers** (primary/master, secondary/slave);
  - **local / recursive resolvers**.
- **Zone** = the part of the tree a server is responsible for.
- ★ **Recursive vs iterative resolution:**
  - **Recursive**: the asked server does the whole lookup and returns the
    final answer (client → local resolver).
  - **Iterative**: each server returns the best **referral** ("ask this
    server next"), and the asker follows it (resolver → root → TLD →
    authoritative).
- **Caching** with a **TTL** speeds up repeat lookups.
- ★ **Resource records**:
  - **A** (name → IPv4), **AAAA** (→ IPv6);
  - **CNAME** (alias → canonical name);
  - **MX** (mail exchanger for a domain, with preference);
  - **NS** (name server for a zone);
  - **PTR** (IP → name, reverse);
  - **SOA** (start of authority: zone information);
  - **TXT**.
- **DNS message**: a 12-byte header (ID, flags, counts) + question, answer,
  authority and additional sections.
- **DDNS** (dynamic DNS): updates records automatically when addresses
  change (e.g. with DHCP).

### ★ SNMP (Simple Network Management Protocol)
- **Purpose**: **monitor and manage** network devices (routers, switches,
  servers, printers): read statistics, change settings, receive alerts.
- **Components**:
  - **Manager** (NMS, network management station);
  - **Agent** (runs on each managed device);
  - **MIB** (Management Information Base): the collection of managed
    objects. Each object has an **OID** (object identifier) in a tree,
    e.g. 1.3.6.1.2.1… (sysUpTime, ifInOctets).
  - **SMI** (Structure of Management Information): the rules for naming
    objects, data types and encoding (**ASN.1, BER**).
- **Operations (PDUs)**:
  - **GetRequest**, **GetNextRequest** (walk tables);
  - **GetBulkRequest** (v2);
  - **SetRequest** (change a value);
  - **Response**;
  - **Trap** (agent → manager, unsolicited event alert, e.g. link down);
  - **InformRequest** (an acknowledged notification).
- **Ports**: **UDP 161** (agent receives requests), **UDP 162** (manager
  receives traps).
- **Versions**:
  - **v1** (community string as a plaintext password);
  - **v2c** (GetBulk, better errors);
  - **v3** (**authentication + encryption**, user-based security).

---

## 6. Common "difference between" questions

| A | B |
|---|---|
| **Hub**: layer 1, broadcasts to all ports, one collision domain, half duplex | **Switch**: layer 2, forwards by MAC to one port, a collision domain per port, full duplex |
| **Switch**: layer 2, MAC, inside one network (one broadcast domain) | **Router**: layer 3, IP, connects different networks, separates broadcast domains |
| **Bit rate**: bits per second | **Baud rate**: signal elements per second (bit rate = baud × bits per element) |
| **Manchester**: transition in the middle; its direction gives the bit | **Differential Manchester**: always a middle transition; the bit is given by a transition (or none) at the start |
| **Block coding**: adds bits (more bandwidth) for sync and error detection | **Scrambling**: substitutes patterns, no extra bandwidth (B8ZS, HDB3) |
| **OSI**: 7 layers, reference model, protocols came after | **TCP/IP**: 4 layers, practical, protocols came first |
| **Circuit switching**: dedicated path, reserved, constant delay | **Packet switching**: shared, store-and-forward, variable delay |
| **Datagram**: each packet routed independently, may arrive out of order | **Virtual circuit**: path set up first, same path, in order |
| **Single-bit error** | **Burst error** (2+ bits; more common) |
| **CRC**: polynomial division, strong, hardware | **Checksum**: one's-complement sum, weaker, software |
| **Error detection** | **Error correction** (needs more redundancy: d_min = 2t+1 vs s+1) |
| **Go-Back-N**: receiver window 1, resend all after the lost frame, cumulative ACK, sender window ≤ 2ᵐ−1 | **Selective Repeat**: receiver buffers, resend only the lost frame, NAK, windows ≤ 2ᵐ⁻¹ |
| **Flow control**: protects the receiver (rwnd) | **Congestion control**: protects the network (cwnd) |
| **Pure ALOHA**: send any time, vulnerable 2·T_fr, max 18.4% | **Slotted ALOHA**: send at slot start, vulnerable T_fr, max 36.8% |
| **CSMA/CD**: wired Ethernet, detects collisions, jam + backoff | **CSMA/CA**: wireless 802.11, avoids collisions (IFS, contention window, ACK, RTS/CTS) |
| **FDMA / TDMA** | **CDMA**: all stations send together with orthogonal codes |
| **IPv4**: 32 bits, 20–60 B header, checksum, broadcast, routers fragment | **IPv6**: 128 bits, 40 B fixed header, no checksum, no broadcast (anycast), only the source fragments, SLAAC |
| **Classful**: fixed A/B/C blocks, wasteful | **Classless (CIDR)**: any prefix /n, efficient, aggregation |
| **Subnetting**: split one network into smaller ones | **Supernetting**: combine contiguous networks into one bigger prefix |
| **Private IP**: 10/8, 172.16/12, 192.168/16, not routable on the internet | **Public IP**: globally unique, routable |
| **ARP**: IP → MAC | **RARP**: MAC → IP (obsolete, replaced by DHCP) |
| **Static routing**: manual, no overhead, doesn't adapt | **Dynamic routing**: protocols, adapts to failures |
| **Distance vector**: share the table with neighbors, Bellman–Ford, count-to-infinity, slow convergence | **Link state**: flood LSAs to all, Dijkstra, full map, fast convergence |
| **RIP**: DV, hop count ≤ 15, UDP 520, 30 s updates, small networks | **OSPF**: LS, cost metric, IP protocol 89, areas, large networks |
| **IGP** (inside an AS: RIP, OSPF) | **EGP** (between ASes: BGP, path vector, TCP 179) |
| **TCP**: connection-oriented, reliable, ordered, byte stream, flow + congestion control, 20–60 B header | **UDP**: connectionless, unreliable, message-oriented, no control, 8 B header, faster |
| **Port number**: identifies a process | **IP address**: identifies a host. Socket = IP + port |
| **Leaky bucket**: constant output rate, no bursts, drops packets when full | **Token bucket**: average rate r with bursts up to b, drops tokens not packets |
| **IntServ**: per-flow reservation (RSVP), doesn't scale | **DiffServ**: per-class marking (DSCP), scalable |
| **HTTP non-persistent**: TCP connection per object (2 RTT each) | **HTTP persistent**: one connection for many objects (keep-alive, pipelining) |
| **GET**: data in the URL, fetches, cacheable | **POST**: data in the body, sends/creates, not cached |
| **FTP**: TCP, two connections (21 + 20), authentication, listing | **TFTP**: UDP 69, one connection, no authentication |
| **TELNET**: port 23, plaintext | **SSH**: port 22, encrypted |
| **SMTP**: push, sends mail (port 25) | **POP3/IMAP**: pull, retrieves mail |
| **POP3**: download + delete, one device, port 110 | **IMAP**: mail stays on the server, folders, multi-device sync, port 143 |
| **Recursive DNS query**: the server returns the final answer | **Iterative DNS query**: the server returns a referral |
| **DHCP**: dynamic, leases, gives mask + gateway + DNS, can cross routers (relay) | **BOOTP / RARP**: static tables / only an IP, can't cross routers (RARP) |

---

## 7. Formulas

| What | Formula |
|---|---|
| Bit rate vs baud | N = S × r (r = bits per signal element = log₂L) |
| **Nyquist bit rate** (noiseless channel) | **C = 2 × B × log₂L** (B = bandwidth in Hz, L = signal levels) |
| **Shannon capacity** (noisy channel) | **C = B × log₂(1 + SNR)** |
| SNR in dB | SNR_dB = 10 log₁₀(SNR) |
| Attenuation / gain in dB | dB = 10 log₁₀(P₂ / P₁) |
| Wavelength | λ = c / f (propagation speed / frequency) |
| **Transmission delay** | **T_t = L / R** (frame bits / bandwidth) |
| **Propagation delay** | **T_p = d / v** (distance / signal speed; ≈ 2×10⁸ m/s in cable) |
| Latency | propagation + transmission + queuing + processing |
| Bandwidth-delay product | bandwidth × delay (bits "in the pipe") |
| **Throughput / efficiency, stop-and-wait** | **η = 1 / (1 + 2a)**, a = T_p / T_t |
| Sliding window efficiency | η = N / (1 + 2a) (≤ 1); window that fills the pipe: N ≥ 1 + 2a |
| Sequence number bits for window N | GBN: N ≤ 2ᵐ − 1; SR: N ≤ 2ᵐ⁻¹ |
| PCM bit rate | f_s × n_b (f_s ≥ 2 f_max, Nyquist sampling) |
| PCM quantization SNR | SNR_dB = 6.02 n_b + 1.76 |
| AM / FM bandwidth | B_AM = 2B; B_FM = 2(1 + β)B |
| ASK/PSK bandwidth | B = (1 + d) S |
| **Pure ALOHA** | S = G e⁻²ᴳ, max 0.184 at G = 0.5; vulnerable time 2 T_fr |
| **Slotted ALOHA** | S = G e⁻ᴳ, max 0.368 at G = 1; vulnerable time T_fr |
| **CSMA/CD minimum frame** | L_min = 2 × T_p × bandwidth (T_fr ≥ 2 T_p) |
| Backoff after the n-th collision | K random in [0, 2ⁿ − 1] slots (n ≤ 10) |
| Hamming parity bits | 2ʳ ≥ m + r + 1 |
| Detect s / correct t errors | d_min = s + 1 / d_min = 2t + 1 |
| Mesh links | n(n − 1) / 2 |
| Addresses in a block /n | 2^(32 − n); usable hosts 2^(32−n) − 2 |
| Subnets from s borrowed bits | 2ˢ subnets, 2ʰ − 2 hosts each |
| Network address | IP AND mask; broadcast = IP OR (NOT mask) |
| TCP send window | min(rwnd, cwnd) |
| TCP throughput (approx.) | window / RTT |
| Token bucket max burst time | S = b / (M − r) |
| Non-persistent HTTP, one object | 2 RTT + transmission time |
| DHCP renew / rebind | T1 = 0.5 × lease, T2 = 0.875 × lease |

---

## 8. Numericals (practice on paper)

**1. Nyquist.** A noiseless 3000 Hz channel with 2 signal levels:
C = 2 × 3000 × log₂2 = **6000 bps**. With 4 levels: 2 × 3000 × 2 =
**12,000 bps**.

**2. Shannon.** A telephone line with B = 3000 Hz and SNR = 3162 (35 dB):
C = 3000 × log₂(3163) ≈ 3000 × 11.62 ≈ **34,860 bps**.

**3. Shannon + Nyquist together.** B = 1 MHz, SNR = 63.
- Shannon: C = 10⁶ × log₂64 = **6 Mbps** (the upper limit).
- To be safe, choose 4 Mbps. Nyquist then gives 4 Mbps = 2 × 1 MHz × log₂L,
  so log₂L = 2 and **L = 4 levels**.

**4. PCM.** A signal with f_max = 4 kHz, quantized with 256 levels
(n_b = 8): f_s = 8000 samples/s, so bit rate = 8000 × 8 = **64 kbps**.

**5. Delays.** A 1000-bit frame, 1 Mbps, 2000 km, v = 2×10⁸ m/s.
- T_t = 1000 / 10⁶ = 1 ms.
- T_p = 2×10⁶ / 2×10⁸ = 10 ms.
- a = 10.
- Stop-and-wait efficiency = 1 / (1 + 20) ≈ **4.8%**.
- Window needed for 100% = 1 + 2a = **21 frames** → 5 sequence bits for GBN
  (2⁵ − 1 = 31 ≥ 21).

**6. CRC.** Data 1001, generator 1011.
- Append 3 zeros → 1001000.
- Mod-2 division: 1001000 ⊕ 1011000 = 0010000; then ⊕ 0010110 = 0000110.
- **CRC = 110**; transmit **1001110**.
- Check: 1001110 ⊕ 1011000 = 0010110; ⊕ 0010110 = 0 → no error.

**7. Hamming (7,4), even parity.** Data 1011 in positions 3, 5, 6, 7.
1. Parity bits:
   - P1 (positions 1, 3, 5, 7) = 1 ⊕ 0 ⊕ 1 = **0**;
   - P2 (2, 3, 6, 7) = 1 ⊕ 1 ⊕ 1 = **1**;
   - P4 (4, 5, 6, 7) = 0 ⊕ 1 ⊕ 1 = **0**.
2. Codeword = **0110011**.
3. If bit 6 flips (giving 0110001), recheck:
   - C1 = 0 ⊕ 1 ⊕ 0 ⊕ 1 = 0;
   - C2 = 1 ⊕ 1 ⊕ 0 ⊕ 1 = 1;
   - C4 = 0 ⊕ 0 ⊕ 0 ⊕ 1 = 1.
4. Syndrome **110 = 6**: bit 6 is wrong; flip it.

**8. Checksum (8-bit words for practice).** Words 10101001 and 00111001.
- Sum = 11100010 (no carry).
- Checksum = complement = **00011101**.
- Receiver: 10101001 + 00111001 + 00011101 = 11111111 → complement =
  00000000 → **accept**.

**9. Hamming distance.** d(10101, 11110) = number of 1s in 01011 = **3**.
A code with d_min = 3 detects 2 errors and corrects 1.

**10. Pure / slotted ALOHA.** A 200 kbps channel, 200-bit frames
(T_fr = 1 ms).
- At 1000 frames/s, G = 1:
  - pure: S = 1 × e⁻² = 0.135 → **135 frames/s** get through;
  - slotted: S = 1 × e⁻¹ = 0.368 → **368 frames/s**.
- At 500 frames/s (G = 0.5), pure ALOHA: S = 0.5 × e⁻¹ = 0.184 →
  **92 frames/s**.

**11. CSMA/CD minimum frame.** 10 Mbps, maximum round-trip time 51.2 µs →
L_min = 10⁷ × 51.2×10⁻⁶ = **512 bits = 64 bytes**.

**12. Classful.** 172.16.5.10 is **Class B** (128–191). Default mask
255.255.0.0, network 172.16.0.0, broadcast 172.16.255.255.

**13. CIDR block.** 205.16.37.39/28.
- Mask = 255.255.255.240.
- Block size 16; 39 is in the block 32–47.
- **First = 205.16.37.32**, **last = 205.16.37.47**.
- 16 addresses, 14 usable.

**14. Subnetting.** Divide 192.168.10.0/24 into 4 subnets.
- Borrow 2 bits → **/26**, mask 255.255.255.192, 64 addresses, **62 hosts**
  each.

  | Subnet | Network | Usable hosts | Broadcast |
  |---|---|---|---|
  | 1 | 192.168.10.0 | .1–.62 | .63 |
  | 2 | 192.168.10.64 | .65–.126 | .127 |
  | 3 | 192.168.10.128 | .129–.190 | .191 |
  | 4 | 192.168.10.192 | .193–.254 | .255 |

**15. Hosts → prefix.** A subnet needs 50 hosts: 2⁶ − 2 = 62 ≥ 50 → 6 host
bits → **/26**.

**16. Which subnet?** 172.16.45.130/20.
- Mask 255.255.240.0; the third octet goes in blocks of 16; 45 is in 32–47.
- Network **172.16.32.0**, broadcast **172.16.47.255**, 4094 hosts.

**17. VLSM.** From 192.168.1.0/24, give A 100 hosts, B 50 hosts, C 2 hosts
(point-to-point link). Allocate the largest first:

| Need | Prefix | Range |
|---|---|---|
| A, 100 hosts | /25 | 192.168.1.0–127 |
| B, 50 hosts | /26 | 192.168.1.128–191 |
| C, 2 hosts | /30 | 192.168.1.192–195 |

**18. Supernetting.** 200.1.0.0/24 + 200.1.1.0/24 + 200.1.2.0/24 +
200.1.3.0/24 → **200.1.0.0/22** (the first 22 bits match).

**19. IPv4 fragmentation.** A 4000-B datagram (20 B header + 3980 B data)
over MTU 1500. Maximum data per fragment = 1480 (a multiple of 8).

| Fragment | Data | Offset | MF |
|---|---|---|---|
| 1 | 1480 | 0 | 1 |
| 2 | 1480 | 185 | 1 |
| 3 | 1020 | 370 | 0 |

**20. Distance vector update.** Router A has neighbors B (cost 2) and
C (cost 5). B says "D at cost 3"; C says "D at cost 1".
A → D = min(2 + 3, 5 + 1) = **5, via B**.

**21. TCP slow start.** MSS = 1 KB, ssthresh = 16 KB, no losses. cwnd per
RTT: 1, 2, 4, 8, **16** (reaches ssthresh), then 17, 18, … (linear).
- A **timeout** at cwnd = 20: ssthresh = 10, cwnd = 1 (Tahoe).
- **3 duplicate ACKs** at cwnd = 20: ssthresh = 10, cwnd = 10 (Reno).

**22. TCP sequence numbers.** A segment carries bytes 1001–2000 (seq =
1001). The ACK for it = **2001**. A SYN with ISN 5000 uses up one number,
so the first data byte is 5001.

**23. Token bucket.** b = 1 MB, r = 2 MB/s, M = 10 MB/s. Maximum burst
time S = 1 / (10 − 2) = **0.125 s**.

**24. HTTP.** A page with 1 base HTML file + 10 images, non-persistent,
no parallel connections, ignoring transmission time: 11 × 2 RTT =
**22 RTT**. Persistent with pipelining: 2 RTT (connection + HTML) + about
1 RTT for all the images = **~3 RTT**.

---

### Last-minute checklist
- **7 OSI layers**, with the job and PDU of each.
- **Nyquist vs Shannon**.
- **Manchester encoding**.
- **CRC by hand**; **Hamming**: position of parity bits and syndrome.
- **GBN vs SR window sizes**.
- **ALOHA 18.4% / 36.8%**; **CSMA/CD vs CA**.
- **Ethernet frame fields, 64–1518**.
- **Classful ranges**; **CIDR first/last address**; **subnetting**.
- **NAT, ARP**; **ICMP types (0, 3, 8, 11)**.
- **DV vs LS**; **RIP/OSPF/BGP table**.
- **UDP vs TCP**; **3-way handshake**.
- **Slow start / AIMD**; **Nagle**; **leaky vs token bucket**.
- **DORA**; **HTTP status codes**; **FTP's 2 connections**; **POP3 vs
  IMAP**; **MIME**; **DNS records + recursive/iterative**.
- **SNMP manager/agent/MIB**.
- **Well-known ports**: 20/21, 22, 23, 25, 53, 67/68, 80, 110, 143, 161,
  443.
