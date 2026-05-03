#!/usr/bin/env bash
# verify the host is in a clean state for clab operations.
# exits non-zero if stale state detected.
#
# usage:
#   ./scripts/lab-verify.sh         # quick checks
#   ./scripts/lab-verify.sh -d      # verbose

set -euo pipefail
source "$(dirname "$0")/_lib.sh"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--debug) DEBUG=1 ;;
    -h|--help)  sed -n '2,7p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) err "unknown flag: $1"; exit 2 ;;
  esac
  shift
done

fail=0

info "checking /etc/hosts for clab entries..."
if grep -qE 'Kind: (arista_ceos|nokia_srlinux|linux)' /etc/hosts; then
  # entries exist — is a lab actually running?
  if containerlab inspect $(clab_flags) -t "$TOPO" >/dev/null 2>&1; then
    info "lab is running, hosts entries are expected"
  else
    warn "stale clab entries in /etc/hosts (no lab running):"
    grep -E 'Kind: (arista_ceos|nokia_srlinux|linux)' /etc/hosts >&2
    fail=1
  fi
else
  dbg "no clab entries in /etc/hosts"
fi

info "checking for orphaned clab marker blocks..."
if grep -qE '### CLAB-.*-(START|END) ###' /etc/hosts; then
  if ! grep -qE 'Kind:' /etc/hosts; then
    warn "clab marker block present but empty — orphaned block"
    fail=1
  fi
fi

if [[ "$fail" == "1" ]]; then
  err "verification failed. fix stale state before deploying."
  err "  suggested: sudo sed -i '/### CLAB-.*-START ###/,/### CLAB-.*-END ###/d' /etc/hosts"
  exit 1
fi

info "host state looks clean."