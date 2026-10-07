#!/usr/bin/env python3
"""Free RECAP copies of platform-litigation filings. Never purchases PACER.

Misses are recorded. A free PDF lands in data/collected/hyletic_data/litigation/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import store

COLLECTOR = Path(__file__).resolve().parents[1]
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))
import court_records

REPO = COLLECTOR.parent
DEFAULT_PROFILE = COLLECTOR / "profiles" / "platform_litigation.json"


def _filing_rank(text: str) -> int:
    low = text.lower()
    if "motion" in low:
        return 8
    if "complaint" in low:
        return 0
    if "declaration" in low:
        return 1
    return 4


def harvest(profile: dict, *, root: Path, max_docs: int) -> list[dict]:
    court_records.load_token_from_env_files([
        REPO / ".env",
        REPO.parent / "CaseLinker" / ".env",
    ])
    saved: list[dict] = []
    queries = list(profile.get("queries") or [])
    want = max(1, max_docs)
    for query in queries:
        if len([row for row in saved if row.get("content_sha256")]) >= want:
            break
        hits = court_records.search_free(
            str(query), search_type="r", max_results=8, on_topic=False
        )
        hits.sort(key=lambda hit: 0 if "attorney general" in str(hit.get("case_name") or "").lower() else 1)
        ranked_hits: list[tuple[dict, list]] = []
        fallback_hits: list[tuple[dict, list]] = []
        for hit in hits:
            docs = sorted(
                list(hit.get("free_nested_documents") or []),
                key=lambda doc: _filing_rank(str(doc.get("description") or "")),
            )
            if hit.get("download_url"):
                docs.append({
                    "id": hit.get("document_id") or hit.get("id"),
                    "description": hit.get("description"),
                    "download_url": hit.get("download_url"),
                })
            complaints = [doc for doc in docs if _filing_rank(str(doc.get("description") or "")) == 0]
            if complaints:
                ranked_hits.append((hit, complaints))
            elif docs:
                fallback_hits.append((hit, docs))
        ordered = ranked_hits or fallback_hits
        if not ordered:
            saved.append(store.save_failure(
                collection="litigation",
                slug="search",
                source_url=court_records.COURTLISTENER_SEARCH,
                error=f"no free RECAP hit for {query}",
                root=root,
                title=str(query),
                catalog_role="search",
            ))
            print(f"  miss  {query}", file=sys.stderr)
            continue
        for hit, docs in ordered:
            if len([row for row in saved if row.get("content_sha256")]) >= want:
                break
            for doc in docs:
                url = str(doc.get("download_url") or "")
                if not url:
                    continue
                slug = f"recap-{doc.get('id') or 'doc'}"
                dest_parent = store.collection_dir("litigation", root) / store.safe_slug(slug)
                dest_parent.mkdir(parents=True, exist_ok=True)
                direct = court_records.download_free_pdf(url, dest_parent / "filing.pdf")
                if not direct.get("ok"):
                    saved.append(store.save_failure(
                        collection="litigation", slug=slug, source_url=url,
                        error=str(direct.get("error") or "download failed"),
                        root=root, title=str(hit.get("case_name") or ""),
                        catalog_role="filing",
                    ))
                    print(f"  fail  {slug}  {direct.get('error')}", file=sys.stderr)
                    continue
                data = (dest_parent / "filing.pdf").read_bytes()
                http_status = 200
                mime = "application/pdf"
                if not data.startswith(b"%PDF"):
                    saved.append(store.save_failure(
                        collection="litigation", slug=slug, source_url=url,
                        error="not a PDF", root=root,
                        title=str(hit.get("case_name") or ""), catalog_role="filing",
                    ))
                    continue
                record = store.save_bytes(
                    collection="litigation",
                    slug=slug,
                    filename="filing.pdf",
                    data=data,
                    source_url=url,
                    root=root,
                    http_status=http_status,
                    mime_type=mime,
                    version_pin=str(doc.get("id") or ""),
                    title=str(hit.get("case_name") or doc.get("description") or slug),
                    catalog_role="filing",
                    extra={
                        "query": query,
                        "description": doc.get("description") or hit.get("description") or "",
                        "docket_number": hit.get("docket_number") or "",
                        "court": hit.get("court") or "",
                        "courtlistener_url": hit.get("absolute_url") or "",
                        "nhsr": court_records.NHSR,
                        "cost": "free",
                    },
                )
                print(f"  ok    {slug}  {record.get('title', '')[:80]}")
                saved.append(record)
                break
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="One free RECAP filing for a platform-litigation query.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--out-dir", type=Path, default=store.DEFAULT_ROOT)
    parser.add_argument("--max-docs", type=int, default=1)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    rows = harvest(profile, root=args.out_dir, max_docs=args.max_docs)
    ok = sum(1 for row in rows if row.get("content_sha256"))
    print(json.dumps({"collection": "litigation", "tried": len(rows), "saved": ok, "pacer_purchases": 0}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
