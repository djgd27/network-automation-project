# Architecture

## Overview

A 6-device multi-vendor spine-leaf fabric running EVPN-VXLAN, driven
end-to-end by an automation pipeline (NetBox → Jinja2 → Nornir/NAPALM
→ CI/CD). Built entirely in containerlab; no physical gear.

## Current Status

- [x] Phase 1 — Lab foundation: topology boots, 9 containers running
- [x] Phase 2 / Pass 1 — Single spine/leaf underlay BGP verified
- [x] Phase 2 / Pass 2 — Full underlay, all 6 devices, multi-vendor
- [x] Phase 2 / Pass 3 — EVPN overlay (next session)
- [x] Phase 2 / Pass 4 — VXLAN + tenant services
- [x] Phase 3 / Step 1 — NetBox stood up (netbox-docker 4.0.2 vendored)
- [x] Phase 3 / Step 2 — Seed YAMLs + `seed.py` populate fabric model in NetBox
- [x] Phase 3 / Step 3 — Jinja2 templates render via `automation/render.py`
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
    |  cEOS   | |cEOS  | | cEOS   |
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
| leaf3   | Arista cEOS | 65103 | Leaf / VTEP (VLAN 101)      |
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
| spine1 Eth3 ↔ leaf3 Eth1      | 10.1.1.4/31  | 10.1.1.5/31  |
| spine1 Eth4 ↔ edge1 eth1      | 10.2.0.0/31  | 10.2.0.1/31  |
| spine2 Eth1 ↔ leaf1 Eth2      | 10.1.2.0/31  | 10.1.2.1/31  |
| spine2 Eth2 ↔ leaf2 Eth2      | 10.1.2.2/31  | 10.1.2.3/31  |
| spine2 Eth3 ↔ leaf3 Eth2      | 10.1.2.4/31  | 10.1.2.5/31  |

### VLAN / VNI / VRF Plan

| VLAN | Type                       | L2 VNI | VRF      | Subnet           | Anycast GW   | Where        |
| ---- | -------------------------- | ------ | -------- | ---------------- | ------------ | ------------ |
| 100  | Tenant access              | 10100  | TENANT_A | 10.100.0.0/24    | 10.100.0.1   | leaf1, leaf2 |
| 101  | Tenant access              | 10101  | TENANT_A | 10.101.0.0/24    | 10.101.0.1   | leaf3        |

**L3 VNI binding (cEOS).** VRF TENANT_A is bound to L3 VNI 10999 via
`vxlan vrf TENANT_A vni 10999` under `interface Vxlan1` on each leaf.
cEOS auto-creates an internal dynamic VLAN (e.g., 4094, 4097) for L3 VNI
plumbing — this VLAN is not user-configurable, does not appear in
`show running-config`, and exists only as data-plane internal state.
This binding enables symmetric IRB routing between VLAN 100 and VLAN 101
across leaves.

### Host Addresses

| Host    | Attached To        | VLAN | IP                | Gateway     |
| ------- | ------------------ | ---- | ----------------- | ----------- |
| server1 | leaf1 Eth3         | 100  | 10.100.0.101/24   | 10.100.0.1  |
| server2 | leaf2 Eth3         | 100  | 10.100.0.102/24   | 10.100.0.1  |
| server3 | leaf3 Eth3         | 101  | 10.101.0.103/24   | 10.101.0.1  |

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

```console
edge1# ping 10.0.0.12
9 packets transmitted, 0 received, 100% packet loss
```

Diagnosis: ping's default source was `10.2.0.1` (primary IP on eth1).
Destination leaf has no route to `10.2.0.0/31`, so return traffic was dropped.

Workaround: source from the loopback (which IS advertised):

```console
edge1# ping -I 10.0.0.254 10.0.0.12
4 packets transmitted, 4 packets received, 0% packet loss
```

This is expected behavior for a loopback-based fabric and is retained as
correct design rather than "fixed" by advertising p2p subnets.

## Demo Traffic Stories

1. **server1 → server2** — same VLAN, different leaves, tests EVPN Type-2
   MAC propagation + VXLAN bridging (L2 EVPN).
2. **server1 → server3** — different VLANs, different leaves, tests symmetric
   IRB routing via L3 VNI 10999 with EVPN Type-5 IP-Prefix advertisement
   (L3 EVPN). Cross-VLAN traffic enters local anycast gateway, is routed
   into VRF TENANT_A, encapsulated in VXLAN with L3 VNI, decapsulated and
   routed at the destination leaf to the local subnet.
3. **server1 → 8.8.8.0/24 synthetic** — tests inter-AS route propagation
   from edge1 (FRR, AS65200) through the cEOS fabric.

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

### L3 VNI on cEOS — minimal binding, no transit VLAN needed

Initial attempts at L3 EVPN symmetric IRB on cEOS used a manual transit VLAN
(VLAN 999 + Vlan999 SVI in VRF + `vxlan vlan 999 vni 10999`). cEOS rejected
this with `% VNI 10999 is already used to map vlan 999` when also trying to
add `vxlan vrf TENANT_A vni 10999`.

