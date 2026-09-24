#!/usr/bin/env python3
"""Join a fraud press release to free RECAP PDFs when the release names a case.

A storage.courtlistener.com path is
``recap/gov.uscourts.{court}.{pacer_case_id}/...pdf``.
Press text has the docket number (``22-cr-20173``), not that PACER case id, so
the URL cannot be guessed. This script:

  1. extracts docket number + district from the local press file (no API)
  2. spends one CourtListener lookup on that exact docket
  3. downloads only free, already-in-RECAP filings from storage
     (those downloads do not spend the lookup quota and do not buy PACER)
  4. keeps a filing only when the description and the first pages look like
     an indictment, plea, factual basis, or sentencing memo

  python3 collector/press_to_recap.py extract
  python3 collector/press_to_recap.py pull --max-calls 200

NHSR #8252. Observed records only. pacer_purchases stays 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

NHSR = "UMass HRPO NHSR #8252 (16 Sep 2026)"
STUDY = REPO / "data" / "collected" / "press_releases" / "fraud" / "study_records.jsonl"
RECAP_DIR = REPO / "data" / "collected" / "recap" / "fraud"
PDF_DIR = RECAP_DIR / "from_press"
QUEUE = RECAP_DIR / "press_docket_queue.jsonl"
MANIFEST = RECAP_DIR / "from_press.jsonl"
TRIED = RECAP_DIR / "from_press_tried.jsonl"
STATUS = RECAP_DIR / "from_press_status.json"
PRIOR_LOG = RECAP_DIR / "fraud_study.jsonl"

MAX_DOCS = 4
MIN_PDF_BYTES = 8000
MIN_TEXT_CHARS = 1200

# USAO site slugs and compact reporter cites (SDNY, S.D.N.Y.) flip to PACER ids.
_SINGLE = {
    "ak": "akd",
    "az": "azd",
    "co": "cod",
    "ct": "ctd",
    "dc": "dcd",
    "de": "ded",
    "gu": "gud",
    "hi": "hid",
    "id": "idd",
    "ks": "ksd",
    "ma": "mad",
    "md": "mdd",
    "me": "med",
    "mn": "mnd",
    "mp": "nmid",
    "mt": "mtd",
    "nd": "ndd",
    "ne": "ned",
    "nh": "nhd",
    "nj": "njd",
    "nm": "nmd",
    "nv": "nvd",
    "or": "ord",
    "pr": "prd",
    "ri": "rid",
    "sc": "scd",
    "sd": "sdd",
    "ut": "utd",
    "vi": "vid",
    "vt": "vtd",
    "wy": "wyd",
}
_STATE = {
    "alabama": "al",
    "alaska": "ak",
    "arizona": "az",
    "arkansas": "ar",
    "california": "ca",
    "colorado": "co",
    "connecticut": "ct",
    "delaware": "de",
    "florida": "fl",
    "georgia": "ga",
    "guam": "gu",
    "hawaii": "hi",
    "idaho": "id",
    "illinois": "il",
    "indiana": "in",
    "iowa": "ia",
    "kansas": "ks",
    "kentucky": "ky",
    "louisiana": "la",
    "maine": "me",
    "maryland": "md",
    "massachusetts": "ma",
    "michigan": "mi",
    "minnesota": "mn",
    "mississippi": "ms",
    "missouri": "mo",
    "montana": "mt",
    "nebraska": "ne",
    "nevada": "nv",
    "new hampshire": "nh",
    "new jersey": "nj",
    "new mexico": "nm",
    "new york": "ny",
    "north carolina": "nc",
    "north dakota": "nd",
    "ohio": "oh",
    "oklahoma": "ok",
    "oregon": "or",
    "pennsylvania": "pa",
    "puerto rico": "pr",
    "rhode island": "ri",
    "south carolina": "sc",
    "south dakota": "sd",
    "tennessee": "tn",
    "texas": "tx",
    "utah": "ut",
    "vermont": "vt",
    "virgin islands": "vi",
    "virginia": "va",
    "washington": "wa",
    "west virginia": "wv",
    "wisconsin": "wi",
    "wyoming": "wy",
}
_DIR = {
    "northern": "n",
    "southern": "s",
    "eastern": "e",
    "western": "w",
    "central": "c",
    "middle": "m",
}
_LONG = {"cal": "ca", "fla": "fl", "tex": "tx", "ill": "il", "tenn": "tn", "okla": "ok"}

USAO_RE = re.compile(r"justice\.gov/usao-([a-z0-9]+)/", re.I)
FULL_DOCKET_RE = re.compile(
    r"\b(\d{1,2})\s*:\s*(\d{2})\s*-\s*(cr|mj)\s*-\s*(\d{2,6})\b",
    re.I,
)
BARE_DOCKET_RE = re.compile(r"\b(\d{2})\s*-\s*(cr|mj)\s*-\s*(\d{2,6})\b", re.I)
DISTRICT_RE = re.compile(
    r"\b(?:(northern|southern|eastern|western|central|middle)\s+)?"
    r"district\s+of\s+([a-z]+(?:\s+[a-z]+)?)",
    re.I,
)
COMPACT_RE = re.compile(
    r"\b([NSEWCM])\.?\s*D\.?\s*\.?\s*([A-Za-z]{2,4})\.?\b",
)
PDF_RE = re.compile(r"https?://[^\s\"'<>]+\.pdf", re.I)
CHARGING_RE = re.compile(
    r"^\s*(?:\(\s*[A-Za-z0-9]+\s*\)\s*)?"
    r"(?:sealed\s+|redacted\s+|first\s+|second\s+|third\s+|fourth\s+|superseding\s+)*"
    r"(indictment|criminal complaint|plea agreement|sentencing memorandum|"
    r"factual basis|factual proffer|statement of offense|affidavit)\b",
    re.I,
)
WRAPPER_RE = re.compile(
    r"^\s*(acknowledgment|motion|order|notice|minute|waiver|summons|response|reply|"
    r"letter|stipulation|judgment|memorandum in|amicus)\b",
    re.I,
)
MECHANICS_RE = re.compile(
    r"scheme to defraud|wire fraud|mail fraud|bank fraud|\bcounts?\b|"
    r"the grand jury|plea agreement|sentencing|factual (?:basis|proffer)|"
    r"criminal complaint|defendant",
    re.I,
)
SHEET_RE = re.compile(r"\bminute entry\b|\bdocket sheet\b", re.I)
RANK = {
    "indictment": 1,
    "criminal complaint": 2,
    "factual basis": 3,
    "factual proffer": 3,
    "statement of offense": 3,
    "plea agreement": 4,
    "sentencing memorandum": 5,
    "affidavit": 6,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def office_to_court(office: str) -> str | None:
    """``sdny`` / ``sdfl`` / ``nj`` → PACER court id (``nysd`` / ``flsd`` / ``njd``)."""
    token = re.sub(r"[^a-z]", "", (office or "").lower())
    if not token:
        return None
    if token in _SINGLE:
        return _SINGLE[token]
    match = re.fullmatch(r"([nsewcm])d([a-z]{2,4})", token)
    if not match:
        return None
    state = _LONG.get(match.group(2), match.group(2))
    if len(state) != 2:
        return None
    return f"{state}{match.group(1)}d"


def court_from_url(url: str) -> str | None:
    match = USAO_RE.search(url or "")
    if not match:
        return None
    return office_to_court(match.group(1))


def _court_from_text(text: str, anchor: int) -> str | None:
    window_start = max(0, anchor - 500)
    window = text[window_start : anchor + 500]
    best: tuple[int, str] | None = None
    for match in DISTRICT_RE.finditer(window):
        state_name = match.group(2).lower()
        if state_name == "columbia":
            court = "dcd"
        else:
            abbr = _STATE.get(state_name)
            if not abbr:
                continue
            direction = _DIR.get((match.group(1) or "").lower())
            if direction:
                court = f"{abbr}{direction}d"
            elif abbr in _SINGLE:
                court = _SINGLE[abbr]
            else:
                continue
        distance = abs((window_start + match.start()) - anchor)
        if best is None or distance < best[0]:
            best = (distance, court)
    for match in COMPACT_RE.finditer(window):
        court = office_to_court(match.group(1) + "d" + match.group(2))
        if not court:
            continue
        distance = abs((window_start + match.start()) - anchor)
        if best is None or distance < best[0]:
            best = (distance, court)
    return best[1] if best else None


def _dockets(text: str) -> list[tuple[str, str, int]]:
    """Return (core, kind, span_start). Full ``1:yy-cr-n`` wins over a bare cite."""
    found: list[tuple[str, str, int]] = []
    covered: list[tuple[int, int]] = []
    for match in FULL_DOCKET_RE.finditer(text):
        core = f"{match.group(2)}-{match.group(3).lower()}-{int(match.group(4))}"
        found.append((core, match.group(3).lower(), match.start()))
        covered.append(match.span())
    for match in BARE_DOCKET_RE.finditer(text):
        if any(start <= match.start() < end for start, end in covered):
            continue
        core = f"{match.group(1)}-{match.group(2).lower()}-{int(match.group(3))}"
        found.append((core, match.group(2).lower(), match.start()))
    # Prefer criminal complaints over magistrate numbers when both appear.
    found.sort(key=lambda row: (row[1] != "cr", row[2]))
    seen: set[str] = set()
    out: list[tuple[str, str, int]] = []
    for row in found:
        if row[0] in seen:
            continue
        seen.add(row[0])
        out.append(row)
        if len(out) >= 3:
            break
    return out


def extract_queue(src: Path = STUDY) -> dict:
    grouped: dict[tuple[str, str], dict] = {}
    rows = 0
    with_docket = 0
    linked_pdfs = 0
    for line in src.open(encoding="utf-8", errors="replace"):
        if not line.strip():
            continue
        rows += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        title = str(rec.get("title") or "")
        body = str(rec.get("body") or "")
        url = str(rec.get("source_url") or "")
        blob = f"{title}\n{body}"
        dockets = _dockets(blob)
        if dockets:
            with_docket += 1
        url_court = court_from_url(url)
        for core, kind, anchor in dockets:
            court = url_court or _court_from_text(blob, anchor)
            if not court:
                continue
            key = (court, core)
            slot = grouped.get(key)
            if slot is None:
                grouped[key] = {
                    "nhsr": NHSR,
                    "court": court,
                    "docket_core": core,
                    "docket_kind": kind,
                    "press_url": url,
                    "press_title": title[:240],
                    "press_date": str(rec.get("pub_date") or "")[:10],
                    "press_urls": [url] if url else [],
                }
            elif url and url not in slot["press_urls"] and len(slot["press_urls"]) < 5:
                slot["press_urls"].append(url)
        linked_pdfs += len(PDF_RE.findall(blob))
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE.open("w", encoding="utf-8") as handle:
        for row in grouped.values():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "updated": _now(),
        "rows_read": rows,
        "rows_with_docket": with_docket,
        "resolvable_dockets": len(grouped),
        "pdf_links_seen": linked_pdfs,
        "queue": str(QUEUE),
    }
    print(
        f"extract rows={rows} with_docket={with_docket} "
        f"resolvable={len(grouped)} pdf_links={linked_pdfs}",
        file=sys.stderr,
    )
    return summary


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _seen_docs() -> set[str]:
    seen: set[str] = set()
    for path in (MANIFEST, PRIOR_LOG):
        for rec in _load_jsonl(path):
            if rec.get("document_id"):
                seen.add(str(rec["document_id"]))
    return seen


def _rank(desc: str) -> int:
    match = CHARGING_RE.search(desc or "")
    if not match:
        return 99
    return RANK.get(match.group(1).lower(), 50)


def _docket_hit(returned: str, core: str) -> bool:
    norm = re.sub(r"\s+", "", (returned or "").lower())
    return re.search(rf"(?:^|[^0-9]){re.escape(core)}(?:[^0-9]|$)", norm) is not None


def _path_court(item: dict) -> str:
    blob = f"{item.get('filepath_local') or ''} {item.get('absolute_url') or ''}".lower()
    match = re.search(r"gov\.uscourts\.([a-z0-9]+)\.", blob)
    return match.group(1) if match else ""


def _queue_rank(seed: dict) -> tuple[int, int]:
    """Older completed cases are more often already in RECAP than a 2026 filing."""
    core = str(seed.get("docket_core") or "99-cr-0")
    yy = int(core[:2]) if core[:2].isdigit() else 99
    year = 1900 + yy if yy >= 90 else 2000 + yy
    if 2013 <= year <= 2025:
        return (0, -year)
    return (1, -year)


def _worthy_text(pdf: Path) -> str:
    """Return 'pass', 'fail', or 'skipped' from the first pages. Does not store the text."""
    try:
        proc = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "3", "-layout", str(pdf), "-"],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "skipped"
    if proc.returncode != 0:
        return "skipped"
    text = proc.stdout.decode("utf-8", errors="replace")
    if len(text) < MIN_TEXT_CHARS:
        return "fail"
    if SHEET_RE.search(text) and not MECHANICS_RE.search(text):
        return "fail"
    if not MECHANICS_RE.search(text):
        return "fail"
    return "pass"


def _public_host_ok(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    if "pacer" in host or host.startswith("ecf.") or ".ecf." in host:
        return False
    return host.endswith("justice.gov") or host.endswith("uscourts.gov") or host.endswith("courtlistener.com")


def pull_linked_pdfs() -> int:
    """Download PDFs already linked from press text. No CourtListener lookup."""
    import requests

    kept = 0
    seen_urls: set[str] = set()
    for rec in _load_jsonl(MANIFEST):
        if rec.get("download_url"):
            seen_urls.add(rec["download_url"])
    if not STUDY.is_file():
        return 0
    for line in STUDY.open(encoding="utf-8", errors="replace"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        blob = f"{rec.get('title') or ''}\n{rec.get('body') or ''}"
        for url in PDF_RE.findall(blob):
            url = url.rstrip(".,;)")
            if url in seen_urls or not _public_host_ok(url):
                continue
            seen_urls.add(url)
            digest = hashlib.sha256(url.encode()).hexdigest()[:16]
            dest = PDF_DIR / f"linked_{digest}.pdf"
            if not (dest.is_file() and dest.stat().st_size > 1000):
                try:
                    resp = requests.get(
                        url,
                        headers={"User-Agent": "CaseNoesis-Collector/1.0 (research; NHSR 8252)"},
                        timeout=45,
                    )
                    resp.raise_for_status()
                except requests.RequestException:
                    continue
                data = resp.content
                if not data.startswith(b"%PDF") or len(data) < MIN_PDF_BYTES:
                    continue
                PDF_DIR.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            verdict = _worthy_text(dest)
            if verdict == "fail":
                dest.unlink(missing_ok=True)
                continue
            _append(
                MANIFEST,
                {
                    "nhsr": NHSR,
                    "observed": True,
                    "inferred": False,
                    "cost": "free",
                    "pacer_purchases": 0,
                    "via": "press_pdf_link",
                    "press_url": rec.get("source_url"),
                    "press_title": str(rec.get("title") or "")[:240],
                    "download_url": url,
                    "pdf": str(dest),
                    "bytes": dest.stat().st_size,
                    "text_check": verdict,
                },
            )
            kept += 1
            print(f"  linked pdf {kept} {url[:90]}", file=sys.stderr)
    return kept


def pull(max_calls: int) -> None:
    import court_records
    import run_source_bulk as bulk

    if not QUEUE.is_file():
        extract_queue()
    court_records.load_token_from_env_files([REPO / ".env", REPO.parent / "CaseLinker" / ".env"])
    court_records.MIN_DELAY = 3.5
    linked = pull_linked_pdfs()
    queue = sorted(_load_jsonl(QUEUE), key=_queue_rank)
    tried = {f"{r.get('court')}|{r.get('docket_core')}" for r in _load_jsonl(TRIED)}
    seen_docs = _seen_docs()
    calls = 0
    kept = sum(1 for r in _load_jsonl(MANIFEST) if r.get("document_id"))
    misses = 0

    def status(**extra: object) -> None:
        _write_json(
            STATUS,
            {
                "updated": _now(),
                "nhsr": NHSR,
                "calls": calls,
                "kept_recap": kept,
                "linked_pdfs": linked,
                "misses": misses,
                "pacer_purchases": 0,
                **extra,
            },
        )

    for seed in queue:
        if calls >= max_calls:
            break
        court = seed.get("court") or ""
        core = seed.get("docket_core") or ""
        key = f"{court}|{core}"
        if not court or not core or key in tried:
            continue
        # Quoted docket plus the filing type. Search rows have no court_id;
        # the district is checked on the PDF path instead.
        query = (
            f'"{core}" AND (indictment OR "plea agreement" OR '
            f'"sentencing memorandum" OR "factual basis" OR "criminal complaint")'
        )
        gap = bulk._wait_for_user_quota(court_records)
        resp = bulk._cl_get(
            court_records,
            court_records.COURTLISTENER_SEARCH,
            {"q": query, "type": "rd", "court": court},
            gap,
        )
        calls += 1
        _append(
            TRIED,
            {"court": court, "docket_core": core, "press_url": seed.get("press_url"), "at": _now()},
        )
        tried.add(key)
        if resp is None:
            continue
        try:
            payload = resp.json()
        except ValueError:
            continue
        raw = [item for item in (payload.get("results") or []) if isinstance(item, dict)]
        hits = []
        for item in raw:
            path_court = _path_court(item)
            if path_court and path_court != court:
                continue
            returned = str(item.get("docketNumber") or "")
            if returned and not _docket_hit(returned, core):
                continue
            hits.append(item)
        hits.sort(key=lambda item: _rank(str(item.get("description") or "")))
        saved = 0
        skipped = Counter()
        sample = ""
        for item in hits:
            if saved >= MAX_DOCS:
                break
            desc = str(item.get("description") or item.get("short_description") or "")
            if WRAPPER_RE.search(desc) or not CHARGING_RE.search(desc):
                skipped["gate"] += 1
                if not sample:
                    sample = desc[:80].replace("\n", " ")
                continue
            doc_id = str(item.get("id") or "")
            fp = item.get("filepath_local")
            if not doc_id or doc_id in seen_docs or not item.get("is_available") or not fp:
                skipped["unavailable"] += 1
                if not sample:
                    sample = desc[:80].replace("\n", " ")
                continue
            if "gov.uscourts." not in str(fp):
                skipped["path"] += 1
                continue
            dest = PDF_DIR / f"{doc_id}.pdf"
            if not (dest.is_file() and dest.stat().st_size > 1000):
                result = court_records.download_free_pdf(
                    f"https://storage.courtlistener.com/{str(fp).lstrip('/')}",
                    dest,
                )
                if not result.get("ok") or int(result.get("bytes") or 0) < MIN_PDF_BYTES:
                    dest.unlink(missing_ok=True)
                    skipped["thin"] += 1
                    continue
            verdict = _worthy_text(dest)
            if verdict == "fail":
                dest.unlink(missing_ok=True)
                skipped["text"] += 1
                continue
            seen_docs.add(doc_id)
            saved += 1
            kept += 1
            abs_url = item.get("absolute_url") or ""
            if abs_url and not str(abs_url).startswith("http"):
                abs_url = f"https://www.courtlistener.com{abs_url}"
            _append(
                MANIFEST,
                {
                    "nhsr": NHSR,
                    "observed": True,
                    "inferred": False,
                    "cost": "free",
                    "pacer_purchases": 0,
                    "via": "docket_lookup",
                    "press_url": seed.get("press_url"),
                    "press_title": seed.get("press_title"),
                    "press_date": seed.get("press_date"),
                    "court": court,
                    "docket_number": item.get("docketNumber") or core,
                    "docket_id": item.get("docket_id"),
                    "document_id": doc_id,
                    "document_description": desc[:300],
                    "entry_date": item.get("entry_date_filed") or item.get("dateFiled"),
                    "page_count": item.get("page_count"),
                    "absolute_url": abs_url,
                    "pdf": str(dest),
                    "bytes": dest.stat().st_size,
                    "text_check": verdict,
                },
            )
            print(f"  join {kept} {court} {core} {desc[:70]}", file=sys.stderr)
        if saved == 0:
            misses += 1
        if calls % 5 == 0:
            status()
        print(
            f"  lookup {calls} {court} {core} raw={len(raw)} hits={len(hits)} "
            f"saved={saved} kept={kept} skip={dict(skipped)} {sample}",
            file=sys.stderr,
        )
    status(mode="finished", finished=_now())
    print(f"pull done calls={calls} kept={kept} misses={misses} linked={linked}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("extract", "pull"))
    parser.add_argument("--max-calls", type=int, default=200)
    args = parser.parse_args()
    if args.phase == "extract":
        extract_queue()
    else:
        pull(args.max_calls)


if __name__ == "__main__":
    main()
