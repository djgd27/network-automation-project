"""
Push rendered configs to devices via NAPALM.

For each Nornir host, loads `configs/rendered/<host>.cfg` as a candidate
config and either prints the diff (default, dry-run) or commits it
(`--commit`).

Uses `load_merge_candidate`, not `load_replace_candidate`. Rendered
configs are intentionally minimal — they contain only the
intent-managed fabric config (BGP, EVPN, VXLAN, interfaces). Replace
would strip the device-side defaults we depend on for our own
connectivity (cEOS auto-emitted `username`, `management api
http-commands`, Management0 mgmt IP), cutting SSH/eAPI mid-push.

Usage:
    python -m automation.tasks.deploy                      # dry-run all
    python -m automation.tasks.deploy --device leaf1       # dry-run one
    python -m automation.tasks.deploy --commit             # apply all
    python -m automation.tasks.deploy --device leaf1 --commit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nornir.core.task import Result, Task
from nornir_utils.plugins.functions import print_result

from automation.nornir_inventory import get_nornir

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDERED_DIR = REPO_ROOT / "configs" / "rendered"


def deploy(task: Task, commit: bool) -> Result:
    rendered = RENDERED_DIR / f"{task.host.name}.cfg"
    if not rendered.exists():
        return Result(
            host=task.host,
            failed=True,
            result=f"no rendered config at {rendered.relative_to(REPO_ROOT)}",
        )

    napalm = task.host.get_connection("napalm", task.nornir.config)
    napalm.load_merge_candidate(filename=str(rendered))
    diff = napalm.compare_config()

    if not diff.strip():
        napalm.discard_config()
        return Result(host=task.host, result="no changes")

    if commit:
        napalm.commit_config()
        return Result(host=task.host, changed=True, result=f"COMMITTED:\n{diff}")

    napalm.discard_config()
    return Result(host=task.host, result=f"DRY-RUN — would change:\n{diff}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--commit", action="store_true", help="apply changes (default: dry-run)")
    ap.add_argument("--device", help="restrict to a single device by name")
    args = ap.parse_args()

    nr = get_nornir()
    if args.device:
        nr = nr.filter(name=args.device)
        if not nr.inventory.hosts:
            print(f"ERROR: no host named {args.device!r}", file=sys.stderr)
            return 2

    result = nr.run(task=deploy, commit=args.commit)
    print_result(result)
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
