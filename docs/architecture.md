# Architecture

## Overview

A 6-device multi-vendor spine-leaf fabric running EVPN-VXLAN, driven
end-to-end by an automation pipeline (NetBox → Jinja2 → Nornir/NAPALM
→ CI/CD). Built entirely in containerlab; no physical gear.

## Current Status

- [x] Phase 1 — Lab foundation: topology boots, 9 containers running
- [x] Phase 2 / Pass 1 — Single spine/leaf underlay BGP verified
- [x] Phase 2 / Pass 2 — Full underlay, all 6 devices, multi-vendor
- [ ] Phase 2 / Pass 3 — EVPN overlay (next session)
- [ ] Phase 2 / Pass 4 — VXLAN + tenant services
- [ ] Phase 3 — NetBox source of truth + Jinja2 templates
- [ ] Phase 4 — Nornir/NAPALM automation + lightweight validation
- [ ] Phase 5 — CI/CD via GitHub Actions (self-hosted runner)
- [ ] Phase 6 — gNMI telemetry + Grafana (single above-and-beyond item)
- [ ] Phase 7 — Report, demo video, polish

## Topology

    +---------+         +---------+
    | spine1  |         | spine2  |
    | AS65001 |         | AS65002 |
    |  cEOS   |         |  cEOS   |
    +----+----+         +----+----+
         |                   |
    -----+-------+------+----+-----
         |       |         |
    +----+----+ +--+---+ +-+------+
    |  leaf1  | |leaf2 | | leaf3  |
    | AS65101 | |65102 | | 65103  |
    |  cEOS   | |cEOS  | | SRL    |
    +----+----+ +--+---+ +-+------+
         |         |        |
     server1   server2   server3
     VLAN100   VLAN100   VLAN101

    edge1 (AS65200, FRR) — single-homed to spine1

## Devices

| Device  | NOS         | ASN   | Role                        |
| ------- | ----------- | ----- | --------------------------- |
| spine1  | Arista cEOS | 65001 | Spine                       |
| spine2  | Arista cEOS | 65002 | Spine                       |
| leaf1   | Arista cEOS | 65101 | Leaf / VTEP (VLAN 100)      |
| leaf2   | Arista cEOS | 65102 | Leaf / VTEP (VLAN 100)      |
| leaf3   | Nokia SRL   | 65103 | Leaf / VTEP (VLAN 101)      |
| edge1   | FRR         | 65200 | Upstream / internet sim     |
| server1 | Alpine      | —     | Host in VLAN 100, Tenant A  |
| server2 | Alpine      | —     | Host in VLAN 100, Tenant A  |
| server3 | Alpine      | —     | Host in VLAN 101, Tenant A  |

## Addressing Plan

### Address Blocks

| Block           | Purpose                                  |
| --------------- | ---------------------------------------- |
| 10.0.0.0/24     | Loopbacks (one /32 per device)           |
| 10.1.0.0/16     | Underlay point-to-point links (/31 each) |
| 10.2.0.0/16     | Edge/upstream connectivity               |
| 10.100.0.0/16   | Tenant A VLAN 100 subnet                 |
| 10.101.0.0/16   | Tenant A VLAN 101 subnet                 |
| 172.20.20.0/24  | containerlab management (auto-assigned)  |

### Loopbacks

| Device  | Loopback     | Purpose                          |
| ------- | ------------ | -------------------------------- |
| spine1  | 10.0.0.1/32  | Router-ID, BGP source            |
| spine2  | 10.0.0.2/32  | Router-ID, BGP source            |
| leaf1   | 10.0.0.11/32 | Router-ID, BGP source, VTEP IP   |
| leaf2   | 10.0.0.12/32 | Router-ID, BGP source, VTEP IP   |
| leaf3   | 10.0.0.13/32 | Router-ID, BGP source, VTEP IP   |
| edge1   | 10.0.0.254/32| Router-ID, BGP source            |

### Underlay Point-to-Point Links (/31)

| Link                          | A-side IP    | Z-side IP    |
| ----------------------------- | ------------ | ------------ |
| spine1 Eth1 ↔ leaf1 Eth1      | 10.1.1.0/31  | 10.1.1.1/31  |
| spine1 Eth2 ↔ leaf2 Eth1      | 10.1.1.2/31  | 10.1.1.3/31  |
| spine1 Eth3 ↔ leaf3 eth-1/1   | 10.1.1.4/31  | 10.1.1.5/31  |
| spine1 Eth4 ↔ edge1 eth1      | 10.2.0.0/31  | 10.2.0.1/31  |
| spine2 Eth1 ↔ leaf1 Eth2      | 10.1.2.0/31  | 10.1.2.1/31  |
| spine2 Eth2 ↔ leaf2 Eth2      | 10.1.2.2/31  | 10.1.2.3/31  |
| spine2 Eth3 ↔ leaf3 eth-1/2   | 10.1.2.4/31  | 10.1.2.5/31  |

