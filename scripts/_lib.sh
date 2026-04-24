#!/usr/bin/env bash
# shared helpers for lab scripts. sourced, not executed.

# anchor to repo root regardless of where the caller cd'd to
# $BASH_SOURCE[1] is the script that sourced us; realpath resolves symlinks
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)"
TOPO="${REPO_ROOT}/topology/lab.clab.yml"

# color output only when stdout is a tty (so logs stay clean)
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'; YEL=$'\033[0;33m'; GRN=$'\033[0;32m'; DIM=$'\033[2m'; RST=$'\033[0m'
else
  RED=''; YEL=''; GRN=''; DIM=''; RST=''
fi

log()  { printf '%s\n' "$*" >&2; }
info() { printf '%s==>%s %s\n' "$GRN" "$RST" "$*" >&2; }
warn() { printf '%sWARN:%s %s\n' "$YEL" "$RST" "$*" >&2; }
err()  { printf '%sERROR:%s %s\n' "$RED" "$RST" "$*" >&2; }
dbg()  { [[ "${DEBUG:-0}" == "1" ]] && printf '%sDEBUG:%s %s\n' "$DIM" "$RST" "$*" >&2 || true; }

# confirm "prompt message" — returns 0 if yes, 1 if no. honors $ASSUME_YES=1.
confirm() {
  if [[ "${ASSUME_YES:-0}" == "1" ]]; then
    dbg "auto-confirming: $1"
    return 0
  fi
  local reply
  read -r -p "$1 [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

# pass --debug through to clab if DEBUG=1
clab_flags() {
  [[ "${DEBUG:-0}" == "1" ]] && printf -- '-d'
}

# ensure topology exists before any command runs
require_topo() {
  [[ -f "$TOPO" ]] || { err "topology not found: $TOPO"; exit 1; }
}

# require a command or exit with install hint
require_cmd() {
  local cmd="$1" hint="${2:-}"
  command -v "$cmd" >/dev/null 2>&1 || {
    err "'$cmd' not found${hint:+. install: $hint}"
    exit 1
  }
}

# list nodes from topology: "name kind" per line, tab-separated
# caller can parse with: while IFS=$'\t' read -r name kind; do ...
topology_nodes() {
  yq -r '.topology.nodes | to_entries | .[] | "\(.key)\t\(.value.kind)"' "$TOPO"
}

# derive the clab runtime dir from the topology's `name:` field
runtime_dir() {
  local lab_name
  lab_name="$(yq -r '.name' "$TOPO")"
  printf '%s/topology/clab-%s' "$REPO_ROOT" "$lab_name"
}