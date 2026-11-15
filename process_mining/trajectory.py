"""Offense trajectories: the acts of an offense as a sequence, at three levels of abstraction.

The object of study is the trajectory: the path an offender takes through
the acts of an offense. This module builds one per record from the engine's
`conduct` table and offers the views a formal model starts from.

Three levels, each a coarser reading of the same acts:

    means    the act and the technology its sentence names: `contact[whatsapp]`
    act      the act alone: `contact`
    phase    the stage of the offense: `approach`

The levels exist because the question is about levels. If technology enters
an offense through its actions and leaves its stages alone, then offenses of
different kinds should look alike at the phase level and differ at the means
level. `compare` measures exactly that: how far apart the offense domains are
at each level. It is a measurement to be read with its limits, which the
function's own text states, and it is not a test result.

Everything here describes what filings and releases narrate. A trajectory
has the acts its record tells, in the order it tells them.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from extraction import acts as act_rules

LEVELS = ("means", "act", "phase")
START, END = "(start)", "(end)"


def _step(act: dict[str, Any], level: str) -> str:
    if level == "phase":
        return act_rules.PHASE[act["kind"]]
    if level == "act":
        return act["kind"]
    means = sorted(set(act["means"].get("platform", []) + act["means"].get("channel", [])))
    return f"{act['kind']}[{'+'.join(means)}]" if means else act["kind"]


def build(db: sqlite3.Connection, *, domain: str = "", kind: str = "", min_acts: int = 2, with_detection: bool = False) -> list[dict[str, Any]]:
    """One trajectory per record that narrates at least `min_acts` acts.

    `kind` is "court" or "press" to keep one kind of record. Detection steps
    (what investigators did) are left out unless asked for: they end the
    offense and are not part of it."""
    records = {row["record_id"]: dict(row) for row in db.execute("SELECT record_id, kind, domain FROM records")}
    offenses: dict[str, list[str]] = defaultdict(list)
    for row in db.execute("SELECT record_id, value FROM finals WHERE field = 'offense' ORDER BY record_id, value"):
        offenses[row["record_id"]].append(row["value"])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in db.execute("SELECT * FROM conduct ORDER BY record_id, position"):
        if row["kind"] == "detection" and not with_detection:
            continue
        grouped[row["record_id"]].append({
            "kind": row["kind"], "phase": act_rules.PHASE[row["kind"]], "date": row["date"],
            "means": json.loads(row["means"]), "people": json.loads(row["people"]), "status": row["status"],
        })
    out = []
    for record_id, acts in grouped.items():
        record = records.get(record_id)
        if record is None or len(acts) < min_acts:
            continue
        if (domain and record["domain"] != domain) or (kind and record["kind"] != kind):
            continue
        out.append({"record_id": record_id, "record_kind": record["kind"], "domain": record["domain"],
                    "offenses": offenses.get(record_id, []), "acts": acts})
    return out


def path(trajectory: dict[str, Any], level: str = "act") -> tuple[str, ...]:
    """The trajectory's steps at one level, a run of one step counted once."""
    out: list[str] = []
    for act in trajectory["acts"]:
        step = _step(act, level)
        if not out or out[-1] != step:
            out.append(step)
    return tuple(out)


