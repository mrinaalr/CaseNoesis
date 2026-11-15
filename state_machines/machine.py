"""The Exploitation State Machine, fitted to observed trajectories.

    M = (S, A, T, R_G, s0, F)

    S     the milestone states of `states`: Preparation, InitialContact, Conditioning, Exploitation, Maintenance
    A     a kind of act, or an act with the technology its sentence names (`transfer[gift_card]`), plus `(stop)`
    T     T(s' | s, a), counted from trajectories
    s0    `start`
    F     Completed, Disrupted, Unresolved
    R_G   not estimated; see `mdp`
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from state_machines import states as st

MACHINE_VERSION = "noesis_esm_2.0"


@dataclass
class Machine:
    level: str
    counts: dict[tuple[str, str], Counter] = field(default_factory=dict)  # (s, a) -> Counter of s'
    taken: dict[str, Counter] = field(default_factory=dict)  # s -> Counter of a
    trajectories: int = 0
    min_count: int = 5
    min_share: float = 0.01

    @property
    def actions(self) -> tuple[str, ...]:
        return tuple(sorted({a for (_, a) in self.counts if a not in (st.STOP, st.DETECTED)}))

    def available(self, state: str) -> list[str]:
        """The action space at a state: actions taken there at least `min_count` times and in at
        least `min_share` of departures from it, plus `(stop)`."""
        seen = self.taken.get(state, Counter())
        total = sum(seen.values())
        kept = [a for a, n in seen.items() if a not in (st.STOP, st.DETECTED) and n >= self.min_count and total and n / total >= self.min_share]
        return sorted(kept) + [st.STOP]

    def transition(self, state: str, action: str) -> dict[str, float]:
        """T(. | s, a). Taking an act either moves the state by its role or is followed by
        narrated detection; the second is folded in as P(Disrupted or Completed by detection | s, a)."""
        if action == st.STOP:
            return {_stop_outcome(state): 1.0}
        seen = self.counts.get((state, action), Counter())
        detected = self.detection.get((state, action), 0)
        total = sum(seen.values()) + detected
        if not total:
            return {}
        out = {nxt: n / total for nxt, n in seen.items()}
        if detected:
            end = _detected_outcome(state, action)
            out[end] = out.get(end, 0.0) + detected / total
        return out

    detection: dict[tuple[str, str], int] = field(default_factory=dict)  # (s, a) -> times detection was narrated right after

    def policy(self, state: str) -> dict[str, float]:
        seen = Counter({a: n for a, n in self.taken.get(state, Counter()).items() if a != st.DETECTED})
        total = sum(seen.values())
        return {a: round(n / total, 4) for a, n in seen.most_common()} if total else {}

    def estimates(self, minimum: int = 1) -> list[dict[str, Any]]:
        rows = []
        for (state, action), following in sorted(self.counts.items()):
            if action == st.DETECTED:
                continue
            total = sum(following.values()) + self.detection.get((state, action), 0)
            if total < minimum:
                continue
            for nxt, p in sorted(self.transition(state, action).items(), key=lambda i: -i[1]):
                rows.append({"from": state, "action": action, "to": nxt, "of": total, "probability": round(p, 4),
                             "times": round(p * total)})
        return rows

    def summary(self) -> dict[str, Any]:
        ends: Counter = Counter()
        for (state, action), following in self.counts.items():
            for terminal in st.TERMINAL:
                ends[terminal] += following[terminal]
        for (state, action), n in self.detection.items():
            ends[_detected_outcome(state, action)] += n
        return {
            "level": self.level, "trajectories": self.trajectories, "states": list(st.STATES),
            "actions_observed": len(self.actions), "state_action_pairs": sum(1 for (_, a) in self.counts if a not in (st.STOP, st.DETECTED)),
            "steps": sum(sum(c.values()) for c in self.counts.values()),
            "action_space_size": {s: len(self.available(s)) - 1 for s in (st.START, *st.STATES)},
            "ends": dict(ends),
            "feasibility_rule": f"taken at least {self.min_count} times and in at least {self.min_share:.0%} of departures",
        }


def _stop_outcome(state: str) -> str:
    return st.COMPLETED if state in (st.EXPLOITATION, st.MAINTENANCE) else st.UNRESOLVED


def _detected_outcome(state: str, action: str) -> str:
    """Detection right after an act: Completed if exploitation had been reached by then, counting this act."""
    after = st.next_state(state, action.split("[", 1)[0])
    return st.COMPLETED if after in (st.EXPLOITATION, st.MAINTENANCE) else st.DISRUPTED


def fit(trajectories: list[dict[str, Any]], *, level: str = "act", min_count: int = 5, min_share: float = 0.01) -> Machine:
    """Count steps. Detection narrated right after an act is credited to that act as its outcome."""
    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    taken: dict[str, Counter] = defaultdict(Counter)
    detection: Counter = Counter()
    used = 0
    for trajectory in trajectories:
        walked = st.steps(trajectory, level=level)
        used += bool(walked)
        for index, (state, action, nxt) in enumerate(walked):
            if action == st.DETECTED:
                previous = walked[index - 1]
                detection[(previous[0], previous[1])] += 1
                counts[(previous[0], previous[1])][previous[2]] -= 1  # the act's outcome was detection, not its state
                continue
            counts[(state, action)][nxt] += 1
            taken[state][action] += 1
    for key in list(counts):
        counts[key] = Counter({s: n for s, n in counts[key].items() if n > 0})
    return Machine(level, dict(counts), dict(taken), used, min_count, min_share, dict(detection))
