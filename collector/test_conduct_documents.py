"""Tests for the conduct-document collector. No network: only how a docket entry is read.

    .venv/bin/python -m unittest collector.test_conduct_documents -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conduct_documents as cd  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def test_the_docket_names_the_filing(self) -> None:
        self.assertEqual(cd.classify("STATEMENT OF OFFENSE by USA as to A DEFENDANT. (Entered: 09/02/2026)", ""), "statement_of_offense")
        self.assertEqual(cd.classify("", "Factual Basis"), "factual_basis")
        self.assertEqual(cd.classify("Factual Resume as to A Defendant", "Factual Resume"), "factual_basis")
        self.assertEqual(cd.classify("COMPLAINT as to A DEFENDANT (1). (Attachments: # 1 Statement of Offense)", "Statement of Offense"), "statement_of_offense")
        self.assertEqual(cd.classify("CRIMINAL COMPLAINT as to A Defendant (1).", ""), "complaint_affidavit")

    def test_a_filing_that_only_mentions_one_is_not_one(self) -> None:
        self.assertIsNone(cd.classify("MOTION to Seal Statement of Offense by USA", ""))
        self.assertIsNone(cd.classify("ORDER granting motion to unseal criminal complaint", ""))
        self.assertIsNone(cd.classify("RESPONSE in Opposition re Factual Basis", ""))
        self.assertIsNone(cd.classify("Arrest Warrant Returned Executed", ""))

    def test_the_query_names_the_filing_and_the_domain(self) -> None:
        text = cd.query("factual_basis", "fraud")
        self.assertIn('description:("factual basis"', text)
        self.assertIn('"wire fraud"', text)

    def test_the_court_is_read_from_the_storage_path(self) -> None:
        self.assertEqual(cd.court_of("recap/gov.uscourts.dcd.297215/gov.uscourts.dcd.297215.1.1.pdf"), "dcd")

    def test_only_district_court_criminal_storage_paths_are_taken(self) -> None:
        self.assertTrue(cd._CRIMINAL_PATH.match("recap/gov.uscourts.ncwd.124787/gov.uscourts.ncwd.124787.3.0.pdf"))
        self.assertFalse(cd._CRIMINAL_PATH.match("recap/gov.uscourts.ca9.1234/x.pdf"))

    def test_every_download_address_is_the_free_archive(self) -> None:
        self.assertEqual(cd.cr.COURTLISTENER_STORAGE, "https://storage.courtlistener.com")
        self.assertFalse(cd.cr.download_free_pdf("https://ecf.dcd.uscourts.gov/doc1/123", Path("/tmp/never.pdf"))["ok"])


if __name__ == "__main__":
    unittest.main()
