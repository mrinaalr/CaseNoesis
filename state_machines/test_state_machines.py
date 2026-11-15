"""Tests for the Exploitation State Machine. Synthetic walks with planted structure; no collected data.

    .venv/bin/python -m unittest state_machines.test_state_machines -v
"""

from __future__ import annotations

import math
import random
import tempfile
import unittest
from pathlib import Path

from state_machines import coverage, invariance, machine as m, mdp, readers
from state_machines import scheme as sc
from state_machines.scheme import START, STOP
from state_machines.walks import Event, Walk, from_start, path, predicate, steps

S = sc.load()


def act(kind: str, **means) -> dict:
    return {"kind": kind, "date": None, "means": means, "status": "resolved"}


def traj(domain: str, *kinds: str, record: str = "r", means: dict | None = None) -> dict:
    return {"record_id": record, "record_kind": "court", "domain": domain, "offenses": [],
            "acts": [act(k, **(means or {}).get(k, {})) for k in kinds]}


def walk(domain: str, *kinds: str, means: dict | None = None) -> Walk:
    return readers.from_conduct(traj(domain, *kinds, means=means), S)


class SchemeTests(unittest.TestCase):
    def test_every_track_state_sits_under_one_milestone(self) -> None:
        for s in S.states.values():
            if s.layer == "track":
                self.assertEqual(S.states[s.broader].layer, "milestone", s.id)

    def test_a_broken_hierarchy_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            sc.from_dict({"name": "x", "layers": ["a"], "states": [{"id": "A", "layer": "a", "broader": "B"}]})
        with self.assertRaises(ValueError):
            sc.from_dict({"name": "x", "layers": ["a", "b"], "states": [{"id": "A", "layer": "a", "broader": "B"},
                                                                         {"id": "B", "layer": "b"}]})

    def test_leverage_after_the_goal_is_maintenance(self) -> None:
        self.assertEqual(S.project("Coercion", "milestone", False), "Conditioning")
        self.assertEqual(S.project("Coercion", "milestone", True), "Maintenance")
        self.assertEqual(S.project("Coercion", "track", True), "RenewedCoercion")

    def test_the_crosswalk_places_sdk_alphabets_under_esm_states(self) -> None:
        leak = S.by_iri["http://example.org/ontology/extortion/LeakThreat"]
        self.assertEqual(S.at(leak, "track"), "Coercion")
        self.assertEqual(S.at(leak, "milestone"), "Conditioning")
        self.assertEqual(S.by_iri["http://example.org/ontology/trafficking/Recruitment"], "Recruitment")
        self.assertTrue(S.is_goal(S.by_iri["http://example.org/ontology/elder-fraud/ProceedsCollection"]))

    def test_the_backbone_aligns_with_cac(self) -> None:
        for state in S.backbone:
            self.assertTrue(any(iri.startswith("https://cacontology.projectvic.org/grooming#") for _, iri in S.states[state].matches), state)


