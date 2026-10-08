#!/usr/bin/env python3
"""Dated platform-policy snapshots via the Wayback CDX API.

Writes data/collected/hyletic_data/wayback/<slug>/<timestamp>.<ext>.
The version pin is the CDX timestamp.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import store

HERE = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = HERE / "profiles" / "platform_policy.json"
CDX = "https://web.archive.org/cdx/search/cdx"


def _ext(mime: str) -> str:
    mime = (mime or "").lower()
    if "pdf" in mime:
        return "pdf"
    if "json" in mime:
        return "json"
    return "html"


def cdx_rows(url: str, *, snapshots: int, yearly: bool = False) -> list[dict]:
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original,statuscode,digest,mimetype,length",
        "filter": "statuscode:200",
        "limit": "20" if yearly else str(-max(1, snapshots)),
    }
    if yearly:
        params["from"] = "20080101"
        params["to"] = "20261231"
        params["collapse"] = "timestamp:4"
    resp = requests.get(CDX, params=params, headers={"User-Agent": store.USER_AGENT}, timeout=90)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    header = payload[0]
    return [dict(zip(header, row)) for row in payload[1:]]


def harvest(profile: dict, *, root: Path, limit: int, snapshots: int, yearly: bool = False) -> list[dict]:
    seeds = list(profile.get("seeds") or [])[: max(0, limit)]
    saved: list[dict] = []
    for seed in seeds:
        original = str(seed.get("url") or "").strip()
        slug = str(seed.get("slug") or urlparse(original).netloc or "policy")
        title = str(seed.get("title") or slug)
        kind = str(seed.get("kind") or "policy")
        time.sleep(1.2)
        try:
            rows = cdx_rows(original, snapshots=snapshots, yearly=yearly)
        except (requests.RequestException, ValueError) as exc:
            saved.append(store.save_failure(
                collection="wayback", slug=slug, source_url=original, error=str(exc),
                root=root, title=title, catalog_role=kind,
            ))
            print(f"  fail  {slug}  cdx  {exc}", file=sys.stderr)
            continue
        if not rows:
            saved.append(store.save_failure(
                collection="wayback", slug=slug, source_url=original, error="no CDX capture",
                root=root, title=title, catalog_role=kind,
            ))
            print(f"  fail  {slug}  no CDX capture", file=sys.stderr)
            continue
        for row in rows:
            stamp = str(row.get("timestamp") or "")
            page = str(row.get("original") or original)
            capture = f"https://web.archive.org/web/{stamp}id_/{page}"
            fetched = store.fetch_url(capture)
            if not fetched.get("ok"):
                saved.append(store.save_failure(
                    collection="wayback", slug=slug, source_url=capture,
                    error=str(fetched.get("error") or "fetch failed"),
                    root=root, title=title, catalog_role=kind,
                ))
                print(f"  fail  {slug}  {stamp}  {fetched.get('error')}", file=sys.stderr)
                continue
            filename = f"{stamp}.{_ext(str(row.get('mimetype') or fetched.get('mime_type') or ''))}"
            record = store.save_bytes(
                collection="wayback",
                slug=slug,
                filename=filename,
                data=fetched["data"],
                source_url=capture,
                root=root,
                http_status=fetched.get("http_status"),
                mime_type=fetched.get("mime_type") or str(row.get("mimetype") or ""),
                version_pin=stamp,
                title=title,
                catalog_role=kind,
                extra={
                    "original_url": page,
                    "cdx_digest": row.get("digest") or "",
                    "cdx_status": row.get("statuscode") or "",
                },
            )
            print(f"  ok    {slug}  {stamp}  {record.get('byte_length')}")
            saved.append(record)
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Wayback snapshots of platform policy pages.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--out-dir", type=Path, default=store.DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=1, help="How many seed URLs.")
    parser.add_argument("--snapshots", type=int, default=1, help="Captures per URL, newest first.")
    parser.add_argument("--yearly", action="store_true", help="One capture per year, 2008 through 2026.")
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    rows = harvest(
        profile, root=args.out_dir, limit=args.limit, snapshots=args.snapshots, yearly=args.yearly
    )
    ok = sum(1 for row in rows if row.get("content_sha256"))
    print(json.dumps({"collection": "wayback", "tried": len(rows), "saved": ok, "pacer_purchases": 0}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
