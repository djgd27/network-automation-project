#!/usr/bin/env bash
# Capture running configs from all devices into configs/golden/.
# Run before any clab destroy to preserve manual configuration work.
#
# Golden configs use stable filenames (git tracks history).
# Evidence captures are timestamped directories (point-in-time snapshots).
#
# Secrets (password hashes) are scrubbed from cEOS configs before writing.

set -uo pipefail

GOLDEN_DIR="./configs/golden"
TIMESTAMP="$(date +%Y%m%d-%H%M)"
EVIDENCE_DIR="./docs/evidence/${TIMESTAMP}"

mkdir -p "${GOLDEN_DIR}" "${EVIDENCE_DIR}"

# -----------------------------------------------------------------------------
# Scrubbers
# -----------------------------------------------------------------------------

scrub_ceos() {
    sed -E \
        -e 's|(secret sha512 )\$[^[:space:]]+.*|\1<REDACTED>|g' \
        -e 's|(secret 5 )\$[^[:space:]]+.*|\1<REDACTED>|g' \
        -e 's|(enable secret [^[:space:]]+) .*|\1 <REDACTED>|g' \
        -e 's|( 7 )[A-Fa-f0-9]+|\1<REDACTED>|g'
}

scrub_srlinux_json() {
    python3 -c '
import json, sys
def scrub(o):
    if isinstance(o, dict):
        for k in list(o.keys()):
            if k in ("hashed-password", "private-key", "psk", "pre-shared-key"):
                o[k] = "<REDACTED>"
            else:
                scrub(o[k])
    elif isinstance(o, list):
        for i in o:
            scrub(i)
d = json.load(sys.stdin)
scrub(d)
json.dump(d, sys.stdout, indent=2)
'
}

# -----------------------------------------------------------------------------
# Golden configs (stable filenames)
# -----------------------------------------------------------------------------

echo "==> Capturing cEOS configs (password hashes scrubbed)..."
for node in spine1 spine2 leaf1 leaf2; do
    if docker exec "${node}" true 2>/dev/null; then
        docker exec "${node}" Cli -p 15 -c "show running-config" \
            | scrub_ceos \
            > "${GOLDEN_DIR}/${node}.cfg"
        echo "    ${node} -> ${GOLDEN_DIR}/${node}.cfg"
    else
        echo "    WARN: ${node} not reachable, skipping"
    fi
done

echo "==> Capturing SR Linux config..."
if docker exec leaf3 true 2>/dev/null; then
    docker exec leaf3 sr_cli "info" > "${GOLDEN_DIR}/leaf3.cfg"
    echo "    leaf3 -> ${GOLDEN_DIR}/leaf3.cfg"

    if docker exec leaf3 test -f /etc/opt/srlinux/config.json; then
        docker exec leaf3 cat /etc/opt/srlinux/config.json \
            | scrub_srlinux_json \
            > "${GOLDEN_DIR}/leaf3.config.json"
        echo "    leaf3 -> ${GOLDEN_DIR}/leaf3.config.json"
    fi
else
    echo "    WARN: leaf3 not reachable, skipping"
fi

echo "==> Capturing FRR running config..."
if docker exec edge1 true 2>/dev/null; then
    docker exec edge1 vtysh -c "show running-config" > "${GOLDEN_DIR}/edge1.cfg" 2>/dev/null
    echo "    edge1 -> ${GOLDEN_DIR}/edge1.cfg"
else
    echo "    WARN: edge1 not reachable, skipping"
fi

# -----------------------------------------------------------------------------
# Evidence (timestamped directories)
# -----------------------------------------------------------------------------

echo ""
echo "==> Capturing evidence to ${EVIDENCE_DIR}..."

for node in spine1 spine2 leaf1 leaf2; do
    docker exec "${node}" Cli -p 15 -c "show ip bgp summary" \
        > "${EVIDENCE_DIR}/${node}-bgp-summary.txt" 2>/dev/null || true
    docker exec "${node}" Cli -p 15 -c "show ip route bgp" \
        > "${EVIDENCE_DIR}/${node}-routes-bgp.txt" 2>/dev/null || true
done

docker exec leaf3 sr_cli "show network-instance default protocols bgp neighbor" \
    > "${EVIDENCE_DIR}/leaf3-bgp-neighbor.txt" 2>/dev/null || true
docker exec leaf3 sr_cli "show network-instance default route-table ipv4-unicast" \
    > "${EVIDENCE_DIR}/leaf3-routes.txt" 2>/dev/null || true

docker exec edge1 vtysh -c "show ip bgp summary" \
    > "${EVIDENCE_DIR}/edge1-bgp-summary.txt" 2>/dev/null || true

echo ""
echo "==> Done."
echo "    Golden configs: ${GOLDEN_DIR}/"
echo "    Evidence:       ${EVIDENCE_DIR}/"