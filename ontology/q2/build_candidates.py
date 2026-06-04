#!/usr/bin/env python3
"""
Stage 1 (Q2): Build candidates.json — offense subset → case IDs.

Research strata align with CaseLinker case_topics, charge clusters, and CAC graph
event typing. Subsets are not mutually exclusive; a case may qualify for several.

Stub: writes empty scaffold until DB query logic is implemented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

DB = "caselinker.db"
OUT = Path("ontology/q2/candidates.json")

# Keep in sync with q2_evidence.py and visualization/questions/q02.html SUBSET_GROUPS.
SUBSETS: Dict[str, Dict[str, str]] = {
    "familial_abuse": {
        "subset_label": "Familial & custodial abuse",
        "criteria_note": (
            "family in case_topics and hands_on, production, and/or custodial relationship "
            "(relative, parent, guardian) in relationship_to_victim or graph custodial typing."
        ),
    },
    "online_grooming": {
        "subset_label": "Online grooming",
        "criteria_note": (
            "grooming in case_topics (merge-layer semantic) or GroomingSolicitation / "
            "OnlineGrooming events in the CAC graph."
        ),
    },
    "sextortion": {
        "subset_label": "Sextortion",
        "criteria_note": (
            "sextortion in case_topics, sextortion charge cluster, or SextortionIncident "
            "in the knowledge graph."
        ),
    },
    "trafficking": {
        "subset_label": "Trafficking & exploitation networks",
        "criteria_note": (
            "trafficking in case_topics or trafficking / multi-victim coercion language "
            "in charges or narrative (rings, forced conduct, commercial exploitation)."
        ),
    },
    "production": {
        "subset_label": "CSAM production",
        "criteria_note": (
            "production in case_topics (phrase-level production cues) or ProductionOffense "
            "in the CAC graph — creating new abuse imagery, not only possessing existing material."
        ),
    },
    "possession_distribution": {
        "subset_label": "Possession & distribution (online)",
        "criteria_note": (
            "possession, csam, and/or distribution in case_topics without hands_on — "
            "trading, downloading, disseminating, or collecting CSAM online."
        ),
    },
    "hands_on_possessor": {
        "subset_label": "Possessors with hands-on signal",
        "criteria_note": (
            "(possession, csam, or distribution) plus hands_on — material offending where "
            "the narrative also signals physical contact or hands-on abuse."
        ),
    },
    "ai_csam": {
        "subset_label": "AI-generated / synthetic CSAM",
        "criteria_note": (
            "ai_csam in case_topics or DigitallyGeneratedCSAMIncident in the graph — "
            "generative-AI or synthetic depictions as a charging or investigative focus."
        ),
    },
}


class CandidateBuilder:
    """Stage-1 builder: map each research subset to qualifying case IDs."""

    def __init__(self, db_path: str = DB) -> None:
        self.db_path = db_path

    def build(self) -> Dict[str, Any]:
        """Return candidates payload. Stub returns empty lists per subset."""
        by_subset: Dict[str, List[Dict[str, Any]]] = {sid: [] for sid in SUBSETS}
        flat: List[Dict[str, Any]] = []
        total_cases = 0
        total_pairs = 0

        return {
            "summary": {
                "total_candidate_cases": total_cases,
                "total_subset_case_pairs": total_pairs,
                "subsets_defined": len(SUBSETS),
                "skipped": {},
                "_stub": True,
            },
            "by_subset": by_subset,
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
    for sid, meta in SUBSETS.items():
        print(f"  {sid}: {meta['subset_label']}")


if __name__ == "__main__":
    main()
