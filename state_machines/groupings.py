"""Groupings: states as a partition of act kinds, compared on equal terms.

A grouping assigns each act kind to a state. It has no goal, no reading
rules and no order of states, so any grouping can be run through the same
code and described the same way:

    acts       every act kind is its own state
    one        every act kind is in one state
    esm        the ESM scheme's milestones, read from each act's role alone. This is also the
               partition of #8's phases. It leaves out the scheme's rules that read history
               (leverage after the goal becomes Maintenance), so it is the scheme's grouping,
               not the scheme
    learned    built from the data: act kinds merged, two at a time, so as to lose the least
               information about the next act, on one half of the records. With as many states
               as `esm`. Fraud is most of the corpus and so shapes it most; `learned_balanced`
               weights every domain the same
    random     act kinds dealt into states at random, keeping a grouping's state sizes

Each grouping is described by:

    states                how many
    next_act_bits         held-out cross-entropy of the next act (or the end) given the current
                          state, in bits. Lower means the state says more about what comes next
    information_bits      how much lower it is than under `one`, which knows only whether the
                          offense has begun. This is what the grouping itself says about the next act
    divergence            how far apart domains are in their transitions between states, above
                          shuffled domain labels, in bits, on equal subsamples
    divergence_order_shuffled   the same with each record's acts shuffled
    coverage              per domain, the share of records reaching each state
    transitions           P(s' | s), all records pooled

A named grouping is set beside random groupings with its own state sizes,
on the same two measures. Where it falls among them is reported as a
percentile, and nothing more is read from it.

The learned grouping is fitted on the records whose id hashes to the
first half and scored on the second. Every other measure uses all records.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from extraction import acts as act_rules

KINDS = tuple(k for k in act_rules.KINDS if k != "detection")
START, END = "(start)", "(end)"
Grouping = dict[str, str]
Sequence = tuple[str, list[str]]  # (domain, act kinds in order)


def sequences(records: list[dict[str, Any]]) -> list[Sequence]:
    """Each record's act kinds in the order told, detection left out."""
    out = []
    for t in records:
        kinds = [a["kind"] for a in t["acts"] if a["kind"] in KINDS]
        if kinds:
            out.append((t["domain"], kinds))
    return out


def half(record_id: str) -> int:
    return int(hashlib.sha256(record_id.encode()).hexdigest(), 16) % 2


def acts() -> Grouping:
    return {k: k for k in KINDS}


def one() -> Grouping:
    return {k: "state" for k in KINDS}


def esm() -> Grouping:
    from state_machines import readers

    milestone = {"prepare": "Preparation", "reach": "InitialContact", "deceive": "Conditioning", "coerce": "Conditioning",
                 "press": "Conditioning", "extract": "Exploitation", "deliver": "Exploitation", "after": "Exit"}
    return {k: milestone[readers.ROLE[k]] for k in KINDS}


def sizes(grouping: Grouping) -> list[int]:
    return sorted(Counter(grouping.values()).values(), reverse=True)


def random_grouping(state_sizes: list[int], rng: random.Random) -> Grouping:
    kinds = list(KINDS)
    rng.shuffle(kinds)
    out, i = {}, 0
    for n, size in enumerate(state_sizes):
        for k in kinds[i:i + size]:
            out[k] = f"g{n}"
        i += size
    return out


def _pairs(seqs: list[Sequence], grouping: Grouping, *, balanced: bool = False) -> Counter:
    """(state of the current act, next act) counts, from the start and to the end. `balanced`
    weights each record by one over its domain's size, so every domain counts the same."""
    size = Counter(d for d, _ in seqs)
    out: Counter = Counter()
    for domain, kinds in seqs:
        w = 1 / size[domain] if balanced else 1
        here = START
        for k in kinds:
            out[(here, k)] += w
            here = grouping[k]
        out[(here, END)] += w
    return out


def _row_loss(row: Counter) -> float:
    total = sum(row.values())
    return sum(n * math.log(n / total) for n in row.values() if n)


