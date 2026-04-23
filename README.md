# Network Automation Project

A multi-vendor network automation pipeline built on containerlab,
NetBox, Nornir, and GitHub Actions. Demonstrates NetDevOps /
Network SRE practices: intent-driven configuration, CI-validated
deployments, and streaming telemetry over a spine-leaf EVPN-VXLAN fabric.

Final project for CMPT 423 Network Virtualization (Marist University),
Spring 2026. Authored by David Galindo Delgado.

## Status

🚧 Under active development — final submission May 4, 2026.

## What This Project Is

A proof-of-concept NetDevOps pipeline where:

- **Intent** lives in NetBox (devices, interfaces, IPs, VLANs, VRFs)
- **Rendered configs** are produced by Jinja2 templates per-vendor
- **Deployment** is driven by Nornir + NAPALM
- **Validation** runs pre- and post-deploy
- **CI/CD** (GitHub Actions) runs the full pipeline on every PR
- **Telemetry** streams from devices via gNMI to Prometheus + Grafana

The virtual fabric is a 9-device spine-leaf topology running Arista
cEOS, Nokia SR Linux, and FRR intentionally multi-vendor to
demonstrate vendor-abstracted automation.

## Repository Layout

See `docs/architecture.md` for the topology, addressing plan,
and component overview.

## Quickstart

*(Coming soon — will be finalized during polish phase.)*

## Report and Demo

*(Links to the final report PDF and demo video will go here.)*