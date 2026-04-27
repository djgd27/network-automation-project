#!/usr/bin/env python3
"""
NetBox seeder for the EVPN-VXLAN fabric.

Reads YAML files from inventory/netbox/data/ and idempotently pushes them
into NetBox via the pynetbox API.

    NETBOX_URL     default: http://127.0.0.1:8000
    NETBOX_TOKEN   required (NetBox v2 token, full nbt_<id>.<secret> form)

    ./seed.py                    full seed
    ./seed.py --dry-run          parse + plan, no writes
    ./seed.py --stage devices    run a single stage
    ./seed.py --from devices     run from this stage onward
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import pynetbox
import yaml
from pynetbox.core.response import Record

DATA_DIR = Path(__file__).resolve().parent / "data"

STAGES = [
    "custom-fields",
    "sites",
    "tenants",
    "manufacturers",
    "device-roles",
    "device-types",
    "vrfs",
    "vlans",
    "prefixes",
    "devices",
    "interfaces",
    "ips",
    "primary-ips",
    "cables",
]


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def load_yaml(name: str) -> list[dict[str, Any]]:
    path = DATA_DIR / f"{name}.yml"
    if not path.exists():
        return []
    with path.open() as f:
        return yaml.safe_load(f) or []


def coerce(value: Any) -> Any:
    """Turn pynetbox Records into a comparable scalar.

    Regular FK records have `.id` (e.g. site, tenant). Choice fields are also
    Records but expose `.value`/`.label` instead (e.g. custom-field `type`,
    interface `mode`). Fall back to `str()` for anything else.
    """
    if isinstance(value, Record):
        try:
            return value.id
        except AttributeError:
            pass
        try:
            return value.value
        except AttributeError:
            return str(value)
    if isinstance(value, list):
        return [coerce(v) for v in value]
    return value


class Resolver:
    """Caches FK lookups so repeated references don't round-trip."""

    def __init__(self, nb: pynetbox.api):
        self.nb = nb
        self._cache: dict[tuple, Record | None] = {}

    def _get(self, path: str, **kwargs) -> Record | None:
        key = (path, tuple(sorted(kwargs.items())))
        if key not in self._cache:
            ep = self.nb
            for part in path.split("."):
                ep = getattr(ep, part)
            self._cache[key] = ep.get(**kwargs)
        return self._cache[key]

    def site(self, slug: str) -> Record:
        return self._require("dcim.sites", "site", slug, slug=slug)

    def tenant(self, slug: str) -> Record:
        return self._require("tenancy.tenants", "tenant", slug, slug=slug)

    def manufacturer(self, slug: str) -> Record:
        return self._require("dcim.manufacturers", "manufacturer", slug, slug=slug)

    def device_role(self, slug: str) -> Record:
        return self._require("dcim.device_roles", "device-role", slug, slug=slug)

    def device_type(self, slug: str) -> Record:
        return self._require("dcim.device_types", "device-type", slug, slug=slug)

    def vrf(self, name: str) -> Record:
        return self._require("ipam.vrfs", "vrf", name, name=name)

    def vlan(self, vid: int, site_slug: str) -> Record:
        site = self.site(site_slug)
        return self._require(
            "ipam.vlans", "vlan", f"{vid}@{site_slug}",
            vid=vid, site_id=site.id,
        )

    def device(self, name: str) -> Record:
        return self._require("dcim.devices", "device", name, name=name)

    def interface(self, device: str, name: str) -> Record:
        dev = self.device(device)
        return self._require(
            "dcim.interfaces", "interface", f"{device}.{name}",
            device_id=dev.id, name=name,
        )

    def ip(self, address: str, vrf_name: str | None = None) -> Record | None:
        kwargs: dict[str, Any] = {"address": address}
        if vrf_name:
            kwargs["vrf"] = vrf_name
        else:
            kwargs["vrf"] = "null"
        return self._get("ipam.ip_addresses", **kwargs)

    def _require(self, path: str, kind: str, label: str, **kwargs) -> Record:
        obj = self._get(path, **kwargs)
        if obj is None:
            raise SystemExit(f"FK lookup failed: {kind}={label!r}")
        return obj


