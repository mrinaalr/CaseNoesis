#!/usr/bin/env python3
"""Transcript sweep and later approved fetch. The sweep never spends money.

sweep   Free CourtListener metadata for every held docket. No PDFs, no PACER.
fetch   Reads transcript_manifest.csv. Dry run unless --download.
        Buying also requires --charge-pacer and --max-spend.
        Unknown page counts are refused unless that row has row_spend_cap_usd.
        Sealed, still-restricted, and court-reporter orders are refused.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from cases2records import classify_transcript_status, hearing_type_of  # noqa: E402
from pacer_cost import estimate_transcript_pacer_cost  # noqa: E402

COLLECTED = REPO / "data" / "collected"
OUT_DIR = COLLECTED / "PACER" / "transcripts"
MANIFEST = OUT_DIR / "transcript_manifest.csv"
STALE = OUT_DIR / "stale_dockets.csv"
CACHE = OUT_DIR / "_cache"
TODAY = date.today()
DOCKET_REFRESH_CAP = 3.00

COURT_LABELS = (
    ("southern district of florida", "flsd"),
    ("s.d. fla", "flsd"),
    ("eastern district of wisconsin", "wied"),
    ("e.d. wis", "wied"),
    ("middle district of florida", "flmd"),
    ("m.d. fla", "flmd"),
    ("western district of kentucky", "kywd"),
    ("w.d. ky", "kywd"),
    ("southern district of california", "casd"),
    ("s.d. cal", "casd"),
    ("eastern district of california", "caed"),
    ("e.d. cal", "caed"),
    ("northern district of california", "cand"),
    ("western district of texas", "txwd"),
    ("w.d. texas", "txwd"),
    ("eastern district of virginia", "vaed"),
    ("e.d. va", "vaed"),
    ("eastern district of kentucky", "kyed"),
    ("eastern district of louisiana", "laed"),
    ("eastern district of new york", "nyed"),
    ("middle district of alabama", "almd"),
    ("m.d. ala", "almd"),
    ("southern district of west virginia", "wvsd"),
    ("district of alaska", "akd"),
    ("d. alaska", "akd"),
    ("district of massachusetts", "mad"),
    ("d. mass", "mad"),
    ("district of maryland", "mdd"),
    ("d. md", "mdd"),
)

MANIFEST_FIELDS = [
    "status",
    "domain",
    "case_caption",
    "court",
    "docket_number",
    "docket_id",
    "docket_entry_number",
    "recap_document_id",
    "hearing_type",
    "hearing_subtype",
    "hearing_date",
    "page_count",
    "restriction_release_date",
    "sealed_or_restricted",
    "is_available",
    "estimated_cost_usd",
    "courtlistener_updated",
    "related_docket",
    "source",
    "unclear_reason",
    "pilot_suggest",
    "approved",
    "row_spend_cap_usd",
    "case_kind",
    "duplicate_of",
    "prior_status",
    "review_flag",
]
STALE_FIELDS = [
    "domain",
    "case_caption",
    "court",
    "docket_number",
    "docket_id",
    "courtlistener_updated",
    "date_terminated",
    "stale_reason",
    "refresh_cost_usd_max",
    "source",
]


def _token() -> str:
    for env_path in (REPO / ".env", REPO.parent / "CaseLinker" / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("COURTLISTENER_API_TOKEN=") or line.startswith("COURTLISTENER_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip("'\"")
                if tok:
                    return tok
    raise SystemExit("COURTLISTENER_API_TOKEN not found")


def _docket_id_from_url(url: str) -> Optional[int]:
    match = re.search(r"/docket/(\d+)/", url or "")
    return int(match.group(1)) if match else None


def _remember(index: Dict[int, Dict[str, Any]], docket_id: Any, row: Dict[str, Any]) -> None:
    if docket_id in (None, ""):
        return
    try:
        did = int(docket_id)
    except (TypeError, ValueError):
        return
    current = index.get(did)
    if current is None:
        index[did] = row
        return
    for key in ("docket_number", "court", "case_caption", "court_id"):
        if not current.get(key) and row.get(key):
            current[key] = row[key]


def _domain_for_folder(name: str) -> str:
    if name in {"forced_labor", "trafficking"}:
        return "trafficking"
    if name == "csea":
        return "csea"
    if name == "fraud":
        return "fraud"
    if name == "cyber":
        return "cyber"
    return name


def load_inventory() -> Dict[int, Dict[str, Any]]:
    index: Dict[int, Dict[str, Any]] = {}
    manifests = {
        "csea": COLLECTED / "recap" / "csea" / "court_manifest.json",
        "fraud": COLLECTED / "recap" / "fraud" / "court_manifest.json",
        "trafficking": COLLECTED / "recap" / "trafficking" / "court_manifest.json",
        "cyber": COLLECTED / "recap" / "cyber" / "court_manifest.json",
    }
    for domain, path in manifests.items():
        if not path.is_file():
            continue
        for rec in json.loads(path.read_text(encoding="utf-8")):
            _remember(
                index,
                rec.get("docket_id"),
                {
                    "domain": domain,
                    "case_caption": rec.get("case_name") or "",
                    "court": rec.get("court") or "",
                    "docket_number": rec.get("docket_number") or "",
                    "source": str(path.relative_to(REPO)),
                    "related_docket": "no",
                },
            )
    bulk = COLLECTED / "recap" / "bulk" / "court_manifest.json"
    if bulk.is_file():
        for rec in json.loads(bulk.read_text(encoding="utf-8")):
            _remember(
                index,
                rec.get("docket_id"),
                {
                    "domain": "trafficking",
                    "case_caption": rec.get("case_name") or "",
                    "court": rec.get("court") or "",
                    "docket_number": rec.get("docket_number") or "",
                    "source": str(bulk.relative_to(REPO)),
                    "related_docket": "no",
                },
            )
    links = COLLECTED / "recap" / "bulk" / "manifests" / "recap_links.jsonl"
    if links.is_file():
        for line in links.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            domain = _domain_for_folder(rec.get("press_domain") or "trafficking")
            if domain not in {"trafficking", "csea", "fraud", "cyber"}:
                domain = "trafficking"
            _remember(
                index,
                _docket_id_from_url(rec.get("absolute_url") or ""),
                {
                    "domain": domain,
                    "case_caption": rec.get("case_name") or "",
                    "court": rec.get("court") or "",
                    "docket_number": rec.get("docket_number") or "",
                    "source": str(links.relative_to(REPO)),
                    "related_docket": "no",
                },
            )
    for path, domain in (
        (COLLECTED / "recap" / "fraud" / "fraud_study.jsonl", "fraud"),
        (COLLECTED / "recap" / "fraud" / "from_press.jsonl", "fraud"),
        (COLLECTED / "public" / "fraud_court_lookup.jsonl", "fraud"),
    ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            did = rec.get("docket_id") or _docket_id_from_url(rec.get("absolute_url") or "")
            _remember(
                index,
                did,
                {
                    "domain": domain,
                    "case_caption": rec.get("case_name") or "",
                    "court": rec.get("court") or "",
                    "docket_number": rec.get("docket_number") or "",
                    "source": str(path.relative_to(REPO)),
                    "related_docket": "no",
                },
            )
    return index


def _court_id_from_text(text: str) -> str:
    low = re.sub(r"\s+", " ", text.lower())
    for label, court_id in COURT_LABELS:
        if label in low:
            return court_id
    return ""


def load_pacer_targets() -> List[Dict[str, Any]]:
    """Docket numbers we already paid for, with a court id when the graph states one."""
    targets: List[Dict[str, Any]] = []
    cost = COLLECTED / "PACER" / "BULK_FOLDER" / "pacer_cost.csv"
    if not cost.is_file():
        return targets
    section = ""
    seen = set()
    for line in cost.read_text(encoding="utf-8").splitlines():
        low = line.lower()
        if low.startswith("icac"):
            section = "csea"
            continue
        if "outside" in low and "total" not in low:
            section = "other"
            continue
        match = re.search(r"(\d+:\d{2}-(?:cr|mj)-\d+)", line, re.I)
        if not match:
            continue
        case_id = line.split(",")[0].strip().strip("[]")
        number = match.group(1)
        domain = "csea" if section == "csea" else "other"
        if "elder fraud" in low:
            domain = "fraud"
        key = (number, case_id)
        if key in seen:
            continue
        seen.add(key)
        court_id = ""
        folder = COLLECTED / "PACER" / "BULK_FOLDER" / case_id
        if not folder.is_dir():
            folder = COLLECTED / "PACER" / "EXTENSION"
        blob = ""
        for path in list(folder.glob(f"{case_id}.jsonld")) + list(folder.glob("*.jsonld"))[:3]:
            blob += "\n" + path.read_text(encoding="utf-8", errors="ignore")[:5000]
        court_id = _court_id_from_text(blob)
        targets.append(
            {
                "domain": domain,
                "docket_number": number,
                "court_id": court_id,
                "case_id": case_id,
                "source": f"PACER/BULK_FOLDER/pacer_cost.csv {case_id}",
            }
        )
    return targets


class Client:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Token {token}"
        self.session.headers["User-Agent"] = "CaseNoesis transcript-sweep"
        self.calls = 0

    def get(self, url: str, params: Any = None) -> Dict[str, Any]:
        for attempt in range(8):
            time.sleep(6.5)
            self.calls += 1
            resp = self.session.get(url, params=params, timeout=120)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp.json()
            wait = int(resp.headers.get("Retry-After", "60")) + 2
            print(f"  rate limit, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
        raise SystemExit("CourtListener rate limit persisted. Re-run sweep to resume from cache.")


def _chunks(items: List[int], size: int) -> Iterable[List[int]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _search_meta_row(hit: Dict[str, Any]) -> Dict[str, Any]:
    """Docket search has dateTerminated and an index timestamp, not the REST date_modified."""
    indexed = ((hit.get("meta") or {}).get("timestamp")) or ""
    return {
        "id": int(hit["docket_id"]),
        "date_modified": indexed,
        "date_terminated": hit.get("dateTerminated") or "",
        "date_last_filing": "",
        "docket_number": hit.get("docketNumber") or "",
        "case_name": hit.get("caseName") or "",
        "court": hit.get("court_id") or hit.get("court") or "",
        "updated_source": "search_index",
    }


def fetch_docket_meta(client: Client, docket_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    found: Dict[int, Dict[str, Any]] = {}
    cache_path = CACHE / "docket_meta.jsonl"
    if cache_path.is_file():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                found[int(row["id"])] = row
    missing = [did for did in docket_ids if did not in found]
    print(f"Docket metadata: {len(found)} cached, {len(missing)} to fetch", file=sys.stderr)
    with cache_path.open("a", encoding="utf-8") as handle:
        for batch in _chunks(missing, 20):
            clause = " OR ".join(f"docket_id:{did}" for did in batch)
            payload = client.get(
                "https://www.courtlistener.com/api/rest/v4/search/",
                {"type": "d", "q": clause},
            )
            for hit in payload.get("results") or []:
                if not hit.get("docket_id"):
                    continue
                row = _search_meta_row(hit)
                found[int(row["id"])] = row
                handle.write(json.dumps(row) + "\n")
            handle.flush()
            print(f"  metadata {len(found)}/{len(docket_ids)}", file=sys.stderr)
    return found


def _search_pages(client: Client, params: Dict[str, Any], max_pages: int = 40) -> tuple:
    url = "https://www.courtlistener.com/api/rest/v4/search/"
    query: Optional[Dict[str, Any]] = params
    page_hits: List[Dict[str, Any]] = []
    for _page in range(max_pages):
        payload = client.get(url, query)
        page_hits.extend(payload.get("results") or [])
        url = payload.get("next") or ""
        query = None
        if not url:
            return page_hits, True
    return page_hits, False


def search_transcripts(client: Client, docket_ids: List[int], cache_name: str) -> List[Dict[str, Any]]:
    cache_path = CACHE / cache_name
    hits: List[Dict[str, Any]] = []
    markers: Dict[str, Dict[str, Any]] = {}
    if cache_path.is_file():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("_batch"):
                markers[row["_batch"]] = row
            elif row.get("id"):
                hits.append(row)
    # A batch of 160 is the old 8-page cap, so those ranges are fetched again.
    done_batches = {
        key
        for key, row in markers.items()
        if row.get("complete") or int(row.get("n") or 0) < 160
    }
    print(
        f"Transcript search {cache_name}: {len(hits)} cached hits, {len(done_batches)} batches done",
        file=sys.stderr,
    )

    def run_batch(batch: List[int], handle: Any) -> None:
        key = f"{batch[0]}:{batch[-1]}:{len(batch)}"
        if key in done_batches:
            return
        clause = " OR ".join(f"docket_id:{did}" for did in batch)
        page_hits, complete = _search_pages(
            client,
            {"type": "rd", "q": f'({clause}) "TRANSCRIPT of Proceedings"'},
        )
        if not complete and len(batch) > 1:
            print(f"  splitting transcript batch of {len(batch)}", file=sys.stderr)
            mid = len(batch) // 2
            run_batch(batch[:mid], handle)
            run_batch(batch[mid:], handle)
            handle.write(json.dumps({"_batch": key, "n": 0, "complete": True, "split": True}) + "\n")
            handle.flush()
            done_batches.add(key)
            return
        for hit in page_hits:
            handle.write(json.dumps(hit) + "\n")
            hits.append(hit)
        handle.write(json.dumps({"_batch": key, "n": len(page_hits), "complete": complete}) + "\n")
        handle.flush()
        done_batches.add(key)
        print(
            f"  transcripts {key} hits+{len(page_hits)} complete={complete} total {len(hits)}",
            file=sys.stderr,
        )

    with cache_path.open("a", encoding="utf-8") as handle:
        for batch in _chunks(docket_ids, 20):
            run_batch(batch, handle)
    return hits


def _court_slug(court_value: str) -> str:
    match = re.search(r"/courts/([a-z0-9]+)/?", court_value or "")
    return match.group(1) if match else ""


def _defendant(case_name: str) -> str:
    match = re.search(r"\bv\.?\s+(.+)$", case_name or "", re.I)
    if not match:
        return ""
    name = re.sub(r"\s*\(.*$", "", match.group(1)).strip(" ,.")
    if len(name) < 3 or name.lower() in {"united states", "usa"}:
        return ""
    return name


def _date_only(value: str) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def related_criminal_ids(
    client: Client,
    inventory: Dict[int, Dict[str, Any]],
    meta: Dict[int, Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    """Companion -mj-/-cr- dockets for the same defendant and court. Metadata only."""
    groups: Dict[tuple, Dict[str, Any]] = {}
    for did, info in inventory.items():
        row = meta.get(did) or {}
        number = (row.get("docket_number") or info.get("docket_number") or "").lower()
        kind = "mj" if "-mj-" in number else "cr" if "-cr-" in number else ""
        if not kind:
            continue
        court = _court_slug(str(row.get("court") or "")) or info.get("court_id") or ""
        name = _defendant(row.get("case_name") or info.get("case_caption") or "")
        if not court or not name:
            continue
        bucket = groups.setdefault((court, name.lower()), {"court": court, "name": name, "kinds": set(), "domain": info["domain"], "source": info["source"]})
        bucket["kinds"].add(kind)
    need = [bucket for bucket in groups.values() if bucket["kinds"] != {"cr", "mj"}]
    print(f"Related criminal lookup: {len(need)} defendant/court pairs missing one side", file=sys.stderr)
    added: Dict[int, Dict[str, Any]] = {}
    # A few names per query so a common surname cannot flood one page.
    for start in range(0, len(need), 6):
        batch = need[start : start + 6]
        by_court: Dict[str, List[Dict[str, Any]]] = {}
        for bucket in batch:
            by_court.setdefault(bucket["court"], []).append(bucket)
        for court, buckets in by_court.items():
            clause = " OR ".join(f'caseName:"United States v. {bucket["name"]}"' for bucket in buckets)
            page_hits, _complete = _search_pages(
                client,
                {"type": "d", "q": f"court_id:{court} AND ({clause})"},
                max_pages=5,
            )
            wanted = {bucket["name"].lower(): bucket for bucket in buckets}
            for hit in page_hits:
                number = (hit.get("docketNumber") or "").lower()
                if "-cr-" not in number and "-mj-" not in number:
                    continue
                caption = hit.get("caseName") or ""
                defendant = _defendant(caption).lower()
                bucket = wanted.get(defendant)
                if bucket is None:
                    continue
                did = int(hit["docket_id"])
                if did in inventory or did in added:
                    continue
                added[did] = {
                    "domain": bucket["domain"],
                    "case_caption": caption,
                    "court": hit.get("court") or court,
                    "court_id": court,
                    "docket_number": hit.get("docketNumber") or "",
                    "source": bucket["source"] + " related",
                    "related_docket": "yes",
                }
    print(f"  companion dockets not already held: {len(added)}", file=sys.stderr)
    return added


def _entry_number(record: Dict[str, Any]) -> Optional[str]:
    """CourtListener entry_number, else docket_entry_number. None when neither is a number."""
    for key in ("entry_number", "docket_entry_number"):
        value = record.get(key)
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text.isdigit():
            return str(int(text))
    return None


def build_rows(
    hits: List[Dict[str, Any]],
    inventory: Dict[int, Dict[str, Any]],
    meta: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for hit in hits:
        try:
            did = int(hit.get("docket_id"))
        except (TypeError, ValueError):
            continue
        info = inventory.get(did)
        if info is None:
            continue
        description = hit.get("description") or ""
        available = bool(hit.get("is_available") and hit.get("filepath_local"))
        classified = classify_transcript_status(
            description,
            is_available=bool(hit.get("is_available")),
            has_file=bool(hit.get("filepath_local")),
            api_page_count=hit.get("page_count"),
            today=TODAY,
        )
        if classified is None:
            continue
        doc_id = hit.get("id") or ""
        entry = _entry_number(hit)
        key = (did, doc_id, entry)
        if key in seen:
            continue
        seen.add(key)
        dmeta = meta.get(did) or {}
        rows.append(
            {
                "status": classified["status"],
                "domain": info.get("domain") or "",
                "case_caption": dmeta.get("case_name") or info.get("case_caption") or "",
                "court": info.get("court") or "",
                "docket_number": dmeta.get("docket_number") or info.get("docket_number") or "",
                "docket_id": did,
                "docket_entry_number": entry or "",
                "recap_document_id": doc_id,
                "hearing_type": classified["hearing_type"],
                "hearing_subtype": classified.get("hearing_subtype") or "",
                "hearing_date": classified["hearing_date"],
                "page_count": classified["page_count"],
                "restriction_release_date": classified["restriction_release_date"],
                "sealed_or_restricted": classified["sealed_or_restricted"],
                "is_available": available,
                "estimated_cost_usd": classified["estimated_cost_usd"],
                "courtlistener_updated": (dmeta.get("date_modified") or "")[:10],
                "related_docket": info.get("related_docket") or "no",
                "source": info.get("source") or "",
                "unclear_reason": classified["reason"],
                "pilot_suggest": "",
                "approved": "",
                "row_spend_cap_usd": "",
            }
        )
    return rows


def covered_docket_ids(inventory_ids: List[int], sections: List[tuple]) -> set:
    """Held docket ids whose transcript search reached the last page."""
    latest: Dict[str, Dict[str, Any]] = {}
    for marker, _section in sections:
        key = str(marker.get("_batch") or "")
        if key.startswith("repost:"):
            continue
        latest[key] = marker
    covered = set()
    for marker in latest.values():
        if not (marker.get("complete") or int(marker.get("n") or 0) < 160):
            continue
        try:
            start, end, _size = _batch_bounds(marker)
        except ValueError:
            continue
        for did in inventory_ids:
            if start <= did <= end:
                covered.add(did)
    return covered


def merge_saved_columns(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep approvals and collected status already stored in the manifest."""
    if not MANIFEST.is_file():
        return rows
    saved = {}
    with MANIFEST.open(encoding="utf-8", newline="") as handle:
        for prev in csv.DictReader(handle):
            key = (
                str(prev.get("docket_id") or ""),
                str(prev.get("recap_document_id") or ""),
                str(prev.get("docket_entry_number") or ""),
            )
            saved[key] = prev
    for row in rows:
        key = (
            str(row.get("docket_id") or ""),
            str(row.get("recap_document_id") or ""),
            str(row.get("docket_entry_number") or ""),
        )
        prev = saved.get(key)
        if not prev:
            continue
        for field in ("approved", "row_spend_cap_usd", "case_kind", "duplicate_of", "prior_status", "review_flag"):
            if (prev.get(field) or "").strip():
                row[field] = prev[field]
        prev_status = (prev.get("status") or "").strip()
        if prev_status == "COLLECTED" or prev_status == "NON_CRIMINAL" or prev_status.startswith("DUPLICATE_OF"):
            row["status"] = prev_status
        if (prev.get("domain") or "").strip() == "other_federal":
            row["domain"] = "other_federal"
    return rows


