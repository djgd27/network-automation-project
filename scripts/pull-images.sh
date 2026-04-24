#!/usr/bin/env bash
# Pull or import all container images required by the lab topology.
# Run once after cloning the repo on a new host, or after bumping an image version.
#
# usage:
#   ./scripts/pull-images.sh          # pull all pullable images
#   ./scripts/pull-images.sh --dry    # show what would be pulled, do nothing
#   ./scripts/pull-images.sh -d       # verbose

set -euo pipefail
source "$(dirname "$0")/_lib.sh"

require_cmd yq "sudo apt install yq"

DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry)       DRY=1 ;;
    -d|--debug)  DEBUG=1 ;;
    -h|--help)   sed -n '2,9p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) err "unknown flag: $1"; exit 2 ;;
  esac
  shift
done

require_topo

# collect images from kinds and per-node overrides, dedupe.
mapfile -t images < <(
  {
    yq -r '.topology.kinds[]?.image // empty' "$TOPO"
    yq -r '.topology.nodes[]?.image   // empty' "$TOPO"
  } | sort -u
)

[[ ${#images[@]} -eq 0 ]] && { warn "no images declared in topology"; exit 0; }

info "images declared in topology:"
printf '  - %s\n' "${images[@]}" >&2
echo >&2

# split pullable vs sideloaded (cEOS)
pullable=()
sideload=()
for img in "${images[@]}"; do
  case "$img" in
    ceos:*|ceos-lab:*|ceos64:*) sideload+=("$img") ;;
    *)                          pullable+=("$img") ;;
  esac
done

if [[ "$DRY" == "1" ]]; then
  info "dry run — not pulling."
  exit 0
fi

# pull what we can
for img in "${pullable[@]}"; do
  info "pulling $img"
  sudo docker pull "$img"
done

# guide the user through sideloading cEOS if needed
if [[ ${#sideload[@]} -gt 0 ]]; then
  echo >&2
  warn "cEOS images cannot be pulled — they must be downloaded manually from Arista."
  for img in "${sideload[@]}"; do
    # already imported?
    if sudo docker image inspect "$img" >/dev/null 2>&1; then
      info "$img already present locally ✓"
      continue
    fi
    version="${img#*:}"                       # 4.36.0F
    expected_tar="cEOS64-lab-${version}.tar"  # or cEOS-lab-... depending on arch
    warn "$img is NOT imported yet. to install:"
    cat >&2 <<EOF
    1. sign in at https://www.arista.com/en/support/software-download
    2. download ${expected_tar} (or the cEOS-lab variant for your arch)
    3. import with:
         sudo docker import ${expected_tar} ${img}
EOF
    echo >&2
  done
fi

info "done."