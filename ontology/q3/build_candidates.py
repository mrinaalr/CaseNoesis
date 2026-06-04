#!/usr/bin/env python3
"""
Stage 1 (Q3): Build candidates.json — intervention point → case IDs.

Maps corpus cases to kill-chain / intervention stages where press releases
describe detection, reporting, investigation, legal action, or safeguarding.
Cases may qualify for multiple points. Subsets cross-link Q1 (platform affordances)
and Q2 (lifecycle phases).

Stub: writes empty scaffold until DB query logic is implemented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

DB = "caselinker.db"
OUT = Path("ontology/q3/candidates.json")

# Keep in sync with q3_evidence.py and visualization/questions/q03.html INTERVENTION_GROUPS.
INTERVENTION_POINTS: Dict[str, Dict[str, str]] = {
    "platform_prevention": {
        "point_label": "Platform design & pre-offense prevention",
        "criteria_note": (
            "Platform policy, integrity tooling, or design-level mitigation named in narrative; "
            "links Q1 affordances to upstream prevention (before contact or offense commission)."
        ),
    },
    "detection_monitoring": {
        "point_label": "Detection & proactive monitoring",
        "criteria_note": (
            "Proactive detection: P2P/hash matching, undercover operations, platform automated "
            "referrals, or proactive ICAC/federal monitoring — offense surfaced before victim report."
        ),
    },
    "reporting_intake": {
        "point_label": "Reporting & intake",
        "criteria_note": (
            "CyberTip, NCMEC, ESP/platform report, public tip line, or victim/guardian report "
            "as the stated intake that opened the case."
        ),
    },
    "investigation_attribution": {
        "point_label": "Investigation & attribution",
        "criteria_note": (
            "ICAC task force, multi-agency investigation, forensic attribution, undercover chat, "
            "or international coordination — involvesAgency patterns in CAC graph."
        ),
    },
    "legal_intervention": {
        "point_label": "Legal intervention (warrant / arrest / seizure)",
        "criteria_note": (
            "Search warrant execution, arrest, device seizure, or takedown action described as "
            "the operational disruption point (InitialPhase / investigation step in graph)."
        ),
    },
    "prosecution_disruption": {
        "point_label": "Prosecution & post-arrest disruption",
        "criteria_note": (
            "Charge, indictment, plea, conviction, sentence, or registration — "
            "LegalProcessPhase / SentencingPhase in lifecycle graph."
        ),
    },
    "victim_safeguarding": {
        "point_label": "Victim identification & safeguarding",
        "criteria_note": (
            "Victim removal, CPS engagement, victim-ID appeals, or safeguarding actions "
            "explicitly described alongside enforcement."
        ),
    },
}


class CandidateBuilder:
    """Stage-1 builder: map each intervention point to qualifying case IDs."""

    def __init__(self, db_path: str = DB) -> None:
        self.db_path = db_path

    def build(self) -> Dict[str, Any]:
        """Return candidates payload. Stub returns empty lists per point."""
        by_point: Dict[str, List[Dict[str, Any]]] = {
            pid: [] for pid in INTERVENTION_POINTS
        }
        flat: List[Dict[str, Any]] = []
        total_cases = 0
        total_pairs = 0

        return {
            "summary": {
                "total_candidate_cases": total_cases,
                "total_point_case_pairs": total_pairs,
                "points_defined": len(INTERVENTION_POINTS),
                "skipped": {},
                "_stub": True,
            },
            "by_point": by_point,
            "flat": flat,
        }

    def write(self, path: Path | str = OUT) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.build(), indent=2), encoding="utf-8")


def main() -> None:
    builder = CandidateBuilder()
    builder.write()
    print(f"Wrote {OUT} (stub — empty candidate lists)")
    for pid, meta in INTERVENTION_POINTS.items():
        print(f"  {pid}: {meta['point_label']}")


if __name__ == "__main__":
    main()
