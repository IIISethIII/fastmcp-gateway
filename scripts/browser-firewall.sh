#!/usr/bin/env bash
# Egress policy for the browser-mcp container (10.250.250.10 on docker network
# `browser-internal`, 10.250.250.0/24): internet allowed, LAN / other containers / the host blocked.
# Idempotent; rules are NOT persistent across reboots (re-run, or see the
# systemd unit note in browser-mcp/README). Needs root.
set -euo pipefail
SUBNET=10.250.250.0/24
BROWSER_IP=10.250.250.10   # browser-mcp only; the gateway shares the subnet and is NOT filtered
CHAIN=BROWSER-MCP

iptables -N "$CHAIN" 2>/dev/null || true
iptables -F "$CHAIN"
iptables -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN   # replies to the gateway's MCP requests
iptables -A "$CHAIN" -d "$SUBNET" -j DROP                   # browser must NOT open connections to the gateway (no auth, CORS *)
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
  iptables -A "$CHAIN" -d "$net" -j DROP                    # private, CGNAT/Tailscale, link-local
done
iptables -A "$CHAIN" -j RETURN                              # everything else = public internet

# forwarded traffic (to LAN, other containers, internet)
iptables -C DOCKER-USER -s "$BROWSER_IP" -j "$CHAIN" 2>/dev/null || iptables -I DOCKER-USER 1 -s "$BROWSER_IP" -j "$CHAIN"
# traffic to the docker host itself (its LAN IP, docker0 gateway, published ports)
iptables -C INPUT -s "$SUBNET" ! -d "$SUBNET" -j DROP 2>/dev/null || iptables -I INPUT 1 -s "$BROWSER_IP" ! -d "$SUBNET" -p tcp -j DROP

# Same-bridge traffic (browser -> gateway) never reaches iptables unless br_netfilter
# is loaded, so drop it in the nftables *bridge* family: no new TCP connections from
# the browser to anything on its own subnet (replies to the gateway's requests are untouched).
nft delete table bridge browser_mcp 2>/dev/null || true
nft -f - <<NFT
table bridge browser_mcp {
  chain forward {
    type filter hook forward priority 0; policy accept;
    ip saddr $BROWSER_IP ip daddr $SUBNET tcp flags & (syn | ack) == syn drop
  }
}
NFT
echo "browser-mcp firewall applied"