class ReaderTests(unittest.TestCase):
    def test_a_walk_at_both_layers(self) -> None:
        w = walk("fraud", "setup", "contact", "deception", "transfer", "movement")
        self.assertEqual(path(w, S), ["Preparation", "InitialContact", "Conditioning", "Exploitation", "Exit", "Completed"])
        self.assertEqual(path(w, S, "track"), ["Preparation", "Solicitation", "Deception", "ValueTaken", "Laundering", "Completed"])

    def test_the_same_act_moves_different_states(self) -> None:
        before = steps(walk("x", "contact", "deception"), S)[1]
        after = steps(walk("x", "transfer", "deception"), S)[1]
        self.assertEqual(before[2], "Conditioning")
        self.assertEqual(after[2], "Maintenance")

    def test_coercion_is_not_undone_by_deception(self) -> None:
        self.assertEqual(path(walk("x", "contact", "deception", "threat", "deception"), S, "track")[:4],
                         ["Solicitation", "Deception", "Coercion", "Unresolved"])

    def test_a_demand_alone_does_not_say_how_leverage_is_held(self) -> None:
        self.assertEqual(path(walk("x", "contact", "demand"), S, "track"), ["Solicitation", "Conditioning", "Unresolved"])

    def test_the_loop(self) -> None:
        self.assertEqual(path(walk("extortion", "contact", "threat", "transfer", "threat", "transfer"), S),
                         ["InitialContact", "Conditioning", "Exploitation", "Maintenance", "Exploitation", "Completed"])

    def test_how_a_walk_ends(self) -> None:
        self.assertEqual(path(walk("csea", "contact", "recruit", "detection"), S)[-1], "Disrupted")
        self.assertEqual(path(walk("fraud", "contact", "transfer", "detection"), S)[-1], "Completed")
        self.assertEqual(path(walk("fraud", "contact", "deception"), S)[-1], "Unresolved")

    def test_the_exploitation_predicate(self) -> None:
        self.assertEqual(predicate(walk("fraud", "deception", "transfer"), S), "passes")
        self.assertEqual(predicate(walk("drugs", "setup", "supply"), S), "fails")
        self.assertEqual(predicate(walk("fraud", "contact", "deception"), S), "not_reached")

    def test_a_graph_in_another_alphabet(self) -> None:
        from rdflib import Graph

        ttl = """
        @prefix traj: <http://example.org/ontology/trajectories/> .
        @prefix ex: <http://example.org/ontology/extortion/> .
        @prefix mine: <http://example.org/mine/> .
        @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        mine:Paid skos:broadMatch <http://example.org/ontology/trafficking/EarningsCollection> .
        mine:t a traj:Trajectory ; traj:hasPhaseAssertion mine:p0, mine:p1, mine:p2, mine:p3 .
        mine:p0 traj:assertsState ex:InitialAccess ; traj:sequenceIndex "0"^^xsd:nonNegativeInteger .
        mine:p1 traj:assertsState ex:Demand ; traj:sequenceIndex "1"^^xsd:nonNegativeInteger .
        mine:p2 traj:assertsState mine:Paid ; traj:sequenceIndex "2"^^xsd:nonNegativeInteger .
        mine:p3 traj:assertsState mine:Unknown ; traj:sequenceIndex "3"^^xsd:nonNegativeInteger ;
            traj:terminalPolarity "completed" .
        """
        walks, scheme, report = readers.from_graph(Graph().parse(data=ttl, format="turtle"), S, domain="extortion")
        self.assertEqual(path(walks[0], scheme), ["InitialContact", "Conditioning", "Exploitation", "Completed"])
        self.assertEqual(path(walks[0], scheme, "track"), ["Intrusion", "Coercion", "ValueTaken", "Completed"])
        self.assertEqual(report["states_unplaced"], ["http://example.org/mine/Unknown"])
        self.assertTrue(walks[0].meta["polarity_agrees"])

    def test_walks_from_any_extractor(self) -> None:
        data = {"states": [{"id": "Hook", "broader": "Deception"}],
                "walks": [{"id": "a", "domain": "fraud", "events": [{"action": "call", "state": "Solicitation"},
                                                                   {"action": "pitch", "state": "Hook"},
                                                                   {"action": "wire", "state": "ValueTaken"}]}]}
        walks, scheme = readers.from_json(data, S)
        self.assertEqual(path(walks[0], scheme, "source"), ["Solicitation", "Hook", "ValueTaken", "Completed"])
        self.assertEqual(path(walks[0], scheme), ["InitialContact", "Conditioning", "Exploitation", "Completed"])


class MachineTests(unittest.TestCase):
    def test_detection_is_an_outcome_of_the_act_before_it(self) -> None:
        log = [walk("x", "contact", "deception", "detection")] * 10 + [walk("x", "contact", "deception", "transfer")] * 30
        outcome = m.fit(log, S).transition("InitialContact", "deception")
        self.assertAlmostEqual(outcome["(detected)"], 0.25)
        self.assertAlmostEqual(outcome["Conditioning"], 0.75)

    def test_a_rare_action_is_not_in_the_action_space(self) -> None:
        fitted = m.fit([walk("x", "contact", "transfer")] * 200 + [walk("x", "threat", "transfer")], S)
        self.assertIn("contact", fitted.available(START))
        self.assertNotIn("threat", fitted.available(START))

    def test_the_same_walks_at_another_layer(self) -> None:
        log = [walk("x", "contact", "deception", "transfer")] * 20 + [walk("x", "recruit", "threat", "exploit")] * 20
        self.assertEqual(len(m.fit(log, S).states), 4)
        self.assertEqual(len(m.fit(log, S, layer="track").states), 7)


