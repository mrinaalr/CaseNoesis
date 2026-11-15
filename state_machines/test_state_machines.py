"""Tests for the Exploitation State Machine. Synthetic trajectories with planted structure; no collected data.

    .venv/bin/python -m unittest state_machines.test_state_machines -v

The point of each test is that a method finds what was planted, and does not find what was not.
"""

from __future__ import annotations

import math
import random
import unittest
from pathlib import Path

from state_machines import coverage, machine as m, mdp, states


def act(kind: str, **means) -> dict:
    return {"kind": kind, "date": None, "means": means, "status": "resolved"}


def traj(domain: str, *kinds: str, record: str = "r") -> dict:
    return {"record_id": record, "record_kind": "court", "domain": domain, "offenses": [], "acts": [act(k) for k in kinds]}


class StepTests(unittest.TestCase):
    def test_detection_is_an_outcome(self) -> None:
        walked = m.steps(traj("fraud", "contact", "deception", "transfer", "detection"))
        self.assertEqual(walked, [("start", "contact", "approach"), ("approach", "deception", "leverage"), ("leverage", "transfer", "disrupted")])

    def test_a_telling_that_ends_stops(self) -> None:
        self.assertEqual(m.steps(traj("fraud", "contact", "transfer"))[-1], ("harm", "(stop)", "completed"))

    def test_a_repeat_is_one_step(self) -> None:
        self.assertEqual(len(m.steps(traj("fraud", "transfer", "transfer", "transfer"))), 2)

    def test_means_level(self) -> None:
        t = {"record_id": "r", "domain": "fraud", "acts": [act("contact", platform=["whatsapp"])]}
        self.assertEqual(m.steps(t, level="means")[0][1], "contact[whatsapp]")


class FeasibilityTests(unittest.TestCase):
    def test_a_rare_action_is_not_in_the_action_space(self) -> None:
        many = [traj("fraud", "contact", "transfer") for _ in range(200)] + [traj("fraud", "threat", "transfer")]
        fitted = m.fit(many)
        self.assertIn("contact", fitted.available("start"))
        self.assertNotIn("threat", fitted.available("start"))
        self.assertIn("(stop)", fitted.available("start"))


class DecisionTests(unittest.TestCase):
    def test_uniform_cost_takes_the_shortest_feasible_path(self) -> None:
        log = [traj("fraud", "contact", "deception", "transfer") for _ in range(50)] + [traj("fraud", "setup", "contact", "transfer") for _ in range(50)]
        fitted = m.fit(log)
        best = mdp.optimal_path(fitted, mdp.solve(fitted, mdp.uniform()))
        self.assertEqual([s["action"] for s in best], ["contact", "transfer", "(stop)"])

    def test_the_goal_pays_once(self) -> None:
        # A loop between harm and exit must not be worth more than stopping once harm is reached.
        log = [traj("fraud", "transfer", "movement", "transfer", "movement") for _ in range(50)]
        fitted = m.fit(log)
        solution = mdp.solve(fitted, mdp.uniform())
        self.assertEqual(solution["policy"][("harm", True)], "(stop)")

    def test_disruption_risk_steers_the_path(self) -> None:
        risky = [traj("fraud", "contact", "transfer", "detection") for _ in range(40)]
        safe = [traj("fraud", "recruit", "deception", "transfer") for _ in range(40)]
        fitted = m.fit(risky + safe)
        first = mdp.optimal_path(fitted, mdp.solve(fitted, mdp.uniform()))[0]["action"]
        self.assertEqual(first, "recruit")

    def test_rationality_finds_a_planted_goal_directed_actor(self) -> None:
        # Fit a machine, then draw trajectories from a softmax over its own Q at beta = 2.
        base = [traj("fraud", *path) for path in (["contact", "transfer"], ["setup", "contact", "transfer"], ["deception", "transfer"],
                                                  ["contact", "deception", "transfer"], ["setup", "deception", "demand", "transfer"])] * 20
        fitted = m.fit(base)
        q = mdp.solve(fitted, mdp.uniform())["q"]
        rng = random.Random(3)
        drawn = []
        for _ in range(400):
            state, kinds = ("start", False), []
            for _ in range(8):
                options = q[state]
                weights = [math.exp(2.0 * v) for v in options.values()]
                choice = rng.choices(list(options), weights)[0]
                if choice == "(stop)":
                    break
                kinds.append(choice)
                nxt = m.phase_state({"kind": choice})
                state = (nxt, state[1] or nxt == "harm")
            if kinds:
                drawn.append(traj("fraud", *kinds))
        result = mdp.rationality(drawn, fitted, mdp.uniform(), nulls=20)
        self.assertGreater(result["beta"], 1.0)
        self.assertLess(result["random_cost_models"]["share_fitting_at_least_as_well"], 0.05)

    def test_rationality_finds_nothing_in_an_indifferent_actor(self) -> None:
        rng = random.Random(5)
        kinds = ["contact", "setup", "deception", "demand", "transfer", "movement", "recruit"]
        drawn = [traj("fraud", *rng.sample(kinds, rng.randint(2, 5))) for _ in range(400)]
        fitted = m.fit(drawn)
        result = mdp.rationality(drawn, fitted, mdp.uniform(), nulls=20)
        self.assertLess(result["bits_per_choice_over_indifferent"], 0.05)


