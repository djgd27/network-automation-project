# Architecture

## Overview

A 6-device multi-vendor spine-leaf fabric running EVPN-VXLAN, driven
end-to-end by an automation pipeline (NetBox → Jinja2 → Nornir/NAPALM
→ CI/CD). Built entirely in containerlab; no physical gear.

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

## Demo Traffic Stories

1. **server1 → server2** — same VLAN, different leaves, tests EVPN
   Type-2 MAC propagation + VXLAN bridging.
2. **server1 → server3** — different VLANs, different vendors (cEOS → SRL),
   tests symmetric IRB routing via L3 VNI 10999.
3. **server1 → 8.8.8.0/24 synthetic** — tests inter-AS route propagation
   from edge1 through the fabric.