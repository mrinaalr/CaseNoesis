#!/usr/bin/env python3
"""
Count ICAC task-force contact rows whose lead-agency names (and common aliases)
appear in case narrative text (raw_data.case_text), optionally augmented by
extracted_features.agencies_involved joined as text.

Usage:
  python3 scripts/icac_tf_text_hits.py
  python3 scripts/icac_tf_text_hits.py --db /path/to/caselinker.db

Does not modify the database. Requires sqlite3 + populated cases rows.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# Canonical row id (aligned to ICAC "Task Force Contacts" lead agencies) →
# case-insensitive substring needles (prefer longer / specific phrases to reduce FP).
# Abbreviations use word-boundary regex; phrases use plain `in` on a lowercased haystack.
TF_ROWS: List[Tuple[str, Sequence[str | re.Pattern]]] = [
    ("AL — Alabama Law Enforcement Agency", ("alabama law enforcement agency", re.compile(r"\balea\b", re.I))),
    ("AK — Anchorage Police Department", ("anchorage police department", re.compile(r"\bapd\b.*anchorage|anchorage.*\bapd\b", re.I))),
    ("AZ — Phoenix Police Department", ("phoenix police department", "phoenix police", re.compile(r"\bppd\b.*phoenix|phoenix.*\bppd\b", re.I))),
    ("AR — Arkansas State Police", ("arkansas state police", re.compile(r"\basp\b.*arkansas|arkansas state patrol", re.I))),
    ("CA — Fresno County Sheriff's Office", ("fresno county sheriff", "fresno sheriff")),
    ("CA — Los Angeles Police Department", ("los angeles police department", re.compile(r"\blapd\b", re.I))),
    ("CA — Sacramento County Sheriff's Office", ("sacramento county sheriff", "sacramento sheriff")),
    ("CA — San Diego Police Department", ("san diego police department", re.compile(r"\bsdpd\b", re.I))),
    ("CA — San Jose Police Department", ("san jose police department", re.compile(r"\bsjpd\b", re.I))),
    ("CO — Colorado Springs Police Department", ("colorado springs police department", re.compile(r"\bcspd\b.*colorado springs", re.I))),
    ("CT — Connecticut State Police", ("connecticut state police", re.compile(r"\bcsp\b.*connecticut", re.I))),
    ("DE — Delaware Department of Justice", ("delaware department of justice",)),
    ("FL — Central (Osceola County Sheriff's Office)", ("osceola county sheriff",)),
    ("FL — Northern (Gainesville Police Department)", ("gainesville police department", re.compile(r"\bgpd\b.*gainesville", re.I))),
    ("FL — Southern (Broward County Sheriff's Office)", ("broward county sheriff", "broward sheriff's office", "broward sheriff")),
    ("GA — Georgia Bureau of Investigation", ("georgia bureau of investigation", re.compile(r"\bgbi\b", re.I))),
    ("HI — Hawaii Department of the Attorney General", ("hawaii department of the attorney general", "hawaii attorney general")),
    ("ID — Idaho Office of Attorney General", ("idaho office of the attorney general", "idaho attorney general")),
    ("IL — Illinois Office of the Attorney General", ("illinois attorney general", "illinois office of the attorney general")),
    ("IL — Cook County State's Attorney's Office", ("cook county state's attorney", "cook county state attorney")),
    ("IN — Indiana State Police", ("indiana state police", re.compile(r"\bisp\b.*indiana", re.I))),
    ("IA — Iowa Division of Criminal Investigation", ("iowa division of criminal investigation", "iowa dci")),
    ("KS — Sedgwick County Sheriff's Office", ("sedgwick county sheriff", "wichita.*sheriff")),
    ("KY — Kentucky State Police", ("kentucky state police", re.compile(r"\bksp\b", re.I))),
    ("LA — Louisiana Department of Justice", ("louisiana department of justice", "louisiana attorney general")),
    ("ME — Maine State Police", ("maine state police",)),
    ("MD — Maryland State Police", ("maryland state police", re.compile(r"\bmsp\b.*maryland", re.I))),
    ("MA — Massachusetts State Police", ("massachusetts state police",)),
    ("MI — Michigan State Police", ("michigan state police", re.compile(r"\bmsp\b.*michigan|michigan.*\bmsp\b", re.I))),
    ("MN — Minnesota Bureau of Criminal Apprehension", ("minnesota bureau of criminal apprehension", re.compile(r"\bbca\b.*minnesota", re.I))),
    ("MS — Mississippi Office of the Attorney General", ("mississippi attorney general", "mississippi office of the attorney general")),
    ("MO — St. Charles County Police Department", ("st. charles county police", "st charles county police")),
    ("MT — Montana Division of Criminal Investigation", ("montana division of criminal investigation", "montana dci", "montana department of justice")),
    ("NE — Nebraska State Patrol", ("nebraska state patrol",)),
    ("NV — Las Vegas Metropolitan Police Department", ("las vegas metropolitan police", "las vegas metro police", re.compile(r"\blvmpd\b", re.I))),
    ("NH — Portsmouth Police Department", ("portsmouth police department", re.compile(r"\bppd\b.*portsmouth", re.I))),
    ("NJ — New Jersey State Police", ("new jersey state police", re.compile(r"\bnjsp\b", re.I))),
    ("NM — New Mexico Attorney General's Office", ("new mexico attorney general", "new mexico department of justice")),
    ("NY — New York State Police", ("new york state police", re.compile(r"\bnysp\b", re.I))),
    ("NY — New York City Police Department", ("new york city police department", re.compile(r"\bnypd\b", re.I))),
    ("NC — North Carolina State Bureau of Investigation", ("north carolina state bureau of investigation", "north carolina sbi", re.compile(r"\bncsbi\b", re.I))),
    ("ND — North Dakota Bureau of Criminal Investigation", ("north dakota bureau of criminal investigation", "north dakota bci")),
    ("OH — Cuyahoga County Prosecuting Attorney's Office", ("cuyahoga county prosecuting attorney", "cuyahoga county prosecutor")),
    ("OK — Oklahoma State Bureau of Investigation", ("oklahoma state bureau of investigation", "oklahoma osbi", re.compile(r"\bosbi\b.*oklahoma", re.I))),
    ("OR — Oregon Department of Justice", ("oregon department of justice", "oregon attorney general")),
    ("PA — Delaware County District Attorney's Office", ("delaware county district attorney", "delaware county prosecutor")),
    ("RI — Rhode Island State Police", ("rhode island state police", re.compile(r"\brisp\b", re.I))),
    ("SC — South Carolina Attorney General's Office", ("south carolina attorney general",)),
    ("SD — South Dakota Division of Criminal Investigation", ("south dakota division of criminal investigation", "south dakota dci")),
    ("TN — Knoxville Police Department", ("knoxville police department", re.compile(r"\bkpd\b.*knoxville", re.I))),
    ("TX — Office of the Attorney General of Texas", ("office of the attorney general of texas", "texas attorney general")),
    ("TX — Dallas Police Department", ("dallas police department", re.compile(r"\bdpd\b.*dallas", re.I))),
    ("TX — Houston Police Department", ("houston police department", re.compile(r"\bhpd\b.*houston", re.I))),
    ("UT — Utah Office of the Attorney General", ("utah attorney general", "utah office of the attorney general")),
    ("VT — Vermont Office of the Attorney General", ("vermont attorney general", "vermont office of the attorney general")),
    ("VA — Virginia State Police", ("virginia state police", re.compile(r"\bvsp\b.*virginia", re.I))),
    ("VA — Bedford County Sheriff's Office", ("bedford county sheriff",)),
    ("WA — Seattle Police Department", ("seattle police department", re.compile(r"\bspd\b.*seattle|seattle.*\bspd\b", re.I))),
    ("WV — West Virginia State Police", ("west virginia state police",)),
    ("WI — Wisconsin Department of Justice", ("wisconsin department of justice", "wisconsin attorney general")),
    ("WY — Wyoming Division of Criminal Investigation", ("wyoming division of criminal investigation", "wyoming dci")),
    ("U.S. — Armed Forces / military investigative agencies", ("army criminal investigation", "ncis", "air force office of special investigations", "afosi", "coast guard investig", "military criminal investigative")),
]


def _haystack(case_text: str, agencies_blob: str) -> str:
    parts = [case_text or "", agencies_blob or ""]
    return "\n".join(parts).lower()


def _matches(needle: str | re.Pattern, hay: str) -> bool:
    if isinstance(needle, re.Pattern):
        return needle.search(hay) is not None
    return needle.lower() in hay


def run(db_path: Path, include_agencies: bool) -> None:
    if not db_path.is_file():
        print(f"No database at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM cases")
    (n_rows,) = cur.fetchone()

    hits: Dict[str, int] = {label: 0 for label, _ in TF_ROWS}
    cases_with_any = 0

    q = "SELECT raw_data, extracted_features FROM cases"
    for raw_json, ex_json in cur.execute(q):
        try:
            raw = json.loads(raw_json) if raw_json else {}
        except (TypeError, json.JSONDecodeError):
            raw = {}
        ct = raw.get("case_text") if isinstance(raw.get("case_text"), str) else ""
        agencies_txt = ""
        if include_agencies and ex_json:
            try:
                ex = json.loads(ex_json) if isinstance(ex_json, str) else ex_json
            except (TypeError, json.JSONDecodeError):
                ex = None
            if isinstance(ex, dict):
                ag = ex.get("agencies_involved")
                if isinstance(ag, list):
                    agencies_txt = " ".join(str(x) for x in ag if x)
                elif isinstance(ag, str):
                    agencies_txt = ag
        hay = _haystack(ct, agencies_txt)
        matched_here = False
        for label, needles in TF_ROWS:
            if any(_matches(n, hay) for n in needles):
                hits[label] += 1
                matched_here = True
        if matched_here:
            cases_with_any += 1

    conn.close()

    ranked = sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))
    n_tf_with_hits = sum(1 for _, c in ranked if c > 0)

    print("=== ICAC task-force contact rows: name/alias hits in case text ===")
    print(f"Database: {db_path}")
    print(f"Total cases (rows): {n_rows}")
    print(f"Cases matching at least one TF row: {cases_with_any}")
    print(f"Distinct TF rows with ≥1 case hit: {n_tf_with_hits} / {len(TF_ROWS)}")
    print(f"> 52 TF rows with hits? {'YES' if n_tf_with_hits > 52 else 'NO'}")
    print()
    print("Rank (TF row → case count):")
    for label, cnt in ranked:
        if cnt == 0:
            continue
        print(f"  {cnt:6d}  {label}")
    zero_labels = [label for label, c in ranked if c == 0]
    print()
    print(f"TF rows with 0 hits ({len(zero_labels)}):")
    for z in zero_labels:
        print(f"  — {z}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("CASELINKER_DB", REPO_ROOT / "caselinker.db")),
    )
    ap.add_argument(
        "--no-agencies",
        action="store_true",
        help="Only raw_data.case_text (ignore extracted_features.agencies_involved)",
    )
    args = ap.parse_args()
    run(args.db, include_agencies=not args.no_agencies)


if __name__ == "__main__":
    main()
