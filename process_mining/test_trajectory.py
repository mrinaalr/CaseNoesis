"""Tests for conduct reading and offense trajectories. Invented text only.

    .venv/bin/python -m unittest process_mining.test_trajectory -v
"""

from __future__ import annotations

import unittest

from extraction import acts, conduct, pipeline
from extraction.readers import Doc
from process_mining import trajectory

# Invented for this test.
FACTS = (
    "II. ELEMENTS OF THE OFFENSE\nThe government must prove beyond a reasonable doubt that the defendant recruited, enticed or transported a person.\n"
    "IV. FACTUAL BASIS\n"
    "4. On or about March 3, 2021, Sample created a profile on a dating website.\n"
    "5. Sample contacted Victim-1 on WhatsApp and posed as an engineer.\n"
    "6. In or about April 2021, Sample asked Victim-1 to send money for customs fees.\n"
    "7. Victim-1 wired $40,000 to an account that Sample named. The money that Victim-1 was paid by her employer was her savings.\n"
    "8. Sample withdrew the funds in cash.\n"
    "9. On or about May 2, 2022, agents executed a search warrant at the residence of Sample.\n"
)


def read(text: str = FACTS):
    return pipeline.read_doc(Doc("ct-test00000000000a", "court", "fraud", text, {}))


def kinds(result) -> list[str]:
    found = [(span[0], final["role"]) for final in result["resolutions"]["conduct"]["finals"] for span in final["spans"]]
    return [role for _, role in sorted(found)]


class ReadingTests(unittest.TestCase):
    def test_the_acts_of_a_narrative_in_order(self) -> None:
        self.assertEqual(kinds(read()), ["setup", "contact", "deception", "demand", "transfer", "movement", "detection"])

    def test_a_recital_of_the_statute_is_not_conduct(self) -> None:
        result = read()
        recital = [a for a in result["assertions"] if a["field"] == "conduct" and a["span_start"] < FACTS.index("IV. FACTUAL")]
        self.assertTrue(recital)
        self.assertEqual({a["role"] for a in recital}, {"not_conduct"})

    def test_was_paid_is_not_a_transfer(self) -> None:
        self.assertEqual(kinds(read()).count("transfer"), 1)

    def test_what_follows_an_ambiguous_verb_decides_it(self) -> None:
        self.assertEqual(kinds(read("Sample sent several messages to the victim on Telegram.")), ["contact"])
        self.assertEqual(kinds(read("The victim sent $5,000 to an account that Sample named.")), ["transfer"])

    def test_the_two_readers_can_disagree_and_then_nothing_is_stored(self) -> None:
        result = read("Sample opened fire on the building.")
        self.assertEqual(kinds(result), ["setup"] if result["resolutions"]["conduct"]["finals"] else [])

    def test_a_short_victim_label_does_not_break_a_demand(self) -> None:
        self.assertEqual(kinds(read("Sample instructed Company A to send future payments to a new account.")), ["demand"])


class VocabularyTests(unittest.TestCase):
    def test_every_kind_has_a_phase(self) -> None:
        self.assertEqual(set(acts.PHASE), set(acts.KINDS))
        self.assertEqual(set(acts.PHASE.values()), set(acts.PHASES))


def act(kind: str, **means) -> dict:
    return {"kind": kind, "phase": acts.PHASE[kind], "date": None, "means": means, "people": [], "status": "resolved"}


def traj(domain: str, *steps: dict) -> dict:
    return {"record_id": "r", "record_kind": "court", "domain": domain, "offenses": [], "acts": list(steps)}


class TrajectoryTests(unittest.TestCase):
    ONE = traj("fraud", act("setup"), act("contact", platform=["whatsapp"]), act("contact", platform=["whatsapp"]), act("demand"), act("transfer", channel=["wire_transfer"]))

    def test_three_levels_of_one_trajectory(self) -> None:
        self.assertEqual(trajectory.path(self.ONE, "act"), ("setup", "contact", "demand", "transfer"))
        self.assertEqual(trajectory.path(self.ONE, "phase"), ("preparation", "approach", "leverage", "harm"))
        self.assertEqual(trajectory.path(self.ONE, "means"), ("setup", "contact[whatsapp]", "demand", "transfer[wire_transfer]"))

    def test_a_run_of_one_step_is_one_step(self) -> None:
        self.assertEqual(conduct.path([{"kind": "transfer"}, {"kind": "transfer"}, {"kind": "movement"}]), ("transfer", "movement"))

    def test_transitions_are_frequencies_that_sum_to_one(self) -> None:
        table = trajectory.transitions([self.ONE, traj("fraud", act("setup"), act("deception"))], "act")["from"]
        self.assertEqual({n["step"]: n["probability"] for n in table["setup"]["next"]}, {"contact": 0.5, "deception": 0.5})
        self.assertEqual(table["setup"]["entropy_bits"], 1.0)
        self.assertEqual(table["demand"]["entropy_bits"], 0.0)

    def test_domains_that_differ_only_in_means_are_alike_above_that_level(self) -> None:
        phone = [traj("a", act("contact", channel=["phone_call"]), act("demand"), act("transfer", channel=["gift_card"])) for _ in range(30)]
        chat = [traj("b", act("contact", platform=["telegram"]), act("demand"), act("transfer", channel=["cryptocurrency"])) for _ in range(30)]
        levels = trajectory.compare(phone + chat, min_trajectories=5)["levels"]
        self.assertEqual(levels["act"]["steps"]["mean_divergence_bits"], 0.0)
        self.assertEqual(levels["phase"]["steps"]["mean_divergence_bits"], 0.0)
        self.assertGreater(levels["means"]["steps"]["above_shuffled"], 0.3)

    def test_identical_domains_do_not_differ(self) -> None:
        same = [traj(d, act("setup"), act("contact"), act("transfer")) for d in ("a", "b") for _ in range(30)]
        levels = trajectory.compare(same, min_trajectories=5)["levels"]
        self.assertEqual(levels["means"]["transitions"]["mean_divergence_bits"], 0.0)

    def test_the_export_holds_no_text(self) -> None:
        row = trajectory.export([self.ONE])[0]
        self.assertEqual(set(row), {"record_id", "record_kind", "domain", "offenses", "acts", "paths"})
        self.assertEqual(set(row["acts"][0]), {"kind", "phase", "date", "means"})

    def test_whether_the_telling_follows_the_dates(self) -> None:
        self.assertTrue(conduct.in_date_order([{"date": "2021-03"}, {"date": None}, {"date": "2021-04-10"}]))
        self.assertFalse(conduct.in_date_order([{"date": "2022-01-05"}, {"date": "2021-04-10"}]))
        self.assertIsNone(conduct.in_date_order([{"date": None}, {"date": "2021-04-10"}]))


if __name__ == "__main__":
    unittest.main()
