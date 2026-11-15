"""The analyses, assembled: one call per question, plain data out. No record text, no names.

Each takes walks from any reader. `load` reads the corpus's acts; `external` reads a graph or a
JSON file of walks, so a hand-built close-read is analyzed by the same code as the corpus.

`groupings_report` describes states with no scheme and no goal: several groupings of the acts,
one of them learned from the data, on equal terms. The ESM analyses read the same acts through the
ESM scheme. The decision model assumes an actor pursuing the scheme's goal; it runs only when asked
for, and its rationality is reported beside the same fit on records whose acts were shuffled.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from state_machines import coverage, groupings, invariance, machine as m, mdp, readers
from state_machines import scheme as sc
from state_machines.scheme import Scheme
from state_machines.walks import Walk, from_start, path, predicate, unplaced

# Court folders that hold filings of every kind, not one offense domain.
MIXED = ("bulk", "transcripts")
LAYERS = ("milestone", "track")


def records(*, kind: str = "", domain: str = "", db=None) -> list[dict[str, Any]]:
    """Each record's acts, in order, for the offense domains."""
    from extraction import store
    from process_mining import trajectory as trajectories_layer

    found = trajectories_layer.build(db or store.connect(), kind=kind, domain=domain, with_detection=True)
    return [t for t in found if t["domain"] not in MIXED]


def load(*, kind: str = "", domain: str = "", db=None, scheme: Scheme | None = None) -> tuple[list[Walk], Scheme]:
    scheme = scheme or sc.load()
    return [readers.from_conduct(t, scheme) for t in records(kind=kind, domain=domain, db=db)], scheme


def nulls_of(found: list[dict[str, Any]], scheme: Scheme, *, minimum: int = 80, draws: int = 200, large: int = 1000) -> dict[str, Any]:
    """The grouping and order nulls for the state level, at both layers, on the same domain sets as `invariance_of`."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in found:
        if t["acts"]:
            grouped[t["domain"]].append(t)
    read = lambda t: readers.from_conduct(t, scheme)  # noqa: E731
    kinds = sorted(readers.ROLE)
    out: dict[str, Any] = {}
    for label, threshold, size in (("all_domains", minimum, None), ("large_domains", large, 1500)):
        sets = {d: v for d, v in grouped.items() if len(v) >= threshold}
        if len(sets) < 2:
            continue
        cap = min(size or 10**9, min(len(v) for v in sets.values()))
        out[label] = {layer: invariance.nulls(sets, scheme, read, kinds=kinds, layer=layer, size=cap,
                                              draws=draws if label == "all_domains" else max(20, draws // 5))
                      for layer in LAYERS}
    return out


def groupings_report(*, kind: str = "", randoms: int = 100, repeats: int = 20, db=None, found=None) -> dict[str, Any]:
    """States with no scheme and no goal: groupings of the acts described on the same measures."""
    found = found if found is not None else records(kind=kind, db=db)
    return groupings.compare(found, minimum=80 if not kind else 40, randoms=randoms, repeats=repeats)


def beta_on_shuffled(found: list[dict[str, Any]], scheme: Scheme, *, draws: int = 20, layer: str = "milestone", seed: int = 8252) -> dict[str, Any]:
    """The rationality fit on the same records with each record's acts in a random order: what beta is
    when the order carries nothing. The observed beta is read against this, not against zero."""
    import random

    betas = []
    for draw in range(draws):
        rng = random.Random(seed + draw)
        walks = from_start([readers.from_conduct(invariance._reorder(t, rng), scheme) for t in found], scheme, layer=layer)
        fitted = m.fit(walks, scheme, layer=layer)
        betas.append(mdp.rationality(walks, fitted, mdp.uniform(), nulls=0)["beta"])
    ordered = sorted(betas)
    n = len(ordered)
    return {"draws": n, "beta_mean": round(sum(betas) / n, 3), "beta_p05": ordered[int(0.05 * (n - 1))],
            "beta_p95": ordered[int(0.95 * (n - 1))], "betas": betas}


def without_payer_rule(found: list[dict[str, Any]], *, db=None, source=None) -> list[dict[str, Any]]:
    """The same records with each payment act read as the verb alone reads it, before #8's payer rule:
    a payment verb is a `transfer` whoever paid. Rebuilt from each act's stored span."""
    from extraction import acts as act_rules, store
    from extraction.source import CorpusSource

    db = db or store.connect()
    source = source or CorpusSource()
    wanted = {t["record_id"] for t in found}
    old: dict[str, list[str]] = defaultdict(list)
    current, text = None, ""
    for row in db.execute("SELECT record_id, kind, span_start, span_end FROM conduct ORDER BY record_id, position"):
        if row["record_id"] not in wanted:
            continue
        if row["record_id"] != current:
            current, text = row["record_id"], source.text(row["record_id"]) or ""
        kind, s, e = row["kind"], row["span_start"], row["span_end"]
        if kind in ("supply", "movement") and act_rules.by_verb(text[s:e], text[e:e + 400], text[max(0, s - 20):s]) == "transfer":
            kind = "transfer"
        old[row["record_id"]].append(kind)
    out = []
    for t in found:
        kinds = old.get(t["record_id"], [])
        if len(kinds) != len(t["acts"]):
            out.append(t)
            continue
        out.append({**t, "acts": [{**a, "kind": k} for a, k in zip(t["acts"], kinds)]})
    return out


