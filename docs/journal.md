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



## 2026-04-26 — Day 4 (Phase 3 Kickoff: NetBox Source of Truth)

### Done

- **Vendored netbox-docker 4.0.2** under `inventory/netbox/upstream/`.
  Cloned from upstream, checked out tag `4.0.2`
  (commit `c6cd7ef2de050803b986c17765b8aa54282dbb3e`), removed nested
  `.git/` so the tree is part of this repo's history rather than a
  submodule. Pin recorded in `inventory/netbox/UPSTREAM_VERSION`.
  Resolved app version: NetBox 4.5.8.
- **Wrote local override** (`inventory/netbox/docker-compose.override.yml`)
  publishing port `0.0.0.0:8000:8080` so the UI is reachable from the LAN
  (host IP `10.11.20.20`), bumping the netbox healthcheck `start_period`
  from 90s to 300s, and bootstrapping a superuser via
  `SKIP_SUPERUSER=false` + `SUPERUSER_*` envs.
- **Stack up.** All 5 containers (`netbox`, `netbox-worker`, `postgres`,
  `redis`, `redis-cache`) reach `healthy`. UI returns HTTP 200 from both
  `127.0.0.1:8000` and `10.11.20.20:8000`. `/api/status/` returns valid
  JSON when called with the bootstrap token (`netbox-version: 4.5.8`,
  `rq-workers-running: 1`).
- **Secrets hygiene.** Live override is gitignored under existing rule
  `*.override.yml`; committed `docker-compose.override.yml.example` with
  `CHANGE_ME` placeholders documents the bring-up flow without leaking
  the actual lab credentials. Standard NetDevOps shape and matches how
  netbox-docker themselves ship their `.example`.

### Issues resolved

1. **NetBox container marked unhealthy on first boot.** Root cause: first-
   boot DB migrations (100+ Django migrations across ~18 apps) take ~5
   minutes on this VM, exceeding the upstream healthcheck `start_period`
   of 90s. Compose then refused to start `netbox-worker` because of its
   `depends_on netbox: condition: service_healthy`. Fix: bumped
   `start_period` to 300s in our override; container now reaches
   `healthy` cleanly and the worker starts on the second `up -d`.

2. **API token format change in NetBox 4.x.** First curl against
   `/api/status/` with `Authorization: Token <hex>` returned
   `403 Invalid v1 token`. Root cause: NetBox 4.0+ moved to v2 tokens of
   the form `nbt_<id>.<secret>` and use `Bearer` auth, not `Token`. The
   `SUPERUSER_API_TOKEN` env only seeds the *secret* portion; the `<id>`
   is generated at first boot and printed in the netbox container logs.
   Verified working header is
   `Authorization: Bearer nbt_<id>.<secret>`. Documented in the override
   `.example` file so future-me doesn't trip on it.

### Decisions

- **Vendor netbox-docker rather than submodule or live clone.** Project
  is graded on reproducibility ("Include instructions for replication" —
  Project-1.pdf §5b). Submission is a Brightspace zip; a self-contained
  tree is the strongest reproducibility story. Cost is ~316 KB committed
  to repo — negligible. Bumping upstream is a manual re-clone-and-replace
  per the procedure in `UPSTREAM_VERSION`.
- **Layout: everything NetBox-related under `inventory/netbox/`.**
  `upstream/` (vendored), `UPSTREAM_VERSION` (pin), override (gitignored)
  + `.example` (committed) all in one folder. `data/` (seed YAMLs) and
  `seed.py` will land here in Step 2 so the entire "source of truth"
  surface lives in one place.
- **NetBox is intent-only; no plane connectivity to the fabric.** NetBox
  has no route to the clab management subnet (`172.20.20.0/24`) and
  doesn't need one. The Phase 4 automation runner (Nornir/NAPALM) is the
  only thing that talks to both NetBox API and device mgmt IPs. Keeps
  NetBox on its own docker network, untouched by `clab destroy/deploy`.
- **Bootstrap token is throwaway.** Bootstrap created token ID
  `WTgJ7mEykcFz` (random per first-boot). For Phase 4 will mint a fresh
  named token in the UI (e.g. `automation-runner`) so rotation doesn't
  drag the bootstrap state along. The bootstrap token is only used for
  smoke testing during this session.

