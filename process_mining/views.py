"""Read-only answers for the command line and the MCP server.

Every function reads the `events` table the engine built and returns plain
data. None writes, and none returns text from a record.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date
from statistics import median
from typing import Any

from extraction import events as events_layer, store
from process_mining import conform, discover, log as log_layer, trajectory

# `offense` is when the conduct began, not a step of the prosecution. Models leave it out unless asked.
PROCEDURAL = ("arrest", "complaint", "indictment", "information", "charge", "plea", "verdict", "conviction", "sentencing")


def _db(db: sqlite3.Connection | None) -> sqlite3.Connection:
    return db or store.connect()


def _traces(db: sqlite3.Connection, dated_only: bool, domain: str | None, with_offense: bool) -> list[log_layer.Trace]:
    return log_layer.build(db, dated_only=dated_only, domain=domain or None, kinds=None if with_offense else PROCEDURAL)


def log_summary(db: sqlite3.Connection | None = None) -> dict[str, Any]:
    db = _db(db)
    traces = log_layer.build(db)
    kinds: Counter = Counter(event["type"] for trace in traces for event in trace.events)
    return {**log_layer.summary(traces), "events_by_kind": dict(kinds.most_common())}


def variants(db: sqlite3.Connection | None = None, *, level: str = "detailed", dated_only: bool = False,
             domain: str = "", with_offense: bool = False, limit: int = 20) -> dict[str, Any]:
    """The distinct paths, most common first, each with its share of traces."""
    traces = _traces(_db(db), dated_only, domain, with_offense)
    counts = discover.variants(trace.activities(level) for trace in traces)
    total = sum(counts.values())
    return {
        "traces": total, "distinct_paths": len(counts), "level": level, "dated_only": dated_only,
        "paths": [{"path": list(path), "traces": count, "share": round(count / total, 4)} for path, count in counts.most_common(limit)],
    }


def _timing(traces: list[log_layer.Trace], level: str) -> dict[tuple[str, str], list[int]]:
    names = log_layer.LEVELS[level]
    gaps: dict[tuple[str, str], list[int]] = defaultdict(list)
    for trace in traces:
        for left, right in zip(trace.events, trace.events[1:]):
            if left["precision"] == "day" and right["precision"] == "day":
                days = (date.fromisoformat(right["date"]) - date.fromisoformat(left["date"])).days
                gaps[(names.get(left["type"], left["type"]), names.get(right["type"], right["type"]))].append(days)
    return gaps


def model(db: sqlite3.Connection | None = None, *, level: str = "detailed", noise: float = 0.2, dated_only: bool = False,
          domain: str = "", with_offense: bool = False) -> dict[str, Any]:
    """The discovered model: a process tree, how well the log replays on it,
    and the directly-follows graph with the days between steps."""
    traces = _traces(_db(db), dated_only, domain, with_offense)
    counts = discover.variants(trace.activities(level) for trace in traces)
    tree = discover.mine(counts, noise)
    dfg = discover.directly_follows(counts)
    gaps = _timing(traces, level)
    try:
        replay: dict[str, Any] = conform.fitness(counts, tree)
    except discover.TooLarge:
        replay = {"error": "the model allows too many paths to list; raise the noise threshold or use the coarse level"}
    return {
        "traces": sum(counts.values()), "level": level, "noise": noise, "dated_only": dated_only,
        "tree": discover.as_dict(tree), "tree_text": discover.show(tree), "replay": replay,
        "starts": dict(dfg["starts"].most_common()), "ends": dict(dfg["ends"].most_common()),
        "directly_follows": [
            {"from": left, "to": right, "traces": count,
             **({"median_days": median(gaps[(left, right)]), "timed": len(gaps[(left, right)])} if gaps.get((left, right)) else {})}
            for (left, right), count in dfg["edges"].most_common(40)
        ],
    }


def conformance(db: sqlite3.Connection | None = None, *, domain: str = "", limit: int = 20) -> dict[str, Any]:
    """Departures from procedural order, over every trace."""
    traces = _traces(_db(db), False, domain, True)
    result = conform.check_log(traces)
    result["flagged"] = result["flagged"][:limit]
    return result


# ---------------------------------------------------------------------------
# Conduct: the offense itself
# ---------------------------------------------------------------------------

def conduct_summary(db: sqlite3.Connection | None = None) -> dict[str, Any]:
    """What the conduct layer holds: records with acts, acts by kind, how many carry a date or a named technology."""
    db = _db(db)
    q = lambda sql: db.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "records_with_acts": q("SELECT COUNT(DISTINCT record_id) FROM conduct"),
        "acts": q("SELECT COUNT(*) FROM conduct"),
        "acts_with_a_date": q("SELECT COUNT(*) FROM conduct WHERE date IS NOT NULL"),
        "acts_naming_a_technology": q("SELECT COUNT(*) FROM conduct WHERE means != '{}'"),
        "acts_settled_by_two_families": q("SELECT COUNT(*) FROM conduct WHERE status = 'agreed'"),
        "by_kind": {row[0]: row[1] for row in db.execute("SELECT kind, COUNT(*) FROM conduct GROUP BY kind ORDER BY 2 DESC")},
        "by_record_kind": {row[0]: row[1] for row in db.execute(
            "SELECT r.kind, COUNT(DISTINCT c.record_id) FROM conduct c JOIN records r ON r.record_id = c.record_id GROUP BY r.kind")},
        "trajectories_of_two_or_more_acts": len(trajectory.build(db)),
    }


def conduct_paths(db: sqlite3.Connection | None = None, *, level: str = "act", domain: str = "", kind: str = "",
                  noise: float = 0.2, limit: int = 15) -> dict[str, Any]:
    """The paths offenses take at one level of abstraction (means, act or phase): the
    most common paths, and the model the Inductive Miner finds for them."""
    found = trajectory.build(_db(db), domain=domain, kind=kind)
    counts = discover.variants(trajectory.path(t, level) for t in found)
    total = sum(counts.values())
    out: dict[str, Any] = {
        "level": level, "trajectories": total, "distinct_paths": len(counts),
        "paths": [{"path": list(p), "trajectories": n, "share": round(n / total, 4)} for p, n in counts.most_common(limit)],
    }
    if total and level != "means":
        tree = discover.mine(counts, noise)
        out["tree_text"] = discover.show(tree)
        try:
            out["replay"] = {k: v for k, v in conform.fitness(counts, tree).items() if k != "least_fitting"}
        except discover.TooLarge:
            out["replay"] = {"note": "the model allows too many paths to list"}
    return out


def conduct_transitions(db: sqlite3.Connection | None = None, *, level: str = "act", domain: str = "", kind: str = "") -> dict[str, Any]:
    return trajectory.transitions(trajectory.build(_db(db), domain=domain, kind=kind), level)


def conduct_compare(db: sqlite3.Connection | None = None, *, kind: str = "", min_trajectories: int = 25) -> dict[str, Any]:
    return trajectory.compare(trajectory.build(_db(db), kind=kind), min_trajectories=min_trajectories)


def conduct_means(db: sqlite3.Connection | None = None, *, domain: str = "", kind: str = "") -> dict[str, Any]:
    return trajectory.means_by_act(trajectory.build(_db(db), domain=domain, kind=kind, min_acts=1))


def conduct_record(record_id: str, db: sqlite3.Connection | None = None) -> dict[str, Any]:
    """One record's acts in the order it tells them, with the path at each level."""
    from extraction import conduct as conduct_layer

    db = _db(db)
    acts = conduct_layer.sequence(db, record_id)
    if not acts:
        return {"record_id": record_id, "acts": [], "note": "no settled act; the record may narrate none, or its wording is outside the readers' vocabulary"}
    shaped = {"acts": [{**act, "phase": trajectory.act_rules.PHASE[act["kind"]]} for act in acts]}
    return {"record_id": record_id, "acts": shaped["acts"], "told_in_date_order": conduct_layer.in_date_order(acts),
            "paths": {level: list(trajectory.path(shaped, level)) for level in trajectory.LEVELS}}


