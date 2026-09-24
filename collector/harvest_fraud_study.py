#!/usr/bin/env python3
"""Year-stratified criminal-fraud harvest for the mechanics-of-exploitation study.

Press  -> data/collected/press_releases/fraud/study_records.jsonl
Court  -> data/collected/recap/fraud/  (free RECAP only; never PACER)
State  -> data/collected/press_releases/fraud/state_records.jsonl

NHSR #8252. Public pages and free RECAP. Does not auto-ingest.

  python3 collector/harvest_fraud_study.py --phase press
  python3 collector/harvest_fraud_study.py --phase court
  python3 collector/harvest_fraud_study.py --phase state
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import harvest_doj_press as h  # noqa: E402
import resolve_press_urls as resolver  # noqa: E402

NHSR = "UMass HRPO NHSR #8252 (16 Sep 2026)"
PRESS_DIR = REPO / "data" / "collected" / "press_releases" / "fraud"
RECAP_DIR = REPO / "data" / "collected" / "recap" / "fraud"
BULK_RECORDS = REPO / "data" / "collected" / "press_releases" / "bulk" / "records"
LOOKUP = REPO / "data" / "collected" / "press_releases" / "press_lookup.jsonl"
STUDY = PRESS_DIR / "study_records.jsonl"
STATE_OUT = PRESS_DIR / "state_records.jsonl"
PRESS_STATUS = PRESS_DIR / "study_status.json"
EJI_DIR = PRESS_DIR / "eji"
COURT_LOG = RECAP_DIR / "fraud_study.jsonl"
COURT_STATUS = RECAP_DIR / "fraud_study_status.json"

YEAR_MIN, YEAR_MAX = 2000, 2026
# 0 = keep every criminal-fraud prosecution. Diversity is the term list, not a yearly quota.
YEAR_CAP = 0
COURT_YEAR_CAP = 40

BUCKET_CAP = {
    "elder": 180,
    "online": 180,
    "cyber": 220,
    "investment": 150,
    "classic": 280,
    "other": 150,
}
BUCKET_RES: list[tuple[str, re.Pattern[str]]] = [
    ("elder", re.compile(r"elder|grandparent|senior(?:s)?\b.{0,40}fraud|fraud.{0,40}senior", re.I)),
    ("online", re.compile(r"romance|lottery|sweepstakes|gift card|tech support|online scam|internet fraud", re.I)),
    ("cyber", re.compile(
        r"business email|pig butcher|cryptocurren|bitcoin|phishing|identity theft|"
        r"\bBEC\b|computer fraud|account takeover|sim swap",
        re.I,
    )),
    ("investment", re.compile(r"investment fraud|ponzi|securities fraud|pyramid scheme", re.I)),
    ("classic", re.compile(r"wire fraud|mail fraud|bank fraud", re.I)),
    ("other", re.compile(r"health care fraud|healthcare fraud|tax fraud|mortgage fraud|insurance fraud", re.I)),
]
REQUIRE_RE = re.compile(
    r"fraud|scam|embezzl|swindle|scheme to defraud|pig butcher|business email|"
    r"ponzi|phish|identity theft|defraud",
    re.I,
)
EXCLUDE_RE = re.compile(
    r"\b(?:scam alert|consumer alert|how to avoid|tips for (?:avoiding|spotting)|"
    r"awareness month|civil settlement|assurance of voluntary compliance)\b",
    re.I,
)
# Diversity terms first. The last two fill each year up to YEAR_CAP.
PRESS_TERMS: list[tuple[str, bool]] = [
    ("elder fraud", False),
    ("elder financial", False),
    ("grandparent scam", False),
    ("romance scam", False),
    ("romance fraud", False),
    ("lottery scam", False),
    ("business email compromise", False),
    ("pig butchering", False),
    ("cryptocurrency fraud", False),
    ("phishing", False),
    ("investment fraud", False),
    ("ponzi", False),
    ("securities fraud", False),
    ("wire fraud", False),
    ("mail fraud", False),
    ("bank fraud", False),
    ("identity theft", False),
    ("mortgage fraud", False),
    ("health care fraud", False),
    ("tech support", False),
    ("gift card", False),
    ("cryptocurrency", False),
    ("bitcoin", False),
    ("fraud scheme", True),
    ("fraud", True),
]
EJI_DOCS = [
    ("appendix-2025", "https://www.justice.gov/elderjustice/media/1414446/dl?inline="),
    ("appendix-2024", "https://www.justice.gov/elderjustice/media/1372226/dl?inline="),
    ("report-2023", "https://www.justice.gov/elderjustice/media/1319976/dl?inline="),
    ("report-2021", "https://www.justice.gov/elderjustice/media/1179021/dl?inline="),
    ("report-2025", "https://www.justice.gov/elderjustice/media/1416301/dl"),
]
COURT_QUERIES = [
    '"wire fraud" AND (indictment OR "plea agreement" OR "sentencing memorandum")',
    '"mail fraud" AND (indictment OR "plea agreement" OR "sentencing memorandum")',
    '"elder fraud" AND (indictment OR "plea agreement" OR "criminal complaint")',
    '("romance scam" OR "romance fraud") AND (indictment OR "plea agreement")',
    '"business email compromise" AND (indictment OR "plea agreement" OR "criminal complaint")',
    '("cryptocurrency" OR "pig butchering") AND (indictment OR "plea agreement" OR "wire fraud")',
    '("investment fraud" OR ponzi) AND (indictment OR "plea agreement")',
    '"grandparent" AND (scam OR fraud) AND (indictment OR "plea agreement")',
    '"bank fraud" AND indictment',
]
FRAUD_LISTING_RE = re.compile(
    r"fraud|elder|scam|wire|romance|phish|ransom|crypto|ponzi",
    re.I,
)
CASE_SPLIT_RE = re.compile(r"U\s*\.?\s*S\s*\.?\s*v\s*\.?\s*", re.I)
NAME_RE = re.compile(r"^([A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+){0,4})")
DOCKET_RE = re.compile(
    r"\b(\d{1,2})\s*:\s*(\d{2})\s*-?\s*cr\s*-?\s*(\d{1,6})\b",
    re.I,
)
URL_RE = re.compile(r"https://www\.justice\.gov/[a-z0-9./_\-#%~]+", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(line)
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def _norm(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _year(pub: str | None) -> int | None:
    if not pub or len(pub) < 4 or not pub[:4].isdigit():
        return None
    year = int(pub[:4])
    if YEAR_MIN <= year <= YEAR_MAX:
        return year
    return None


def _bucket(title: str, body: str) -> str:
    blob = f"{title}\n{(body or '')[:1800]}"
    for name, rx in BUCKET_RES:
        if rx.search(blob):
            return name
    if REQUIRE_RE.search(blob):
        return "classic"
    return "other"


def _load_jsonl_urls(path: Path) -> set[str]:
    found: set[str] = set()
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = _norm(rec.get("source_url") or "")
        if url:
            found.add(url)
    return found


def _counts_from_study() -> tuple[Counter, dict[int, Counter]]:
    years: Counter = Counter()
    buckets: dict[int, Counter] = {}
    if not STUDY.is_file():
        return years, buckets
    for line in STUDY.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        year = _year(rec.get("pub_date"))
        if year is None:
            continue
        years[year] += 1
        buckets.setdefault(year, Counter())[rec.get("bucket") or "other"] += 1
    return years, buckets


def _should_keep(
    year: int,
    bucket: str,
    years: Counter,
    buckets: dict[int, Counter],
    *,
    filling: bool,
    force: bool = False,
) -> bool:
    """Keep the prosecution. YEAR_CAP 0 means no yearly ceiling."""
    del bucket, buckets, filling, force
    if YEAR_CAP and years[year] >= YEAR_CAP:
        return False
    return True


def _press_row(rec: dict) -> dict:
    return {
        "kind": "press",
        "domain": "fraud",
        "agency": rec.get("agency") or "",
        "title": rec.get("title") or "",
        "pub_date": rec.get("pub_date"),
        "source_url": rec.get("source_url"),
        "bucket": rec.get("bucket"),
        "stage": rec.get("stage"),
        "nhsr": NHSR,
    }


def _keep_press(
    rec: dict,
    years: Counter,
    buckets: dict[int, Counter],
    seen: set[str],
    *,
    filling: bool,
    force: bool = False,
) -> bool:
    url = _norm(rec.get("source_url") or "")
    year = _year(rec.get("pub_date"))
    if not url or url in seen or year is None:
        return False
    bucket = rec.get("bucket") or _bucket(rec.get("title") or "", rec.get("body") or "")
    rec["bucket"] = bucket
    rec["year"] = year
    if not _should_keep(year, bucket, years, buckets, filling=filling, force=force):
        return False
    seen.add(url)
    years[year] += 1
    buckets.setdefault(year, Counter())[bucket] += 1
    _append(STUDY, rec)
    _append(LOOKUP, _press_row(rec))
    return True


def _from_parts(*, source_id: str, agency: str, title: str, body: str, pub_date: str | None, url: str, stage: str) -> dict:
    return {
        "nhsr": NHSR,
        "observed": True,
        "inferred": False,
        "cost": "free",
        "pacer_purchases": 0,
        "kind": "press",
        "domain": "fraud",
        "source_id": source_id,
        "agency": agency,
        "title": title,
        "byline": "",
        "pub_date": pub_date,
        "source_url": url,
        "body": body,
        "mode": "resolved",
        "stage": stage,
        "bucket": _bucket(title, body),
    }


def seed_existing(seen: set[str], years: Counter, buckets: dict[int, Counter]) -> int:
    """Copy criminal-fraud rows already on disk into the study file. They count toward the yearly cap."""
    added = 0
    if not BULK_RECORDS.is_dir():
        return 0
    for path in sorted(BULK_RECORDS.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            domain = rec.get("domain")
            blob = f"{rec.get('title') or ''}\n{(rec.get('body') or '')[:2000]}"
            if domain not in {"fraud", "cyber"} or not REQUIRE_RE.search(blob):
                continue
            if h.classify_stage(rec.get("title") or "") == "other" and not re.search(
                r"\b(?:sentenc|plead|guilty|convict|indict|charg|arrest)",
                blob,
                re.I,
            ):
                continue
            row = _from_parts(
                source_id=rec.get("source_id") or path.stem,
                agency=rec.get("agency") or "",
                title=rec.get("title") or "",
                body=rec.get("body") or "",
                pub_date=rec.get("pub_date"),
                url=rec.get("source_url") or "",
                stage=rec.get("stage") or h.classify_stage(rec.get("title") or ""),
            )
            if _keep_press(row, years, buckets, seen, filling=True, force=True):
                added += 1
    return added


def _prosecution(title: str, body: str) -> bool:
    if EXCLUDE_RE.search(title) or h.NOISE_RE.search(title):
        return False
    blob = f"{title}\n{body[:1800]}"
    if not REQUIRE_RE.search(blob):
        return False
    stage = h.classify_stage(title)
    if stage == "other" and not re.search(r"\b(?:sentenc|plead|guilty|convict|indict|charg|arrest)", blob, re.I):
        return False
    return True


def _record_from_api(raw: dict) -> dict | None:
    title = (raw.get("title") or "").strip()
    url = h.canonical_url(raw.get("url") or "")
    pub = resolver._epoch_to_date(raw.get("date"))
    body = resolver.clean_doj_api_body(raw.get("body") or "")
    if len(body) < h.MIN_BODY_CHARS or not url or not _prosecution(title, body):
        return None
    components = raw.get("component") or []
    agency = ""
    if components and isinstance(components[0], dict):
        agency = components[0].get("name") or ""
    return _from_parts(
        source_id="doj_fraud_study",
        agency=agency,
        title=title,
        body=body,
        pub_date=pub.isoformat() if pub else None,
        url=url,
        stage=h.classify_stage(title),
    )


def page_term(term: str, *, filling: bool, seen: set[str], years: Counter, buckets: dict[int, Counter]) -> int:
    added = 0
    page = 0
    while True:
        try:
            data = h.api_get(
                {
                    "parameters[title]": term,
                    "pagesize": h.PAGESIZE,
                    "page": page,
                    "sort": "date",
                    "direction": "DESC",
                }
            )
        except Exception as exc:
            print(f"  FAILED {term} page {page}: {exc}", file=sys.stderr)
            break
        results = data.get("results") or []
        total = int(data.get("metadata", {}).get("resultset", {}).get("count") or 0)
        page_added = 0
        for raw in results:
            rec = _record_from_api(raw)
            if rec and _keep_press(rec, years, buckets, seen, filling=filling):
                added += 1
                page_added += 1
        short = sum(1 for y in range(YEAR_MIN, YEAR_MAX + 1) if years[y] < YEAR_CAP)
        print(
            f"    [{term}] page {page} +{page_added} kept={added} years_short={short} /{total}",
            file=sys.stderr,
        )
        if not results or (page + 1) * h.PAGESIZE >= total:
            break
        if YEAR_CAP and short == 0:
            print(f"    [{term}] every year is at {YEAR_CAP}", file=sys.stderr)
            break
        page += 1
        if page % 5 == 0:
            _write_json(PRESS_STATUS, _press_status(years, buckets, term=term, page=page))
    return added


def _press_status(years: Counter, buckets: dict[int, Counter], **extra: object) -> dict:
    return {
        "updated": _now(),
        "nhsr": NHSR,
        "year_cap": YEAR_CAP,
        "doj_api_floor": "2009-01-06",
        "note": "DOJ News API fraud titles begin in January 2009. Years 2000-2008 depend on state prosecution feeds.",
        "by_year": {str(y): years[y] for y in range(YEAR_MIN, YEAR_MAX + 1)},
        "by_bucket": {str(y): dict(buckets.get(y, {})) for y in range(YEAR_MIN, YEAR_MAX + 1) if years[y]},
        "total": sum(years.values()),
        **extra,
    }


def _good_press_url(url: str) -> bool:
    """Keep a real justice.gov press slug. PDF text-glue produces CamelCase junk."""
    if not url.startswith("https://www.justice.gov/") or "/pr/" not in url:
        return False
    path = url.split("www.justice.gov", 1)[-1]
    if any(ch.isupper() for ch in path) or len(url) > 170:
        return False
    tail = path.rstrip("/").split("/")[-1]
    return bool(re.fullmatch(r"[a-z0-9\-]{12,}", tail))


def _flatten_urls(text: str) -> list[str]:
    flat = re.sub(r"\s+", "", text or "")
    found = []
    seen: set[str] = set()
    for url in URL_RE.findall(flat):
        url = url.rstrip(".,;)")
        if url not in seen and _good_press_url(url):
            seen.add(url)
            found.append(url)
    return found


def parse_eji_cases(text: str, source: str) -> list[dict]:
    cases: list[dict] = []
    parts = CASE_SPLIT_RE.split(text or "")
    for part in parts[1:]:
        window = part[:900]
        name_m = NAME_RE.match(window.strip())
        if not name_m:
            continue
        name = re.sub(r"\s+", " ", name_m.group(1)).strip(" .")
        if len(name) < 4 or name.lower() in {"et", "al", "the"}:
            continue
        criminal = bool(re.search(r"\bcriminal\b", window, re.I))
        civil = bool(re.search(r"\bcivil\b", window, re.I))
        docket_m = DOCKET_RE.search(window)
        docket = ""
        if docket_m:
            docket = f"{int(docket_m.group(1))}:{docket_m.group(2)}-cr-{int(docket_m.group(3))}"
        if civil and not criminal and not docket:
            continue
        if not criminal and not docket:
            continue
        offense = _bucket(name, window)
        cases.append(
            {
                "case_name": f"United States v. {name}",
                "defendant": name,
                "docket_number": docket,
                "criminal": True,
                "bucket": offense,
                "source": source,
                "nhsr": NHSR,
            }
        )
    return cases


def fetch_eji_text() -> list[tuple[str, str]]:
    """Download EJI appendix PDFs and return (source_id, text). Provenance stays under eji/."""
    import requests

    EJI_DIR.mkdir(parents=True, exist_ok=True)
    out: list[tuple[str, str]] = []
    headers = {"User-Agent": "CaseNoesis-Collector/1.0 (research; UMass HRPO NHSR #8252)"}
    for slug, url in EJI_DOCS:
        pdf_path = EJI_DIR / f"{slug}.pdf"
        txt_path = EJI_DIR / f"{slug}.txt"
        try:
            if not pdf_path.is_file() or pdf_path.stat().st_size < 1000:
                resp = requests.get(url, headers=headers, timeout=90)
                resp.raise_for_status()
                if resp.content[:4] == b"%PDF":
                    pdf_path.write_bytes(resp.content)
                    print(f"  eji pdf {slug} {pdf_path.stat().st_size} bytes", file=sys.stderr)
                else:
                    print(f"  eji {slug} was not a PDF ({len(resp.content)} bytes)", file=sys.stderr)
            if pdf_path.is_file():
                proc = subprocess.run(
                    ["pdftotext", "-layout", str(pdf_path), str(txt_path)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if proc.returncode != 0:
                    print(f"  pdftotext {slug}: {(proc.stderr or '')[-200:]}", file=sys.stderr)
            if txt_path.is_file() and txt_path.stat().st_size > 500:
                out.append((slug, txt_path.read_text(encoding="utf-8", errors="replace")))
        except Exception as exc:
            print(f"  eji {slug} failed: {exc}", file=sys.stderr)
    return out


def eji_press_and_seeds(seen: set[str], years: Counter, buckets: dict[int, Counter]) -> dict:
    docs = fetch_eji_text()
    cases: list[dict] = []
    urls: list[str] = []
    url_seen: set[str] = set()
    for slug, text in docs:
        cases.extend(parse_eji_cases(text, slug))
        for url in _flatten_urls(text):
            if url not in url_seen:
                url_seen.add(url)
                urls.append(url)
    # Curated press-room listing. justice.gov HTML is often a bot wall; a miss is recorded and skipped.
    room_urls = _press_room_urls()
    for url in room_urls:
        if url not in url_seen:
            url_seen.add(url)
            urls.append(url)
    deduped: list[dict] = []
    seen_keys: set[str] = set()
    for case in cases:
        key = (case.get("docket_number") or case["defendant"]).lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(case)
    seed_path = EJI_DIR / "seeds.json"
    _write_json(
        seed_path,
        {
            "nhsr": NHSR,
            "updated": _now(),
            "cases": deduped,
            "press_urls": urls,
            "docs": [slug for slug, _ in docs],
        },
    )
    resolved = 0
    for url in urls:
        if _norm(url) in seen:
            continue
        try:
            rec = resolver.resolve_justice_gov_url(url)
        except Exception as exc:
            print(f"  resolve failed {url}: {exc}", file=sys.stderr)
            continue
        if rec.get("mode") != "resolved":
            continue
        if not _prosecution(rec.get("title") or "", rec.get("body") or ""):
            continue
        row = _from_parts(
            source_id="eji",
            agency=rec.get("agency") or "DOJ Elder Justice Initiative",
            title=rec.get("title") or "",
            body=rec.get("body") or "",
            pub_date=rec.get("pub_date"),
            url=rec.get("source_url") or url,
            stage=h.classify_stage(rec.get("title") or ""),
        )
        row["bucket"] = "elder"
        if _keep_press(row, years, buckets, seen, filling=False, force=True):
            resolved += 1
    print(f"  eji cases {len(deduped)} press urls {len(urls)} newly kept {resolved}", file=sys.stderr)
    return {"cases": len(deduped), "press_urls": len(urls), "kept": resolved}


def _press_room_urls() -> list[str]:
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CaseNoesis-Collector/1.0; research; NHSR 8252)",
        "Accept": "text/html",
    }
    found: list[str] = []
    seen: set[str] = set()
    for page in range(0, 12):
        url = "https://www.justice.gov/elderjustice/elder-justice-initiative-press-room"
        if page:
            url = f"{url}?page={page}"
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            print(f"  eji press room page {page}: {exc}", file=sys.stderr)
            break
        text = resp.text or ""
        if resp.status_code != 200 or len(text) < 4000 or "akamai" in text.lower() or "challenge" in text[:500].lower():
            print(f"  eji press room page {page} unusable status={resp.status_code} bytes={len(text)}", file=sys.stderr)
            break
        for match in re.findall(r"https://www\.justice\.gov/[a-z0-9/\-]+", text, re.I):
            if "/pr/" in match and match not in seen:
                seen.add(match)
                found.append(match)
        print(f"  eji press room page {page} urls {len(found)}", file=sys.stderr)
        time.sleep(0.6)
    return found


def phase_press() -> None:
    PRESS_DIR.mkdir(parents=True, exist_ok=True)
    seen = _load_jsonl_urls(STUDY)
    years, buckets = _counts_from_study()
    status_path_flag = PRESS_STATUS.is_file()
    seeded = 0
    already = {}
    if status_path_flag:
        try:
            already = json.loads(PRESS_STATUS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            already = {}
    if not already.get("seed_done"):
        seeded = seed_existing(seen, years, buckets)
        _write_json(PRESS_STATUS, _press_status(years, buckets, seed_done=True, seeded=seeded))
        print(f"seeded {seeded} existing fraud rows", file=sys.stderr)
    if (EJI_DIR / "seeds.json").is_file():
        print("eji seeds already on disk; skipping press-room URL resolve", file=sys.stderr)
        eji = {"skipped": True}
    else:
        eji = eji_press_and_seeds(seen, years, buckets)
    added = 0
    for term, filling in PRESS_TERMS:
        if YEAR_CAP and all(years[y] >= YEAR_CAP for y in range(YEAR_MIN, YEAR_MAX + 1)):
            break
        print(f"\n=== {term} filling={filling} ===", file=sys.stderr)
        added += page_term(term, filling=filling, seen=seen, years=years, buckets=buckets)
        _write_json(PRESS_STATUS, _press_status(years, buckets, seed_done=True, seeded=seeded, eji=eji, added=added, term=term))
    _write_json(
        PRESS_STATUS,
        _press_status(years, buckets, seed_done=True, seeded=seeded, eji=eji, added=added, finished=_now()),
    )
    print(f"press done added={added} total={sum(years.values())}", file=sys.stderr)


def _fraud_listing(url: str) -> bool:
    return bool(FRAUD_LISTING_RE.search(url or ""))


def phase_state(per_source: int) -> None:
    import run_source_bulk as bulk

    PRESS_DIR.mkdir(parents=True, exist_ok=True)
    seen = bulk.collected_urls()
    seen |= _load_jsonl_urls(STUDY)
    seen |= _load_jsonl_urls(STATE_OUT)
    summary: dict = {"started": _now(), "nhsr": NHSR, "sources": {}}
    jobs: list[tuple[str, str, list[str]]] = []
    for src in bulk.HTML_SOURCES:
        try:
            urls = bulk.discover_html_source(src, listing_ok=_fraud_listing)
        except Exception as exc:
            print(f"[{src['id']}] discover failed {exc}", file=sys.stderr)
            summary["sources"][src["id"]] = {"error": str(exc)}
            continue
        jobs.append((src["id"], src["name"], urls))
    for src in bulk.USA_SOURCES:
        try:
            urls = bulk.discover_usa(src, listing_ok=_fraud_listing)
        except Exception as exc:
            print(f"[{src['id']}] discover failed {exc}", file=sys.stderr)
            summary["sources"][src["id"]] = {"error": str(exc)}
            continue
        jobs.append((src["id"], src["name"], urls))
    for sid, name, urls in jobs:
        fresh = []
        for url in urls:
            n = bulk._norm(url)
            if n and n not in seen:
                fresh.append(url)
        fresh = fresh[:per_source]
        print(f"[{sid}] candidates {len(urls)} new {len(fresh)}", file=sys.stderr)
        before = 0
        dest = PRESS_DIR / "state_feeds" / f"{sid}.jsonl"
        if dest.is_file():
            before = dest.stat().st_size
        stats = bulk.extract_urls(sid, name, fresh, seen, delay=0.8, dest_path=dest)
        kept_here = 0
        if dest.is_file():
            with dest.open(encoding="utf-8", errors="replace") as handle:
                handle.seek(before)
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("domain") != "fraud":
                        continue
                    if not _prosecution(rec.get("title") or "", rec.get("body") or ""):
                        continue
                    rec["bucket"] = _bucket(rec.get("title") or "", rec.get("body") or "")
                    rec["source_id"] = sid
                    _append(STATE_OUT, rec)
                    _append(LOOKUP, _press_row(rec))
                    kept_here += 1
        summary["sources"][sid] = {"name": name, "new": len(fresh), "gate": dict(stats), "fraud_kept": kept_here}
        summary["updated"] = _now()
        _write_json(PRESS_DIR / "state_status.json", summary)
        print(f"[{sid}] fraud_kept {kept_here} gate {dict(stats)}", file=sys.stderr)
    summary["finished"] = _now()
    _write_json(PRESS_DIR / "state_status.json", summary)


def _court_year(item: dict) -> int | None:
    raw = str(item.get("entry_date_filed") or item.get("dateFiled") or item.get("date_filed") or "")
    return _year(raw[:10])


def _best_rank(desc: str) -> int:
    low = desc.lower()
    order = (
        "sentencing memorandum",
        "plea agreement",
        "factual basis",
        "indictment",
        "criminal complaint",
        "affidavit",
    )
    for i, token in enumerate(order):
        if token in low:
            return i
    return 9


def phase_court(max_calls: int) -> None:
    import court_records
    import run_source_bulk as bulk

    RECAP_DIR.mkdir(parents=True, exist_ok=True)
    court_records.load_token_from_env_files([REPO / ".env", REPO.parent / "CaseLinker" / ".env"])
    court_records.MIN_DELAY = 3.5
    seen_docs: set[str] = set()
    seen_dockets: set[str] = set()
    covered_dockets: Counter = Counter()
    year_counts: Counter = Counter()
    if COURT_LOG.is_file():
        for line in COURT_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("document_id"):
                seen_docs.add(str(rec["document_id"]))
            if rec.get("docket_id"):
                seen_dockets.add(str(rec["docket_id"]))
            if rec.get("docket_number"):
                covered_dockets[str(rec["docket_number"])] += 1
            year = _year(str(rec.get("entry_date") or "")[:10])
            if year:
                year_counts[year] += 1
    if not _wait_for_seeds(420) and not (EJI_DIR / "seeds.json").is_file():
        docs = fetch_eji_text()
        cases: list[dict] = []
        for slug, text in docs:
            cases.extend(parse_eji_cases(text, slug))
        _write_json(EJI_DIR / "seeds.json", {"nhsr": NHSR, "updated": _now(), "cases": cases})
    seeds = []
    try:
        seeds = json.loads((EJI_DIR / "seeds.json").read_text(encoding="utf-8")).get("cases") or []
    except (OSError, json.JSONDecodeError):
        seeds = []
    gap = bulk._wait_for_user_quota(court_records)
    calls = 0
    kept = sum(year_counts.values())
    date_field = _probe_date_field(court_records, bulk, gap)
    calls += 1

    def status(**extra: object) -> None:
        _write_json(
            COURT_STATUS,
            {
                "updated": _now(),
                "nhsr": NHSR,
                "calls": calls,
                "kept": kept,
                "date_field": date_field,
                "by_year": {str(y): year_counts[y] for y in range(YEAR_MIN, YEAR_MAX + 1)},
                "pacer_purchases": 0,
                **extra,
            },
        )

    def take_page(payload: dict, *, query: str, seed: dict | None, year_hint: int | None) -> None:
        nonlocal kept
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            if kept >= COURT_YEAR_CAP * 27:
                return
            desc = str(item.get("description") or item.get("short_description") or "")
            if not bulk._federal_recap(item) or not bulk._rich_filing(item):
                continue
            year = _court_year(item) or year_hint
            if year is None or not (YEAR_MIN <= year <= YEAR_MAX):
                continue
            if year_counts[year] >= COURT_YEAR_CAP:
                continue
            docket_id = str(item.get("docket_id") or "")
            doc_id = str(item.get("id") or "")
            if not doc_id or doc_id in seen_docs:
                continue
            if docket_id and docket_id in seen_dockets:
                continue
            fp = item.get("filepath_local")
            if not item.get("is_available") or not fp:
                continue
            dest = RECAP_DIR / f"{doc_id}.pdf"
            if not (dest.is_file() and dest.stat().st_size > 1000):
                result = court_records.download_free_pdf(
                    f"https://storage.courtlistener.com/{str(fp).lstrip('/')}",
                    dest,
                )
                if not result.get("ok"):
                    continue
                if int(result.get("bytes") or 0) < 8000:
                    dest.unlink(missing_ok=True)
                    continue
            else:
                result = {"ok": True, "path": str(dest), "bytes": dest.stat().st_size}
            seen_docs.add(doc_id)
            if docket_id:
                seen_dockets.add(docket_id)
            year_counts[year] += 1
            kept += 1
            abs_url = item.get("absolute_url") or ""
            if abs_url and not str(abs_url).startswith("http"):
                abs_url = f"https://www.courtlistener.com{abs_url}"
            _append(
                COURT_LOG,
                {
                    "nhsr": NHSR,
                    "observed": True,
                    "inferred": False,
                    "cost": "free",
                    "pacer_purchases": 0,
                    "domain": "fraud",
                    "query": query,
                    "seed": seed,
                    "bucket": (seed or {}).get("bucket") or _bucket(desc, query),
                    "case_name": (seed or {}).get("case_name") or desc[:180],
                    "docket_number": (seed or {}).get("docket_number") or item.get("docketNumber"),
                    "docket_id": docket_id,
                    "document_id": doc_id,
                    "document_description": desc,
                    "page_count": bulk._page_count(item),
                    "entry_date": item.get("entry_date_filed") or item.get("dateFiled"),
                    "year": year,
                    "absolute_url": abs_url,
                    "pdf": result.get("path"),
                    "bytes": result.get("bytes"),
                    "rank": _best_rank(desc),
                },
            )
            print(f"  court {kept} {year} p.{bulk._page_count(item) or '?'} {desc[:70]}", file=sys.stderr)

    # Spread rich filings across years before spending the quota on the newest EJI dockets.
    year_cycle = list(range(2009, YEAR_MAX + 1)) + list(range(YEAR_MIN, 2009))
    qi = 0
    yi = 0
    while calls < max_calls:
        year = year_cycle[yi % len(year_cycle)]
        yi += 1
        if year_counts[year] >= COURT_YEAR_CAP:
            if all(year_counts[y] >= COURT_YEAR_CAP for y in year_cycle):
                break
            continue
        query = COURT_QUERIES[qi % len(COURT_QUERIES)]
        qi += 1
        if date_field:
            q = f"{query} AND {date_field}:[{year}-01-01 TO {year}-12-31]"
        else:
            q = query
        gap = bulk._wait_for_user_quota(court_records)
        resp = bulk._cl_get(
            court_records,
            court_records.COURTLISTENER_SEARCH,
            {"q": q, "type": "rd", "order_by": "entry_date_filed desc"},
            gap,
        )
        calls += 1
        if resp is None:
            continue
        try:
            payload = resp.json()
        except ValueError:
            continue
        print(
            f"  [{year} {query[:40]}] hits {len(payload.get('results') or [])} kept {kept} call {calls}",
            file=sys.stderr,
        )
        take_page(payload, query=q, seed=None, year_hint=year if date_field else None)
        if calls % 5 == 0:
            status(mode="year_sweep", year=year)

    for seed in seeds:
        if calls >= max_calls:
            break
        docket = seed.get("docket_number") or ""
        if docket and covered_dockets[docket] >= 2:
            continue
        name = seed.get("defendant") or ""
        if docket:
            query = f'"{docket}"'
        elif len(name.split()) >= 2:
            query = f'"{name}" AND (indictment OR "plea agreement" OR "sentencing memorandum")'
        else:
            continue
        gap = bulk._wait_for_user_quota(court_records)
        resp = bulk._cl_get(
            court_records,
            court_records.COURTLISTENER_SEARCH,
            {"q": query, "type": "rd", "order_by": "score desc"},
            gap,
        )
        calls += 1
        if resp is None:
            continue
        try:
            payload = resp.json()
        except ValueError:
            continue
        take_page(payload, query=query, seed=seed, year_hint=None)
        if calls % 5 == 0:
            status(mode="eji_seed")
    status(mode="finished", finished=_now())
    print(f"court done kept={kept} calls={calls}", file=sys.stderr)


def _wait_for_seeds(seconds: int) -> bool:
    """Press phase writes eji/seeds.json. Avoid a second download racing that write."""
    path = EJI_DIR / "seeds.json"
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.is_file() and path.stat().st_size > 80:
            return True
        time.sleep(10)
    return path.is_file()


def _probe_date_field(court_records, bulk, gap: float) -> str:
    """Return a date field only when a 2015-bounded query actually returns 2015."""
    field = "entry_date_filed"
    q = f'"wire fraud" AND indictment AND {field}:[2015-01-01 TO 2015-12-31]'
    resp = bulk._cl_get(
        court_records,
        court_records.COURTLISTENER_SEARCH,
        {"q": q, "type": "rd", "order_by": "score desc"},
        gap,
    )
    if resp is None:
        print("  date probe failed; sweeping without a year filter", file=sys.stderr)
        return ""
    try:
        payload = resp.json()
    except ValueError:
        return ""
    results = payload.get("results") or []
    raw = ""
    if results:
        raw = str(results[0].get("entry_date_filed") or results[0].get("dateFiled") or "")
    print(f"  date probe {field} count={payload.get('count')} first={raw[:10]}", file=sys.stderr)
    if raw.startswith("2015"):
        return field
    print("  date probe did not constrain the year", file=sys.stderr)
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Fraud study harvest (NHSR #8252). Never purchases PACER.")
    ap.add_argument("--phase", required=True, choices=["press", "court", "state"])
    ap.add_argument("--state-cap", type=int, default=100, help="New state/federal feed URLs to extract per source.")
    ap.add_argument("--court-calls", type=int, default=220, help="CourtListener search calls to spend this run.")
    args = ap.parse_args()
    if args.phase == "press":
        phase_press()
    elif args.phase == "court":
        phase_court(args.court_calls)
    else:
        phase_state(args.state_cap)


if __name__ == "__main__":
    main()
