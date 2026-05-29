#!/usr/bin/env python3
"""
Verify every case in CaseLinker is a crimes-against-children (CAC) case.

Broad gate: **one** signal anywhere in case text, structured topics/tags, or
source URL slug is enough to pass. Use before a full DB wipe / knowledge-graph export.

Companion (uniqueness, not CAC scope):
  python3 scripts/verify/validate_case_uniqueness.py

Usage::
    python3 scripts/verify/verify_cac.py
    python3 scripts/verify/verify_cac.py --db /path/to/caselinker.db
    python3 scripts/verify/verify_cac.py --fail-csv /tmp/cac_failures.csv
    python3 scripts/verify/verify_cac.py --json /tmp/cac_verify.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "caselinker.db"

# Structured topics assigned by the processing pipeline (ICAC/CAC ingest).
_CAC_TOPIC_TAGS = frozenset(
    {
        "csam",
        "hands_on",
        "production",
        "possession",
        "online_only",
    }
)

# (signal_name, compiled regex) — first match wins for reporting; any match passes.
_TEXT_SIGNALS: List[Tuple[str, re.Pattern[str]]] = [
    ("csam", re.compile(r"\bcsam\b|csem\b|child\s+sexual\s+abuse\s+material", re.I)),
    ("child_pornography", re.compile(
        r"child\s+pornograph|child\s+porn\b|kiddie\s+porn|cpam\b|"
        r"pornograph\w*\s+involving\s+juveniles?|juveniles?\s+.{0,30}pornograph",
        re.I,
    )),
    ("child_exploitation", re.compile(
        r"child\s+exploi\w*|child\s+exploitation|exploitation\s+of\s+(a\s+)?(child|minor)|exploiting\s+children|"
        r"sex\s+exploitation",
        re.I,
    )),
    ("indecent_liberties", re.compile(
        r"indecent\s+(liberties|behavior|exposure).{0,40}(child|minor|juvenile)|"
        r"(child|minor|juvenile).{0,40}indecent",
        re.I,
    )),
    ("obscenity_minor", re.compile(
        r"pandering\s+obscen\w*|obscen\w+.{0,50}\bminors?\b|harmful\s+to\s+juveniles|"
        r"obscen\w+\s+involving\s+(a\s+)?minor",
        re.I,
    )),
    ("child_sexual", re.compile(r"child\s+sexual|sexual\s+(conduct|contact|acts?)\s+with\s+(a\s+)?(child|minor|teen|juvenile)", re.I)),
    ("child_sex_crime", re.compile(r"child\s+sex\s+(crime|offen)|sex\s+offen\w*\s+.{0,40}\b(child|minor|juvenile)", re.I)),
    ("child_predator", re.compile(r"child\s+predator|predator\s+.{0,30}\b(child|minor)", re.I)),
    ("sexual_abuse_minor", re.compile(r"sexual\s+abuse\s+of\s+(a\s+)?(child|minor)|abuse\s+of\s+(a\s+)?minor", re.I)),
    ("rape_molest_child", re.compile(r"\brape\b.{0,50}\b(child|minor|juvenile)|\b(child|minor|juvenile).{0,50}\brape\b|child\s+molest|molest\w+.{0,40}\b(child|minor)", re.I)),
    ("enticement_solicitation", re.compile(r"entic\w+.{0,60}\b(child|minor|juvenile|teen)|solicit\w+.{0,60}\b(child|minor|juvenile|teen)", re.I)),
    ("grooming", re.compile(r"groom\w+.{0,50}\b(child|minor|juvenile)|\b(child|minor).{0,50}groom", re.I)),
    ("possession_distribution_csam", re.compile(
        r"(possess|possession|distribut|distribution|receiv\w+|transmit\w+|share\w+|send\w+|upload\w+|download\w+)"
        r".{0,40}(child\s+porn|csam|csem|child\s+sexual\s+abuse\s+material|child\s+exploitation|"
        r"sexual\s+abuse\s+material|images?\s+of\s+(a\s+)?child)",
        re.I,
    )),
    ("production_csam", re.compile(r"produc\w+.{0,30}(child\s+porn|csam|csem|child\s+sexual)", re.I)),
    ("meeting_minor_sex", re.compile(r"meet\w+.{0,40}\b(child|minor|juvenile|teen).{0,40}(sexual|sex\b)|travel\w+.{0,40}(child|minor).{0,40}sex", re.I)),
    ("icac", re.compile(r"internet\s+crimes\s+against\s+children|\bicac\b|i\.?c\.?a\.?c\.?\s+task\s+force", re.I)),
    ("fbi_cse_unit", re.compile(r"child\s+sexual\s+exploitation\s+unit|crimes\s+against\s+children", re.I)),
    ("operation_predator", re.compile(r"operation\s+predator|project\s+safe\s+childhood", re.I)),
    ("lewd_indecent_child", re.compile(r"lewd\w*.{0,30}(child|minor)|indecent\s+(exposure|acts?).{0,30}(child|minor|juvenile)", re.I)),
    ("statutory_underage", re.compile(r"statutory\s+rape|underage\s+.{0,20}(sex|victim|girl|boy)|\b1[0-7][\s-]*year[\s-]*old\b.{0,40}(sexual|rape|molest|abuse)", re.I)),
    ("juvenile_sexual_pair", re.compile(
        r"\b(juvenile|minor|child|children|teen|teenager|preteen|adolescent|student)\b.{0,80}"
        r"(sexual|sex\b|rape|molest|exploit|pornograph\w*|entic|solicit|abuse|assault|traffick)|"
        r"(sexual|sex\b|rape|molest|exploit|pornograph\w*|entic|solicit|abuse|assault|traffick).{0,80}"
        r"\b(juvenile|minor|child|children|teen|teenager|preteen|adolescent|student)\b",
        re.I,
    )),
    ("sex_offender_child_context", re.compile(
        r"sex\s+offen\w+.{0,120}\b(child|children|minor|juvenile|student|teen)\b|"
        r"\b(child|children|minor|juvenile|student|teen)\b.{0,120}sex\s+offen",
        re.I,
    )),
    ("deepfake_minor", re.compile(r"deepfake\w*.{0,40}\b(minor|juvenile|child|student)|\b(minor|juvenile|child|student).{0,40}deepfake", re.I)),
    ("sexual_assault_child", re.compile(r"sexual\s+assault.{0,40}(child|minor|juvenile)|(child|minor|juvenile).{0,40}sexual\s+assault", re.I)),
    ("trafficking_child_sex", re.compile(r"(sex|human)\s+traffick\w+.{0,40}(child|minor)|(child|minor).{0,40}sex\s+traffick", re.I)),
    ("pedophile", re.compile(r"pedophil|paedophil", re.I)),
    ("upsert_nmec_style", re.compile(r"sexual\s+exploitation\s+of\s+(a\s+)?minor|lewd\s+photos?\s+of\s+(a\s+)?juvenile", re.I)),
]

_URL_SIGNAL = re.compile(
    r"child[\-_]?(sexual|sex|porn|predator|exploit|molest|rape|abuse)|"
    r"csam|sex[\-_]?offen|sexual[\-_]?assault[\-_]?child|"
    r"aggravated[\-_]?sexual[\-_]?assault|entic\w+|icac",
    re.I,
)


def _parse_json_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip().lower() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
        return [s.lower()]
    return []


def _case_text(case: Dict[str, Any]) -> str:
    t = case.get("case_text")
    if isinstance(t, str) and t.strip():
        return t
    raw = case.get("raw_data")
    if isinstance(raw, dict):
        rt = raw.get("case_text")
        if isinstance(rt, str):
            return rt
    if isinstance(raw, str):
        try:
            rd = json.loads(raw)
            if isinstance(rd, dict) and isinstance(rd.get("case_text"), str):
                return rd["case_text"]
        except json.JSONDecodeError:
            pass
    return ""


def _normalize_match_text(text: str) -> str:
    """Collapse whitespace; keep letters so split OCR/PDF tokens still match."""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _search_blob(case: Dict[str, Any]) -> str:
    """Lowercased text used for regex matching."""
    parts: List[str] = []
    parts.append(_case_text(case))
    for key in ("notes", "tags", "severity_indicators", "case_topics", "relationship_to_victim"):
        val = case.get(key)
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, list):
            parts.append(" ".join(str(x) for x in val))
    raw = case.get("raw_data")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k != "case_text" and isinstance(v, str):
                parts.append(v)
    return _normalize_match_text("\n".join(parts))


@dataclass
class CacVerdict:
    case_id: str
    source: str
    passed: bool
    signals: List[str] = field(default_factory=list)
    source_url: str = ""
    preview: str = ""


def cac_signals(case: Dict[str, Any]) -> List[str]:
    """Return all CAC signal names matched for this case (empty if none)."""
    hits: List[str] = []

    topics = _parse_json_list(case.get("case_topics"))
    topic_hits = sorted(t for t in topics if t in _CAC_TOPIC_TAGS)
    if topic_hits:
        hits.append("topic:" + "+".join(topic_hits))

    blob = _search_blob(case)
    for name, pat in _TEXT_SIGNALS:
        if pat.search(blob):
            hits.append(name)

    url = str(case.get("source_url") or "").strip()
    if url and _URL_SIGNAL.search(url):
        hits.append("source_url_slug")

    return hits


def is_cac_case(case: Dict[str, Any]) -> bool:
    return bool(cac_signals(case))


def load_cases(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, source, source_url, case_topics, tags, severity_indicators,
               notes, relationship_to_victim, raw_data
        FROM cases
        ORDER BY source, id
        """
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        raw_data = row["raw_data"]
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                raw_data = {}
        if not isinstance(raw_data, dict):
            raw_data = {}
        case_topics = row["case_topics"]
        if isinstance(case_topics, str):
            try:
                case_topics = json.loads(case_topics)
            except json.JSONDecodeError:
                case_topics = []
        out.append(
            {
                "id": row["id"],
                "source": row["source"] or "",
                "source_url": row["source_url"] or "",
                "case_topics": case_topics,
                "tags": row["tags"],
                "severity_indicators": row["severity_indicators"],
                "notes": row["notes"] or "",
                "relationship_to_victim": row["relationship_to_victim"] or "",
                "raw_data": raw_data,
                "case_text": raw_data.get("case_text", ""),
            }
        )
    return out


