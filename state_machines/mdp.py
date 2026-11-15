"""A goal-conditioned decision model over the fitted machine, and tests of it.

The machine says what followed what. This module asks whether the observed
choices look like those of an actor pursuing a goal, under a stated account
of what actions cost, and how strongly.

    L_obs   the observed trajectories
    L*      the path a goal-directed actor takes through the fitted machine,
            under a declared cost model

**The reward is an assumption, and it is named.** A record states neither
what an act cost its author nor what the outcome was worth. A `CostModel`
names the goal states, the value of reaching one, the cost of each action and
of being disrupted. Every result carries the cost model's name.

    uniform    every action costs 1. L* is the shortest feasible path to the
               goal. The hypothesis it encodes is "offenders are direct".
    declared   a table a researcher writes (config/esm_costs.json): one level
               per friction per action, the four frictions of the `means`
               extension. It encodes "offenders take the easiest path", with
               "easy" defined by the researcher, not by the data.

**The state carries whether the goal has been reached.** The goal pays once,
on first arrival; the actor may then stop or keep acting. Without this, a
loop through the goal state would pay again on every pass.

**Tests.**

- `rationality` fits one parameter, beta, to the observed choices: the
  probability of taking action a in state s is proportional to
  exp(beta * Q*(s, a)). beta = 0 is indifference to the model's values. The
  log-likelihood at the fitted beta is compared with indifference and with
  the same fit under random cost models. A cost model that explains choices
  no better than random costs does not describe them.
- `agreement` is the share of observed choices that are the optimal action,
  beside the share an actor reaches who always takes each state's most common
  action: the ceiling any single-action rule can reach.
- `paths` compares L* with observed trajectories: length, and whether they
  reach the goal.

**What this is not.** States are kinds of stage and actions are kinds of act,
at the level of a textbook. The model is fitted to closed, public,
prosecuted cases, and the solved policy is published only at this level. It
is not written into the ontology: the `means` extension records no reward and
no Bellman value by design.
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

LEVELS = {"low": 1.0, "moderate": 2.0, "high": 3.0, "not_in_source": 2.0}
FRICTIONS = ("identityFriction", "delayBurden", "detectionExposure", "resourceCost")
COSTS_PATH = Path(__file__).resolve().parents[2] / "config" / "esm_costs.json"
State = tuple[str, bool]  # (machine state, goal already reached)


@dataclass
class CostModel:
    name: str
    goal: tuple[str, ...] = ("harm",)
    goal_value: float = 10.0
    step_cost: float = 1.0
    action_cost: dict[str, float] = field(default_factory=dict)  # by action, or by act kind
    disruption_cost: float = 10.0
    discount: float = 0.95

    def cost(self, action: str) -> float:
        if action == m.STOP:
            return 0.0
        kind = action.split("[", 1)[0]
        return self.step_cost + self.action_cost.get(action, self.action_cost.get(kind, 0.0))


def uniform(goal: tuple[str, ...] = ("harm",), disruption_cost: float = 10.0) -> CostModel:
    return CostModel("uniform", goal, disruption_cost=disruption_cost)


def declared(path: Path | None = None, goal: tuple[str, ...] = ("harm",)) -> CostModel | None:
    """The researcher's friction table, or None when there is none."""
    path = path or COSTS_PATH
    if not path.is_file():
        return None
    table = json.loads(path.read_text(encoding="utf-8"))
    costs = {action: sum(LEVELS[levels.get(f, "not_in_source")] for f in FRICTIONS) / len(FRICTIONS) - LEVELS["not_in_source"]
             for action, levels in (table.get("actions") or {}).items()}
    return CostModel(f"declared:{path.name}", tuple(table.get("goal") or goal), action_cost=costs)


def random_costs(base: CostModel, actions: tuple[str, ...], seed: int) -> CostModel:
    """Action costs drawn uniformly from [0, 2]: the null a cost model has to beat."""
    rng = random.Random(seed)
    return CostModel(f"random:{seed}", base.goal, base.goal_value, base.step_cost,
                     {a: rng.uniform(0.0, 2.0) for a in actions}, base.disruption_cost, base.discount)


def _states(machine: m.Machine) -> list[State]:
    return [(s, reached) for s in (m.START, *machine.states) for reached in (False, True)]


def solve(machine: m.Machine, costs: CostModel, *, tolerance: float = 1e-10, sweeps: int = 5000) -> dict[str, Any]:
    """Value iteration on V(s) = max_a sum_s' T(s'|s,a) [r(s,a,s') + gamma V(s')]. Terminal states are worth 0."""
    states = _states(machine)
    value: dict[State, float] = {s: 0.0 for s in states}

    def outcomes(state: State, action: str) -> list[tuple[float, float, State | None]]:
        here, reached = state
        out = []
        for nxt, p in machine.transition(here, action).items():
            reward = -costs.cost(action)
            if nxt == m.DISRUPTED:
                out.append((p, reward - costs.disruption_cost, None))
                continue
            if nxt == m.COMPLETED:
                out.append((p, reward, None))
                continue
            arrive = nxt in costs.goal and not reached
            out.append((p, reward + (costs.goal_value if arrive else 0.0), (nxt, reached or arrive)))
        return out

    def q_of(state: State, action: str) -> float:
        return sum(p * (r + (costs.discount * value[n] if n is not None else 0.0)) for p, r, n in outcomes(state, action))

    for _ in range(sweeps):
        change = 0.0
        for state in states:
            best = max(q_of(state, a) for a in machine.available(state[0]))
            change = max(change, abs(best - value[state]))
            value[state] = best
        if change < tolerance:
            break
    q = {state: {a: q_of(state, a) for a in machine.available(state[0])} for state in states}
    policy = {state: max(options, key=lambda a: (round(options[a], 9), a)) for state, options in q.items()}
    return {"cost_model": costs.name, "goal": list(costs.goal), "value": value, "q": q, "policy": policy, "costs": costs}


