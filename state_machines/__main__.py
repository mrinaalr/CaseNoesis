"""Command line for the Exploitation State Machine.

    python -m state_machines machine --kind court          the fitted machine: action space, policy, T with counts
    python -m state_machines states --kind court           learned states per domain, and whether they hold across domains
    python -m state_machines decide --domain fraud         L*, observed paths beside it, and the rationality test
    python -m state_machines coverage                      backbone by coverage threshold, and intervention by state
    python -m state_machines report                        every analysis, to data/extracted/esm/report.json
    python -m state_machines graphs --kind court --gate    trajectory graphs per record, and a fitted model per domain

Run `python -m extraction conduct` first: the machine is fitted to its acts.
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

    machine = commands.add_parser("machine", help="the fitted machine")
    scope(machine)
    machine.add_argument("--level", choices=["act", "means"], default="act")
    states = commands.add_parser("states", help="learned states, and whether they hold across domains")
    scope(states, domain=False)
    states.add_argument("--min-trajectories", type=int, default=50)
    states.add_argument("--resamples", type=int, default=20)
    decide = commands.add_parser("decide", help="the goal-conditioned decision model and its tests")
    scope(decide)
    decide.add_argument("--goal", default="harm", help="goal state, or several joined by commas")
    decide.add_argument("--nulls", type=int, default=100)
    cover = commands.add_parser("coverage", help="backbone and intervention")
    scope(cover, domain=False)
    cover.add_argument("--goal", default="harm")
    report = commands.add_parser("report", help="every analysis, to one JSON file")
    report.add_argument("--out", default="data/extracted/esm/report.json")
    report.add_argument("--nulls", type=int, default=100)
    report.add_argument("--resamples", type=int, default=20)
    graphs = commands.add_parser("graphs", help="write trajectory and model graphs in the trajectories and means extensions")
    scope(graphs, domain=False)
    graphs.add_argument("--gate", action="store_true", help="validate every graph with the SDK gate")
    graphs.add_argument("--workers", type=int, default=1)
    graphs.add_argument("--min-model-trajectories", type=int, default=15)
    args = parser.parse_args(argv)

    from state_machines import analysis

    if args.command == "machine":
        out = analysis.machine_report(kind=args.kind, domain=args.domain, level=args.level)
    elif args.command == "states":
        out = analysis.states_report(kind=args.kind, min_trajectories=args.min_trajectories, resamples=args.resamples)
    elif args.command == "decide":
        out = analysis.decision_report(kind=args.kind, domain=args.domain, goal=tuple(args.goal.split(",")), nulls=args.nulls)
    elif args.command == "coverage":
        out = analysis.coverage_report(kind=args.kind, goal=tuple(args.goal.split(",")))
    elif args.command == "report":
        out = analysis.full(nulls=args.nulls, resamples=args.resamples)
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

    found = analysis.load(kind=args.kind)
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
    for domain, items in analysis.by_domain(found, args.min_model_trajectories).items():
        result = ontology.model_graph(items, f"{domain}-{label}", check=args.gate)
        out["models"].append({k: v for k, v in result.items() if k not in ("path", "sha256")})
    out["records"] = dict(out["records"])
    return out


if __name__ == "__main__":
    sys.exit(main())
