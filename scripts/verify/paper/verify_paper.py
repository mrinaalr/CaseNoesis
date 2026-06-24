#!/usr/bin/env python3
"""Verify paper claims → scripts/verify/paper/claims.md + paper_tested.md."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VERIFY_DIR = Path(__file__).resolve().parent
REPO_ROOT = VERIFY_DIR.parents[2]
sys.path.insert(0, str(VERIFY_DIR))

from claims_registry import build_claims  # noqa: E402
from paper import PAPER_URL, load_or_build_paper_text, verify_dir  # noqa: E402
from report import write_reports  # noqa: E402
from verifiers import build_context, verify_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify paper claims against CaseLinker")
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "caselinker.db")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output dir (default: scripts/verify/paper/)",
    )
    parser.add_argument("--refresh-paper", action="store_true")
    parser.add_argument("--json", type=Path, default=None, help="Also write results.json")
    args = parser.parse_args()

    out_dir = args.out or verify_dir()
    paper_text, _ = load_or_build_paper_text(refresh=args.refresh_paper)

    claims = build_claims()
    ctx = build_context(db_path=args.db, paper_text=paper_text)
    results = verify_all(claims, ctx)

    claims_path, tested_path = write_reports(
        out_dir, claims, results, PAPER_URL, db_path=args.db
    )
    print(f"Wrote {claims_path}")
    print(f"Wrote {tested_path}")

    if args.json:
        payload = [
            {
                "claim_id": r.claim_id,
                "status": r.status,
                "observed": r.observed,
                "expected": r.expected,
                "source": r.source,
                "detail": r.detail,
                "notes": r.notes,
            }
            for r in results
        ]
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {args.json}")

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print("Summary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if counts.get("fail") else 0


if __name__ == "__main__":
    raise SystemExit(main())
