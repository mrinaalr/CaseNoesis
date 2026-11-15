"""A goal-conditioned decision model over the fitted machine, and measures of its fit.

It assumes an actor pursuing the scheme's goal. Nothing else in the package does.

    L_obs   observed walks
    L*      the path an actor pursuing the goal takes through the fitted machine under a declared cost model

The reward is not in the records; a `CostModel` declares it and every result carries its name.

    uniform    every act costs 1. L* is the shortest feasible path to the goal
    declared   a researcher's friction table, config/esm_costs.json

The goal is the scheme's goal at the machine's layer: any state at or under a goal state. It pays
once, on first arrival; the decision state carries whether it has been reached.

Measures: `rationality` fits beta in P(a | x) proportional to exp(beta Q*(x, a)) to the observed choices and
compares it with indifference and with random cost models; `agreement` is the share of choices that are
the optimal action; `paths` sets L* beside observed walks; `sensitivity` repeats them under nine cutoffs.

beta is fitted over [-20, 20]. A negative beta means choices lean away from what the cost model calls
optimal. A random cost model is counted as fitting better only when its fit is strictly better; one that
fits exactly as well is a tie, and ties are reported apart, since two models at beta = 0 always tie.

A walk whose telling starts at exploitation (a release that begins at the payment) makes a one-act path
to the goal look feasible from `start`. `from_start` keeps the walks told from preparation or contact, so
the fit is to choices made from the beginning of an offense.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from state_machines import machine as m
from state_machines.scheme import COMPLETED, DETECTED, DISRUPTED, START, STOP, TERMINAL, UNRESOLVED, Scheme
from state_machines.walks import Walk, steps

LEVELS = {"low": 1.0, "moderate": 2.0, "high": 3.0, "not_in_source": 2.0}
FRICTIONS = ("identityFriction", "delayBurden", "detectionExposure", "resourceCost")
COSTS_PATH = Path(__file__).resolve().parents[1] / "config" / "esm_costs.json"
State = tuple[str, bool]


@dataclass
class CostModel:
    name: str
    goal_value: float = 10.0
    step_cost: float = 1.0
    action_cost: dict[str, float] = field(default_factory=dict)
    disruption_cost: float = 10.0
    discount: float = 0.95

    def cost(self, action: str) -> float:
        if action == STOP:
            return 0.0
        return self.step_cost + self.action_cost.get(action, self.action_cost.get(action.split("[", 1)[0], 0.0))


def uniform(disruption_cost: float = 10.0) -> CostModel:
    return CostModel("uniform", disruption_cost=disruption_cost)


def declared(path: Path | None = None) -> CostModel | None:
    path = path or COSTS_PATH
    if not path.is_file():
        return None
    table = json.loads(path.read_text(encoding="utf-8"))
    costs = {a: sum(LEVELS[levels.get(f, "not_in_source")] for f in FRICTIONS) / len(FRICTIONS) - LEVELS["not_in_source"]
             for a, levels in (table.get("actions") or {}).items()}
    return CostModel(f"declared:{path.name}", action_cost=costs)


def random_costs(base: CostModel, actions: tuple[str, ...], seed: int) -> CostModel:
    rng = random.Random(seed)
    return CostModel(f"random:{seed}", base.goal_value, base.step_cost, {a: rng.uniform(0.0, 2.0) for a in actions},
                     base.disruption_cost, base.discount)


def outcomes(machine: m.Machine, state: State, action: str) -> dict[str, float]:
    """Where (s, a) leads from a decision state, with stopping and detection settled by whether
    the goal has been reached."""
    here, reached = state
    if action == STOP:
        return {COMPLETED if reached else UNRESOLVED: 1.0}
    out: dict[str, float] = {}
    for nxt, p in machine.transition(here, action).items():
        if nxt == DETECTED:
            done = 1.0 if reached else machine.detected_completes(here, action)
            for end, share in ((COMPLETED, done), (DISRUPTED, 1.0 - done)):
                if share:
                    out[end] = out.get(end, 0.0) + p * share
        else:
            out[nxt] = out.get(nxt, 0.0) + p
    return out


def solve(machine: m.Machine, costs: CostModel, *, tolerance: float = 1e-10, sweeps: int = 5000) -> dict[str, Any]:
    """Value iteration over (state, goal reached). Terminal states are worth 0."""
    scheme = machine.scheme
    states = [(s, r) for s in machine.states for r in (False, True)]
    value = {s: 0.0 for s in states}

    def q_of(state: State, action: str) -> float:
        reached = state[1]
        total = 0.0
        for nxt, p in outcomes(machine, state, action).items():
            reward = -costs.cost(action)
            if nxt in TERMINAL:
                # Completed without the goal reached before: this act reached it, then was detected.
                arrived = costs.goal_value if nxt == COMPLETED and not reached and action != STOP else 0.0
                total += p * (reward + arrived - (costs.disruption_cost if nxt == DISRUPTED else 0.0))
                continue
            arrive = scheme.is_goal(nxt) and not reached
            total += p * (reward + (costs.goal_value if arrive else 0.0) + costs.discount * value.get((nxt, reached or arrive), 0.0))
        return total

    for _ in range(sweeps):
        change = 0.0
        for state in states:
            best = max(q_of(state, a) for a in machine.available(state[0]))
            change, value[state] = max(change, abs(best - value[state])), best
        if change < tolerance:
            break
    q = {state: {a: q_of(state, a) for a in machine.available(state[0])} for state in states}
    policy = {state: max(o, key=lambda a: (round(o[a], 9), a)) for state, o in q.items()}
    return {"cost_model": costs.name, "goal": sorted(scheme.goal), "layer": machine.layer, "value": value, "q": q, "policy": policy}


def optimal_path(machine: m.Machine, solution: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    out, state = [], (START, False)
    for _ in range(limit):
        action = solution["policy"][state]
        following = outcomes(machine, state, action)
        nxt = max(following, key=lambda s: (following[s], s))
        out.append({"state": state[0], "action": action, "to": nxt, "probability": round(following[nxt], 3)})
        if nxt in TERMINAL:
            break
        state = (nxt, state[1] or machine.scheme.is_goal(nxt))
    return out


def _choices(walks: list[Walk], machine: m.Machine) -> Counter:
    out: Counter = Counter()
    for walk in walks:
        reached = False
        for here, action, nxt in steps(walk, machine.scheme, machine.layer, machine.level):
            if action == DETECTED:
                continue
            out[((here, reached), action)] += 1
            reached = reached or machine.scheme.is_goal(nxt)
    return out


def _log_likelihood(choices: Counter, q: dict[State, dict[str, float]], beta: float) -> tuple[float, int]:
    total, used = 0.0, 0
    for (state, action), n in choices.items():
        options = q.get(state) or {}
        if action not in options or len(options) < 2:
            continue
        top = max(options.values())
        total += n * (beta * (options[action] - top) - math.log(sum(math.exp(beta * (v - top)) for v in options.values())))
        used += n
    return total, used


def _fit_beta(choices: Counter, q: dict[State, dict[str, float]]) -> tuple[float, float, int]:
    """The log-likelihood is concave in beta, so a golden-section search finds its maximum."""
    low, high = -20.0, 20.0
    for _ in range(80):
        a, b = low + (high - low) * 0.382, low + (high - low) * 0.618
        if _log_likelihood(choices, q, a)[0] < _log_likelihood(choices, q, b)[0]:
            low = a
        else:
            high = b
    beta = (low + high) / 2
    fitted, used = _log_likelihood(choices, q, beta)
    return beta, fitted, used


def rationality(walks: list[Walk], machine: m.Machine, costs: CostModel, *, nulls: int = 100, seed: int = 8252) -> dict[str, Any]:
    choices = _choices(walks, machine)
    q = solve(machine, costs)["q"]
    beta, fitted, used = _fit_beta(choices, q)
    indifferent, _ = _log_likelihood(choices, q, 0.0)
    null = [_fit_beta(choices, solve(machine, random_costs(costs, machine.actions, seed + i))["q"])[1] for i in range(nulls)]
    tolerance = 1e-6 * max(1.0, abs(fitted))
    better = sum(1 for v in null if v > fitted + tolerance)
    tied = sum(1 for v in null if abs(v - fitted) <= tolerance)
    return {
        "cost_model": costs.name, "choices": used, "beta": round(beta, 3),
        "bits_per_choice_over_indifferent": round((fitted - indifferent) / used / math.log(2), 4) if used else None,
        "random_cost_models": len(null),
        "random_fitting_better": round(better / len(null), 3) if null else None,
        "random_fitting_as_well": round(tied / len(null), 3) if null else None,
    }


def agreement(walks: list[Walk], machine: m.Machine, solution: dict[str, Any]) -> dict[str, Any]:
    choices = [(s, a) for (s, a), n in _choices(walks, machine).items()
               for _ in range(n) if len(machine.available(s[0])) > 1 and a in machine.available(s[0])]
    hits = sum(1 for s, a in choices if solution["policy"][s] == a)
    modal = {s: c.most_common(1)[0][0] for s, c in machine.taken.items()}
    ceiling = sum(1 for s, a in choices if modal.get(s[0]) == a)
    return {"choices": len(choices), "optimal_action_taken": round(hits / len(choices), 4) if choices else None,
            "most_common_action_taken": round(ceiling / len(choices), 4) if choices else None}


def paths(walks: list[Walk], machine: m.Machine, solution: dict[str, Any]) -> dict[str, Any]:
    lengths, ends = [], Counter()
    for walk in walks:
        walked = steps(walk, machine.scheme, machine.layer, machine.level)
        acts = [s for s in walked if s[1] not in (STOP, DETECTED)]
        if acts:
            lengths.append(len(acts))
            ends[walked[-1][2]] += 1
    lengths.sort()
    best = optimal_path(machine, solution)
    n = len(lengths)
    return {"optimal_path": best, "optimal_length": sum(1 for s in best if s["action"] != STOP),
            "observed_median_length": lengths[n // 2] if n else None,
            "observed_ends": {k: round(v / n, 4) for k, v in ends.most_common()} if n else {}}


def sensitivity(walks: list[Walk], scheme: Scheme, costs: CostModel, *, layer: str = "milestone",
                counts=(1, 5, 20), shares=(0.0, 0.01, 0.05), nulls: int = 50) -> list[dict[str, Any]]:
    """The decision-model results under every feasibility cutoff, to show whether they depend on it."""
    rows = []
    for min_count in counts:
        for min_share in shares:
            fitted = m.fit(walks, scheme, layer=layer, min_count=min_count, min_share=min_share)
            solution = solve(fitted, costs)
            result = rationality(walks, fitted, costs, nulls=nulls)
            rows.append({"min_count": min_count, "min_share": min_share,
                         "optimal_path": " -> ".join(s["action"] for s in optimal_path(fitted, solution)),
                         "beta": result["beta"], "random_fitting_better": result["random_fitting_better"],
                         "random_fitting_as_well": result["random_fitting_as_well"],
                         "action_space_at_start": len(fitted.available(START)) - 1})
    return rows
