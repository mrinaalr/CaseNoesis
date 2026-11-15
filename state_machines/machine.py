"""The Exploitation State Machine, fitted to walks at one layer of a scheme.

    M = (S, A, T, R_G, s0, F)

    S     the scheme's states at the layer: milestones, or tracks, or a source alphabet's states
    A     a kind of act, or an act with the technology its sentence names (`transfer[gift_card]`), plus `(stop)`
    T     T(s' | s, a), counted from walks
    s0    `start`
    F     Completed, Disrupted, Unresolved
    R_G   not estimated; see `mdp`

Nothing here depends on how the states were defined or read: any walks, any scheme.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from state_machines.scheme import COMPLETED, DETECTED, START, STOP, TERMINAL, Scheme
from state_machines.walks import Walk, steps

MACHINE_VERSION = "noesis_esm_3.0"


@dataclass
class Machine:
    scheme: Scheme
    layer: str
    level: str
    counts: dict[tuple[str, str], Counter] = field(default_factory=dict)  # (s, a) -> Counter of s'
    taken: dict[str, Counter] = field(default_factory=dict)  # s -> Counter of a
    detection: dict[tuple[str, str], Counter] = field(default_factory=dict)  # (s, a) -> Counter of the terminal detection led to
    trajectories: int = 0
    min_count: int = 5
    min_share: float = 0.01

    @property
    def states(self) -> list[str]:
        seen = {s for s in self.taken} | {n for c in self.counts.values() for n in c if n not in TERMINAL}
        order = {s: i for i, s in enumerate(self.scheme.states)}
        return [START] + sorted(seen - {START}, key=lambda s: (order.get(s, len(order)), s))

    @property
    def actions(self) -> tuple[str, ...]:
        return tuple(sorted({a for (_, a) in self.counts if a not in (STOP, DETECTED)}))

    def available(self, state: str) -> list[str]:
        """The action space at a state: actions taken there at least `min_count` times and in at
        least `min_share` of departures from it, plus `(stop)`."""
        seen = self.taken.get(state, Counter())
        total = sum(seen.values())
        kept = [a for a, n in seen.items() if a not in (STOP, DETECTED) and n >= self.min_count and total and n / total >= self.min_share]
        return sorted(kept) + [STOP]

    def transition(self, state: str, action: str) -> dict[str, float]:
        """T(. | s, a). Detection narrated right after an act is folded in as an outcome of the act:
        `(detected)`, whose terminal the decision model settles from whether the goal was reached."""
        if action == STOP:
            seen = self.counts.get((state, STOP), Counter())
            total = sum(seen.values())
            return {k: n / total for k, n in seen.items()} if total else {}
        seen = self.counts.get((state, action), Counter())
        detected = sum(self.detection.get((state, action), Counter()).values())
        total = sum(seen.values()) + detected
        if not total:
            return {}
        out = {nxt: n / total for nxt, n in seen.items()}
        if detected:
            out[DETECTED] = detected / total
        return out

    def detected_completes(self, state: str, action: str) -> float:
        """Of the times detection followed (s, a), the share that came after the goal was reached."""
        seen = self.detection.get((state, action), Counter())
        total = sum(seen.values())
        return seen[COMPLETED] / total if total else 0.0

    def policy(self, state: str) -> dict[str, float]:
        seen = self.taken.get(state, Counter())
        total = sum(seen.values())
        return {a: round(n / total, 4) for a, n in seen.most_common()} if total else {}

    def estimates(self, minimum: int = 1) -> list[dict[str, Any]]:
        rows = []
        for (state, action), following in sorted(self.counts.items()):
            if action == STOP:
                continue
            detected = self.detection.get((state, action), Counter())
            total = sum(following.values()) + sum(detected.values())
            if total < minimum:
                continue
            outcomes = {nxt: n for nxt, n in following.items()} | {end: n for end, n in detected.items()}
            for nxt, n in sorted(outcomes.items(), key=lambda i: -i[1]):
                rows.append({"from": state, "action": action, "to": nxt, "of": total, "probability": round(n / total, 4),
                             "times": n, **({"by": DETECTED} if nxt in detected and nxt not in following else {})})
        return rows

    def summary(self) -> dict[str, Any]:
        ends: Counter = Counter()
        for (_, action), following in self.counts.items():
            for terminal in TERMINAL:
                ends[terminal] += following[terminal]
        for found in self.detection.values():
            ends.update(found)
        return {
            "scheme": f"{self.scheme.name} {self.scheme.version}", "layer": self.layer, "level": self.level,
            "trajectories": self.trajectories, "states": self.states[1:],
            "actions_observed": len(self.actions), "state_action_pairs": sum(1 for (_, a) in self.counts if a != STOP),
            "steps": sum(sum(c.values()) for c in self.counts.values()) + sum(sum(c.values()) for c in self.detection.values()),
            "action_space_size": {s: len(self.available(s)) - 1 for s in self.states},
            "ends": {k: ends[k] for k in TERMINAL},
            "feasibility_rule": f"taken at least {self.min_count} times and in at least {self.min_share:.0%} of departures",
        }


def fit(walks: list[Walk], scheme: Scheme, *, layer: str = "milestone", level: str = "act", min_count: int = 5, min_share: float = 0.01) -> Machine:
    """Count steps. Detection narrated right after an act is credited to that act as its outcome."""
    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    taken: dict[str, Counter] = defaultdict(Counter)
    detection: dict[tuple[str, str], Counter] = defaultdict(Counter)
    used = 0
    for walk in walks:
        walked = steps(walk, scheme, layer, level)
        used += bool(walked)
        for index, (state, action, nxt) in enumerate(walked):
            if action == DETECTED:
                previous = walked[index - 1] if index else None
                if previous is None or previous[1] == DETECTED:
                    continue
                counts[(previous[0], previous[1])][previous[2]] -= 1  # its outcome was detection, not that state
                detection[(previous[0], previous[1])][nxt] += 1
                continue
            counts[(state, action)][nxt] += 1
            taken[state][action] += 1
    for key in list(counts):
        counts[key] = Counter({s: n for s, n in counts[key].items() if n > 0})
    return Machine(scheme, layer, level, dict(counts), dict(taken), dict(detection), used, min_count, min_share)

