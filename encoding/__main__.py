"""Command line for SDK encoding.

    python -m encoding pin                      which SDK, and is it the pin
    python -m encoding index                    index what the collector has
    python -m encoding records --kind court     SDK document processor over records
    python -m encoding redact                   remove names from graphs already encoded
    python -m encoding gate <graph> [...]       validate graphs against the pinned SDK
    python -m encoding status                   what has been indexed and encoded
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Any


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _select(args: argparse.Namespace) -> list[dict[str, Any]]:
    from encoding import corpus

    entries = corpus.load_index()
    if args.ids:
        wanted = set(args.ids)
        return [entry for entry in entries if entry["record_id"] in wanted]
    if args.kind:
        entries = [entry for entry in entries if entry["kind"] == args.kind]
    if args.domain:
        entries = [entry for entry in entries if corpus.in_domain(entry, args.domain)]
    if args.sample:
        random.Random(args.seed).shuffle(entries)
    return entries[: args.limit] if args.limit else entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m encoding", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pin", help="show the SDK checkout and whether it is the pin")
    commands.add_parser("index", help="rebuild data/encoded/index.jsonl")
    commands.add_parser("status", help="counts of indexed and encoded records")

    records = commands.add_parser("records", help="run the SDK document processor")
    records.add_argument("ids", nargs="*", help="record ids (default: select by filters)")
    records.add_argument("--kind", choices=["press", "court", "reference"])
    records.add_argument("--domain")
    records.add_argument("--limit", type=int, default=0)
    records.add_argument("--sample", action="store_true", help="shuffle before --limit")
    records.add_argument("--seed", type=int, default=8252)
    records.add_argument("--workers", type=int, default=1)
    records.add_argument("--force", action="store_true", help="re-encode records already done")
    records.add_argument("--gate", action="store_true", help="validate every graph written")

    redact = commands.add_parser("redact", help="remove names from graphs already encoded")
    redact.add_argument("--kind", choices=["press", "court", "reference"])
    redact.add_argument("--workers", type=int, default=1)
    redact.add_argument("--force", action="store_true")

    gate = commands.add_parser("gate", help="validate graphs against the pinned SDK")
    gate.add_argument("graphs", nargs="*", help="graph files (default: encoded records with no receipt)")
    gate.add_argument("--kind", choices=["press", "court", "reference"])
    gate.add_argument("--workers", type=int, default=1)
    gate.add_argument("--ontology", action="append", default=[], help="local declaration (.ttl)")
    gate.add_argument("--write-receipt", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "pin":
        from encoding import sdk

        status = sdk.pin_status()
        _print(status)
        return 0 if status["pinned"] else 1

    if args.command == "index":
        from encoding import corpus

        _print(corpus.build_index())
        return 0

    if args.command == "status":
        from encoding import records as record_layer

        _print(record_layer.status())
        return 0

    if args.command == "records":
        from encoding import records as record_layer

        _print(record_layer.run(_select(args), workers=args.workers, force=args.force, gate=args.gate))
        return 0

    if args.command == "redact":
        from encoding import records as record_layer

        _print(record_layer.redact_encoded(kind=args.kind, workers=args.workers, force=args.force))
        return 0

    if args.command == "gate":
        from encoding import records as record_layer
        from encoding import sdk

        if not args.graphs:
            _print(record_layer.gate_encoded(kind=args.kind, workers=args.workers))
            return 0
        failed = False
        for graph in args.graphs:
            receipt = sdk.gate(graph, extra_ontology_graphs=args.ontology or None)
            if args.write_receipt:
                sdk.write_receipt(graph, receipt)
            failed = failed or not receipt["conforms"]
            _print(receipt)
        return 1 if failed else 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