class DecisionTests(unittest.TestCase):
    def test_uniform_cost_takes_the_shortest_feasible_path(self) -> None:
        fitted = m.fit([walk("x", "contact", "deception", "transfer")] * 50 + [walk("x", "setup", "contact", "transfer")] * 50, S)
        best = mdp.optimal_path(fitted, mdp.solve(fitted, mdp.uniform()))
        self.assertEqual([s["action"] for s in best], ["contact", "transfer", STOP])

    def test_the_goal_pays_once(self) -> None:
        fitted = m.fit([walk("x", "transfer", "threat", "transfer", "threat")] * 50, S)
        self.assertEqual(mdp.solve(fitted, mdp.uniform())["policy"][("Exploitation", True)], STOP)

    def test_the_goal_pays_when_detection_follows_it(self) -> None:
        fitted = m.fit([walk("x", "contact", "transfer", "detection")] * 50, S)
        q = mdp.solve(fitted, mdp.uniform())["q"]
        self.assertGreater(q[("InitialContact", False)]["transfer"], q[("InitialContact", False)][STOP])

    def test_disruption_risk_steers_the_path(self) -> None:
        fitted = m.fit([walk("x", "contact", "deception", "detection")] * 40 + [walk("x", "contact", "demand", "transfer")] * 40, S)
        best = mdp.optimal_path(fitted, mdp.solve(fitted, mdp.uniform()))
        self.assertNotEqual(best[1]["action"], "deception")

    @staticmethod
    def sample(fitted: m.Machine, q: dict, beta: float, n: int, seed: int) -> list[Walk]:
        rng, drawn = random.Random(seed), []
        for i in range(n):
            state, events = (START, False), []
            for _ in range(8):
                options = q[state]
                choice = rng.choices(list(options), [math.exp(beta * v) for v in options.values()])[0]
                if choice == STOP:
                    break
                following = mdp.outcomes(fitted, state, choice)
                nxt = rng.choices(list(following), list(following.values()))[0]
                if nxt in sc.TERMINAL:
                    break
                events.append(Event(choice, nxt))
                state = (nxt, state[1] or S.is_goal(nxt))
            if events:
                drawn.append(Walk(f"w{i}", "x", events))
        return drawn

    def test_rationality_finds_a_planted_goal_directed_actor(self) -> None:
        base = [walk("x", *p) for p in (["contact", "transfer"], ["setup", "contact", "transfer"], ["deception", "transfer"],
                                        ["contact", "deception", "transfer"], ["setup", "deception", "demand", "transfer"])] * 20
        fitted = m.fit(base, S)
        drawn = self.sample(fitted, mdp.solve(fitted, mdp.uniform())["q"], 2.0, 400, 3)
        result = mdp.rationality(drawn, fitted, mdp.uniform(), nulls=20)
        self.assertGreater(result["beta"], 1.0)
        self.assertLess(result["random_fitting_better"], 0.05)

    def test_an_actor_avoiding_the_optimum_gives_a_negative_beta(self) -> None:
        base = [walk("x", *p) for p in (["contact", "transfer"], ["setup", "contact", "transfer"], ["deception", "transfer"],
                                        ["contact", "deception", "transfer"], ["setup", "deception", "demand", "transfer"])] * 20
        fitted = m.fit(base, S)
        drawn = self.sample(fitted, mdp.solve(fitted, mdp.uniform())["q"], -2.0, 400, 4)
        self.assertLess(mdp.rationality(drawn, fitted, mdp.uniform(), nulls=5)["beta"], -0.5)

    def test_ties_are_not_counted_as_fitting_better(self) -> None:
        rng = random.Random(5)
        kinds = ["contact", "setup", "deception", "demand", "transfer", "movement", "recruit"]
        drawn = [walk("x", *rng.sample(kinds, rng.randint(2, 5))) for _ in range(400)]
        result = mdp.rationality(drawn, m.fit(drawn, S), mdp.uniform(), nulls=10)
        self.assertLessEqual(result["random_fitting_better"] + result["random_fitting_as_well"], 1.0)
        self.assertIn("random_fitting_as_well", result)

    def test_tellings_from_the_start(self) -> None:
        log = [walk("x", "contact", "transfer"), walk("x", "transfer", "movement"), walk("x", "setup", "transfer")]
        self.assertEqual(len(from_start(log, S)), 2)

    def test_rationality_finds_nothing_in_an_indifferent_actor(self) -> None:
        rng = random.Random(5)
        kinds = ["contact", "setup", "deception", "demand", "transfer", "movement", "recruit"]
        drawn = [walk("x", *rng.sample(kinds, rng.randint(2, 5))) for _ in range(400)]
        result = mdp.rationality(drawn, m.fit(drawn, S), mdp.uniform(), nulls=20)
        self.assertLess(result["bits_per_choice_over_indifferent"], 0.05)

    def test_sensitivity_covers_every_cutoff(self) -> None:
        log = [walk("x", "contact", "deception", "transfer")] * 30
        self.assertEqual(len(mdp.sensitivity(log, S, mdp.uniform(), counts=(1, 5), shares=(0.0, 0.05), nulls=2)), 4)