# ----------------------------------------------------------------------
# generic upsert
# ----------------------------------------------------------------------

class Stats:
    def __init__(self) -> None:
        self.created = 0
        self.updated = 0
        self.unchanged = 0

    def line(self) -> str:
        return f"{self.created} created · {self.updated} updated · {self.unchanged} unchanged"


def upsert(
    endpoint,
    *,
    lookup: dict[str, Any],
    payload: dict[str, Any],
    label: str,
    stats: Stats,
    dry_run: bool,
    skip_drift_keys: Iterable[str] = (),
) -> Record | None:
    existing = endpoint.get(**lookup)
    if existing is None:
        if dry_run:
            print(f"  CREATE  [dry] {label}")
            stats.created += 1
            return None
        try:
            obj = endpoint.create(payload)
        except pynetbox.RequestError as e:
            raise SystemExit(f"CREATE failed for {label}: {e.error}") from e
        print(f"  CREATE        {label}")
        stats.created += 1
        return obj

    drift: dict[str, tuple[Any, Any]] = {}
    for key, new in payload.items():
        if key in skip_drift_keys:
            continue
        if key == "custom_fields":
            cur = dict(getattr(existing, "custom_fields", {}) or {})
            for ck, cv in new.items():
                if cur.get(ck) != cv:
                    drift[key] = (cur, new)
                    break
            continue
        cur = coerce(getattr(existing, key, None))
        if cur != coerce(new):
            drift[key] = (cur, coerce(new))

    if not drift:
        stats.unchanged += 1
        return existing

    if dry_run:
        print(f"  UPDATE  [dry] {label}  fields={list(drift)}")
        stats.updated += 1
        return existing
    try:
        existing.update(payload)
    except pynetbox.RequestError as e:
        raise SystemExit(f"UPDATE failed for {label}: {e.error}") from e
    print(f"  UPDATE        {label}  fields={list(drift)}")
    stats.updated += 1
    return existing


# ----------------------------------------------------------------------
# stages
# ----------------------------------------------------------------------

