"""The analyses, assembled: one call per question, plain data out.

Every function reads trajectories from the engine's store and returns
numbers with the counts behind them. The command line and the MCP server
call these. Nothing here reads text from a record or returns a name.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from extraction import store
from process_mining import trajectory as trajectories_layer
from state_machines import coverage, machine as m, mdp, states as state_layer

# Court folders that hold filings of every kind, not one offense domain.
MIXED = ("bulk", "transcripts")


def load(*, kind: str = "", domain: str = "", db=None) -> list[dict[str, Any]]:
    """Trajectories with detection kept, offense domains only."""
    found = trajectories_layer.build(db or store.connect(), kind=kind, domain=domain, with_detection=True)
    return [t for t in found if t["domain"] not in MIXED]


def by_domain(trajectories: list[dict[str, Any]], minimum: int) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trajectories:
        grouped[t["domain"]].append(t)
    return {d: items for d, items in sorted(grouped.items()) if len(items) >= minimum}


def machine_report(*, kind: str = "", domain: str = "", level: str = "act", db=None) -> dict[str, Any]:
    """The fitted machine: summary, the observed policy at each state, and transition estimates with counts."""
    fitted = m.fit(load(kind=kind, domain=domain, db=db), level=level)
    return {**fitted.summary(), "policy": {s: fitted.policy(s) for s in (m.START, *fitted.states)},
            "transitions": fitted.estimates(minimum=5)}


def states_report(*, kind: str = "", min_trajectories: int = 50, resamples: int = 20, db=None) -> dict[str, Any]:
    """Learned states per domain, and whether they hold across domains."""
    grouped = by_domain(load(kind=kind, db=db), 0)
    seqs = {d: s for d, s in ((d, state_layer.sequences(items)) for d, items in grouped.items()) if len(s) >= min_trajectories}
    if len(seqs) < 2:
        return {"error": "fewer than two domains have enough trajectories", "domains": {d: len(s) for d, s in seqs.items()}}
    return state_layer.invariance(seqs, resamples=resamples)


def decision_report(*, kind: str = "", domain: str = "", goal: tuple[str, ...] = ("harm",), nulls: int = 100, db=None) -> dict[str, Any]:
    """The decision model under each available cost model: L*, how observed paths compare, and the tests."""
    found = load(kind=kind, domain=domain, db=db)
    fitted = m.fit(found)
    models = [mdp.uniform(goal), mdp.uniform(goal, disruption_cost=0.0)]
    researcher = mdp.declared(goal=goal)
    if researcher is not None:
        models.append(researcher)
    out = {"trajectories": fitted.trajectories, "goal": list(goal), "cost_models": []}
    for costs in models:
        solution = mdp.solve(fitted, costs)
        out["cost_models"].append({
            "name": costs.name, "disruption_cost": costs.disruption_cost,
            "paths": mdp.paths(found, fitted, solution),
            "agreement": mdp.agreement(found, fitted, solution),
            "rationality": mdp.rationality(found, fitted, costs, nulls=nulls),
        })
    if researcher is None:
        out["note"] = "No researcher cost table (config/esm_costs.json). Only the uniform model was tested."
    return out


def coverage_report(*, kind: str = "", goal: tuple[str, ...] = ("harm",), min_trajectories: int = 25, db=None) -> dict[str, Any]:
    found = load(kind=kind, db=db)
    return {"coverage": coverage.coverage(found, min_trajectories=min_trajectories),
            "intervention": coverage.intervention(found, goal, min_trajectories=min_trajectories)}


def full(*, nulls: int = 100, resamples: int = 20, db=None) -> dict[str, Any]:
    """Every analysis, for all records and for court filings alone."""
    db = db or store.connect()
    out: dict[str, Any] = {}
    for label, kind in (("all_records", ""), ("court_filings", "court")):
        out[label] = {
            "machine": machine_report(kind=kind, db=db),
            "states": states_report(kind=kind, min_trajectories=50 if not kind else 15, resamples=resamples, db=db),
            "decision": decision_report(kind=kind, nulls=nulls, db=db),
            "coverage": coverage_report(kind=kind, min_trajectories=25 if not kind else 15, db=db),
        }
    return out
