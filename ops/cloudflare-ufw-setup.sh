#!/bin/bash
# Restrict inbound HTTP/HTTPS to Cloudflare's published IP ranges only.
# Run this ON THE VPS itself, over SSH, as root or with sudo.
#
# SAFETY: this deliberately leaves SSH (port 22) open to ANY source. Never scope SSH down to
# Cloudflare's ranges -- Cloudflare only proxies web traffic, not SSH, so doing that would lock
# you out entirely. If you want to harden SSH separately, do it as its own, carefully-tested step
# (e.g. restrict to your own IP or a VPN), not bundled with this script.

set -e

echo "== current ufw status (before changes) =="
ufw status verbose

echo
echo "== ensuring SSH stays allowed =="
ufw allow 22/tcp comment 'SSH - always open'

echo
echo "== fetching current Cloudflare IP ranges =="
CF_V4=$(curl -fsSL https://www.cloudflare.com/ips-v4)
CF_V6=$(curl -fsSL https://www.cloudflare.com/ips-v6)

if [ -z "$CF_V4" ]; then
  echo "Failed to fetch Cloudflare IPv4 ranges -- aborting, not touching any rules." >&2
  exit 1
fi

echo
echo "== removing any previous Cloudflare-tagged rules (safe to re-run this script) =="
# Delete by matching our comment tag rather than assuming exact prior rule text, so re-running
# after Cloudflare updates their published ranges doesn't leave stale entries behind.
for port in 80 443; do
  while ufw status numbered | grep -q "cf-allow-$port"; do
    rule_num=$(ufw status numbered | grep "cf-allow-$port" | head -1 | grep -oP '^\[\s*\K[0-9]+')
    [ -n "$rule_num" ] && yes | ufw delete "$rule_num" >/dev/null
  done
done

echo
echo "== adding allow rules for 80/tcp and 443/tcp, scoped to Cloudflare's ranges only =="
for ip in $CF_V4 $CF_V6; do
  ufw allow from "$ip" to any port 80 proto tcp comment "cf-allow-80"
  ufw allow from "$ip" to any port 443 proto tcp comment "cf-allow-443"
done

echo
echo "== denying 80/443 from everywhere else =="
# These land AFTER the specific allow rules above; ufw evaluates in order, first match wins, so
# traffic from a Cloudflare IP hits the allow rule first and never reaches this deny.
ufw deny 80/tcp comment 'deny non-Cloudflare web traffic'
ufw deny 443/tcp comment 'deny non-Cloudflare web traffic'

echo
echo "== enabling ufw (no-op if already enabled) =="
ufw --force enable

echo
echo "== final status -- VERIFY SSH (22) shows ALLOW before disconnecting this session =="
ufw status verbose