def analyze_cases(cases: Sequence[Dict[str, Any]]) -> Tuple[List[CacVerdict], Dict[str, Any]]:
    verdicts: List[CacVerdict] = []
    fails_by_source: Counter[str] = Counter()
    pass_by_source: Counter[str] = Counter()
    signal_counts: Counter[str] = Counter()

    for case in cases:
        sigs = cac_signals(case)
        passed = bool(sigs)
        v = CacVerdict(
            case_id=str(case.get("id") or ""),
            source=str(case.get("source") or ""),
            passed=passed,
            signals=sigs,
            source_url=str(case.get("source_url") or ""),
            preview=_case_text(case).replace("\n", " ")[:220],
        )
        verdicts.append(v)
        if passed:
            pass_by_source[v.source] += 1
            for s in sigs:
                signal_counts[s] += 1
        else:
            fails_by_source[v.source] += 1

    failures = [v for v in verdicts if not v.passed]
    summary = {
        "total": len(cases),
        "passed": len(cases) - len(failures),
        "failed": len(failures),
        "pass_rate_pct": round(100.0 * (len(cases) - len(failures)) / len(cases), 2) if cases else 0.0,
        "fails_by_source": dict(fails_by_source.most_common()),
        "pass_by_source": dict(pass_by_source.most_common()),
        "top_signals": signal_counts.most_common(25),
    }
    return verdicts, summary


