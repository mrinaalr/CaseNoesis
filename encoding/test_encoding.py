"""Tests for the encoding stage. Synthetic text only; no collected data is read.

    .venv/bin/python -m unittest encoding.test_encoding -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from encoding import corpus, records, sdk

# Invented for this test. No person, bank, or docket here exists.
SYNTHETIC = (
    "UNITED STATES DISTRICT COURT\nNORTHERN DISTRICT OF EXAMPLE\n\n"
    "Case 1:99-cr-00001 Document 1 Filed 01/05/99\n\n"
    "1. From on or about January 3, 1999 until on or about January 9, 1999, the defendant "
    "telephoned an account holder and claimed to be a bank employee, in violation of "
    "18 U.S.C. § 1343.\n"
    "2. The account holder then wired $2,500.00 to an account the defendant controlled.\n"
)


class PinTests(unittest.TestCase):
    def test_checkout_is_the_pinned_commit(self) -> None:
        status = sdk.pin_status()
        self.assertEqual(status["commit"], sdk.SDK_COMMIT)
        self.assertTrue(status["pinned"])
        self.assertIn("trajectories", status["extensions"])

    def test_detects_the_extensions_a_graph_uses(self) -> None:
        exemplar = sdk.sdk_root() / "extensions/trafficking/trafficking-exemplar.ttl"
        self.assertEqual(sdk.extensions_used(exemplar), ["trafficking", "trajectories"])


class GateTests(unittest.TestCase):
    def test_valid_exemplar_conforms_and_is_publishable(self) -> None:
        receipt = sdk.gate(sdk.sdk_root() / "extensions/trafficking/trafficking-exemplar.ttl")
        self.assertTrue(receipt["conforms"])
        self.assertTrue(receipt["publishable"])
        self.assertEqual(receipt["sdk"]["commit"], sdk.SDK_COMMIT)

    def test_invalid_fixture_is_rejected_with_a_reason(self) -> None:
        fixture = sdk.sdk_root() / "extensions/trajectories/trajectories-invalid-terminal.ttl"
        receipt = sdk.gate(fixture)
        self.assertFalse(receipt["conforms"])
        self.assertFalse(receipt["publishable"])
        self.assertTrue(any("isTerminal" in item["message"] for item in receipt["messages"]))


class RecordLayerTests(unittest.TestCase):
    """Synthetic record -> SDK processor -> source URL added -> gate."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        rows = root / "rows.jsonl"
        rows.write_text(json.dumps({"body": SYNTHETIC, "title": "Synthetic"}) + "\n", encoding="utf-8")
        self.entry = {
            "record_id": "pr-synthetic000000",
            "kind": "press",
            "domain": "fraud",
            "source_url": "https://example.org/press/synthetic",
            "pub_date": "1999-01-10",
            "file": str(rows),
            "offset": 0,
        }
        self.patch = mock.patch.object(records, "RECORDS", root / "records")
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_record_is_encoded_validates_and_carries_its_source(self) -> None:
        status = records.process_one(self.entry, gate=True)
        self.assertEqual(status["status"], "encoded")
        self.assertTrue(status["conforms"])
        self.assertEqual(status["sdk_commit"], sdk.SDK_COMMIT)
        folder = records.record_dir(self.entry["record_id"])
        self.assertFalse(list(folder.glob("*.txt")))
        graph = (folder / "graph.jsonld").read_text(encoding="utf-8")
        self.assertIn("https://example.org/press/synthetic", graph)
        self.assertIn(status["source_sha256"], graph.lower())

    def test_an_encoded_record_is_not_processed_twice(self) -> None:
        first = records.process_one(self.entry)
        with mock.patch.object(records, "_processor", side_effect=AssertionError("must not run")):
            self.assertEqual(records.process_one(self.entry), first)


if __name__ == "__main__":
    unittest.main()
