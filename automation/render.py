#!/usr/bin/env python3
"""
Render device configs from NetBox via Jinja2 templates.

Pulls the fabric model from NetBox in batched calls, builds a per-device
context, selects a template by manufacturer + role, renders, and writes
to configs/rendered/<hostname>.cfg.

    NETBOX_URL     default: http://127.0.0.1:8000
    NETBOX_TOKEN   required

    ./render.py                       render all devices
    ./render.py --device leaf1        render one device
    ./render.py --diff                diff each rendered file vs configs/<host>/...
    ./render.py --device leaf1 --diff
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pynetbox
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "configs" / "templates"
OUTPUT_DIR = REPO_ROOT / "configs" / "rendered"
GOLDEN_DIR = REPO_ROOT / "configs"

GOLDEN_FILE = {
    "arista": "startup.cfg",
    "frrouting": "frr.conf",
}
TEMPLATE_DIR_BY_MFR = {
    "arista": "arista",
    "frrouting": "frr",
}

L3_VNI = 10999
L2_VNI_BASE = 10000


# ----------------------------------------------------------------------
# fetch + index
# ----------------------------------------------------------------------

def fetch_fabric(nb) -> dict[str, Any]:
    """One read-only sweep of NetBox; everything else is local lookups."""
    devices = list(nb.dcim.devices.all())
    interfaces = list(nb.dcim.interfaces.all())
    ips = list(nb.ipam.ip_addresses.all())
    cables = list(nb.dcim.cables.all())

    iface_by_dev: dict[int, list] = defaultdict(list)
    for i in interfaces:
        iface_by_dev[i.device.id].append(i)

    ip_by_iface: dict[int, list] = defaultdict(list)
    for ip in ips:
        if ip.assigned_object_type == "dcim.interface":
            ip_by_iface[ip.assigned_object_id].append(ip)

    cable_neighbor: dict[int, int] = {}
    for c in cables:
        if not c.a_terminations or not c.b_terminations:
            continue
        a_id = c.a_terminations[0].object_id
        b_id = c.b_terminations[0].object_id
        cable_neighbor[a_id] = b_id
        cable_neighbor[b_id] = a_id

    return {
        "devices": devices,
        "iface_by_dev": iface_by_dev,
        "iface_by_id": {i.id: i for i in interfaces},
        "ip_by_iface": ip_by_iface,
        "cable_neighbor": cable_neighbor,
        "device_by_id": {d.id: d for d in devices},
    }


# ----------------------------------------------------------------------
# context builder
# ----------------------------------------------------------------------

_IFACE_PREFIX_ORDER = {"Ethernet": 0, "eth": 0, "Loopback": 1, "lo": 1, "Vlan": 2, "Vxlan": 3}
_IFACE_RE = re.compile(r"^([A-Za-z]+)(\d.*)?$")


def iface_sort_key(name: str) -> tuple[int, int, str]:
    m = _IFACE_RE.match(name)
    if not m:
        return (9, 0, name)
    prefix, suffix = m.group(1), m.group(2) or "0"
    order = _IFACE_PREFIX_ORDER.get(prefix, 9)
    try:
        return (order, int(suffix), name)
    except ValueError:
        return (order, 0, name)


def classify(iface) -> str:
    name = iface.name
    if name.startswith("Loopback") or name == "lo":
        return "loopback"
    if name.startswith("Vlan"):
        return "svi"
    if name.startswith("Vxlan"):
        return "vxlan"
    mode = getattr(iface, "mode", None)
    if mode is not None and getattr(mode, "value", None) == "access":
        return "access"
    if name.startswith(("Ethernet", "eth")):
        return "p2p"
    return "other"


def compute_peer(iface, fabric) -> dict[str, Any] | None:
    peer_id = fabric["cable_neighbor"].get(iface.id)
    if not peer_id:
        return None
    peer_iface = fabric["iface_by_id"][peer_id]
    peer_dev = fabric["device_by_id"][peer_iface.device.id]
    peer_ips = fabric["ip_by_iface"].get(peer_id, [])
    peer_ip = peer_ips[0].address.split("/")[0] if peer_ips else None
    peer_asn = (peer_dev.custom_fields or {}).get("bgp_asn")
    role_slug = peer_dev.role.slug
    return {
        "ip": peer_ip,
        "asn": peer_asn,
        "name": peer_dev.name,
        "iface": peer_iface.name,
        "role": role_slug,
        "is_fabric": role_slug in ("spine", "leaf"),
    }


def build_context(device, fabric) -> dict[str, Any]:
    asn = (device.custom_fields or {}).get("bgp_asn")
    primary = device.primary_ip4
    router_id = primary.address.split("/")[0] if primary else None

    raw_ifaces = sorted(
        fabric["iface_by_dev"].get(device.id, []),
        key=lambda i: iface_sort_key(i.name),
    )

    interfaces: list[dict[str, Any]] = []
    neighbors: list[dict[str, Any]] = []
    vlans: dict[int, dict[str, Any]] = {}
    anycast_vids: set[int] = set()
    has_vrf = False

    for iface in raw_ifaces:
        if iface.mgmt_only:
            continue
        kind = classify(iface)
        ips = fabric["ip_by_iface"].get(iface.id, [])
        ip = ips[0] if ips else None
        ip_addr = ip.address if ip else None
        ip_role = (ip.role.value if ip and ip.role else None) if ip else None

        peer = compute_peer(iface, fabric) if kind == "p2p" else None
        if peer and peer["ip"]:
            neighbors.append(peer)

        rec = {
            "name": iface.name,
            "kind": kind,
            "description": iface.description or "",
            "ip_address": ip_addr,
            "ip_role": ip_role,
            "vrf": iface.vrf.name if iface.vrf else None,
            "untagged_vlan": iface.untagged_vlan.vid if iface.untagged_vlan else None,
            "untagged_vlan_name": iface.untagged_vlan.name if iface.untagged_vlan else None,
            "peer": peer,
        }
        interfaces.append(rec)

        if iface.untagged_vlan:
            v = iface.untagged_vlan
            vlans.setdefault(v.vid, {"vid": v.vid, "name": v.name, "vni": L2_VNI_BASE + v.vid})

        if kind == "svi" and iface.name.startswith("Vlan"):
            try:
                svi_vid = int(iface.name[len("Vlan"):])
            except ValueError:
                svi_vid = None
            if svi_vid is not None:
                vlans.setdefault(svi_vid, {
                    "vid": svi_vid,
                    "name": f"TENANT_A_VLAN{svi_vid}",
                    "vni": L2_VNI_BASE + svi_vid,
                })
                if ip_role == "anycast":
                    anycast_vids.add(svi_vid)

        if iface.vrf and iface.vrf.name == "TENANT_A":
            has_vrf = True

    return {
        "hostname": device.name,
        "role": device.role.slug,
        "manufacturer": device.device_type.manufacturer.slug,
        "asn": asn,
        "router_id": router_id,
        "interfaces": interfaces,
        "neighbors": neighbors,
        "vlans": sorted(vlans.values(), key=lambda v: v["vid"]),
        "anycast_vids": sorted(anycast_vids),
        "has_vrf_tenant_a": has_vrf,
        "vrf_name": "TENANT_A" if has_vrf else None,
        "l3_vni": L3_VNI,
    }


# ----------------------------------------------------------------------
# render + write + diff
# ----------------------------------------------------------------------

def short_iface(name: str) -> str:
    """Ethernet1 → Eth1; ethernet-1/1 → ethernet-1/1; everything else unchanged."""
    return name.replace("Ethernet", "Eth", 1) if name.startswith("Ethernet") else name


def anycast_mac(vid: int) -> str:
    return f"02:1c:73:00:00:{vid:02x}"


def make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["short_iface"] = short_iface
    env.filters["anycast_mac"] = anycast_mac
    return env


def select_template(env: Environment, manufacturer: str, role: str):
    sub = TEMPLATE_DIR_BY_MFR.get(manufacturer, manufacturer)
    return env.get_template(f"{sub}/{role}.j2")


def render_device(device, fabric, env) -> str:
    ctx = build_context(device, fabric)
    template = select_template(env, ctx["manufacturer"], ctx["role"])
    return template.render(**ctx)


def write_rendered(name: str, content: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{name}.cfg"
    out.write_text(content)
    return out


def show_diff(device) -> int:
    mfr = device.device_type.manufacturer.slug
    rendered_path = OUTPUT_DIR / f"{device.name}.cfg"
    golden_path = GOLDEN_DIR / device.name / GOLDEN_FILE.get(mfr, "startup.cfg")
    if not golden_path.exists():
        print(f"  (no golden at {golden_path.relative_to(REPO_ROOT)})")
        return 0
    golden = golden_path.read_text().splitlines(keepends=True)
    rendered = rendered_path.read_text().splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        golden, rendered,
        fromfile=str(golden_path.relative_to(REPO_ROOT)),
        tofile=str(rendered_path.relative_to(REPO_ROOT)),
    ))
    if not diff:
        print(f"  byte-equivalent to golden")
        return 0
    sys.stdout.writelines(diff)
    if not diff[-1].endswith("\n"):
        sys.stdout.write("\n")
    return len(diff)


# ----------------------------------------------------------------------
# entrypoint
# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--device", help="render only this device")
    ap.add_argument("--diff", action="store_true", help="diff rendered vs configs/<host>/...")
    args = ap.parse_args()

    url = os.environ.get("NETBOX_URL", "http://127.0.0.1:8000")
    token = os.environ.get("NETBOX_TOKEN")
    if not token:
        print("ERROR: NETBOX_TOKEN not set", file=sys.stderr)
        return 2

    nb = pynetbox.api(url, token=token)
    try:
        status = nb.status()
    except Exception as e:
        print(f"ERROR: cannot reach NetBox at {url}: {e}", file=sys.stderr)
        return 2
    print(f"NetBox {status.get('netbox-version')} at {url}")

    fabric = fetch_fabric(nb)
    env = make_env()

    targets = fabric["devices"]
    if args.device:
        targets = [d for d in targets if d.name == args.device]
        if not targets:
            print(f"ERROR: no device named {args.device!r} in NetBox", file=sys.stderr)
            return 2

    print()
    for device in targets:
        try:
            content = render_device(device, fabric, env)
        except Exception as e:
            print(f"== {device.name} ==  RENDER FAILED: {e}", file=sys.stderr)
            continue
        out = write_rendered(device.name, content)
        print(f"== {device.name} ==  -> {out.relative_to(REPO_ROOT)}")
        if args.diff:
            show_diff(device)
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
