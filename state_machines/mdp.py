"""A goal-conditioned decision model over the fitted machine, and tests of it.

    L_obs   observed trajectories
    L*      the path an actor pursuing the goal takes through the fitted machine under a declared cost model

The reward is not in the records; a `CostModel` declares it and every result carries its name.

    uniform    every act costs 1. L* is the shortest feasible path to the goal ("offenders are direct")
    declared   a researcher's friction table, config/esm_costs.json ("offenders take the easiest path")

The goal pays once, on first arrival; the state carries whether it has been reached.

Tests: `rationality` fits beta in P(a | x) proportional to exp(beta Q*(x, a)) to the observed choices and
compares it with indifference and with random cost models; `agreement` is the share of choices that are
the optimal action; `paths` sets L* beside observed trajectories.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from state_machines import machine as m, states as st

LEVELS = {"low": 1.0, "moderate": 2.0, "high": 3.0, "not_in_source": 2.0}
FRICTIONS = ("identityFriction", "delayBurden", "detectionExposure", "resourceCost")
COSTS_PATH = Path(__file__).resolve().parents[1] / "config" / "esm_costs.json"
GOAL = (st.EXPLOITATION,)
State = tuple[str, bool]


@dataclass
class CostModel:
    name: str
    goal: tuple[str, ...] = GOAL
    goal_value: float = 10.0
    step_cost: float = 1.0
    action_cost: dict[str, float] = field(default_factory=dict)
    disruption_cost: float = 10.0
    discount: float = 0.95

    def cost(self, action: str) -> float:
        if action == st.STOP:
            return 0.0
        return self.step_cost + self.action_cost.get(action, self.action_cost.get(action.split("[", 1)[0], 0.0))


def uniform(goal: tuple[str, ...] = GOAL, disruption_cost: float = 10.0) -> CostModel:
    return CostModel("uniform", goal, disruption_cost=disruption_cost)


def declared(path: Path | None = None, goal: tuple[str, ...] = GOAL) -> CostModel | None:
    path = path or COSTS_PATH
    if not path.is_file():
        return None
    table = json.loads(path.read_text(encoding="utf-8"))
    costs = {a: sum(LEVELS[levels.get(f, "not_in_source")] for f in FRICTIONS) / len(FRICTIONS) - LEVELS["not_in_source"]
             for a, levels in (table.get("actions") or {}).items()}
    return CostModel(f"declared:{path.name}", tuple(table.get("goal") or goal), action_cost=costs)


def random_costs(base: CostModel, actions: tuple[str, ...], seed: int) -> CostModel:
    rng = random.Random(seed)
    return CostModel(f"random:{seed}", base.goal, base.goal_value, base.step_cost,
                     {a: rng.uniform(0.0, 2.0) for a in actions}, base.disruption_cost, base.discount)


def solve(machine: m.Machine, costs: CostModel, *, tolerance: float = 1e-10, sweeps: int = 5000) -> dict[str, Any]:
    """Value iteration over (state, goal reached). Terminal states are worth 0."""
    states = [(s, r) for s in (st.START, *st.STATES) for r in (False, True)]
    value = {s: 0.0 for s in states}

    def q_of(state: State, action: str) -> float:
        here, reached = state
        total = 0.0
        for nxt, p in machine.transition(here, action).items():
            reward = -costs.cost(action)
            if nxt in st.TERMINAL:
                total += p * (reward - (costs.disruption_cost if nxt == st.DISRUPTED else 0.0))
                continue
            arrive = nxt in costs.goal and not reached
            total += p * (reward + (costs.goal_value if arrive else 0.0) + costs.discount * value[(nxt, reached or arrive)])
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
    return {"cost_model": costs.name, "goal": list(costs.goal), "value": value, "q": q, "policy": policy}


def optimal_path(machine: m.Machine, solution: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    out, state, goal = [], (st.START, False), set(solution["goal"])
    for _ in range(limit):
        action = solution["policy"][state]
        following = machine.transition(state[0], action)
        nxt = max(following, key=lambda s: (following[s], s))
        out.append({"state": state[0], "action": action, "to": nxt, "probability": round(following[nxt], 3)})
        if nxt in st.TERMINAL:
            break
        state = (nxt, state[1] or nxt in goal)
    return out


def _choices(trajectories: list[dict[str, Any]], level: str, goal: set[str]) -> Counter:
    out: Counter = Counter()
    for trajectory in trajectories:
        reached = False
        for here, action, nxt in st.steps(trajectory, level=level):
            if action == st.DETECTED:
                continue
            out[((here, reached), action)] += 1
            reached = reached or nxt in goal
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
    low, high = 0.0, 20.0
    for _ in range(80):
        a, b = low + (high - low) * 0.382, low + (high - low) * 0.618
        if _log_likelihood(choices, q, a)[0] < _log_likelihood(choices, q, b)[0]:
            low = a
        else:
            high = b
    beta = (low + high) / 2
    fitted, used = _log_likelihood(choices, q, beta)
    return beta, fitted, used


def rationality(trajectories: list[dict[str, Any]], machine: m.Machine, costs: CostModel, *, nulls: int = 100, seed: int = 8252) -> dict[str, Any]:
    choices = _choices(trajectories, machine.level, set(costs.goal))
    q = solve(machine, costs)["q"]
    beta, fitted, used = _fit_beta(choices, q)
    indifferent, _ = _log_likelihood(choices, q, 0.0)
    null = [_fit_beta(choices, solve(machine, random_costs(costs, machine.actions, seed + i))["q"])[1] for i in range(nulls)]
    return {
        "cost_model": costs.name, "goal": list(costs.goal), "choices": used, "beta": round(beta, 3),
        "bits_per_choice_over_indifferent": round((fitted - indifferent) / used / math.log(2), 4) if used else None,
        "random_cost_models_fitting_at_least_as_well": round(sum(1 for v in null if v >= fitted) / len(null), 3) if null else None,
    }


def agreement(trajectories: list[dict[str, Any]], machine: m.Machine, solution: dict[str, Any]) -> dict[str, Any]:
    choices = [(s, a) for (s, a), n in _choices(trajectories, machine.level, set(solution["goal"])).items()
               for _ in range(n) if len(machine.available(s[0])) > 1 and a in machine.available(s[0])]
    hits = sum(1 for s, a in choices if solution["policy"][s] == a)
    modal = {s: c.most_common(1)[0][0] for s, c in machine.taken.items()}
    ceiling = sum(1 for s, a in choices if modal.get(s[0]) == a)
    return {"choices": len(choices), "optimal_action_taken": round(hits / len(choices), 4) if choices else None,
            "most_common_action_taken": round(ceiling / len(choices), 4) if choices else None}


def paths(trajectories: list[dict[str, Any]], machine: m.Machine, solution: dict[str, Any]) -> dict[str, Any]:
    lengths, ends = [], Counter()
    for trajectory in trajectories:
        walked = st.steps(trajectory, level=machine.level)
        acts = [s for s in walked if s[1] not in (st.STOP, st.DETECTED)]
        if acts:
            lengths.append(len(acts))
            ends[walked[-1][2]] += 1
    lengths.sort()
    best = optimal_path(machine, solution)
    n = len(lengths)
    return {"optimal_path": best, "optimal_length": sum(1 for s in best if s["action"] != st.STOP),
            "observed_median_length": lengths[n // 2] if n else None,
            "observed_ends": {k: round(v / n, 4) for k, v in ends.most_common()} if n else {}}


def sensitivity(trajectories: list[dict[str, Any]], costs: CostModel, *, counts=(1, 5, 20), shares=(0.0, 0.01, 0.05), nulls: int = 50) -> list[dict[str, Any]]:
    """The decision-model results under every feasibility cutoff, to show whether they depend on it."""
    rows = []
    for min_count in counts:
        for min_share in shares:
            fitted = m.fit(trajectories, min_count=min_count, min_share=min_share)
            solution = solve(fitted, costs)
            result = rationality(trajectories, fitted, costs, nulls=nulls)
            rows.append({"min_count": min_count, "min_share": min_share,
                         "optimal_path": " -> ".join(f"{s['action']}" for s in optimal_path(fitted, solution)),
                         "beta": result["beta"], "random_fitting_at_least_as_well": result["random_cost_models_fitting_at_least_as_well"],
                         "action_space_at_start": len(fitted.available(st.START)) - 1})
    return rows
