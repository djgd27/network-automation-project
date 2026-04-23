#!/usr/bin/env bash
# Pull or import all container images required by the lab topology.
# Run once after cloning the repo on a new host.

set -euo pipefail

echo "==> Pulling Nokia SR Linux..."
docker pull ghcr.io/nokia/srlinux:latest

echo "==> Pulling FRR..."
docker pull frrouting/frr:latest

echo "==> Pulling Alpine (for server nodes)..."
docker pull alpine:latest

echo ""
echo "==> Arista cEOS cannot be pulled — it must be downloaded manually."
echo "    1. Sign in at https://www.arista.com/en/support/software-download"
echo "    2. Download cEOS64-lab-4.36.0F.tar (or your chosen version)."
echo "    3. Import with:"
echo "       docker import cEOS64-lab-4.36.0F.tar ceos:4.36.0F"
echo ""
echo "==> Done."