def merges(seqs: list[Sequence], *, balanced: bool = False) -> dict[int, Grouping]:
    """Groupings of every size, from every act its own state down to one state. At each step the two
    states whose merging loses the least likelihood of the next act are merged."""
    rows: dict[frozenset, Counter] = {}
    for (s, x), n in _pairs(seqs, acts(), balanced=balanced).items():
        if s != START:
            rows.setdefault(frozenset([s]), Counter())[x] += n
    for k in KINDS:
        rows.setdefault(frozenset([k]), Counter())
    out: dict[int, Grouping] = {}
    while True:
        out[len(rows)] = {k: "+".join(sorted(group)) for group in rows for k in group}
        if len(rows) == 1:
            return out
        best = None
        for a, b in combinations(sorted(rows, key=sorted), 2):
            lost = _row_loss(rows[a]) + _row_loss(rows[b]) - _row_loss(rows[a] + rows[b])
            if best is None or lost < best[0]:
                best = (lost, a, b)
        _, a, b = best
        rows[a | b] = rows.pop(a) + rows.pop(b)


def learned(seqs: list[Sequence], k: int, *, balanced: bool = False) -> Grouping:
    return merges(seqs, balanced=balanced)[k]


def next_act_bits(train: list[Sequence], test: list[Sequence], grouping: Grouping, *, alpha: float = 0.5) -> float:
    """Held-out cross-entropy of the next act given the current state, with add-alpha smoothing."""
    counts, totals = _pairs(train, grouping), Counter()
    for (s, _), n in counts.items():
        totals[s] += n
    vocab = len(KINDS) + 1
    held = _pairs(test, grouping)
    total = sum(held.values())
    loss = -sum(n * math.log2((counts[(s, x)] + alpha) / (totals[s] + alpha * vocab)) for (s, x), n in held.items())
    return loss / total


def _moves(kinds: list[str], grouping: Grouping) -> list[tuple[str, str]]:
    path = [START]
    for k in kinds:
        s = grouping[k]
        if s != path[-1]:
            path.append(s)
    path.append(END)
    return list(zip(path, path[1:]))


def _jsd(left: Counter, right: Counter) -> float:
    a, b = sum(left.values()), sum(right.values())
    total = 0.0
    for key in set(left) | set(right):
        p, q = left[key] / a, right[key] / b
        mid = (p + q) / 2
        total += (p * math.log2(p / mid) if p else 0.0) / 2 + (q * math.log2(q / mid) if q else 0.0) / 2
    return total


def _mean_pairwise(groups: dict[str, list[list[tuple[str, str]]]]) -> float:
    dists = {d: Counter(m for moves in items for m in moves) for d, items in groups.items()}
    values = [_jsd(dists[a], dists[b]) for a, b in combinations(sorted(dists), 2)]
    return sum(values) / len(values)


def divergence(by_domain: dict[str, list[list[str]]], grouping: Grouping, *, size: int, repeats: int = 20, shuffles: int = 10,
               reorder: bool = False, seed: int = 8252) -> float:
    """Mean excess divergence of state transitions between domains over shuffled domain labels."""
    rng = random.Random(seed)
    excess = []
    for _ in range(repeats):
        sample = {d: rng.sample(items, size) for d, items in by_domain.items()}
        if reorder:
            sample = {d: [rng.sample(kinds, len(kinds)) for kinds in items] for d, items in sample.items()}
        moved = {d: [_moves(kinds, grouping) for kinds in items] for d, items in sample.items()}
        observed = _mean_pairwise(moved)
        pooled = [m for items in moved.values() for m in items]
        shuffled = []
        for _ in range(shuffles):
            rng.shuffle(pooled)
            shuffled.append(_mean_pairwise({d: pooled[i * size:(i + 1) * size] for i, d in enumerate(sorted(moved))}))
        excess.append(observed - sum(shuffled) / len(shuffled))
    return sum(excess) / len(excess)


def coverage(seqs: list[Sequence], grouping: Grouping, *, minimum: int = 25) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[set[str]]] = defaultdict(list)
    for domain, kinds in seqs:
        grouped[domain].append({grouping[k] for k in kinds})
    return {d: {s: round(sum(1 for r in rows if s in r) / len(rows), 3) for s in sorted(set(grouping.values()))}
            for d, rows in sorted(grouped.items()) if len(rows) >= minimum}


