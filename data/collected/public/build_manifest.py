#!/usr/bin/env python3
"""
build_manifest.py

Turns a press_lookup-style JSONL file (fields: kind, domain, agency, title,
pub_date, source_url, nhsr, stage, bucket, source_id) into a CSV manifest:
one row per case record, with a generated `filename`, plus `crime_type`,
`document_type`, and `source` columns derived from the raw fields.

What it does, step by step:
  1. Read each JSONL line.
  2. crime_type   <- domain, with "csea" uppercased to "CSEA" (everything
                     else passed through as-is: fraud, trafficking,
                     forced_labor, cyber, ...).
  3. document_type <- kind (press / court), passed through as-is.
  4. source        <- hostname of source_url (e.g. "justice.gov",
                       "courtlistener.com"), NOT the agency field (agency
                       stays in its own column; using it for `source` too
                       would just duplicate it).
  5. filename      <- "{crime_type}_{document_type}_{title-slug}.json",
                       title slug lowercased, non-alphanumerics collapsed to
                       hyphens, capped at 40 characters. If two rows produce
                       the same base filename, later ones get a "_2", "_3",
                       ... suffix so every filename stays unique.
  6. Drop the now-redundant `domain` and `kind` fields (crime_type and
     document_type already carry that information).
  7. Write everything out as a CSV, with filename/crime_type/document_type/
     source as the first four columns and the rest following in the order
     they were first seen.

Usage:
    python3 build_manifest.py input.jsonl output_manifest.csv

No rows are ever dropped -- every input line produces exactly one output
row, even if agency, pub_date, or title is missing (those become
"unknown-agency" / "nodate" / "untitled" style fallbacks where needed, so
nothing crashes on a sparse record).
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from urllib.parse import urlparse

DOC_TYPE_MAP = {"press": "press", "court": "court"}


def crime_type_label(domain):
    if domain is None:
        return "unknown"
    if domain == "csea":
        return "CSEA"
    return domain


def slugify(text, max_len=40):
    """Lowercase, strip stray HTML tags, collapse non-alphanumerics to
    hyphens, trim to max_len. Falls back to "untitled" for empty/missing text."""
    if not text:
        return "untitled"
    s = text.lower()
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return (s[:max_len].rstrip("-")) or "untitled"


def hostname(url):
    """Pull the bare hostname out of a URL, dropping a leading 'www.'."""
    if not url:
        return "unknown-source"
    try:
        h = urlparse(url).netloc
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return "unknown-source"


def build_manifest(in_path, out_csv_path, out_jsonl_path=None, title_max_len=40):
    rows = []
    with open(in_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    built = []
    for item in rows:
        kind = item.get("kind")
        domain = item.get("domain")
        title = item.get("title")
        source_url = item.get("source_url")

        crime_type = crime_type_label(domain)
        document_type = DOC_TYPE_MAP.get(kind, kind or "unknown")
        source = hostname(source_url)
        title_slug = slugify(title, max_len=title_max_len)

        item["crime_type"] = crime_type
        item["document_type"] = document_type
        item["source"] = source
        item.pop("domain", None)
        item.pop("kind", None)

        base = f"{crime_type}_{document_type}_{title_slug}"
        built.append((item, base))

    # De-duplicate filenames: first occurrence keeps the plain name,
    # repeats get _2, _3, ... appended.
    seen = defaultdict(int)
    out_items = []
    dupes = 0
    for item, base in built:
        seen[base] += 1
        n = seen[base]
        item["filename"] = f"{base}.json" if n == 1 else f"{base}_{n}.json"
        if n > 1:
            dupes += 1
        out_items.append(item)

    # Column order: priority columns first, then whatever else was in the
    # source data, in the order first encountered.
    priority = ["filename", "crime_type", "document_type", "source"]
    all_keys, seen_keys = [], set()
    for d in out_items:
        for k in d.keys():
            if k not in seen_keys:
                seen_keys.add(k)
                all_keys.append(k)
    fieldnames = priority + [k for k in all_keys if k not in priority]

    with open(out_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for d in out_items:
            writer.writerow(d)

    if out_jsonl_path:
        with open(out_jsonl_path, "w", encoding="utf-8") as f:
            for d in out_items:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    return {
        "rows": len(out_items),
        "dedupe_suffixes_added": dupes,
        "columns": fieldnames,
    }


def main():
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument("input_jsonl", help="Path to the source *.jsonl file")
    arg_parser.add_argument("output_csv", help="Path to write the manifest *.csv to")
    arg_parser.add_argument(
        "--jsonl-out",
        default=None,
        help="Optional: also write the same labeled data back out as JSONL",
    )
    arg_parser.add_argument(
        "--title-max-len",
        type=int,
        default=40,
        help="Max characters of the title to use in the filename (default: 40)",
    )
    parsed_args = arg_parser.parse_args()

    stats = build_manifest(
        parsed_args.input_jsonl,
        parsed_args.output_csv,
        out_jsonl_path=parsed_args.jsonl_out,
        title_max_len=parsed_args.title_max_len,
    )

    print(f"Wrote {stats['rows']} rows to {parsed_args.output_csv}")
    print(f"Filenames needing a _2/_3/... dedupe suffix: {stats['dedupe_suffixes_added']}")
    print(f"Columns: {', '.join(stats['columns'])}")


if __name__ == "__main__":
    main()
