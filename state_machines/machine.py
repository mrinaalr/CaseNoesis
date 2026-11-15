"""The Exploitation State Machine, fitted to observed trajectories.

    M = (S, A, T, R_G, s0, F)

This module supplies the parts of the tuple that records can supply, and
keeps out the part they cannot.

    S     a state alphabet: a map from a kind of act to a state. The default is
          the five phases of `extraction.acts`. `states.induce` learns others
          from data, and any of them can be passed here.
    A     actions: a kind of act, or an act with the technology its sentence
          names (`contact[whatsapp]`), plus `(stop)`.
    T     T(s' | s, a), counted from trajectories. Taking act a moves the
          trajectory to the state of a, or to `disrupted` when the record
          narrates detection immediately after it.
    s0    `start`, the state every trajectory leaves from.
    F     `completed`: the actor stopped, or the record's telling ended.
          `disrupted`: the record narrates what investigators did next.
    R_G   not estimated. Records do not state rewards. `mdp` takes them as a
          declared assumption.

Every case in the corpus was prosecuted, so every offense in it was disrupted
in fact. `disrupted` here means the record narrates the detection; `completed`
means it does not. The split is about the telling.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from extraction import acts as act_rules

START = "start"
COMPLETED = "completed"
DISRUPTED = "disrupted"
TERMINAL = (COMPLETED, DISRUPTED)
STOP = "(stop)"
MACHINE_VERSION = "noesis_esm_1.0"

StateMap = Callable[[dict[str, Any]], str]


def phase_state(act: dict[str, Any]) -> str:
    """The default alphabet: the phase of an act."""
    return act_rules.PHASE[act["kind"]]


def alphabet(partition: dict[str, str]) -> StateMap:
    """A learned partition (act kind -> state label) as a state map."""
    return lambda act: partition.get(act["kind"], act["kind"])


def action_of(act: dict[str, Any], level: str = "act") -> str:
    """An act as an action: `contact`, or `contact[whatsapp]` at the means level."""
    if level == "act":
        return act["kind"]
    means = act.get("means") or {}
    labels = sorted(set(means.get("platform", []) + means.get("channel", [])))
    return f"{act['kind']}[{'+'.join(labels)}]" if labels else act["kind"]


def steps(trajectory: dict[str, Any], *, level: str = "act", states: StateMap = phase_state) -> list[tuple[str, str, str]]:
    """A trajectory as (state, action, next state) triples from `start` to a terminal state.

    A repeat of the same action into the same state is one step. An act
    followed by a narrated detection leads to `disrupted` and ends the
    trajectory; otherwise the trajectory ends with `(stop)`."""
    acts = trajectory["acts"]
    out: list[tuple[str, str, str]] = []
    here = START
    for index, act in enumerate(acts):
        if act["kind"] == "detection":
            if not out:
                continue  # a record that opens with the investigation: nothing yet to disrupt
            break
        action, there = action_of(act, level), states(act)
        detected_next = index + 1 < len(acts) and acts[index + 1]["kind"] == "detection"
        if out and out[-1][1] == action and out[-1][2] == there and not detected_next:
            continue
        if detected_next:
            out.append((here, action, DISRUPTED))
            return out
        out.append((here, action, there))
        here = there
    if out:
        out.append((here, STOP, COMPLETED))
    return out


@dataclass
class Machine:
    """A fitted machine: the counts, and estimates read off them."""

    level: str
    states: tuple[str, ...]
    actions: tuple[str, ...]
    counts: dict[tuple[str, str], Counter] = field(default_factory=dict)  # (s, a) -> Counter of s'
    taken: dict[str, Counter] = field(default_factory=dict)  # s -> Counter of a
    trajectories: int = 0
    min_count: int = 5
    min_share: float = 0.01

    def available(self, state: str) -> list[str]:
        """The action space at a state: actions taken there at least `min_count` times and in at
        least `min_share` of departures from it, plus `(stop)`. An action seen once is not evidence
        that it is open from that state."""
        seen = self.taken.get(state, Counter())
        total = sum(seen.values())
        kept = [a for a, n in seen.items() if a != STOP and n >= self.min_count and total and n / total >= self.min_share]
        return sorted(kept) + [STOP]

    def transition(self, state: str, action: str) -> dict[str, float]:
        """T(. | s, a): maximum-likelihood frequencies over the outcomes observed for this pair."""
        if action == STOP:
            return {COMPLETED: 1.0}
        seen = self.counts.get((state, action), Counter())
        total = sum(seen.values())
        return {nxt: n / total for nxt, n in seen.items()} if total else {}

    def policy(self, state: str) -> dict[str, float]:
        """pi_hat(a | s): how often each action was taken at a state. Descriptive, not a choice rule."""
        seen = self.taken.get(state, Counter())
        total = sum(seen.values())
        return {a: round(n / total, 4) for a, n in seen.most_common()} if total else {}

    def estimates(self, minimum: int = 1) -> list[dict[str, Any]]:
        """One row per observed (state, action, next state), with the counts behind it."""
        rows = []
        for (state, action), following in sorted(self.counts.items()):
            total = sum(following.values())
            if total >= minimum:
                rows += [{"from": state, "action": action, "to": nxt, "times": n, "of": total, "probability": round(n / total, 4)}
                         for nxt, n in following.most_common()]
        return rows

    def summary(self) -> dict[str, Any]:
        ends = Counter()
        for following in self.counts.values():
            for terminal in TERMINAL:
                ends[terminal] += following[terminal]
        return {
            "level": self.level, "trajectories": self.trajectories, "states": list(self.states),
            "actions_observed": len(self.actions), "state_action_pairs": len(self.counts),
            "steps": sum(sum(c.values()) for c in self.counts.values()),
            "action_space_size": {s: len(self.available(s)) - 1 for s in (START, *self.states)},
            "ends": dict(ends),
            "feasibility_rule": f"taken at least {self.min_count} times and in at least {self.min_share:.0%} of departures",
        }


def fit(trajectories: list[dict[str, Any]], *, level: str = "act", states: StateMap = phase_state,
        min_count: int = 5, min_share: float = 0.01) -> Machine:
    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    taken: dict[str, Counter] = defaultdict(Counter)
    seen_states: set[str] = set()
    seen_actions: set[str] = set()
    used = 0
    for trajectory in trajectories:
        path = steps(trajectory, level=level, states=states)
        used += bool(path)
        for state, action, nxt in path:
            counts[(state, action)][nxt] += 1
            taken[state][action] += 1
            if action != STOP:
                seen_actions.add(action)
            seen_states.update(s for s in (state, nxt) if s not in (START, *TERMINAL))
    order = [p for p in act_rules.PHASES if p in seen_states] + sorted(seen_states - set(act_rules.PHASES))
    return Machine(level, tuple(order), tuple(sorted(seen_actions)), dict(counts), dict(taken), used, min_count, min_share)
