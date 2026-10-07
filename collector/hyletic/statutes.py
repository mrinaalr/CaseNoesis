#!/usr/bin/env python3
"""GovInfo copies of United States Code sections.

uscode.house.gov currently redirects to a House.gov maintenance page.
Each citation is fetched from https://www.govinfo.gov/link/uscode/{title}/{section}
and stored under data/collected/hyletic_data/statutes/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import store

HERE = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = HERE / "profiles" / "statutes.json"


def section_url(title: str, section: str, edition: str) -> str:
    # OLRC HTML (uscode.house.gov) currently redirects to a House.gov maintenance page.
    # GovInfo's citation link is the official GPO copy and follows to the latest edition.
    del edition
    return f"https://www.govinfo.gov/link/uscode/{title}/{section}"


def harvest(profile: dict, *, root: Path, limit: int) -> list[dict]:
    edition = str(profile.get("edition") or "prelim")
    cites = list(profile.get("citations") or [])[: max(0, limit)]
    saved: list[dict] = []
    for cite in cites:
        title = str(cite.get("title") or "").strip()
        section = str(cite.get("section") or "").strip()
        slug = str(cite.get("slug") or f"usc-{title}-{section}")
        name = str(cite.get("title_text") or f"{title} U.S.C. § {section}")
        url = str(cite.get("url") or section_url(title, section, edition))
        fetched = store.fetch_url(url)
        data = fetched.get("data") or b""
        maintenance = b"Under Maintenance" in data[:8000] and not data.startswith(b"%PDF")
        if not fetched.get("ok") or maintenance:
            saved.append(store.save_failure(
                collection="statutes", slug=slug, source_url=url,
                error=str(fetched.get("error") or "maintenance page, not the statute"),
                root=root, title=name, catalog_role="statute",
            ))
            print(f"  fail  {slug}  {fetched.get('error') or 'maintenance page'}", file=sys.stderr)
            continue
        final = str(fetched.get("final_url") or url)
        is_pdf = data.startswith(b"%PDF")
        record = store.save_bytes(
            collection="statutes",
            slug=slug,
            filename="section.pdf" if is_pdf else "section.html",
            data=data,
            source_url=url,
            root=root,
            http_status=fetched.get("http_status"),
            mime_type=fetched.get("mime_type") or ("application/pdf" if is_pdf else "text/html"),
            version_pin=final.rsplit("/", 1)[-1],
            title=name,
            catalog_role="statute",
            extra={"usc_title": title, "usc_section": section, "edition": edition, "final_url": final},
        )
        print(f"  ok    {slug}  {record.get('byte_length')}")
        saved.append(record)
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="OLRC section pages for a citation list.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--out-dir", type=Path, default=store.DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    rows = harvest(profile, root=args.out_dir, limit=args.limit)
    ok = sum(1 for row in rows if row.get("content_sha256"))
    print(json.dumps({"collection": "statutes", "tried": len(rows), "saved": ok, "pacer_purchases": 0}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
