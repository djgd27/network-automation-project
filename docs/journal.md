# Project Journal

*Note: "Day N" entries below are work sessions, not calendar days.
Sessions often span midnight, so a single Day captures continuous
work regardless of clock rollover.*

## 2026-04-23 — Day 1 (Setup)

### Done

- Decided on Ubuntu 24.04 LTS over RHEL 9.7 for the host (containerlab
  ecosystem assumes Ubuntu; less friction).
- Locked in scope: containerlab-only, no physical gear, no VM-based
  NOS, no IPv6, no Batfish, no pyATS (replaced with lightweight Python
  validation + Nornir/NAPALM getters). I do not think I will have enough
  time to implement Batfish/pyATS — could revisit the project in the future.
- Locked in topology: 2 spines + 3 leaves (2 cEOS, 1 SRL) + 1 FRR edge
  + 3 Alpine servers.
- Finalized IPv4 addressing plan (see docs/architecture.md).
- Wrote initial lab.clab.yml.
- Wrote initial edge1 FRR daemons + frr.conf.
- Drew topology diagram in draw.io; exported to PNG/SVG/HTML + source
  .drawio file, all committed.

### Decisions

- Single tenant (TENANT_A) with two VLANs to keep template surface
  manageable. Multi-tenant deferred to "Future Work."
- LICENSE deferred to Day 8.
- Professor's project PDF will NOT be committed (copyright).


## 2026-04-24 — Day 2 (Manual Fabric Configuration)

### Done

- Pulled all container images (cEOS 4.36.0F, SR Linux latest, FRR latest,
  Alpine latest).
- First successful `clab deploy` — all 9 containers up, mgmt IPs assigned.
- Refactored `lab.clab.yml` per best practices: added `group` attributes,
  explicit mgmt network declaration, server `exec:` blocks for auto-IP
  configuration.
- **Pass 1 — Single spine/leaf underlay BGP.** Configured spine1 and
  leaf1 by hand. eBGP session established, loopback-to-loopback ping
  confirmed (10.0.0.1 ↔ 10.0.0.11).
- **Pass 2 — Full underlay, all 6 devices.** Extended to spine2, leaf2,
  leaf3 (SR Linux), edge1 (FRR). All 10 BGP sessions in `Established`
  state. Full-mesh loopback reachability verified from leaf1 and leaf3
  to all 5 other devices.
- Multi-vendor transit verified: leaf1 ↔ leaf3 (cEOS ↔ SRL) works, and
  spine2 ↔ edge1 via leaf transit works.
- Wrote `scripts/capture-golden.sh` with secret scrubbing for cEOS
  (password hashes) and SR Linux (`hashed-password`, `private-key`,
  `psk`, `pre-shared-key` JSON fields). Verified scrubbing works on
  actual captures.
- Established `.gitignore` excluding rendering/runtime state but
  committing golden configs + evidence as first-class artifacts.
- Saved SR Linux startup config via `save startup` (defensive; clab is
  ephemeral anyway).

### Issues resolved

1. **FRR RFC 8212 default-deny.** edge1 BGP session established but
   `PfxRcd 0 / PfxSnt 0` with `(Policy)` marker. Root cause: FRR 7.0+
   requires explicit route-maps on eBGP sessions. Added `route-map
   PERMIT-ALL permit 10` and applied as both `in` and `out` on the
   neighbor. Committed to `configs/edge1/frr.conf` on disk so the fix
   survives clab destroy/deploy.

2. **Loopback-only advertisements → non-loopback source fails.**
   `edge1 ping 10.0.0.12` failed because default source `10.2.0.1`
   isn't in any leaf's BGP table. Diagnosed with `show ip route 10.2.0.1`
   on leaf2 (no specific route). Confirmed this is correct EVPN fabric
   design; documented as a deliberate decision in `docs/architecture.md`.
   Workaround for demos: source pings from loopback (`ping -I 10.0.0.254`).

3. **SR Linux routing-policy syntax.** Initial `match prefix-set loopback`
   rejected by parser. Corrected to nested `match prefix { prefix-set
   loopback }`. Lesson: SRL's error output shows valid tokens at current
   position; trust it.

4. **capture-golden.sh shell quoting bug.** First attempt used a helper
   function that word-split `docker exec "${node}" $cmd` and mangled the
   quotes on `"show running-config"`. Simplified by inlining the docker
   exec call — no helper, no word-splitting issue.

### Decisions

- **Golden configs use stable filenames**, not timestamped. Git provides
  history. Timestamped directories only for per-run evidence captures.
- **Secret scrubbing is mandatory** before commit. Script enforces via
  sed (cEOS) and Python/JSON (SRL).
- **p2p subnets intentionally not advertised in BGP.** See architecture.md
  "Design Decision: Loopback-Only BGP Advertisements."

### Issues / blockers (open)

- [ ] **spine2 has stray `network` statements** for `10.1.1.0/31`,
      `10.1.1.2/31`, `10.1.1.4/31`, `10.2.0.0/31`. These are silently
      ignored by cEOS (prefixes not in RIB) but pollute the config.
      Clean first thing Day 3.