def case(case_id: str, db: sqlite3.Connection | None = None, *, level: str = "detailed", noise: float = 0.2) -> dict[str, Any]:
    """One case: its events in order, each defendant's path against the
    discovered model, and any departure from procedural order."""
    db = _db(db)
    row = db.execute("SELECT case_id FROM cases WHERE case_id = ? OR record_id = ? LIMIT 1", (case_id, case_id)).fetchone()
    if row is None:
        return {"error": f"no case or record {case_id}"}
    case_id = row["case_id"]
    everything = log_layer.build(db)
    procedural = _traces(db, False, None, False)
    tree = discover.mine(discover.variants(trace.activities(level) for trace in procedural), noise)
    try:
        allowed: set[tuple[str, ...]] | None = discover.language(tree)
    except discover.TooLarge:
        allowed = None
    defendants = []
    for trace in everything:
        if trace.case_id != case_id:
            continue
        own = next((t for t in procedural if (t.case_id, t.person) == (trace.case_id, trace.person)), None)
        entry: dict[str, Any] = {"person": trace.person, "path": list(trace.activities(level)), "departures_from_procedure": conform.check_order(trace)}
        if own is not None and allowed is not None:
            entry["against_the_model"] = conform.align(own.activities(level), allowed)
        defendants.append(entry)
    return {
        "case_id": case_id,
        "records": [r["record_id"] for r in db.execute("SELECT record_id FROM cases WHERE case_id = ? ORDER BY record_id", (case_id,))],
        "timeline": events_layer.timeline(db, case_id),
        "defendants": defendants,
    }
