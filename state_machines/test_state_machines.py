"""Tests for the Exploitation State Machine. Synthetic trajectories with planted structure; no collected data.

    .venv/bin/python -m unittest state_machines.test_state_machines -v
"""

from __future__ import annotations

import math
import random
import unittest
from pathlib import Path

from state_machines import coverage, invariance, machine as m, mdp, states as st


def act(kind: str, **means) -> dict:
    return {"kind": kind, "date": None, "means": means, "status": "resolved"}


def traj(domain: str, *kinds: str, record: str = "r", means: dict | None = None) -> dict:
    acts = [act(k, **(means or {}).get(k, {})) for k in kinds]
    return {"record_id": record, "record_kind": "court", "domain": domain, "offenses": [], "acts": acts}


class StateTests(unittest.TestCase):
    def test_a_state_is_what_has_been_reached(self) -> None:
        self.assertEqual(st.path(traj("fraud", "setup", "contact", "deception", "transfer")),
                         ["Preparation", "InitialContact", "Conditioning", "Exploitation", "Completed"])

    def test_the_same_act_moves_different_states(self) -> None:
        self.assertEqual(st.next_state(st.CONTACT, "deception"), st.CONDITIONING)
        self.assertEqual(st.next_state(st.EXPLOITATION, "deception"), st.MAINTENANCE)

    def test_maintenance_and_the_loop(self) -> None:
        self.assertEqual(st.path(traj("extortion", "contact", "threat", "transfer", "threat", "transfer")),
                         ["InitialContact", "Conditioning", "Exploitation", "Maintenance", "Exploitation", "Completed"])

    def test_how_a_trajectory_ends(self) -> None:
        self.assertEqual(st.path(traj("csea", "contact", "recruit", "detection"))[-1], "Disrupted")
        self.assertEqual(st.path(traj("fraud", "contact", "transfer", "detection"))[-1], "Completed")
        self.assertEqual(st.path(traj("fraud", "contact", "deception"))[-1], "Unresolved")

    def test_an_act_that_reaches_nothing_new_stays(self) -> None:
        self.assertEqual(st.steps(traj("fraud", "transfer", "movement"))[1], ("Exploitation", "movement", "Exploitation"))

    def test_the_exploitation_predicate(self) -> None:
        self.assertEqual(st.predicate(traj("fraud", "deception", "transfer")), "passes")
        self.assertEqual(st.predicate(traj("drugs", "setup", "supply")), "fails")
        self.assertEqual(st.predicate(traj("fraud", "contact", "deception")), "not_reached")

    def test_backbone_states_align_with_cac(self) -> None:
        self.assertEqual(set(st.CAC_MATCH), set(st.BACKBONE))
        self.assertTrue(all(iri.startswith("https://cacontology.projectvic.org/grooming#") for iri in st.CAC_MATCH.values()))


class MachineTests(unittest.TestCase):
    def test_detection_is_an_outcome_of_the_act_before_it(self) -> None:
        log = [traj("x", "contact", "deception", "detection")] * 10 + [traj("x", "contact", "deception", "transfer")] * 30
        fitted = m.fit(log)
        outcome = fitted.transition("InitialContact", "deception")
        self.assertAlmostEqual(outcome["Disrupted"], 0.25)
        self.assertAlmostEqual(outcome["Conditioning"], 0.75)

    def test_a_rare_action_is_not_in_the_action_space(self) -> None:
        fitted = m.fit([traj("x", "contact", "transfer")] * 200 + [traj("x", "threat", "transfer")])
        self.assertIn("contact", fitted.available("start"))
        self.assertNotIn("threat", fitted.available("start"))


