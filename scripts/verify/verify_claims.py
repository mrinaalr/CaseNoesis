#!/usr/bin/env python3
"""
Verify published CaseLinker claims against the live database.

Run from repo root:
  python3 scripts/verify/verify_claims.py
  python3 scripts/verify/verify_claims.py --db /path/to/caselinker.db
  python3 scripts/verify/verify_claims.py --json verify_claims_output.json

Claim 1: CSAM possession cohort + contact / hands-on (``policy_research_stats``).
Claim 2: CSAM-as-primary-charge proxy via ``csam`` case_topics + era breakdown.
Claim 3: Platform concentration + named-platform frequency.
Claim 4: 61 geographic ICAC task forces vs narrative + ingest ``source`` (``icac_tf_verify``;
Claim 5: Investigation type (undercover / online / proactive; unstated vs unknown).
Claim 6: Hands-on topic vs platform breadth (``policy_research_stats``).
  normalized apostrophes, CCSAO/HICAC needles, aligned-source narrative fallback).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from icac_tf_verify import ICAC_LIKE_SOURCES, analyze_icac_task_forces

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "caselinker.db"

# --- Prior published baseline (~2k-case corpus) for comparison ----------------
BASELINE_POSSESSION_CSAM_COHORT = 1552
BASELINE_CONTACT_BROAD = 450
BASELINE_CONTACT_PCT = 29.0
BASELINE_HANDS_ON_TOPIC = 108

BASELINE_CSAM_TOPIC_PCT = 77.0
BASELINE_CSAM_TOPIC_N = 3665  # ~77% of ~4,760-case corpus
BASELINE_CORPUS_N = 4760

# Claim 4 (~4,788-case corpus, pre–Tier A ingest expansion).
BASELINE_CLAIM4_GEOGRAPHIC_TF = 61
BASELINE_CLAIM4_NARRATIVE_TF = 58
BASELINE_CLAIM4_ALIGNED_TF = 27
BASELINE_CLAIM4_DISTINCT_SOURCES = 34

# Claim 3 (~4,788-case corpus; per-case platform listing counts).
BASELINE_DISTINCT_PLATFORMS = 30
BASELINE_TOP3_PLATFORM_PCT = 42.4

# Claim 5 (~4,760-case corpus): explicit investigation subtypes + unstated.
BASELINE_INV_UNDERCOVER = 363
BASELINE_INV_ONLINE = 275
BASELINE_INV_PROACTIVE = 38
BASELINE_INV_UNSTATED = 1082
BASELINE_INV_CHARACTERIZED = (
    BASELINE_INV_UNDERCOVER + BASELINE_INV_ONLINE + BASELINE_INV_PROACTIVE
)

# Claim 6 (~2,532-case corpus; hands_on n=192).
BASELINE_HANDS_ON_MEAN_PLATFORMS = 1.20
BASELINE_HANDS_ON_COHORT_MEAN_PLATFORMS = 1.64
BASELINE_HANDS_ON_COHORT_OTHER_MEAN = 0.87
BASELINE_NAMED_2PLUS_VS_1_HANDS_ON_RATIO = 2.0  # "nearly double" (old ~2+ vs 1 named)

_GENERIC_PLATFORMS = frozenset({"online", "social media", "chat"})

TIER_A_ZERO_NARRATIVE_LABELS = (
    "CA — San Diego Police Department",
    "HI — Hawaii Department of the Attorney General",
    "IL — Cook County State's Attorney's Office",
)

# Report eras (``date_start`` year); aligned with Painting the Landscape.
ERA_BANDS: List[tuple[str, str, int, int]] = [
    ("I", "2010–2014", 2010, 2014),
    ("II", "2015–2018", 2015, 2018),
    ("III", "2019–2022", 2019, 2022),
    ("IV", "2023–2026", 2023, 2026),
]


def j(x: Any) -> Any:
    if x is None or (isinstance(x, str) and not str(x).strip()):
        return None
    if isinstance(x, (dict, list)):
        return x
    try:
        return json.loads(x)
    except Exception:
        return None


def topic_set(case_topics_blob: Any) -> Set[str]:
    t = j(case_topics_blob)
    if isinstance(t, list):
        return {str(x).lower() for x in t if x is not None}
    return set()


def case_text_lower(raw_blob: Any) -> str:
    rd = j(raw_blob)
    if isinstance(rd, dict):
        t = rd.get("case_text")
        if isinstance(t, str):
            return t.lower()
    return ""


def parse_charges(charges_json: Any) -> List[Dict[str, Any]]:
    c = j(charges_json)
    return [x for x in c if isinstance(x, dict)] if isinstance(c, list) else []


def charge_texts_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for r in rows:
        for item in parse_charges(r.get("charges")):
            ch = item.get("charge")
            if isinstance(ch, str) and ch.strip():
                out.append(ch.lower())
    return out


# --- Contact signal (same as policy_research_stats.py) ------------------------

_SEXUAL_ABUSE_CONTACT_RE = re.compile(
    r"\b(rape|raped|raping|sexual\s+assault|sexually\s+assaulted|sexual\s+abuse|sexually\s+abused|molest|molested|molesting)\b",
    re.IGNORECASE,
)

_CSAM_DEF_LABEL_SCRUB_RE = re.compile(
    r"""(?ix)
    child[\s-]+sexual[\s-]+abuse[\s-]+(?:material|materials|images?|videos?|content|depictions?|files?|csam)\b
    | minor[\s-]+sexual[\s-]+abuse[\s-]+(?:material|materials|images?|videos?|content)\b
    | (?:images?|videos?|materials?|content|depictions?|files?)\s+of\s+child\s+sexual\s+abuse\b
    """
)

_CONTACT_TOKENS = (
    "rape",
    "sodom",
    "molest",
    "sexual contact",
    "physical contact",
    "hands-on",
    "hands on",
    "assault",
    "indecency with",
    "exploitation of a child",
    "sexual conduct with a minor",
    "lewd and lascivious",
    "lewd or lascivious",
    "lascivious exhibition",
    "criminal sexual conduct",
    "carnal knowledge",
    "fondling",
    "fondled",
    "fondles",
    "unlawful sexual contact",
    "unlawful sexual intercourse",
    "unlawful sexual activity with a minor",
    "unlawful sexual conduct with",
    "sexual activity with a minor",
    "penetrative",
    "penetration",
)


def scrub_csam_definitional_labels(text: str) -> str:
    return _CSAM_DEF_LABEL_SCRUB_RE.sub(" ", text)


def cohort_csam_possession(topics: Set[str]) -> bool:
    return "possession" in topics and "csam" in topics


def contact_via_scrubbed_regex(charges_lower: List[str], narrative: str) -> bool:
    blob = "\n".join([*charges_lower, narrative])
    scrubbed = scrub_csam_definitional_labels(blob)
    return bool(_SEXUAL_ABUSE_CONTACT_RE.search(scrubbed))


def contact_via_tokens(charges_lower: List[str], narrative: str) -> bool:
    for tok in _CONTACT_TOKENS:
        for ch in charges_lower:
            if tok in ch:
                return True
        if tok in narrative:
            return True
    return False


def contact_signal(topics: Set[str], charges_lower: List[str], narrative: str) -> bool:
    if "hands_on" in topics:
        return True
    if contact_via_scrubbed_regex(charges_lower, narrative):
        return True
    if contact_via_tokens(charges_lower, narrative):
        return True
    return False


@dataclass
class ContactBreakdown:
    cohort_n: int = 0
    hands_on_topic: int = 0
    contact_broad: int = 0
    via_regex_only: int = 0
    via_tokens_only: int = 0
    broad_not_topic: int = 0


def analyze_csam_and_contact(
    cases: List[Dict[str, Any]],
    prosecution_by_id: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Claim 1: CSAM prevalence + possession+CSAM cohort vs contact / hands-on."""
    n_total = len(cases)
    n_csam_topic = 0
    n_possession_topic = 0
    n_possession_csam = 0
    n_severity_sexual_abuse = 0

    bd = ContactBreakdown()

    for c in cases:
        T = topic_set(c.get("case_topics"))
        if "csam" in T:
            n_csam_topic += 1
        if "possession" in T:
            n_possession_topic += 1
        if not cohort_csam_possession(T):
            continue

        n_possession_csam += 1
        cid = c["id"]
        chg = charge_texts_from_rows(prosecution_by_id.get(cid, []))
        nar = case_text_lower(c.get("raw_data"))

        sev = j(c.get("severity_indicators"))
        if isinstance(sev, list) and "sexual_abuse" in {str(x).lower() for x in sev}:
            n_severity_sexual_abuse += 1

        bd.cohort_n += 1
        has_topic = "hands_on" in T
        has_broad = contact_signal(T, chg, nar)
        has_regex = contact_via_scrubbed_regex(chg, nar)
        has_tok = contact_via_tokens(chg, nar)

        if has_topic:
            bd.hands_on_topic += 1
        if has_broad:
            bd.contact_broad += 1
            if not has_topic:
                bd.broad_not_topic += 1
        if has_broad and not has_topic and has_regex:
            bd.via_regex_only += 1
        if has_broad and not has_topic and not has_regex and has_tok:
            bd.via_tokens_only += 1

    pct_broad = 100.0 * bd.contact_broad / bd.cohort_n if bd.cohort_n else 0.0
    pct_topic = 100.0 * bd.hands_on_topic / bd.cohort_n if bd.cohort_n else 0.0

    return {
        "total_cases": n_total,
        "distinct_ingest_sources": None,  # filled in main() from ICAC/source scan
        "icac_like_source_slots": len(ICAC_LIKE_SOURCES),
        "csam_topic_cases": n_csam_topic,
        "csam_topic_pct_of_corpus": round(100.0 * n_csam_topic / n_total, 1) if n_total else 0.0,
        "possession_topic_cases": n_possession_topic,
        "possession_and_csam_cohort": bd.cohort_n,
        "contact_broad_n": bd.contact_broad,
        "contact_broad_pct_of_cohort": round(pct_broad, 1),
        "hands_on_topic_n": bd.hands_on_topic,
        "hands_on_topic_pct_of_cohort": round(pct_topic, 1),
        "contact_broad_not_hands_on_topic_n": bd.broad_not_topic,
        "severity_sexual_abuse_in_cohort_n": n_severity_sexual_abuse,
        "baseline_comparison": {
            "prior_corpus_approx_cases": 2000,
            "prior_cohort_n": BASELINE_POSSESSION_CSAM_COHORT,
            "prior_contact_broad_n": BASELINE_CONTACT_BROAD,
            "prior_contact_broad_pct": BASELINE_CONTACT_PCT,
            "prior_hands_on_topic_n": BASELINE_HANDS_ON_TOPIC,
            "delta_cohort_n": bd.cohort_n - BASELINE_POSSESSION_CSAM_COHORT,
            "delta_contact_broad_n": bd.contact_broad - BASELINE_CONTACT_BROAD,
            "delta_contact_broad_pct_points": round(pct_broad - BASELINE_CONTACT_PCT, 1),
            "delta_hands_on_topic_n": bd.hands_on_topic - BASELINE_HANDS_ON_TOPIC,
        },
    }