def predicate_by_payer_rule(found: list[dict[str, Any]], scheme: Scheme, *, db=None, minimum: int = 15) -> dict[str, Any]:
    """The exploitation predicate by domain, with and without the payer rule, so it is visible how much
    of the separation the rule makes."""
    before = without_payer_rule(found, db=db)
    count = lambda rows: sum(1 for t in rows for a in t["acts"] if a["kind"] == "transfer")  # noqa: E731
    return {"with_payer_rule": {"transfers": count(found), "by_domain": coverage.predicate([readers.from_conduct(t, scheme) for t in found], scheme, minimum=minimum)},
            "without_payer_rule": {"transfers": count(before), "by_domain": coverage.predicate([readers.from_conduct(t, scheme) for t in before], scheme, minimum=minimum)}}


def by_domain(walks: list[Walk], minimum: int) -> dict[str, list[Walk]]:
    grouped: dict[str, list[Walk]] = defaultdict(list)
    for w in walks:
        grouped[w.domain].append(w)
    return {d: items for d, items in sorted(grouped.items()) if len(items) >= minimum}


def machine_of(walks: list[Walk], scheme: Scheme, *, layer: str = "milestone", level: str = "act") -> dict[str, Any]:
    fitted = m.fit(walks, scheme, layer=layer, level=level)
    return {**fitted.summary(), "policy": {s: fitted.policy(s) for s in fitted.states}, "transitions": fitted.estimates(minimum=5)}


def machine_report(*, kind: str = "", domain: str = "", layer: str = "milestone", level: str = "act", db=None) -> dict[str, Any]:
    walks, scheme = load(kind=kind, domain=domain, db=db)
    return machine_of(walks, scheme, layer=layer, level=level)