_CRIMINAL_NUM_RE = re.compile(r"\d+:\d{2}-(?:cr|mj)-\d+", re.I)


def _meta_court_id(docket_id: str) -> str:
    if not str(docket_id or "").isdigit():
        return ""
    rec = _docket_meta_index().get(int(docket_id)) or {}
    court = str(rec.get("court") or "")
    match = re.search(r"/courts/([^/]+)/", court)
    return match.group(1) if match else court


def _metadata_score(row: Dict[str, Any]) -> int:
    skip = {"case_kind", "duplicate_of", "prior_status"}
    return sum(1 for key, value in row.items() if key not in skip and str(value or "").strip())


def apply_canonical_marks(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """One row per court + case number + docket entry. Others are marked, not deleted.

    Non-criminal docket numbers (civil, MDL, and anything other than cr/mj) are
    marked NON_CRIMINAL. A free or collected copy is preferred, then the row
    with the most filled fields.
    """
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in rows:
        number = (row.get("docket_number") or "").strip()
        court = (row.get("court") or "").strip() or _meta_court_id(str(row.get("docket_id") or ""))
        if not (row.get("court") or "").strip() and court:
            row["court"] = court
        entry = _entry_number(row)
        if entry is None:
            if not (row.get("prior_status") or "").strip():
                row["prior_status"] = row.get("status") or ""
            row["docket_entry_number"] = ""
            row["status"] = "UNCLEAR"
            row["unclear_reason"] = "missing_entry_number"
            row["duplicate_of"] = ""
            continue
        row["docket_entry_number"] = entry
        key = (court.lower(), number.lower(), entry)
        groups.setdefault(key, []).append(row)

    queued_removed = 0
    duplicates = 0
    non_criminal = 0
    for key, group in groups.items():
        criminal = bool(_CRIMINAL_NUM_RE.search(key[1]))

        def rank(row: Dict[str, Any]) -> tuple:
            status = (row.get("status") or "").strip()
            collected = 0 if status == "COLLECTED" else 1
            preferred = 0 if status in {"COLLECTED", "FREE_NOW"} else 1
            recap = int(row["recap_document_id"]) if str(row.get("recap_document_id") or "").isdigit() else 0
            return (collected, preferred, -_metadata_score(row), recap)

        ordered = sorted(group, key=rank)
        canon = ordered[0]
        canon_id = str(canon.get("recap_document_id") or "")
        for row in ordered:
            row["case_kind"] = "criminal" if criminal else "non_criminal"
            row.setdefault("duplicate_of", "")
            row.setdefault("prior_status", "")
            if not criminal:
                non_criminal += 1
                if (row.get("status") or "") == "FREE_NOW":
                    queued_removed += 1
                if not (row.get("prior_status") or "").strip():
                    row["prior_status"] = row.get("status") or ""
                row["status"] = "NON_CRIMINAL"
                row["duplicate_of"] = "" if row is canon else canon_id
                continue
            if row is canon:
                row["duplicate_of"] = ""
                continue
            duplicates += 1
            if (row.get("status") or "") == "FREE_NOW":
                queued_removed += 1
            if not (row.get("prior_status") or "").strip():
                row["prior_status"] = row.get("status") or ""
            row["duplicate_of"] = canon_id
            row["status"] = f"DUPLICATE_OF={canon_id}"
    return {
        "duplicate_rows": duplicates,
        "non_criminal_rows": non_criminal,
        "queued_removed": queued_removed,
    }


# Jeffrey Sterling, E.D. Va. 1:10-cr-00485, is an Espionage Act case. The fraud
# year sweep kept it because a "mail fraud" AND indictment query returned the
# indictment. The docket text of that indictment does not describe a fraud case.
_DOMAIN_OVERRIDES = {
    "1:10-cr-00485": "other_federal",
}
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
)
_HEARING_DATE_RES = (
    re.compile(r"\b(?:held on|for dates? of|date of)\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.I),
    re.compile(r"\b(?:held on|for dates? of|date of)\s+([A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?, \d{4})", re.I),
    re.compile(r"\b(?:held on|for dates? of|date of)\s+([A-Za-z]+ \d{1,2} \d{4})", re.I),
)
_FINER_HEARING = (
    ("suppression", re.compile(r"suppress", re.I)),
    ("arraignment", re.compile(r"arraign", re.I)),
    ("status_conference", re.compile(r"status conference", re.I)),
    ("bail", re.compile(r"\bbail\b", re.I)),
    ("pretrial", re.compile(r"pre-?\s*trial", re.I)),
    ("motion", re.compile(r"motion hearing|\bmotion to\b|\bre:\s*motion\b", re.I)),
    ("oral_argument", re.compile(r"oral argument", re.I)),
    ("conference", re.compile(r"\bconference\b", re.I)),
    ("revocation", re.compile(r"revocation|supervised release", re.I)),
)


def _parse_date_text(text: str) -> str:
    raw = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", (text or "").strip(), flags=re.I)
    if not raw:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        if parsed.year < 1980 or parsed.year > 2035:
            continue
        return parsed.isoformat()
    return ""


def normalize_hearing_date(raw: str, description: str = "") -> str:
    """YYYY-MM-DD from the stored value, or from the docket description."""
    parsed = _parse_date_text(raw)
    if parsed:
        return parsed
    for pattern in _HEARING_DATE_RES:
        match = pattern.search(description or "")
        if not match:
            continue
        parsed = _parse_date_text(match.group(1))
        if parsed:
            return parsed
    return ""


def refined_hearing_type(description: str, current: str) -> str:
    """Replace a generic other label when the docket text names the proceeding."""
    current = (current or "").strip() or "other"
    text = description or ""
    if current in {"sentencing", "change_of_plea", "detention", "trial"}:
        return current
    # "Vol. I" has no word boundary after the period, so the shared trial regex misses it.
    if re.search(r"\bvol\.", text, re.I):
        return "trial"
    proposed = hearing_type_of(text) if text else current
    if proposed in {"sentencing", "change_of_plea", "detention", "trial"}:
        return proposed
    for label, pattern in _FINER_HEARING:
        if pattern.search(text):
            return label
    return proposed if proposed != "other" else current


def _description_core(description: str) -> str:
    text = description or ""
    text = re.split(
        r"court reporter|transcript may be viewed|redaction request due|notice re redact",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    return re.sub(r"\s+", " ", text).strip().lower()


def descriptions_clearly_differ(left: str, right: str) -> bool:
    """True when the hearings themselves differ, not just the reporter or boilerplate."""
    core_left = _description_core(left)
    core_right = _description_core(right)
    if not core_left or not core_right:
        return False
    return core_left != core_right


def _add_flag(row: Dict[str, Any], flag: str) -> None:
    current = [part for part in (row.get("review_flag") or "").split(";") if part]
    if flag not in current:
        current.append(flag)
    row["review_flag"] = ";".join(current)


def apply_share_cleanup(
    rows: List[Dict[str, Any]],
    descriptions: Dict[str, str],
) -> Dict[str, Any]:
    """Second dedup, domain correction, hearing labels, dates, and review flags.

    Within one criminal case, the same hearing date and the same page count are
    one transcript unless the docket descriptions clearly differ. A collected
    copy is kept; otherwise the lower docket entry is kept.
    """
    for row in rows:
        row["review_flag"] = ""
        number = (row.get("docket_number") or "").strip().lower()
        override = _DOMAIN_OVERRIDES.get(number)
        if override:
            row["domain"] = override
        description = descriptions.get(str(row.get("recap_document_id") or ""), "")
        row["hearing_date"] = normalize_hearing_date(row.get("hearing_date") or "", description)
        row["hearing_type"] = refined_hearing_type(description, row.get("hearing_type") or "")
        pages = str(row.get("page_count") or "").strip()
        if pages.isdigit() and int(pages) < 3:
            _add_flag(row, "under_3_pages")
        if re.match(r"\s*redacted transcript\b", description, re.I):
            _add_flag(row, "redacted_copy")
        pointed = re.search(r"see redacted transcript\s+(\d+)", description, re.I)
        if pointed:
            _add_flag(row, f"see_redacted_entry={pointed.group(1)}")

    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in rows:
        status = (row.get("status") or "").strip()
        if row.get("case_kind") != "criminal":
            continue
        if (row.get("duplicate_of") or "").strip() or status.startswith("DUPLICATE_OF") or status == "NON_CRIMINAL":
            continue
        if status == "UNCLEAR" or _entry_number(row) is None:
            continue
        groups.setdefault(((row.get("court") or "").strip().lower(), (row.get("docket_number") or "").strip().lower()), []).append(row)

    exact_pairs: List[Dict[str, str]] = []
    differed: List[Dict[str, str]] = []
    queued_removed = 0
    for key, group in groups.items():
        by_hearing: Dict[tuple, List[Dict[str, Any]]] = {}
        for row in group:
            pages = str(row.get("page_count") or "").strip()
            heard = (row.get("hearing_date") or "").strip()
            if not pages.isdigit() or not heard:
                continue
            by_hearing.setdefault((heard, pages), []).append(row)
        for (heard, pages), bucket in by_hearing.items():
            if len(bucket) < 2:
                continue
            ordered = sorted(bucket, key=lambda row: (0 if row.get("status") == "COLLECTED" else 1, int(_entry_number(row))))
            canon = ordered[0]
            canon_desc = descriptions.get(str(canon.get("recap_document_id") or ""), "")
            for row in ordered[1:]:
                row_desc = descriptions.get(str(row.get("recap_document_id") or ""), "")
                pair = {
                    "court": key[0],
                    "docket_number": row.get("docket_number") or "",
                    "case_caption": row.get("case_caption") or "",
                    "hearing_date": heard,
                    "pages": pages,
                    "kept_entry": str(canon.get("docket_entry_number") or ""),
                    "other_entry": str(row.get("docket_entry_number") or ""),
                }
                if descriptions_clearly_differ(canon_desc, row_desc):
                    pair["action"] = "kept_both"
                    differed.append(pair)
                    continue
                pair["action"] = "duplicate"
                exact_pairs.append(pair)
                if (row.get("status") or "") == "FREE_NOW":
                    queued_removed += 1
                if not (row.get("prior_status") or "").strip():
                    row["prior_status"] = row.get("status") or ""
                canon_id = str(canon.get("recap_document_id") or "")
                row["duplicate_of"] = canon_id
                row["status"] = f"DUPLICATE_OF={canon_id}"

    near_pairs: List[Dict[str, str]] = []
    for key, group in groups.items():
        live = [
            row for row in group
            if not (row.get("duplicate_of") or "").strip() and not (row.get("status") or "").startswith("DUPLICATE_OF")
        ]
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for row in live:
            heard = (row.get("hearing_date") or "").strip()
            if heard and str(row.get("page_count") or "").strip().isdigit():
                by_date.setdefault(heard, []).append(row)
        for heard, bucket in by_date.items():
            ordered = sorted(bucket, key=lambda row: int(_entry_number(row)))
            for index, left in enumerate(ordered):
                for right in ordered[index + 1 :]:
                    left_pages = int(left["page_count"])
                    right_pages = int(right["page_count"])
                    if left_pages == right_pages:
                        continue
                    left_desc = descriptions.get(str(left.get("recap_document_id") or ""), "")
                    right_desc = descriptions.get(str(right.get("recap_document_id") or ""), "")
                    if descriptions_clearly_differ(left_desc, right_desc):
                        continue
                    diff = abs(left_pages - right_pages)
                    close = diff <= 5 or diff / max(left_pages, right_pages) <= 0.05
                    if not close:
                        continue
                    _add_flag(left, "near_duplicate_pages")
                    _add_flag(right, "near_duplicate_pages")
                    near_pairs.append(
                        {
                            "court": key[0],
                            "docket_number": left.get("docket_number") or "",
                            "case_caption": left.get("case_caption") or "",
                            "hearing_date": heard,
                            "entries": f"{left.get('docket_entry_number')}/{right.get('docket_entry_number')}",
                            "pages": f"{left_pages}/{right_pages}",
                            "action": "review",
                        }
                    )
    return {
        "exact_pairs": exact_pairs,
        "descriptions_differed": differed,
        "near_pairs": near_pairs,
        "queued_removed": queued_removed,
    }


_PILOT_HEARINGS = ("sentencing", "change_of_plea", "detention", "suppression", "evidentiary_agent")
_KEY_DOC_RE = re.compile(
    r"^\s*(?:(?:sealed|redacted|superseding|first|second|third|amended)\s+)*"
    r"(indictment|plea agreement|sentencing memorandum|sentencing memo)\b",
    re.I,
)
_DOCKET_NUM_RE = re.compile(r"(\d+):(\d{2})-(cr|mj)-0*(\d+)", re.I)
_DOC_TYPE_RE = re.compile(
    r"\b(superseding indictment|sealed indictment|redacted indictment|indictment|"
    r"plea agreement|sentencing memorandum|sentencing memo|criminal complaint|"
    r"complaint|affidavit|transcript|order|letter)\b",
    re.I,
)


def hearing_key(row: Dict[str, Any]) -> str:
    if row.get("hearing_type") in {"sentencing", "change_of_plea", "detention", "trial"}:
        return str(row.get("hearing_type"))
    return str(row.get("hearing_subtype") or "other")


def pilot_eligible(row: Dict[str, Any]) -> bool:
    if row.get("status") not in {"FREE_NOW", "BUYABLE_LATER"}:
        return False
    if row.get("hearing_type") == "trial":
        return False
    subtype = row.get("hearing_subtype") or ""
    if subtype in {"status_conference", "conference", "arraignment", "unspecified_proceeding", "oral_argument", "opening_statement", "bench_trial"}:
        return False
    return hearing_key(row) in _PILOT_HEARINGS


def _court_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if re.fullmatch(r"[a-z]{3,6}", text):
        return text
    return _court_id_from_text(text)


def _number_parts(value: Any) -> Optional[tuple]:
    match = _DOCKET_NUM_RE.search(str(value or ""))
    if not match:
        return None
    office, year, kind, seq = match.groups()
    return (office, year, kind.lower(), str(int(seq)))


def _document_type(text: str) -> str:
    match = _KEY_DOC_RE.match(text or "")
    if match:
        name = match.group(1).lower()
        if name.startswith("sentencing"):
            name = "sentencing memo"
        prefix = (text or "")[: match.start(1)].strip().lower()
        return f"{prefix} {name}".strip() if prefix else name
    found = _DOC_TYPE_RE.search(text or "")
    return found.group(1).lower() if found else "other"


def _pdf_on_disk(path_value: Any) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_file():
        path = REPO / raw
    if path.is_file() and path.suffix.lower() == ".pdf" and path.stat().st_size > 0:
        return str(path)
    return ""


def _held_sources() -> Iterable[tuple]:
    """Local indexes that point at PDFs already under data/collected/."""
    for path in (
        COLLECTED / "recap" / "fraud" / "fraud_study.jsonl",
        COLLECTED / "recap" / "fraud" / "from_press.jsonl",
        COLLECTED / "recap" / "bulk" / "manifests" / "recap_links.jsonl",
        COLLECTED / "public" / "fraud_court_lookup.jsonl",
    ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield path, json.loads(line)
    for path in (
        COLLECTED / "recap" / "csea" / "court_manifest.json",
        COLLECTED / "recap" / "fraud" / "court_manifest.json",
        COLLECTED / "recap" / "trafficking" / "court_manifest.json",
        COLLECTED / "recap" / "cyber" / "court_manifest.json",
        COLLECTED / "recap" / "bulk" / "court_manifest.json",
    ):
        if not path.is_file():
            continue
        for rec in json.loads(path.read_text(encoding="utf-8")):
            chosen = rec.get("chosen_document") or {}
            saved = (rec.get("download") or {}).get("path") if isinstance(rec.get("download"), dict) else ""
            base = {
                "docket_id": rec.get("docket_id"),
                "docket_number": rec.get("docket_number"),
                "court": rec.get("court"),
                "absolute_url": rec.get("absolute_url"),
            }
            if isinstance(chosen, dict) and chosen:
                yield path, {**base, "document_id": chosen.get("id"), "description": chosen.get("description"), "pdf": saved}
            for doc in rec.get("free_nested_documents") or []:
                if isinstance(doc, dict):
                    yield path, {**base, "document_id": doc.get("id"), "description": doc.get("description")}


def load_held_pdfs() -> List[Dict[str, Any]]:
    """Every held court PDF, with the docket id and the court plus docket number when known."""
    cached = getattr(load_held_pdfs, "cache", None)
    if cached is not None:
        return cached
    by_doc: Dict[str, Path] = {}
    for path in COLLECTED.rglob("*.pdf"):
        if path.stat().st_size > 0:
            by_doc.setdefault(path.stem, path)
    meta = _docket_meta_index()
    found: Dict[tuple, Dict[str, Any]] = {}
    for source, rec in _held_sources():
        if not isinstance(rec, dict):
            continue
        description = str(rec.get("document_description") or rec.get("description") or "")
        download = rec.get("download") if isinstance(rec.get("download"), dict) else {}
        pdf = _pdf_on_disk(rec.get("pdf") or download.get("path") or "")
        doc_id = str(rec.get("document_id") or rec.get("id") or "")
        if not pdf and doc_id:
            named = by_doc.get(doc_id)
            pdf = str(named) if named else ""
        if not pdf:
            continue
        docket_id = rec.get("docket_id") or _docket_id_from_url(
            str(rec.get("absolute_url") or rec.get("page_url") or "")
        )
        try:
            docket_id_int = int(docket_id) if docket_id else None
        except (TypeError, ValueError):
            docket_id_int = None
        number = str(rec.get("docket_number") or "")
        court = _court_key(rec.get("court_id") or rec.get("court"))
        if docket_id_int and docket_id_int in meta:
            number = number or meta[docket_id_int].get("docket_number") or ""
            court = court or _court_key(meta[docket_id_int].get("court"))
        if not number:
            embedded = _DOCKET_NUM_RE.search(description)
            number = embedded.group(0) if embedded else ""
        doc_type = _document_type(description)
        key = (pdf, docket_id_int, doc_type)
        found[key] = {
            "pdf": pdf,
            "docket_id": docket_id_int,
            "docket_number": number,
            "court": court,
            "document_type": doc_type,
            "description": description[:180],
            "source": str(source.relative_to(REPO)),
            "key_doc": bool(_KEY_DOC_RE.match(description)),
        }
    load_held_pdfs.cache = list(found.values())  # type: ignore[attr-defined]
    return load_held_pdfs.cache  # type: ignore[attr-defined]


def _docket_meta_index() -> Dict[int, Dict[str, Any]]:
    path = CACHE / "docket_meta.jsonl"
    index: Dict[int, Dict[str, Any]] = {}
    if not path.is_file():
        return index
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        try:
            index[int(rec.get("id") or rec.get("docket_id"))] = rec
        except (TypeError, ValueError):
            continue
    return index


def dockets_with_key_docs() -> set:
    """Dockets that already have an indictment, plea agreement, or sentencing memo on disk.

    A hit on the criminal docket also covers its magistrate docket in the same court,
    and the reverse, when the office, year, and sequence match.
    """
    meta = _docket_meta_index()
    direct: set = set()
    cores: set = set()
    for rec in load_held_pdfs():
        if not rec["key_doc"] or not rec["docket_id"]:
            continue
        direct.add(rec["docket_id"])
        info = meta.get(rec["docket_id"]) or {}
        parts = _number_parts(info.get("docket_number") or rec.get("docket_number"))
        court = _court_key(info.get("court") or rec.get("court"))
        if parts and court:
            cores.add((court, parts[0], parts[1], parts[3]))
    found = set(direct)
    for docket_id, info in meta.items():
        parts = _number_parts(info.get("docket_number"))
        court = _court_key(info.get("court"))
        if parts and court and (court, parts[0], parts[1], parts[3]) in cores:
            found.add(docket_id)
    dockets_with_key_docs.direct = direct  # type: ignore[attr-defined]
    dockets_with_key_docs.related = found - direct  # type: ignore[attr-defined]
    return found


def _key_doc_label(docket_id: int, key_docs: set) -> str:
    if docket_id not in key_docs:
        return "no"
    types = sorted(
        {
            rec["document_type"]
            for rec in load_held_pdfs()
            if rec["key_doc"] and rec["docket_id"] == docket_id
        }
    )
    if types:
        return ", ".join(types)
    return "yes, on related docket"


def _pilot_score(row: Dict[str, Any], key_docs: set) -> tuple:
    free = 0 if row.get("status") == "FREE_NOW" else 1
    try:
        did = int(row.get("docket_id"))
    except (TypeError, ValueError):
        did = -1
    held = 0 if did in key_docs else 1
    pages = str(row.get("page_count") or "")
    known = 0 if pages.isdigit() else 1
    cost = int(pages) if pages.isdigit() else 100
    return (free, held, known, cost)


def assign_pilot(rows: List[Dict[str, Any]], key_docs: Optional[set] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Clear old pilot tags and pick 10 rows, then 3 alternates. At most 2 per case."""
    if key_docs is None:
        key_docs = dockets_with_key_docs()
    for row in rows:
        if (row.get("approved") or "") in {"pilot", "pilot-alternate"}:
            row["approved"] = ""
        if (row.get("pilot_suggest") or "") in {"yes", "alternate"}:
            row["pilot_suggest"] = ""
    per_case: Dict[str, int] = {}
    chosen: Dict[str, List[Dict[str, Any]]] = {"pilot": [], "alternate": []}

    def take(row: Dict[str, Any], role: str) -> None:
        row["approved"] = role
        row["pilot_suggest"] = "yes" if role == "pilot" else "alternate"
        key = str(row.get("docket_id"))
        per_case[key] = per_case.get(key, 0) + 1
        chosen["pilot" if role == "pilot" else "alternate"].append(row)

    def open_rows(pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            row
            for row in pool
            if row not in chosen["pilot"]
            and row not in chosen["alternate"]
            and per_case.get(str(row.get("docket_id")), 0) < 2
        ]

    def fill(pool: List[Dict[str, Any]], quota: int, role: str) -> int:
        got = 0
        for hearing in _PILOT_HEARINGS:
            if got >= quota:
                break
            options = [row for row in open_rows(pool) if hearing_key(row) == hearing]
            if not options:
                continue
            options.sort(key=lambda row: _pilot_score(row, key_docs))
            take(options[0], role)
            got += 1
        rest = open_rows(pool)
        rest.sort(key=lambda row: _pilot_score(row, key_docs))
        for row in rest:
            if got >= quota:
                break
            take(row, role)
            got += 1
        return got

    short_domains = []
    quotas = (("csea", 4), ("fraud", 3), ("trafficking", 3))
    for domain, quota in quotas:
        pool = [row for row in rows if row.get("domain") == domain and pilot_eligible(row)]
        got = fill(pool, quota, "pilot")
        if got < quota:
            short_domains.append((domain, quota, got))
    if len(chosen["pilot"]) < 10:
        rest_pool = [row for row in rows if pilot_eligible(row)]
        fill(rest_pool, 10 - len(chosen["pilot"]), "pilot")
    alt_pool = [row for row in rows if pilot_eligible(row)]
    fill(alt_pool, 3, "pilot-alternate")
    chosen["short_domains"] = short_domains
    return chosen
def stale_rows(
    inventory: Dict[int, Dict[str, Any]],
    meta: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for did, info in inventory.items():
        dmeta = meta.get(did) or {}
        modified = _date_only(dmeta.get("date_modified") or "")
        terminated = _date_only(dmeta.get("date_terminated") or "")
        if not modified or not terminated or modified >= terminated:
            continue
        source = dmeta.get("updated_source") or "rest"
        reason = (
            "search_index_timestamp_before_termination"
            if source == "search_index"
            else "courtlistener_updated_before_termination"
        )
        rows.append(
            {
                "domain": info.get("domain") or "",
                "case_caption": dmeta.get("case_name") or info.get("case_caption") or "",
                "court": info.get("court") or "",
                "docket_number": dmeta.get("docket_number") or info.get("docket_number") or "",
                "docket_id": did,
                "courtlistener_updated": modified.isoformat(),
                "date_terminated": terminated.isoformat(),
                "stale_reason": reason,
                "refresh_cost_usd_max": f"{DOCKET_REFRESH_CAP:.2f}",
                "source": info.get("source") or "",
            }
        )
    return rows


def _write_csv(path: Path, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def resolve_pacer(client: Client, inventory: Dict[int, Dict[str, Any]]) -> None:
    targets = [row for row in load_pacer_targets() if row.get("court_id")]
    if not targets:
        print("No PACER ledger dockets with a known court id", file=sys.stderr)
        return
    known_numbers = {
        (info.get("court_id"), (info.get("docket_number") or "").lower())
        for info in inventory.values()
    }
    pending = [
        row
        for row in targets
        if (row["court_id"], row["docket_number"].lower()) not in known_numbers
    ]
    print(f"Resolving {len(pending)} PACER ledger dockets on CourtListener", file=sys.stderr)
    for start in range(0, len(pending), 8):
        batch = pending[start : start + 8]
        clause = " OR ".join(
            f'(docketNumber:"{row["docket_number"]}" AND court_id:{row["court_id"]})'
            for row in batch
        )
        payload = client.get(
            "https://www.courtlistener.com/api/rest/v4/search/",
            {"type": "d", "q": clause},
        )
        for hit in payload.get("results") or []:
            number = (hit.get("docketNumber") or "").lower()
            court = (hit.get("court_id") or "").lower()
            match = next(
                (
                    row
                    for row in batch
                    if row["court_id"] == court and row["docket_number"].lower() in number
                ),
                None,
            )
            if match is None:
                continue
            _remember(
                inventory,
                hit.get("docket_id"),
                {
                    "domain": match["domain"],
                    "case_caption": hit.get("caseName") or "",
                    "court": hit.get("court") or "",
                    "court_id": court,
                    "docket_number": hit.get("docketNumber") or match["docket_number"],
                    "source": match["source"],
                    "related_docket": "no",
                },
            )


def _hit_sections(cache_name: str) -> tuple:
    """Return (hit rows, batch sections) from the transcript cache. No network."""
    hits: List[Dict[str, Any]] = []
    sections: List[tuple] = []
    current: List[Dict[str, Any]] = []
    path = CACHE / cache_name
    if not path.is_file():
        return hits, sections
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("_batch"):
            sections.append((row, current))
            current = []
        elif row.get("id"):
            hits.append(row)
            current.append(row)
    return hits, sections


def _batch_bounds(marker: Dict[str, Any]) -> tuple:
    start, end, size = str(marker["_batch"]).split(":")
    return int(start), int(end), int(size)


def _capped_groups(inventory_ids: List[int], sections: List[tuple]) -> List[tuple]:
    """Held docket ids inside each batch that stopped at 160 hits."""
    latest: Dict[str, Dict[str, Any]] = {}
    section_hits: Dict[str, List[Dict[str, Any]]] = {}
    for marker, section in sections:
        key = str(marker.get("_batch") or "")
        if key.startswith("repost:"):
            continue
        latest[key] = marker
        if section:
            section_hits[key] = section
    groups = []
    for key, marker in latest.items():
        if marker.get("complete") or int(marker.get("n") or 0) < 160:
            continue
        start, end, _size = _batch_bounds(marker)
        group = {did for did in inventory_ids if start <= did <= end}
        for hit in section_hits.get(key, []):
            try:
                did = int(hit.get("docket_id"))
            except (TypeError, ValueError):
                continue
            if start <= did <= end:
                group.add(did)
        groups.append((key, sorted(group)))
    return groups


def finish_capped_batches(client: Client, inventory_ids: List[int]) -> int:
    """Paginate the three batches that stopped at 160 hits. Does not start new batches."""
    _hits, sections = _hit_sections("transcript_hits.jsonl")
    groups = _capped_groups(inventory_ids, sections)
    print(f"Capped transcript batches to finish: {len(groups)}", file=sys.stderr)
    if not groups:
        return 0
    path = CACHE / "transcript_hits.jsonl"
    written = 0
    with path.open("a", encoding="utf-8") as handle:

        def run(batch: List[int], label: str) -> None:
            nonlocal written
            clause = " OR ".join(f"docket_id:{did}" for did in batch)
            page_hits, complete = _search_pages(
                client,
                {"type": "rd", "q": f'({clause}) "TRANSCRIPT of Proceedings"'},
            )
            if not complete and len(batch) > 1:
                print(f"  splitting {label} ({len(batch)} dockets)", file=sys.stderr)
                mid = len(batch) // 2
                run(batch[:mid], label + "a")
                run(batch[mid:], label + "b")
                return
            for hit in page_hits:
                handle.write(json.dumps(hit) + "\n")
                written += 1
            handle.write(
                json.dumps(
                    {
                        "_batch": label,
                        "n": len(page_hits),
                        "complete": complete,
                        "ids": len(batch),
                    }
                )
                + "\n"
            )
            handle.flush()
            print(
                f"  finished {label} dockets={len(batch)} hits+{len(page_hits)} complete={complete}",
                file=sys.stderr,
            )

        for key, group in groups:
            print(f"Paginating capped batch {key} ({len(group)} held dockets)", file=sys.stderr)
            run(group, f"repost:{key}")
            handle.write(
                json.dumps(
                    {
                        "_batch": key,
                        "n": 0,
                        "complete": True,
                        "repost": True,
                        "queried": len(group),
                    }
                )
                + "\n"
            )
            handle.flush()
    return written


def _coverage(sections: List[tuple]) -> tuple:
    """Docket slots from the original 786-id sweep whose search reached the last page."""
    finished_slots = 0
    capped_slots = 0
    finished_batches = 0
    capped_batches = 0
    latest: Dict[str, Dict[str, Any]] = {}
    for marker, _section in sections:
        key = str(marker.get("_batch") or "")
        if key.startswith("repost:"):
            continue
        latest[key] = marker
    for marker in latest.values():
        _start, _end, size = _batch_bounds(marker)
        if marker.get("complete") or int(marker.get("n") or 0) < 160:
            finished_slots += int(marker["queried"]) if marker.get("repost") else size
            finished_batches += 1
        else:
            capped_slots += size
            capped_batches += 1
    return finished_batches, finished_slots, capped_batches, capped_slots


def _print_status_counts(rows: List[Dict[str, Any]]) -> None:
    statuses = ["FREE_NOW", "BUYABLE_LATER", "RESTRICTED", "SEALED", "UNCLEAR"]
    counted = [row for row in rows if row.get("hearing_type") != "trial"]
    domains = sorted({row.get("domain") or "unknown" for row in counted})
    print("Counts by domain x status, trial excluded")
    header = "domain," + ",".join(statuses) + ",total"
    print(header)
    for domain in domains:
        cells = []
        for status in statuses:
            cells.append(
                str(sum(1 for row in counted if row.get("domain") == domain and row.get("status") == status))
            )
        total = sum(1 for row in counted if row.get("domain") == domain)
        print(domain + "," + ",".join(cells) + f",{total}")
    print(f"Rows in that table: {len(counted)}")
    print(f"Trial rows excluded from the table: {len(rows) - len(counted)}")


def _load_hit_text() -> Dict[str, Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    path = CACHE / "transcript_hits.jsonl"
    if not path.is_file():
        return by_id
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("_batch") or not row.get("id"):
            continue
        by_id[str(row["id"])] = row
    return by_id


def refine_from_cache() -> Dict[str, Any]:
    """Reclassify the manifest from cached docket text. No network."""
    from datetime import datetime as dt

    inventory = load_inventory()
    hits = _load_hit_text()
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    before_unclear = {}
    for domain in ("fraud", "trafficking", "csea"):
        before_unclear[domain] = sum(1 for row in rows if row.get("domain") == domain and row.get("status") == "UNCLEAR")
    before_unknown_pages = sum(
        1
        for row in rows
        if row.get("status") == "BUYABLE_LATER"
        and row.get("hearing_type") != "trial"
        and not str(row.get("page_count") or "").isdigit()
    )
    pages_resolved = 0
    for row in rows:
        hit = hits.get(str(row.get("recap_document_id") or ""))
        if not hit:
            row.setdefault("hearing_subtype", hearing_key(row) if row.get("hearing_type") != "other" else "unspecified_proceeding")
            continue
        description = hit.get("description") or ""
        entry_date = None
        filed = hit.get("entry_date_filed") or ""
        if filed:
            try:
                entry_date = dt.strptime(str(filed)[:10], "%Y-%m-%d").date()
            except ValueError:
                entry_date = None
        had_pages = str(row.get("page_count") or "").isdigit()
        classified = classify_transcript_status(
            description,
            is_available=bool(hit.get("is_available")),
            has_file=bool(hit.get("filepath_local")),
            entry_date=entry_date,
            api_page_count=hit.get("page_count"),
            today=TODAY,
        )
        if classified is None:
            continue
        row["status"] = classified["status"]
        row["hearing_type"] = classified["hearing_type"]
        row["hearing_subtype"] = classified["hearing_subtype"]
        row["hearing_date"] = classified["hearing_date"]
        row["page_count"] = classified["page_count"]
        row["restriction_release_date"] = classified["restriction_release_date"]
        row["sealed_or_restricted"] = classified["sealed_or_restricted"]
        row["estimated_cost_usd"] = classified["estimated_cost_usd"]
        row["unclear_reason"] = classified["reason"]
        if not had_pages and str(classified["page_count"]).isdigit():
            pages_resolved += 1
        if row["status"] == "BUYABLE_LATER" and not str(row.get("page_count") or "").isdigit():
            if not (row.get("row_spend_cap_usd") or "").strip():
                row["row_spend_cap_usd"] = "10"
                row["estimated_cost_usd"] = "10.00"
        elif (row.get("row_spend_cap_usd") or "") == "10" and str(row.get("page_count") or "").isdigit():
            row["row_spend_cap_usd"] = ""
    after_unclear = {}
    for domain in ("fraud", "trafficking", "csea"):
        after_unclear[domain] = sum(1 for row in rows if row.get("domain") == domain and row.get("status") == "UNCLEAR")
    chosen = assign_pilot(rows, dockets_with_key_docs())
    _write_csv(MANIFEST, MANIFEST_FIELDS, rows)
    stats = {
        "inventory": inventory,
        "before_unclear": before_unclear,
        "after_unclear": after_unclear,
        "pages_resolved": pages_resolved,
        "before_unknown_pages": before_unknown_pages,
    }
    write_discovery_report(rows, chosen, inventory_count=len(inventory), covered_count=len(inventory), hit_dockets=0, stats=stats)
    return {"rows": rows, "chosen": chosen, "stats": stats}


def _report_bucket(row: Dict[str, Any]) -> str:
    key = hearing_key(row)
    if key in {"detention", "change_of_plea", "sentencing", "suppression", "evidentiary_agent", "trial"}:
        return key
    return "other"


def write_discovery_report(
    rows: List[Dict[str, Any]],
    chosen: Dict[str, List[Dict[str, Any]]],
    *,
    inventory_count: int,
    covered_count: int,
    hit_dockets: int,
    stats: Optional[Dict[str, Any]] = None,
) -> None:
    labels = {"csea": "CSEA/ICAC", "fraud": "fraud", "trafficking": "trafficking", "cyber": "cyber"}
    inventory = (stats or {}).get("inventory") or {}
    domain_counts = {}
    if inventory:
        for info in inventory.values():
            domain_counts[info.get("domain") or "other"] = domain_counts.get(info.get("domain") or "other", 0) + 1
    statuses = ["FREE_NOW", "BUYABLE_LATER", "RESTRICTED", "SEALED", "UNCLEAR"]
    hearings = ["detention", "change_of_plea", "sentencing", "suppression", "evidentiary_agent", "trial", "other"]
    lines = [
        "# Transcript discovery",
        "",
        "Free CourtListener metadata only. No PDFs were downloaded and no PACER charge was made.",
        "",
        "## Held corpus",
        "",
        f"Held dockets: {inventory_count or sum(domain_counts.values())}.",
        "",
    ]
    for domain in ("csea", "fraud", "trafficking", "cyber"):
        lines.append(f"- {labels.get(domain, domain)}: {domain_counts.get(domain, 0)} dockets")
    csea_rows = [row for row in rows if row.get("domain") == "csea"]
    csea_dockets = {row.get("docket_id") for row in csea_rows}
    lines.extend(
        [
            "",
            f"CSEA/ICAC transcript rows: {len(csea_rows)} on {len(csea_dockets)} of the {domain_counts.get('csea', 0)} held CSEA dockets.",
            "",
            "## Counts",
            "",
            "Trial rows stay in the table and are not eligible to pull.",
            "",
        ]
    )
    for domain, label in labels.items():
        if not any(row.get("domain") == domain for row in rows):
            continue
        lines.append(f"### {label}")
        lines.append("")
        lines.append("| status | " + " | ".join(hearings) + " |")
        lines.append("| --- | " + " | ".join("---" for _ in hearings) + " |")
        for status in statuses:
            cells = []
            for hearing in hearings:
                cells.append(
                    str(
                        sum(
                            1
                            for row in rows
                            if row.get("domain") == domain
                            and row.get("status") == status
                            and _report_bucket(row) == hearing
                        )
                    )
                )
            lines.append(f"| {status} | " + " | ".join(cells) + " |")
        lines.append("")
    free = [row for row in rows if row.get("status") == "FREE_NOW" and row.get("hearing_type") != "trial"]
    lines.extend(["## FREE_NOW, trials excluded", "", f"{len(free)} rows.", ""])
    lines.append("| domain | detention | change_of_plea | sentencing | suppression | evidentiary_agent | other |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for domain in ("csea", "fraud", "trafficking", "cyber"):
        cells = [
            str(sum(1 for row in free if row.get("domain") == domain and _report_bucket(row) == hearing))
            for hearing in ("detention", "change_of_plea", "sentencing", "suppression", "evidentiary_agent", "other")
        ]
        if any(cell != "0" for cell in cells):
            lines.append(f"| {labels[domain]} | " + " | ".join(cells) + " |")
    other_free = [row for row in free if _report_bucket(row) == "other"]
    subtype_counts: Dict[str, int] = {}
    for row in other_free:
        subtype_counts[row.get("hearing_subtype") or "unspecified_proceeding"] = (
            subtype_counts.get(row.get("hearing_subtype") or "unspecified_proceeding", 0) + 1
        )
    lines.extend(["", "### Other, by subtype", ""])
    for name, count in sorted(subtype_counts.items(), key=lambda item: -item[1]):
        lines.append(f"- {name}: {count}")
    lines.extend(
        [
            "",
            "Suppression hearings, and evidentiary hearings that mention agent testimony, are eligible.",
            "Status conferences, other conferences, and arraignments are not.",
            "",
            "## UNCLEAR",
            "",
        ]
    )
    before = (stats or {}).get("before_unclear") or {}
    after = (stats or {}).get("after_unclear") or {}
    if before:
        lines.append("| domain | before | after |")
        lines.append("| --- | ---: | ---: |")
        for domain in ("fraud", "trafficking", "csea"):
            lines.append(f"| {labels[domain]} | {before.get(domain, 0)} | {after.get(domain, 0)} |")
        lines.extend(
            [
                "",
                "The parser now accepts `Release of the Transcript Restriction is set for`.",
                "A filing older than 90 days with no restriction or sealing language is BUYABLE_LATER.",
                "",
            ]
        )
    lines.extend(
        [
            "## Page counts",
            "",
            f"Previously unknown non-trial BUYABLE_LATER page counts: {(stats or {}).get('before_unknown_pages', 'n/a')}.",
            f"Resolved from docket text in this pass: {(stats or {}).get('pages_resolved', 0)}.",
            "Remaining unknown paid rows use row_spend_cap_usd = 10 as a planning number.",
            "The run still stops at --max-spend, and the real page count is recorded after each buy.",
            "",
            "## Proposed pilot",
            "",
            "Key-doc preference uses PDFs on disk in the fraud study, press-joined RECAP files, trafficking RECAP links, and court manifests. A magistrate and criminal docket pair count as one case when the court, office, year, and sequence match.",
            "",
        ]
    )
    short = chosen.get("short_domains") or []
    if short:
        lines.append("Eligible rows did not fill every domain quota. The rest of the 10 were filled from other held domains.")
        for domain, quota, got in short:
            lines.append(f"- {labels.get(domain, domain)}: {got} of {quota}")
        lines.append("")
    pilot = chosen.get("pilot") or []
    alternates = chosen.get("alternate") or []
    lines.append("| role | domain | docket | entry | hearing | status | pages | est | key docs held |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    key_docs = dockets_with_key_docs()
    pilot_cost = 0.0
    for role, group in (("pilot", pilot), ("alternate", alternates)):
        for row in group:
            pages = row.get("page_count") or ""
            if row.get("status") == "FREE_NOW":
                est = 0.0
                est_text = "0.00"
            elif str(pages).isdigit():
                est = int(pages) * 0.10
                est_text = f"{est:.2f}"
            else:
                est = float(row.get("row_spend_cap_usd") or 0)
                est_text = f"{est:.2f} cap"
            if role == "pilot":
                pilot_cost += est
            try:
                held = _key_doc_label(int(row.get("docket_id")), key_docs)
            except (TypeError, ValueError):
                held = "no"
            lines.append(
                f"| {role} | {labels.get(row.get('domain'), row.get('domain'))} | {row.get('docket_number')} | "
                f"{row.get('docket_entry_number')} | {hearing_key(row)} | {row.get('status')} | {pages or 'unknown'} | {est_text} | {held} |"
            )
    lines.extend(
        [
            "",
            f"Estimated pilot cost, using $10 where the page count is unknown: ${pilot_cost:.2f}.",
            "Alternates are tagged `approved=pilot-alternate` and are not in that cost.",
            "",
            "## Pull command",
            "",
            "Not run. Wait until the reply is exactly `pulling is ok`.",
            "",
            "```bash",
            "python3 collector/pacer/transcripts.py fetch --manifest data/collected/PACER/transcripts/transcript_manifest.csv --approval-tag pilot --download --charge-pacer --max-records 10 --max-spend 100",
            "```",
            "",
        ]
    )
    report = OUT_DIR / "DISCOVERY_REPORT.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {report}")


def _hit_descriptions(hits: List[Dict[str, Any]]) -> Dict[str, str]:
    descriptions: Dict[str, str] = {}
    for hit in hits:
        doc_id = str(hit.get("id") or "").strip()
        if doc_id:
            descriptions[doc_id] = hit.get("description") or ""
    return descriptions


def assemble_sweep_rows(
    hits: List[Dict[str, Any]],
    inventory: Dict[int, Dict[str, Any]],
    meta: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build rows, restore saved approvals and COLLECTED, then recompute duplicate marks."""
    rows = merge_saved_columns(build_rows(hits, inventory, meta))
    apply_canonical_marks(rows)
    apply_share_cleanup(rows, _hit_descriptions(hits))
    return rows


def sweep() -> int:
    """Finish capped pages, search the remaining held dockets, then metadata.

    No downloads and no PACER. The manifest keeps any approval already saved.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    inventory = load_inventory()
    ids = sorted(inventory)
    _prior_hits, prior_sections = _hit_sections("transcript_hits.jsonl")
    covered = covered_docket_ids(ids, prior_sections)
    print(
        f"Held dockets in inventory: {len(ids)}. Already covered by finished batches: {len(covered)}.",
        file=sys.stderr,
    )
    client = Client(_token())
    finish_capped_batches(client, ids)
    _hits, sections = _hit_sections("transcript_hits.jsonl")
    covered = covered_docket_ids(ids, sections)
    missing = [did for did in ids if did not in covered]
    print(f"Transcript search still needed for {len(missing)} held dockets", file=sys.stderr)
    if missing:
        search_transcripts(client, missing, "transcript_hits.jsonl")
    hits, sections = _hit_sections("transcript_hits.jsonl")
    covered = covered_docket_ids(ids, sections)
    hit_dockets = sorted({int(hit["docket_id"]) for hit in hits if hit.get("docket_id")})
    print(f"Dockets with transcript hits: {len(hit_dockets)}", file=sys.stderr)
    meta = fetch_docket_meta(client, [did for did in hit_dockets if did in inventory or True])
    rows = assemble_sweep_rows(hits, inventory, meta)
    chosen = assign_pilot(rows)
    _write_csv(MANIFEST, MANIFEST_FIELDS, rows)
    print(f"Wrote {MANIFEST} ({len(rows)} transcript rows)")
    print(f"Finished transcript search covers {len(covered)} of {len(ids)} held dockets.")
    _print_status_counts(rows)
    write_discovery_report(
        rows,
        chosen,
        inventory_count=len(ids),
        covered_count=len(covered),
        hit_dockets=len(hit_dockets),
    )
    print(f"CourtListener GET calls so far: {client.calls}", file=sys.stderr)
    print(f"Metadata for the remaining dockets ({len(ids)} inventory ids)", file=sys.stderr)
    fetch_docket_meta(client, ids)
    meta_all: Dict[int, Dict[str, Any]] = {}
    cache_path = CACHE / "docket_meta.jsonl"
    if cache_path.is_file():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("id") is not None:
                    meta_all[int(row["id"])] = row
    _write_csv(STALE, STALE_FIELDS, stale_rows(inventory, meta_all))
    print(f"Wrote {STALE}")
    print(f"CourtListener GET calls: {client.calls}")
    return 0
def _approved(value: str) -> bool:
    return (value or "").strip().lower() in {"y", "yes", "true", "1", "approved"}


def _money(value: str) -> Optional[float]:
    text = (value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return float(text)


FREE_ROOT = COLLECTED / "recap" / "transcripts"
_MIN_PDF_BYTES = 512
_API_INTERVAL_S = 12.5


def _free_filename(row: Dict[str, Any]) -> str:
    return (
        f"{str(row.get('docket_number') or 'docket').replace(':', '-')}"
        f"_entry{row.get('docket_entry_number', '')}_{row['recap_document_id']}.pdf"
    )


def _free_dest(row: Dict[str, Any]) -> Path:
    domain = (row.get("domain") or "other").strip().lower()
    if domain not in {"csea", "fraud", "trafficking", "cyber", "other"}:
        domain = "other"
    return FREE_ROOT / domain / _free_filename(row)


def _provenance_path(pdf: Path) -> Path:
    return Path(str(pdf) + ".provenance.json")


def _saved_pdf(row: Dict[str, Any]) -> Path:
    """Use a PDF already on disk, including one saved before a domain correction."""
    name = _free_filename(row)
    for folder in ("fraud", "trafficking", "cyber", "csea", "other"):
        path = FREE_ROOT / folder / name
        if _pdf_ready(path) and _provenance_path(path).is_file():
            return path
    return _free_dest(row)


def _pdf_ready(path: Path) -> bool:
    from pull_guard import local_pdf_ok

    try:
        return path.is_file() and path.stat().st_size >= _MIN_PDF_BYTES and local_pdf_ok(path)
    except OSError:
        return False


def _write_provenance(pdf: Path, row: Dict[str, Any], *, storage: str, pages: Any, nbytes: int) -> None:
    payload = {
        "storage_url": storage,
        "docket_number": row.get("docket_number") or "",
        "docket_id": row.get("docket_id") or "",
        "docket_entry_number": row.get("docket_entry_number") or "",
        "recap_document_id": row.get("recap_document_id") or "",
        "hearing_type": row.get("hearing_type") or "",
        "pages": pages if pages not in (None, "") else "",
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "cost_usd": 0,
        "bytes": nbytes,
        "domain": row.get("domain") or "",
        "http_method": "GET",
        "posts": 0,
    }
    _provenance_path(pdf).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _api_get(session: requests.Session, url: str) -> Dict[str, Any]:
    """GET one CourtListener URL. Sleeps through 429s. Never POST."""
    for _attempt in range(30):
        time.sleep(_API_INTERVAL_S)
        resp = session.get(url, timeout=120, allow_redirects=False)
        if resp.status_code in {301, 302, 303, 307, 308} or resp.is_redirect:
            raise RuntimeError("redirect refused")
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "60")) + 2
            print(f"rate limit, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if resp.status_code == 401:
            raise SystemExit("CourtListener returned 401")
        resp.raise_for_status()
        return resp.json()
    raise SystemExit("rate limit persisted; re-run to resume")


def fetch_free_now() -> int:
    """Download every FREE_NOW row from CourtListener storage. Never buys.

    PDFs land in data/collected/recap/transcripts/<domain>/. A row that is not
    free at pull time is skipped and logged. PACER credentials are removed
    from this process before any request.
    """
    import os
    import shutil

    from pull_guard import excluded_row_reason, read_storage_pdf, storage_url

    os.environ.pop("PACER_USERNAME", None)
    os.environ.pop("PACER_PASSWORD", None)
    if os.environ.get("PACER_USERNAME") or os.environ.get("PACER_PASSWORD"):
        raise SystemExit("Refusing to run with PACER credentials set")

    if not MANIFEST.is_file():
        raise SystemExit(f"Manifest not found: {MANIFEST}")
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    skipped = [row for row in rows if excluded_row_reason(row)]
    queued_removed = sum(1 for row in skipped if (row.get("prior_status") or "") == "FREE_NOW")
    targets = [
        row
        for row in rows
        if (row.get("status") or "") in {"FREE_NOW", "COLLECTED"}
        and (row.get("recap_document_id") or "").strip()
        and not excluded_row_reason(row)
    ]
    FREE_ROOT.mkdir(parents=True, exist_ok=True)
    ledger_path = FREE_ROOT / "pull_ledger.csv"
    ledger_fields = [
        "docket_number",
        "docket_id",
        "recap_document_id",
        "domain",
        "hearing_type",
        "pages",
        "estimate_usd",
        "actual_usd",
        "outcome",
        "http_method",
        "posts",
        "running_spent_usd",
        "running_records",
    ]
    log: Dict[str, Dict[str, Any]] = {}

    def flush() -> None:
        _write_csv(MANIFEST, MANIFEST_FIELDS, rows)
        with ledger_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ledger_fields, extrasaction="ignore")
            writer.writeheader()
            spent_rows = 0
            for item in log.values():
                spent_rows += 1
                item["running_records"] = spent_rows
                item["running_spent_usd"] = "0.00"
                item["posts"] = 0
                writer.writerow(item)

    session = requests.Session()
    session.headers["Authorization"] = f"Token {_token()}"
    session.headers["User-Agent"] = "CaseNoesis free-transcript-pull"
    print(
        f"FREE_NOW rows: {len(targets)}. Skipping {queued_removed} queued downloads "
        f"marked DUPLICATE or NON_CRIMINAL. Saving under {FREE_ROOT}. No PACER, no POST.",
        file=sys.stderr,
    )
    for index, row in enumerate(targets, start=1):
        doc_id = str(row.get("recap_document_id"))
        dest = _saved_pdf(row)
        label = f"[{index}/{len(targets)}] {row.get('domain')} {row.get('docket_number')} entry {row.get('docket_entry_number')}"
        if shutil.disk_usage(FREE_ROOT).free < 2 * 1024 ** 3 and not _pdf_ready(dest):
            log[doc_id] = {
                "docket_number": row.get("docket_number") or "",
                "docket_id": row.get("docket_id") or "",
                "recap_document_id": doc_id,
                "domain": row.get("domain") or "",
                "hearing_type": row.get("hearing_type") or "",
                "pages": row.get("page_count") or "",
                "estimate_usd": "0.00",
                "actual_usd": "0.00",
                "outcome": "failed",
                "http_method": "none",
                "posts": 0,
            }
            print(f"{label} failed: less than 2GB free disk", file=sys.stderr)
            flush()
            return 1
        if _pdf_ready(dest) and _provenance_path(dest).is_file():
            row["status"] = "COLLECTED"
            pages = row.get("page_count") or ""
            log[doc_id] = {
                "docket_number": row.get("docket_number") or "",
                "docket_id": row.get("docket_id") or "",
                "recap_document_id": doc_id,
                "domain": row.get("domain") or "",
                "hearing_type": row.get("hearing_type") or "",
                "pages": pages,
                "estimate_usd": "0.00",
                "actual_usd": "0.00",
                "outcome": "downloaded",
                "http_method": "GET",
                "posts": 0,
            }
            print(f"{label} already on disk", file=sys.stderr)
            continue
        try:
            fresh = _api_get(session, f"https://www.courtlistener.com/api/rest/v4/recap-documents/{doc_id}/")
        except (requests.RequestException, RuntimeError, SystemExit) as exc:
            if isinstance(exc, SystemExit):
                flush()
                raise
            log[doc_id] = {
                "docket_number": row.get("docket_number") or "",
                "docket_id": row.get("docket_id") or "",
                "recap_document_id": doc_id,
                "domain": row.get("domain") or "",
                "hearing_type": row.get("hearing_type") or "",
                "pages": row.get("page_count") or "",
                "estimate_usd": "0.00",
                "actual_usd": "0.00",
                "outcome": "failed",
                "http_method": "GET",
                "posts": 0,
            }
            print(f"{label} failed: {type(exc).__name__}", file=sys.stderr)
            flush()
            continue
        available = bool(fresh.get("is_available") and fresh.get("filepath_local"))
        pages = fresh.get("page_count") if str(fresh.get("page_count") or "").isdigit() or isinstance(fresh.get("page_count"), int) else row.get("page_count") or ""
        if isinstance(pages, int):
            pages = str(pages)
        base = {
            "docket_number": row.get("docket_number") or "",
            "docket_id": row.get("docket_id") or "",
            "recap_document_id": doc_id,
            "domain": row.get("domain") or "",
            "hearing_type": row.get("hearing_type") or "",
            "pages": pages,
            "estimate_usd": "0.00",
            "actual_usd": "0.00",
            "http_method": "GET",
            "posts": 0,
        }
        if not available:
            base["outcome"] = "skipped_not_free"
            log[doc_id] = base
            print(f"{label} skipped: not free", file=sys.stderr)
            flush()
            continue
        def storage_get(url: str, **kwargs: Any) -> requests.Response:
            kwargs["allow_redirects"] = False
            kwargs.setdefault("timeout", 180)
            last = None
            for _try in range(8):
                last = session.get(url, **kwargs)
                if last.status_code == 429:
                    wait = int(last.headers.get("Retry-After", "30")) + 2
                    print(f"storage rate limit, sleeping {wait}s", file=sys.stderr)
                    time.sleep(wait)
                    continue
                return last
            return last

        try:
            if not _pdf_ready(dest):
                content = read_storage_pdf(storage_get, fresh["filepath_local"])
                if len(content) < _MIN_PDF_BYTES or not content.startswith(b"%PDF"):
                    raise ValueError("pdf too small")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            nbytes = dest.stat().st_size
            storage = storage_url(str(fresh["filepath_local"]))
            _write_provenance(pdf=dest, row=row, storage=storage, pages=pages, nbytes=nbytes)
        except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
            base["outcome"] = "failed"
            log[doc_id] = base
            print(f"{label} failed: {type(exc).__name__}", file=sys.stderr)
            flush()
            continue
        if str(pages).isdigit():
            row["page_count"] = str(pages)
        row["status"] = "COLLECTED"
        row["is_available"] = "True"
        row["estimated_cost_usd"] = "0.00"
        base["outcome"] = "downloaded"
        log[doc_id] = base
        print(f"{label} downloaded {pages} pages", file=sys.stderr)
        flush()
    flush()
    counts: Dict[str, int] = {}
    for item in log.values():
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    print(
        "FREE PULL DONE",
        f"downloaded={counts.get('downloaded', 0)}",
        f"skipped_not_free={counts.get('skipped_not_free', 0)}",
        f"failed={counts.get('failed', 0)}",
        "spent=0.00 posts=0",
        file=sys.stderr,
    )
    return 0


def fetch_approved(args: argparse.Namespace) -> int:
    """Dry run unless --download. Purchases need --charge-pacer and --max-spend.

    Only rows whose approved column equals --approval-tag are eligible.
    FREE_NOW rows are saved before any BUYABLE_LATER row. Buying stops at
    --max-records or --max-spend, whichever comes first.
    """
    from pull_guard import PullBudget, plan_transcript_pull, run_transcript_pull

    path = Path(args.manifest)
    if not path.is_file():
        raise SystemExit(f"Manifest not found: {path}")
    tag = getattr(args, "approval_tag", None) or "pilot"
    max_records = getattr(args, "max_records", None)
    if args.charge_pacer and not args.download:
        raise SystemExit("Refusing PACER charge without --download")
    if args.charge_pacer and args.max_spend is None:
        raise SystemExit("Refusing PACER charge: pass --max-spend (dollars, total cap)")
    if args.charge_pacer and (not args.pacer_username or not args.pacer_password):
        raise SystemExit("Refusing PACER charge: PACER username and password are required")

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    plan = plan_transcript_pull(
        rows,
        approval_tag=tag,
        max_spend=args.max_spend,
        max_records=max_records,
    )
    planned = plan["planned"]
    print(f"Approval tag {tag}: {len(planned)} planned, {len(plan['refused'])} refused")
    for item in plan["refused"]:
        print(f"  refuse {item['recap_document_id']}: {item['reason']}")
    free_n = sum(1 for row in planned if row["_mode"] == "free")
    buy_n = sum(1 for row in planned if row["_mode"] == "buy")
    print(f"Plan: {free_n} free, {buy_n} purchases, estimated ${plan['budget'].spent:.2f}")
    if not args.download:
        print("Dry run. No downloads and no PACER calls. Pass --download to fetch free rows.")
        return 0
    if args.charge_pacer is False and buy_n:
        print("Buys left unpurchased. Pass --charge-pacer with --max-spend to buy.")

    from cases2records import CourtListenerClient

    class _Client:
        def __init__(self, inner: CourtListenerClient) -> None:
            self.inner = inner

        def session_get(self, url: str, **kwargs: Any) -> Any:
            return inner_get(self.inner, url, **kwargs)

        def get_recap_document(self, doc_id: int) -> Dict[str, Any]:
            return self.inner.get_recap_document(doc_id)

        def fetch_missing_pdf(self, doc_id: int, *, pacer_username: str, pacer_password: str) -> Dict[str, Any]:
            return self.inner.fetch_missing_pdf(
                doc_id, pacer_username=pacer_username, pacer_password=pacer_password
            )

        def wait_for_recap_document(self, doc_id: int) -> Dict[str, Any]:
            return self.inner.wait_for_recap_document(doc_id)

    def dest_for(row: Dict[str, Any]) -> Path:
        domain = (row.get("domain") or "other").strip().lower()
        if domain not in {"csea", "fraud", "trafficking", "cyber"}:
            domain = "other"
        filename = (
            f"{str(row.get('docket_number') or 'docket').replace(':', '-')}"
            f"_entry{row.get('docket_entry_number', '')}_{row['recap_document_id']}.pdf"
        )
        return OUT_DIR / domain / filename

    client = CourtListenerClient(_token(), min_interval=6.5)
    budget = PullBudget(args.max_spend if args.max_spend is not None else 0.0, max_records)
    if not args.charge_pacer:
        budget.max_spend = 0.0
    done = run_transcript_pull(
        [row for row in planned if row["_mode"] == "free" or args.charge_pacer],
        client=_Client(client),
        budget=budget,
        ledger_path=OUT_DIR / "pull_ledger.csv",
        dest_for=dest_for,
        pacer_username=args.pacer_username or "",
        pacer_password=args.pacer_password or "",
    )
    by_id = {str(row.get("recap_document_id")): row for row in done}
    for row in rows:
        updated = by_id.get(str(row.get("recap_document_id")))
        if updated and updated.get("status") == "COLLECTED":
            row["status"] = "COLLECTED"
    _write_csv(path, MANIFEST_FIELDS, rows)
    print(f"Collected {len(done)}. Spent ${budget.spent:.2f}. Records {budget.records}.")
    return 0


def inner_get(client: Any, url: str, **kwargs: Any) -> Any:
    return client._session.get(url, **kwargs)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Transcript sweep and approved fetch. Sweep spends $0.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sweep", help="Metadata sweep of held dockets. No downloads, no PACER.")
    fetch = sub.add_parser("fetch", help="Act on approved manifest rows. Defaults to dry run.")
    fetch.add_argument("--manifest", type=Path, default=MANIFEST)
    fetch.add_argument("--approval-tag", default="pilot", help="Only rows with approved equal to this tag")
    fetch.add_argument("--download", action="store_true", help="Download approved FREE_NOW rows")
    fetch.add_argument("--charge-pacer", action="store_true", help="Buy approved BUYABLE_LATER rows")
    fetch.add_argument("--max-records", type=int, default=None, help="Stop after this many transcripts, free or paid")
    fetch.add_argument("--max-spend", type=float, default=None, help="Total PACER cap in dollars")
    fetch.add_argument("--pacer-username", default="")
    fetch.add_argument("--pacer-password", default="")
    sub.add_parser("fetch-free", help="Download every FREE_NOW row. Never buys and never POSTs.")
    args = parser.parse_args(argv)
    if args.command == "sweep":
        return sweep()
    import os

    if args.command == "fetch-free":
        os.environ.pop("PACER_USERNAME", None)
        os.environ.pop("PACER_PASSWORD", None)
        return fetch_free_now()

    from cases2records import _load_dotenv

    _load_dotenv()
    args.pacer_username = args.pacer_username or os.environ.get("PACER_USERNAME", "")
    args.pacer_password = args.pacer_password or os.environ.get("PACER_PASSWORD", "")
    return fetch_approved(args)


if __name__ == "__main__":
    raise SystemExit(main())
