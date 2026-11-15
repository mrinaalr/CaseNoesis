"""The backbone, the laws that can be read off observed walks, and the exploitation predicate.

    coverage_d(s)    share of domain d's walks that occupy state s
    backbone_theta   states with coverage at least theta in every domain
    kappa_d(b)       share of domain d's completed walks that avoid state b
                     (0: every recorded completed path went through b)

Laws, each measured on walks that reach the goal, at the milestone layer.
States are named by the scheme's roles, so a scheme without a role skips its law.

    contact primacy      contact occurs before the goal
    conditioning         conditioning occurs before the goal
    full backbone        both occur before the goal
    maintenance          maintenance occurs after the goal
    loop                 the goal is re-entered
    exit                 exit occurs after the goal
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from state_machines.scheme import COMPLETED, Scheme
from state_machines.walks import Walk, path, predicate as walk_predicate

THRESHOLDS = (0.9, 0.75, 0.5, 0.25, 0.1)


def _by_domain(walks: list[Walk], scheme: Scheme, layer: str, minimum: int) -> dict[str, list[list[str]]]:
    grouped: dict[str, list[list[str]]] = defaultdict(list)
    for w in walks:
        walked = path(w, scheme, layer)
        if walked:
            grouped[w.domain].append(walked)
    return {d: paths for d, paths in sorted(grouped.items()) if len(paths) >= minimum}


def coverage(walks: list[Walk], scheme: Scheme, *, layer: str = "milestone", minimum: int = 25) -> dict[str, Any]:
    grouped = _by_domain(walks, scheme, layer, minimum)
    states = [s for s in scheme.at_layer(layer) if any(s in p for paths in grouped.values() for p in paths)]
    table = {d: {s: round(sum(1 for p in paths if s in p) / len(paths), 4) for s in states} for d, paths in grouped.items()}
    backbone = {str(theta): [s for s in states if table and all(table[d][s] >= theta for d in table)] for theta in THRESHOLDS}
    ends = {d: {k: round(v / len(paths), 4) for k, v in Counter(p[-1] for p in paths).most_common()} for d, paths in grouped.items()}
    return {"layer": layer, "domains": {d: len(p) for d, p in grouped.items()}, "coverage": table, "backbone_at_threshold": backbone, "ends": ends}


def laws(walks: list[Walk], scheme: Scheme, *, minimum: int = 15) -> dict[str, Any]:
    r = scheme.roles
    goal, contact, conditioning, maintenance, exit_ = (r.get(k) for k in ("goal", "contact", "conditioning", "maintenance", "exit"))
    out: dict[str, Any] = {}
    for d, paths in _by_domain(walks, scheme, "milestone", 1).items():
        reached = [p for p in paths if goal in p]
        if len(reached) < minimum:
            continue
        first = [p.index(goal) for p in reached]

        def share(test) -> float:
            return round(sum(1 for p, i in zip(reached, first) if test(p, i)) / len(reached), 4)

        row: dict[str, Any] = {"reaching_goal": len(reached)}
        if contact:
            row["contact_primacy"] = share(lambda p, i: contact in p[:i])
        if conditioning:
            row["conditioning_before_goal"] = share(lambda p, i: conditioning in p[:i])
        if contact and conditioning:
            row["full_backbone_before_goal"] = share(lambda p, i: contact in p[:i] and conditioning in p[:i])
        if maintenance:
            row["maintenance_after_goal"] = share(lambda p, i: maintenance in p[i:])
        row["goal_reentered"] = share(lambda p, i: p.count(goal) > 1)
        if exit_:
            row["exit_after_goal"] = share(lambda p, i: exit_ in p[i:])
        out[d] = row
    return out


def intervention(walks: list[Walk], scheme: Scheme, *, minimum: int = 25) -> dict[str, Any]:
    before = [scheme.roles[k] for k in ("preparation", "contact", "conditioning") if k in scheme.roles]
    grouped = {d: [p for p in paths if p[-1] == COMPLETED] for d, paths in _by_domain(walks, scheme, "milestone", 1).items()}
    grouped = {d: paths for d, paths in grouped.items() if len(paths) >= minimum}
    return {d: {b: round(sum(1 for p in paths if b not in p) / len(paths), 4) for b in before} for d, paths in grouped.items()}


def predicate(walks: list[Walk], scheme: Scheme, *, minimum: int = 15) -> dict[str, Any]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for w in walks:
        grouped[w.domain][walk_predicate(w, scheme)] += 1
    return {d: {k: round(v / sum(c.values()), 4) for k, v in c.most_common()} | {"trajectories": sum(c.values())}
            for d, c in sorted(grouped.items()) if sum(c.values()) >= minimum}


def tracks(walks: list[Walk], scheme: Scheme, *, minimum: int = 25) -> dict[str, Any]:
    """For each domain, how each milestone it reached was reached: the share of its walks at each
    track state beneath it."""
    grouped = _by_domain(walks, scheme, "track", minimum)
    out: dict[str, Any] = {}
    for d, paths in grouped.items():
        row: dict[str, dict[str, float]] = {}
        for milestone in scheme.at_layer("milestone"):
            below = [s for s in scheme.children(milestone) if scheme.states[s].layer == "track"]
            if not below:
                continue
            holding = [p for p in paths if any(s in p for s in below) or milestone in p]
            if holding:
                row[milestone] = {s: round(sum(1 for p in holding if s in p) / len(holding), 4) for s in [*below, milestone]
                                  if any(s in p for p in holding)}
        out[d] = row
    return out
