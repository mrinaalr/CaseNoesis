#!/usr/bin/env python3
"""
Fetch federal docket PDFs from CourtListener (RECAP archive) into local records.

By default downloads only FREE docs already in RECAP (is_available=True).
PACER purchases are OFF unless you pass --charge-pacer (costs real money).

Output naming (flat in BULK_FOLDER):
  pacer -- {corpus_id} -- {doc type}.pdf
  pacer -- {corpus_id} -- manifest.json

Usage:
  # Safe: audit what's free vs needs PACER (no downloads, no charges)
  python collector/pacer/cases2records.py --preset wayerski --dry-run

  # Safe: pull only free key docs (indictment/plea/sentencing), max 4 per case
  python collector/pacer/cases2records.py --preset wayerski --key-docs --log-cost

  # Berger + 3 more bridge cases, free RECAP only
  python collector/pacer/cases2records.py --batch bridge4 --key-docs --log-cost

  # PAID — only when you explicitly want PACER charges via CourtListener recap-fetch
  python collector/pacer/cases2records.py --preset wayerski --key-docs --charge-pacer --log-cost

  # Transcripts are off unless you pass --transcripts (no $3/document cap).
  python collector/pacer/cases2records.py --preset wayerski --transcripts --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urljoin

import requests

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PACER_DIR = REPO_ROOT / "data" / "collected" / "PACER"
BULK_DIR = PACER_DIR / "BULK_FOLDER"
DEFAULT_ENV = REPO_ROOT / ".env"

sys.path.insert(0, str(HERE))
from pacer_cost import (  # noqa: E402
    append_cost_row,
    append_cost_rows,
    estimate_pacer_pdf_cost,
    estimate_transcript_pacer_cost,
)

API_BASE = "https://www.courtlistener.com/api/rest/v4/"
STORAGE_BASE = "https://storage.courtlistener.com/"

# CourtListener rate limits are tight on free tokens; stay under ~5 req/min.
MIN_REQUEST_INTERVAL_S = 12.5


class RateLimitExceeded(RuntimeError):
    """CourtListener hourly quota exhausted; stop and re-run after the window resets."""

# Pull priority for --key-docs (matches manual ICAC workflow in pacer_cost.csv).
KEY_DOC_SKIP = re.compile(
    r"minute order|notice of .*hearing|order of detention|scheduling order|"
    r"notice of attorney appearance|mandate of usca|"
    r"referral to magistrate|order of referral|referral",
    re.I,
)
# ICAC pull set: indictment, plea/proffer, sentencing only (no complaint/information noise).
KEY_DOC_RULES: Tuple[Tuple[re.Pattern[str], str, int], ...] = (
    (re.compile(r"superseding\s+indictment", re.I), "superseding indictment", 1),
    (re.compile(r"\bindictment\b", re.I), "indictment", 2),
    (re.compile(r"factual\s+proffer", re.I), "factual proffer", 3),
    (re.compile(r"plea\s+agreement", re.I), "plea agreement", 4),
    (re.compile(r"sentencing\s+(memo|memorandum)", re.I), "sentencing memo", 5),
    (re.compile(r"statement\s+of\s+offense", re.I), "statement of offense", 6),
)

# Docket text for a transcript filing. Default --key-docs does not select these.
TRANSCRIPT_FILING_RE = re.compile(
    r"\btranscript\s+of\s+proceedings\b|\bofficial\s+transcript\b",
    re.I,
)
_PRETRIAL_RE = re.compile(r"\bpre-?\s*trial\b", re.I)
_TRIAL_RE = re.compile(r"\b(?:jury\s+)?trial\b", re.I)
_RESTRICTION_RE = re.compile(
    r"Release of (?:the )?Transcript Restriction(?: is)? (?:set for|deadline of)\s+(\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)
_PAGE_SPAN_RE = re.compile(
    r"(?:Page\s*Nos?(?:\(s\))?|Page\s*Numbers?|Pages?)\s*:?\s*(\d+)\s*[-–—]\s*(\d+)",
    re.I,
)
_HEARING_DATE_RE = re.compile(
    r"\bheld on\s+(\d{1,2}/\d{1,2}/\d{4}|[A-Za-z]+ \d{1,2}, \d{4})",
    re.I,
)

BRIDGE4_PRESETS: Tuple[str, ...] = ("wayerski", "herrera", "katsampes", "ramirez")

# Human district labels → CourtListener court id (lowercase PACER slug).
DISTRICT_TO_COURT: Dict[str, str] = {
    "n.d. fla": "flnd",
    "n.d. florida": "flnd",
    "northern district of florida": "flnd",
    "flnd": "flnd",
    "w.d. tex": "txwd",
    "w.d. texas": "txwd",
    "western district of texas": "txwd",
    "txwd": "txwd",
    "d. alaska": "akd",
    "district of alaska": "akd",
    "akd": "akd",
    "s.d. fla": "flsd",
    "s.d. florida": "flsd",
    "southern district of florida": "flsd",
    "flsd": "flsd",
    "n.d. cal": "cand",
    "n.d. california": "cand",
    "northern district of california": "cand",
    "cand": "cand",
}


@dataclass
class CaseSpec:
    """Everything needed to resolve one federal docket."""

    slug: str
    defendant: str
    case_name: str
    district: str
    court: str
    docket: Optional[str] = None
    corpus_id: Optional[str] = None
    notes: str = ""


# Five graph-traversal PACER targets (conversation picks).
RECOMMENDED_CASES: Dict[str, CaseSpec] = {
    "wayerski": CaseSpec(
        slug="wayerski",
        defendant="Wayerski",
        case_name="United States v. Berger",
        district="N.D. Florida",
        court="flnd",
        docket="3:08-cr-00022",
        corpus_id="doj_archives_2008_034",
        notes="14-defendant international enterprise; caption Berger on CL.",
    ),
    "herrera": CaseSpec(
        slug="herrera",
        defendant="Herrera",
        case_name="United States v. Herrera",
        district="W.D. Texas",
        court="txwd",
        docket="3:25-cr-01046",
        corpus_id="doj_ceos_2025_002",
        notes="Also related D. Alaska 3:24-cr-00091 — pull separately if needed.",
    ),
    "katsampes": CaseSpec(
        slug="katsampes",
        defendant="Katsampes",
        case_name="United States v. Mcintosh",
        district="S.D. Florida",
        court="flsd",
        docket="9:24-cr-80053",
        corpus_id="doj_ceos_2025_031",
        notes="Operation Grayskull; caption Mcintosh on CL, Katsampes is co-defendant.",
    ),
    "ramirez": CaseSpec(
        slug="ramirez",
        defendant="Ramirez",
        case_name="United States v. Ramirez",
        district="N.D. California",
        court="cand",
        docket="3:24-cr-00564",
        corpus_id="doj_ceos_2025_003",
        notes="Donald Ramirez; Snapchat/Telegram/Wickr enticement (Salinas).",
    ),
    "geilenfeld": CaseSpec(
        slug="geilenfeld",
        defendant="Geilenfeld",
        case_name="United States v. MICHAEL KARL GEILENFELD",
        district="S.D. Florida",
        court="flsd",
        docket="1:24-cr-20008",
        corpus_id="doj_ceos_2025_013",
        notes="Haiti orphanage; foreign travel illicit sexual conduct.",
    ),
}


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
        load_dotenv(PACER_DIR / ".env", override=False)
    except ImportError:
        pass


def _normalize_district(district: str) -> str:
    return re.sub(r"\s+", " ", district.strip().lower())


def district_to_court(district: str, explicit_court: Optional[str] = None) -> str:
    if explicit_court:
        return explicit_court.strip().lower()
    key = _normalize_district(district)
    if key in DISTRICT_TO_COURT:
        return DISTRICT_TO_COURT[key]
    raise ValueError(
        f"Unknown district {district!r}. Pass --court explicitly "
        f"(e.g. flnd, txwd). Known aliases: {', '.join(sorted(set(DISTRICT_TO_COURT.values())))}"
    )


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return s or "case"


def case_id_for(spec: CaseSpec) -> str:
    return spec.corpus_id or spec.slug


def doc_type_label(description: str, *, entry_num: Any = None, doc_num: Any = None) -> str:
    """Human doc label for filenames: pacer -- {caseid} -- {doc type}.pdf"""
    desc = (description or "").strip()
    if desc:
        line = desc.split("\n")[0].strip()
        line = re.sub(r"^\d+\s+", "", line)
        line = re.split(r"\s+as to\b", line, maxsplit=1, flags=re.I)[0].strip()
        line = line.split(".")[0].strip()
        if line:
            desc = line
    if not desc:
        if entry_num is not None:
            desc = f"Entry {entry_num}"
        elif doc_num is not None:
            desc = f"Document {doc_num}"
        else:
            desc = "document"
    desc = re.sub(r'[<>:"/\\|?*]', "", desc)
    desc = re.sub(r"\s+", " ", desc).strip()
    return desc[:120] or "document"


def bulk_pdf_name(case_id: str, doc_type: str, *, disambiguator: str = "") -> str:
    label = doc_type
    if disambiguator:
        label = f"{label} ({disambiguator})"
    return f"pacer -- {case_id} -- {label}.pdf"


def resolve_pdf_path(
    base: Path,
    case_id: str,
    label: str,
    *,
    entry_num: Any = None,
    doc_num: Any = None,
    used_names: Dict[str, int],
) -> Path:
    """Assign a unique BULK_FOLDER path; suffix when doc types collide."""
    key = label.lower()
    used_names[key] = used_names.get(key, 0) + 1
    count = used_names[key]
    disambiguator = ""
    if count > 1:
        parts = []
        if entry_num not in (None, ""):
            parts.append(f"entry {entry_num}")
        if doc_num not in (None, "") and doc_num != entry_num:
            parts.append(f"doc {doc_num}")
        disambiguator = ", ".join(parts) if parts else f"copy {count}"
    return base / bulk_pdf_name(case_id, label, disambiguator=disambiguator)


def _docket_core(docket_number: str) -> str:
    m = re.search(r"(\d{2}-(?:cr|mj)-\d+)", docket_number.lower())
    return m.group(1) if m else docket_number.lower()


def _docket_variants(docket_number: str) -> List[str]:
    variants = [docket_number]
    if docket_number.startswith("0:"):
        variants.append("9:" + docket_number[2:])
    return list(dict.fromkeys(variants))


def _sort_key_num(val: Any) -> Tuple[int, str]:
    if val is None:
        return (0, "")
    if isinstance(val, int):
        return (1, f"{val:010d}")
    return (2, str(val))
    if val is None:
        return (0, "")
    if isinstance(val, int):
        return (1, f"{val:010d}")
    return (2, str(val))


class CourtListenerClient:
    def __init__(
        self,
        token: str,
        min_interval: float = MIN_REQUEST_INTERVAL_S,
        max_quota_wait_s: float = 300.0,
    ) -> None:
        if not token:
            raise ValueError(
                "CourtListener API token required. Set COURTLISTENER_API_TOKEN in "
                f"{DEFAULT_ENV} (create at https://www.courtlistener.com/profile/api/)."
            )
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Token {token}"
        self._min_interval = min_interval
        self._last_request = 0.0
        # Cumulative budget for sleeping through 429s. When the server's
        # Retry-After demands exceed it, raise RateLimitExceeded instead of
        # silently grinding — the caller should stop and re-run later.
        self._max_quota_wait_s = max_quota_wait_s
        self._quota_slept_s = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _handle_429(self, resp: requests.Response) -> None:
        wait = int(resp.headers.get("Retry-After", "15")) + 2
        if self._quota_slept_s + wait > self._max_quota_wait_s:
            raise RateLimitExceeded(
                f"CourtListener hourly quota exhausted: server asks for {wait}s more "
                f"and {self._quota_slept_s:.0f}s of the {self._max_quota_wait_s:.0f}s "
                "wait budget is already spent. Re-run after the quota window resets."
            )
        print(
            f"    [rate-limit] CourtListener 429 — sleeping {wait}s "
            f"({self._quota_slept_s:.0f}s/{self._max_quota_wait_s:.0f}s budget used)",
            file=sys.stderr,
        )
        time.sleep(wait)
        self._quota_slept_s += wait

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = urljoin(API_BASE, path.lstrip("/"))
        for attempt in range(4):
            self._throttle()
            resp = self._session.request(method, url, timeout=120, **kwargs)
            self._last_request = time.monotonic()
            if resp.status_code == 429 and attempt < 3:
                self._handle_429(resp)
                continue
            if resp.status_code == 401:
                raise PermissionError(
                    "CourtListener returned 401 — check COURTLISTENER_API_TOKEN in .env"
                )
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp  # unreachable

    def paginate(self, path: str, params: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        url: Optional[str] = None
        first = True
        while url or first:
            first = False
            if url:
                self._throttle()
                resp = self._session.get(url, timeout=120)
                self._last_request = time.monotonic()
                if resp.status_code == 429:
                    self._handle_429(resp)
                    continue
                resp.raise_for_status()
            else:
                resp = self._request("GET", path, params=params or {})
            data = resp.json()
            for item in data.get("results", []):
                yield item
            url = data.get("next")

    def find_docket(
        self,
        *,
        court: str,
        docket_number: Optional[str],
        case_name: str,
        defendant: str,
        max_search_hits: Optional[int] = None,
        filed_after: Optional[str] = None,
        filed_before: Optional[str] = None,
    ) -> Dict[str, Any]:
        candidates: List[Dict[str, Any]] = []

        if docket_number:
            for dn in _docket_variants(docket_number):
                for d in self.paginate(
                    "dockets/",
                    {
                        "docket_number": dn,
                        "court": court,
                    },
                ):
                    candidates.append(d)

        if not candidates:
            query = case_name or f"United States v. {defendant}"
            search_params: Dict[str, Any] = {"type": "r", "q": query, "court": court}
            # Caption searches are fuzzy; a filed-date window (e.g. anchored to
            # the press-release date) keeps decades-old same-surname cases out.
            if filed_after:
                search_params["filed_after"] = filed_after
            if filed_before:
                search_params["filed_before"] = filed_before
            # Each hit costs a throttled GET for its docket; max_search_hits
            # caps a bad/ambiguous caption query from crawling every result.
            for hit in self.paginate("search/", search_params):
                docket_id = hit.get("docket_id")
                if not docket_id:
                    continue
                d = self._request("GET", f"dockets/{docket_id}/").json()
                candidates.append(d)
                if max_search_hits and len(candidates) >= max_search_hits:
                    break

        if not candidates:
            raise LookupError(
                f"No docket found for court={court} docket={docket_number!r} "
                f"case_name={case_name!r}"
            )

        def score(d: Dict[str, Any]) -> int:
            name = (d.get("case_name") or "").lower()
            dn = (d.get("docket_number") or "").lower()
            s = 0
            if defendant.lower() in name:
                s += 3
            if "united states" in name:
                s += 1
            if docket_number:
                if dn == docket_number.lower():
                    s += 8
                core = _docket_core(docket_number)
                if core and core in _docket_core(dn):
                    s += 6
            if case_name and case_name.lower() in name:
                s += 4
            if "-cr-" in dn:
                s += 4
            if "-mj-" in dn:
                s -= 6
            return s

        candidates.sort(key=score, reverse=True)
        best = candidates[0]
        if len(candidates) > 1 and score(candidates[0]) == score(candidates[1]):
            names = [f"{c.get('docket_number')} — {c.get('case_name')}" for c in candidates[:5]]
            print(
                f"Warning: ambiguous docket match; using {best.get('docket_number')} — "
                f"{best.get('case_name')}. Other hits: {'; '.join(names[1:])}",
                file=sys.stderr,
            )
        return best

    def list_recap_documents(self, docket_id: int) -> List[Dict[str, Any]]:
        fields = (
            "id,document_number,description,is_available,filepath_local,"
            "page_count,file_size,docket_entry,entry_number"
        )
        docs = list(
            self.paginate(
                "recap-documents/",
                {
                    "docket_entry__docket": docket_id,
                    "fields": fields,
                },
            )
        )
        docs.sort(
            key=lambda d: (
                _sort_key_num(d.get("entry_number")),
                _sort_key_num(d.get("document_number")),
                d.get("id") or 0,
            )
        )
        return docs

    def list_docket_entry_descriptions(self, docket_id: int) -> Dict[str, str]:
        """Map docket entry number → filing description text."""
        mapping: Dict[str, str] = {}
        for entry in self.paginate(
            "docket-entries/",
            {"docket": docket_id, "fields": "entry_number,description"},
        ):
            num = entry.get("entry_number")
            desc = (entry.get("description") or "").strip()
            if num is not None and desc:
                mapping[str(num)] = desc
        return mapping

    def lookup_recap_document(
        self, docket_id: int, document_number: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch one RECAP row by docket + document/entry number (fast path for --key-docs)."""
        fields = (
            "id,document_number,description,is_available,filepath_local,"
            "page_count,file_size,docket_entry,entry_number"
        )
        for doc in self.paginate(
            "recap-documents/",
            {
                "docket_entry__docket": docket_id,
                "document_number": document_number,
                "fields": fields,
            },
        ):
            return doc
        return None

    def download_pdf(self, filepath_local: str) -> bytes:
        from pull_guard import read_storage_pdf

        self._throttle()
        data = read_storage_pdf(self._session.get, filepath_local)
        self._last_request = time.monotonic()
        return data

    def fetch_missing_pdf(
        self,
        recap_document_id: int,
        *,
        pacer_username: str,
        pacer_password: str,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "recap-fetch/",
            data={
                "request_type": "2",
                "recap_document": str(recap_document_id),
                "pacer_username": pacer_username,
                "pacer_password": pacer_password,
            },
        ).json()

    def get_recap_document(self, recap_document_id: int) -> Dict[str, Any]:
        return self._request("GET", f"recap-documents/{recap_document_id}/").json()

    def wait_for_recap_document(
        self,
        recap_document_id: int,
        *,
        timeout_s: float = 600,
        poll_s: float = 20,
    ) -> Dict[str, Any]:
        """Poll until CourtListener finishes a recap-fetch purchase."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            doc = self.get_recap_document(recap_document_id)
            if doc.get("is_available") and doc.get("filepath_local"):
                return doc
            time.sleep(poll_s)
        raise TimeoutError(
            f"RECAP document {recap_document_id} not available after {timeout_s:.0f}s"
        )


@dataclass
class FetchResult:
    spec: CaseSpec
    docket: Dict[str, Any]
    output_dir: Path
    downloaded: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)


def manifest_path_for(spec: CaseSpec, base: Path) -> Path:
    return base / f"pacer -- {case_id_for(spec)} -- manifest.json"


def is_transcript_filing(description: str) -> bool:
    """True when the docket entry is itself a transcript, not a notice that one exists."""
    text = (description or "").strip()
    if not text or not TRANSCRIPT_FILING_RE.search(text):
        return False
    if re.match(r"(?i)(minute|notice|order|see)\b", text):
        return False
    return bool(
        re.match(
            r"(?i)(?:\d+\s+)?(?:sealed\s+)?(?:official\s+)?transcript\s+of\s+proceedings\b",
            text,
        )
        or re.match(r"(?i).{0,40}transcript\s+of\s+proceedings\b", text)
    )


def hearing_type_of(description: str) -> str:
    """detention, change_of_plea, sentencing, trial, or other. Pretrial is not trial."""
    text = description or ""
    masked = _PRETRIAL_RE.sub(" ", text)
    if _TRIAL_RE.search(masked):
        return "trial"
    low = text.lower()
    if re.search(r"\bsentenc", low):
        return "sentencing"
    if re.search(r"change of plea|plea colloquy|guilty plea|rearraignment|plea hearing|\bre:\s*plea\b", low):
        return "change_of_plea"
    if re.search(r"\bdetention\b|\bbond hearing\b|initial appearance", low):
        return "detention"
    if re.search(r"\bvol(?:ume|\.)\b", low):
        return "trial"
    return "other"


def hearing_subtype_of(description: str, hearing_type: str) -> str:
    """Finer label for hearing_type other. Coarse types keep their own name."""
    if hearing_type != "other":
        return hearing_type
    low = (description or "").lower()
    if re.search(r"suppress", low):
        return "suppression"
    if re.search(r"evidentiary", low):
        return "evidentiary_agent" if re.search(r"\bagent\b", low) else "evidentiary"
    if re.search(r"revocation|supervised release", low):
        return "revocation"
    if re.search(r"arraign", low):
        return "arraignment"
    if re.search(r"status conference", low):
        return "status_conference"
    if re.search(r"\bconference\b", low):
        return "conference"
    if re.search(r"bench trial", low):
        return "bench_trial"
    if re.search(r"oral argument", low):
        return "oral_argument"
    if re.search(r"motion hearing|\bmotion to\b", low):
        return "motion_hearing"
    if re.search(r"opening statement", low):
        return "opening_statement"
    return "unspecified_proceeding"


def restriction_release_date(description: str) -> Optional[date]:
    match = _RESTRICTION_RE.search(description or "")
    if not match:
        return None
    return datetime.strptime(match.group(1), "%m/%d/%Y").date()


def page_count_from_description(description: str) -> Optional[int]:
    text = description or ""
    match = _PAGE_SPAN_RE.search(text)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if end >= start:
            return end - start + 1
    match = re.search(r"Number of Pages[:\s]+(\d+)", text, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d+)\s+pages?\b", text, re.I)
    if match:
        return int(match.group(1))
    return None


def hearing_date_of(description: str) -> str:
    match = _HEARING_DATE_RE.search(description or "")
    return match.group(1) if match else ""


_ENTERED_RE = re.compile(r"\(Entered:\s+(\d{1,2}/\d{1,2}/\d{4})\)", re.I)


def _parse_mdy(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError:
        return None


def classify_transcript_status(
    description: str,
    *,
    is_available: bool = False,
    has_file: bool = False,
    entry_date: Optional[date] = None,
    api_page_count: Optional[int] = None,
    today: Optional[date] = None,
) -> Optional[Dict[str, Any]]:
    """Classify a docket entry. Returns None when it is not a transcript filing.

    Status is FREE_NOW, BUYABLE_LATER, RESTRICTED, SEALED, or UNCLEAR.
    Hearing type trial is recorded; it is not a separate status.
    """
    text = description or ""
    if not is_transcript_filing(text):
        return None
    today = today or date.today()
    if entry_date is None:
        entered = _ENTERED_RE.search(text)
        entry_date = _parse_mdy(entered.group(1)) if entered else None
    release = restriction_release_date(text)
    pages = page_count_from_description(text)
    if pages is None and api_page_count:
        try:
            api_pages = int(api_page_count)
        except (TypeError, ValueError):
            api_pages = 0
        if api_pages > 0:
            pages = api_pages
    sealed = bool(
        re.search(r"\b(sealed|under seal|in camera)\b", text, re.I)
        or re.search(r"3509|closed proceeding|closed to the public", text, re.I)
    )
    access_restricted = bool(
        re.search(r"\brestricted\b", text, re.I)
        and not re.search(r"transcript restriction", text, re.I)
    )
    reason = ""
    if sealed or access_restricted:
        status = "SEALED"
        reason = "sealed" if sealed else "restricted_access"
    elif release is not None and release >= today:
        status = "RESTRICTED"
        reason = "restriction_release_not_reached"
    elif release is None and entry_date is not None and (today - entry_date).days < 90:
        status = "RESTRICTED"
        reason = "inside_90_days"
    elif release is None and not (is_available and has_file):
        aged = entry_date is not None and (today - entry_date).days >= 90
        if aged and not re.search(r"transcript restriction", text, re.I):
            status = "BUYABLE_LATER"
            reason = "no_restriction_language_filed_over_90_days"
        else:
            status = "UNCLEAR"
            reason = "no_restriction_release_date"
    elif is_available and has_file:
        status = "FREE_NOW"
    else:
        status = "BUYABLE_LATER"
    hearing = hearing_type_of(text)
    if status == "BUYABLE_LATER":
        cost = estimate_transcript_pacer_cost(pages)
        cost_text = "unknown" if cost is None else f"{cost:.2f}"
    elif status == "FREE_NOW":
        cost_text = "0.00"
    else:
        cost_text = ""
    return {
        "status": status,
        "reason": reason,
        "hearing_type": hearing,
        "hearing_subtype": hearing_subtype_of(text, hearing),
        "hearing_date": hearing_date_of(text),
        "page_count": pages if pages is not None else "",
        "restriction_release_date": release.isoformat() if release else "",
        "estimated_cost_usd": cost_text,
        "sealed_or_restricted": status if status in {"SEALED", "RESTRICTED"} else "no",
    }


def assess_transcript(description: str, *, today: Optional[date] = None) -> Dict[str, Any]:
    """Eligibility for a transcript docket entry. Does not read the PDF."""
    today = today or date.today()
    text = description or ""
    hearing = hearing_type_of(text)
    release = restriction_release_date(text)
    pages = page_count_from_description(text)
    reason = ""
    if not is_transcript_filing(text):
        reason = "notice_only" if re.match(r"(?i)notice\b", text.strip()) else "not_transcript"
    elif re.search(r"\b(sealed|under seal|in camera)\b", text, re.I):
        reason = "sealed"
    elif re.search(r"3509|closed proceeding|closed to the public", text, re.I):
        reason = "closed_proceeding"
    elif re.search(r"\brestricted\b", text, re.I) and not re.search(
        r"transcript restriction", text, re.I
    ):
        reason = "restricted"
    elif hearing == "trial":
        reason = "trial"
    elif release is None:
        reason = "unclear_status"
    elif release >= today:
        reason = "reporter_only"
    if reason:
        eligible = False
    else:
        eligible = True
        reason = "ok"
    return {
        "eligible": eligible,
        "reason": reason,
        "hearing_type": hearing,
        "hearing_date": hearing_date_of(text),
        "page_count": pages,
        "restriction_release_date": release.isoformat() if release else "",
    }


def classify_key_action(
    description: str,
    doc_type: str,
    *,
    include_transcripts: bool = False,
) -> Optional[Tuple[str, int]]:
    blob = f"{description} {doc_type}"
    # Transcripts are their own document type. Default key-doc pulls skip them
    # even when the entry text also contains "plea" or "sentencing".
    if is_transcript_filing(blob):
        if not include_transcripts:
            return None
        assessment = assess_transcript(blob)
        if not assessment["eligible"]:
            return None
        rank = {"sentencing": 1, "change_of_plea": 2, "detention": 3}.get(
            assessment["hearing_type"], 4
        )
        return "transcript", rank
    if KEY_DOC_SKIP.search(blob):
        return None
    for pat, action, priority in KEY_DOC_RULES:
        if pat.search(blob):
            return action, priority
    return None


def _keep_candidate(action: str, seen_actions: set[str], charging_slot: Tuple[str, ...]) -> bool:
    if action == "transcript":
        return True
    if action in charging_slot:
        return not any(a in seen_actions for a in charging_slot)
    return action not in seen_actions


def select_key_documents(
    docs: List[Dict[str, Any]],
    entry_descriptions: Dict[str, str],
    *,
    max_docs: int = 4,
    include_transcripts: bool = False,
) -> List[Dict[str, Any]]:
    """Pick up to max_docs filings matching indictment / plea / sentencing / etc."""
    candidates: List[Tuple[int, int, Dict[str, Any], str]] = []
    for doc in docs:
        entry_num = doc.get("entry_number") or doc.get("document_number")
        doc_num = doc.get("document_number")
        desc = (doc.get("description") or "").strip()
        if not desc:
            desc = entry_descriptions.get(str(entry_num or doc_num or ""), "")
        doc_type = doc_type_label(desc, entry_num=entry_num, doc_num=doc_num)
        match = classify_key_action(
            desc, doc_type, include_transcripts=include_transcripts
        )
        if not match:
            continue
        action, priority = match
        sort_entry = entry_num if isinstance(entry_num, int) else 0
        candidates.append((priority, -sort_entry, doc, action))

    candidates.sort(key=lambda t: (t[0], t[1]))
    chosen: List[Dict[str, Any]] = []
    seen_actions: set[str] = set()
    # One charging doc: prefer superseding indictment over indictment.
    charging_slot = ("superseding indictment", "indictment")
    for _priority, _neg_entry, doc, action in candidates:
        if not _keep_candidate(action, seen_actions, charging_slot):
            continue
        seen_actions.add(action)
        doc = dict(doc)
        doc["_key_action"] = action
        chosen.append(doc)
        if len(chosen) >= max_docs:
            break
    return chosen


def select_key_entry_targets(
    entry_descriptions: Dict[str, str],
    *,
    max_docs: int = 4,
    include_transcripts: bool = False,
    transcripts_only: bool = False,
) -> List[Tuple[str, str, str]]:
    """Return (entry_number, description, action) without scanning all RECAP pages."""
    candidates: List[Tuple[int, int, str, str, str]] = []
    for en, desc in entry_descriptions.items():
        if transcripts_only and not is_transcript_filing(desc):
            continue
        doc_type = doc_type_label(desc, entry_num=en)
        match = classify_key_action(
            desc, doc_type, include_transcripts=include_transcripts or transcripts_only
        )
        if not match:
            continue
        action, priority = match
        if transcripts_only and action != "transcript":
            continue
        sort_entry = int(en) if str(en).isdigit() else 0
        candidates.append((priority, -sort_entry, str(en), desc, action))

    candidates.sort(key=lambda t: (t[0], t[1]))
    chosen: List[Tuple[str, str, str]] = []
    seen_actions: set[str] = set()
    charging_slot = ("superseding indictment", "indictment")
    for _priority, _neg_entry, en, desc, action in candidates:
        if not _keep_candidate(action, seen_actions, charging_slot):
            continue
        seen_actions.add(action)
        chosen.append((en, desc, action))
        if len(chosen) >= max_docs:
            break
    return chosen


def fetch_case_records(
    client: CourtListenerClient,
    spec: CaseSpec,
    *,
    output_base: Path = BULK_DIR,
    dry_run: bool = False,
    key_docs_only: bool = False,
    transcripts: bool = False,
    download: bool = False,
    max_spend: Optional[float] = None,
    budget: Optional[Any] = None,
    max_docs: int = 4,
    log_cost: bool = False,
    charge_pacer: bool = False,
    pacer_username: Optional[str] = None,
    pacer_password: Optional[str] = None,
    max_search_hits: Optional[int] = None,
    filed_after: Optional[str] = None,
    filed_before: Optional[str] = None,
) -> FetchResult:
    if transcripts and not download:
        dry_run = True
    if transcripts and charge_pacer and max_spend is None:
        raise SystemExit(
            "Refusing PACER charge: --transcripts requires --max-spend. "
            "Rows with an unknown page count also need row_spend_cap_usd."
        )
    court = district_to_court(spec.district, spec.court)
    docket = client.find_docket(
        court=court,
        docket_number=spec.docket,
        case_name=spec.case_name,
        defendant=spec.defendant,
        max_search_hits=max_search_hits,
        filed_after=filed_after,
        filed_before=filed_before,
    )
    docket_id = docket["id"]
    case_id = case_id_for(spec)
    out_dir = output_base

    print(f"\n=== {spec.slug} ===")
    print(f"  Court:     {court}")
    print(f"  Docket:    {docket.get('docket_number')} (CL id {docket_id})")
    print(f"  Caption:   {docket.get('case_name')}")
    print(f"  Case id:   {case_id}")
    print(f"  Output:    {out_dir}/pacer -- {case_id} -- <doc type>.pdf")

    entry_descriptions = client.list_docket_entry_descriptions(docket_id)
    if key_docs_only or transcripts:
        targets: List[Tuple[str, str, str]] = []
        seen_entries: set[str] = set()
        groups: List[List[Tuple[str, str, str]]] = []
        if key_docs_only:
            groups.append(select_key_entry_targets(entry_descriptions, max_docs=max_docs))
        if transcripts:
            groups.append(
                select_key_entry_targets(
                    entry_descriptions,
                    max_docs=max_docs,
                    transcripts_only=True,
                )
            )
        for group in groups:
            for item in group:
                if item[0] in seen_entries:
                    continue
                seen_entries.add(item[0])
                targets.append(item)
        docs: List[Dict[str, Any]] = []
        for en, desc, action in targets:
            doc = client.lookup_recap_document(docket_id, en) or {
                "document_number": en,
                "entry_number": en,
                "description": desc,
                "is_available": False,
                "filepath_local": None,
            }
            doc = dict(doc)
            doc["_key_action"] = action
            if not (doc.get("description") or "").strip():
                doc["description"] = desc
            docs.append(doc)
        label = "Transcripts" if transcripts and not key_docs_only else "Key docs"
        if transcripts and key_docs_only:
            label = "Key docs + transcripts"
        print(f"  {label}: {len(docs)} selected (max {max_docs} each)")
    else:
        docs = client.list_recap_documents(docket_id)
        print(f"  RECAP docs: {len(docs)} total")

    result = FetchResult(spec=spec, docket=docket, output_dir=out_dir)
    used_names: Dict[str, int] = {}
    cost_rows: List[Tuple[str, str, str, float]] = []
    docket_number = str(docket.get("docket_number") or spec.docket or "")

    from pull_guard import PullBudget, append_ledger, local_pdf_ok

    if budget is None:
        budget = PullBudget(max_spend, None)
    ledger_path = output_base / "pull_ledger.csv"

    for doc in docs:
        doc_id = doc.get("id")
        entry_num = doc.get("entry_number") or doc.get("document_number")
        doc_num = doc.get("document_number")
        desc = (doc.get("description") or "").strip()
        if not desc:
            lookup = str(entry_num or doc_num or "")
            desc = entry_descriptions.get(lookup, "")
        doc_type = doc_type_label(desc, entry_num=entry_num, doc_num=doc_num)
        key_action = doc.get("_key_action") or classify_key_action(desc, doc_type)
        if isinstance(key_action, tuple):
            key_action = key_action[0]
        cost_action = key_action or doc_type.lower()
        is_transcript = cost_action == "transcript" or is_transcript_filing(desc)
        if is_transcript:
            pages = doc.get("page_count") or page_count_from_description(desc)
            transcript_est = estimate_transcript_pacer_cost(pages)
        pdf_path = resolve_pdf_path(
            out_dir,
            case_id,
            doc_type,
            entry_num=entry_num,
            doc_num=doc_num,
            used_names=used_names,
        )

        meta = {
            "id": doc_id,
            "entry_number": entry_num,
            "document_number": doc_num,
            "description": desc,
            "doc_type": doc_type,
            "filename": pdf_path.name,
            "is_available": doc.get("is_available"),
            "filepath_local": doc.get("filepath_local"),
        }

        if dry_run:
            if doc.get("is_available") and doc.get("filepath_local"):
                meta["local_path"] = str(pdf_path.relative_to(REPO_ROOT))
                meta["cost"] = 0.00
                print(f"  FREE:       {pdf_path.name}")
                result.downloaded.append(meta)
            else:
                if is_transcript:
                    est = transcript_est
                else:
                    est = estimate_pacer_pdf_cost(doc.get("page_count")) if charge_pacer else None
                meta["needs_pacer"] = True
                if est is not None:
                    meta["estimated_pacer_cost"] = est
                if is_transcript and est is None:
                    tag = "NEEDS PACER (transcript page count unknown; no $3 cap)"
                elif est:
                    tag = f"NEEDS PACER (~${est:.2f})"
                else:
                    tag = "NEEDS PACER"
                print(f"  {tag}: {pdf_path.name}")
                result.skipped.append(meta)
            continue

        if not doc.get("is_available") or not doc.get("filepath_local"):
            if local_pdf_ok(pdf_path):
                meta["local_path"] = str(pdf_path.relative_to(REPO_ROOT))
                result.downloaded.append(meta)
                continue
            if doc_id:
                try:
                    fresh = client.get_recap_document(int(doc_id))
                except Exception:
                    fresh = None
                if fresh and fresh.get("is_available") and fresh.get("filepath_local"):
                    doc = fresh
            if doc.get("is_available") and doc.get("filepath_local"):
                pass
            elif charge_pacer and pacer_username and pacer_password and doc_id:
                if budget.stop:
                    print("  stop: run cap reached", file=sys.stderr)
                    break
                if is_transcript and transcript_est is None:
                    print(
                        f"  refuse doc {doc_id}: transcript page count unknown "
                        "(no $3 substitute)",
                        file=sys.stderr,
                    )
                    meta["error"] = "page_count_unknown"
                    result.skipped.append(meta)
                    continue
                est = transcript_est if is_transcript else estimate_pacer_pdf_cost(doc.get("page_count"))
                if not budget.can_buy(est):
                    print(
                        f"  stop doc {doc_id}: {budget.reason} (spent ${budget.spent:.2f})",
                        file=sys.stderr,
                    )
                    meta["error"] = budget.reason or "max_spend"
                    result.skipped.append(meta)
                    break
                est_label = f"~${est:.2f}" if est is not None else "page count unknown"
                posted = False
                try:
                    print(f"  PACER purchase doc {doc_id} ({cost_action}) est {est_label} …")
                    client.fetch_missing_pdf(
                        doc_id,
                        pacer_username=pacer_username,
                        pacer_password=pacer_password,
                    )
                    posted = True
                    print("  waiting for RECAP …")
                    doc = client.wait_for_recap_document(doc_id)
                    meta["is_available"] = True
                    meta["filepath_local"] = doc.get("filepath_local")
                    meta["page_count"] = doc.get("page_count")
                    if is_transcript:
                        actual_cost = estimate_transcript_pacer_cost(
                            doc.get("page_count") or page_count_from_description(desc)
                        )
                    else:
                        actual_cost = estimate_pacer_pdf_cost(doc.get("page_count"))
                    if actual_cost is None:
                        actual_cost = est or 0.0
                    meta["pacer_cost"] = actual_cost
                    budget.commit(float(actual_cost), record=False)
                    append_ledger(
                        ledger_path,
                        {
                            "docket_number": docket_number,
                            "docket_id": docket.get("id") or "",
                            "recap_document_id": doc_id,
                            "pages": doc.get("page_count") or "",
                            "estimate_usd": f"{float(est or 0):.2f}",
                            "actual_usd": f"{float(actual_cost):.2f}",
                            "outcome": "posted",
                            "running_spent_usd": f"{budget.spent:.2f}",
                            "running_records": budget.records,
                        },
                    )
                    if budget.max_spend is not None and budget.spent > float(budget.max_spend) + 1e-9:
                        budget.stop = True
                        budget.reason = "max_spend"
                    if pdf_path.exists() and local_pdf_ok(pdf_path):
                        print(f"  skip existing {pdf_path.name}")
                        meta["local_path"] = str(pdf_path.relative_to(REPO_ROOT))
                        result.downloaded.append(meta)
                        continue
                    print(f"  download {pdf_path.name}")
                    out_dir.mkdir(parents=True, exist_ok=True)
                    content = client.download_pdf(doc["filepath_local"])
                    pdf_path.write_bytes(content)
                    meta["local_path"] = str(pdf_path.relative_to(REPO_ROOT))
                    meta["bytes"] = len(content)
                    result.downloaded.append(meta)
                    continue
                except Exception as exc:  # noqa: BLE001
                    if posted:
                        budget.commit(float(est or 0), record=False)
                        append_ledger(
                            ledger_path,
                            {
                                "docket_number": docket_number,
                                "docket_id": docket.get("id") or "",
                                "recap_document_id": doc_id,
                                "pages": "",
                                "estimate_usd": f"{float(est or 0):.2f}",
                                "actual_usd": f"{float(est or 0):.2f}",
                                "outcome": "failed",
                                "running_spent_usd": f"{budget.spent:.2f}",
                                "running_records": budget.records,
                            },
                        )
                        budget.stop = True
                        budget.reason = "post_failed"
                    meta["error"] = str(exc)
                    result.errors.append(meta)
                    print(f"  fetch failed doc {doc_id}: {exc}", file=sys.stderr)
                    if budget.stop:
                        break
                    continue
            else:
                meta["needs_pacer"] = True
            if doc.get("is_available") and doc.get("filepath_local"):
                pass
            else:
                result.skipped.append(meta)
                continue

        try:
            if local_pdf_ok(pdf_path):
                print(f"  skip existing {pdf_path.name}")
                meta["local_path"] = str(pdf_path.relative_to(REPO_ROOT))
                result.downloaded.append(meta)
                continue
            print(f"  download {pdf_path.name}")
            out_dir.mkdir(parents=True, exist_ok=True)
            content = client.download_pdf(doc["filepath_local"])
            pdf_path.write_bytes(content)
            meta["local_path"] = str(pdf_path.relative_to(REPO_ROOT))
            meta["bytes"] = len(content)
            meta["cost"] = 0.00
            result.downloaded.append(meta)
            if log_cost and not charge_pacer:
                cost_rows.append((case_id, docket_number, cost_action, 0.00))
        except Exception as exc:  # noqa: BLE001
            meta["error"] = str(exc)
            result.errors.append(meta)
            print(f"  error doc {doc_id}: {exc}", file=sys.stderr)

    if dry_run:
        free = sum(1 for m in result.downloaded)
        need = sum(1 for m in result.skipped)
        est = sum(m.get("estimated_pacer_cost", 0) for m in result.skipped)
        print(f"  dry-run: {free} free in RECAP, {need} need PACER", end="")
        if charge_pacer and est:
            print(f" (est ~${est:.2f} if --charge-pacer)", end="")
        print()
        return result

    if log_cost and cost_rows:
        append_cost_rows(cost_rows)
        print(f"  cost log:  {len(cost_rows)} row(s) → pacer_cost.csv")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spec": {
            "slug": spec.slug,
            "defendant": spec.defendant,
            "case_name": spec.case_name,
            "district": spec.district,
            "court": court,
            "docket": spec.docket,
            "corpus_id": spec.corpus_id,
            "notes": spec.notes,
        },
        "docket": {
            "id": docket_id,
            "docket_number": docket.get("docket_number"),
            "case_name": docket.get("case_name"),
            "date_filed": docket.get("date_filed"),
            "courtlistener_url": urljoin(
                "https://www.courtlistener.com", docket.get("absolute_url", "")
            ),
        },
        "summary": {
            "total_recap_documents": len(docs),
            "downloaded": len(result.downloaded),
            "skipped_unavailable": len(result.skipped),
            "errors": len(result.errors),
        },
        "downloaded": result.downloaded,
        "skipped": result.skipped,
        "errors": result.errors,
    }
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_path_for(spec, out_dir)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"  manifest:  {manifest_path.name}")
    print(
        f"  done: {len(result.downloaded)} downloaded, "
        f"{len(result.skipped)} unavailable, {len(result.errors)} errors"
    )
    return result


def _spec_from_args(args: argparse.Namespace) -> CaseSpec:
    if not args.defendant or not args.district:
        raise SystemExit("--defendant and --district are required without --preset/--batch")
    court = district_to_court(args.district, args.court)
    slug = args.slug or _slugify(args.defendant)
    return CaseSpec(
        slug=slug,
        defendant=args.defendant,
        case_name=args.case_name or f"United States v. {args.defendant}",
        district=args.district,
        court=court,
        docket=args.docket,
        corpus_id=args.corpus_id,
    )


def _resolve_specs(args: argparse.Namespace) -> List[CaseSpec]:
    if args.batch == "recommended":
        return list(RECOMMENDED_CASES.values())
    if args.batch == "bridge4":
        return [RECOMMENDED_CASES[s] for s in BRIDGE4_PRESETS]
    if args.preset:
        if args.preset not in RECOMMENDED_CASES:
            known = ", ".join(sorted(RECOMMENDED_CASES))
            raise SystemExit(f"Unknown preset {args.preset!r}. Known: {known}")
        return [RECOMMENDED_CASES[args.preset]]
    return [_spec_from_args(args)]


def main() -> int:
    _load_dotenv()

    parser = argparse.ArgumentParser(
        description="Download RECAP/PDF court records from CourtListener for a federal case.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--preset", choices=sorted(RECOMMENDED_CASES), help="Built-in case spec")
    parser.add_argument(
        "--batch",
        choices=("recommended", "bridge4"),
        help="recommended=all 5 targets; bridge4=wayerski+herrera+katsampes+ramirez",
    )
    parser.add_argument("--defendant", help="Lead defendant surname (for search/disambiguation)")
    parser.add_argument("--case-name", help='Docket caption, e.g. "United States v. Berger"')
    parser.add_argument("--district", help='District label, e.g. "N.D. Florida"')
    parser.add_argument("--court", help="CourtListener court id (overrides --district), e.g. flnd")
    parser.add_argument("--docket", help="PACER docket number, e.g. 3:08-cr-00022")
    parser.add_argument("--corpus-id", help="CaseLinker corpus id → output subfolder name")
    parser.add_argument("--slug", help="Short name for output folder when no --corpus-id")
    parser.add_argument(
        "--output-base",
        type=Path,
        default=BULK_DIR,
        help=f"Base output directory (default: {BULK_DIR})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Resolve docket and list docs only")
    parser.add_argument(
        "--key-docs",
        action="store_true",
        help="Only indictment/plea/sentencing/complaint-class filings (max --max-docs)",
    )
    parser.add_argument("--max-docs", type=int, default=4, help="Cap per case with --key-docs or --transcripts")
    parser.add_argument(
        "--transcripts",
        action="store_true",
        help=(
            "Select TRANSCRIPT of Proceedings filings. Default --key-docs skips them. "
            "Transcript mode is a dry run unless --download. "
            "Buying also requires --charge-pacer and --max-spend. "
            "$0.10/page, no $3 cap."
        ),
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="With --transcripts, download approved free RECAP PDFs. Still no PACER unless --charge-pacer.",
    )
    parser.add_argument(
        "--max-spend",
        type=float,
        default=None,
        help="Total PACER dollar cap. Required with --transcripts --charge-pacer.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Approved transcript_manifest.csv. Only rows with approved=yes are considered.",
    )
    parser.add_argument(
        "--log-cost",
        action="store_true",
        help="Append rows to BULK_FOLDER/pacer_cost.csv (free=0.00)",
    )
    parser.add_argument(
        "--charge-pacer",
        action="store_true",
        help="BUY missing PDFs via CourtListener recap-fetch (charges your PACER account)",
    )
    parser.add_argument("--pacer-username", default=os.environ.get("PACER_USERNAME"))
    parser.add_argument("--pacer-password", default=os.environ.get("PACER_PASSWORD"))
    parser.add_argument(
        "--token",
        default=os.environ.get("COURTLISTENER_API_TOKEN", ""),
        help="CourtListener API token (default: COURTLISTENER_API_TOKEN env)",
    )
    args = parser.parse_args()

    if args.transcripts and args.manifest:
        from transcripts import fetch_approved

        return fetch_approved(args)
    if args.charge_pacer and args.max_spend is None:
        parser.error("--charge-pacer requires --max-spend")
    if not args.preset and not args.batch and not args.defendant:
        parser.error("Provide --preset, --batch recommended, or --defendant with --district")

    try:
        client = CourtListenerClient(args.token)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    specs = _resolve_specs(args)
    results: List[FetchResult] = []
    from pull_guard import PullBudget

    budget = PullBudget(args.max_spend, None)
    for spec in specs:
        try:
            results.append(
                fetch_case_records(
                    client,
                    spec,
                    output_base=args.output_base,
                    dry_run=args.dry_run,
                    key_docs_only=args.key_docs,
                    transcripts=args.transcripts,
                    download=args.download,
                    max_spend=args.max_spend,
                    budget=budget,
                    max_docs=args.max_docs,
                    log_cost=args.log_cost,
                    charge_pacer=args.charge_pacer,
                    pacer_username=args.pacer_username,
                    pacer_password=args.pacer_password,
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED {spec.slug}: {exc}", file=sys.stderr)
            if len(specs) == 1:
                return 1

    total_dl = sum(len(r.downloaded) for r in results)
    total_skip = sum(len(r.skipped) for r in results)
    print(f"\nAll cases: {len(results)} processed, {total_dl} PDFs, {total_skip} unavailable")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
