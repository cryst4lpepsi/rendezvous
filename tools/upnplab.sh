#!/bin/bash
# upnplab.sh - the NAT lab plus a real UPnP router: miniupnpd (nftables backend) on
# alice's router rA. Needs root and miniupnpd.
# Env: UPNP=yes|no  NATPMP=yes|no  START=yes|no (no = router without port opening;
#      start it later with: ip netns exec rA miniupnpd -f $TMPDIR/miniupnpd.conf -d)
# Then, for example:
#   ip netns exec hA python3 peer.py --host --room friday --password pw --name alice --vlan
#   ip netns exec hB python3 peer.py --invite <code from alice's /api/state> --name bob --vlan
set -e
R=$(cd "$(dirname "$0")/.." && pwd); S=${TMPDIR:-/tmp}
pkill -x miniupnpd || true; sleep 0.3; rm -f /var/run/miniupnpd.pid
$R/tools/natlab.sh down; NET=11.0.0 $R/tools/natlab.sh up >/dev/null
# allow port-forwarded (DNAT) connections through, like a real router
ip netns exec rA iptables -I FORWARD 1 -i wan -m conntrack --ctstate DNAT -j ACCEPT
ip netns exec rA nft -f - <<'NFT'
table inet filter {
  chain forward { type filter hook forward priority 0; policy accept; jump miniupnpd; }
  chain miniupnpd { }
  chain prerouting { type nat hook prerouting priority -100; policy accept; jump prerouting_miniupnpd; }
  chain postrouting { type nat hook postrouting priority 100; policy accept; jump postrouting_miniupnpd; }
  chain prerouting_miniupnpd { }
  chain postrouting_miniupnpd { }
}
NFT
cat > $S/miniupnpd.conf <<CONF
ext_ifname=wan
ext_ip=11.0.0.1
listening_ip=lan
port=5000
enable_upnp=${UPNP:-yes}
enable_natpmp=${NATPMP:-no}
secure_mode=yes
system_uptime=yes
uuid=c0afbae1-35f2-422a-aefe-0f0e6b2a9fb5
allow 1024-65535 192.168.1.0/24 1024-65535
deny 0-65535 0.0.0.0/0 0-65535
CONF
if [ "${START:-yes}" = yes ]; then
  ip netns exec rA miniupnpd -f $S/miniupnpd.conf -d > $S/miniupnpd.log 2>&1 &
fi
sleep 1
echo "lab up (UPnP=${UPNP:-yes} NAT-PMP=${NATPMP:-no} running=${START:-yes})"
