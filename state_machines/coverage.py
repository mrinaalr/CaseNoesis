"""The backbone, the laws that can be read off observed trajectories, and the exploitation predicate.

    coverage_d(s)    share of domain d's trajectories that occupy state s
    backbone_theta   states with coverage at least theta in every domain
    kappa_d(b)       share of domain d's completed trajectories that avoid state b
                     (0: every recorded completed path went through b)

Laws, each measured on trajectories that reach Exploitation:

    contact primacy      InitialContact occurs before Exploitation
    backbone             InitialContact, Conditioning and Exploitation all occur
    maintenance          Maintenance occurs after Exploitation
    loop                 Exploitation is re-entered after Maintenance

Most records tell part of an offense: a release often begins at the payment.
A missing state can be a state the telling skipped, so the laws are reported
for court filings, which narrate the offense from its start, beside all records.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from state_machines import states as st


def _by_domain(trajectories: list[dict[str, Any]], minimum: int) -> dict[str, list[list[str]]]:
    grouped: dict[str, list[list[str]]] = defaultdict(list)
    for t in trajectories:
        walked = st.path(t)
        if walked:
            grouped[t["domain"]].append(walked)
    return {d: paths for d, paths in sorted(grouped.items()) if len(paths) >= minimum}


def coverage(trajectories: list[dict[str, Any]], *, minimum: int = 25) -> dict[str, Any]:
    grouped = _by_domain(trajectories, minimum)
    table = {d: {s: round(sum(1 for p in paths if s in p) / len(paths), 4) for s in st.STATES} for d, paths in grouped.items()}
    backbone = {str(theta): [s for s in st.STATES if table and all(table[d][s] >= theta for d in table)] for theta in (0.9, 0.75, 0.5, 0.25, 0.1)}
    ends = {d: {k: round(v / len(paths), 4) for k, v in Counter(p[-1] for p in paths).most_common()} for d, paths in grouped.items()}
    return {"domains": {d: len(p) for d, p in grouped.items()}, "coverage": table, "backbone_at_threshold": backbone, "ends": ends}


def laws(trajectories: list[dict[str, Any]], *, minimum: int = 15) -> dict[str, Any]:
    grouped = _by_domain(trajectories, 1)
    out: dict[str, Any] = {}
    for d, paths in grouped.items():
        reached = [p for p in paths if st.EXPLOITATION in p]
        if len(reached) < minimum:
            continue
        first = [p.index(st.EXPLOITATION) for p in reached]
        out[d] = {
            "reaching_exploitation": len(reached),
            "contact_primacy": round(sum(1 for p, i in zip(reached, first) if st.CONTACT in p[:i]) / len(reached), 4),
            "conditioning_before_exploitation": round(sum(1 for p, i in zip(reached, first) if st.CONDITIONING in p[:i]) / len(reached), 4),
            "full_backbone_before_exploitation": round(sum(1 for p, i in zip(reached, first) if st.CONTACT in p[:i] and st.CONDITIONING in p[:i]) / len(reached), 4),
            "maintenance_after_exploitation": round(sum(1 for p in reached if st.MAINTENANCE in p) / len(reached), 4),
            "exploitation_maintenance_loop": round(sum(1 for p in reached if p.count(st.EXPLOITATION) > 1) / len(reached), 4),
        }
    return out


def intervention(trajectories: list[dict[str, Any]], *, minimum: int = 25) -> dict[str, Any]:
    grouped = {d: [p for p in paths if p[-1] == st.COMPLETED] for d, paths in _by_domain(trajectories, 1).items()}
    grouped = {d: paths for d, paths in grouped.items() if len(paths) >= minimum}
    return {d: {b: round(sum(1 for p in paths if b not in p) / len(paths), 4) for b in (st.PREPARATION, st.CONTACT, st.CONDITIONING)}
            for d, paths in grouped.items()}


def predicate(trajectories: list[dict[str, Any]], *, minimum: int = 15) -> dict[str, Any]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for t in trajectories:
        grouped[t["domain"]][st.predicate(t)] += 1
    return {d: {k: round(v / sum(c.values()), 4) for k, v in c.most_common()} | {"trajectories": sum(c.values())}
            for d, c in sorted(grouped.items()) if sum(c.values()) >= minimum}