def stage_custom_fields(nb, r, dry_run):
    s = Stats()
    for entry in load_yaml("custom-fields"):
        payload = dict(entry)
        upsert(
            nb.extras.custom_fields,
            lookup={"name": entry["name"]},
            payload=payload,
            label=f'cf:{entry["name"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_sites(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("sites"):
        upsert(
            nb.dcim.sites,
            lookup={"slug": e["slug"]},
            payload=e,
            label=f'site:{e["slug"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_tenants(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("tenants"):
        upsert(
            nb.tenancy.tenants,
            lookup={"slug": e["slug"]},
            payload=e,
            label=f'tenant:{e["slug"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_manufacturers(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("manufacturers"):
        upsert(
            nb.dcim.manufacturers,
            lookup={"slug": e["slug"]},
            payload=e,
            label=f'mfr:{e["slug"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_device_roles(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("device-roles"):
        upsert(
            nb.dcim.device_roles,
            lookup={"slug": e["slug"]},
            payload=e,
            label=f'role:{e["slug"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_device_types(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("device-types"):
        payload = dict(e)
        payload["manufacturer"] = r.manufacturer(e["manufacturer"]).id
        upsert(
            nb.dcim.device_types,
            lookup={"slug": e["slug"]},
            payload=payload,
            label=f'dtype:{e["slug"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_vrfs(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("vrfs"):
        payload = dict(e)
        if e.get("tenant"):
            payload["tenant"] = r.tenant(e["tenant"]).id
        upsert(
            nb.ipam.vrfs,
            lookup={"name": e["name"]},
            payload=payload,
            label=f'vrf:{e["name"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_vlans(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("vlans"):
        payload = dict(e)
        site = r.site(e["site"])
        payload["site"] = site.id
        if e.get("tenant"):
            payload["tenant"] = r.tenant(e["tenant"]).id
        upsert(
            nb.ipam.vlans,
            lookup={"vid": e["vid"], "site_id": site.id},
            payload=payload,
            label=f'vlan:{e["vid"]}@{e["site"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_prefixes(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("prefixes"):
        payload = dict(e)
        if e.get("site"):
            payload["site"] = r.site(e["site"]).id
        if e.get("vrf"):
            payload["vrf"] = r.vrf(e["vrf"]).id
        if e.get("tenant"):
            payload["tenant"] = r.tenant(e["tenant"]).id
        if e.get("vlan") is not None:
            payload["vlan"] = r.vlan(e["vlan"], e["site"]).id
        lookup = {"prefix": e["prefix"]}
        if e.get("vrf"):
            lookup["vrf_id"] = payload["vrf"]
        else:
            lookup["vrf"] = "null"
        upsert(
            nb.ipam.prefixes,
            lookup=lookup,
            payload=payload,
            label=f'prefix:{e["prefix"]}' + (f' (vrf={e["vrf"]})' if e.get("vrf") else ""),
            stats=s, dry_run=dry_run,
        )
    return s


def stage_devices(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("devices"):
        payload = {
            "name": e["name"],
            "site": r.site(e["site"]).id,
            "role": r.device_role(e["role"]).id,
            "device_type": r.device_type(e["device_type"]).id,
            "status": e.get("status", "active"),
            "custom_fields": e.get("custom_fields", {}),
        }
        upsert(
            nb.dcim.devices,
            lookup={"name": e["name"]},
            payload=payload,
            label=f'device:{e["name"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_interfaces(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("interfaces"):
        dev = r.device(e["device"])
        payload: dict[str, Any] = {
            "device": dev.id,
            "name": e["name"],
            "type": e["type"],
            "description": e.get("description", ""),
            "mgmt_only": e.get("mgmt_only", False),
        }
        if e.get("mode"):
            payload["mode"] = e["mode"]
        if e.get("untagged_vlan") is not None:
            payload["untagged_vlan"] = r.vlan(e["untagged_vlan"], "lab").id
        if e.get("tagged_vlans"):
            payload["tagged_vlans"] = [
                r.vlan(v, "lab").id for v in e["tagged_vlans"]
            ]
        if e.get("vrf"):
            payload["vrf"] = r.vrf(e["vrf"]).id
        upsert(
            nb.dcim.interfaces,
            lookup={"device_id": dev.id, "name": e["name"]},
            payload=payload,
            label=f'iface:{e["device"]}.{e["name"]}',
            stats=s, dry_run=dry_run,
        )
    return s


def stage_ips(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("ips"):
        iface = r.interface(e["device"], e["interface"])
        payload: dict[str, Any] = {
            "address": e["address"],
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": iface.id,
            "description": e.get("description", ""),
            "status": e.get("status", "active"),
        }
        if e.get("vrf"):
            payload["vrf"] = r.vrf(e["vrf"]).id
        if e.get("role"):
            payload["role"] = e["role"]

        lookup = {
            "address": e["address"],
            "device_id": r.device(e["device"]).id,
            "interface_id": iface.id,
        }
        upsert(
            nb.ipam.ip_addresses,
            lookup=lookup,
            payload=payload,
            label=f'ip:{e["address"]} → {e["device"]}.{e["interface"]}',
            stats=s, dry_run=dry_run,
            skip_drift_keys=("assigned_object_type", "assigned_object_id"),
        )
    return s


def stage_primary_ips(nb, r, dry_run):
    """Second pass: set device.primary_ip4 to the IP marked is_primary in ips.yml."""
    s = Stats()
    for e in load_yaml("ips"):
        if not e.get("is_primary"):
            continue
        dev = r.device(e["device"])
        iface = r.interface(e["device"], e["interface"])
        ip_obj = nb.ipam.ip_addresses.get(
            address=e["address"],
            interface_id=iface.id,
        )
        if ip_obj is None:
            if dry_run:
                print(f"  PRIMARY [dry] {e['device']} (ip not yet created)")
                s.created += 1
                continue
            raise SystemExit(f"primary-ips: IP {e['address']} not found for {e['device']}")
        current = coerce(getattr(dev, "primary_ip4", None))
        if current == ip_obj.id:
            s.unchanged += 1
            continue
        if dry_run:
            print(f"  PRIMARY [dry] {e['device']} → {e['address']}")
            s.updated += 1
            continue
        dev.update({"primary_ip4": ip_obj.id})
        print(f"  PRIMARY       {e['device']} → {e['address']}")
        s.updated += 1
    return s


def stage_cables(nb, r, dry_run):
    s = Stats()
    for e in load_yaml("cables"):
        a_iface = r.interface(e["a"]["device"], e["a"]["interface"])
        b_iface = r.interface(e["b"]["device"], e["b"]["interface"])
        label = (
            f'cable:{e["a"]["device"]}.{e["a"]["interface"]} ↔ '
            f'{e["b"]["device"]}.{e["b"]["interface"]}'
        )
        if a_iface.cable is not None:
            s.unchanged += 1
            continue
        payload = {
            "a_terminations": [
                {"object_type": "dcim.interface", "object_id": a_iface.id}
            ],
            "b_terminations": [
                {"object_type": "dcim.interface", "object_id": b_iface.id}
            ],
            "status": e.get("status", "connected"),
            "type": e.get("type", "cat6"),
        }
        if dry_run:
            print(f"  CREATE  [dry] {label}")
            s.created += 1
            continue
        try:
            nb.dcim.cables.create(payload)
        except pynetbox.RequestError as ex:
            raise SystemExit(f"CREATE failed for {label}: {ex.error}") from ex
        print(f"  CREATE        {label}")
        s.created += 1
    return s


STAGE_FUNCS = {
    "custom-fields": stage_custom_fields,
    "sites": stage_sites,
    "tenants": stage_tenants,
    "manufacturers": stage_manufacturers,
    "device-roles": stage_device_roles,
    "device-types": stage_device_types,
    "vrfs": stage_vrfs,
    "vlans": stage_vlans,
    "prefixes": stage_prefixes,
    "devices": stage_devices,
    "interfaces": stage_interfaces,
    "ips": stage_ips,
    "primary-ips": stage_primary_ips,
    "cables": stage_cables,
}


# ----------------------------------------------------------------------
# entrypoint
# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="parse + plan, no writes")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--stage", choices=STAGES, help="run a single stage")
    grp.add_argument("--from", dest="from_stage", choices=STAGES, help="run from this stage onward")
    args = ap.parse_args()

    url = os.environ.get("NETBOX_URL", "http://127.0.0.1:8000")
    token = os.environ.get("NETBOX_TOKEN")
    if not token:
        print("ERROR: NETBOX_TOKEN not set in environment", file=sys.stderr)
        print("Hint: export NETBOX_TOKEN='nbt_<id>.<secret>'", file=sys.stderr)
        return 2

    nb = pynetbox.api(url, token=token)
    try:
        status = nb.status()
    except Exception as e:
        print(f"ERROR: cannot reach NetBox at {url}: {e}", file=sys.stderr)
        return 2
    print(f"NetBox {status.get('netbox-version')} at {url}")
    if args.dry_run:
        print("(dry-run — no changes will be written)")
    print()

    resolver = Resolver(nb)

    if args.stage:
        run = [args.stage]
    elif args.from_stage:
        run = STAGES[STAGES.index(args.from_stage):]
    else:
        run = list(STAGES)

    totals = Stats()
    for name in run:
        print(f"== {name} ==")
        s = STAGE_FUNCS[name](nb, resolver, args.dry_run)
        print(f"   {s.line()}")
        print()
        totals.created += s.created
        totals.updated += s.updated
        totals.unchanged += s.unchanged

    print(f"DONE  {totals.line()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
