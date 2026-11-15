#!/usr/bin/env python3
"""Checks that public lookup rows carry no CourtListener case caption. No network.

    python3 -m unittest collector.test_public_lookup
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import public_lookup  # noqa: E402
from public_lookup import neutral_docket_url  # noqa: E402


def _caption_segments(url: str) -> list[str]:
    """Non-numeric path segments after /docket/ on a CourtListener page, other than the placeholder."""
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in {"courtlistener.com", "www.courtlistener.com"}:
        return []
    parts = [part for part in parsed.path.split("/") if part]
    if not parts or parts[0] != "docket":
        return []
    return [part for part in parts[1:] if not part.isdigit() and part != public_lookup.CAPTION_PLACEHOLDER]


class NeutralDocketUrl(unittest.TestCase):
    def test_entry_caption_replaced(self) -> None:
        self.assertEqual(
            neutral_docket_url("https://www.courtlistener.com/docket/73715928/104/united-states-v-a-person/"),
            "https://www.courtlistener.com/docket/73715928/104/case/",
        )

    def test_attachment_caption_replaced(self) -> None:
        self.assertEqual(
            neutral_docket_url("https://www.courtlistener.com/docket/69290092/1/1/united-states-v-person/"),
            "https://www.courtlistener.com/docket/69290092/1/1/case/",
        )

    def test_docket_caption_replaced(self) -> None:
        self.assertEqual(
            neutral_docket_url("https://www.courtlistener.com/docket/5471876/united-states-v-person"),
            "https://www.courtlistener.com/docket/5471876/case/",
        )

    def test_address_without_caption_gets_placeholder(self) -> None:
        # /docket/<id>/ alone is a 404 on CourtListener, so the placeholder is added.
        self.assertEqual(
            neutral_docket_url("https://www.courtlistener.com/docket/5471876/"),
            "https://www.courtlistener.com/docket/5471876/case/",
        )

    def test_query_kept_fragment_dropped(self) -> None:
        self.assertEqual(
            neutral_docket_url("https://www.courtlistener.com/docket/1/2/united-states-v-person/?page=2#entry-2"),
            "https://www.courtlistener.com/docket/1/2/case/?page=2",
        )

    def test_already_neutral_unchanged(self) -> None:
        url = "https://www.courtlistener.com/docket/73715928/104/case/"
        self.assertEqual(neutral_docket_url(url), url)

    def test_other_addresses_unchanged(self) -> None:
        for url in (
            "https://storage.courtlistener.com/recap/gov.uscourts.nyed.1/gov.uscourts.nyed.1.1.0.pdf",
            "https://www.courtlistener.com/opinion/1/some-opinion/",
            "https://www.justice.gov/usao-sdfl/pr/some-release",
            "",
        ):
            self.assertEqual(neutral_docket_url(url), url)


class AppendLookup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._public = public_lookup.PUBLIC
        self._seen = dict(public_lookup._seen)
        public_lookup.PUBLIC = Path(self._tmp.name)
        public_lookup._seen.clear()

    def tearDown(self) -> None:
        public_lookup.PUBLIC = self._public
        public_lookup._seen.clear()
        public_lookup._seen.update(self._seen)
        self._tmp.cleanup()

    def _rows(self) -> list[dict]:
        return public_lookup.read_lookup(Path(self._tmp.name) / public_lookup.FILES["recap"])

    def test_writer_cannot_add_caption(self) -> None:
        wrote = public_lookup.append_lookup(
            "recap",
            domain="trafficking",
            source_url="https://www.courtlistener.com/docket/73715928/104/united-states-v-a-person/",
        )
        self.assertTrue(wrote)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_url"], "https://www.courtlistener.com/docket/73715928/104/case/")
        self.assertNotIn("person", json.dumps(rows[0]))

    def test_same_entry_under_two_captions_written_once(self) -> None:
        base = "https://www.courtlistener.com/docket/73715928/104/"
        self.assertTrue(public_lookup.append_lookup("recap", source_url=base + "united-states-v-one/"))
        self.assertFalse(public_lookup.append_lookup("recap", source_url=base + "united-states-v-two/"))
        self.assertEqual(len(self._rows()), 1)

    def test_old_row_with_caption_counts_as_seen(self) -> None:
        path = Path(self._tmp.name) / public_lookup.FILES["recap"]
        path.write_text(
            json.dumps({"kind": "recap", "source_url": "https://www.courtlistener.com/docket/9/1/united-states-v-x/"})
            + "\n",
            encoding="utf-8",
        )
        self.assertFalse(
            public_lookup.append_lookup("recap", source_url="https://www.courtlistener.com/docket/9/1/case/")
        )


class CommittedLookups(unittest.TestCase):
    def test_no_committed_row_carries_a_caption(self) -> None:
        for path in public_lookup.lookup_paths():
            for rec in public_lookup.read_lookup(path):
                url = str(rec.get("source_url") or "")
                self.assertEqual(_caption_segments(url), [], f"{path.name}: {url}")


if __name__ == "__main__":
    unittest.main()