class StateLearningTests(unittest.TestCase):
    @staticmethod
    def planted(groups: list[list[str]], n: int, seed: int) -> list[tuple[str, ...]]:
        """Sequences that move through `groups` in order, drawing any member of each group."""
        rng = random.Random(seed)
        return [tuple(rng.choice(g) for g in groups) for _ in range(n)]

    def test_induction_recovers_a_planted_partition(self) -> None:
        groups = [["setup", "contact"], ["deception", "demand", "threat"], ["transfer", "access"], ["movement", "concealment"]]
        learned = states.induce(self.planted(groups, 3000, 1))
        self.assertEqual(sorted(learned["states"]), sorted(sorted(g) for g in groups))

    def test_the_same_structure_in_two_domains_is_found_invariant(self) -> None:
        groups = [["setup", "contact"], ["deception", "demand"], ["transfer", "access"]]
        report = states.invariance({"a": self.planted(groups, 1500, 1), "b": self.planted(groups, 1500, 2)}, resamples=5)
        self.assertEqual(report["summary"]["pairs_where_partitions_agree_less_than_any_resample"], 0)
        self.assertGreater(report["summary"]["mean_cross_domain_agreement"], 0.9)

    def test_different_structures_are_found_different(self) -> None:
        a = self.planted([["setup", "contact"], ["deception", "demand"], ["transfer", "access"]], 1500, 1)
        b = self.planted([["setup", "deception"], ["contact", "transfer"], ["demand", "access"]], 1500, 2)
        report = states.invariance({"a": a, "b": b}, resamples=5)
        self.assertEqual(report["summary"]["pairs_where_borrowing_costs_more_than_any_resample"], 2)
        self.assertLess(report["summary"]["mean_cross_domain_agreement"], 0.2)

    def test_adjusted_rand(self) -> None:
        self.assertEqual(states.adjusted_rand({"a": "1", "b": "1", "c": "2", "d": "2"}, {"a": "x", "b": "x", "c": "y", "d": "y"}), 1.0)


class CoverageTests(unittest.TestCase):
    def test_backbone_and_intervention(self) -> None:
        log = [traj("a", "contact", "transfer")] * 30 + [traj("b", "contact", "deception", "transfer")] * 30
        report = coverage.coverage(log, min_trajectories=10)
        self.assertEqual(report["backbone_at_threshold"]["0.9"], ["approach", "harm"])
        kappa = coverage.intervention(log, min_trajectories=10)["kappa"]
        self.assertEqual(kappa["a"]["approach"], 0.0)
        self.assertEqual(kappa["b"]["leverage"], 0.0)


class OntologyTests(unittest.TestCase):
    def test_a_trajectory_graph_and_a_model_graph_validate(self) -> None:
        import tempfile

        from state_machines import ontology

        t = {"record_id": "ct-test0000000000aa", "domain": "fraud", "record_kind": "court", "offenses": [],
             "acts": [act("setup"), act("contact", platform=["whatsapp"], channel=["messaging_app"]), {**act("transfer"), "date": "2021-04"}, act("detection")]}
        with tempfile.TemporaryDirectory() as folder:
            ontology.ESM = Path(folder)
            record = ontology.record_graph(t, check=True)
            model = ontology.model_graph([t, {**t, "record_id": "ct-test0000000000ab"}], "test", check=True)
        self.assertTrue(record["conforms"], record)
        self.assertTrue(model["conforms"], model)


if __name__ == "__main__":
    unittest.main()