### VLAN / VNI / VRF Plan

| VLAN | L2 VNI | L3 VNI | VRF      | Subnet           | Anycast GW   |
| ---- | ------ | ------ | -------- | ---------------- | ------------ |
| 100  | 10100  | 10999  | TENANT_A | 10.100.0.0/24    | 10.100.0.1   |
| 101  | 10101  | 10999  | TENANT_A | 10.101.0.0/24    | 10.101.0.1   |

### Host Addresses

| Host    | Attached To             | VLAN | IP                | Gateway     |
| ------- | ----------------------- | ---- | ----------------- | ----------- |
| server1 | leaf1 Eth3              | 100  | 10.100.0.101/24   | 10.100.0.1  |
| server2 | leaf2 Eth3              | 100  | 10.100.0.102/24   | 10.100.0.1  |
| server3 | leaf3 ethernet-1/3      | 101  | 10.101.0.103/24   | 10.101.0.1  |

## BGP Design

- **Underlay:** eBGP per-link, unique ASN per device
- **Overlay:** eBGP EVPN between every leaf and every spine
  - Session sourced from loopbacks
  - `ebgp-multihop` required (loopback-to-loopback is > 1 hop)
  - Advertises EVPN address-family only
- **No route reflectors** — spines are BGP transit between leaves

## Design Decision: Loopback-Only BGP Advertisements

Each device advertises only its Loopback0 / system0 /32 into BGP. Point-to-point
link subnets (10.1.1.0/31 range, 10.1.2.0/31 range, 10.2.0.0/31) are
intentionally NOT advertised.

### Rationale

- **Alignment with modern EVPN/VXLAN design.** Spine-leaf fabrics source all
  control-plane (BGP, EVPN) and data-plane (VXLAN) traffic from loopbacks.
  p2p interface IPs carry no user traffic and need not be globally reachable.
- **Minimal BGP state.** Advertising p2p /31s scales poorly and adds no
  operational value in an EVPN fabric.
- **Cleaner failure semantics.** A flapping p2p link affects one underlay
  session, not the entire routing table.

### Observable Effect

During Pass 2 verification, pinging a non-loopback destination from edge1
failed:

```
edge1# ping 10.0.0.12
9 packets transmitted, 0 received, 100% packet loss
```

Diagnosis: ping's default source was `10.2.0.1` (primary IP on eth1).
Destination leaf has no route to `10.2.0.0/31`, so return traffic was dropped.

Workaround: source from the loopback (which IS advertised):

```
edge1# ping -I 10.0.0.254 10.0.0.12
4 packets transmitted, 4 packets received, 0% packet loss
```

This is expected behavior for a loopback-based fabric and is retained as
correct design rather than "fixed" by advertising p2p subnets.

## Demo Traffic Stories

1. **server1 → server2** — same VLAN, different leaves, tests EVPN Type-2
   MAC propagation + VXLAN bridging.
2. **server1 → server3** — different VLANs, different vendors (cEOS → SRL),
   tests symmetric IRB routing via L3 VNI 10999.
3. **server1 → 8.8.8.0/24 synthetic** — tests inter-AS route propagation
   from edge1 through the fabric.

## Lessons Learned (rolling)

### FRR RFC 8212 default-deny

FRR 7.0+ enforces RFC 8212: eBGP sessions require explicit inbound AND
outbound route-maps to pass any prefixes. Without them, the session
establishes but all routes are silently filtered. Symptom: `show ip bgp
summary` shows `(Policy)` instead of prefix counts.

Fix: `route-map PERMIT-ALL permit 10` referenced as both in and out policy
on the eBGP neighbor. See `configs/edge1/frr.conf`.

### FRR image version drift

The `frrouting/frr:latest` Docker Hub image is currently version 8.4, not
10.6 (current upstream). For final submission, pin to an explicit tag
(e.g., `quay.io/frrouting/frr:10.6.0`). Tracked as Day 8 cleanup.

### SR Linux CLI: routing policy syntax

`match prefix-set <name>` (flat form, older SRL) is rejected by current SRL
versions. Correct form is nested: `match prefix { prefix-set <name> }`.
When a command fails, SR Linux's error output shows the valid tokens at the
current position — treat that as authoritative over documentation.

### cEOS vs Arista interface naming in containerlab

containerlab link endpoints use Linux-style `eth1`, `eth2`, etc. Inside
cEOS these appear as `Ethernet1`, `Ethernet2`, etc. The mapping is automatic
and correct — no configuration needed on either side.

### Stray `network` statements on cEOS BGP

During hand-configuration of Pass 2, extra `network` statements for p2p /31
subnets ended up in spine2's config (and likely others). These are silently
ignored by cEOS because the prefixes aren't in the device's local RIB, but
they pollute the config and must be cleaned before templating in Phase 3.
Audit and clean scheduled for Day 3 start.