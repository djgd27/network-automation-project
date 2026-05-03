# Network Automation PoC: NetBox-Driven EVPN-VXLAN Fabric in Containerlab

A multi-vendor spine-leaf fabric running EVPN-VXLAN inside containerlab,
configured by an automation pipeline that pulls fabric data from NetBox,
renders per-vendor configs through Jinja2 templates, runs offline
pre-flight validation, and deploys via Nornir + NAPALM. A GitHub Actions
workflow runs the offline half of the pipeline on every pull request.

Final project for **MSIS 603N - Network Virtualization** (Marist
University, Spring 2026), Option 5: Network Automation. Built by
**David Galindo Delgado**.

This README is the **replication guide** for the code and configs. For
project background, design decisions, results, and analysis see
`docs/report/main.pdf` and `docs/architecture.md`.

---

## Prerequisites

### Software packages

Installed via `apt` in Step 1 below:

- `docker.io`, `docker-compose-v2`  container runtime + Compose v2 plugin
- `python3`, `python3-venv`, `python3-pip` Python 3 + venv + pip
- `yq`, `jq` YAML / JSON tooling used by the lifecycle scripts
- `git`, `curl`

Installed separately:

- **containerlab**  installed via the official one-line script in Step 2.
- **Python dependencies**  pinned in `requirements.txt` (pynetbox, PyYAML,
  Jinja2, nornir + nornir-netbox + nornir-napalm + nornir-utils, napalm).
  The `venv/` directory is **gitignored**, so you must create your own
  virtual environment in Step 4.

### Accounts

- **Arista** free signup at <https://www.arista.com/en/support/software-download>.
  Required to download the cEOS image (cEOS images cannot be pulled from
  a public registry).

---

## Reproduction steps

The instructions below take a fresh Ubuntu 24.04 host all the way to a
working fabric and a successful pipeline run.

### Step 1 Install system packages

```bash
sudo apt update
sudo apt install -y \
    docker.io docker-compose-v2 \
    python3 python3-venv python3-pip \
    yq jq \
    git curl
```

### Step 2 Install containerlab

```bash
bash -c "$(curl -sL https://get.containerlab.dev)"
```

This installs the `containerlab` binary into `/usr/bin/containerlab`.

### Step 3 Get the cEOS image (manual)

cEOS images cannot be pulled from a public registry.

1. Sign in at <https://www.arista.com/en/support/software-download>.
2. Navigate to **EOS / cEOS-Lab** and download `cEOS64-lab-4.36.0F.tar`.
3. Import the tarball into Docker with the exact tag the topology expects:

   ```bash
   sudo docker import cEOS64-lab-4.36.0F.tar ceos:4.36.0F
   ```

4. Verify it is present:

   ```bash
   docker image ls ceos
   ```

If you skip this step the lab will not deploy. `scripts/pull-images.sh`
detects the missing image and prints these instructions.

### Step 4 Clone the repo and set up a Python environment

The `venv/` directory is gitignored, so create your own:

```bash
git clone <this-repo> network-automation-project
cd network-automation-project

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 5 Configure secrets

Copy the two `.example` files and fill in real values:

```bash
cp .env.example .env
cp inventory/netbox/docker-compose.override.yml.example \
   inventory/netbox/docker-compose.override.yml
```

Edit `.env`:

```dotenv
NETBOX_URL=http://127.0.0.1:8000
NETBOX_TOKEN=nbt_<id>.<secret>     # filled in after Step 6 below
NORNIR_USERNAME=admin
NORNIR_PASSWORD=admin
```

Edit `inventory/netbox/docker-compose.override.yml`:

- Set `SUPERUSER_PASSWORD` to a real value.
- Generate a 40-character hex token for `SUPERUSER_API_TOKEN` with `openssl rand -hex 20`.

Both files are gitignored. Do not commit them.

### Step 6 Bring up NetBox

The NetBox compose tree is vendored under `inventory/netbox/upstream/`
(pinned to netbox-docker 4.0.2, which deploys NetBox app v4.5).

```bash
cd inventory/netbox
docker compose -f upstream/docker-compose.yml -f docker-compose.override.yml up -d
```

First boot runs ~100 Django migrations and takes about 5 minutes. Watch
progress with:

```bash
docker compose -f upstream/docker-compose.yml -f docker-compose.override.yml logs -f netbox
```

When the container reports healthy:

1. Open <http://127.0.0.1:8000> and log in as `admin` with the password you set.
2. Navigate to **Admin → Users → API Tokens**, find the bootstrap token whose secret matches your `SUPERUSER_API_TOKEN`, and copy the full `nbt_<id>.<secret>` string.
3. Paste that full token into `.env` as `NETBOX_TOKEN`.

### Step 7 Pull the remaining container images

From the repo root with the venv active:

```bash
sudo ./scripts/pull-images.sh
```

This pulls `alpine:latest` and `frrouting/frr:latest`. If `ceos:4.36.0F`
is missing it prints sideload instructions and exits cleanly. Pass
`--dry` to preview without pulling.

### Step 8 Seed NetBox from YAML

```bash
set -a; source .env; set +a                       # export all .env vars
python inventory/netbox/seed.py --dry-run         # parse and plan, no writes
python inventory/netbox/seed.py                   # actually push to NetBox
```

The seeder is idempotent: re-running it converges NetBox state to the
YAML truth in `inventory/netbox/data/`.

### Step 9 Deploy the fabric

```bash
sudo containerlab deploy -t topology/lab.clab.yml
```

```bash
containerlab inspect -t topology/lab.clab.yml
./scripts/lab-verify.sh
```

### Step 10 Run the pipeline

```bash
# Render configurations from NetBox into configs/rendered/
python -m automation.run render

# Run the four offline pre-flight checks
python -m automation.run validate

# Deploy to a single device first to limit blast radius
python -m automation.run deploy --device leaf1 --commit

# Deploy to the rest of the fleet
python -m automation.run deploy --commit

# Verify every BGP neighbor is up and Loopback0 matches NetBox
python -m automation.run verify

# Pull running configs back as goldens (round trip)
python -m automation.run backup
```

`deploy` defaults to dry-run (diff only); `--commit` actually applies.
A successful `verify` ends with all leaves and spines reporting `OK`.

### Step 11 Check the data plane

```bash
# Same-VLAN, cross-leaf (L2 EVPN)
sudo docker exec clab-network-automation-project-server1 ping -c 4 10.100.0.102

# Cross-VLAN, cross-leaf (symmetric IRB, L3 EVPN)
sudo docker exec clab-network-automation-project-server1 ping -c 4 10.101.0.103
```

Both should return 4 / 4 packets. If you got this far, the lab is reproduced.

---

## Optional: reproducing the CI/CD setup

Reproducing GitHub Actions is optional. The pipeline runs on a
self-hosted runner because cEOS images cannot live on GitHub-hosted
runners. If you want CI in your own fork:

1. Install the Actions runner on the same VM (`https://github.com/<your-fork>/settings/actions/runners/new`).
2. Register it with the labels `[self-hosted, linux, clab-lab]`.
3. Add `NETBOX_URL` and `NETBOX_TOKEN` as repository secrets.

The workflow at `.github/workflows/network-ci.yml` runs on every PR.
Without a registered runner it queues indefinitely. The local pipeline
(Step 10 above) works regardless.

---

## Further documentation

- **Final report**: `docs/report/main.pdf`
- **Architecture & design decisions**: `docs/architecture.md`
- **Day-by-day work log**: `docs/journal.md`