def optimal_path(machine: m.Machine, solution: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    """L*: from `start`, the optimal action and its most probable outcome, to a terminal state."""
    out, state, goal = [], (m.START, False), set(solution["goal"])
    for _ in range(limit):
        action = solution["policy"][state]
        following = machine.transition(state[0], action)
        nxt = max(following, key=lambda s: (following[s], s))
        out.append({"state": state[0], "action": action, "to": nxt, "probability": round(following[nxt], 3)})
        if nxt in m.TERMINAL:
            break
        state = (nxt, state[1] or nxt in goal)
    return out


def _observed_choices(trajectories: list[dict[str, Any]], machine: m.Machine, goal: set[str], states: m.StateMap) -> list[tuple[State, str]]:
    choices = []
    for trajectory in trajectories:
        reached = False
        for here, action, nxt in m.steps(trajectory, level=machine.level, states=states):
            choices.append(((here, reached), action))
            reached = reached or nxt in goal
    return choices


def _log_likelihood(choices: Counter, q: dict[State, dict[str, float]], beta: float) -> tuple[float, int]:
    """Log-likelihood of the observed choices (a Counter of (state, action)) under a softmax over Q."""
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
    """The beta in [0, 20] that maximises the log-likelihood (concave in beta), by golden-section search."""
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


def rationality(trajectories: list[dict[str, Any]], machine: m.Machine, costs: CostModel, *, states: m.StateMap = m.phase_state,
                nulls: int = 100, seed: int = 8252) -> dict[str, Any]:
    choices = Counter(_observed_choices(trajectories, machine, set(costs.goal), states))
    q = solve(machine, costs)["q"]
    beta, fitted, used = _fit_beta(choices, q)
    indifferent, _ = _log_likelihood(choices, q, 0.0)
    null = [_fit_beta(choices, solve(machine, random_costs(costs, machine.actions, seed + i))["q"])[1] for i in range(nulls)]
    return {
        "cost_model": costs.name, "goal": list(costs.goal), "choices_with_more_than_one_option": used, "beta": round(beta, 3),
        "log_likelihood": round(fitted, 1), "log_likelihood_indifferent": round(indifferent, 1),
        "bits_per_choice_over_indifferent": round((fitted - indifferent) / used / math.log(2), 4) if used else None,
        "random_cost_models": {
            "runs": nulls, "mean_log_likelihood": round(sum(null) / len(null), 1) if null else None,
            "share_fitting_at_least_as_well": round(sum(1 for v in null if v >= fitted) / len(null), 3) if null else None,
        },
    }


def agreement(trajectories: list[dict[str, Any]], machine: m.Machine, solution: dict[str, Any], *, states: m.StateMap = m.phase_state) -> dict[str, Any]:
    choices = [(s, a) for s, a in _observed_choices(trajectories, machine, set(solution["goal"]), states)
               if len(machine.available(s[0])) > 1 and a in machine.available(s[0])]
    hits = sum(1 for s, a in choices if solution["policy"][s] == a)
    modal = {s: machine.taken[s].most_common(1)[0][0] for s in machine.taken}
    ceiling = sum(1 for s, a in choices if modal.get(s[0]) == a)
    return {"cost_model": solution["cost_model"], "choices": len(choices),
            "optimal_action_taken": round(hits / len(choices), 4) if choices else None,
            "most_common_action_taken": round(ceiling / len(choices), 4) if choices else None}


def paths(trajectories: list[dict[str, Any]], machine: m.Machine, solution: dict[str, Any], *, states: m.StateMap = m.phase_state) -> dict[str, Any]:
    """L* beside the observed trajectories: how long, and whether they reach the goal."""
    goal = set(solution["goal"])
    lengths, reach, disrupted = [], 0, 0
    for trajectory in trajectories:
        walked = m.steps(trajectory, level=machine.level, states=states)
        acts = [s for s in walked if s[1] != m.STOP]
        if not acts:
            continue
        lengths.append(len(acts))
        reach += any(nxt in goal or (nxt == m.DISRUPTED and states({"kind": a.split("[")[0], "means": {}}) in goal) for _, a, nxt in acts)
        disrupted += walked[-1][2] == m.DISRUPTED
    lengths.sort()
    best = optimal_path(machine, solution)
    return {
        "cost_model": solution["cost_model"], "optimal_path": best, "optimal_length": sum(1 for s in best if s["action"] != m.STOP),
        "observed": {"trajectories": len(lengths), "median_length": lengths[len(lengths) // 2] if lengths else None,
                     "reach_goal": round(reach / len(lengths), 4) if lengths else None,
                     "end_in_narrated_detection": round(disrupted / len(lengths), 4) if lengths else None},
    }
