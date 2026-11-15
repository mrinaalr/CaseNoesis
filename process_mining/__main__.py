"""Command line for process mining.

    python -m process_mining log                       the event log: traces, events, how many are dated
    python -m process_mining variants --limit 15       the paths cases take, most common first
    python -m process_mining model --noise 0.2         the discovered model and how well the log fits it
    python -m process_mining conform                   departures from procedural order
    python -m process_mining case <case-id | record-id>
    python -m process_mining ocel data/extracted/events.ocel.json

    python -m process_mining conduct summary            the acts read from records
    python -m process_mining conduct paths --level phase --kind court
    python -m process_mining conduct transitions --domain fraud
    python -m process_mining conduct compare            how far apart the domains are at each level
    python -m process_mining conduct means --domain fraud
    python -m process_mining conduct record <record-id>
    python -m process_mining conduct export data/extracted/trajectories.jsonl

Run `python -m extraction people` and `python -m extraction events` first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m process_mining", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--level", choices=["detailed", "coarse"], default="detailed")
        sub.add_argument("--dated-only", action="store_true", help="keep only events that have a date")
        sub.add_argument("--domain", default="")
        sub.add_argument("--with-offense", action="store_true", help="include when the conduct began as a step")

    commands.add_parser("log", help="the event log")
    variants = commands.add_parser("variants", help="the paths cases take")
    common(variants)
    variants.add_argument("--limit", type=int, default=20)
    model = commands.add_parser("model", help="the discovered model")
    common(model)
    model.add_argument("--noise", type=float, default=0.2)
    conform = commands.add_parser("conform", help="departures from procedural order")
    conform.add_argument("--domain", default="")
    conform.add_argument("--limit", type=int, default=20)
    case = commands.add_parser("case", help="one case against the model and against procedure")
    case.add_argument("id")
    conduct = commands.add_parser("conduct", help="the offense itself: acts, paths, transitions, and how domains compare")
    conduct.add_argument("view", choices=["summary", "paths", "transitions", "compare", "means", "record", "export"])
    conduct.add_argument("target", nargs="?", default="", help="a record id for `record`; a file path for `export`")
    conduct.add_argument("--level", choices=["means", "act", "phase"], default="act")
    conduct.add_argument("--domain", default="")
    conduct.add_argument("--kind", choices=["", "court", "press"], default="", help="keep only court filings or only press releases")
    conduct.add_argument("--noise", type=float, default=0.2)
    conduct.add_argument("--limit", type=int, default=15)
    ocel = commands.add_parser("ocel", help="write the dated events as an OCEL 2.0 log")
    ocel.add_argument("path")
    args = parser.parse_args(argv)

    from process_mining import views

    if args.command == "log":
        out = views.log_summary()
    elif args.command == "variants":
        out = views.variants(level=args.level, dated_only=args.dated_only, domain=args.domain, with_offense=args.with_offense, limit=args.limit)
    elif args.command == "model":
        out = views.model(level=args.level, noise=args.noise, dated_only=args.dated_only, domain=args.domain, with_offense=args.with_offense)
        print(out.pop("tree_text"), end="\n\n")
    elif args.command == "conform":
        out = views.conformance(domain=args.domain, limit=args.limit)
    elif args.command == "case":
        out = views.case(args.id)
    elif args.command == "conduct":
        if args.view == "summary":
            out = views.conduct_summary()
        elif args.view == "paths":
            out = views.conduct_paths(level=args.level, domain=args.domain, kind=args.kind, noise=args.noise, limit=args.limit)
            if "tree_text" in out:
                print(out.pop("tree_text"), end="\n\n")
        elif args.view == "transitions":
            out = views.conduct_transitions(level=args.level, domain=args.domain, kind=args.kind)
        elif args.view == "compare":
            out = views.conduct_compare(kind=args.kind)
        elif args.view == "means":
            out = views.conduct_means(domain=args.domain, kind=args.kind)
        elif args.view == "record":
            out = views.conduct_record(args.target)
        else:
            from extraction import store
            from process_mining import trajectory

            rows = trajectory.export(trajectory.build(store.connect(), domain=args.domain, kind=args.kind))
            target = Path(args.target or "data/extracted/trajectories.jsonl")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            out = {"trajectories": len(rows), "path": str(target)}
    else:
        from extraction import store
        from process_mining import log

        out = log.write_ocel(store.connect(), Path(args.path))
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
