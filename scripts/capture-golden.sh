#!/usr/bin/env bash
# capture running configs as the new golden (git-tracked) source of truth.
# runs `clab save`, then promotes per-node artifacts from runtime dir to configs/.
# linux nodes are skipped — they're already sourced from configs/ via bind mounts.
#
# usage:
#   ./scripts/capture-golden.sh                  # save all nodes, prompt before overwriting golden
#   ./scripts/capture-golden.sh -y               # no prompts
#   ./scripts/capture-golden.sh --node leaf1     # one node only; repeatable
#   ./scripts/capture-golden.sh -d               # verbose

set -euo pipefail
source "$(dirname "$0")/_lib.sh"

require_cmd yq "sudo snap install yq  (or: sudo apt install yq)"

NODE_FILTER=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --node)      NODE_FILTER+=("$2"); shift ;;
    -y|--yes)    ASSUME_YES=1 ;;
    -d|--debug)  DEBUG=1 ;;
    -h|--help)   sed -n '2,10p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) err "unknown flag: $1"; exit 2 ;;
  esac
  shift
done

require_topo
RUNTIME_DIR="$(runtime_dir)"
[[ -d "$RUNTIME_DIR" ]] || { err "runtime dir missing: $RUNTIME_DIR (lab deployed?)"; exit 1; }

# step 1: tell every node to save its running config.
# for ceos this writes flash/startup-config; for srl it writes checkpoint-0.json.
info "saving running configs on all nodes..."
save_args=()
if [[ ${#NODE_FILTER[@]} -gt 0 ]]; then
  save_args+=(--node-filter "$(IFS=,; echo "${NODE_FILTER[*]}")")
fi
sudo containerlab save $(clab_flags) -t "$TOPO" "${save_args[@]}"

# step 2: for each node in the topology, copy the runtime artifact into configs/
changes=0
skipped=0
while IFS=$'\t' read -r name kind; do
  # skip if filter is set and this node isn't in it
  if [[ ${#NODE_FILTER[@]} -gt 0 ]]; then
    [[ " ${NODE_FILTER[*]} " == *" $name "* ]] || continue
  fi

  case "$kind" in
    arista_ceos)
      src="$RUNTIME_DIR/$name/flash/startup-config"
      dst="$REPO_ROOT/configs/$name/startup-config"
      ;;
    nokia_srlinux)
      src="$RUNTIME_DIR/$name/config/checkpoint/checkpoint-0.json"
      dst="$REPO_ROOT/configs/$name/config.json"
      ;;
    linux)
      dbg "$name: linux kind, already sourced from configs/ via binds — skipping"
      ((skipped++))
      continue
      ;;
    *)
      warn "$name: unknown kind '$kind' — skipping"
      ((skipped++))
      continue
      ;;
  esac

  if ! sudo test -f "$src"; then
    warn "$name: runtime artifact missing ($src) — did save fail for this node?"
    continue
  fi

  mkdir -p "$(dirname "$dst")"

  if [[ -f "$dst" ]] && sudo cmp -s "$src" "$dst"; then
    dbg "$name: no changes"
    continue
  fi

  if [[ -f "$dst" ]]; then
    info "$name: changes detected vs existing golden:"
    sudo diff -u "$dst" "$src" | head -40 >&2 || true
    confirm "  overwrite golden for $name?" || { warn "  skipped $name"; continue; }
  else
    info "$name: no existing golden — creating new at configs/$name/"
  fi

  sudo cp "$src" "$dst"
  # clab saves run as root; make the golden owned by the caller so git sees it normally
  sudo chown "$(id -u):$(id -g)" "$dst"
  ((changes++))
done < <(topology_nodes)

info "done. $changes node(s) updated, $skipped skipped."
if [[ "$changes" -gt 0 ]]; then
  info "review: git diff configs/"
  info "commit: git add configs/ && git commit -m 'capture golden configs'"
fi