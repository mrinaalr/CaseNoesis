"""The analyses, assembled: one call per question, plain data out. No record text, no names."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from extraction import store
from process_mining import trajectory as trajectories_layer
from state_machines import coverage, invariance, machine as m, mdp, states as st

# Court folders that hold filings of every kind, not one offense domain.
MIXED = ("bulk", "transcripts")


def load(*, kind: str = "", domain: str = "", db=None) -> list[dict[str, Any]]:
    found = trajectories_layer.build(db or store.connect(), kind=kind, domain=domain, with_detection=True)
    return [t for t in found if t["domain"] not in MIXED]


def by_domain(trajectories: list[dict[str, Any]], minimum: int) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trajectories:
        grouped[t["domain"]].append(t)
    return {d: items for d, items in sorted(grouped.items()) if len(items) >= minimum}


def machine_report(*, kind: str = "", domain: str = "", level: str = "act", db=None) -> dict[str, Any]:
    fitted = m.fit(load(kind=kind, domain=domain, db=db), level=level)
    return {**fitted.summary(), "policy": {s: fitted.policy(s) for s in (st.START, *st.STATES)}, "transitions": fitted.estimates(minimum=5)}


def invariance_report(*, kind: str = "", minimum: int = 80, repeats: int = 50, db=None) -> dict[str, Any]:
    found = load(kind=kind, db=db)
    grouped = by_domain(found, minimum)
    if len(grouped) < 2:
        return {"error": "fewer than two domains have enough trajectories", "domains": {d: len(v) for d, v in grouped.items()}}
    out = {"all_domains": invariance.test(grouped, repeats=repeats), "pairs": invariance.pairs(grouped),
           "state_transitions": invariance.state_transitions(grouped)}
    large = {d: v for d, v in grouped.items() if len(v) >= 1000}
    if len(large) >= 2:
        out["large_domains"] = invariance.test(large, size=min(1500, min(len(v) for v in large.values())), repeats=max(10, repeats // 5))
    return out


def decision_report(*, kind: str = "", domain: str = "", nulls: int = 100, sensitivity: bool = True, db=None) -> dict[str, Any]:
    found = load(kind=kind, domain=domain, db=db)
    fitted = m.fit(found)
    models = [mdp.uniform()]
    researcher = mdp.declared()
    if researcher is not None:
        models.append(researcher)
    out: dict[str, Any] = {"trajectories": fitted.trajectories, "cost_models": []}
    for costs in models:
        solution = mdp.solve(fitted, costs)
        out["cost_models"].append({"name": costs.name, "paths": mdp.paths(found, fitted, solution),
                                   "agreement": mdp.agreement(found, fitted, solution),
                                   "rationality": mdp.rationality(found, fitted, costs, nulls=nulls)})
    if sensitivity:
        out["cutoff_sensitivity"] = mdp.sensitivity(found, models[0], nulls=max(20, nulls // 4))
    if researcher is None:
        out["note"] = "No researcher cost table (config/esm_costs.json). Only the uniform model was tested."
    return out


def laws_report(*, kind: str = "", db=None) -> dict[str, Any]:
    found = load(kind=kind, db=db)
    minimum = 15 if kind == "court" else 25
    return {"coverage": coverage.coverage(found, minimum=minimum), "laws": coverage.laws(found, minimum=15),
            "intervention": coverage.intervention(found, minimum=minimum), "predicate": coverage.predicate(found)}


def full(*, nulls: int = 100, repeats: int = 50, db=None) -> dict[str, Any]:
    db = db or store.connect()
    out: dict[str, Any] = {}
    for label, kind in (("all_records", ""), ("court_filings", "court")):
        out[label] = {"machine": machine_report(kind=kind, db=db),
                      "invariance": invariance_report(kind=kind, minimum=80 if not kind else 40, repeats=repeats, db=db),
                      "decision": decision_report(kind=kind, nulls=nulls, sensitivity=not kind, db=db),
                      "laws": laws_report(kind=kind, db=db)}
    return out
