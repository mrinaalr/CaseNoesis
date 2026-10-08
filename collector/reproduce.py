#!/usr/bin/env python3
"""Reproduce collected records from the public JSONL lookups.

The files in data/collected/public/ are the share. This module reads only
those rows and fetches source_url again. It does not read article text or PDFs.

    python3 -m collector.reproduce
    python3 -m collector.reproduce --run --kind statute --limit 1
    python3 collector/reproduce.py --run --lookup data/collected/public/press_lookup.jsonl --limit 5

A bare run prints the plan and does not fetch. --run without --limit or --all
refuses, so a 46,230-row file is not pulled by accident. PACER is never purchased.
A CourtListener docket page has no filing URL, so that row is skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PRESS = HERE / "press_releases"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(PRESS) not in sys.path:
    sys.path.insert(0, str(PRESS))

import court_records
import public_lookup
import resolve_press_urls
from collector.hyletic import store

REFERENCE = {
    "wayback": "wayback",
    "statute": "statutes",
    "calibration": "calibration",
    "litigation": "litigation",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _storage_pdf(url: str) -> bool:
    return _host(url) == "storage.courtlistener.com"


def _docket_page(url: str) -> bool:
    host = _host(url)
    return host.endswith("courtlistener.com") and not _storage_pdf(url)


def select_rows(
    *,
    lookup: Path | None = None,
    public_dir: Path | None = None,
    kind: str = "",
    limit: int | None = None,
) -> list[dict]:
    """Rows from one lookup file, or from every file in public/."""
    if lookup is not None:
        paths = [lookup]
    else:
        paths = public_lookup.lookup_paths(public_dir)
    want = (kind or "").strip().lower()
    rows: list[dict] = []
    for path in paths:
        for rec in public_lookup.read_lookup(path):
            if want and str(rec.get("kind") or "") != want:
                continue
            if not (rec.get("source_url") or "").strip():
                continue
            rows.append(rec)
            if limit is not None and len(rows) >= limit:
                return rows
    return rows


def plan(rows: list[dict]) -> dict:
    by_kind = Counter(str(rec.get("kind") or "") for rec in rows)
    docket = sum(1 for rec in rows if str(rec.get("kind")) == "recap" and _docket_page(str(rec.get("source_url") or "")))
    return {
        "rows": len(rows),
        "by_kind": dict(by_kind),
        "docket_pages": docket,
        "fetchable": len(rows) - docket,
        "run": False,
        "pacer_purchases": 0,
    }


def _slug(rec: dict, url: str) -> str:
    raw = str(rec.get("domain") or "").strip()
    if raw:
        return public_lookup._norm(raw).replace("/", "-")[:80] or "doc"
    tail = url.rstrip("/").split("/")[-1]
    return store.safe_slug(tail) or "doc"


def _write_press(rec: dict, url: str) -> dict:
    domain = str(rec.get("domain") or "press")
    folder = REPO / "data" / "collected" / "press_releases" / domain / "from_lookup"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    dest = folder / f"{digest}.json"
    if resolve_press_urls.is_justice_gov_url(url):
        resolved = resolve_press_urls.resolve_justice_gov_url(url)
        if resolved.get("mode") != "resolved":
            return {"ok": False, "kind": "press", "source_url": url, "error": "no DOJ API match"}
        body = str(resolved.get("body") or "")
        payload = {
            **resolved,
            "domain": domain,
            "kind": "press",
            "retrieved_at": _now(),
            "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "observed": True,
            "inferred": False,
            "nhsr": public_lookup.NHSR,
        }
        dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "kind": "press", "source_url": url, "path": str(dest), "bytes": dest.stat().st_size}
    fetched = store.fetch_url(url)
    if not fetched.get("ok"):
        return {"ok": False, "kind": "press", "source_url": url, "error": fetched.get("error")}
    data = fetched["data"]
    payload = {
        "kind": "press",
        "domain": domain,
        "title": rec.get("title") or "",
        "source_url": url,
        "retrieved_at": _now(),
        "content_sha256": hashlib.sha256(data).hexdigest(),
        "observed": True,
        "inferred": False,
        "nhsr": public_lookup.NHSR,
        "body_bytes": len(data),
    }
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (folder / f"{dest.stem}.bin").write_bytes(data)
    return {"ok": True, "kind": "press", "source_url": url, "path": str(dest), "bytes": len(data)}


def _write_recap(rec: dict, url: str) -> dict:
    if _docket_page(url):
        return {
            "ok": False,
            "skipped": "docket_page",
            "kind": "recap",
            "source_url": url,
            "error": "docket page has no storage URL",
        }
    if not _storage_pdf(url):
        return {"ok": False, "kind": "recap", "source_url": url, "error": f"refusing host {_host(url)}"}
    domain = str(rec.get("domain") or "recap")
    name = url.rstrip("/").split("/")[-1] or "filing.pdf"
    if not name.endswith(".pdf"):
        name = f"{name}.pdf"
    dest = REPO / "data" / "collected" / "recap" / domain / name
    if dest.is_file() and dest.stat().st_size > 0 and dest.read_bytes()[:4] == b"%PDF":
        return {"ok": True, "skipped": "present", "kind": "recap", "source_url": url, "path": str(dest)}
    court_records.load_token_from_env_files([REPO / ".env", REPO.parent / "CaseLinker" / ".env"])
    result = court_records.download_free_pdf(url, dest)
    result["kind"] = "recap"
    return result


def _write_reference(rec: dict, url: str) -> dict:
    kind = str(rec.get("kind") or "")
    collection = REFERENCE[kind]
    slug = _slug(rec, url)
    fetched = store.fetch_url(url)
    if not fetched.get("ok"):
        return {"ok": False, "kind": kind, "source_url": url, "error": fetched.get("error")}
    data = fetched["data"]
    if kind == "statute" and not data.startswith(b"%PDF"):
        return {"ok": False, "kind": kind, "source_url": url, "error": "statute body is not a PDF"}
    if kind == "wayback":
        stamp = ""
        marker = "/web/"
        if marker in url:
            stamp = url.split(marker, 1)[1][:14]
        filename = f"{stamp}.html" if stamp.isdigit() else "capture.html"
    elif kind == "statute":
        filename = "section.pdf"
    else:
        filename = url.rstrip("/").split("/")[-1] or "document.bin"
    row = store.save_bytes(
        collection=collection,
        slug=slug,
        filename=filename,
        data=data,
        source_url=url,
        title=str(rec.get("title") or ""),
        catalog_role=kind,
        version_pin=str(rec.get("pub_date") or ""),
    )
    row["kind"] = kind
    return row


def reproduce_row(rec: dict) -> dict:
    url = str(rec.get("source_url") or "").strip()
    kind = str(rec.get("kind") or "")
    if kind == "press":
        return _write_press(rec, url)
    if kind == "recap":
        return _write_recap(rec, url)
    if kind in REFERENCE:
        return _write_reference(rec, url)
    return {"ok": False, "kind": kind, "source_url": url, "error": f"unknown kind {kind}"}


def reproduce(
    *,
    lookup: Path | None = None,
    public_dir: Path | None = None,
    kind: str = "",
    limit: int | None = None,
    run: bool = False,
) -> dict:
    """Plan, or fetch. run=False does not touch the network."""
    rows = select_rows(lookup=lookup, public_dir=public_dir, kind=kind, limit=limit)
    summary = plan(rows)
    if not run:
        return summary
    results = [reproduce_row(rec) for rec in rows]
    on_disk = {"unchanged", "present"}
    noted = on_disk | {"docket_page"}
    saved = sum(1 for row in results if row.get("ok") or row.get("skipped") in on_disk)
    skipped = sum(1 for row in results if row.get("skipped"))
    failed = sum(1 for row in results if not row.get("ok") and row.get("skipped") not in noted)
    summary.update({
        "run": True,
        "saved": saved,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    })
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reproduce collected records from public JSONL lookups.")
    parser.add_argument("--lookup", type=Path, default=None, help="One public JSONL. Default: every file in public/.")
    parser.add_argument("--public", type=Path, default=public_lookup.PUBLIC)
    parser.add_argument("--kind", default="", help="press, recap, wayback, statute, calibration, or litigation.")
    parser.add_argument("--limit", type=int, default=0, help="First N matching rows. 0 means unset.")
    parser.add_argument("--all", action="store_true", help="Every matching row. Required for a full rerun.")
    parser.add_argument("--run", action="store_true", help="Fetch. Without this flag, print the plan only.")
    args = parser.parse_args(argv)
    if args.run and not args.all and args.limit <= 0:
        print("pass --limit N or --all with --run", file=sys.stderr)
        return 2
    limit = None if args.all or args.limit <= 0 else args.limit
    summary = reproduce(
        lookup=args.lookup,
        public_dir=args.public,
        kind=args.kind,
        limit=limit,
        run=args.run,
    )
    shown = dict(summary)
    if args.run and len(shown.get("results") or []) > 20:
        shown["results"] = shown["results"][:20]
        shown["results_truncated"] = True
    print(json.dumps(shown, indent=2, default=str))
    if not args.run:
        return 0
    return 0 if not summary.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
