# Project Journal

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