### Issues / blockers (open)

- [ ] **No wrapper scripts yet.** `scripts/netbox-up.sh` /
      `netbox-down.sh` to mirror the existing clab wrappers. Deferred so
      the lifecycle stays in one literal `docker compose` command for now;
      mirror the `_lib.sh` style when added.
- [ ] **Phase 5 secret rotation.** Lab-default password (`admin`) and
      bootstrap token secret are in the live override, which is
      gitignored — fine for now. Before any GitHub Actions self-hosted
      runner work, rotate to a different token and store it in GH Secrets
      rather than a committed file.

### Next session

1. **Phase 3 / Step 2 — Seed YAMLs.** Author `inventory/netbox/data/`:
   `sites.yml`, `device-roles.yml`, `device-types.yml`, `devices.yml`,
   `interfaces.yml`, `ips.yml`, `vlans.yml`, `vrfs.yml`. Custom fields
   for BGP ASN, router-id, VTEP IP per `architecture.md` addressing plan.
2. Write `inventory/netbox/seed.py` using `pynetbox` to idempotently push
   the YAML data into NetBox. Run, inspect UI, fix inconsistencies.
3. **Phase 3 / Step 3 — Jinja2 templates** rendering against captured
   golden cEOS configs; goal is byte-equivalence after secret scrubbing.
4. End of Day 5 target: NetBox populated, Jinja2 templates rendering
   byte-equivalent configs. Phase 3 complete; Phase 4 (Nornir/NAPALM
   tasks + lightweight pre-flight validator) starts Day 6.



## 2026-04-27 — Day 5 (Phase 3 / Step 2: Seed YAMLs + Idempotent Seeder)

### Done

- **Authored seed YAMLs under `inventory/netbox/data/`.** Thirteen files
  modeling the full fabric: `custom-fields.yml`, `sites.yml`, `tenants.yml`,
  `manufacturers.yml`, `device-roles.yml`, `device-types.yml`, `vrfs.yml`,
  `vlans.yml`, `prefixes.yml`, `devices.yml`, `interfaces.yml`, `ips.yml`,
  `cables.yml`. Custom fields for `bgp_asn`, `router_id`, `vtep_ip` per the
  `architecture.md` addressing plan.
