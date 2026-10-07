#!/usr/bin/env python3
"""Public calibration publications from a seed list.

Raw CyberTipline case reports are not in this list.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import seed as fetch_seed_docs
from . import store

HERE = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = HERE / "profiles" / "calibration.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Public calibration PDFs and report pages.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--out-dir", type=Path, default=store.DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    seed = fetch_seed_docs.load_seed(args.profile)
    rows = fetch_seed_docs.fetch_documents(seed, root=args.out_dir, limit=args.limit)
    ok = sum(1 for row in rows if row.get("ok") or row.get("content_sha256"))
    print(json.dumps({"collection": seed.get("collection"), "tried": len(rows), "saved": ok, "pacer_purchases": 0}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
