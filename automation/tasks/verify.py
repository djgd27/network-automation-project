"""
Read-only fabric health check.

For each Nornir host (leaf + spine), assert:

  1. Every BGP neighbor reported by the device is `is_up: True`.
  2. Loopback0 IP on the device matches the device's `primary_ip4`
     in NetBox.

Failures are surfaced via Nornir's task status — exit non-zero so this
plays well with CI later.

Usage:
    python -m automation.tasks.verify
"""

from __future__ import annotations

import sys

from nornir.core.task import Result, Task
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

from automation.nornir_inventory import get_nornir


def verify(task: Task) -> Result:
    sub = task.run(
        task=napalm_get,
        getters=["bgp_neighbors", "interfaces_ip"],
        severity_level=20,
    )
    bgp = sub.result["bgp_neighbors"]
    ifaces = sub.result["interfaces_ip"]

    failures: list[str] = []

    # 1. every BGP neighbor is up
    for vrf_name, vrf in bgp.items():
        for peer_ip, peer in vrf.get("peers", {}).items():
            if not peer.get("is_up"):
                failures.append(
                    f"BGP {peer_ip} in vrf={vrf_name!r} is DOWN "
                    f"(state={peer.get('uptime')!r})"
                )

    # 2. Loopback0 matches NetBox primary_ip4
    expected = task.host.data["primary_ip4"]["address"].split("/")[0]
    lo0 = ifaces.get("Loopback0", {}).get("ipv4", {})
    actual_ips = list(lo0.keys())
    if expected not in actual_ips:
        failures.append(
            f"Loopback0 IP mismatch: NetBox={expected}, device={actual_ips}"
        )

    if failures:
        return Result(
            host=task.host,
            failed=True,
            result="\n".join(failures),
        )
    peer_count = sum(len(v.get("peers", {})) for v in bgp.values())
    return Result(
        host=task.host,
        result=f"OK — {peer_count} BGP peers up, Loopback0={expected}",
    )


def main() -> int:
    nr = get_nornir()
    result = nr.run(task=verify)
    print_result(result)
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