class DecisionTests(unittest.TestCase):
    def test_uniform_cost_takes_the_shortest_feasible_path(self) -> None:
        fitted = m.fit([traj("x", "contact", "deception", "transfer")] * 50 + [traj("x", "setup", "contact", "transfer")] * 50)
        best = mdp.optimal_path(fitted, mdp.solve(fitted, mdp.uniform()))
        self.assertEqual([s["action"] for s in best], ["contact", "transfer", "(stop)"])

    def test_the_goal_pays_once(self) -> None:
        fitted = m.fit([traj("x", "transfer", "threat", "transfer", "threat")] * 50)
        self.assertEqual(mdp.solve(fitted, mdp.uniform())["policy"][("Exploitation", True)], "(stop)")

    def test_disruption_risk_steers_the_path(self) -> None:
        fitted = m.fit([traj("x", "contact", "deception", "detection")] * 40 + [traj("x", "contact", "demand", "transfer")] * 40)
        best = mdp.optimal_path(fitted, mdp.solve(fitted, mdp.uniform()))
        self.assertEqual(best[1]["action"], "transfer" if "transfer" in fitted.available("InitialContact") else "demand")

    def test_rationality_finds_a_planted_goal_directed_actor(self) -> None:
        base = [traj("x", *p) for p in (["contact", "transfer"], ["setup", "contact", "transfer"], ["deception", "transfer"],
                                        ["contact", "deception", "transfer"], ["setup", "deception", "demand", "transfer"])] * 20
        fitted = m.fit(base)
        q = mdp.solve(fitted, mdp.uniform())["q"]
        rng, drawn = random.Random(3), []
        for _ in range(400):
            state, kinds = (st.START, False), []
            for _ in range(8):
                options = q[state]
                choice = rng.choices(list(options), [math.exp(2.0 * v) for v in options.values()])[0]
                if choice == st.STOP:
                    break
                kinds.append(choice)
                nxt = st.next_state(state[0], choice)
                state = (nxt, state[1] or nxt == st.EXPLOITATION)
            if kinds:
                drawn.append(traj("x", *kinds))
        result = mdp.rationality(drawn, fitted, mdp.uniform(), nulls=20)
        self.assertGreater(result["beta"], 1.0)
        self.assertLess(result["random_cost_models_fitting_at_least_as_well"], 0.05)

    def test_rationality_finds_nothing_in_an_indifferent_actor(self) -> None:
        rng = random.Random(5)
        kinds = ["contact", "setup", "deception", "demand", "transfer", "movement", "recruit"]
        drawn = [traj("x", *rng.sample(kinds, rng.randint(2, 5))) for _ in range(400)]
        result = mdp.rationality(drawn, m.fit(drawn), mdp.uniform(), nulls=20)
        self.assertLess(result["bits_per_choice_over_indifferent"], 0.05)

    def test_sensitivity_covers_every_cutoff(self) -> None:
        log = [traj("x", "contact", "deception", "transfer")] * 30
        self.assertEqual(len(mdp.sensitivity(log, mdp.uniform(), counts=(1, 5), shares=(0.0, 0.05), nulls=2)), 4)


class InvarianceTests(unittest.TestCase):
    """The claim predicts: same states, different acts. Plant each case and check the test sees it."""

    @staticmethod
    def domain(name: str, paths: list[list[str]], n: int, seed: int, means: dict | None = None) -> list[dict]:
        rng = random.Random(seed)
        return [traj(name, *rng.choice(paths), means=means) for _ in range(n)]

    def test_same_states_different_acts(self) -> None:
        a = self.domain("a", [["contact", "deception", "transfer"]], 300, 1)
        b = self.domain("b", [["recruit", "threat", "exploit"]], 300, 2)
        levels = invariance.test({"a": a, "b": b}, repeats=5, shuffles=5)["levels"]
        self.assertLess(levels["states"]["excess_bits"], 0.01)
        self.assertGreater(levels["acts"]["excess_bits"], 0.5)

    def test_different_states(self) -> None:
        a = self.domain("a", [["contact", "deception", "transfer"]], 300, 1)
        b = self.domain("b", [["setup", "supply"]], 300, 2)
        levels = invariance.test({"a": a, "b": b}, repeats=5, shuffles=5)["levels"]
        self.assertGreater(levels["states"]["excess_bits"], 0.3)

    def test_same_acts_different_technology(self) -> None:
        a = self.domain("a", [["contact", "transfer"]], 300, 1, means={"contact": {"platform": ["whatsapp"]}})
        b = self.domain("b", [["contact", "transfer"]], 300, 2, means={"contact": {"channel": ["phone_call"]}})
        levels = invariance.test({"a": a, "b": b}, repeats=5, shuffles=5)["levels"]
        self.assertLess(levels["acts"]["excess_bits"], 0.01)
        self.assertGreater(levels["means"]["excess_bits"], 0.5)


class LawTests(unittest.TestCase):
    def test_laws_and_backbone(self) -> None:
        log = [traj("a", "contact", "deception", "transfer", "threat")] * 20 + [traj("a", "transfer")] * 20
        law = coverage.laws(log, minimum=10)["a"]
        self.assertEqual(law["contact_primacy"], 0.5)
        self.assertEqual(law["maintenance_after_exploitation"], 0.5)
        self.assertEqual(coverage.coverage(log, minimum=10)["backbone_at_threshold"]["0.9"], ["Exploitation"])
        self.assertEqual(coverage.intervention(log, minimum=10)["a"]["InitialContact"], 0.5)


class OntologyTests(unittest.TestCase):
    def test_trajectory_and_model_graphs_validate(self) -> None:
        import tempfile

        from state_machines import ontology

        t = {"record_id": "ct-test0000000000aa", "domain": "fraud", "record_kind": "court", "offenses": [],
             "acts": [act("setup"), act("contact", platform=["whatsapp"], channel=["messaging_app"]),
                      {**act("transfer"), "date": "2021-04"}, act("threat"), act("detection")]}
        with tempfile.TemporaryDirectory() as folder:
            ontology.ESM = Path(folder)
            record = ontology.record_graph(t, check=True)
            model = ontology.model_graph([t, {**t, "record_id": "ct-test0000000000ab"}], "test", check=True)
            text = Path(record["path"]).read_text()
        self.assertTrue(record["conforms"], record)
        self.assertTrue(model["conforms"], model)
        self.assertIn("grooming#MaintenancePhase", text)
        self.assertIn('"completed"', text)


if __name__ == "__main__":
    unittest.main()
