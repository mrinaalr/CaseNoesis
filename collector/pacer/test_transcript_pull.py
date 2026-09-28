#!/usr/bin/env python3
"""Mocked checks for the transcript pull. No network and no PACER."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cases2records import is_transcript_filing  # noqa: E402
import transcripts  # noqa: E402
from transcripts import (  # noqa: E402
    MANIFEST_FIELDS,
    _entry_number,
    _write_csv,
    apply_share_cleanup,
    assemble_sweep_rows,
    normalize_hearing_date,
    refined_hearing_type,
)
from pull_guard import (  # noqa: E402
    PullBudget,
    plan_transcript_pull,
    read_storage_pdf,
    run_transcript_pull,
    storage_url,
)


def row(**kwargs):
    base = {
        "status": "BUYABLE_LATER",
        "hearing_type": "sentencing",
        "approved": "pilot",
        "recap_document_id": "1",
        "docket_number": "1:23-cr-00001",
        "docket_id": "10",
        "docket_entry_number": "1",
        "page_count": "10",
        "domain": "fraud",
    }
    base.update(kwargs)
    return base


class FakeResponse:
    def __init__(self, status=200, content=b"%PDF-1.4", redirect=False):
        self.status_code = status
        self.content = content
        self.is_redirect = redirect


class FakeClient:
    def __init__(self, docs):
        self.docs = docs
        self.posts = []
        self.gets = []
        self.fail_post = False
        self.fail_wait = False

    def session_get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return FakeResponse()

    def get_recap_document(self, doc_id):
        return dict(self.docs.get(doc_id, {"is_available": False, "filepath_local": None, "page_count": 10}))

    def fetch_missing_pdf(self, doc_id, *, pacer_username, pacer_password):
        if self.fail_post:
            raise TimeoutError("timeout")
        self.posts.append(doc_id)
        return {"ok": True}

    def wait_for_recap_document(self, doc_id):
        if self.fail_wait:
            raise TimeoutError("wait")
        return dict(self.docs.get(doc_id, {"is_available": True, "filepath_local": "recap/x.pdf", "page_count": 10}))


class PullTests(unittest.TestCase):
    def test_minute_entry_is_not_a_transcript(self):
        text = "Minute Entry for proceedings held: see transcript of proceedings for a complete record."
        self.assertFalse(is_transcript_filing(text))
        self.assertTrue(is_transcript_filing("TRANSCRIPT of Proceedings held on May 1, 2024."))

        from datetime import date
        from cases2records import classify_transcript_status

        aged = classify_transcript_status(
            "TRANSCRIPT of Proceedings held on January 2, 2020. (Entered: 01/15/2020)",
            is_available=False,
            has_file=False,
            today=date(2026, 9, 28),
        )
        self.assertEqual(aged["status"], "BUYABLE_LATER")
        parsed = classify_transcript_status(
            "TRANSCRIPT of Proceedings held on May 1, 2024. Release of the Transcript Restriction is set for 10/28/2024. Page Numbers: 1-12.",
            is_available=False,
            has_file=False,
            today=date(2026, 9, 28),
        )
        self.assertEqual(parsed["restriction_release_date"], "2024-10-28")
        self.assertEqual(parsed["page_count"], 12)
        self.assertEqual(parsed["status"], "BUYABLE_LATER")
        rows = [
            row(recap_document_id="buy40", page_count="40", hearing_type="detention"),
            row(recap_document_id="free", status="FREE_NOW", page_count="3", hearing_type="change_of_plea"),
            row(recap_document_id="buy10", page_count="10"),
            row(recap_document_id="sealed", status="SEALED", page_count="4"),
            row(recap_document_id="trial", hearing_type="trial", page_count="8"),
            row(recap_document_id="unknown", page_count=""),
            row(recap_document_id="capped", page_count="", row_spend_cap_usd="10"),
            row(recap_document_id="other", approved="pilot-alternate", page_count="1"),
        ]
        plan = plan_transcript_pull(rows, approval_tag="pilot", max_spend=100, max_records=10)
        order = [item["recap_document_id"] for item in plan["planned"]]
        self.assertEqual(order, ["free", "buy10", "buy40", "capped"])
        reasons = {item["recap_document_id"]: item["reason"] for item in plan["refused"]}
        self.assertEqual(reasons["sealed"], "SEALED")
        self.assertEqual(reasons["trial"], "trial")
        self.assertEqual(reasons["unknown"], "unknown_pages")
        self.assertNotIn("other", order)

        capped = plan_transcript_pull(rows, approval_tag="pilot", max_spend=2.5, max_records=10)
        self.assertEqual([item["recap_document_id"] for item in capped["planned"]], ["free", "buy10"])

        few = plan_transcript_pull(rows, approval_tag="pilot", max_spend=100, max_records=1)
        self.assertEqual([item["recap_document_id"] for item in few["planned"]], ["free"])

    def test_storage_host_and_redirect(self):
        self.assertEqual(
            storage_url("recap/gov.uscourts.pdf"),
            "https://storage.courtlistener.com/recap/gov.uscourts.pdf",
        )
        with self.assertRaises(ValueError):
            storage_url("https://storage.courtlistener.com.example/x.pdf")
        with self.assertRaises(ValueError):
            storage_url("/etc/passwd")

        def redirecting(url, **kwargs):
            self.assertFalse(kwargs.get("allow_redirects", True))
            return FakeResponse(status=302, content=b"", redirect=True)

        with self.assertRaises(ValueError):
            read_storage_pdf(redirecting, "recap/x.pdf")

        def not_pdf(url, **kwargs):
            return FakeResponse(content=b"hello")

        with self.assertRaises(ValueError):
            read_storage_pdf(not_pdf, "recap/x.pdf")

    def test_available_document_does_not_post(self):
        client = FakeClient({7: {"is_available": True, "filepath_local": "recap/a.pdf", "page_count": 4}})
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.pdf"
            run_transcript_pull(
                [row(recap_document_id="7", status="BUYABLE_LATER", _mode="buy", _cost=1.0, _pages=10)],
                client=client,
                budget=PullBudget(100, 10),
                ledger_path=Path(tmp) / "ledger.csv",
                dest_for=lambda _row: dest,
            )
            self.assertEqual(client.posts, [])
            self.assertTrue(dest.read_bytes().startswith(b"%PDF"))

    def test_local_pdf_skips_post(self):
        client = FakeClient({})
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "a.pdf"
            dest.write_bytes(b"%PDF-1.4 already")
            run_transcript_pull(
                [row(recap_document_id="8", _mode="buy", _cost=1.0, _pages=10)],
                client=client,
                budget=PullBudget(100, 10),
                ledger_path=Path(tmp) / "ledger.csv",
                dest_for=lambda _row: dest,
            )
            self.assertEqual(client.posts, [])

    def test_failed_post_counts_and_stops(self):
        client = FakeClient({})
        client.fail_post = True
        with tempfile.TemporaryDirectory() as tmp:
            budget = PullBudget(100, 10)
            run_transcript_pull(
                [
                    row(recap_document_id="9", _mode="buy", _cost=1.5, _pages=15),
                    row(recap_document_id="99", _mode="buy", _cost=1.0, _pages=10),
                ],
                client=client,
                budget=budget,
                ledger_path=Path(tmp) / "ledger.csv",
                dest_for=lambda row: Path(tmp) / f"{row['recap_document_id']}.pdf",
            )
            self.assertEqual(client.posts, [])
            self.assertEqual(budget.spent, 1.5)
            self.assertTrue(budget.stop)
            text = (Path(tmp) / "ledger.csv").read_text()
            self.assertIn("failed", text)
            self.assertIn("9", text)
            self.assertNotIn("99", text)

    def test_actual_pages_stop_the_next_buy(self):
        client = FakeClient(
            {
                11: {"is_available": True, "filepath_local": "recap/long.pdf", "page_count": 60},
                12: {"is_available": False, "filepath_local": None, "page_count": 10},
            }
        )
        # First row is not yet available, so the wait returns 60 pages after the POST.
        client.docs[11] = {"is_available": False, "filepath_local": None, "page_count": 10}

        def wait(doc_id):
            if doc_id == 11:
                return {"is_available": True, "filepath_local": "recap/long.pdf", "page_count": 60}
            return {"is_available": True, "filepath_local": "recap/short.pdf", "page_count": 10}

        client.wait_for_recap_document = wait
        with tempfile.TemporaryDirectory() as tmp:
            budget = PullBudget(5, 10)
            run_transcript_pull(
                [
                    row(recap_document_id="11", _mode="buy", _cost=1.0, _pages=10),
                    row(recap_document_id="12", _mode="buy", _cost=1.0, _pages=10),
                ],
                client=client,
                budget=budget,
                ledger_path=Path(tmp) / "ledger.csv",
                dest_for=lambda row: Path(tmp) / f"{row['recap_document_id']}.pdf",
            )
            self.assertEqual(client.posts, [11])
            self.assertEqual(budget.spent, 6.0)
            self.assertTrue(budget.stop)

    def test_plan_refuses_duplicate_and_non_criminal(self):
        plan = plan_transcript_pull(
            [
                row(recap_document_id="2", status="FREE_NOW", duplicate_of="99"),
                row(recap_document_id="3", status="NON_CRIMINAL"),
                row(recap_document_id="4", status="DUPLICATE_OF=99", case_kind="criminal"),
                row(recap_document_id="5", status="BUYABLE_LATER", case_kind="non_criminal"),
            ],
            approval_tag="pilot",
            max_spend=100,
            max_records=10,
        )
        reasons = {item["recap_document_id"]: item["reason"] for item in plan["refused"]}
        self.assertEqual(reasons["2"], "DUPLICATE")
        self.assertEqual(reasons["3"], "NON_CRIMINAL")
        self.assertEqual(reasons["4"], "DUPLICATE")
        self.assertEqual(reasons["5"], "NON_CRIMINAL")
        self.assertEqual(plan["planned"], [])


class ShareCleanupTest(unittest.TestCase):
    def test_same_date_and_pages_keep_the_lower_entry(self):
        rows = [
            row(recap_document_id="20", docket_entry_number="576", docket_number="1:24-cr-00542", court="nysd", page_count="317", hearing_date="5/28/2025", hearing_type="trial", case_kind="criminal", status="FREE_NOW"),
            row(recap_document_id="10", docket_entry_number="417", docket_number="1:24-cr-00542", court="nysd", page_count="317", hearing_date="5/28/2025", hearing_type="trial", case_kind="criminal", status="FREE_NOW"),
        ]
        same = "TRANSCRIPT of Proceedings re: Trial held on 5/28/2025 before Judge Subramanian."
        report = apply_share_cleanup(rows, {"20": same + " Court Reporter: A", "10": same + " Court Reporter: A"})
        self.assertEqual(report["queued_removed"], 1)
        self.assertEqual(report["exact_pairs"][0]["kept_entry"], "417")
        self.assertEqual(report["exact_pairs"][0]["other_entry"], "576")
        marked = next(item for item in rows if item["recap_document_id"] == "20")
        self.assertEqual(marked["status"], "DUPLICATE_OF=10")
        self.assertEqual(marked["hearing_date"], "2025-05-28")

    def test_different_hearings_are_not_duplicates(self):
        rows = [
            row(recap_document_id="1", docket_entry_number="1", page_count="20", hearing_date="2024-01-01", case_kind="criminal", status="FREE_NOW"),
            row(recap_document_id="2", docket_entry_number="2", page_count="20", hearing_date="2024-01-01", case_kind="criminal", status="FREE_NOW"),
        ]
        report = apply_share_cleanup(
            rows,
            {
                "1": "TRANSCRIPT of Proceedings re: Trial held on 1/1/2024.",
                "2": "TRANSCRIPT of Proceedings re: Conference held on 1/1/2024.",
            },
        )
        self.assertEqual(report["exact_pairs"], [])
        self.assertEqual(report["descriptions_differed"][0]["action"], "kept_both")
        self.assertTrue(all(item["status"] == "FREE_NOW" for item in rows))

    def test_near_pages_are_flagged_not_dropped(self):
        rows = [
            row(recap_document_id="1", docket_entry_number="189", page_count="11", hearing_date="2022-10-13", case_kind="criminal"),
            row(recap_document_id="2", docket_entry_number="248", page_count="15", hearing_date="2022-10-13", case_kind="criminal"),
        ]
        report = apply_share_cleanup(rows, {"1": "TRANSCRIPT of Proceedings re: Conference held on 10/13/2022.", "2": "TRANSCRIPT of Proceedings re: Conference held on 10/13/2022."})
        self.assertEqual(report["exact_pairs"], [])
        self.assertEqual(len(report["near_pairs"]), 1)
        self.assertTrue(all("near_duplicate_pages" in item["review_flag"] for item in rows))
        different = [
            row(recap_document_id="3", docket_entry_number="189", page_count="11", hearing_date="2022-10-13", case_kind="criminal"),
            row(recap_document_id="4", docket_entry_number="248", page_count="15", hearing_date="2022-10-13", case_kind="criminal"),
        ]
        skipped = apply_share_cleanup(
            different,
            {
                "3": "TRANSCRIPT of Proceedings as to Yanbin Chen held on October 13, 2022.",
                "4": "TRANSCRIPT of Proceedings as to Hua Zhou held on October 13, 2022.",
            },
        )
        self.assertEqual(skipped["near_pairs"], [])

    def test_short_volume_and_sterling_domain(self):
        self.assertEqual(normalize_hearing_date("January 30, 2023"), "2023-01-30")
        self.assertEqual(refined_hearing_type("TRANSCRIPT of proceedings (Vol. I) for date of 1/13/2015.", "other"), "trial")
        rows = [
            row(recap_document_id="9", docket_number="1:10-cr-00485", docket_entry_number="472", page_count="1", hearing_date="", hearing_type="other", case_kind="criminal", domain="fraud"),
        ]
        apply_share_cleanup(rows, {"9": "TRANSCRIPT of Proceedings held on January 30, 2023."})
        self.assertEqual(rows[0]["domain"], "other_federal")
        self.assertEqual(rows[0]["hearing_date"], "2023-01-30")
        self.assertIn("under_3_pages", rows[0]["review_flag"])


def _transcript_hit(doc_id, docket_id, description, entry=None):
    hit = {
        "id": doc_id,
        "docket_id": docket_id,
        "description": description,
        "is_available": True,
        "filepath_local": "recap/x.pdf",
        "page_count": 20,
    }
    if entry is not None:
        hit["entry_number"] = entry
    return hit


class SweepMarkTest(unittest.TestCase):
    def test_entry_number_reads_hit_then_row_then_none(self):
        self.assertEqual(_entry_number({"entry_number": "12", "docket_entry_number": "99"}), "12")
        self.assertEqual(_entry_number({"docket_entry_number": "44"}), "44")
        self.assertIsNone(_entry_number({}))
        self.assertIsNone(_entry_number({"entry_number": "", "absolute_url": "/docket/1/15/x/"}))

    def test_sweep_marks_duplicates_and_civil(self):
        same = "TRANSCRIPT of Proceedings held on May 1, 2024. 20 pages."
        hits = [
            _transcript_hit(1, 1, "TRANSCRIPT of Proceedings re: Sentencing held on June 2, 2024. 12 pages.", 5),
            _transcript_hit(2, 1, "TRANSCRIPT of Proceedings re: Sentencing held on June 2, 2024. 12 pages.", 5),
            _transcript_hit(100, 1, same, 8),
            _transcript_hit(200, 1, same, 30),
            _transcript_hit(9, 3, "TRANSCRIPT of Proceedings held on May 1, 2024.", 4),
            _transcript_hit(11, 1, "TRANSCRIPT of Proceedings held on May 1, 2024."),
        ]
        inventory = {
            1: {"domain": "fraud", "court": "nysd", "docket_number": "1:23-cr-00001", "case_caption": "United States v. Example"},
            3: {"domain": "fraud", "court": "nysd", "docket_number": "1:25-cv-07679", "case_caption": "Ebadi v. Example"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            old = transcripts.MANIFEST
            transcripts.MANIFEST = Path(tmp) / "manifest.csv"
            try:
                rows = assemble_sweep_rows(hits, inventory, {})
            finally:
                transcripts.MANIFEST = old
        by_id = {str(item["recap_document_id"]): item for item in rows}
        self.assertEqual(by_id["2"]["status"], "DUPLICATE_OF=1")
        self.assertEqual(by_id["1"]["duplicate_of"], "")
        self.assertEqual(by_id["200"]["status"], "DUPLICATE_OF=100")
        self.assertEqual(by_id["100"]["status"], "FREE_NOW")
        self.assertEqual(by_id["9"]["status"], "NON_CRIMINAL")
        self.assertEqual(by_id["9"]["case_kind"], "non_criminal")
        self.assertEqual(by_id["11"]["status"], "UNCLEAR")
        self.assertEqual(by_id["11"]["unclear_reason"], "missing_entry_number")
        self.assertEqual(by_id["11"]["docket_entry_number"], "")
        self.assertFalse(any(item.get("duplicate_of") == "11" or str(item.get("status", "")).endswith("=11") for item in rows))

    def test_second_sweep_keeps_collected_canonical(self):
        sparse = "TRANSCRIPT of Proceedings."
        rich = "TRANSCRIPT of Proceedings held on May 1, 2024. 40 pages."
        hits = [
            _transcript_hit(50, 1, sparse, 10),
            _transcript_hit(80, 1, rich, 10),
        ]
        inventory = {
            1: {"domain": "fraud", "court": "nysd", "docket_number": "1:23-cr-00001", "case_caption": "United States v. Example", "source": "unit"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.csv"
            saved = row(
                recap_document_id="50",
                docket_id="1",
                docket_entry_number="10",
                docket_number="1:23-cr-00001",
                court="nysd",
                status="COLLECTED",
                approved="pilot",
                page_count="",
                hearing_date="",
            )
            _write_csv(manifest, MANIFEST_FIELDS, [saved])
            old = transcripts.MANIFEST
            transcripts.MANIFEST = manifest
            try:
                first = assemble_sweep_rows(hits, inventory, {})
                _write_csv(manifest, MANIFEST_FIELDS, first)
                second = assemble_sweep_rows(hits, inventory, {})
            finally:
                transcripts.MANIFEST = old
        for rows in (first, second):
            by_id = {str(item["recap_document_id"]): item for item in rows}
            self.assertEqual(by_id["50"]["status"], "COLLECTED")
            self.assertEqual(by_id["50"]["approved"], "pilot")
            self.assertEqual(by_id["50"]["duplicate_of"], "")
            self.assertEqual(by_id["80"]["status"], "DUPLICATE_OF=50")


if __name__ == "__main__":
    unittest.main()
