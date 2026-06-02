#!/bin/bash
# Push the kindledash KOReader plugin to the Kindle over SSH (KOReader dropbear).
# Usage: ./deploy-plugin.sh [kindle_ip]
set -e
IP="${1:-192.168.1.30}"
PORT=2222
SRC="$(cd "$(dirname "$0")/kindledash.koplugin" && pwd)"
DST="/mnt/us/koreader/plugins/kindledash.koplugin"

# key first, fall back to empty password (KOReader "login without password")
ssh_k() { ssh -p "$PORT" -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null -o PreferredAuthentications=publickey \
            -o BatchMode=yes -o ConnectTimeout=8 "root@$IP" "$@" 2>/dev/null; }
ssh_p() { sshpass -p '' ssh -p "$PORT" -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 "root@$IP" "$@" \
            2>&1 | grep -v "Permanently added"; }

run()  { ssh_k "$1" 2>/dev/null && return 0; ssh_p "$1"; }
push() { # local_file remote_file
  if ssh_k "cat > $2" < "$1" 2>/dev/null; then :; else
    sshpass -p '' ssh -p "$PORT" -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null "root@$IP" "cat > $2" < "$1" 2>/dev/null
  fi
}

run "mkdir -p $DST"
push "$SRC/_meta.lua" "$DST/_meta.lua"
push "$SRC/main.lua"  "$DST/main.lua"
echo "deployed to $IP:"
run "ls -la $DST && echo --- && wc -l $DST/main.lua"
