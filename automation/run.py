#!/usr/bin/env python3
"""
Single dispatcher for the automation pipeline.

    python -m automation.run render [--device leaf1] [--diff]
    python -m automation.run validate [--quiet]
    python -m automation.run deploy [--device leaf1] [--commit]
    python -m automation.run verify
    python -m automation.run backup

Each subcommand delegates to the matching module's `main()` — flags pass
through unchanged. The dispatcher exists so the rehearsal and CI workflow
have one stable entrypoint instead of five module paths.
"""

from __future__ import annotations

import importlib
import sys

SUBCOMMANDS = {
    "render":   "automation.render",
    "validate": "automation.validate",
    "deploy":   "automation.tasks.deploy",
    "verify":   "automation.tasks.verify",
    "backup":   "automation.tasks.backup",
}


def usage() -> str:
    cmds = " | ".join(SUBCOMMANDS)
    return f"usage: run.py {{{cmds}}} [--help] [...]"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2

    cmd, rest = argv[0], argv[1:]
    module_name = SUBCOMMANDS.get(cmd)
    if module_name is None:
        print(f"ERROR: unknown subcommand {cmd!r}", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 2

    module = importlib.import_module(module_name)
    # rewrite argv so the delegated main() sees its own flags as if invoked directly
    sys.argv = [module_name.split(".")[-1] + ".py", *rest]
    rc = module.main()
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