def _print_report(summary: Dict[str, Any], failures: Sequence[CacVerdict], show_failures: int) -> None:
    print("=" * 72)
    print("CAC CORPUS VERIFY — one broad signal required per case")
    print("=" * 72)
    print(f"Total cases:  {summary['total']}")
    print(f"Passed:       {summary['passed']} ({summary['pass_rate_pct']}%)")
    print(f"Failed:       {summary['failed']}")
    if summary["failed"]:
        print("\nFailures by source:")
        for src, n in summary["fails_by_source"].items():
            print(f"  {src}: {n}")
    print("\nTop matched signals (cases may match multiple):")
    for name, n in summary["top_signals"][:15]:
        print(f"  {name}: {n}")
    if failures and show_failures:
        print(f"\nFirst {show_failures} failing cases:")
        for v in failures[:show_failures]:
            print(f"  - {v.case_id} [{v.source}]")
            if v.source_url:
                print(f"    {v.source_url[:100]}")
            print(f"    {v.preview[:180]}...")


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify every DB case is a CAC-relevant case.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    ap.add_argument("--fail-csv", type=Path, help="Write failing rows to CSV")
    ap.add_argument("--json", type=Path, help="Write full summary JSON")
    ap.add_argument("--show-failures", type=int, default=25, help="Max failures printed to stdout")
    ap.add_argument("--quiet", action="store_true", help="Only print summary line unless failures")
    args = ap.parse_args()

    db_path = args.db.expanduser().resolve()
    if not db_path.is_file():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    try:
        cases = load_cases(conn)
    finally:
        conn.close()

    verdicts, summary = analyze_cases(cases)
    failures = [v for v in verdicts if not v.passed]

    if args.quiet and not failures:
        print(f"CAC verify OK: {summary['passed']}/{summary['total']} cases")
    else:
        _print_report(summary, failures, args.show_failures)

    if args.fail_csv and failures:
        args.fail_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.fail_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "source", "source_url", "preview"])
            for v in failures:
                w.writerow([v.case_id, v.source, v.source_url, v.preview])

    if args.json:
        payload = {
            "summary": summary,
            "failures": [
                {
                    "id": v.case_id,
                    "source": v.source,
                    "source_url": v.source_url,
                    "preview": v.preview,
                }
                for v in failures
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote JSON -> {args.json}")

    if args.fail_csv and failures:
        print(f"Wrote failures CSV -> {args.fail_csv}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
