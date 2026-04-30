"""
Pull running configs from every Nornir host, scrub secrets and cEOS
boilerplate, and write to `configs/<host>/startup.cfg` (the path
render.py diffs against).

Two-layer secret handling:

  1. NAPALM's `sanitized=True` redacts password / secret fields at the
     driver level. Belt.
  2. The DROP_PATTERNS list strips cEOS-emitted boilerplate stanzas
     (mgmt API enable, system l1, password line, Management0 with
     clab-assigned IP, mgmt default route, etc.) — anything render.py
     does not manage. Suspenders.

Usage:
    python -m automation.tasks.backup
"""

from __future__ import annotations

import re
from pathlib import Path

from nornir.core.task import Result, Task
from nornir_utils.plugins.functions import print_result

from automation.nornir_inventory import get_nornir

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGS_DIR = REPO_ROOT / "configs"

DROP_PATTERNS = [
    re.compile(r"^! (Command|device):"),
    re.compile(r"^no aaa root$"),
    re.compile(r"^username \S+ "),
    re.compile(r"^enable (password|secret) "),
    re.compile(r"^management api http-commands$"),
    re.compile(r"^no service interface inactive port-id allocation disabled$"),
    re.compile(r"^spanning-tree mode "),
    re.compile(r"^system l1$"),
    re.compile(r"^management api gnmi$"),
    re.compile(r"^management api netconf$"),
    re.compile(r"^interface Management\d+$"),
    re.compile(r"^ip route 0\.0\.0\.0/0 172\.20\.20\."),
]


def scrub(running: str) -> str:
    stanzas = running.split("\n!\n")
    kept: list[str] = []
    for stanza in stanzas:
        lines = stanza.splitlines()
        first = next((l for l in lines if l.strip()), "")
        if any(p.match(first) for p in DROP_PATTERNS):
            continue
        kept.append(stanza)
    return "\n!\n".join(kept)


def backup(task: Task) -> Result:
    napalm = task.host.get_connection("napalm", task.nornir.config)
    raw = napalm.get_config(retrieve="running", sanitized=True)["running"]
    cleaned = scrub(raw)
    target = CONFIGS_DIR / task.host.name / "startup.cfg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cleaned)
    return Result(
        host=task.host,
        result=f"wrote {target.relative_to(REPO_ROOT)} ({len(cleaned)} bytes)",
    )


def main() -> None:
    nr = get_nornir()
    print_result(nr.run(task=backup))


if __name__ == "__main__":
    main()
