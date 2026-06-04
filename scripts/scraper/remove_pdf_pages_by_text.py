#!/usr/bin/env python3
"""Drop pages from a merged PDF whose text matches any exclude regex."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import pdfplumber
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.exit("pip install pdfplumber pypdf")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--exclude", action="append", required=True, help="Regex; page dropped if any matches")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pdf_path = args.pdf.resolve()
    patterns = [re.compile(p, re.I | re.S) for p in args.exclude]
    reader = PdfReader(str(pdf_path))
    keep: list[int] = []
    dropped: list[tuple[int, str]] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            hit = next((p.pattern[:60] for p in patterns if p.search(text)), None)
            if hit:
                dropped.append((i, text[:120].replace("\n", " ")))
            else:
                keep.append(i)

    print(f"{pdf_path.name}: {len(reader.pages)} pages -> keep {len(keep)}, drop {len(dropped)}")
    for idx, snip in dropped[:10]:
        print(f"  drop page {idx + 1}: {snip}…")

    if args.dry_run or not dropped:
        return

    writer = PdfWriter()
    for i in keep:
        writer.add_page(reader.pages[i])
    bak = pdf_path.with_suffix(".pdf.pre_remove_failures.bak")
    if not bak.exists():
        import shutil

        shutil.copy2(pdf_path, bak)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    print(f"Wrote {pdf_path} ({len(writer.pages)} pages). Backup: {bak}")


if __name__ == "__main__":
    main()