def transitions(seqs: list[Sequence], grouping: Grouping, *, minimum: int = 5) -> dict[str, dict[str, float]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for _, kinds in seqs:
        for s, n in _moves(kinds, grouping):
            counts[s][n] += 1
    return {s: {n: round(c / sum(row.values()), 3) for n, c in row.most_common() if c >= minimum} for s, row in sorted(counts.items())}


def _percentile(value: float, null: list[float]) -> float:
    """The share of the null strictly below `value`, plus half the ties."""
    below = sum(1 for v in null if v < value)
    tied = sum(1 for v in null if v == value)
    return round((below + tied / 2) / len(null), 3)


def compare(records: list[dict[str, Any]], *, minimum: int = 80, ks: tuple[int, ...] = tuple(range(1, len(KINDS) + 1)),
            randoms: int = 100, repeats: int = 20, seed: int = 8252) -> dict[str, Any]:
    """Every grouping described on the same measures, each named one beside random groupings of its sizes."""
    ids = [t["record_id"] for t in records if any(a["kind"] in KINDS for a in t["acts"])]
    seqs = sequences(records)
    train = [s for s, i in zip(seqs, ids) if half(i) == 0]
    test = [s for s, i in zip(seqs, ids) if half(i) == 1]
    by_domain: dict[str, list[list[str]]] = defaultdict(list)
    for domain, kinds in seqs:
        by_domain[domain].append(kinds)
    by_domain = {d: v for d, v in sorted(by_domain.items()) if len(v) >= minimum}
    size = min(len(v) for v in by_domain.values()) if len(by_domain) >= 2 else 0
    base = next_act_bits(train, test, one())

    def describe(grouping: Grouping, *, full: bool = True) -> dict[str, Any]:
        bits = next_act_bits(train, test, grouping)
        row: dict[str, Any] = {"states": len(set(grouping.values())), "next_act_bits": round(bits, 4),
                               "information_bits": round(base - bits, 4)}
        if size:
            row["divergence_bits"] = round(divergence(by_domain, grouping, size=size, repeats=repeats, seed=seed), 4)
        if full:
            row["grouping"] = {s: sorted(k for k, t in grouping.items() if t == s) for s in sorted(set(grouping.values()))}
            if size:
                row["divergence_order_shuffled_bits"] = round(divergence(by_domain, grouping, size=size, repeats=repeats, reorder=True, seed=seed), 4)
            row["coverage"] = coverage(seqs, grouping)
            row["transitions"] = transitions(seqs, grouping)
        return row

    named: dict[str, Grouping] = {"acts": acts(), "one": one(), "esm": esm()}
    k = len(set(named["esm"].values()))
    named["learned"] = learned(train, k)
    named["learned_balanced"] = learned(train, k, balanced=True)
    out: dict[str, Any] = {"records": len(seqs), "train": len(train), "test": len(test), "one_state_bits": round(base, 4),
                           "domains": {d: len(v) for d, v in by_domain.items()}, "subsample_size": size, "groupings": {}}
    rng = random.Random(seed)
    for name, grouping in named.items():
        row = describe(grouping)
        if 1 < row["states"] < len(KINDS):
            null = [describe(random_grouping(sizes(grouping), rng), full=False) for _ in range(randoms)]
            row["random_same_sizes"] = {
                "groupings": randoms,
                "information_bits": _summary([r["information_bits"] for r in null]),
                "information_percentile": _percentile(row["information_bits"], [r["information_bits"] for r in null]),
                **({"divergence_bits": _summary([r["divergence_bits"] for r in null]),
                    "divergence_percentile": _percentile(row["divergence_bits"], [r["divergence_bits"] for r in null])} if size else {}),
            }
        out["groupings"][name] = row
    out["learned_by_size"] = []
    path = merges(train)
    for k in ks:
        g = path[k]
        out["learned_by_size"].append({"states": k, "information_bits": round(base - next_act_bits(train, test, g), 4),
                                       "grouping": sorted("+".join(sorted(kk for kk, t in g.items() if t == s)) for s in set(g.values()))})
    return out


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    n = len(ordered)
    return {"mean": round(sum(values) / n, 4), "p05": ordered[int(0.05 * (n - 1))], "p50": ordered[n // 2], "p95": ordered[int(0.95 * (n - 1))]}