- **Wrote `inventory/netbox/seed.py`** (idempotent NetBox seeder via
  `pynetbox`). Fourteen ordered stages mirroring the YAML files plus a
  `primary-ips` stage that backfills `device.primary_ip4` after IPs are
  assigned (NetBox can't attach a primary IP before the IP itself exists).
  Behavior: **create-if-absent + update-on-drift**, so re-running is safe
  and converges to YAML truth. Flags: `--dry-run` (parse + plan, no writes)
  and `--stage <name>` / `--from <name>` for iteration during debugging.
- **Ran the seeder against the live NetBox.** Inspected the UI; fabric
  model populated correctly across sites, devices, interfaces, IPs, VLANs,
  VRFs, cables.
- **Captured deployment notes** for the report under `inventory/netbox/`
  documenting the bring-up sequence end-to-end.

### Issues resolved

1. **NetBox 200-char description limit.** Several YAML descriptions
   exceeded NetBox's hard cap and the API rejected the create calls.
   Trimmed wording in the offending YAMLs; documented in the commit
   message so future-me doesn't re-hit it.

2. **Stage ordering matters more than expected.** First seeder draft tried
   to create devices and assign their primary IPs in one pass; failed
   because `primary_ip4` is a foreign key to an IP that doesn't exist
   until interfaces are created and IPs are bound to them. Split into a
   dedicated `primary-ips` stage that runs after `ips`. Same lesson for
   `cables`: terminations reference interfaces, so cables must come last.

### Decisions

- **Idempotent over destructive.** Seeder never deletes; it only creates
  or updates fields that drift from YAML. Means I can re-run after every
  YAML edit without rebuilding NetBox state. Trade-off: removing a device
  from YAML doesn't remove it from NetBox — has to be done in the UI. Fine
  for project scope.
- **Single source of truth lives in YAML, not NetBox.** NetBox is a
  rendered view of the YAML. If they disagree, YAML wins on next seed.
  Reproducibility story: clone the repo, stand up NetBox, run `seed.py`,
  arrive at identical fabric model.

### Next session (Day 6)

1. **Phase 3 / Step 3 — Jinja2 templates.** Render against the captured
   golden cEOS configs; goal is byte-equivalence after secret scrubbing.
2. End-of-Day-6 target: NetBox-driven render pipeline working; Phase 3
   complete; Phase 4 (Nornir/NAPALM) starts next.



## 2026-04-29 — Day 6 (Phase 3 / Step 3: Templates + Render Pipeline)

### Done

- **Wrote `automation/render.py`** (~345 lines). Pulls the fabric from
  NetBox in four bulk API calls (`devices`, `interfaces`, `ip_addresses`,
  `cables`), builds in-memory indexes, then for each device builds a
  context dict, selects a template by `manufacturer + role`, renders, and
  writes `configs/rendered/<host>.cfg`. **No SSH; no device contact** —
  this is a pure NetBox-API → file pipeline. Pushing to nodes is Phase 4.
- **Wrote three Jinja2 templates** under `configs/templates/`:
  `arista/spine.j2`, `arista/leaf.j2`, `frr/edge.j2`. Templates contain
  no addressing or ASN data — every concrete value comes from NetBox via
  the per-device context.
- **Cable graph drives peer discovery.** `compute_peer()` looks up the
  cable terminations in NetBox to derive each P2P link's neighbor name,
  IP, and ASN. Removed any need to hand-author neighbor lists in YAML or
  templates.
- **`--diff` mode** compares each rendered file against the captured
  golden in `configs/<host>/`. Used iteratively during template
  development to drive byte-equivalence.
- **Render results.** All 6 devices render. `spine1` / `spine2` are
  byte-equivalent to goldens (modulo stale SR Linux–era interface names
  in the goldens — render is correct). Leaves diff only on description
  wording.
- **Consolidated `requirements.txt`** to the repo root (was duplicated
  under `inventory/netbox/` and `automation/`). One pinned dependency
  list for the whole project now.
- **Renamed `scripts/capture-golden.sh` → `scripts/save-configs.sh`.**
  Same logic, simpler name; matches how it's referred to in CLAUDE.md
  and the lab-lifecycle docs.

### Issues resolved

1. **Description wording diff between rendered and golden.** Templates
   produce slightly different P2P interface descriptions than what was
   typed by hand on the live boxes (e.g., `p2p to leaf1 Eth1` vs the
   hand-typed phrasing). Decision: **accept render as canonical going
   forward.** Goldens get re-aligned during Phase 4 when Nornir pushes
   the rendered configs back. Chasing byte-equivalence on description
   text is busywork that doesn't validate the pipeline.

2. **SR Linux residue in golden interface names.** Captured goldens for
   the leaf3 cEOS rebuild still showed `ethernet-1/1`–style SRL names in
   places. Render correctly produces `Ethernet1`. Same resolution as
   above — render is canonical.

### Decisions

- **Render is the canonical fabric configuration; goldens are historical
  captures.** From this session forward, any divergence between
  `configs/rendered/<host>.cfg` and `configs/<host>/startup.cfg` is
  resolved in favor of render.
- **Pipeline is the deliverable.** The grading rubric values the
  reproducibility of the NetBox → Jinja2 → Nornir flow over hand-tuned
  per-device byte-equivalence. Time spent on cosmetic diffs is time not
  spent on Phase 4.
- **No SR Linux template.** With leaf3 standardized to cEOS in Day 3,
  only `arista/` and `frr/` template trees are needed. The
  `manufacturer + role` selector in `render.py` keeps the door open if
  SR Linux comes back as Future Work.

### Next session (Day 7)

1. Close the open blockers above (phantom interfaces, working-tree
   drift).
2. **Phase 4 — Nornir/NAPALM.** Inventory pulled from NetBox.
   `tasks/deploy.py` using NAPALM `load_merge_candidate` +
   `compare_config` + `commit_config`. Verify tasks via
   `get_bgp_neighbors` / `get_interfaces_ip`. Pre-flight validator
   (`automation/validate.py`, ~150 lines: duplicate IPs, ASN
   consistency, undefined VLANs).
3. End-to-end rehearsal: `clab destroy && clab deploy`, run Nornir
   deploy, run Nornir verify. Target: "all green."