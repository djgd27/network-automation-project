#!/usr/bin/env python3
"""
Offline pre-flight validator for rendered configs.

Runs four checks across configs/rendered/*.cfg, with an optional NetBox
cross-check when NETBOX_TOKEN is set:

  1. Duplicate IPs across devices (anycast `ip address virtual` exempt).
  2. Local BGP ASN in `router bgp <asn>` matches NetBox `bgp_asn` custom
     field for that device.
  3. Each `neighbor <ip> remote-as <asn>` references the ASN that the
     IP-owning device is actually configured with.
  4. Every `switchport access vlan <vid>` references a `vlan <vid>` that
     is declared in the same file.

No SSH, no device contact. Designed to run in CI before any deploy.

    NETBOX_URL     default: http://127.0.0.1:8000
    NETBOX_TOKEN   optional (enables check #2)

    ./validate.py            run all checks, exit 1 on any failure
    ./validate.py --quiet    suppress per-check OK lines
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERED_DIR = REPO_ROOT / "configs" / "rendered"

# cEOS uses 3-space indent inside `interface` blocks; FRR uses a single
# space. Both styles produce the same `ip address <cidr>` token shape, so
# the regexes below are intentionally indent-agnostic.
RE_HOSTNAME = re.compile(r"^\s*hostname\s+(\S+)", re.MULTILINE)
RE_BGP_ASN = re.compile(r"^\s*router\s+bgp\s+(\d+)", re.MULTILINE)
RE_INTERFACE = re.compile(r"^\s*interface\s+(\S+)\s*$", re.MULTILINE)
RE_IP_ADDR = re.compile(r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s*$")
RE_IP_VIRTUAL = re.compile(r"^\s+ip\s+address\s+virtual\s+(\d+\.\d+\.\d+\.\d+)/(\d+)")
RE_NEIGHBOR_AS = re.compile(
    r"^\s+neighbor\s+(\d+\.\d+\.\d+\.\d+)\s+remote-as\s+(\d+)\s*$",
    re.MULTILINE,
)
RE_VLAN_DECL = re.compile(r"^\s*vlan\s+(\d+)\s*$", re.MULTILINE)
RE_ACCESS_VLAN = re.compile(r"^\s+switchport\s+access\s+vlan\s+(\d+)")


@dataclass
class Parsed:
    host: str
    path: Path
    bgp_asn: int | None = None
    # iface -> list[(ip, prefixlen)]; physical addresses only, anycast excluded
    ip_by_iface: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    anycast_ips: set[str] = field(default_factory=set)
    # list of (neighbor_ip, remote_asn)
    bgp_peers: list[tuple[str, int]] = field(default_factory=list)
    declared_vlans: set[int] = field(default_factory=set)
    # iface -> vid referenced via `switchport access vlan`
    access_vlans: dict[str, int] = field(default_factory=dict)


@dataclass
class Finding:
    host: str
    check: str
    message: str


def parse_config(path: Path) -> Parsed:
    text = path.read_text()
    host_m = RE_HOSTNAME.search(text)
    host = host_m.group(1) if host_m else path.stem

    p = Parsed(host=host, path=path)

    asn_m = RE_BGP_ASN.search(text)
    if asn_m:
        p.bgp_asn = int(asn_m.group(1))

    p.bgp_peers = [(ip, int(asn)) for ip, asn in RE_NEIGHBOR_AS.findall(text)]
    p.declared_vlans = {int(v) for v in RE_VLAN_DECL.findall(text)}

    # walk line-by-line to keep an "inside which interface" cursor — this
    # is what binds `ip address` / `switchport access vlan` to the right
    # interface name.
    current: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("!"):
            current = None
            continue
        m = RE_INTERFACE.match(line)
        if m:
            current = m.group(1)
            p.ip_by_iface.setdefault(current, [])
            continue
        if current is None:
            continue
        m = RE_IP_ADDR.match(line)
        if m:
            p.ip_by_iface[current].append((m.group(1), int(m.group(2))))
            continue
        m = RE_IP_VIRTUAL.match(line)
        if m:
            p.anycast_ips.add(m.group(1))
            continue
        m = RE_ACCESS_VLAN.match(line)
        if m:
            p.access_vlans[current] = int(m.group(1))

    return p


# ----------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------

def check_duplicate_ips(parsed: list[Parsed]) -> list[Finding]:
    seen: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for p in parsed:
        for iface, addrs in p.ip_by_iface.items():
            for ip, _ in addrs:
                seen[ip].append((p.host, iface))
    findings: list[Finding] = []
    for ip, owners in seen.items():
        if len(owners) > 1:
            owners_str = ", ".join(f"{h}:{i}" for h, i in owners)
            findings.append(Finding(
                host="<global>",
                check="duplicate-ip",
                message=f"{ip} configured on multiple interfaces: {owners_str}",
            ))
    return findings


def check_local_asn_vs_netbox(
    parsed: list[Parsed],
    netbox_asn: dict[str, int],
) -> list[Finding]:
    findings: list[Finding] = []
    for p in parsed:
        expected = netbox_asn.get(p.host)
        if expected is None:
            continue  # device not in NetBox (e.g. edge1 if filtered)
        if p.bgp_asn is None:
            findings.append(Finding(
                p.host, "local-asn",
                f"NetBox has bgp_asn={expected} but rendered config has no `router bgp` line",
            ))
            continue
        if p.bgp_asn != expected:
            findings.append(Finding(
                p.host, "local-asn",
                f"local ASN drift: rendered={p.bgp_asn}, NetBox={expected}",
            ))
    return findings


def check_peer_asns(parsed: list[Parsed]) -> list[Finding]:
    # build IP -> (host, local_asn) map across all rendered devices
    ip_owner: dict[str, tuple[str, int | None]] = {}
    for p in parsed:
        for addrs in p.ip_by_iface.values():
            for ip, _ in addrs:
                ip_owner[ip] = (p.host, p.bgp_asn)

    findings: list[Finding] = []
    for p in parsed:
        for peer_ip, claimed_asn in p.bgp_peers:
            owner = ip_owner.get(peer_ip)
            if owner is None:
                findings.append(Finding(
                    p.host, "peer-asn",
                    f"neighbor {peer_ip} remote-as {claimed_asn} — no rendered "
                    f"device owns {peer_ip}",
                ))
                continue
            owner_host, owner_asn = owner
            if owner_asn is None:
                continue
            if owner_asn != claimed_asn:
                findings.append(Finding(
                    p.host, "peer-asn",
                    f"neighbor {peer_ip} remote-as {claimed_asn} but {owner_host} "
                    f"is configured with router bgp {owner_asn}",
                ))
    return findings


def check_undefined_vlans(parsed: list[Parsed]) -> list[Finding]:
    findings: list[Finding] = []
    for p in parsed:
        for iface, vid in p.access_vlans.items():
            if vid not in p.declared_vlans:
                findings.append(Finding(
                    p.host, "undefined-vlan",
                    f"{iface} switchport access vlan {vid} but vlan {vid} is "
                    f"not declared in this config",
                ))
    return findings


# ----------------------------------------------------------------------
# entrypoint
# ----------------------------------------------------------------------

def fetch_netbox_asns(url: str, token: str) -> dict[str, int]:
    import pynetbox
    nb = pynetbox.api(url, token=token)
    nb.status()  # fail fast if unreachable
    out: dict[str, int] = {}
    for d in nb.dcim.devices.all():
        asn = (d.custom_fields or {}).get("bgp_asn")
        if asn is not None:
            out[d.name] = int(asn)
    return out


def report(findings: list[Finding], check: str, quiet: bool) -> None:
    bucket = [f for f in findings if f.check == check]
    if not bucket:
        if not quiet:
            print(f"  OK  {check}")
        return
    print(f"  FAIL  {check}  ({len(bucket)} finding{'s' if len(bucket) > 1 else ''})")
    for f in bucket:
        print(f"        [{f.host}] {f.message}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--quiet", action="store_true", help="suppress per-check OK lines")
    args = ap.parse_args()

    if not RENDERED_DIR.is_dir():
        print(f"ERROR: {RENDERED_DIR} does not exist — run render.py first", file=sys.stderr)
        return 2

    cfgs = sorted(RENDERED_DIR.glob("*.cfg"))
    if not cfgs:
        print(f"ERROR: no rendered configs found in {RENDERED_DIR}", file=sys.stderr)
        return 2

    parsed = [parse_config(c) for c in cfgs]
    print(f"Validating {len(parsed)} rendered config(s) from {RENDERED_DIR.relative_to(REPO_ROOT)}")

    findings: list[Finding] = []
    findings += check_duplicate_ips(parsed)
    findings += check_peer_asns(parsed)
    findings += check_undefined_vlans(parsed)

    netbox_asn: dict[str, int] = {}
    token = os.environ.get("NETBOX_TOKEN")
    if token:
        url = os.environ.get("NETBOX_URL", "http://127.0.0.1:8000")
        try:
            netbox_asn = fetch_netbox_asns(url, token)
        except Exception as e:
            print(f"WARN: NetBox cross-check skipped — {e}", file=sys.stderr)
        else:
            findings += check_local_asn_vs_netbox(parsed, netbox_asn)
    else:
        print("NOTE: NETBOX_TOKEN not set — skipping local-asn cross-check")

    print()
    report(findings, "duplicate-ip", args.quiet)
    report(findings, "peer-asn", args.quiet)
    report(findings, "undefined-vlan", args.quiet)
    if netbox_asn:
        report(findings, "local-asn", args.quiet)

    print()
    if findings:
        print(f"FAIL — {len(findings)} finding(s) across {len({f.check for f in findings})} check(s)")
        return 1
    print(f"OK — {len(parsed)} configs, all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