The Arista official L3 EVPN lab guide
(https://labguides.testdrive.arista.com/2025.1/data_center/l3_evpn/) is
authoritative: the **only** Vxlan1 line needed for L3 service is
`vxlan vrf <VRF> vni <L3_VNI>`. cEOS auto-creates a dynamic internal VLAN
(visible only in `show vxlan vni` operational state, not in running-config)
to anchor the L3 VNI in the data plane. The user never configures or sees
this VLAN.

Combined with `redistribute connected` under `router bgp / vrf <VRF>`,
this is sufficient to:

- Generate Type-5 IP-Prefix routes for connected subnets
- Receive Type-5 routes carrying matching RT and install them in VRF RIB
- Forward routed traffic via VXLAN with the L3 VNI

Lesson: vendor lab guides beat blog posts and stale documentation. When in
doubt, find the official walkthrough and follow it literally.

### Server default gateway in containerlab

containerlab Alpine server containers have two interfaces: `eth0` (mgmt
network, default gateway via `172.20.20.1`) and `eth1` (data plane, attached
to leaf access port). By default, the kernel's default route points at the
mgmt gateway. This breaks tenant cross-subnet traffic: packets for unknown
destinations exit `eth0` to the mgmt bridge instead of `eth1` to the leaf.

Symptom: cross-VLAN ping fails 100% even though all EVPN routes are
correctly installed and BGP control plane is healthy.

Fix: in `lab.clab.yml` under each server's `exec:` block, replace the
default route to point at the leaf-side anycast gateway via `eth1`:

```yaml
exec:
  - ip route del default
  - ip route add default via 10.100.0.1 dev eth1
```

This makes the leaf's anycast gateway the host's default — production
behavior. The connected route to `172.20.20.0/24` (scope link) is preserved,
so `docker exec` and clab management still work over the mgmt side-channel.

Lesson: a healthy fabric control plane is necessary but not sufficient.
End-to-end connectivity requires the host's routing table to actually
direct traffic to the fabric.

### Vendor selection rationale and SR Linux scope reduction

Initial design included Nokia SR Linux as leaf3 to demonstrate multi-vendor
EVPN interoperability at the leaf layer. L2 EVPN configuration completed
successfully (server3 reaching local anycast gateway via SR Linux MAC-VRF).
However, L3 EVPN cross-vendor symmetric IRB (cEOS leaf1/leaf2 ↔ SR Linux
leaf3) introduced multiple compatibility frictions:

- **Route-target format mismatch.** cEOS naturally emits RTs as
  `<asn>:<value>` (e.g., `10999:10999`). SR Linux defaults to
  `target:<asn>:<value>` form. Cross-vendor RT matching requires
  vendor-specific knobs and explicit policy.
- **Routing-policy syntax learning curve.** SR Linux's policy framework
  diverges significantly from Arista/Cisco conventions, requiring nested
  `match prefix { prefix-set <name> }` syntax and explicit `family evpn`
  policy statements.
- **Type-5 advertisement gating.** SR Linux requires explicit
  `route-table ip-prefix advertise` only under specific service contexts
  (mac-vrf with single-broadcast-domain), not under ip-vrf as initially
  attempted.

Given the project's timeline and the priority of completing the full
automation pipeline (Phases 3-7: NetBox, Nornir/NAPALM, CI/CD, telemetry),
leaf3 was migrated to Arista cEOS to standardize the leaf layer.
Multi-vendor diversity is preserved at the **edge layer**: edge1 runs FRR
(AS65200) peering eBGP with cEOS spine1.

Cross-vendor EVPN leaf-layer interoperability is documented in Future Work
as a follow-on extension. The L2 EVPN work completed on SR Linux (verified
working before migration) demonstrates the pattern applies cross-vendor;
the gap is L3 EVPN-specific configuration tuning.

### Self-directed learning of EVPN-VXLAN

The course curriculum did not cover EVPN-VXLAN, symmetric IRB, NetBox-driven
automation, Nornir/NAPALM, GitHub Actions for network CI/CD, or gNMIc
streaming telemetry. These technologies were selected specifically because
they represent current production data-center fabric practice.

This project is therefore as much a self-teaching exercise as an
implementation. Each phase began with reading vendor documentation, RFCs,
and reference lab guides before any configuration was written. Trial and
error against the live containerlab fabric, including the blind alleys
documented in this Lessons Learned section, was the primary learning
mechanism. This is reflected in the iterative pace: passes within Phase 2
were not pre-planned with confidence but discovered as understanding deepened.

The artifact this produces is more valuable for being self-built. A
copied-from-tutorial fabric does not reveal which configuration lines
matter and which are vendor noise; this one does, because every line was
fought for.

## Future Work

The following items are intentionally out of scope for the project deadline
but represent natural extensions of the current build:

- **Cross-vendor EVPN leaf interop.** Re-introduce Nokia SR Linux as a
  fourth leaf and resolve cEOS↔SRL L3 EVPN symmetric IRB compatibility:
  RT format normalization, vendor-specific policy alignment, and Type-5
  reception under SRL ip-vrf. L2 EVPN cross-vendor was verified working
  during initial buildout.
- **Multi-tenant overlay.** Add TENANT_B with its own VRF, L3 VNI, and
  VLAN/subnet allocation. Validate route-target import/export isolation
  between tenants.
- **IPv6 underlay and overlay.** Current build is IPv4-only. EVPN supports
  Type-5 IPv6 prefixes; underlay can run BGP unnumbered or IPv6 LLA peering.
- **Batfish / pyATS validation.** Replace the lightweight Python pre-flight
  validator (Phase 4) with a full Batfish reachability and policy analysis
  pass and pyATS testbed-driven verification suite. Out of scope due to
  setup overhead vs. project timeline.
- **MLAG / multi-homing.** Current servers are single-homed to one leaf.
  Production fabrics use ESI-LAG (EVPN multi-homing) or MLAG for redundant
  host attachment. Adds Type-1 (Ethernet Auto-Discovery) and Type-4
  (Ethernet Segment) routes to the EVPN control plane.
- **Anycast RP / multicast overlay.** EVPN supports L2/L3 multicast via
  Selective Multicast Ethernet Tag (SMET) routes. Out of scope.
- **Production-grade FRR pinning.** edge1 currently uses
  `frrouting/frr:latest` (resolves to 8.4). Pin to an explicit upstream tag
  (`quay.io/frrouting/frr:10.6.0` or equivalent) for reproducibility.