- [ ] **Audit spine1, leaf1, leaf2 for the same stray network statements.**
      Likely present on all three from hand-config muscle memory.
- [ ] Create `configs/edge1/vtysh.conf` to suppress the harmless
      "vtysh.conf not found" warning. Cosmetic — deferred.

### Next session (Day 3)

1. Clean stray `network` statements on spine1, spine2, leaf1, leaf2.
2. Re-capture golden configs after cleanup.
3. **Pass 3 — EVPN overlay.** Enable EVPN address-family on all
   leaf↔spine sessions. Verify EVPN sessions come up with zero routes
   (because no VLANs/VNIs configured yet).
4. **Pass 4 — VXLAN + tenant services.** VRF TENANT_A, VLAN 100 on
   leaf1/2 + VXLAN VNI 10100, VLAN 101 on leaf3 + VXLAN VNI 10101,
   L3 VNI 10999. Anycast gateways. End goal: `server1 ping server2` and
   `server1 ping server3` both work.
5. End of Day 3 target: full manual fabric complete. Golden configs
   captured. Phase 2 done. Phase 3 (NetBox + templates) starts Day 4.



## 2026-04-25 — Day 3 (EVPN Overlay, VXLAN Tenant Services, SR Linux Scope Cut)

### Done

- **Cleanup from Day 2 blockers.** Removed stray `network` statements
  for p2p /31 subnets from spine1, spine2, leaf1, leaf2 BGP configs.
  Re-captured golden configs.
- **Pass 3 — EVPN overlay activation.** Enabled `address-family evpn`
  on all 6 leaf↔spine BGP sessions (3 leaves × 2 spines). All EVPN
  sessions reached `Established` state with zero prefixes — expected,
  since no VLANs/VNIs configured yet.
- **Pass 4.1-4.5 — Initial L2 EVPN buildout (cEOS leaves).**
  - Declared `vrf instance TENANT_A` on leaf1, leaf2, leaf3.
  - VLAN 100 on leaf1 + leaf2, mapped to VNI 10100 via `interface Vxlan1`.
  - VLAN 101 on leaf3 (Nokia SR Linux at this point), mapped to VNI 10101.
  - Anycast gateways: VLAN 100 = `10.100.0.1` MAC `02:1c:73:00:00:64`;
    VLAN 101 = `10.101.0.1` MAC `02:1c:73:00:00:65`.
  - BGP MAC-VRFs declared per VLAN with RD/RT (e.g., `10.0.0.11:10100` /
    `10100:10100` for leaf1 VLAN 100).
  - Verified L2 EVPN: server1 ↔ server2 (cross-leaf, same VLAN, both
    cEOS) reachable via VXLAN — 4/4 ping, ~6-7ms warm path. EVPN Type-2
    MAC-IP routes flowing; Type-3 IMETs visible in spine RIBs with ECMP.
  - Verified server3 ↔ local anycast gateway (10.101.0.1) on SR Linux —
    proves SRL L2 EVPN MAC-VRF + IRB anycast configuration valid.
- **leaf3 migration: Nokia SR Linux → Arista cEOS.** Updated
  `lab.clab.yml` (kind change), `clab destroy && clab deploy`,
  reconfigured leaf3 from scratch as cEOS (loopback, p2p IPs, VLAN 101
  + VNI 10101, anycast gateway, BGP AS 65103, EVPN). Saved as
  `configs/leaf3/startup.cfg`. Re-verified all Phase 2 baselines: 6 EVPN
  sessions Established, 3 IMETs flowing with ECMP, server1↔server2
  still working, server3 reaching local gateway.
- **Pass 4.8 — L3 EVPN symmetric IRB.** All three leaves now bound to
  L3 VNI 10999 via single line `vxlan vrf TENANT_A vni 10999` under
  `interface Vxlan1`. Added `redistribute connected` under `router bgp /
  vrf TENANT_A` on each leaf. cEOS auto-creates dynamic internal VLANs
  (4094 on leaf1/leaf2, 4097 on leaf3) for L3 VNI plumbing. Type-5
  IP-Prefix routes flowing in both directions across all three leaves.
  Each leaf installs remote subnets via VTEP + L3 VNI 10999 + remote
  router-MAC.
- **Server-side gateway fix.** Updated `lab.clab.yml` `exec:` blocks for
  all servers to replace default route with leaf-side anycast gateway via
  `eth1`. `clab destroy && clab deploy` to apply.
- **Demo Story #2 working.** server1 ↔ server3 cross-VLAN, cross-leaf
  symmetric IRB ping: 4/4 both directions. Cold first-packet ~44ms (ARP
  + Type-2 MAC-IP learning + propagation back to source leaf), warm
  ~5-8ms. Steady-state confirmed.
- Saved running configs (`write memory`) on all 5 cEOS devices.
  Captured updated golden configs for spine1, spine2, leaf1, leaf2, leaf3.

