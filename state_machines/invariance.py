"""How far apart domains are at a scheme's states, its acts, and their technology.

Three distributions per domain:

    states      transitions between states, s -> s' with s' != s, ending in a terminal state
    acts        the act taken at each state, (s, a)
    means       the act and its named technology at each state, (s, a[means]), for acts that name one

For each, the divergence between domains (Jensen-Shannon, in bits, averaged
over pairs) is compared with the same divergence after shuffling domain
labels. Domains are subsampled to the same number of trajectories, repeated,
so that a large domain does not look more distinct only by being large.

Excess at the state level means the domains move between states
differently, as the scheme reads them.

Levels are not compared with one another. States are computed from acts by
grouping them, and a coarser grouping of any data diverges less than a finer
one: random act sequences with no order give the same ordering of levels.
The state level is set beside two nulls instead, each on the same equal-size
subsamples as the observed value:

    grouping   act kinds reassigned to roles at random, keeping how many kinds each
               role has: where the scheme's grouping falls among random ones.
    order      each record's acts shuffled: how much of the state-level divergence
               comes from the order of acts, not only from which acts domains use.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from state_machines.scheme import DETECTED, STOP, Scheme
from state_machines.walks import Walk, steps

LEVELS = ("states", "acts", "means")


def features(walk: Walk, scheme: Scheme, layer: str = "milestone") -> dict[str, list]:
    walked = steps(walk, scheme, layer, "means")
    moves = [(s, n) for s, a, n in walked if n != s]
    acts = [(s, a.split("[", 1)[0]) for s, a, _ in walked if a not in (STOP, DETECTED)]
    means = [(s, a) for s, a, _ in walked if "[" in a]
    return {"states": moves, "acts": acts, "means": means}


def _jsd(left: Counter, right: Counter) -> float:
    a, b = sum(left.values()), sum(right.values())
    if not a or not b:
        return float("nan")
    total = 0.0
    for key in set(left) | set(right):
        p, q = left[key] / a, right[key] / b
        mid = (p + q) / 2
        total += (p * math.log2(p / mid) if p else 0.0) / 2 + (q * math.log2(q / mid) if q else 0.0) / 2
    return total


def _mean_pairwise(groups: dict[str, list[dict[str, list]]], level: str) -> float:
    dists = {d: Counter(x for f in items for x in f[level]) for d, items in groups.items()}
    values = [_jsd(dists[a], dists[b]) for a, b in combinations(sorted(dists), 2)]
    values = [v for v in values if v == v]
    return sum(values) / len(values) if values else float("nan")


def test(by_domain: dict[str, list[Walk]], scheme: Scheme, *, layer: str = "milestone", size: int | None = None, repeats: int = 50, shuffles: int = 20, seed: int = 8252) -> dict[str, Any]:
    """Observed and shuffled divergence at each level, on equal-size subsamples of each domain."""
    rng = random.Random(seed)
    feats = {d: [features(w, scheme, layer) for w in items] for d, items in by_domain.items()}
    feats = {d: [f for f in items if f["acts"]] for d, items in feats.items()}
    size = size or min(len(items) for items in feats.values())
    results: dict[str, dict[str, list[float]]] = {level: {"observed": [], "shuffled": [], "beats_all_shuffles": []} for level in LEVELS}
    for _ in range(repeats):
        sample = {d: rng.sample(items, size) for d, items in feats.items()}
        pooled = [f for items in sample.values() for f in items]
        for level in LEVELS:
            observed = _mean_pairwise(sample, level)
            nulls = []
            for _ in range(shuffles):
                rng.shuffle(pooled)
                nulls.append(_mean_pairwise({d: pooled[i * size:(i + 1) * size] for i, d in enumerate(sorted(sample))}, level))
            results[level]["observed"].append(observed)
            results[level]["shuffled"].append(sum(nulls) / len(nulls))
            results[level]["beats_all_shuffles"].append(float(observed > max(nulls)))
    out: dict[str, Any] = {"layer": layer, "domains": {d: len(items) for d, items in sorted(feats.items())}, "subsample_size": size, "repeats": repeats, "levels": {}}
    for level in LEVELS:
        r = results[level]
        observed, shuffled = sum(r["observed"]) / repeats, sum(r["shuffled"]) / repeats
        out["levels"][level] = {"divergence_bits": round(observed, 4), "shuffled_bits": round(shuffled, 4),
                                "excess_bits": round(observed - shuffled, 4),
                                "share_of_subsamples_beating_every_shuffle": round(sum(r["beats_all_shuffles"]) / repeats, 3)}
    return out


def pairs(by_domain: dict[str, list[Walk]], scheme: Scheme, *, layer: str = "milestone") -> list[dict[str, Any]]:
    """Divergence for every pair of domains at each level, on all their walks."""
    feats = {d: [features(w, scheme, layer) for w in items] for d, items in by_domain.items()}
    dists = {d: {level: Counter(x for f in items for x in f[level]) for level in LEVELS} for d, items in feats.items()}
    return [{"domains": f"{a} / {b}", **{level: round(_jsd(dists[a][level], dists[b][level]), 4) for level in LEVELS}}
            for a, b in combinations(sorted(dists), 2)]


def state_transitions(by_domain: dict[str, list[Walk]], scheme: Scheme, *, layer: str = "milestone") -> dict[str, dict[str, float]]:
    """P(s' | s) between states for each domain: the state-level process the comparison is about."""
    out: dict[str, dict[str, float]] = {}
    for d, items in sorted(by_domain.items()):
        counts: dict[str, Counter] = defaultdict(Counter)
        for w in items:
            for s, n in features(w, scheme, layer)["states"]:
                counts[s][n] += 1
        out[d] = {f"{s} -> {n}": round(c / sum(row.values()), 3) for s, row in sorted(counts.items()) for n, c in row.most_common()}
    return out


def _relabel(trajectory: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {**trajectory, "acts": [{**a, "kind": mapping.get(a["kind"], a["kind"])} for a in trajectory["acts"]]}


def _reorder(trajectory: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """The record's acts in a random order; detection stays where it was told."""
    acts = trajectory["acts"]
    movable = [a for a in acts if a["kind"] != "detection"]
    rng.shuffle(movable)
    it = iter(movable)
    return {**trajectory, "acts": [a if a["kind"] == "detection" else next(it) for a in acts]}


def nulls(by_domain: dict[str, list[dict[str, Any]]], scheme: Scheme, read, *, kinds: list[str], layer: str = "milestone",
          size: int | None = None, draws: int = 200, shuffles: int = 10, seed: int = 8252) -> dict[str, Any]:
    """State-level excess divergence, observed, under random groupings of acts, and under shuffled order.

    `by_domain` holds records with their acts; `read` turns one into a walk. Each draw takes one
    equal-size subsample of every domain and scores it three ways, so the comparisons are paired."""
    rng = random.Random(seed)
    # Only records the reader makes a walk of: a record whose only act is a detection has no step.
    by_domain = {d: [t for t in items if read(t).events] for d, items in by_domain.items()}
    smallest = min(len(items) for items in by_domain.values())
    size = min(size or smallest, smallest)
    rows = {"observed": [], "grouping": [], "order": []}
    lower_than_grouping = lower_than_order = 0
    for draw in range(draws):
        sample = {d: rng.sample(items, size) for d, items in by_domain.items()}
        perm = list(kinds)
        rng.shuffle(perm)
        mapping = dict(zip(kinds, perm))

        def excess(groups: dict[str, list[dict[str, Any]]]) -> float:
            walks = {d: [read(t) for t in items] for d, items in groups.items()}
            return test(walks, scheme, layer=layer, size=size, repeats=1, shuffles=shuffles, seed=seed + draw)["levels"]["states"]["excess_bits"]

        observed = excess(sample)
        grouped = excess({d: [_relabel(t, mapping) for t in items] for d, items in sample.items()})
        order_rng = random.Random(seed * 7 + draw)
        shuffled = excess({d: [_reorder(t, order_rng) for t in items] for d, items in sample.items()})
        rows["observed"].append(observed)
        rows["grouping"].append(grouped)
        rows["order"].append(shuffled)
        lower_than_grouping += observed < grouped
        lower_than_order += observed < shuffled

    def summary(values: list[float]) -> dict[str, float]:
        ordered = sorted(values)
        return {"mean": round(sum(values) / len(values), 4), "p05": round(ordered[int(0.05 * (len(ordered) - 1))], 4),
                "p50": round(ordered[len(ordered) // 2], 4), "p95": round(ordered[int(0.95 * (len(ordered) - 1))], 4)}

    return {"layer": layer, "domains": {d: len(v) for d, v in sorted(by_domain.items())}, "subsample_size": size, "draws": draws,
            "observed_state_excess_bits": summary(rows["observed"]),
            "random_grouping_state_excess_bits": summary(rows["grouping"]),
            "shuffled_order_state_excess_bits": summary(rows["order"]),
            "share_of_draws_observed_below_random_grouping": round(lower_than_grouping / draws, 3),
            "share_of_draws_observed_below_shuffled_order": round(lower_than_order / draws, 3)}