def parse_year(date_start: Any) -> Optional[int]:
    if isinstance(date_start, str) and len(date_start) >= 4 and date_start[:4].isdigit():
        return int(date_start[:4])
    return None


def era_key_for_year(year: Optional[int]) -> Optional[str]:
    if year is None:
        return None
    for label, _years, y0, y1 in ERA_BANDS:
        if y0 <= year <= y1:
            return label
    return None


def platforms_list(blob: Any) -> List[str]:
    p = j(blob)
    if not isinstance(p, list):
        return []
    return [str(x).strip() for x in p if x is not None and str(x).strip()]


def load_cases(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, date_start, case_topics, severity_indicators, raw_data, platforms_used, "
        "extracted_features FROM cases"
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    for c in rows:
        ex = j(c.get("extracted_features"))
        if isinstance(ex, dict) and ex.get("investigation_type"):
            c["investigation_type"] = ex.get("investigation_type")
        else:
            c["investigation_type"] = None
    return rows


def investigation_type_label(case: Dict[str, Any]) -> str:
    t = case.get("investigation_type")
    if t is None or not str(t).strip():
        return "unstated"
    return str(t).strip().lower()


def load_prosecution(conn: sqlite3.Connection) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    cur = conn.execute(
        "SELECT case_id, status, charges, sentences FROM prosecution_outcomes"
    )
    for case_id, status, charges, sentences in cur.fetchall():
        out[case_id].append(
            {"status": status, "charges": charges, "sentences": sentences}
        )
    return out


def analyze_csam_primary_charge(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Claim 2: share of corpus with ``csam`` in case_topics.

    Proxy for “CSAM as primary charge”: narrative/charge language matching the
    pipeline CSAM material regex (CSAM, child sexual abuse material, child porn*).
    Not parsed prosecution charge tables (sparse in DB).
    """
    n_total = len(cases)
    n_csam = 0
    by_era: Dict[str, Dict[str, int]] = {
        f"{label} ({years})": {"n": 0, "csam": 0} for label, years, _, _ in ERA_BANDS
    }
    by_era["unknown date"] = {"n": 0, "csam": 0}

    for c in cases:
        T = topic_set(c.get("case_topics"))
        has_csam = "csam" in T
        if has_csam:
            n_csam += 1
        year = parse_year(c.get("date_start"))
        ek = era_key_for_year(year)
        if ek is None:
            bucket = "unknown date"
        else:
            bucket = next(f"{label} ({years})" for label, years, _, _ in ERA_BANDS if label == ek)
        by_era[bucket]["n"] += 1
        if has_csam:
            by_era[bucket]["csam"] += 1

    pct = 100.0 * n_csam / n_total if n_total else 0.0
    era_rows: List[Dict[str, Any]] = []
    for label, years, _, _ in ERA_BANDS:
        key = f"{label} ({years})"
        d = by_era[key]
        era_rows.append(
            {
                "era": label,
                "years": years,
                "n": d["n"],
                "csam_n": d["csam"],
                "csam_pct": round(100.0 * d["csam"] / d["n"], 1) if d["n"] else 0.0,
            }
        )
    unk = by_era["unknown date"]
    outside_era_n = unk["n"]
    outside_era_csam = unk["csam"]
    if unk["n"]:
        era_rows.append(
            {
                "era": "unknown",
                "years": None,
                "n": unk["n"],
                "csam_n": unk["csam"],
                "csam_pct": round(100.0 * unk["csam"] / unk["n"], 1),
            }
        )

    # Eras III–IV band (modern reporting) for “relatively stable” footnote
    modern_n = sum(by_era[f"{label} ({years})"]["n"] for label, years, _, _ in ERA_BANDS if label in ("III", "IV"))
    modern_csam = sum(
        by_era[f"{label} ({years})"]["csam"] for label, years, _, _ in ERA_BANDS if label in ("III", "IV")
    )
    modern_pct = round(100.0 * modern_csam / modern_n, 1) if modern_n else 0.0

    return {
        "total_cases": n_total,
        "csam_topic_n": n_csam,
        "csam_topic_pct": round(pct, 1),
        "headline_pct_rounded": round(pct),
        "definition": (
            "case_topics contains 'csam' (pipeline: CSAM, child sexual abuse material, "
            "child pornography / pornographic / child porn in public-release text)"
        ),
        "by_era": era_rows,
        "eras_iii_iv_n": modern_n,
        "eras_iii_iv_csam_n": modern_csam,
        "eras_iii_iv_csam_pct": modern_pct,
        "outside_report_era_window_n": outside_era_n,
        "outside_report_era_window_csam_n": outside_era_csam,
        "footnote_era_lines": [
            f"Era {r['era']} ({r['years']}): {r['csam_n']:,}/{r['n']:,} ({r['csam_pct']}%)"
            for r in era_rows
            if r.get("years")
        ],
        "baseline_comparison": {
            "prior_corpus_n": BASELINE_CORPUS_N,
            "prior_csam_topic_n": BASELINE_CSAM_TOPIC_N,
            "prior_csam_topic_pct": BASELINE_CSAM_TOPIC_PCT,
            "delta_csam_topic_n": n_csam - BASELINE_CSAM_TOPIC_N,
            "delta_csam_topic_pct_points": round(pct - BASELINE_CSAM_TOPIC_PCT, 1),
        },
    }


# --- Claim 3: platform concentration + named-platform frequency ---------------

def _platform_lows(plats: List[str]) -> List[str]:
    return [p.lower() for p in plats]


def _case_lists_display_platform(plats: List[str], display: str) -> bool:
    lows = _platform_lows(plats)
    if display == "Online / Unspecified":
        return "online" in lows
    if display == "Unspecified (no platform tag)":
        return not plats
    if display == "Social Media":
        return "social media" in lows
    if display == "Kik Messenger":
        return any("kik" in x for x in lows)
    if display == "Facebook / Meta":
        return any("facebook" in x for x in lows)
    if display == "Snapchat":
        return any("snapchat" in x for x in lows)
    return False


def analyze_platform_concentration(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Claim 3a: distinct ``platforms_used`` labels; share of corpus touching top-3 surfaces.
    """
    per_platform: Dict[str, int] = defaultdict(int)
    distinct: Set[str] = set()
    n_total = len(cases)

    for c in cases:
        seen: Set[str] = set()
        for p in platforms_list(c.get("platforms_used")):
            distinct.add(p.casefold())
            if p not in seen:
                seen.add(p)
                per_platform[p] += 1

    ranked = sorted(per_platform.items(), key=lambda x: (-x[1], x[0].lower()))
    top3_labels = [p for p, _ in ranked[:3]]
    top3_set = {x.lower() for x in top3_labels}
    with_top3 = sum(
        1
        for c in cases
        if any(p.lower() in top3_set for p in platforms_list(c.get("platforms_used")))
    )
    with_any = sum(1 for c in cases if platforms_list(c.get("platforms_used")))
    pct_top3 = 100.0 * with_top3 / n_total if n_total else 0.0

    return {
        "total_cases": n_total,
        "distinct_platform_labels": len(distinct),
        "cases_with_any_platform_tag": with_any,
        "cases_with_any_platform_pct": round(100.0 * with_any / n_total, 1) if n_total else 0.0,
        "top3_labels": top3_labels,
        "cases_touching_top3": with_top3,
        "top3_pct_of_corpus": round(pct_top3, 1),
        "top3_pct_rounded_headline": round(pct_top3),
        "platform_ranking": [{"platform": p, "cases": n} for p, n in ranked],
        "definition": (
            "platforms_used from ingest regex (extract_platforms); each case counted once "
            "per label it lists; top-3 share = cases listing online, social media, or chat"
        ),
        "baseline_comparison": {
            "prior_distinct_platforms": BASELINE_DISTINCT_PLATFORMS,
            "prior_top3_pct": BASELINE_TOP3_PLATFORM_PCT,
            "delta_distinct_platforms": len(distinct) - BASELINE_DISTINCT_PLATFORMS,
            "delta_top3_pct_points": round(pct_top3 - BASELINE_TOP3_PLATFORM_PCT, 1),
        },
    }


def analyze_named_platform_frequency(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Claim 3b: report-style named-platform rows (listing frequency, not mutex primary).
    """
    display_order = [
        "Unspecified (no platform tag)",
        "Online / Unspecified",
        "Social Media",
        "Kik Messenger",
        "Facebook / Meta",
        "Snapchat",
    ]
    counts = {label: 0 for label in display_order}
    for c in cases:
        plats = platforms_list(c.get("platforms_used"))
        seen: Set[str] = set()
        for label in display_order:
            if label in seen:
                continue
            if _case_lists_display_platform(plats, label):
                counts[label] += 1
                seen.add(label)

    n_total = len(cases)
    rows = [
        {
            "display": label,
            "cases": counts[label],
            "pct_of_corpus": round(100.0 * counts[label] / n_total, 1) if n_total else 0.0,
        }
        for label in display_order
    ]

    # Era notes for narrative footnotes (listing counts within era bands).
    era_counts: Dict[str, Dict[str, int]] = {
        f"{label} ({years})": {d: 0 for d in display_order}
        for label, years, _, _ in ERA_BANDS
    }
    for c in cases:
        year = parse_year(c.get("date_start"))
        ek = era_key_for_year(year)
        if ek is None:
            continue
        era_key = next(f"{label} ({years})" for label, years, _, _ in ERA_BANDS if label == ek)
        plats = platforms_list(c.get("platforms_used"))
        seen = set()
        for label in display_order:
            if label in seen:
                continue
            if _case_lists_display_platform(plats, label):
                era_counts[era_key][label] += 1
                seen.add(label)

    return {
        "total_cases": n_total,
        "definition": (
            "Per-case listing frequency on platforms_used (case counted once per display row "
            "it matches). 'Online / Unspecified' = generic online tag only (not empty). "
            "'Unspecified' = empty platforms_used. Named brands use pipeline labels "
            "(Kik, Facebook/Messenger, Snapchat)."
        ),
        "rows": rows,
        "by_era": era_counts,
    }


def analyze_investigation_types(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Claim 5: investigation_type from extract_investigation_info (stored in extracted_features).

    - undercover / online / proactive / reactive: explicit subtype regex on narrative.
    - unstated: no type stored (no ``investigation`` / ``operation(s)`` gate in text).
    - unknown: gate matched but no subtype phrase (not in headline counts).
    """
    n_total = len(cases)
    counts: Dict[str, int] = defaultdict(int)
    by_era: Dict[str, Dict[str, int]] = {
        f"{label} ({years})": defaultdict(int) for label, years, _, _ in ERA_BANDS
    }
    specific_types = ("undercover", "online", "proactive", "reactive")

    for c in cases:
        lab = investigation_type_label(c)
        counts[lab] += 1
        year = parse_year(c.get("date_start"))
        ek = era_key_for_year(year)
        if ek is not None:
            era_key = next(f"{label} ({years})" for label, years, _, _ in ERA_BANDS if label == ek)
            by_era[era_key][lab] += 1

    n_specific = sum(counts.get(t, 0) for t in specific_types)
    n_unstated = counts.get("unstated", 0)
    n_unknown = counts.get("unknown", 0)

    return {
        "total_cases": n_total,
        "undercover_n": counts.get("undercover", 0),
        "online_n": counts.get("online", 0),
        "proactive_n": counts.get("proactive", 0),
        "reactive_n": counts.get("reactive", 0),
        "characterized_specific_n": n_specific,
        "unstated_n": n_unstated,
        "unknown_n": n_unknown,
        "definition": (
            "extract_investigation_info in processing.py: requires 'investigation' or "
            "'operation(s)' in case_text; checks undercover before proactive; subtype "
            "regex for undercover/online/proactive/reactive else 'unknown'"
        ),
        "by_era": {k: dict(v) for k, v in by_era.items()},
        "baseline_comparison": {
            "prior_undercover": BASELINE_INV_UNDERCOVER,
            "prior_online": BASELINE_INV_ONLINE,
            "prior_proactive": BASELINE_INV_PROACTIVE,
            "prior_unstated": BASELINE_INV_UNSTATED,
            "prior_characterized": BASELINE_INV_CHARACTERIZED,
            "delta_undercover": counts.get("undercover", 0) - BASELINE_INV_UNDERCOVER,
            "delta_online": counts.get("online", 0) - BASELINE_INV_ONLINE,
            "delta_proactive": counts.get("proactive", 0) - BASELINE_INV_PROACTIVE,
            "delta_unstated": n_unstated - BASELINE_INV_UNSTATED,
            "delta_characterized": n_specific - BASELINE_INV_CHARACTERIZED,
        },
    }


def print_claim_5(result: Dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("CLAIM 5 — Investigation type (undercover / online / proactive)")
    print("=" * 78)
    print(
        "Metric: investigation_type in extracted_features "
        "(extract_investigation_info on press-release text).\n"
        "  Characterized headline = undercover + online + proactive + reactive.\n"
        "  Unstated = no investigation/operation gate in narrative (field absent).\n"
        "  Unknown = gate matched but subtype phrase not found (footnote only).\n"
    )
    n = result["total_cases"]
    u, o, p, r = (
        result["undercover_n"],
        result["online_n"],
        result["proactive_n"],
        result["reactive_n"],
    )
    spec = result["characterized_specific_n"]
    print(f"Total cases:                         {n:,}")
    print(f"Characterized (specific subtypes):     {spec:,}")
    print(f"  undercover:                          {u:,}")
    print(f"  online:                              {o:,}")
    print(f"  proactive:                           {p:,}")
    print(f"  reactive:                            {r:,}")
    print(f"Unstated (no type extracted):          {result['unstated_n']:,}")
    print(f"Unknown (inv signal, no subtype):    {result['unknown_n']:,}")
    bl = result["baseline_comparison"]
    print(
        f"\nPublished baseline (~4,760 cases): characterized {bl['prior_characterized']:,} "
        f"(undercover {bl['prior_undercover']}, online {bl['prior_online']}, "
        f"proactive {bl['prior_proactive']}); unstated {bl['prior_unstated']:,}"
    )
    print(
        f"  → now characterized {spec:,} (Δ {bl['delta_characterized']:+d}); "
        f"unstated {result['unstated_n']:,} (Δ {bl['delta_unstated']:+d})"
    )
    print("\nBy era (specific subtypes only):")
    for label, years, _, _ in ERA_BANDS:
        key = f"{label} ({years})"
        era = result["by_era"].get(key, {})
        print(
            f"  Era {label}: undercover={era.get('undercover', 0)}, "
            f"online={era.get('online', 0)}, proactive={era.get('proactive', 0)}"
        )


def distinct_platform_count(blob: Any) -> int:
    """Distinct platforms_used strings (case-folded, min length 2)."""
    pl = platforms_list(blob)
    return len({x.casefold() for x in pl if len(x) >= 2})


def distinct_named_platform_count(blob: Any) -> int:
    """Distinct non-generic brand labels (excludes online / social media / chat)."""
    pl = platforms_list(blob)
    return len(
        {x.casefold() for x in pl if len(x) >= 2 and x.lower() not in _GENERIC_PLATFORMS}
    )


def analyze_hands_on_platforms(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Claim 6: ``hands_on`` topic vs distinct ``platforms_used`` count (association, not causal).

    Mirrors ``policy_research_stats.analyze_hands_on_platforms``.
    """
    hands_pl: List[int] = []
    other_pl: List[int] = []
    coh_h: List[int] = []
    coh_o: List[int] = []
    bins_all: Dict[str, Dict[str, int]] = {
        k: {"h": 0, "t": 0} for k in ("0", "1", "2+")
    }
    bins_named: Dict[str, Dict[str, int]] = {
        k: {"h": 0, "t": 0} for k in ("1", "2+")
    }

    for c in cases:
        T = topic_set(c.get("case_topics"))
        ho = "hands_on" in T
        n = distinct_platform_count(c.get("platforms_used"))
        nn = distinct_named_platform_count(c.get("platforms_used"))
        if ho:
            hands_pl.append(n)
        else:
            other_pl.append(n)
        if cohort_csam_possession(T):
            if ho:
                coh_h.append(n)
            else:
                coh_o.append(n)
        key = "0" if n == 0 else ("1" if n == 1 else "2+")
        bins_all[key]["t"] += 1
        if ho:
            bins_all[key]["h"] += 1
        if nn >= 1:
            nkey = "1" if nn == 1 else "2+"
            bins_named[nkey]["t"] += 1
            if ho:
                bins_named[nkey]["h"] += 1

    def mean(xs: List[int]) -> float:
        return statistics.mean(xs) if xs else 0.0

    def pct_hands(bin_d: Dict[str, int]) -> float:
        return 100.0 * bin_d["h"] / bin_d["t"] if bin_d["t"] else 0.0

    mh, mo = mean(hands_pl), mean(other_pl)
    ch, co = mean(coh_h), mean(coh_o)
    p1_all = pct_hands(bins_all["1"])
    p2_all = pct_hands(bins_all["2+"])
    p1_named = pct_hands(bins_named["1"])
    p2_named = pct_hands(bins_named["2+"])

    return {
        "total_cases": len(cases),
        "hands_on_n": len(hands_pl),
        "hands_on_mean_distinct_platforms": round(mh, 2),
        "other_mean_distinct_platforms": round(mo, 2),
        "mean_ratio_hands_on_vs_other": round(mh / mo, 2) if mo > 0 else None,
        "possession_csam_cohort_hands_on_n": len(coh_h),
        "possession_csam_cohort_hands_on_mean": round(ch, 2),
        "possession_csam_cohort_other_mean": round(co, 2),
        "possession_csam_cohort_mean_ratio": round(ch / co, 2) if co > 0 else None,
        "p_hands_on_given_0_platforms_pct": round(pct_hands(bins_all["0"]), 1),
        "p_hands_on_given_1_platform_pct": round(p1_all, 1),
        "p_hands_on_given_2plus_platforms_pct": round(p2_all, 1),
        "p_hands_on_2plus_vs_1_all_tags_ratio": round(p2_all / p1_all, 2) if p1_all > 0 else None,
        "p_hands_on_given_1_named_platform_pct": round(p1_named, 1),
        "p_hands_on_given_2plus_named_platforms_pct": round(p2_named, 1),
        "p_hands_on_2plus_vs_1_named_ratio": round(p2_named / p1_named, 2) if p1_named > 0 else None,
        "definition": (
            "hands_on in case_topics (extract_topics molest/hands on/sexually abused); "
            "distinct platforms_used per case (case-folded, len>=2); possession+CSAM cohort "
            "requires both possession and csam topics. Named = excludes online/social media/chat."
        ),
        "baseline_comparison": {
            "prior_hands_on_mean_platforms": BASELINE_HANDS_ON_MEAN_PLATFORMS,
            "prior_cohort_hands_on_mean": BASELINE_HANDS_ON_COHORT_MEAN_PLATFORMS,
            "prior_cohort_other_mean": BASELINE_HANDS_ON_COHORT_OTHER_MEAN,
            "delta_hands_on_mean": round(mh - BASELINE_HANDS_ON_MEAN_PLATFORMS, 2),
            "delta_cohort_hands_on_mean": round(ch - BASELINE_HANDS_ON_COHORT_MEAN_PLATFORMS, 2),
        },
    }


def print_claim_6(result: Dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("CLAIM 6 — Hands-on topic vs platform breadth")
    print("=" * 78)
    print(
        "Metric: distinct platforms_used per case; hands_on from case_topics.\n"
        "  Possession+CSAM cohort = both possession and csam topics (strict).\n"
        "  Association in press-derived tags only; not a causal claim.\n"
    )
    print(f"Total cases:                         {result['total_cases']:,}")
    print(f"hands_on cases:                      {result['hands_on_n']:,}")
    print(
        f"  mean distinct platforms (all):       {result['hands_on_mean_distinct_platforms']}  "
        f"(others {result['other_mean_distinct_platforms']}, "
        f"~{result['mean_ratio_hands_on_vs_other']}x)"
    )
    print(
        f"Possession+CSAM cohort — hands_on:     n={result['possession_csam_cohort_hands_on_n']:,}  "
        f"mean={result['possession_csam_cohort_hands_on_mean']}  "
        f"(others {result['possession_csam_cohort_other_mean']}, "
        f"~{result['possession_csam_cohort_mean_ratio']}x)"
    )
    print("\nP(hands_on | platform count) — all tags:")
    print(
        f"  0 platforms:  {result['p_hands_on_given_0_platforms_pct']}%  "
        f"  1: {result['p_hands_on_given_1_platform_pct']}%  "
        f"  2+: {result['p_hands_on_given_2plus_platforms_pct']}%  "
        f"(2+ vs 1 ratio {result['p_hands_on_2plus_vs_1_all_tags_ratio']}x)"
    )
    print(
        f"Named platforms only (excl. online/social media/chat), 1 vs 2+:\n"
        f"  1 named: {result['p_hands_on_given_1_named_platform_pct']}%  "
        f"  2+ named: {result['p_hands_on_given_2plus_named_platforms_pct']}%  "
        f"(ratio {result['p_hands_on_2plus_vs_1_named_ratio']}x — use for 'nearly double')"
    )
    bl = result["baseline_comparison"]
    print(
        f"\nPublished baseline (~2,532 cases, hands_on n=192): "
        f"mean {bl['prior_hands_on_mean_platforms']}; "
        f"possession+CSAM hands_on mean {bl['prior_cohort_hands_on_mean']} "
        f"vs other {bl['prior_cohort_other_mean']}"
    )
    print(
        f"  → now hands_on mean {result['hands_on_mean_distinct_platforms']} "
        f"(Δ {bl['delta_hands_on_mean']:+.2f}); "
        f"cohort hands_on mean {result['possession_csam_cohort_hands_on_mean']} "
        f"(Δ {bl['delta_cohort_hands_on_mean']:+.2f})"
    )


def print_claim_3(conc: Dict[str, Any], named: Dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("CLAIM 3 — Platform concentration + named-platform frequency")
    print("=" * 78)
    print(
        "Source: cases.platforms_used (regex extract_platforms on press-release text).\n"
        "  Generics online / social media / chat are modalities, not single products.\n"
    )
    n = conc["total_cases"]
    print(f"Total cases:                         {n:,}")
    print(f"Distinct platform labels:            {conc['distinct_platform_labels']}")
    print(f"Cases with >=1 platform tag:         {conc['cases_with_any_platform_tag']:,}  "
          f"({conc['cases_with_any_platform_pct']}%)")
    print(f"Top 3 surfaces:                      {', '.join(conc['top3_labels'])}")
    print(
        f"Cases touching >=1 of top 3:         {conc['cases_touching_top3']:,}  "
        f"({conc['top3_pct_of_corpus']}%)  [headline ~{conc['top3_pct_rounded_headline']}%]"
    )
    bl = conc["baseline_comparison"]
    print(
        f"\nPublished baseline: {bl['prior_distinct_platforms']} platforms, "
        f"{bl['prior_top3_pct']}% top-3  →  "
        f"now {conc['distinct_platform_labels']}, {conc['top3_pct_of_corpus']}%  "
        f"(Δ {bl['delta_top3_pct_points']:+.1f} pp)"
    )
    print("\nNamed platforms by frequency (listing count, current DB):")
    for row in named["rows"]:
        print(f"  {row['cases']:5,}  {row['display']}  ({row['pct_of_corpus']}%)")
    print("\n  Era breakdown (listing count):")
    for era_key, counts in named["by_era"].items():
        sm = counts.get("Social Media", 0)
        kik = counts.get("Kik Messenger", 0)
        fb = counts.get("Facebook / Meta", 0)
        on = counts.get("Online / Unspecified", 0)
        print(f"    {era_key}: online={on}, social_media={sm}, kik={kik}, facebook={fb}")


def print_claim_2(result: Dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("CLAIM 2 — CSAM as primary charge (csam topic proxy)")
    print("=" * 78)
    print(
        "Metric: case_topics contains 'csam' — material/charge language in press releases,\n"
        "  not sparse prosecution_outcomes JSON. Older releases often say 'sexual exploitation\n"
        "  of minors' without CSAM/child-porn labels, so Era I–II rates run lower.\n"
    )
    n = result["total_cases"]
    c = result["csam_topic_n"]
    print(f"Total cases:                         {n:,}")
    print(f"Cases with csam topic:               {c:,}  ({result['csam_topic_pct']}%)")
    print(f"Headline (rounded):                  {result['headline_pct_rounded']}%")
    print()
    print("By era (footnote):")
    for line in result["footnote_era_lines"]:
        print(f"  {line}")
    print(
        f"\n  Eras III–IV combined: {result['eras_iii_iv_csam_n']:,}/"
        f"{result['eras_iii_iv_n']:,} ({result['eras_iii_iv_csam_pct']}%) — "
        "relatively stable vs corpus-wide share once reporting language standardizes."
    )
    out_n = result.get("outside_report_era_window_n") or 0
    if out_n:
        print(
            f"  ({out_n:,} cases dated before 2010 included in corpus {result['headline_pct_rounded']}% "
            f"but excluded from era table; report eras start at 2010.)"
        )
    bl = result["baseline_comparison"]
    print(
        f"\nPublished baseline: {bl['prior_csam_topic_pct']}% "
        f"(~{bl['prior_csam_topic_n']:,} of ~{bl['prior_corpus_n']:,})  →  "
        f"now {result['csam_topic_pct']}% (n={c:,})  "
        f"(Δ {bl['delta_csam_topic_pct_points']:+.1f} pp)"
    )
    print()
    print("Template footnote:")
    era_note = (
        f"Era I–II lower (60–65%) where releases often say 'sexual exploitation of minors' "
        f"without CSAM/child-porn labels; Eras III–IV {result['eras_iii_iv_csam_pct']}% "
        f"({result['eras_iii_iv_csam_n']:,}/{result['eras_iii_iv_n']:,}), relatively stable."
    )
    pre2010 = result.get("outside_report_era_window_n") or 0
    pre_note = (
        f" {pre2010:,} cases dated before 2010 count in corpus total but outside era bands."
        if pre2010
        else ""
    )
    print(
        f"  Based on {c:,} of {n:,} cases (csam topic). {era_note}{pre_note} "
        + " ".join(result["footnote_era_lines"])
    )


def claim4_json_slice(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Drop bulky pair lists from JSON export; add Claim 4 headline fields."""
    skip = {"cross_rows", "text_hits", "aligned_hits"}
    out = {k: v for k, v in analysis.items() if k not in skip}
    geo = int(out.get("geographic_tf_roster") or BASELINE_CLAIM4_GEOGRAPHIC_TF)
    n_txt = int(out.get("narrative_hit_tf_count") or 0)
    n_align = int(out.get("aligned_pipeline_tf_count") or 0)
    n_src = int(out.get("distinct_ingest_source_count") or 0)
    per_tf = {r["label"]: r for r in out.get("per_tf", []) if isinstance(r, dict)}
    out["full_narrative_coverage_61"] = n_txt >= geo
    out["tier_a_status"] = [
        {
            "label": lab,
            "text_hit_pairs": per_tf.get(lab, {}).get("text_hit_pairs", 0),
            "aligned_hit_pairs": per_tf.get(lab, {}).get("aligned_hit_pairs", 0),
            "mapped_sources": per_tf.get(lab, {}).get("mapped_sources", []),
        }
        for lab in TIER_A_ZERO_NARRATIVE_LABELS
    ]
    out["baseline_comparison"] = {
        "prior_narrative_tf_count": BASELINE_CLAIM4_NARRATIVE_TF,
        "prior_aligned_tf_count": BASELINE_CLAIM4_ALIGNED_TF,
        "prior_distinct_ingest_sources": BASELINE_CLAIM4_DISTINCT_SOURCES,
        "delta_narrative_tf_count": n_txt - BASELINE_CLAIM4_NARRATIVE_TF,
        "delta_aligned_tf_count": n_align - BASELINE_CLAIM4_ALIGNED_TF,
        "delta_distinct_ingest_sources": n_src - BASELINE_CLAIM4_DISTINCT_SOURCES,
    }
    return out


def print_claim_4(result: Dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("CLAIM 4 — ICAC task force roster (61) vs corpus narrative + ingest source")
    print("=" * 78)
    print(
        "Roster: 61 geographic ICAC contact leads (+ military row in icac_tf_verify, not counted here).\n"
        "Narrative hit (text_hit_pairs > 0 per row):\n"
        "  • Agency needles on case_text [+ agencies_involved], after apostrophe normalization.\n"
        "  • Cook County: CCSAO token + flexible “state's attorney” regex.\n"
        "  • Hawaii: HICAC + Operation Keiki Shield needles.\n"
        "  • Mapped ingest: if cases.source is that row’s pipeline (e.g. SDPD, HI AG, CCSAO),\n"
        "    counts as narrative even when PDF text omits the full agency name.\n"
        "Aligned hit: narrative hit AND cases.source ∈ that row’s mapped ingest set.\n"
        "Cross-source / backlog: ``ingest_backlog`` and --missing-ingest-csv.\n"
    )
    print(f"Total cases:                              {result['total_cases']:,}")
    print(f"Distinct CaseLinker ingest sources:       {result['distinct_ingest_source_count']:,}")
    print(f"ICAC-like source names in mapping:        {result['icac_like_source_count']}")
    print()
    geo = result["geographic_tf_roster"]
    n_txt = result["narrative_hit_tf_count"]
    n_align = result["aligned_pipeline_tf_count"]
    n_src = result["distinct_ingest_source_count"]
    print(f"Geographic TF leads (roster):             {geo}")
    print(f"  ≥1 narrative hit:                       {n_txt} / {geo}")
    print(f"  ≥1 aligned pipeline hit:                {n_align} / {geo}")
    print(f"  ≥1 hit on any ICAC-like source:         {result['icac_like_source_tf_count']} / {geo}")
    print(f"  Missing aligned ingest (backlog):       {result['ingest_backlog_count']} / {geo}")
    full_cov = n_txt >= geo
    print(f"  Full 61/61 narrative coverage:          {'YES' if full_cov else 'NO'}")
    print()
    bl = {
        "prior_narrative_tf_count": BASELINE_CLAIM4_NARRATIVE_TF,
        "prior_aligned_tf_count": BASELINE_CLAIM4_ALIGNED_TF,
        "prior_distinct_ingest_sources": BASELINE_CLAIM4_DISTINCT_SOURCES,
    }
    print("Published baseline (~4,788-case corpus, before SDPD / HI AG / CCSAO feeds):")
    print(
        f"  Narrative TF rows:  {bl['prior_narrative_tf_count']}/{geo}  →  now {n_txt}/{geo}  "
        f"(Δ {n_txt - bl['prior_narrative_tf_count']:+d})"
    )
    print(
        f"  Aligned TF rows:    {bl['prior_aligned_tf_count']}/{geo}  →  now {n_align}/{geo}  "
        f"(Δ {n_align - bl['prior_aligned_tf_count']:+d})"
    )
    print(
        f"  Ingest sources:     {bl['prior_distinct_ingest_sources']}  →  now {n_src}  "
        f"(Δ {n_src - bl['prior_distinct_ingest_sources']:+d})"
    )
    print()
    per_tf = {r["label"]: r for r in result.get("per_tf", [])}
    print("Tier A (were 0 narrative hits on prior full corpus):")
    for lab in TIER_A_ZERO_NARRATIVE_LABELS:
        row = per_tf.get(lab, {})
        t = row.get("text_hit_pairs", 0)
        a = row.get("aligned_hit_pairs", 0)
        mapped = ", ".join(row.get("mapped_sources") or []) or "(none)"
        ok = "OK" if t > 0 else "MISSING"
        print(f"  [{ok}]  {lab}")
        print(f"        text_pairs={t}  aligned={a}  mapped={mapped}")
    print()
    no_txt = result["no_narrative_hit_labels"]
    if no_txt:
        print(f"No narrative hit ({len(no_txt)}) — add ingest + corpus depth:")
        for lab in no_txt:
            print(f"  • {lab}")
        print()
    else:
        print(f"No narrative hit: (none) — all {geo} geographic rows have ≥1 text hit.\n")
    print("Ingest backlog (no aligned cases) — top 15 by priority:")
    for row in result["ingest_backlog"][:15]:
        mapped = ", ".join(row["mapped_sources"]) if row["mapped_sources"] else "(none mapped)"
        print(
            f"  [{row['priority']}]  {row['label']}\n"
            f"      text_pairs={row['text_hit_pairs']}  aligned={row['aligned_hit_pairs']}  mapped={mapped}"
        )
    remaining = len(result["ingest_backlog"]) - 15
    if remaining > 0:
        print(f"  … and {remaining} more (see --missing-ingest-csv or JSON ingest_backlog)")
    print()
    print(
        f"Headline: {n_txt} of {geo} task forces appear in narrative"
        f"{' (full roster)' if full_cov else ''}; "
        f"{n_align} have dedicated ingest alignment "
        f"({n_src} distinct feeds vs {geo} roster leads)."
    )


def write_missing_ingest_csv(path: Path, analysis: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "priority",
                "task_force_label",
                "text_hit_pairs",
                "aligned_hit_pairs",
                "mapped_sources",
                "has_mapped_ingest",
            ]
        )
        for row in analysis["ingest_backlog"]:
            w.writerow(
                [
                    row["priority"],
                    row["label"],
                    row["text_hit_pairs"],
                    row["aligned_hit_pairs"],
                    "; ".join(row["mapped_sources"]),
                    row["has_mapped_ingest"],
                ]
            )


def print_claim_1(result: Dict[str, Any]) -> None:
    print("=" * 78)
    print("CLAIM 1 — CSAM possession cohort vs contact / hands-on signal")
    print("=" * 78)
    print(
        "Cohort: case_topics contains BOTH 'possession' AND 'csam'.\n"
        "Broad contact: hands_on topic OR scrubbed sexual_abuse regex on charges+narrative\n"
        "  OR statutory/contact substring tokens on original text (policy_research_stats).\n"
    )
    n = result["total_cases"]
    print(f"Total cases in database:                    {n:,}")
    n_src = result.get("distinct_ingest_sources")
    if n_src is not None:
        print(
            f"Distinct ingest sources (cases.source):   {n_src:,}  "
            f"(ICAC-like mapped slots in repo: {result.get('icac_like_source_slots', '?')}; "
            f"61-TF roster → Claim 4)"
        )
    print(f"Cases with csam topic:                      {result['csam_topic_cases']:,}  ({result['csam_topic_pct_of_corpus']}% of corpus)")
    print(f"Cases with possession topic (any):          {result['possession_topic_cases']:,}")
    print()
    c = result["possession_and_csam_cohort"]
    b = result["contact_broad_n"]
    h = result["hands_on_topic_n"]
    print(f"Cohort (possession + csam topics):          {c:,}")
    print(f"  … broad contact / hands-on signal:        {b:,}  ({result['contact_broad_pct_of_cohort']}%)")
    print(f"  … explicit hands_on topic only:             {h:,}  ({result['hands_on_topic_pct_of_cohort']}%)")
    print(f"  … broad signal, NOT hands_on topic:         {result['contact_broad_not_hands_on_topic_n']:,}")
    print(f"  … severity_indicators sexual_abuse (cohort): {result['severity_sexual_abuse_in_cohort_n']:,}")
    print()
    print("Published baseline (~2,000-case corpus):")
    bl = result["baseline_comparison"]
    print(f"  Prior cohort n={bl['prior_cohort_n']:,}  →  now {c:,}  (Δ {bl['delta_cohort_n']:+,})")
    print(
        f"  Prior broad contact {bl['prior_contact_broad_pct']}% (n={bl['prior_contact_broad_n']})  →  "
        f"now {result['contact_broad_pct_of_cohort']}% (n={b})  (Δ {bl['delta_contact_broad_pct_points']:+.1f} pp, n {bl['delta_contact_broad_n']:+,})"
    )
    print(
        f"  Prior hands_on topic n={bl['prior_hands_on_topic_n']}  →  "
        f"now {h}  (Δ {bl['delta_hands_on_topic_n']:+,})"
    )
    print()
    one_in = round(c / b) if b else 0
    if b and c:
        print(
            f"Headline: ~{result['contact_broad_pct_of_cohort']:.0f}% of CSAM possession cases "
            f"carry a contact or hands-on signal "
            f"(~1 in {one_in} at n={c:,}; broad n={b}, explicit topic n={h})."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CaseLinker published claims.")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"SQLite path (default: CASELINKER_DB or {DEFAULT_DB})",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write machine-readable results to this path",
    )
    parser.add_argument(
        "--missing-ingest-csv",
        type=Path,
        default=None,
        help="Write Claim 4 ingest backlog (TFs without aligned pipeline) for source expansion",
    )
    args = parser.parse_args()
    db = args.db or Path(os.environ.get("CASELINKER_DB", "").strip() or DEFAULT_DB)

    if not db.exists():
        print(f"Database not found: {db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db))
    try:
        cases = load_cases(conn)
        prosecution = load_prosecution(conn)
        tf_analysis = analyze_icac_task_forces(conn, include_agencies=True)
        claim1 = analyze_csam_and_contact(cases, prosecution)
        claim1["distinct_ingest_sources"] = tf_analysis["distinct_ingest_source_count"]
        claim1["icac_like_source_slots"] = tf_analysis["icac_like_source_count"]
        claim2 = analyze_csam_primary_charge(cases)
        claim3_conc = analyze_platform_concentration(cases)
        claim3_named = analyze_named_platform_frequency(cases)
        claim5 = analyze_investigation_types(cases)
        claim6 = analyze_hands_on_platforms(cases)
        claim4 = claim4_json_slice(tf_analysis)
    finally:
        conn.close()

    print(f"Database: {db.resolve()}\n")
    print_claim_1(claim1)
    print_claim_2(claim2)
    print_claim_3(claim3_conc, claim3_named)
    print_claim_5(claim5)
    print_claim_6(claim6)
    print_claim_4(tf_analysis)

    payload = {
        "database": str(db.resolve()),
        "claims": {
            "csam_possession_contact": claim1,
            "csam_primary_charge": claim2,
            "platform_concentration": claim3_conc,
            "named_platform_frequency": claim3_named,
            "investigation_types": claim5,
            "hands_on_platform_breadth": claim6,
            "icac_task_forces": claim4,
        },
    }

    if args.json:
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote JSON: {args.json}")

    if args.missing_ingest_csv:
        write_missing_ingest_csv(args.missing_ingest_csv, tf_analysis)
        print(f"Wrote ingest backlog CSV: {args.missing_ingest_csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
