#!/usr/bin/env python3
"""Fetch a JSON list of public documents into data/collected/hyletic_data/<collection>/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import store


def _ext(mime: str, url: str) -> str:
    if "pdf" in mime or url.lower().split("?")[0].endswith(".pdf"):
        return ".pdf"
    if "json" in mime or url.endswith(".json"):
        return ".json"
    if "xml" in mime or url.endswith(".xml"):
        return ".xml"
    if url.endswith(".txt") or mime.startswith("text/plain"):
        return ".txt"
    return ".html"


def load_seed(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        raise SystemExit(f"{path} needs a documents list")
    return data


def fetch_documents(seed: dict, *, root: Path, limit: int | None) -> list[dict]:
    collection = str(seed.get("collection") or "seeds")
    docs = seed["documents"]
    if limit is not None:
        docs = docs[: max(0, limit)]
    saved: list[dict] = []
    for doc in docs:
        url = str(doc.get("url") or "").strip()
        slug = str(doc.get("slug") or "doc")
        title = str(doc.get("title") or slug)
        if not url:
            saved.append(store.save_failure(
                collection=collection, slug=slug, source_url="", error="missing url",
                root=root, title=title, catalog_role=str(doc.get("catalog_role") or ""),
            ))
            continue
        fetched = store.fetch_url(url)
        if not fetched.get("ok"):
            row = store.save_failure(
                collection=collection,
                slug=slug,
                source_url=url,
                error=str(fetched.get("error") or "fetch failed"),
                root=root,
                title=title,
                catalog_role=str(doc.get("catalog_role") or ""),
            )
            print(f"  fail  {slug}  {row['error']}", file=sys.stderr)
            saved.append(row)
            continue
        filename = str(doc.get("filename") or (slug + _ext(fetched.get("mime_type") or "", url)))
        row = store.save_bytes(
            collection=collection,
            slug=slug,
            filename=filename,
            data=fetched["data"],
            source_url=url,
            root=root,
            http_status=fetched.get("http_status"),
            mime_type=fetched.get("mime_type") or "",
            version_pin=str(doc.get("version_pin") or ""),
            title=title,
            catalog_role=str(doc.get("catalog_role") or ""),
            see_also=list(doc.get("see_also") or []),
            extra={"final_url": fetched.get("final_url") or url},
        )
        print(f"  ok    {slug}  {row.get('byte_length')}  {row.get('content_sha256', '')[:12]}")
        saved.append(row)
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a public-document seed into hyletic_data/.")
    parser.add_argument("--seeds", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=store.DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=None, help="First N documents only.")
    args = parser.parse_args()
    seed = load_seed(args.seeds)
    rows = fetch_documents(seed, root=args.out_dir, limit=args.limit)
    ok = sum(1 for row in rows if row.get("ok") or row.get("content_sha256"))
    print(json.dumps({
        "collection": seed.get("collection"),
        "tried": len(rows),
        "saved": ok,
        "out_dir": str(args.out_dir),
        "pacer_purchases": 0,
    }))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
