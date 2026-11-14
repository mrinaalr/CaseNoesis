"""Tests for the gold set: it is reproducible, it is what it says it is, and the
engine does not fall below what it scored on the development split.

    .venv/bin/python -m unittest gold.test_gold -v
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from extraction import fields
from gold import build, score


class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, cls.truth, cls.cases = build.load()

    def test_the_committed_corpus_is_what_the_generator_writes(self) -> None:
        records, truth, cases, _ = build.generate()
        self.assertEqual(json.dumps(records, sort_keys=True), json.dumps(self.records, sort_keys=True))
        self.assertEqual({t["record_id"]: t for t in json.loads(json.dumps(truth))}, self.truth)

    def test_size_and_split(self) -> None:
        self.assertEqual(len(self.records), 200)
        self.assertEqual(sum(1 for r in self.records if r["split"] == "dev"), 100)
        self.assertEqual({r["split"] for r in self.records}, {"dev", "test"})
        self.assertTrue(all(len({r["split"] for r in self.records if r["case_id"] == c["case_id"]}) == 1 for c in self.cases), "a case is in one split")

    def test_every_typed_token_is_claimed_or_listed_as_a_distractor(self) -> None:
        for record in self.records:
            gold = self.truth[record["record_id"]]
            known = {(item["field"], build._norm(item["field"], item["value"])) for key in ("values", "optional", "distractors") for item in gold[key]}
            for name, iterate in fields.ITERATORS.items():
                if name == "event":
                    continue
                for _, _, value, extras in iterate(record["text"]):
                    shown = ("life" if extras.get("life") else extras.get("months")) if name == "sentence" else value
                    self.assertIn((name, build._norm(name, shown)), known, record["record_id"])

    def test_every_personal_value_names_a_defendant_of_the_record(self) -> None:
        for gold in self.truth.values():
            for item in gold["values"]:
                self.assertTrue(set(item.get("persons", [])) <= set(gold["defendants"]))

    def test_sources_are_marked_as_invented(self) -> None:
        self.assertTrue(all(r["entry"]["source_url"].startswith("https://gold.example/") for r in self.records))


class FloorTests(unittest.TestCase):
    """The development split, rules only. A change that drops a score below its floor fails here."""

    FLOORS = {"sentence": 0.97, "money": 0.95, "date": 0.98, "statute": 0.98, "case_number": 0.98, "party": 0.97,
              "event": 0.95, "stage": 0.97, "offense": 0.97, "person_link": 0.98, "case_link": 0.98}

    def test_development_split_floors(self) -> None:
        with mock.patch.dict(os.environ, {"CASENOESIS_SYNTAX": ""}):
            report = score.evaluate("dev", "test-floors")
        for name, floor in self.FLOORS.items():
            self.assertGreaterEqual(report["fields"][name]["f1"], floor, name)
        self.assertGreaterEqual(report["attribution"]["accuracy_when_placed"], 0.97)
        self.assertGreaterEqual(report["traces"]["exact_rate"], 0.9)


if __name__ == "__main__":
    unittest.main()
