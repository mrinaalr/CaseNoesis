"""States: learned from trajectories, and tested for whether they hold across domains.

The claim under study is that the states of exploitation stay roughly fixed
across domains while the actions change. That is a claim, and this module
treats it as one. It does not assume a state alphabet. It learns one from
each domain's trajectories and measures how far the learned alphabets agree
with each other, with the five-phase alphabet of crime-script theory, and
with chance.

**What a state is here.** A partition of the kinds of act into classes, such
that knowing which class the last act was in predicts the next act about as
well as knowing the act itself. Two acts belong to one state when they are
interchangeable in what precedes and follows them. Formally, a class-based
first-order model:

    P(next act | last act) = P(class of next | class of last) x P(next act | its class)

The partition is found by agglomeration: start with every act in a class of
its own, and repeatedly merge the pair of classes whose merging loses the
least likelihood (Brown et al., 1992). Each number of classes gives one
partition. The number is chosen by the Bayesian information criterion, and
every comparison below is made on held-out trajectories.

**The tests.**

- `evaluate`: held-out bits per step for a domain under several alphabets:
  its own learned states, the theory's phases, the states learned from all
  domains pooled, no states at all (every act its own class), and one state.
  If the theory's phases predict held-out trajectories as well as the learned
  states, the data do not ask for other states.
- `invariance`: every domain's learned states applied to every other domain.
  The cost of borrowing another domain's states is set beside a noise floor:
  the cost of borrowing states learned from a resample of the same domain,
  and the agreement between partitions (adjusted Rand index) beside the
  agreement between two resamples of one domain. States vary across domains
  to the extent that borrowing costs more, and partitions agree less, than
  that floor.

A result that the states differ is as much a finding as a result that they
do not.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from itertools import combinations
from typing import Any

from extraction import acts as act_rules

START, END = "(start)", "(end)"
SMOOTHING = 0.1
Partition = dict[str, str]  # act kind -> state label


def sequences(trajectories: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    """Each trajectory as its acts in order, a run of one kind counted once, detection left out."""
    out = []
    for trajectory in trajectories:
        path: list[str] = []
        for act in trajectory["acts"]:
            if act["kind"] != "detection" and (not path or path[-1] != act["kind"]):
                path.append(act["kind"])
        if len(path) >= 2:
            out.append(tuple(path))
    return out


def bigrams(seqs: list[tuple[str, ...]]) -> Counter:
    counts: Counter = Counter()
    for seq in seqs:
        counts.update(zip((START, *seq), (*seq, END)))
    return counts


def _class_of(partition: Partition, symbol: str) -> str:
    return symbol if symbol in (START, END) else partition.get(symbol, symbol)


def log_likelihood(test: Counter, train: Counter, partition: Partition, vocabulary: list[str]) -> float:
    """Log-likelihood in bits of the `test` bigrams under the class model with `partition`,
    its probabilities estimated from the `train` bigrams with additive smoothing."""
    classes = sorted({_class_of(partition, v) for v in vocabulary} | {END})
    between: Counter = Counter()
    left_total: Counter = Counter()
    emitted: Counter = Counter()
    class_total: Counter = Counter()
    for (x, y), n in train.items():
        cx, cy = _class_of(partition, x), _class_of(partition, y)
        between[(cx, cy)] += n
        left_total[cx] += n
        emitted[y] += n
        class_total[cy] += n
    members = Counter(_class_of(partition, v) for v in [*vocabulary, END])
    total = 0.0
    for (x, y), n in test.items():
        cx, cy = _class_of(partition, x), _class_of(partition, y)
        transition = (between[(cx, cy)] + SMOOTHING) / (left_total[cx] + SMOOTHING * len(classes))
        emission = (emitted[y] + SMOOTHING) / (class_total[cy] + SMOOTHING * members[cy])
        total += n * math.log2(transition * emission)
    return total


def _parameters(partition: Partition, vocabulary: list[str]) -> int:
    k = len({_class_of(partition, v) for v in vocabulary})
    return (k + 1) * k + (len(vocabulary) - k)  # transitions among classes and from start, plus emissions


def induce(seqs: list[tuple[str, ...]]) -> dict[str, Any]:
    """Learn states by agglomeration. Returns the partition at every number of states and the one BIC prefers."""
    counts = bigrams(seqs)
    vocabulary = sorted({s for seq in seqs for s in seq})
    partition: Partition = {v: v for v in vocabulary}
    steps_total = sum(counts.values())
    levels = []

    def record(current: Partition) -> None:
        fit = log_likelihood(counts, counts, current, vocabulary)
        k = len(set(current.values()))
        levels.append({"states": k, "partition": dict(current), "bits_per_step": round(-fit / steps_total, 4),
                       "bic": round(-2 * fit * math.log(2) + _parameters(current, vocabulary) * math.log(steps_total), 1)})

    record(partition)
    while len(set(partition.values())) > 1:
        best: tuple[float, Partition] | None = None
        for a, b in combinations(sorted(set(partition.values())), 2):
            merged = {v: (a if c == b else c) for v, c in partition.items()}
            fit = log_likelihood(counts, counts, merged, vocabulary)
            if best is None or fit > best[0]:
                best = (fit, merged)
        partition = best[1]
        record(partition)
    chosen = min(levels, key=lambda level: level["bic"])
    return {"vocabulary": vocabulary, "steps": steps_total, "levels": levels, "chosen": chosen,
            "states": groups(chosen["partition"])}


def groups(partition: Partition) -> list[list[str]]:
    """A partition as lists of acts, the largest state first."""
    by_class: dict[str, list[str]] = {}
    for act, label in partition.items():
        by_class.setdefault(label, []).append(act)
    return sorted((sorted(members) for members in by_class.values()), key=lambda g: (-len(g), g))


THEORY: Partition = dict(act_rules.PHASE)


def adjusted_rand(left: Partition, right: Partition) -> float | None:
    """Agreement between two partitions over the acts both cover: 1 identical, about 0 at chance."""
    shared = sorted(set(left) & set(right))
    if len(shared) < 3:
        return None
    pairs = list(combinations(shared, 2))
    same_left = [left[a] == left[b] for a, b in pairs]
    same_right = [right[a] == right[b] for a, b in pairs]
    both = sum(1 for l, r in zip(same_left, same_right) if l and r)
    n_left, n_right, n = sum(same_left), sum(same_right), len(pairs)
    expected = n_left * n_right / n
    ceiling = (n_left + n_right) / 2
    return round((both - expected) / (ceiling - expected), 3) if ceiling != expected else 1.0


def held_out(seqs: list[tuple[str, ...]], partition: Partition, *, folds: int = 5, seed: int = 8252) -> float:
    """Bits per step on held-out trajectories: probabilities from four folds, likelihood on the fifth."""
    order = list(range(len(seqs)))
    random.Random(seed).shuffle(order)
    vocabulary = sorted({s for seq in seqs for s in seq})
    total, steps = 0.0, 0
    for fold in range(folds):
        test = bigrams([seqs[i] for n, i in enumerate(order) if n % folds == fold])
        train = bigrams([seqs[i] for n, i in enumerate(order) if n % folds != fold])
        total += log_likelihood(test, train, partition, vocabulary)
        steps += sum(test.values())
    return round(-total / steps, 4) if steps else float("nan")


def evaluate(seqs: list[tuple[str, ...]], *, pooled: Partition | None = None) -> dict[str, Any]:
    """Held-out bits per step for one set of trajectories under each candidate alphabet. Lower is better."""
    learned = induce(seqs)
    vocabulary = learned["vocabulary"]
    out = {
        "trajectories": len(seqs), "steps": learned["steps"], "acts_seen": len(vocabulary),
        "learned_states": learned["states"],
        "held_out_bits_per_step": {
            "own_learned_states": held_out(seqs, learned["chosen"]["partition"]),
            "theory_phases": held_out(seqs, THEORY),
            "every_act_its_own_state": held_out(seqs, {v: v for v in vocabulary}),
            "one_state": held_out(seqs, {v: "all" for v in vocabulary}),
        },
        "agreement_with_theory_phases": adjusted_rand(learned["chosen"]["partition"], THEORY),
        "by_number_of_states": [{"states": level["states"], "bits_per_step_in_sample": level["bits_per_step"], "bic": level["bic"]}
                                for level in learned["levels"]],
        "partition": learned["chosen"]["partition"],
    }
    if pooled is not None:
        out["held_out_bits_per_step"]["states_learned_from_all_domains"] = held_out(seqs, pooled)
    return out


def invariance(by_domain: dict[str, list[tuple[str, ...]]], *, resamples: int = 20, seed: int = 8252) -> dict[str, Any]:
    """Whether the learned states hold across domains.

    For every pair of domains (A, B): the held-out cost on A of using B's
    learned states in place of A's own (`borrowing_cost_bits`), and the
    agreement between the two partitions. Beside both, the same two figures
    for states learned from bootstrap resamples of A itself: what borrowing
    costs, and how much partitions disagree, when nothing but sampling
    differs."""
    rng = random.Random(seed)
    learned = {domain: induce(seqs)["chosen"]["partition"] for domain, seqs in by_domain.items()}
    pooled = induce([seq for seqs in by_domain.values() for seq in seqs])["chosen"]["partition"]
    own = {domain: held_out(seqs, learned[domain]) for domain, seqs in by_domain.items()}
    floor = {}
    for domain, seqs in by_domain.items():
        costs, agreements = [], []
        for _ in range(resamples):
            again = induce([rng.choice(seqs) for _ in seqs])["chosen"]["partition"]
            costs.append(held_out(seqs, again) - own[domain])
            agreements.append(adjusted_rand(learned[domain], again) or 0.0)
        floor[domain] = {
            "resample_borrowing_cost_bits": round(sum(costs) / resamples, 4),
            "resample_borrowing_cost_max": round(max(costs), 4),
            "resample_agreement": round(sum(agreements) / resamples, 3),
            "resample_agreement_min": round(min(agreements), 3),
        }
    pairs = []
    for a in sorted(by_domain):
        for b in sorted(by_domain):
            if a == b:
                continue
            cost = round(held_out(by_domain[a], learned[b]) - own[a], 4)
            agree = adjusted_rand(learned[a], learned[b])
            pairs.append({
                "states_of": b, "applied_to": a, "borrowing_cost_bits": cost, "agreement": agree,
                "cost_exceeds_every_resample": cost > floor[a]["resample_borrowing_cost_max"],
                "agreement_below_every_resample": agree is not None and agree < floor[a]["resample_agreement_min"],
            })
    exceed = sum(1 for p in pairs if p["cost_exceeds_every_resample"])
    below = sum(1 for p in pairs if p["agreement_below_every_resample"])
    return {
        "domains": {d: {"trajectories": len(s), "states": groups(learned[d]), "own_bits_per_step": own[d],
                        "theory_phases_bits_per_step": held_out(s, THEORY), "pooled_states_bits_per_step": held_out(s, pooled),
                        "agreement_with_theory_phases": adjusted_rand(learned[d], THEORY), **floor[d]}
                    for d, s in sorted(by_domain.items())},
        "pooled_states": groups(pooled),
        "pairs": pairs,
        "summary": {
            "ordered_pairs": len(pairs),
            "pairs_where_borrowing_costs_more_than_any_resample": exceed,
            "pairs_where_partitions_agree_less_than_any_resample": below,
            "mean_cross_domain_agreement": round(sum(p["agreement"] or 0 for p in pairs) / len(pairs), 3) if pairs else None,
            "mean_resample_agreement": round(sum(f["resample_agreement"] for f in floor.values()) / len(floor), 3) if floor else None,
        },
    }
