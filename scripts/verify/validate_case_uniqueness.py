#!/usr/bin/env python3
"""
Validate case uniqueness and aggregator overlaps in local DB.

Checks:
1) Per-source duplicate summaries (exact and weighted Jaccard)
2) Aggregator-vs-all comparisons for NCMEC and DOJ:
   - exact text matches
   - weighted Jaccard similarity
   - headline matches
"""

from __future__ import annotations

import argparse
import bisect
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "Storage Layer"))


def _load_storage():
    if os.getenv("DATABASE_URL"):
        from storage_postgres import CaseStorage  # type: ignore

        return CaseStorage()
    from storage import CaseStorage  # type: ignore

    db_path = PROJECT_ROOT / "caselinker.db"
    return CaseStorage(str(db_path))


def normalize_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def weighted_jaccard_from_counters(c1: Counter, c2: Counter) -> float:
    if not c1 and not c2:
        return 1.0
    if not c1 or not c2:
        return 0.0
    keys = set(c1.keys()) | set(c2.keys())
    intersection = sum(min(c1[t], c2[t]) for t in keys)
    union = sum(max(c1[t], c2[t]) for t in keys)
    if union == 0:
        return 0.0
    return intersection / union


def weighted_jaccard(text_a: str, text_b: str) -> float:
    return weighted_jaccard_from_counters(Counter(tokenize(text_a)), Counter(tokenize(text_b)))


def get_case_text(case: Dict[str, Any]) -> str:
    case_text = case.get("case_text")
    if isinstance(case_text, str) and case_text.strip():
        return case_text
    raw_data = case.get("raw_data")
    if isinstance(raw_data, dict):
        rd_text = raw_data.get("case_text")
        if isinstance(rd_text, str):
            return rd_text
    return ""


def derive_headline(case_text: str) -> str:
    if not case_text:
        return ""
    lines = [ln.strip() for ln in case_text.splitlines() if ln.strip()]
    for ln in lines:
        # Skip obvious metadata-ish lines for cleaner "headline" matching.
        if ln.lower().startswith(("source:", "http://", "https://")):
            continue
        if len(ln) >= 20:
            return normalize_text(ln)
    if lines:
        return normalize_text(lines[0])
    return ""


def source_file(case: Dict[str, Any]) -> str:
    raw_data = case.get("raw_data")
    if isinstance(raw_data, dict):
        sf = raw_data.get("source_file")
        if isinstance(sf, str):
            return sf
    return ""


def case_row(case: Dict[str, Any]) -> Dict[str, Any]:
    text = get_case_text(case)
    norm_text = normalize_text(text)
    tok_counts = Counter(tokenize(norm_text))
    tot = sum(tok_counts.values())
    return {
        "id": case.get("id", ""),
        "source": str(case.get("source", "") or ""),
        "source_file": source_file(case),
        "source_url": str(case.get("source_url", "") or ""),
        "text": text,
        "norm_text": norm_text,
        "headline": derive_headline(text),
        "tok_counts": tok_counts,
        "total_tokens": tot,
    }


