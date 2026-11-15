"""Command line for the Exploitation State Machine.

    python -m state_machines groupings                     states with no scheme and no goal: groupings of the acts, one learned, compared
    python -m state_machines scheme --gate                 the states, their hierarchy and crosswalk; writes schemes/esm.ttl
    python -m state_machines machine --kind court          the fitted machine: action space, policy, T with counts (--layer track)
    python -m state_machines invariance --draws 200        domains compared at each level and layer, and the nulls that test it
    python -m state_machines decide --domain fraud         assumes an actor pursuing the goal: L*, beta beside beta on shuffled order
    python -m state_machines laws --kind court             coverage, laws, tracks, the exploitation predicate
    python -m state_machines read graph.ttl                any traj graph or JSON walks, through the same analyses
    python -m state_machines report                        every description, to data/extracted/esm/report.json (--decision adds the decision model)
    python -m state_machines graphs --kind court --gate    trajectory graphs per record, and fitted models per domain and layer

Run `python -m extraction conduct` first for the corpus commands: they read its acts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m state_machines", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def scope(sub: argparse.ArgumentParser, domain: bool = True) -> None:
        sub.add_argument("--kind", choices=["", "court", "press"], default="", help="keep only court filings or only press releases")
        if domain:
            sub.add_argument("--domain", default="")

    grp = commands.add_parser("groupings", help="groupings of the acts, one learned from the data, on the same measures")
    scope(grp, domain=False)
    grp.add_argument("--randoms", type=int, default=100, help="random groupings each named one is set beside")
    sch = commands.add_parser("scheme", help="the states, their hierarchy and crosswalk")
    sch.add_argument("--gate", action="store_true", help="write schemes/esm.ttl and validate it with the SDK gate")
    machine = commands.add_parser("machine", help="the fitted machine")
    scope(machine)
    machine.add_argument("--layer", choices=["milestone", "track"], default="milestone")
    machine.add_argument("--level", choices=["act", "means"], default="act")
    read = commands.add_parser("read", help="a traj graph (.ttl) or JSON walks, through the same analyses")
    read.add_argument("path")
    read.add_argument("--domain", default="")
    read.add_argument("--layer", choices=["milestone", "track", "source"], default="milestone")
    inv = commands.add_parser("invariance", help="same states, different acts? domains compared at each level")
    scope(inv, domain=False)
    inv.add_argument("--min-trajectories", type=int, default=80)
    inv.add_argument("--repeats", type=int, default=50)
    inv.add_argument("--draws", type=int, default=0, help="also run the grouping and order nulls, with this many paired draws")
    decide = commands.add_parser("decide", help="the decision model: assumes an actor pursuing the scheme's goal")
    scope(decide)
    decide.add_argument("--layer", choices=["milestone", "track"], default="milestone")
    decide.add_argument("--nulls", type=int, default=100)
    decide.add_argument("--baseline", type=int, default=20, help="draws of shuffled act order to fit beta on")
    laws = commands.add_parser("laws", help="backbone, contact primacy, maintenance, the exploitation predicate")
    scope(laws, domain=False)
    report = commands.add_parser("report", help="every analysis, to one JSON file")
    report.add_argument("--out", default="data/extracted/esm/report.json")
    report.add_argument("--nulls", type=int, default=100)
    report.add_argument("--repeats", type=int, default=50)
    report.add_argument("--draws", type=int, default=200)
    report.add_argument("--decision", action="store_true", help="also run the decision model, which assumes the scheme's goal")
    graphs = commands.add_parser("graphs", help="write trajectory and model graphs in the trajectories and means extensions")
    scope(graphs, domain=False)
    graphs.add_argument("--gate", action="store_true", help="validate every graph with the SDK gate")
    graphs.add_argument("--workers", type=int, default=1)
    graphs.add_argument("--min-model-trajectories", type=int, default=15)
    args = parser.parse_args(argv)

    from state_machines import analysis

    if args.command == "groupings":
        out = analysis.groupings_report(kind=args.kind, randoms=args.randoms)
    elif args.command == "scheme":
        out = analysis.scheme_report()
        if args.gate:
            from state_machines import ontology

            out = {"written": ontology.scheme_graph(check=True), "states": len(out["states"])}
    elif args.command == "read":
        out = analysis.external(args.path, domain=args.domain, layer=args.layer)
    elif args.command == "machine":
        out = analysis.machine_report(kind=args.kind, domain=args.domain, layer=args.layer, level=args.level)
    elif args.command == "invariance":
        out = analysis.invariance_report(kind=args.kind, minimum=args.min_trajectories, repeats=args.repeats, draws=args.draws)
    elif args.command == "decide":
        out = analysis.decision_report(kind=args.kind, domain=args.domain, layer=args.layer, nulls=args.nulls, baseline=args.baseline)
    elif args.command == "laws":
        out = analysis.laws_report(kind=args.kind)
    elif args.command == "report":
        out = analysis.full(nulls=args.nulls, repeats=args.repeats, draws=args.draws, decision=args.decision)
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
        out = {"written": str(path)}
    else:
        out = _graphs(args)
    print(json.dumps(out, indent=2, default=str))
    return 0


def _record(args: tuple[dict, bool]) -> dict:
    from state_machines import ontology

    trajectory, check = args
    try:
        return ontology.record_graph(trajectory, check=check)
    except Exception as error:  # report it, keep going
        return {"record_id": trajectory["record_id"], "error": f"{type(error).__name__}: {error}"}


def _graphs(args: argparse.Namespace) -> dict:
    from collections import Counter
    from concurrent.futures import ProcessPoolExecutor

    from state_machines import analysis, ontology

    from process_mining import trajectory as trajectories_layer
    from extraction import store

    found = [t for t in trajectories_layer.build(store.connect(), kind=args.kind, with_detection=True) if t["domain"] not in analysis.MIXED]
    jobs = [(t, args.gate) for t in found]
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(_record, jobs, chunksize=8))
    else:
        rows = [_record(job) for job in jobs]
    out: dict = {"records": Counter(), "models": []}
    for row in rows:
        out["records"]["error" if "error" in row else "skipped" if "skipped" in row else "written"] += 1
        if "conforms" in row:
            out["records"]["conforming" if row["conforms"] else "not_conforming"] += 1
    label = args.kind or "all"
    grouped: dict[str, list[dict]] = {}
    for t in found:
        grouped.setdefault(t["domain"], []).append(t)
    for domain, items in sorted(grouped.items()):
        if len(items) < args.min_model_trajectories:
            continue
        for layer in analysis.LAYERS:
            result = ontology.model_graph(items, f"{domain}-{label}", layer=layer, check=args.gate)
            out["models"].append({k: v for k, v in result.items() if k not in ("path", "sha256")})
    out["records"] = dict(out["records"])
    return out


if __name__ == "__main__":
    sys.exit(main())
