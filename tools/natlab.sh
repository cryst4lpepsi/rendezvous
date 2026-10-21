#!/bin/bash
# natlab.sh up [--symmetric] | down
#   hA + hC behind home router rA (same LAN), hB behind router rB, server "srv" on the "internet"
# Linux/WSL only, needs root (ip netns + iptables). Used to test hole punching against real NAT.
# After "up", run the server in ns "srv" and the peers in "hA" / "hB", e.g.
#   ip netns exec srv python3 rendezvous_server.py
#   ip netns exec hA  python3 peer.py --server $NET.10:9000 --name alice
#   ip netns exec hB  python3 peer.py --server $NET.10:9000 --name bob
#   ip netns exec hC  python3 peer.py --server $NET.10:9000 --name carol   (add --vlan for the virtual LAN)
set -e
NET=${NET:-203.0.113}   # the lab "internet"; NET=11.0.0 for miniupnpd, which refuses reserved ranges
NS="inet srv rA rB hA hB hC"
if [ "$1" = down ]; then for n in $NS; do ip netns del $n 2>/dev/null || true; done; exit 0; fi
for n in $NS; do ip netns add $n; ip -n $n link set lo up; done
ip -n inet link add br0 type bridge; ip -n inet link set br0 up
link() { # ns_a if_a ns_b if_b
  ip link add $2 netns $1 type veth peer name $4 netns $3
  ip -n $1 link set $2 up; ip -n $3 link set $4 up; }
link srv eth0 inet p-srv; link rA wan inet p-rA; link rB wan inet p-rB
for p in p-srv p-rA p-rB; do ip -n inet link set $p master br0; done
ip -n srv addr add $NET.10/24 dev eth0
ip -n rA addr add $NET.1/24 dev wan
ip -n rB addr add $NET.2/24 dev wan
ip -n rA link add lan type bridge; ip -n rA link set lan up
link hA eth0 rA lanA; link hC eth0 rA lanC; link hB eth0 rB lan
ip -n rA link set lanA master lan; ip -n rA link set lanC master lan
ip -n rA addr add 192.168.1.1/24 dev lan
ip -n hA addr add 192.168.1.10/24 dev eth0; ip -n hA route add default via 192.168.1.1
ip -n hC addr add 192.168.1.11/24 dev eth0; ip -n hC route add default via 192.168.1.1
ip -n rB addr add 192.168.2.1/24 dev lan; ip -n hB addr add 192.168.2.10/24 dev eth0; ip -n hB route add default via 192.168.2.1
for r in rA rB; do
  ip netns exec $r sysctl -qw net.ipv4.ip_forward=1
  if [ "$2" = --symmetric ] && [ $r = rB ]; then
    # symmetric NAT: a new random public port for every destination
    ip netns exec $r iptables -t nat -A POSTROUTING -o wan -j MASQUERADE --random-fully
  else
    ip netns exec $r iptables -t nat -A POSTROUTING -o wan -j MASQUERADE
  fi
  # the router drops unsolicited inbound traffic, like a home router
  ip netns exec $r iptables -A FORWARD -i wan -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  ip netns exec $r iptables -A FORWARD -i wan -j DROP
  ip netns exec $r iptables -A INPUT -i wan -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  ip netns exec $r iptables -A INPUT -i wan -j DROP
done
echo "lab up $2"
