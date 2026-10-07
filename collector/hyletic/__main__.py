"""One CLI for the hyletic packet.

    python3 -m collector.hyletic seed --seeds collector/profiles/calibration.json
    python3 -m collector.hyletic wayback --limit 1 --snapshots 1
    python3 -m collector.hyletic litigation --max-docs 1
    python3 -m collector.hyletic statutes --limit 1
    python3 -m collector.hyletic calibration --limit 1

Output root is data/collected/hyletic_data/. Nothing is written at the repo root.
"""

from __future__ import annotations

import sys

from . import calibration, litigation, seed, statutes, wayback

COMMANDS = {
    "seed": seed.main,
    "wayback": wayback.main,
    "litigation": litigation.main,
    "statutes": statutes.main,
    "calibration": calibration.main,
}


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__.strip())
        return 0
    command, rest = argv[0], argv[1:]
    run = COMMANDS.get(command)
    if run is None:
        print(f"unknown command {command}", file=sys.stderr)
        print("commands: " + ", ".join(COMMANDS), file=sys.stderr)
        return 2
    sys.argv = [command, *rest]
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
