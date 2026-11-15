"""Command line for the gold set.

    python -m gold build                 write gold/corpus/ from the generator
    python -m gold score --split dev     run the engine on one split and score it
    python -m gold score --misses 20     also list what was missed and what was extra
    CASENOESIS_SYNTAX=1 python -m gold score     with the parser and NER readers on
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gold", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="write the corpus")
    conduct = commands.add_parser("conduct", help="the gold statements of offense: build them, or score the acts the engine reads")
    conduct.add_argument("action", choices=["build", "score"])
    conduct.add_argument("--split", choices=["dev", "test"])
    conduct.add_argument("--out", default="")
    score = commands.add_parser("score", help="run the engine and score it")
    score.add_argument("--split", choices=["dev", "test"])
    score.add_argument("--misses", type=int, default=0, help="list this many misses per field")
    score.add_argument("--field", default="", help="only list misses for this field")
    score.add_argument("--out", default="", help="also write the full report to this file")
    args = parser.parse_args(argv)

    if args.command == "build":
        from gold import build

        print(json.dumps(build.write(), indent=2))
        return 0

    if args.command == "conduct":
        from gold import conduct as gold_conduct

        report = gold_conduct.write() if args.action == "build" else gold_conduct.score(args.split, f"conduct-{args.split or 'all'}")
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=1, sort_keys=True)
        print(json.dumps(report, indent=2))
        return 0

    from gold import score as scoring

    name = (args.split or "all") + ("-syntax" if scoring.os.environ.get("CASENOESIS_SYNTAX") == "1" else "-rules")
    report = scoring.evaluate(args.split, name)
    misses = report.pop("misses")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({**report, "misses": misses}, handle, indent=2, ensure_ascii=False, default=str)
    print(json.dumps(report, indent=2, default=str))
    if args.misses:
        shown: dict[tuple[str, str], int] = {}
        for miss in misses:
            if args.field and miss["field"] != args.field:
                continue
            key = (miss["field"], miss["kind"])
            shown[key] = shown.get(key, 0) + 1
            if shown[key] <= args.misses:
                print(json.dumps(miss, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
