#!/bin/bash
# natlab.sh up [--symmetric] | down   : two peers behind separate NAT routers + a public server
# Linux/WSL only, needs root (ip netns + iptables). Used to test hole punching against real NAT.
# After "up", run the server in ns "srv" and the peers in "hA" / "hB", e.g.
#   ip netns exec srv python3 rendezvous_server.py
#   ip netns exec hA  python3 peer.py --server 203.0.113.10:9000 --name alice
#   ip netns exec hB  python3 peer.py --server 203.0.113.10:9000 --name bob
set -e
NS="inet srv rA rB hA hB"
if [ "$1" = down ]; then for n in $NS; do ip netns del $n 2>/dev/null || true; done; exit 0; fi
for n in $NS; do ip netns add $n; ip -n $n link set lo up; done
ip -n inet link add br0 type bridge; ip -n inet link set br0 up
link() { # ns_a if_a ns_b if_b
  ip link add $2 netns $1 type veth peer name $4 netns $3
  ip -n $1 link set $2 up; ip -n $3 link set $4 up; }
link srv eth0 inet p-srv; link rA wan inet p-rA; link rB wan inet p-rB
for p in p-srv p-rA p-rB; do ip -n inet link set $p master br0; done
ip -n srv addr add 203.0.113.10/24 dev eth0
ip -n rA addr add 203.0.113.1/24 dev wan
ip -n rB addr add 203.0.113.2/24 dev wan
link hA eth0 rA lan; link hB eth0 rB lan
ip -n rA addr add 192.168.1.1/24 dev lan; ip -n hA addr add 192.168.1.10/24 dev eth0; ip -n hA route add default via 192.168.1.1
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
