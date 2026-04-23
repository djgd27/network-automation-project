#!/usr/bin/env bash
# scripts/lab-down.sh
set -euo pipefail
sudo containerlab destroy -t topology/lab.clab.yml --cleanup
echo "verifying hosts file is clean..."
if grep -qE 'Kind: (arista_ceos|nokia_srlinux|linux)' /etc/hosts; then
  echo "WARNING: stale clab entries remain in /etc/hosts"
  grep -E 'Kind: (arista_ceos|nokia_srlinux|linux)' /etc/hosts
  exit 1
fi
echo "lab destroyed cleanly."