class InvarianceTests(unittest.TestCase):
    """The claim predicts: same states, different acts. Plant each case and check the test sees it."""

    @staticmethod
    def domain(name: str, paths: list[list[str]], n: int, seed: int, means: dict | None = None) -> list[Walk]:
        rng = random.Random(seed)
        return [walk(name, *rng.choice(paths), means=means) for _ in range(n)]

    def compare(self, a: list[Walk], b: list[Walk], layer: str = "milestone") -> dict:
        return invariance.test({"a": a, "b": b}, S, layer=layer, repeats=5, shuffles=5)["levels"]

    def test_same_milestones_different_acts_and_tracks(self) -> None:
        a = self.domain("a", [["contact", "deception", "transfer"]], 300, 1)
        b = self.domain("b", [["recruit", "threat", "exploit"]], 300, 2)
        milestone, track = self.compare(a, b), self.compare(a, b, "track")
        self.assertLess(milestone["states"]["excess_bits"], 0.01)
        self.assertGreater(milestone["acts"]["excess_bits"], 0.5)
        self.assertGreater(track["states"]["excess_bits"], 0.5)

    def test_different_milestones(self) -> None:
        a = self.domain("a", [["contact", "deception", "transfer"]], 300, 1)
        b = self.domain("b", [["setup", "supply"]], 300, 2)
        self.assertGreater(self.compare(a, b)["states"]["excess_bits"], 0.3)

    def test_same_acts_different_technology(self) -> None:
        a = self.domain("a", [["contact", "transfer"]], 300, 1, means={"contact": {"platform": ["whatsapp"]}})
        b = self.domain("b", [["contact", "transfer"]], 300, 2, means={"contact": {"channel": ["phone_call"]}})
        levels = self.compare(a, b)
        self.assertLess(levels["acts"]["excess_bits"], 0.01)
        self.assertGreater(levels["means"]["excess_bits"], 0.5)


