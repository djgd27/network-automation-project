#!/usr/bin/env bash
# tear down the lab. preserves runtime dir (saved configs) by default.
# use --purge to fully nuke state.
#
# usage:
#   ./scripts/lab-down.sh              # safe teardown, prompts
#   ./scripts/lab-down.sh --purge      # full nuke incl. runtime dir, prompts
#   ./scripts/lab-down.sh --purge -y   # full nuke, no prompt
#   ./scripts/lab-down.sh -d           # verbose

set -euo pipefail
source "$(dirname "$0")/_lib.sh"

PURGE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge)     PURGE=1 ;;
    -y|--yes)    ASSUME_YES=1 ;;
    -d|--debug)  DEBUG=1 ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) err "unknown flag: $1"; exit 2 ;;
  esac
  shift
done

require_topo

if [[ "$PURGE" == "1" ]]; then
  warn "PURGE mode: --cleanup will be used. all saved configs in the runtime dir will be DELETED."
  confirm "continue?" || { info "aborted."; exit 0; }
  info "destroying lab + purging runtime dir"
  containerlab destroy $(clab_flags) --graceful --cleanup -t "$TOPO"
else
  confirm "destroy lab (runtime dir preserved)?" || { info "aborted."; exit 0; }
  info "destroying lab (preserving runtime dir and saved configs)"
  containerlab destroy $(clab_flags) --graceful -t "$TOPO"
fi

info "lab destroyed."