### Issues resolved

1. **L3 EVPN cross-vendor friction (cEOS ↔ SR Linux).** Multi-hour
   debugging of L3 EVPN symmetric IRB across cEOS leaf1/leaf2 and SR
   Linux leaf3. Issues encountered: route-target format mismatch
   (`<asn>:<value>` cEOS vs `target:<asn>:<value>` SRL), routing-policy
   syntax dead-ends (incorrect `route-table ip-prefix advertise true`
   path under ip-vrf — only valid for mac-vrf with single-broadcast-domain),
   missing `family evpn` policy statements blocking EVPN exports, and
   suspected RT-constrained route distribution behavior between vendors.
   No clean resolution emerged in the time available. Resolved by scope
   decision (see Decisions below) rather than technical fix.

2. **L3 VNI configuration on cEOS — wrong path attempted first.** Initial
   attempt used manual L3 transit VLAN (VLAN 999 + Vlan999 SVI in VRF +
   `vxlan vlan 999 vni 10999`). cEOS rejected the second VRF binding line
   with `% VNI 10999 is already used to map vlan 999`. Multiple iterations
   tried adding/removing the VLAN 999 stanza without success. Resolved by
   reading Arista's official L3 EVPN lab guide
   (https://labguides.testdrive.arista.com/2025.1/data_center/l3_evpn/),
   which specifies the **single line** `vxlan vrf <VRF> vni <L3_VNI>`
   under Vxlan1 — no transit VLAN needed. cEOS handles internal VLAN
   allocation automatically. Documented in `architecture.md` Lessons
   Learned.

3. **Cross-VLAN ping failed despite healthy control plane.** After all
   leaves had L3 VNI binding and Type-5 routes flowing, server1 → server3
   ping returned 0/4. Diagnosed: `docker exec server1 ip route` showed
   default route via `172.20.20.1` (mgmt network on `eth0`), not via the
   leaf-side anycast gateway. Tenant traffic for unknown destinations
   exited the wrong interface. Resolved by updating server `exec:` blocks
   in `lab.clab.yml` to delete and replace the default route. Fabric was
   never broken — host routing was misconfigured.

### Decisions

- **Drop Nokia SR Linux from leaf layer; standardize on Arista cEOS.**
  Multi-vendor diversity preserved at edge layer (FRR↔cEOS spine1).
  Cross-vendor EVPN leaf interop documented as Future Work. Rationale:
  project timeline (11 days total, ~5-6 days remaining for Phases 3-7)
  cannot absorb unbounded debugging of cross-vendor L3 EVPN compatibility.
  L2 EVPN had been verified working cross-vendor before migration, so
  the principle is demonstrated; the gap is L3-specific configuration
  tuning. Side benefit: uniform cEOS leaf layer simplifies Phase 3
  Jinja2 templating significantly.
- **VLAN/VNI architecture confirmed.** VLAN 100 → VNI 10100 (leaf1, leaf2),
  VLAN 101 → VNI 10101 (leaf3), L3 VNI 10999 in VRF TENANT_A on all leaves.
  No manual L3 transit VLAN — cEOS handles it.
- **Server default routing model.** Servers' default gateway points at
  leaf-side anycast gateway via `eth1`. Connected route to mgmt subnet
  preserved (`scope link`) so `docker exec` and clab management still
  work. Production-equivalent behavior.
- **Self-directed learning is the project thesis.** EVPN-VXLAN, symmetric
  IRB, and the surrounding NetDevOps stack were not covered in course
  material. Every pass began with vendor docs, RFCs, and lab guides
  before any configuration. The iterative, sometimes-circuitous pace
  documented in this journal reflects genuine learning rather than
  recipe-following. Will be emphasized in final report.

### Issues / blockers (open)

- [ ] Update demo video script to reflect the two working demo stories
      (server1↔server2 L2 EVPN, server1↔server3 L3 EVPN symmetric IRB).
      Drop the original cross-vendor narrative.
- [ ] Capture organized evidence dump for report appendix: BGP summaries,
      EVPN route-types (IMET, MAC-IP, IP-Prefix), VRF route tables,
      successful pings. Currently scattered across this session's
      transcript; needs consolidation into `validation/` or `evidence/`.

### Next session (Day 4)

1. Consolidate evidence dump (the open blocker above).
2. **Phase 3 — NetBox source of truth.** Stand up NetBox via Docker.
   Model the fabric: sites, devices, interfaces, IP addresses, VLANs,
   VRFs, BGP ASNs. The uniform cEOS leaf layer (post-SRL drop) makes
   templating significantly cleaner.
3. **Jinja2 templates** rendering against the captured golden cEOS configs
   to validate idempotence (rendered config = golden config, byte-for-byte
   after secret scrubbing).
4. End of Day 4 target: NetBox populated, Jinja2 templates rendering
   identical configs to golden. Phase 3 complete. Phase 4 (Nornir/NAPALM)
   starts Day 5.