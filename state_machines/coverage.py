"""Backbone and intervention, measured on observed trajectories.

The backbone is what every completed trajectory passes through. On a corpus
of whole narratives the definition is an intersection. Here most records tell
part of an offense, so an intersection is empty for reasons that are about
the records, and coverage is used instead:

    coverage_d(s) = share of domain d's trajectories that occupy state s at least once

A state is in the backbone at threshold theta when its coverage is at least
theta in every domain. The table is given at every threshold, so a reader can
see where states drop out, and per kind of record, because a statement of
offense and a press release tell different amounts of the offense.

Intervention is the same idea from the other side. Removing a state b
(a wall, in the `means` extension's terms) would cut every recorded path
through b:

    kappa_d(b) = share of domain d's goal-reaching trajectories that do not pass through b

kappa = 0 means every recorded path to the goal went through b. Like coverage,
it is a statement about recorded paths. It does not predict how an offender
would reroute.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from state_machines import machine as m


def occupied(trajectory: dict[str, Any], states: m.StateMap = m.phase_state) -> set[str]:
    return {states(act) for act in trajectory["acts"] if act["kind"] != "detection"}


def coverage(trajectories: list[dict[str, Any]], *, states: m.StateMap = m.phase_state, min_trajectories: int = 25) -> dict[str, Any]:
    by_domain: dict[str, list[set[str]]] = defaultdict(list)
    for trajectory in trajectories:
        seen = occupied(trajectory, states)
        if seen:
            by_domain[trajectory["domain"]].append(seen)
    kept = {d: rows for d, rows in by_domain.items() if len(rows) >= min_trajectories}
    every = sorted({s for rows in kept.values() for row in rows for s in row})
    table = {d: {s: round(sum(1 for row in rows if s in row) / len(rows), 4) for s in every} for d, rows in sorted(kept.items())}
    backbone = {}
    for theta in (0.9, 0.75, 0.5, 0.25, 0.1):
        backbone[str(theta)] = [s for s in every if table and all(table[d][s] >= theta for d in table)]
    return {"domains": {d: len(rows) for d, rows in sorted(kept.items())}, "coverage": table, "backbone_at_threshold": backbone}


def intervention(trajectories: list[dict[str, Any]], goal: tuple[str, ...] = ("harm",), *, states: m.StateMap = m.phase_state,
                 min_trajectories: int = 25) -> dict[str, Any]:
    reaching: dict[str, list[set[str]]] = defaultdict(list)
    for trajectory in trajectories:
        seen = occupied(trajectory, states)
        if seen & set(goal):
            reaching[trajectory["domain"]].append(seen)
    kept = {d: rows for d, rows in reaching.items() if len(rows) >= min_trajectories}
    blockable = sorted({s for rows in kept.values() for row in rows for s in row} - set(goal))
    return {
        "goal": list(goal), "goal_reaching_trajectories": {d: len(rows) for d, rows in sorted(kept.items())},
        "kappa": {d: {b: round(sum(1 for row in rows if b not in row) / len(rows), 4) for b in blockable} for d, rows in sorted(kept.items())},
    }
