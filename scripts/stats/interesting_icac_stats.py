#!/usr/bin/env python3
"""
Interesting ICAC stats — heavy read-only queries over CaseLinker SQLite.

Usage:
  python3 scripts/stats/interesting_icac_stats.py
  python3 scripts/stats/interesting_icac_stats.py --db /path/to/caselinker.db

Requires a populated caselinker.db (not committed to git). Uses the same
CaseStorage merge rules as the API (extracted_features merged onto rows).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "Storage Layer"))

from facet_tree import (  # noqa: E402
    DEFAULT_FACET_ORDER,
    build_facet_tree,
    count_nodes,
    primary_bucket,
)
from storage import CaseStorage  # noqa: E402


def _json_list(val: Any) -> List[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            p = json.loads(val)
            return p if isinstance(p, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _text_len(case: Dict[str, Any]) -> int:
    t = case.get("case_text") or ""
    if not t:
        rd = case.get("raw_data")
        if isinstance(rd, str):
            try:
                rd = json.loads(rd)
            except (json.JSONDecodeError, TypeError):
                rd = None
        if isinstance(rd, dict):
            t = rd.get("case_text") or ""
    return len(t) if isinstance(t, str) else 0


def run_report(db_path: Path) -> str:
    if not db_path.exists():
        return (
            f"Database not found: {db_path}\n"
            "Populate caselinker.db (e.g. python3 src/main.py …) and re-run.\n"
        )

    storage = CaseStorage(str(db_path))
    cases = storage.get_all_cases(include_raw_data=True)
    lines: List[str] = []

    def out(s: str = "") -> None:
        lines.append(s)

    n = len(cases)
    out("=== CaseLinker — Interesting ICAC stats ===")
    out(f"Database: {db_path}")
    out(f"Total cases: {n}")
    out()

    if n == 0:
        out("No rows in `cases`.")
        return "\n".join(lines)

    # --- Sources
    by_source = Counter((c.get("source") or "unknown") for c in cases)
    out("--- By source ---")
    for src, cnt in by_source.most_common():
        out(f"  {src}: {cnt} ({100 * cnt / n:.1f}%)")
    out()

    # --- Temporal (date_start)
    years = []
    for c in cases:
        ds = c.get("date_start") or (c.get("date_range") or {}).get("start")
        if isinstance(ds, str) and len(ds) >= 4 and ds[:4].isdigit():
            years.append(int(ds[:4]))
    if years:
        yc = Counter(years)
        out("--- date_start year (top 15) ---")
        for y, cnt in yc.most_common(15):
            out(f"  {y}: {cnt}")
        out(f"  (earliest {min(years)}, latest {max(years)})")
    else:
        out("--- date_start year --- (no parseable years)")
    out()

    # --- Victim count
    vc_vals = [c.get("victim_count") for c in cases if c.get("victim_count") is not None]
    out("--- victim_count ---")
    out(f"  non-null: {len(vc_vals)} / {n}")
    if vc_vals:
        out(f"  mean {mean(vc_vals):.2f}, median {median(vc_vals):.1f}, max {max(vc_vals)}")
    out()

    # --- Tag dimensions (same categories as /api/tags)
    case_topics: set = set()
    severity_indicators: set = set()
    platforms_used: set = set()
    investigation_types: set = set()
    relationships: set = set()
    status_tags: set = set()
    severity_phrases_all: set = set()
    agencies_all: set = set()
    orgs_all: set = set()
    locs_all: set = set()

    topics_per_case = []
    sev_per_case = []
    plat_per_case = []

    for c in cases:
        tpc = _json_list(c.get("case_topics"))
        topics_per_case.append(len(tpc))
        case_topics.update(tpc)

        sev = _json_list(c.get("severity_indicators"))
        sev_per_case.append(len(sev))
        severity_indicators.update(sev)

        pl = _json_list(c.get("platforms_used"))
        plat_per_case.append(len(pl))
        platforms_used.update(pl)

        if c.get("investigation_type"):
            investigation_types.add(c["investigation_type"])
        if c.get("relationship_to_victim"):
            relationships.add(c["relationship_to_victim"])
        if c.get("perpetrator_registered_sex_offender"):
            status_tags.add("registered_sex_offender")

        for sp in _json_list(c.get("severity_phrases")):
            severity_phrases_all.add(sp)

        for a in _json_list(c.get("agencies_involved")):
            agencies_all.add(a)
        for o in _json_list(c.get("organizations")):
            orgs_all.add(o)
        for loc in _json_list(c.get("locations")):
            locs_all.add(loc)

    out("--- Distinct tag-like values (corpus-wide) ---")
    out(f"  case_topics: {len(case_topics)} distinct")
    out(f"  severity_indicators: {len(severity_indicators)} distinct")
    out(f"  platforms_used: {len(platforms_used)} distinct")
    out(f"  investigation_type: {len(investigation_types)} distinct")
    out(f"  relationship_to_victim: {len(relationships)} distinct")
    out(f"  status (RSO flag): {len(status_tags)} distinct → {sorted(status_tags)}")
    out(f"  severity_phrases: {len(severity_phrases_all)} distinct")
    out(f"  agencies_involved (merged): {len(agencies_all)} distinct")
    out(f"  organizations (NER/merge): {len(orgs_all)} distinct")
    out(f"  locations (NER/merge): {len(locs_all)} distinct")
    out()

    out("--- Per-case list lengths (mean) ---")
    out(f"  case_topics / case: {mean(topics_per_case):.2f}")
    out(f"  severity_indicators / case: {mean(sev_per_case):.2f}")
    out(f"  platforms_used / case: {mean(plat_per_case):.2f}")
    out()

    # --- Top raw tags
    def top_from_cases(field: str, k: int = 12) -> Counter:
        ctr: Counter = Counter()
        for c in cases:
            for x in _json_list(c.get(field)):
                if x:
                    ctr[str(x)] += 1
        return ctr

    out("--- Top case_topics (by case count) ---")
    for tag, cnt in top_from_cases("case_topics", 20).most_common(12):
        out(f"  {tag}: {cnt}")
    out()

    out("--- Top severity_indicators ---")
    for tag, cnt in top_from_cases("severity_indicators").most_common(12):
        out(f"  {tag}: {cnt}")
    out()

    out("--- Top platforms_used ---")
    for tag, cnt in top_from_cases("platforms_used").most_common(12):
        out(f"  {tag}: {cnt}")
    out()

    # --- Facet primary-bucket empties (∅ rate)
    out("--- Facet tree: ∅ primary-bucket rate (empty at that dimension) ---")
    for field_key, label in DEFAULT_FACET_ORDER:
        empty = sum(1 for c in cases if primary_bucket(c, field_key) == "∅")
        out(f"  {label} ({field_key}): {empty} / {n} ({100 * empty / n:.1f}% ∅)")
    out()

    tree = build_facet_tree(cases, max_depth=None)
    out("--- Facet tree (full DEFAULT_FACET_ORDER depth) ---")
    out(f"  Partition dimensions: {len(DEFAULT_FACET_ORDER)}")
    out(f"  Total tree nodes: {count_nodes(tree)}")
    out()

    # --- Narrative length
    lens = [_text_len(c) for c in cases]
    out("--- case_text length (chars) ---")
    out(f"  mean {mean(lens):.0f}, median {median(lens):.0f}, min {min(lens)}, max {max(lens)}")
    out()

    # --- comparison_values presence
    with_cv = sum(
        1
        for c in cases
        if isinstance(c.get("comparison_values"), dict) and c["comparison_values"]
    )
    out("--- comparison_values ---")
    out(f"  cases with non-empty comparison_values: {with_cv} / {n}")
    out()

    # --- evidence_volume quick hits
    img_nonnull = ev_vid = ev_sz = 0
    for c in cases:
        ev = c.get("evidence_volume")
        if isinstance(ev, dict):
            if ev.get("images") is not None:
                img_nonnull += 1
            if ev.get("videos") is not None:
                ev_vid += 1
            if ev.get("storage_size"):
                ev_sz += 1
    out("--- evidence_volume field presence ---")
    out(f"  images non-null: {img_nonnull}, videos non-null: {ev_vid}, storage_size set: {ev_sz}")
    out()

    # --- investigation_type distribution
    inv_c = Counter((c.get("investigation_type") or "∅") for c in cases)
    out("--- investigation_type ---")
    for k, v in inv_c.most_common():
        out(f"  {k}: {v}")
    out()

    out("=== End report ===")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="CaseLinker corpus statistics")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to caselinker.db (default: repo root caselinker.db or CASELINKER_DB)",
    )
    args = parser.parse_args()
    db = args.db
    if db is None:
        env_db = os.environ.get("CASELINKER_DB")
        db = Path(env_db) if env_db else REPO_ROOT / "caselinker.db"
    else:
        db = db.resolve()

    report = run_report(db)
    print(report)


if __name__ == "__main__":
    main()
