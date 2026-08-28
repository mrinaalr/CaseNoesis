#!/usr/bin/env python3
"""
Federal press release → structured PDF → PACER/RECAP locate → dry-run / retrieve.

One URL in, two artifacts out, side by side:

  data/collected/press_releases/<slug>.pdf     press release (ReportLab layout,
                                               same `Source:` format as the corpus)
  data/collected/pacer/<slug>/pacer -- …pdf    key court filings (only with --retrieve)
  data/collected/manifests/<slug>.json         join keys + provenance + cost report

This is an orchestrator over existing precise tools — NOT a crawler:

  press stage   scrape_noesis.resolve_justice_gov_url (DOJ API) or
                scrape_pdf.resolve_url_content (host extractors + Jina fallback)
  locate stage  docket regexes on press body + USAO-slug / district-name →
                CourtListener court id (all 94 districts)
  pacer stage   cases2records.CourtListenerClient — DRY-RUN BY DEFAULT.
                Nothing is downloaded and nothing is charged unless --retrieve
                is passed; PACER purchases additionally require --charge-pacer
                and pass a --max-est-cost budget check.

Usage:
  # Dry run (default): press PDF + locate + CourtListener docket report. $0.
  python3 scripts/collect/collect_federal_case.py --url https://www.justice.gov/usao-…/pr/…

  # Press PDF only, skip CourtListener entirely
  python3 scripts/collect/collect_federal_case.py --url … --skip-pacer

  # Later, when authorized to spend: free RECAP docs only
  python3 scripts/collect/collect_federal_case.py --url … --retrieve

  # Later: also buy missing filings (budget-guarded)
  python3 scripts/collect/collect_federal_case.py --url … --retrieve --charge-pacer --max-est-cost 5.00

Env: COURTLISTENER_API_TOKEN (repo .env, or falls back to ../CaseLinker/.env).
Run with a Python ≥3.10 that has requests/bs4/reportlab/pypdf (repo .venv 3.14
is currently broken at the pyexpat level — plain `python3` works).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Optional
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_DIR = REPO_ROOT / "scripts" / "scraper"
PACER_DIR = REPO_ROOT / "data" / "PACER"
COLLECTED_ROOT = REPO_ROOT / "data" / "collected"

# Sibling repo fallback: CaseLinker ran the original PACER pulls and holds the token.
FALLBACK_ENV_FILES = (REPO_ROOT / ".env", REPO_ROOT.parent / "CaseLinker" / ".env")


# ── module loading (scraper + PACER scripts are files, not packages) ──────────


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


scrape_pdf = _load_module("scrape_pdf", SCRAPER_DIR / "scrape_pdf.py")
scrape_noesis = _load_module("scrape_noesis", SCRAPER_DIR / "scrape_noesis.py")
cases2records = _load_module("cases2records", PACER_DIR / "cases2records.py")


def load_env_token(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    import os

    tok = os.environ.get("COURTLISTENER_API_TOKEN", "")
    if tok:
        return tok
    for env_path in FALLBACK_ENV_FILES:
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("COURTLISTENER_API_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip("'\"")
                if tok:
                    print(f"  [env] CourtListener token loaded from {env_path}")
                    return tok
    return ""


# ── locate stage: docket + court out of a press release ───────────────────────

# 3:20-cr-00049-DJH / 1:24-cr-123 / 9:24-mj-8113 (judge-initial suffixes kept out
# of the normalized form; CourtListener stores the bare office:yy-type-seq core).
_FULL_DOCKET_RE = re.compile(
    r"\b(\d{1,2}):(\d{2})-(cr|mj|cv)-(\d{1,6})(?:-[A-Za-z]{1,4})*\b", re.I
)
# "Case No. 20-cr-123" / "Case Number: 20-CR-123" without office prefix.
_BARE_DOCKET_RE = re.compile(
    r"\bcase\s+(?:no\.?|number|nos?\.?)[:\s]+(\d{1,2}[:])?(\d{2})-(cr|mj|cv)-(\d{1,6})",
    re.I,
)

_TYPE_RANK = {"cr": 0, "mj": 1, "cv": 2}

_DIRECTIONS = {
    "northern": "n",
    "southern": "s",
    "eastern": "e",
    "western": "w",
    "middle": "m",
    "central": "c",
}

_STATE_CODES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}

# Single-district states + territories: USAO slug → CourtListener court id.
_SINGLE_DISTRICT_SLUGS = {
    "ak": "akd", "az": "azd", "co": "cod", "ct": "ctd", "de": "ded",
    "dc": "dcd", "hi": "hid", "id": "idd", "ks": "ksd", "me": "med",
    "md": "mdd", "ma": "mad", "mn": "mnd", "mt": "mtd", "ne": "ned",
    "nv": "nvd", "nh": "nhd", "nj": "njd", "nm": "nmd", "nd": "ndd",
    "or": "ord", "pr": "prd", "ri": "rid", "sc": "scd", "sd": "sdd",
    "ut": "utd", "vt": "vtd", "vi": "vid", "wy": "wyd", "gu": "gud",
    "mp": "nmid",
}

_SPECIAL_DISTRICT_NAMES = {
    "district of columbia": "dcd",
    "puerto rico": "prd",
    "guam": "gud",
    "virgin islands": "vid",
    "northern mariana islands": "nmid",
}

_STATE_CODE_SET = frozenset(_STATE_CODES.values())

_DISTRICT_NAME_RE = re.compile(
    r"\b(Northern|Southern|Eastern|Western|Middle|Central)\s+District\s+of\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)
_SINGLE_DISTRICT_NAME_RE = re.compile(
    r"\bDistrict\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)

# "John Doe, 34, of Springfield, was sentenced …" — the standard USAO lede.
# Name tokens must stay on one line (never cross a paragraph boundary) and
# must not end mid-name with a sentence period.
_DEFENDANT_AGE_RE = re.compile(
    r"\b([A-Z][A-Za-z'’\-]+(?: [A-Z]\.)?(?: [\"“'‘][A-Z][A-Za-z'’\-]+[\"”'’])?"
    r"(?: [A-Z][A-Za-z'’\-]+){0,3}),\s+(?:age\s+)?\d{1,3},"
)
_US_V_RE = re.compile(r"United States v\.?\s+([A-Z][A-Za-z'’\-]+(?: [A-Z][A-Za-z'’\-]+){0,3})")

# Words that mark an institution, not a person — reject the candidate.
_NON_PERSON_TOKENS = frozenset(
    "police department sheriff office district attorney judge court investigations "
    "investigation task force county city state federal bureau agency division "
    "united states america justice homeland security".split()
)


def _looks_like_person(name: str) -> bool:
    tokens = [t.strip(".").lower() for t in name.split()]
    return bool(tokens) and not any(t in _NON_PERSON_TOKENS for t in tokens)


def extract_dockets(text: str) -> list[str]:
    """Normalized docket candidates, criminal first, deduplicated, padded to 5."""
    found: list[tuple[int, str]] = []
    for m in _FULL_DOCKET_RE.finditer(text):
        office, yy, typ, seq = m.group(1), m.group(2), m.group(3).lower(), m.group(4)
        found.append((_TYPE_RANK[typ], f"{office}:{yy}-{typ}-{int(seq):05d}"))
    for m in _BARE_DOCKET_RE.finditer(text):
        office, yy, typ, seq = m.group(1), m.group(2), m.group(3).lower(), m.group(4)
        prefix = office if office else ""
        found.append((_TYPE_RANK[typ], f"{prefix}{yy}-{typ}-{int(seq):05d}"))
    seen: set[str] = set()
    out: list[str] = []
    for _rank, d in sorted(found, key=lambda t: t[0]):
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def court_from_usao_slug(url: str) -> Optional[str]:
    """justice.gov/usao-<slug>/pr/… → CourtListener court id."""
    m = re.search(r"/usao-([a-z]+)/", url.lower())
    if not m:
        return None
    slug = m.group(1)
    if slug in _SINGLE_DISTRICT_SLUGS:
        return _SINGLE_DISTRICT_SLUGS[slug]
    if len(slug) >= 4 and slug[:2] in ("nd", "sd", "ed", "wd", "md", "cd"):
        state = slug[2:]
        if state in _STATE_CODE_SET:
            return f"{state}{slug[0]}d"
    return None


def court_from_body(body: str) -> Optional[str]:
    m = _DISTRICT_NAME_RE.search(body)
    if m:
        direction, state_name = m.group(1).lower(), m.group(2).lower()
        code = _STATE_CODES.get(state_name)
        if code:
            return f"{code}{_DIRECTIONS[direction]}d"
    m = _SINGLE_DISTRICT_NAME_RE.search(body)
    if m:
        name = m.group(1).lower()
        if name in _SPECIAL_DISTRICT_NAMES:
            return _SPECIAL_DISTRICT_NAMES[name]
        code = _STATE_CODES.get(name)
        if code:
            return f"{code}d"
    return None


def extract_defendant(title: str, body: str) -> str:
    m = _US_V_RE.search(body) or _US_V_RE.search(title)
    if m and _looks_like_person(m.group(1)):
        return m.group(1).strip()
    # Match line-by-line so a name can never span a paragraph boundary.
    for line in body.splitlines():
        m = _DEFENDANT_AGE_RE.search(line)
        if m and _looks_like_person(m.group(1)):
            return m.group(1).strip()
    return ""


def locate(url: str, title: str, body: str) -> dict[str, Any]:
    dockets = extract_dockets(body)
    court = court_from_usao_slug(url)
    court_source = "usao-slug" if court else None
    if not court:
        court = court_from_body(body)
        court_source = "body-district" if court else None
    defendant = extract_defendant(title, body)
    if dockets and court:
        confidence = "high"
    elif court and defendant:
        confidence = "medium"  # CourtListener caption search still possible
    else:
        confidence = "none"
    return {
        "dockets_found": dockets,
        "docket": dockets[0] if dockets else None,
        "court": court,
        "court_source": court_source,
        "defendant": defendant or None,
        "confidence": confidence,
    }


# ── press stage ────────────────────────────────────────────────────────────────


def _slug_for(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1].lower()
    slug = re.sub(r"[^a-z0-9\-]+", "-", slug).strip("-")
    return slug[:70] or "case"


def resolve_press(url: str, jina_fallback: bool) -> Optional[dict[str, Any]]:
    """→ {mode, title, byline, body, pub_date (date|None), agency} or None."""
    if scrape_noesis.is_justice_gov_url(url):
        rec = scrape_noesis.resolve_justice_gov_url(url)
        if rec.get("mode") != "resolved":
            print("    [press] DOJ API could not resolve this URL")
            return None
        pub = rec.get("pub_date")
        return {
            "mode": "doj-api",
            "title": rec["title"],
            "byline": rec.get("byline", ""),
            "body": rec["body"],
            "pub_date": date.fromisoformat(pub) if pub else None,
            "agency": rec.get("agency", ""),
        }
    args = SimpleNamespace(referer=None, jina_fallback=jina_fallback)
    result = scrape_pdf.resolve_url_content(url, args, verify_tls=True)
    if not result:
        return None
    title, byline, body, pub_date = result
    return {
        "mode": "scrape",
        "title": title,
        "byline": byline,
        "body": body,
        "pub_date": pub_date,
        "agency": urlparse(url).netloc,
    }


# ── pacer stage ────────────────────────────────────────────────────────────────


def run_pacer_stage(
    client: "cases2records.CourtListenerClient",
    *,
    slug: str,
    loc: dict[str, Any],
    args: argparse.Namespace,
    pacer_out: Path,
    pub_date: Optional[date] = None,
) -> dict[str, Any]:
    court = args.court or loc["court"]
    docket = args.docket or loc["docket"]
    defendant = args.defendant or loc["defendant"] or ""
    if not court:
        return {"status": "skipped", "reason": "no court located (pass --court to override)"}
    if not docket and not defendant:
        return {"status": "skipped", "reason": "no docket and no defendant to search with"}

    # Federal captions are styled "United States v. <surname>", so search and
    # score on the surname; nicknames/quotes in the full name poison the query.
    surname = re.sub(r"[\"“”'‘’]", "", defendant.split()[-1]) if defendant else ""

    spec = cases2records.CaseSpec(
        slug=slug,
        defendant=surname or slug,
        case_name=f"United States v. {surname}" if surname else "",
        district=court,
        court=court,
        docket=docket,
        corpus_id=slug,
    )

    # Anchor caption searches to the press date: charges are filed before the
    # press release, rarely more than ~8 years before it.
    filed_after = (pub_date.replace(year=pub_date.year - 8)).isoformat() if pub_date else None
    filed_before = pub_date.isoformat() if pub_date else None

    def _run(dry: bool) -> "cases2records.FetchResult":
        return cases2records.fetch_case_records(
            client,
            spec,
            output_base=pacer_out,
            dry_run=dry,
            key_docs_only=True,
            max_docs=args.max_docs,
            log_cost=bool(not dry and args.log_cost),
            # In dry-run the purchase branch is unreachable; charge_pacer=True
            # there only switches the report to show per-doc estimates.
            charge_pacer=True if dry else args.charge_pacer,
            pacer_username=None if dry else args.pacer_username,
            pacer_password=None if dry else args.pacer_password,
            max_search_hits=8,
            filed_after=filed_after,
            filed_before=filed_before,
        )

    dry_run = not args.retrieve
    try:
        # Budget guard: purchases happen inline inside fetch_case_records, so a
        # charge run is always preceded by a dry-run estimate check.
        if args.retrieve and args.charge_pacer:
            probe = _run(dry=True)
            est_probe = sum(m.get("estimated_pacer_cost", 0) for m in probe.skipped)
            if est_probe > args.max_est_cost:
                return {
                    "status": "budget-exceeded",
                    "estimated_purchase_cost": round(est_probe, 2),
                    "max_est_cost": args.max_est_cost,
                    "reason": "raise --max-est-cost or lower --max-docs to proceed",
                }
        result = _run(dry=dry_run)
    except cases2records.RateLimitExceeded as exc:
        return {"status": "rate-limited", "reason": str(exc)}
    except LookupError as exc:
        return {"status": "not-found", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — report per-case, keep batch alive
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}

    est = sum(m.get("estimated_pacer_cost", 0) for m in result.skipped)
    report = {
        "status": "dry-run" if dry_run else "retrieved",
        # docket-in-press = strong join (verify quickly); caption-search =
        # fuzzy match (verify caption + date_filed on CourtListener first).
        "match_basis": "docket-in-press" if docket else "caption-search",
        "cl_docket_id": result.docket.get("id"),
        "docket_number": result.docket.get("docket_number"),
        "caption": result.docket.get("case_name"),
        "date_filed": result.docket.get("date_filed"),
        "courtlistener_url": "https://www.courtlistener.com"
        + (result.docket.get("absolute_url") or ""),
        "free_in_recap": [
            {"doc": m.get("doc_type"), "entry": m.get("entry_number")}
            for m in result.downloaded
        ],
        "needs_pacer": [
            {
                "doc": m.get("doc_type"),
                "entry": m.get("entry_number"),
                "est_cost": m.get("estimated_pacer_cost"),
            }
            for m in result.skipped
        ],
        "estimated_purchase_cost": round(est, 2),
        "errors": result.errors,
    }
    if not dry_run:
        report["output_dir"] = str(pacer_out.relative_to(REPO_ROOT))
    return report


# ── orchestrator ───────────────────────────────────────────────────────────────


def collect_one(url: str, args: argparse.Namespace, client: Optional[Any]) -> dict[str, Any]:
    slug = _slug_for(url)
    print(f"\n=== {slug} ===\n  URL: {url}")

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "slug": slug,
    }

    press = resolve_press(url, jina_fallback=not args.no_jina)
    if not press:
        manifest["press"] = {"status": "failed"}
        return manifest

    press_dir = args.out_root / "press_releases"
    press_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = press_dir / f"{slug}.pdf"
    ok = scrape_pdf.write_pdf(
        pdf_path, press["title"], press["byline"], press["body"], url, press["pub_date"]
    )
    manifest["press"] = {
        "status": "ok" if ok else "pdf-failed",
        "mode": press["mode"],
        "title": press["title"],
        "pub_date": press["pub_date"].isoformat() if press["pub_date"] else None,
        "agency": press["agency"],
        "pdf": str(pdf_path.relative_to(REPO_ROOT)) if ok else None,
        "body_chars": len(press["body"]),
    }
    print(f"  press: {press['mode']}  \"{press['title'][:70]}\"")
    if ok:
        print(f"  press pdf: {pdf_path.relative_to(REPO_ROOT)}")

    loc = locate(url, press["title"], press["body"])
    manifest["locate"] = loc
    print(
        f"  locate: docket={loc['docket'] or '—'}  court={loc['court'] or '—'}"
        f" ({loc['court_source'] or 'n/a'})  defendant={loc['defendant'] or '—'}"
        f"  confidence={loc['confidence']}"
    )

    if args.skip_pacer:
        manifest["pacer"] = {"status": "skipped", "reason": "--skip-pacer"}
        return manifest
    if client is None:
        manifest["pacer"] = {
            "status": "skipped",
            "reason": "no COURTLISTENER_API_TOKEN available",
        }
        return manifest

    pacer_out = args.out_root / "pacer" / slug
    manifest["pacer"] = run_pacer_stage(
        client, slug=slug, loc=loc, args=args, pacer_out=pacer_out,
        pub_date=press["pub_date"],
    )
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--url", action="append", default=[], help="Press release URL (repeatable)")
    ap.add_argument("--url-file", type=Path, help="One URL per line, # comments allowed")
    ap.add_argument("--out-root", type=Path, default=COLLECTED_ROOT)
    ap.add_argument("--skip-pacer", action="store_true", help="Press PDF + locate only")
    ap.add_argument("--no-jina", action="store_true", help="Disable Jina Reader fallback")
    ap.add_argument("--court", help="Override CourtListener court id (e.g. vaed)")
    ap.add_argument("--docket", help="Override docket number (e.g. 1:20-cr-00096)")
    ap.add_argument("--defendant", help="Override defendant surname for search/scoring")
    ap.add_argument("--max-docs", type=int, default=4, help="Key-doc cap per case")
    ap.add_argument(
        "--cl-interval",
        type=float,
        default=2.0,
        help="Seconds between CourtListener requests (authenticated limit is "
        "~5000/hr; cases2records' 12.5s default is far more cautious than needed)",
    )
    ap.add_argument("--token", default=None, help="CourtListener API token")
    ap.add_argument(
        "--max-quota-wait",
        type=float,
        default=120.0,
        help="Total seconds to tolerate CourtListener 429 sleeps before aborting "
        "the batch (hourly quota exhausted — re-run later)",
    )
    ap.add_argument(
        "--retrieve",
        action="store_true",
        help="Actually download free RECAP PDFs (default is dry-run: report only)",
    )
    ap.add_argument(
        "--charge-pacer",
        action="store_true",
        help="With --retrieve: BUY missing filings via recap-fetch (real money)",
    )
    ap.add_argument("--max-est-cost", type=float, default=6.00,
                    help="Refuse --charge-pacer when the dry-run estimate exceeds this")
    ap.add_argument("--log-cost", action="store_true",
                    help="With --retrieve: append rows to pacer_cost.csv")
    ap.add_argument("--pacer-username", default=None)
    ap.add_argument("--pacer-password", default=None)
    args = ap.parse_args()

    urls = list(args.url)
    if args.url_file and args.url_file.is_file():
        for line in args.url_file.read_text(encoding="utf-8").splitlines():
            line = line.strip().split("#", 1)[0].strip()
            if line.startswith("http"):
                urls.append(line)
    if not urls:
        ap.error("provide --url or --url-file")

    if args.charge_pacer and not args.retrieve:
        ap.error("--charge-pacer requires --retrieve")

    token = load_env_token(args.token)
    client = None
    if not args.skip_pacer:
        if token:
            client = cases2records.CourtListenerClient(
                token,
                min_interval=args.cl_interval,
                max_quota_wait_s=args.max_quota_wait,
            )
        else:
            print(
                "  [warn] no COURTLISTENER_API_TOKEN found (.env / CaseLinker/.env) — "
                "PACER stage will be skipped",
                file=sys.stderr,
            )

    mode = "RETRIEVE" + (" + CHARGE-PACER" if args.charge_pacer else " (free RECAP only)") \
        if args.retrieve else "DRY-RUN (no downloads, no charges)"
    print(f"\nMode: {mode}   URLs: {len(urls)}   Out: {args.out_root.relative_to(REPO_ROOT) if args.out_root.is_relative_to(REPO_ROOT) else args.out_root}")

    manifests_dir = args.out_root / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for url in urls:
        manifest = collect_one(url, args, client)
        if manifest.get("pacer", {}).get("status") == "budget-exceeded":
            p = manifest["pacer"]
            print(
                f"  [budget] est ${p['estimated_purchase_cost']:.2f} > "
                f"--max-est-cost ${p['max_est_cost']:.2f} — no purchases made"
            )
        mpath = manifests_dir / f"{manifest['slug']}.json"
        mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"  manifest: {mpath.relative_to(REPO_ROOT)}")
        if manifest.get("press", {}).get("status") != "ok":
            failures += 1
        if manifest.get("pacer", {}).get("status") == "rate-limited":
            print(
                "\n[stop] CourtListener hourly quota exhausted — aborting the rest of "
                "the batch. Press PDFs collected so far are kept; re-run the remaining "
                "URLs after the quota window resets (~1 hour).",
                file=sys.stderr,
            )
            break

    print(f"\nDone: {len(urls) - failures}/{len(urls)} press releases collected.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
