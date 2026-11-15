#!/usr/bin/env python3
"""Collect the filings that narrate the offense. Free RECAP only; never purchases PACER.

A press release announces a prosecution and a judgment records its result.
The conduct itself (who did what, when, to whom, by what means) is told in
a small set of filings, each of them a dated narrative:

    statement_of_offense   "Statement of Offense", "Statement of Facts": filed with a plea
    factual_basis          "Factual Basis", "Factual Resume", "Factual Proffer", "Stipulation of Facts"
    complaint_affidavit    a criminal complaint and the agent's affidavit in support of it

These are found by searching CourtListener's RECAP archive at the document
level (`type=rd`): the docket entry's own description names the filing, and
the archive's full text narrows it to an offense domain. Only documents RECAP
already holds are returned (`available_only`), so every download is a free
file from storage.courtlistener.com. Nothing here can reach PACER.

    python collector/conduct_documents.py --domain fraud --max-docs 300
    python collector/conduct_documents.py --domain all --max-docs 600 --pages 2
    python collector/conduct_documents.py --domain fraud --search-only

Files land in `data/collected/recap/<domain>/<document id>.pdf`, with one row
per file in `conduct_documents.jsonl` beside them (the record index reads it)
and one row in the public lookup. The lookup row carries the kind of filing,
the court and the date, and no party name.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import court_records as cr  # noqa: E402
import public_lookup  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RECAP = REPO / "data" / "collected" / "recap"
LOG_NAME = "conduct_documents.jsonl"
MAX_PAGES_PER_DOCUMENT = 60

# What the docket entry calls the filing. Searched in both description fields.
KINDS: dict[str, tuple[str, ...]] = {
    "statement_of_offense": ("statement of offense", "statement of facts", "statement of the offense"),
    "factual_basis": ("factual basis", "factual resume", "factual proffer", "stipulation of facts", "stipulated factual basis"),
    "complaint_affidavit": ("affidavit in support of criminal complaint", "affidavit in support of complaint", "criminal complaint"),
}
# Full-text terms that place a filing in an offense domain.
DOMAINS: dict[str, tuple[str, ...]] = {
    # Not "money laundering": drug and firearm cases charge it too, and fraud is searched first.
    "fraud": ("wire fraud", "bank fraud", "mail fraud", "health care fraud", "investment fraud", "securities fraud"),
    "trafficking": ("sex trafficking", "commercial sex act"),
    "forced_labor": ("forced labor", "labor trafficking", "involuntary servitude"),
    "cyber": ("ransomware", "unauthorized access to a protected computer", "computer intrusion", "business email compromise"),
    "csea": ("child pornography", "enticement of a minor", "sexual exploitation of a minor", "child sexual abuse material"),
    "extortion": ("extortion", "sextortion", "interstate threats", "Hobbs Act"),
    "drugs": ("conspiracy to distribute", "distribution of fentanyl", "possession with intent to distribute", "darknet"),
    "firearms": ("firearms trafficking", "straw purchase", "dealing in firearms without a license", "machinegun"),
    "corruption": ("bribery", "honest services fraud", "kickbacks", "public official"),
    "stalking": ("cyberstalking", "interstate stalking", "threatening communications"),
    "smuggling": ("alien smuggling", "bringing in and harboring", "smuggling of goods", "export control"),
    "racketeering": ("racketeering conspiracy", "RICO", "murder for hire", "kidnapping"),
}
# The filing is in a district court. A civil "statement of facts" is filed there too, so the case
# itself must also be criminal: see `is_criminal`.
_CRIMINAL_PATH = re.compile(r"^recap/gov\.uscourts\.[a-z]+d\.\d+/")
_PROSECUTION_CAPTION = re.compile(r"^(?:united-states(?:-of-america)?|usa|us)-v-")
_CRIMINAL_DOCKET = re.compile(r"(?:^|[:\-])cr(?:im)?[\-:]|\bcr\b", re.IGNORECASE)


def caption_slug(absolute_url: str) -> str:
    """The case caption CourtListener puts at the end of a docket address: `united-states-v-...`."""
    return (absolute_url or "").rstrip("/").rsplit("/", 1)[-1].lower()


def is_criminal(absolute_url: str, docket_number: str = "") -> bool:
    """A federal prosecution: the caption is "United States v.", or the docket number is a criminal one."""
    return bool(_PROSECUTION_CAPTION.match(caption_slug(absolute_url))) or bool(docket_number and _CRIMINAL_DOCKET.search(docket_number))
_NOT_THE_FILING = re.compile(
    r"\b(?:motion|order|notice|response|reply|opposition|objection|memorandum|transcript|minute\s+entry|waiver|"
    r"exhibit\s+list|appeal|judgment|certificate|summons|warrant)\b",
    re.IGNORECASE,
)


def query(kind: str, domain: str) -> str:
    """The search string for one kind of filing in one domain."""
    named = " OR ".join(f'"{phrase}"' for phrase in KINDS[kind])
    about = " OR ".join(f'"{phrase}"' for phrase in DOMAINS[domain])
    return f"(description:({named}) OR short_description:({named})) AND ({about})"


def classify(description: str, short: str) -> str | None:
    """Which kind of conduct filing a docket entry describes, or None when it is
    a motion, an order or another filing that only mentions one."""
    label = (short or "").strip().lower()
    text = (description or "").strip().lower()
    for kind, phrases in KINDS.items():
        if any(label.startswith(phrase) or label == phrase for phrase in phrases):
            return kind
    head = text[:90]
    for kind, phrases in KINDS.items():
        for phrase in phrases:
            position = head.find(phrase)
            if position != -1 and not _NOT_THE_FILING.search(head[:position]):
                return kind
    return None


def court_of(filepath: str) -> str:
    match = re.match(r"recap/gov\.uscourts\.([a-z]+)\.", filepath or "")
    return match.group(1) if match else ""


def search(kind: str, domain: str, *, pages: int, gap: float) -> tuple[list[dict[str, Any]], int]:
    """Free documents of one kind in one domain: `(hits, total the archive reports)`."""
    params: dict[str, Any] | None = {"q": query(kind, domain), "type": "rd", "available_only": "on", "order_by": "entry_date_filed desc"}
    url: str | None = cr.COURTLISTENER_SEARCH
    hits: list[dict[str, Any]] = []
    total = 0
    for _ in range(max(1, pages)):
        if not url:
            break
        resp = cr.cl_get(url, params, gap)
        if resp is None:
            break
        payload = resp.json()
        total = int(payload.get("count") or total)
        url, params = payload.get("next"), None
        for item in payload.get("results") or []:
            path = str(item.get("filepath_local") or "")
            if not (item.get("is_available") and path and _CRIMINAL_PATH.match(path)):
                continue
            absolute = str(item.get("absolute_url") or "")
            if not is_criminal(absolute, str(item.get("docketNumber") or item.get("docket_number") or "")):
                continue
            found = classify(str(item.get("description") or ""), str(item.get("short_description") or ""))
            if found is None:
                continue
            page_count = int(item.get("page_count") or 0)
            if page_count > MAX_PAGES_PER_DOCUMENT:
                continue
            hits.append({
                "document_id": int(item["id"]), "docket_id": item.get("docket_id"), "document_kind": found,
                "searched_as": kind, "domain": domain, "court": court_of(path), "entry_date": item.get("entry_date_filed"),
                "page_count": page_count, "filepath_local": path,
                "download_url": f"{cr.COURTLISTENER_STORAGE}/{path}",
                "absolute_url": f"https://www.courtlistener.com{absolute}" if absolute.startswith("/") else absolute,
            })
    return hits, total


def _logged(folder: Path) -> set[int]:
    log = folder / LOG_NAME
    if not log.is_file():
        return set()
    return {int(json.loads(line)["document_id"]) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()}


def collect(domains: list[str], *, max_docs: int, pages: int, search_only: bool = False,
            kinds: list[str] | None = None, out_root: Path = RECAP) -> dict[str, Any]:
    """Search each domain for each kind of filing and download what is free.

    Documents are taken round-robin across kinds, so a domain with thousands
    of complaints and a few factual bases still yields both. A document
    already on disk in any domain folder is skipped."""
    cr.load_token_from_env_files([REPO / ".env", REPO.parent / "CaseLinker" / ".env"])
    gap = cr.wait_for_user_quota()
    kinds = kinds or list(KINDS)
    have = {int(path.stem) for path in out_root.glob("*/*.pdf") if path.stem.isdigit()}
    summary: dict[str, Any] = {"cost": "free", "pacer_purchases": 0, "searches": [], "saved": 0, "skipped_on_disk": 0, "failed": 0, "by_domain": {}}
    per_domain = max(1, max_docs // max(1, len(domains)))
    for domain in domains:
        found: dict[str, list[dict[str, Any]]] = {}
        for kind in kinds:
            hits, total = search(kind, domain, pages=pages, gap=gap)
            found[kind] = hits
            summary["searches"].append({"domain": domain, "kind": kind, "free_in_archive": total, "usable_hits": len(hits)})
        if search_only:
            continue
        folder = out_root / domain
        folder.mkdir(parents=True, exist_ok=True)
        done = _logged(folder)
        saved_here: dict[str, int] = {}
        queue: list[dict[str, Any]] = []
        for position in range(max((len(hits) for hits in found.values()), default=0)):
            queue += [hits[position] for hits in found.values() if position < len(hits)]
        taken: set[int] = set()
        for hit in queue:
            if sum(saved_here.values()) >= per_domain:
                break
            doc_id = hit["document_id"]
            if doc_id in taken:
                continue
            taken.add(doc_id)
            if doc_id in have or doc_id in done:
                summary["skipped_on_disk"] += 1
                continue
            result = cr.download_free_pdf(hit["download_url"], folder / f"{doc_id}.pdf")
            if not result.get("ok"):
                summary["failed"] += 1
                continue
            have.add(doc_id)
            row = {
                "pdf": f"{doc_id}.pdf", "document_id": doc_id, "docket_id": hit["docket_id"],
                "document_kind": hit["document_kind"], "domain": domain, "court": hit["court"],
                "entry_date": hit["entry_date"], "page_count": hit["page_count"],
                "absolute_url": hit["absolute_url"], "download_url": hit["download_url"],
                "content_sha256": result["content_sha256"], "bytes": result["bytes"],
                "retrieved_at": result["retrieved_at"], "cost": "free", "pacer_purchases": 0, "nhsr": cr.NHSR,
            }
            with (folder / LOG_NAME).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            public_lookup.append_lookup(
                "recap", domain=domain, agency=hit["court"],
                title=hit["document_kind"].replace("_", " "), pub_date=str(hit["entry_date"] or ""),
                source_url=hit["download_url"],
            )
            saved_here[hit["document_kind"]] = saved_here.get(hit["document_kind"], 0) + 1
            summary["saved"] += 1
        summary["by_domain"][domain] = saved_here
    summary["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return summary


def exclude_civil(out_root: Path = RECAP) -> dict[str, Any]:
    """Take filings from civil cases out of a collection made before `is_criminal`: each one's row moves
    to `conduct_documents.civil.jsonl`, its file to `<root>/_civil/<domain>/`, and its public lookup row
    is dropped. Nothing is deleted."""
    moved: list[dict[str, Any]] = []
    for log in sorted(out_root.glob(f"*/{LOG_NAME}")):
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        keep = [r for r in rows if is_criminal(r.get("absolute_url", ""), r.get("docket_number", ""))]
        civil = [r for r in rows if r not in keep]
        if not civil:
            continue
        aside = out_root / "_civil" / log.parent.name
        aside.mkdir(parents=True, exist_ok=True)
        for row in civil:
            pdf = log.parent / row["pdf"]
            if pdf.is_file():
                pdf.rename(aside / row["pdf"])
        with (log.parent / "conduct_documents.civil.jsonl").open("a", encoding="utf-8") as handle:
            for row in civil:
                handle.write(json.dumps(row) + "\n")
        log.write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
        moved += civil
    urls = {r["download_url"] for r in moved}
    lookup = REPO / "data" / "collected" / "public" / "recap_lookup.jsonl"
    dropped = 0
    if urls and lookup.is_file():
        lines = lookup.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if not (line.strip() and json.loads(line).get("source_url") in urls)]
        dropped = len(lines) - len(kept)
        lookup.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    return {"civil_filings_moved": len(moved), "lookup_rows_dropped": dropped,
            "cases": sorted({caption_slug(r.get("absolute_url", ""))[:40] for r in moved})}


def move_filing(pdf: str, source: str, target: str, out_root: Path = RECAP) -> bool:
    """Move one collected filing, file and row, from one domain folder to another."""
    src, dst = out_root / source, out_root / target
    rows = [json.loads(line) for line in (src / LOG_NAME).read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next((r for r in rows if r["pdf"] == pdf), None)
    if row is None or not (src / pdf).is_file():
        return False
    dst.mkdir(parents=True, exist_ok=True)
    (src / pdf).rename(dst / pdf)
    (src / LOG_NAME).write_text("".join(json.dumps(r) + "\n" for r in rows if r is not row), encoding="utf-8")
    with (dst / LOG_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**row, "domain": target, "moved_from": source}) + "\n")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect statements of offense, factual bases and complaint affidavits. Free RECAP only.")
    ap.add_argument("--domain", default="fraud", help="one of the domains in DOMAINS, a comma-separated list of them, or all")
    ap.add_argument("--max-docs", type=int, default=100, help="documents to save, split evenly across the domains asked for")
    ap.add_argument("--pages", type=int, default=1, help="result pages per search (20 results a page; each page is one API call)")
    ap.add_argument("--kind", action="append", choices=sorted(KINDS), help="limit to one kind of filing; repeatable")
    ap.add_argument("--search-only", action="store_true", help="report what is free in the archive and download nothing")
    ap.add_argument("--exclude-civil", action="store_true", help="move filings from civil cases out of an earlier collection, then stop")
    args = ap.parse_args()
    if args.exclude_civil:
        print(json.dumps(exclude_civil(), indent=2))
        return
    domains = list(DOMAINS) if args.domain == "all" else [d.strip() for d in args.domain.split(",") if d.strip()]
    for domain in domains:
        if domain not in DOMAINS:
            ap.error(f"unknown domain {domain}")
    print(json.dumps(collect(domains, max_docs=args.max_docs, pages=args.pages, search_only=args.search_only, kinds=args.kind), indent=2))


if __name__ == "__main__":
    main()