class NullTests(unittest.TestCase):
    """The tests of the claim itself: does the scheme's grouping, or the order of acts, explain the state level?"""

    @staticmethod
    def records(name: str, paths: list[list[str]], n: int, seed: int) -> list[dict]:
        rng = random.Random(seed)
        return [traj(name, *rng.choice(paths), record=f"{name}{i}") for i in range(n)]

    def run_nulls(self, a: list[dict], b: list[dict]) -> dict:
        return invariance.nulls({"a": a, "b": b}, S, lambda t: readers.from_conduct(t, S), kinds=sorted(readers.ROLE),
                                draws=12, shuffles=5)

    def test_a_grouping_that_captures_shared_states_beats_random_groupings(self) -> None:
        a = self.records("a", [["contact", "deception", "transfer"]], 200, 1)
        b = self.records("b", [["recruit", "threat", "exploit"]], 200, 2)
        self.assertGreater(self.run_nulls(a, b)["share_of_draws_observed_below_random_grouping"], 0.8)

    def test_on_random_acts_the_grouping_null_is_calibrated(self) -> None:
        """With no structure, the scheme's grouping is one grouping among many: over several datasets it
        beats a random grouping about half the time. A single dataset can land anywhere."""
        kinds = sorted(readers.ROLE)
        shares = []
        for seed in range(6):
            rng = random.Random(seed)
            weights = {d: [rng.random() for _ in kinds] for d in "ab"}
            groups = {d: [traj(d, *rng.choices(kinds, weights[d], k=rng.randint(2, 6)), record=f"{d}{i}") for i in range(150)] for d in "ab"}
            shares.append(self.run_nulls(groups["a"], groups["b"])["share_of_draws_observed_below_random_grouping"])
        self.assertGreater(sum(shares) / len(shares), 0.2)
        self.assertLess(sum(shares) / len(shares), 0.8)

    def test_records_without_a_step_are_left_out(self) -> None:
        a = self.records("a", [["contact", "deception", "transfer"]], 50, 1) + [traj("a", "detection", record="a-only")] * 10
        b = self.records("b", [["recruit", "threat", "exploit"]], 50, 2)
        self.assertEqual(self.run_nulls(a, b)["subsample_size"], 50)

    def test_order_that_differs_between_domains_is_seen(self) -> None:
        a = self.records("a", [["contact", "deception", "transfer"]], 200, 1)
        b = self.records("b", [["transfer", "deception", "contact"]], 200, 2)
        self.assertEqual(self.run_nulls(a, b)["share_of_draws_observed_below_shuffled_order"], 0.0)


class LawTests(unittest.TestCase):
    def test_laws_backbone_and_tracks(self) -> None:
        log = [walk("a", "contact", "deception", "transfer", "threat")] * 20 + [walk("a", "transfer")] * 20
        law = coverage.laws(log, S, minimum=10)["a"]
        self.assertEqual(law["contact_primacy"], 0.5)
        self.assertEqual(law["maintenance_after_goal"], 0.5)
        self.assertEqual(coverage.coverage(log, S, minimum=10)["backbone_at_threshold"]["0.9"], ["Exploitation"])
        self.assertEqual(coverage.intervention(log, S, minimum=10)["a"]["InitialContact"], 0.5)
        self.assertEqual(coverage.tracks(log, S, minimum=10)["a"]["Exploitation"], {"ValueTaken": 1.0})

    def test_a_scheme_without_a_role_skips_its_law(self) -> None:
        bare = sc.from_dict({"name": "bare", "layers": ["milestone"], "goal": ["G"], "roles": {"goal": "G"},
                             "states": [{"id": "A", "layer": "milestone"}, {"id": "G", "layer": "milestone"}]})
        log = [Walk("w", "d", [Event("x", "A"), Event("y", "G")])] * 20
        self.assertEqual(set(coverage.laws(log, bare, minimum=10)["d"]), {"reaching_goal", "goal_reentered"})


class OntologyTests(unittest.TestCase):
    def test_trajectory_model_and_scheme_graphs_validate(self) -> None:
        from state_machines import ontology

        t = {"record_id": "ct-test0000000000aa", "domain": "fraud", "record_kind": "court", "offenses": [],
             "acts": [act("setup"), act("contact", platform=["whatsapp"], channel=["messaging_app"]),
                      {**act("transfer"), "date": "2021-04"}, act("threat"), act("detection")]}
        with tempfile.TemporaryDirectory() as folder:
            ontology.ESM = Path(folder)
            record = ontology.record_graph(t, check=True)
            model = ontology.model_graph([t, {**t, "record_id": "ct-test0000000000ab"}], "test", layer="track", check=True)
            scheme = ontology.scheme_graph(check=True, path=Path(folder) / "esm.ttl")
            text = Path(record["path"]).read_text()
        for result in (record, model, scheme):
            self.assertTrue(result["conforms"], result)
        self.assertIn("grooming#MaintenancePhase", text)
        self.assertIn("skos:broader", text)
        self.assertIn('"completed"', text)


if __name__ == "__main__":
    unittest.main()