def transitions(trajectories: list[dict[str, Any]], level: str = "act") -> dict[str, Any]:
    """A first-order transition model: from each step, how often each step follows.

    This is the empirical side of a Markov model of offending: the observed
    frequencies, with their counts, and the entropy of what follows each step
    (0 when one step always follows, higher when the next move is open)."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for trajectory in trajectories:
        steps = (START, *path(trajectory, level), END)
        for left, right in zip(steps, steps[1:]):
            counts[left][right] += 1
    table = {}
    for left, following in counts.items():
        total = sum(following.values())
        entropy = -sum((n / total) * math.log2(n / total) for n in following.values())
        table[left] = {
            "times": total, "entropy_bits": round(entropy, 3),
            "next": [{"step": step, "times": n, "probability": round(n / total, 3)} for step, n in following.most_common()],
        }
    return {"level": level, "trajectories": len(trajectories), "from": dict(sorted(table.items(), key=lambda item: -item[1]["times"]))}


def _distribution(trajectories: list[dict[str, Any]], level: str, what: str) -> Counter:
    counts: Counter = Counter()
    for trajectory in trajectories:
        steps = path(trajectory, level)
        counts.update(steps if what == "steps" else zip((START, *steps), (*steps, END)))
    return counts


def _jensen_shannon(left: Counter, right: Counter) -> float:
    """Jensen-Shannon divergence in bits: 0 for identical distributions, 1 for disjoint ones."""
    a_total, b_total = sum(left.values()), sum(right.values())
    out = 0.0
    for key in set(left) | set(right):
        p, q = left[key] / a_total, right[key] / b_total
        m = (p + q) / 2
        out += (p * math.log2(p / m) if p else 0.0) / 2 + (q * math.log2(q / m) if q else 0.0) / 2
    return out


def compare(trajectories: list[dict[str, Any]], *, min_trajectories: int = 25) -> dict[str, Any]:
    """How far apart the offense domains are, at each level of abstraction.

    For every pair of domains with at least `min_trajectories` trajectories,
    the Jensen-Shannon divergence between their distributions of steps and of
    transitions, at the phase, act and means levels. A coarser level always
    has fewer categories, and fewer categories alone push a divergence down,
    so each figure is given beside the same figure for the domains' labels
    shuffled (`shuffled`, the mean over 20 shuffles). What a level shows is
    the gap between the two, not the raw number."""
    import random

    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trajectory in trajectories:
        by_domain[trajectory["domain"]].append(trajectory)
    kept = {domain: items for domain, items in by_domain.items() if len(items) >= min_trajectories}
    out: dict[str, Any] = {"domains": {domain: len(items) for domain, items in sorted(kept.items())},
                           "left_out_for_too_few": {d: len(i) for d, i in sorted(by_domain.items()) if d not in kept}, "levels": {}}
    if len(kept) < 2:
        return out
    pooled = [t for items in kept.values() for t in items]
    sizes = [(domain, len(items)) for domain, items in sorted(kept.items())]
    for level in ("phase", "act", "means"):
        result: dict[str, Any] = {}
        for what in ("steps", "transitions"):
            observed = {d: _distribution(items, level, what) for d, items in kept.items()}
            pairs = {f"{a} / {b}": round(_jensen_shannon(observed[a], observed[b]), 4) for a, b in combinations(sorted(kept), 2)}
            rng = random.Random(8252)
            shuffled_means = []
            for _ in range(20):
                mixed = pooled[:]
                rng.shuffle(mixed)
                parts, cursor = {}, 0
                for domain, size in sizes:
                    parts[domain] = _distribution(mixed[cursor: cursor + size], level, what)
                    cursor += size
                shuffled_means.append(sum(_jensen_shannon(parts[a], parts[b]) for a, b in combinations(sorted(parts), 2)) / len(pairs))
            mean = sum(pairs.values()) / len(pairs)
            baseline = sum(shuffled_means) / len(shuffled_means)
            result[what] = {"mean_divergence_bits": round(mean, 4), "shuffled": round(baseline, 4),
                            "above_shuffled": round(mean - baseline, 4), "categories": len(set().union(*observed.values())), "pairs": pairs}
        out["levels"][level] = result
    return out


def means_by_act(trajectories: list[dict[str, Any]], *, limit: int = 8) -> dict[str, Any]:
    """Which technology is named at which act, per domain: where in an offense each affordance is used."""
    table: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    totals: dict[str, Counter] = defaultdict(Counter)
    for trajectory in trajectories:
        for act in trajectory["acts"]:
            totals[trajectory["domain"]][act["kind"]] += 1
            for label in act["means"].get("channel", []) + act["means"].get("platform", []):
                table[trajectory["domain"]][act["kind"]][label] += 1
    return {
        domain: {
            kind: {"acts": totals[domain][kind], "means": [{"label": label, "acts": n} for label, n in labels.most_common(limit)]}
            for kind, labels in sorted(kinds.items(), key=lambda item: -totals[domain][item[0]])
        }
        for domain, kinds in sorted(table.items())
    }


def export(trajectories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trajectories as plain rows for a model to read: every act with its kind, phase, date and means,
    and the path at each level. No text from a record and no name."""
    return [
        {**{k: t[k] for k in ("record_id", "record_kind", "domain", "offenses")},
         "acts": [{k: act[k] for k in ("kind", "phase", "date", "means")} for act in t["acts"]],
         "paths": {level: list(path(t, level)) for level in LEVELS}}
        for t in trajectories
    ]
