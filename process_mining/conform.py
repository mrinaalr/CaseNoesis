"""Conformance: how one case departs from the usual path, and from procedure.

Two different questions, answered separately.

**Against the discovered model.** The model is what cases usually do. An
alignment (Adriansyah, van Dongen and van der Aalst, 2011) pairs a trace with
the closest trace the model allows and counts what is left over: events the
trace has that the model does not allow there, and steps the model expects
that the trace lacks. Fitness is one minus that count over the worst case. A
low-fitness trace took an unusual path. It is not thereby a wrong one.

The closest model trace is found by listing what the model allows, with
loops taken a bounded number of times, and taking the one with the longest
common subsequence. That is exact for models and traces of the size a
prosecution produces, and it fails loudly (`TooLarge`) when a model allows too
much to list.

**Against procedure.** A federal prosecution has an order that does not
depend on what cases usually do: a charge comes before a plea, a conviction
before a sentence. The records are incomplete, so a missing step means only
that no record mentioned it, and is never counted. What is counted:

    order            two dated events in an order procedure does not allow
    repeat           the same step twice on different dates (a resentencing,
                     a superseding indictment)
    plea_and_verdict the same defendant both pleaded guilty and was convicted
                     at trial

Only a defendant's own events are checked. An event that a record gives to no
one in particular is in every co-defendant's trace and is left out of these
checks.

Each of these is either something that happened in the case or an error in a
record or in the reading of it. The check does not say which. It says where
to look.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from process_mining import discover
from process_mining.log import Trace

# (earlier kinds, later kinds): no dated event of a later kind may come before every dated event of an earlier kind.
ORDER_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("offense",), ("complaint", "indictment", "information", "charge", "plea", "verdict", "conviction", "sentencing"),
     "the conduct began before the prosecution"),
    (("complaint",), ("indictment",), "a complaint comes before the indictment that replaces it"),
    (("complaint", "indictment", "information", "charge"), ("plea", "verdict", "conviction"), "a charge comes before its disposition"),
    (("arrest",), ("plea", "verdict", "conviction", "sentencing"), "an arrest comes before a disposition"),
    (("plea", "verdict", "conviction"), ("sentencing",), "a conviction comes before the sentence"),
)
REPEATABLE_NOTE = {"sentencing": "resentencing", "indictment": "superseding indictment", "plea": "second plea"}


def _bounds(stamp: str) -> tuple[str, str]:
    """The earliest and latest day a date can mean. A month spans its days."""
    return (stamp, stamp) if len(stamp) == 10 else (stamp + "-01", stamp + "-31")


def _lcs(left: tuple[str, ...], right: tuple[str, ...]) -> list[list[int]]:
    table = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i in range(len(left) - 1, -1, -1):
        for j in range(len(right) - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if left[i] == right[j] else max(table[i + 1][j], table[i][j + 1])
    return table


def align(trace: tuple[str, ...], allowed: set[tuple[str, ...]]) -> dict[str, Any]:
    """The closest allowed trace, the moves that turn one into the other, and the fitness."""
    shortest = min((len(model) for model in allowed), default=0)
    best: tuple[int, tuple[str, ...], list[list[int]]] | None = None
    for model in sorted(allowed, key=lambda m: (len(m), m)):
        table = _lcs(trace, model)
        cost = len(trace) + len(model) - 2 * table[0][0]
        if best is None or cost < best[0]:
            best = (cost, model, table)
            if cost == 0:
                break
    if best is None:
        return {"cost": len(trace), "fitness": 0.0, "moves": [{"move": "log", "activity": a} for a in trace], "closest": []}
    cost, model, table = best
    moves, i, j = [], 0, 0
    while i < len(trace) or j < len(model):
        if i < len(trace) and j < len(model) and trace[i] == model[j]:
            moves.append({"move": "both", "activity": trace[i]})
            i, j = i + 1, j + 1
        elif j < len(model) and (i == len(trace) or table[i][j + 1] >= table[i + 1][j]):
            moves.append({"move": "model", "activity": model[j]})  # expected, not reported
            j += 1
        else:
            moves.append({"move": "log", "activity": trace[i]})  # reported, not allowed here
            i += 1
    worst = len(trace) + shortest
    return {"cost": cost, "fitness": round(1 - cost / worst, 4) if worst else 1.0, "moves": moves, "closest": list(model)}


def fitness(log: discover.Log, tree: discover.Tree, max_loop: int = 3) -> dict[str, Any]:
    """How well a log replays on a model: average fitness, and the share of traces that fit exactly."""
    allowed = discover.language(tree, max_loop)
    total = sum(log.values())
    exact = weighted = 0.0
    worst: list[tuple[float, int, tuple[str, ...]]] = []
    for trace, count in log.items():
        result = align(trace, allowed)
        weighted += result["fitness"] * count
        exact += count if result["cost"] == 0 else 0
        worst.append((result["fitness"], count, trace))
    seen = set(log)
    return {
        "traces": total,
        "fitness": round(weighted / total, 4) if total else None,
        "traces_fitting_exactly": round(exact / total, 4) if total else None,
        "paths_the_model_allows": len(allowed),
        "allowed_paths_observed": len(allowed & seen),
        "least_fitting": [{"path": list(trace), "traces": count, "fitness": fit} for fit, count, trace in sorted(worst)[:8] if fit < 1],
    }


def check_order(trace: Trace) -> list[dict[str, Any]]:
    """Departures from procedural order among a trace's own events.

    An event shared by every defendant of a case because its record named no
    one is left out: one co-defendant's plea and another's verdict are not one
    person's plea and verdict."""
    own = [event for event in trace.events if event.get("own", True)]
    dated = [event for event in own if event["date"]]
    found: list[dict[str, Any]] = []
    for earlier_kinds, later_kinds, why in ORDER_RULES:
        earlier = [event for event in dated if event["type"] in earlier_kinds]
        later = [event for event in dated if event["type"] in later_kinds]
        if not earlier or not later:
            continue
        first = min(earlier, key=lambda e: _bounds(e["date"])[0])
        for event in later:
            # Certain only when the later event's last possible day is before the earlier one's first.
            if _bounds(event["date"])[1] < _bounds(first["date"])[0]:
                found.append({
                    "kind": "order", "rule": why,
                    "detail": f"{event['type']} dated {event['date']} is before {first['type']} dated {first['date']}",
                })
    by_kind: dict[str, list[str]] = {}
    for event in dated:
        by_kind.setdefault(event["type"], []).append(event["date"])
    for kind, dates in by_kind.items():
        distinct = sorted(set(dates))
        separate = [d for i, d in enumerate(distinct) if not any(o != d and (o.startswith(d) or d.startswith(o)) for o in distinct[:i])]
        if kind != "offense" and len(separate) > 1:
            found.append({"kind": "repeat", "rule": REPEATABLE_NOTE.get(kind, "the same step on two dates"),
                          "detail": f"{kind} dated {' and '.join(separate)}"})
    kinds = {event["type"] for event in own}
    if {"plea", "verdict"} <= kinds:
        found.append({"kind": "plea_and_verdict", "rule": "a defendant is convicted by plea or by verdict",
                      "detail": "the records report both a guilty plea and a trial verdict for this defendant"})
    return found


def check_log(traces: list[Trace]) -> dict[str, Any]:
    counts: Counter = Counter()
    flagged = []
    for trace in traces:
        found = check_order(trace)
        for item in found:
            counts[item["kind"]] += 1
        if found:
            flagged.append({"case_id": trace.case_id, "person": trace.person, "path": list(trace.activities()), "departures": found})
    return {
        "traces": len(traces), "traces_with_a_departure": len(flagged),
        "cases_with_a_departure": len({item["case_id"] for item in flagged}),
        "by_kind": dict(counts), "flagged": flagged,
    }
