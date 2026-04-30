"""
Nornir bootstrap for the EVPN-VXLAN fabric.

Pulls inventory from NetBox via `nornir-netbox` and applies a transform that
overrides each host's connection target with the clab-managed short name
(leaf1, spine1, ...) — `/etc/hosts` resolves these to the clab mgmt IPs.

NetBox stores `primary_ip4` as the device's Loopback0 (10.0.0.x), which is
correct for the fabric but unreachable from this VM. We leave NetBox alone
and override at Nornir's edge.

edge1 (FRR) is filtered out: NAPALM has no production-ready FRR driver.
edge1's config remains bind-mounted via `topology/lab.clab.yml` and is
managed by file on disk + clab redeploy.

Env:
    NETBOX_URL       default http://127.0.0.1:8000
    NETBOX_TOKEN     required (nbt_<id>.<secret>)
    NORNIR_USERNAME  required (device login)
    NORNIR_PASSWORD  required
"""

from __future__ import annotations

import os

from nornir import InitNornir
from nornir.core import Nornir

PLATFORM_BY_MFR = {
    "arista": "eos",
}


def get_nornir() -> Nornir:
    nr = InitNornir(
        runner={"plugin": "threaded", "options": {"num_workers": 5}},
        inventory={
            "plugin": "NetBoxInventory2",
            "options": {
                "nb_url": os.environ.get("NETBOX_URL", "http://127.0.0.1:8000"),
                "nb_token": os.environ["NETBOX_TOKEN"],
                "filter_parameters": {"role": ["spine", "leaf"]},
            },
        },
        logging={"enabled": False},
    )
    username = os.environ["NORNIR_USERNAME"]
    password = os.environ["NORNIR_PASSWORD"]
    for host in nr.inventory.hosts.values():
        host.hostname = host.name
        host.username = username
        host.password = password
        host.platform = PLATFORM_BY_MFR[host.data["device_type"]["manufacturer"]["slug"]]
    return nr