def invariance_of(walks: list[Walk], scheme: Scheme, *, minimum: int = 80, repeats: int = 50) -> dict[str, Any]:
    grouped = by_domain(walks, minimum)
    if len(grouped) < 2:
        return {"error": "fewer than two domains have enough trajectories", "domains": {d: len(v) for d, v in grouped.items()}}
    out: dict[str, Any] = {}
    for layer in LAYERS:
        out[layer] = {"all_domains": invariance.test(grouped, scheme, layer=layer, repeats=repeats),
                      "pairs": invariance.pairs(grouped, scheme, layer=layer),
                      "state_transitions": invariance.state_transitions(grouped, scheme, layer=layer)}
        large = {d: v for d, v in grouped.items() if len(v) >= 1000}
        if len(large) >= 2:
            out[layer]["large_domains"] = invariance.test(large, scheme, layer=layer, size=min(1500, min(len(v) for v in large.values())),
                                                          repeats=max(10, repeats // 5))
    return out


def invariance_report(*, kind: str = "", minimum: int = 80, repeats: int = 50, draws: int = 0, db=None) -> dict[str, Any]:
    """The comparison of domains, and with `draws` the grouping and order nulls beside it."""
    scheme = sc.load()
    found = records(kind=kind, db=db)
    out = invariance_of([readers.from_conduct(t, scheme) for t in found], scheme, minimum=minimum, repeats=repeats)
    if draws:
        out["nulls"] = nulls_of(found, scheme, minimum=minimum, draws=draws)
    return out


def decision_of(walks: list[Walk], scheme: Scheme, *, layer: str = "milestone", nulls: int = 100, sensitivity: bool = True,
                complete_only: bool = True) -> dict[str, Any]:
    """The decision model and its fit. By default on walks told from preparation or contact: a telling that
    begins at the payment would make a one-act path to the goal feasible by construction."""
    every = walks
    if complete_only:
        walks = from_start(walks, scheme, layer=layer)
    fitted = m.fit(walks, scheme, layer=layer)
    models = [mdp.uniform()]
    researcher = mdp.declared()
    if researcher is not None:
        models.append(researcher)
    out: dict[str, Any] = {"layer": layer, "goal": sorted(scheme.goal), "walks_told_from_start_only": complete_only,
                           "trajectories": fitted.trajectories, "of_all_walks": len(every), "cost_models": []}
    for costs in models:
        solution = mdp.solve(fitted, costs)
        out["cost_models"].append({"name": costs.name, "paths": mdp.paths(walks, fitted, solution),
                                   "agreement": mdp.agreement(walks, fitted, solution),
                                   "rationality": mdp.rationality(walks, fitted, costs, nulls=nulls)})
    if sensitivity:
        out["cutoff_sensitivity"] = mdp.sensitivity(walks, scheme, models[0], layer=layer, nulls=max(20, nulls // 4))
    if researcher is None:
        out["note"] = "No researcher cost table (config/esm_costs.json). Only the uniform model was tested."
    return out


def decision_report(*, kind: str = "", domain: str = "", layer: str = "milestone", nulls: int = 100, sensitivity: bool = True,
                    baseline: int = 20, db=None) -> dict[str, Any]:
    scheme = sc.load()
    found = records(kind=kind, domain=domain, db=db)
    out = decision_of([readers.from_conduct(t, scheme) for t in found], scheme, layer=layer, nulls=nulls, sensitivity=sensitivity)
    if baseline:
        out["beta_on_shuffled_order"] = beta_on_shuffled(found, scheme, draws=baseline, layer=layer)
    return out


def laws_of(walks: list[Walk], scheme: Scheme, *, minimum: int = 25) -> dict[str, Any]:
    return {"coverage": {layer: coverage.coverage(walks, scheme, layer=layer, minimum=minimum) for layer in LAYERS},
            "laws": coverage.laws(walks, scheme, minimum=15), "intervention": coverage.intervention(walks, scheme, minimum=minimum),
            "tracks": coverage.tracks(walks, scheme, minimum=minimum), "predicate": coverage.predicate(walks, scheme)}


def laws_report(*, kind: str = "", db=None) -> dict[str, Any]:
    walks, scheme = load(kind=kind, db=db)
    return laws_of(walks, scheme, minimum=15 if kind == "court" else 25)


def scheme_report() -> dict[str, Any]:
    return sc.load().describe()


def external(source: str, *, domain: str = "", layer: str = "milestone") -> dict[str, Any]:
    """Read a graph (.ttl) or walks (.json) and run every analysis the walks are enough for."""
    walks, scheme, read = readers.read(Path(source), sc.load(), domain=domain)
    out: dict[str, Any] = {"read": read, "walks": [{"id": w.id, "domain": w.domain, "events": len(w.events),
                                                    "unplaced": unplaced(w, scheme, "milestone"),
                                                    **{f"path_{lay}": path(w, scheme, lay) for lay in (*LAYERS, "source")},
                                                    "predicate": predicate(w, scheme), **w.meta} for w in walks]}
    if walks:
        out["machine"] = machine_of(walks, scheme, layer=layer)
        fitted = m.fit(walks, scheme, layer=layer, min_count=1, min_share=0.0)
        solution = mdp.solve(fitted, mdp.uniform())
        out["decision"] = {"note": "Every observed action is feasible: there are too few walks for a cutoff.",
                           "optimal_path": mdp.optimal_path(fitted, solution)}
    return out


def full(*, nulls: int = 100, repeats: int = 50, draws: int = 200, decision: bool = False, db=None) -> dict[str, Any]:
    """Every description, for all records and for court filings. With `decision`, also the decision
    model, which assumes an actor pursuing the scheme's goal."""
    from extraction import store

    db = db or store.connect()
    scheme = sc.load()
    out: dict[str, Any] = {"scheme": f"{scheme.name} {scheme.version}"}
    for label, kind in (("all_records", ""), ("court_filings", "court")):
        found = records(kind=kind, db=db)
        walks = [readers.from_conduct(t, scheme) for t in found]
        row: dict[str, Any] = {
            "groupings": groupings_report(kind=kind, found=found, randoms=nulls),
            "esm": {"machine": {layer: machine_of(walks, scheme, layer=layer) for layer in LAYERS},
                    "invariance": invariance_of(walks, scheme, minimum=80 if not kind else 40, repeats=repeats),
                    "invariance_nulls": nulls_of(found, scheme, minimum=80 if not kind else 40, draws=draws),
                    "laws": laws_of(walks, scheme, minimum=15 if kind == "court" else 25),
                    "predicate_by_payer_rule": predicate_by_payer_rule(found, scheme, db=db, minimum=15 if kind == "court" else 25)}}
        if decision:
            row["decision"] = {"assumes": f"an actor pursuing {sorted(scheme.goal)}, under the uniform cost model unless a table is declared",
                               **{layer: decision_of(walks, scheme, layer=layer, nulls=nulls, sensitivity=not kind and layer == "milestone")
                                  for layer in LAYERS},
                               "all_walks": decision_of(walks, scheme, nulls=max(20, nulls // 4), sensitivity=False, complete_only=False),
                               "beta_on_shuffled_order": beta_on_shuffled(found, scheme, draws=20)}
        out[label] = row
    return out