def find_exact_duplicates(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["norm_text"]:
            grouped[row["norm_text"]].append(row)
    return {k: v for k, v in grouped.items() if len(v) > 1}


def _totals_compatible_for_jaccard(ta: int, tb: int, threshold: float) -> bool:
    """
    Necessary condition: multiset weighted Jaccard <= min(ta,tb)/max(ta,tb).
    So sim >= threshold implies min/max >= threshold.
    """
    if ta <= 0 or tb <= 0:
        return False
    return min(ta, tb) >= threshold * max(ta, tb)


def find_weighted_jaccard_pairs(
    rows: List[Dict[str, Any]], threshold: float
) -> List[Tuple[float, Dict[str, Any], Dict[str, Any]]]:
    """Compare only pairs whose total token counts can reach threshold (cheap bound)."""
    pairs: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    usable = [r for r in rows if r["norm_text"] and r["total_tokens"] > 0]
    usable.sort(key=lambda r: r["total_tokens"])
    n = len(usable)
    for i in range(n):
        a = usable[i]
        ta = a["total_tokens"]
        c1 = a["tok_counts"]
        j = i + 1
        while j < n:
            b = usable[j]
            tb = b["total_tokens"]
            if tb * threshold > ta:
                break
            if _totals_compatible_for_jaccard(ta, tb, threshold):
                sim = weighted_jaccard_from_counters(c1, b["tok_counts"])
                if sim >= threshold:
                    pairs.append((sim, a, b))
            j += 1
    pairs.sort(key=lambda x: x[0], reverse=True)
    return pairs


def print_per_source_uniqueness(
    rows: List[Dict[str, Any]],
    jaccard_threshold: float,
    max_pairs: int,
) -> None:
    by_source: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_source[row["source"]].append(row)

    print("\n" + "=" * 88)
    print("A) WITHIN-SOURCE UNIQUENESS CHECK")
    print("=" * 88)
    print(
        f"Using weighted Jaccard threshold={jaccard_threshold:.2f}; "
        f"showing up to {max_pairs} similar pairs per source."
    )

    for src in sorted(by_source.keys()):
        src_rows = by_source[src]
        exact_dupes = find_exact_duplicates(src_rows)
        jaccard_pairs = find_weighted_jaccard_pairs(src_rows, jaccard_threshold)

        print("\n" + "-" * 88)
        print(f"Source: {src} (cases={len(src_rows)})")
        print(f"Exact duplicate summary groups: {len(exact_dupes)}")
        if exact_dupes:
            for idx, group_rows in enumerate(exact_dupes.values(), 1):
                ids = [r["id"] for r in group_rows]
                files = sorted({r["source_file"] for r in group_rows if r["source_file"]})
                print(f"  [Exact {idx}] ids={ids}")
                if files:
                    print(f"            files={files}")

        print(f"Weighted Jaccard duplicate-like pairs: {len(jaccard_pairs)}")
        for idx, (sim, a, b) in enumerate(jaccard_pairs[:max_pairs], 1):
            print(
                f"  [Jaccard {idx}] sim={sim:.3f} "
                f"{a['id']}  <->  {b['id']}"
            )


def match_aggregator_sources(
    rows: List[Dict[str, Any]], aggregator_token: str
) -> List[Dict[str, Any]]:
    token = aggregator_token.lower()
    return [r for r in rows if token in r["source"].lower()]


def run_aggregator_vs_all(
    rows: List[Dict[str, Any]],
    aggregator_name: str,
    aggregator_rows: List[Dict[str, Any]],
    jaccard_threshold: float,
    max_pairs: int,
) -> None:
    agg_ids = {r["id"] for r in aggregator_rows}
    others = [r for r in rows if r["id"] not in agg_ids]
    others_with_tokens = [r for r in others if r["norm_text"] and r["total_tokens"] > 0]
    others_with_tokens.sort(key=lambda r: r["total_tokens"])
    other_totals = [r["total_tokens"] for r in others_with_tokens]

    agg_by_exact: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    all_by_exact: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    all_by_headline: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for r in aggregator_rows:
        if r["norm_text"]:
            agg_by_exact[r["norm_text"]].append(r)
    for r in others:
        if r["norm_text"]:
            all_by_exact[r["norm_text"]].append(r)
        if r["headline"]:
            all_by_headline[r["headline"]].append(r)

    exact_matches: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for txt_key, agg_items in agg_by_exact.items():
        for a in agg_items:
            for b in all_by_exact.get(txt_key, []):
                exact_matches.append((a, b))

    headline_matches: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for a in aggregator_rows:
        h = a["headline"]
        if not h:
            continue
        for b in all_by_headline.get(h, []):
            headline_matches.append((a, b))

    similar_pairs: List[Tuple[float, Dict[str, Any], Dict[str, Any]]] = []
    for a in aggregator_rows:
        if not a["norm_text"] or a["total_tokens"] <= 0:
            continue
        ta = a["total_tokens"]
        lo = ta * jaccard_threshold
        hi = ta / jaccard_threshold
        left = bisect.bisect_left(other_totals, lo)
        right = bisect.bisect_right(other_totals, hi)
        for b in others_with_tokens[left:right]:
            sim = weighted_jaccard_from_counters(a["tok_counts"], b["tok_counts"])
            if sim >= jaccard_threshold:
                similar_pairs.append((sim, a, b))
    similar_pairs.sort(key=lambda x: x[0], reverse=True)

    print("\n" + "=" * 88)
    print(f"B) {aggregator_name.upper()} VS ALL")
    print("=" * 88)
    print(
        f"Aggregator cases={len(aggregator_rows)} | Compared-against cases={len(others)}"
    )
    print(f"Exact text overlaps: {len(exact_matches)}")
    for idx, (a, b) in enumerate(exact_matches[:max_pairs], 1):
        print(f"  [Exact {idx}] {a['id']} ({a['source']})  ==  {b['id']} ({b['source']})")

    print(f"Headline overlaps: {len(headline_matches)}")
    for idx, (a, b) in enumerate(headline_matches[:max_pairs], 1):
        print(
            f"  [Headline {idx}] '{a['headline'][:90]}' :: "
            f"{a['id']} ({a['source']}) == {b['id']} ({b['source']})"
        )

    print(f"Weighted Jaccard overlaps (>= {jaccard_threshold:.2f}): {len(similar_pairs)}")
    for idx, (sim, a, b) in enumerate(similar_pairs[:max_pairs], 1):
        print(
            f"  [Jaccard {idx}] sim={sim:.3f} "
            f"{a['id']} ({a['source']}) <-> {b['id']} ({b['source']})"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check per-source uniqueness and aggregator overlaps in local DB."
    )
    parser.add_argument(
        "--jaccard-threshold",
        type=float,
        default=0.88,
        help="Weighted Jaccard threshold for duplicate-like pairs (default: 0.88).",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=20,
        help="Max overlap pairs to print per section (default: 20).",
    )
    parser.add_argument(
        "--ncmec-token",
        type=str,
        default="ncmec",
        help="Source token for NCMEC aggregator matching (default: ncmec).",
    )
    parser.add_argument(
        "--doj-token",
        type=str,
        default="doj",
        help="Source token for DOJ aggregator matching (default: doj).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    storage = _load_storage()
    print("Loading cases from database...", flush=True)
    cases = storage.get_all_cases(include_raw_data=True)

    rows = [case_row(c) for c in cases]
    print(f"Loaded {len(rows)} cases from database.", flush=True)

    if not rows:
        print("No cases found. Exiting.")
        return

    print_per_source_uniqueness(
        rows=rows,
        jaccard_threshold=args.jaccard_threshold,
        max_pairs=args.max_pairs,
    )

    ncmec_rows = match_aggregator_sources(rows, args.ncmec_token)
    doj_rows = match_aggregator_sources(rows, args.doj_token)

    run_aggregator_vs_all(
        rows=rows,
        aggregator_name="NCMEC",
        aggregator_rows=ncmec_rows,
        jaccard_threshold=args.jaccard_threshold,
        max_pairs=args.max_pairs,
    )
    run_aggregator_vs_all(
        rows=rows,
        aggregator_name="DOJ",
        aggregator_rows=doj_rows,
        jaccard_threshold=args.jaccard_threshold,
        max_pairs=args.max_pairs,
    )


if __name__ == "__main__":
    main()
