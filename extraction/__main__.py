"""Command line for the extraction engine.

    python -m extraction run --kind court --workers 6    read records: readers, gate, vote
    python -m extraction resolve                         vote again over stored assertions
    python -m extraction cases                           group records into cases
    python -m extraction people                          link defendants across a case's records; settle whose each value is
    python -m extraction events                          date and order what happened in each case
    python -m extraction conduct                         put the acts each record narrates in order
    python -m extraction timeline <case-id | record-id>  one case's events in order
    python -m extraction graph --gate --workers 6        write and validate CASE/UCO graphs
    python -m extraction store                           load validated graphs into Oxigraph and graphs.nq
    python -m extraction sparql "SELECT ..."              query the local triple store
    python -m extraction serve                           SPARQL over HTTP on 127.0.0.1
    python -m extraction status                          what has been read, settled, and queued
    python -m extraction show <record-id>                one record's values and open mentions
    python -m extraction review --field money            the review queue
    python -m extraction search money --role loss --min 1000000
    python -m extraction count scheme --domain fraud     how often each label was settled
    python -m extraction case <case-id | record-id>
    python -m extraction fields                          the field registry and reader list
    python -m extraction prune                           drop assertion rows from superseded runs
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Any


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m extraction", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="read records")
    run.add_argument("ids", nargs="*")
    run.add_argument("--kind", choices=["press", "court", "reference"])
    run.add_argument("--domain")
    run.add_argument("--encoded-only", action="store_true", help="only records the SDK processor has encoded")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--sample", action="store_true", help="shuffle before --limit")
    run.add_argument("--seed", type=int, default=8252)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--force", action="store_true", help="read records again")
    run.add_argument("--syntax", action="store_true", help="also run the parser and NER readers (same as CASENOESIS_SYNTAX=1)")

    resolve = commands.add_parser("resolve", help="vote again over stored assertions")
    resolve.add_argument("--kind", choices=["press", "court", "reference"])

    commands.add_parser("cases", help="group records into cases")
    commands.add_parser("people", help="link defendants across records and settle attributions")
    commands.add_parser("events", help="date and order the events of each case")
    commands.add_parser("conduct", help="put the acts each record narrates in order")
    timeline = commands.add_parser("timeline", help="one case's events in order")
    timeline.add_argument("id")

    graph = commands.add_parser("graph", help="write CASE/UCO graphs for read records")
    graph.add_argument("ids", nargs="*")
    graph.add_argument("--kind", choices=["press", "court", "reference"])
    graph.add_argument("--gate", action="store_true", help="validate every graph written")
    graph.add_argument("--workers", type=int, default=1)
    graph.add_argument("--limit", type=int, default=0)
    graph.add_argument("--force", action="store_true")

    store_cmd = commands.add_parser("store", help="load validated graphs into the local Oxigraph store and graphs.nq")
    store_cmd.add_argument("--rebuild", action="store_true")
    store_cmd.add_argument("--include-unvalidated", action="store_true", help="also load graphs that were not gated")
    sparql = commands.add_parser("sparql", help="query the local triple store")
    sparql.add_argument("query", help="SPARQL text, or the name of a built-in example")
    sparql.add_argument("--limit", type=int, default=50)
    serve = commands.add_parser("serve", help="SPARQL over HTTP on 127.0.0.1")
    serve.add_argument("--port", type=int, default=7878)

    commands.add_parser("status", help="counts")
    commands.add_parser("agreement", help="how the reader families compare")
    commands.add_parser("fields", help="the field registry and the readers")
    commands.add_parser("prune", help="drop assertion rows from superseded runs")
    commands.add_parser("rescrub", help="mask names again in stored span text with the current rules")

    show = commands.add_parser("show", help="one record")
    show.add_argument("record_id")

    review = commands.add_parser("review", help="the review queue")
    review.add_argument("--field", default="")
    review.add_argument("--state", default="", choices=["", "contested", "weak", "self_contradiction"])
    review.add_argument("--kind", default="")
    review.add_argument("--limit", type=int, default=10)

    search = commands.add_parser("search", help="records with a settled value")
    search.add_argument("field")
    search.add_argument("--value", default="")
    search.add_argument("--role", default="")
    search.add_argument("--kind", default="")
    search.add_argument("--domain", default="")
    search.add_argument("--min", type=float, dest="minimum")
    search.add_argument("--max", type=float, dest="maximum")
    search.add_argument("--limit", type=int, default=20)

    count = commands.add_parser("count", help="how often each settled label occurs")
    count.add_argument("field")
    count.add_argument("--by", default="value", choices=["value", "role"])
    count.add_argument("--kind", default="")
    count.add_argument("--domain", default="")
    count.add_argument("--limit", type=int, default=40)

    case = commands.add_parser("case", help="one case")
    case.add_argument("id")

    args = parser.parse_args(argv)
    if getattr(args, "syntax", False):
        import os

        os.environ["CASENOESIS_SYNTAX"] = "1"  # before the readers load; worker processes inherit it
    from extraction import explore

    if args.command == "run":
        from encoding import corpus
        from extraction import pipeline

        entries = corpus.load_index()
        if args.ids:
            wanted = set(args.ids)
            entries = [e for e in entries if e["record_id"] in wanted]
        else:
            if args.kind:
                entries = [e for e in entries if e["kind"] == args.kind]
            if args.domain:
                entries = [e for e in entries if corpus.in_domain(e, args.domain)]
            if args.encoded_only:
                entries = [e for e in entries if (pipeline.ENCODED_RECORDS / e["record_id"] / "extracted-content.json").is_file()]
            if args.sample:
                random.Random(args.seed).shuffle(entries)
            if args.limit:
                entries = entries[: args.limit]
        _print(pipeline.run(entries, workers=args.workers, force=args.force))
    elif args.command == "resolve":
        from extraction import pipeline

        _print(pipeline.reresolve(kind=args.kind))
    elif args.command == "cases":
        from extraction import cases

        _print(cases.build())
    elif args.command == "people":
        from extraction import people

        _print(people.build())
    elif args.command == "events":
        from extraction import events

        _print(events.build())
    elif args.command == "conduct":
        from extraction import conduct

        _print(conduct.build())
    elif args.command == "timeline":
        _print(explore.timeline(args.id))
    elif args.command == "graph":
        from extraction import graph as graph_layer

        _print(graph_layer.build(args.ids or None, kind=args.kind, gate=args.gate, workers=args.workers,
                                 force=args.force, limit=args.limit))
    elif args.command == "store":
        from extraction import triples

        _print(triples.load(rebuild=args.rebuild, include_unvalidated=args.include_unvalidated))
    elif args.command == "sparql":
        from extraction import triples

        _print(triples.query(triples.EXAMPLES.get(args.query, args.query), args.limit))
    elif args.command == "serve":
        from extraction import triples

        triples.serve(args.port)
    elif args.command == "status":
        _print(explore.status())
    elif args.command == "agreement":
        _print(explore.agreement())
    elif args.command == "fields":
        from extraction import fields, profiles
        from extraction.readers import FAMILY, reader_versions

        _print({
            "fields": {
                spec.name: {
                    "shape": spec.shape, "roles": list(spec.roles), "never_stored": list(spec.excluded_roles),
                    "labels": list(spec.vocabulary) or (list(profiles.labels(spec.name)) if spec.name in ("scheme", "channel", "platform") else []),
                    "description": spec.description,
                }
                for spec in fields.all_fields()
            },
            "readers": reader_versions(),
            "families": FAMILY,
        })
    elif args.command == "rescrub":
        from extraction import pipeline, store
        from extraction.source import CorpusSource

        _print(pipeline.rescrub(store.connect(), CorpusSource()))
    elif args.command == "prune":
        from extraction import store

        _print({"assertion_rows_removed": store.prune(store.connect())})
    elif args.command == "show":
        _print(explore.record(args.record_id))
    elif args.command == "review":
        _print(explore.review_queue(args.field, args.state, args.kind, args.limit))
    elif args.command == "search":
        _print(explore.search(args.field, args.value, args.role, args.kind, args.domain, "", args.minimum, args.maximum, args.limit))
    elif args.command == "count":
        _print(explore.distribution(args.field, args.kind, args.domain, args.by, args.limit))
    elif args.command == "case":
        _print(explore.case(args.id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
