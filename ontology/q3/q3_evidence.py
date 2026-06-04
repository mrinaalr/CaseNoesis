#!/usr/bin/env python3
"""
Q3 intervention-evidence extraction — stub pipeline.

For each (case_id, intervention_point) in candidates.json: read case_text,
classify intervention signals and leverage evidence, tier stated/inferred/named_only.

Seven intervention points (see build_candidates.INTERVENTION_POINTS).

Outputs:
  ontology/q3/q3_evidence.json
  ontology/q3/q3_intervention_table.md  (evidence base; synthesis manual in q3_interventions.json)
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_candidates import INTERVENTION_POINTS  # noqa: E402

CANDIDATES_FILE = Path("ontology/q3/candidates.json")
OUTPUT_DIR = Path("ontology/q3")


class Q3EvidenceExtractor:
    """Stage-2 extractor: case_text → per-point intervention evidence records."""

    def __init__(self, candidates_path: Path = CANDIDATES_FILE) -> None:
        self.candidates_path = candidates_path

    def load_candidates(self) -> Dict[str, Any]:
        if not self.candidates_path.is_file():
            return {"flat": [], "by_point": {pid: [] for pid in INTERVENTION_POINTS}}
        with open(self.candidates_path, encoding="utf-8") as f:
            return json.load(f)

    def process_case(
        self, case_id: str, points: List[str], case_text: str
    ) -> Dict[str, Any]:
        """Per-case extraction. Stub returns no records until text rules are wired."""
        _ = (case_id, points, case_text)
        return {"records": [], "exclusions": []}

    def run(self, test_mode: bool = False) -> Dict[str, Any]:
        candidates = self.load_candidates()
        case_to_points: Dict[str, List[str]] = {}
        for entry in candidates.get("flat", []):
            pid = entry.get("point", entry.get("point_id", entry.get("subset", "")))
            for cid in entry.get("case_ids", []):
                case_to_points.setdefault(cid, []).append(pid)

        all_case_ids = sorted(case_to_points.keys())
        if test_mode:
            all_case_ids = all_case_ids[:50]

        all_records: List[Dict[str, Any]] = []
        all_exclusions: List[Dict[str, str]] = []

        for case_id in all_case_ids:
            result = self.process_case(case_id, case_to_points[case_id], "")
            all_records.extend(result["records"])
            all_exclusions.extend(result["exclusions"])

        return {
            "_meta": {
                "generated": str(date.today()),
                "cases_processed": len(all_case_ids),
                "evidence_records": len(all_records),
                "exclusions": len(all_exclusions),
                "_stub": True,
            },
            "records": all_records,
            "excluded_cases": all_exclusions,
        }

    def write_outputs(self, payload: Dict[str, Any]) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "q3_evidence.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        self._write_intervention_table_md(payload)
        print("Wrote q3_evidence.json", flush=True)
        print("Wrote q3_intervention_table.md", flush=True)

    def _write_intervention_table_md(self, payload: Dict[str, Any]) -> None:
        lines = [
            "# Q3 Intervention-Point Evidence Table",
            "",
            "> Intervention synthesis lives in `q3_interventions.json` (manual). "
            "This file is the empirical evidence base.",
            "",
            f"Records: {len(payload.get('records', []))}",
            "",
        ]
        if not payload.get("records"):
            lines.append("*(empty — run pipeline after candidates are populated)*")
        (OUTPUT_DIR / "q3_intervention_table.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


def main() -> None:
    test_mode = "--test" in sys.argv
    extractor = Q3EvidenceExtractor()
    payload = extractor.run(test_mode=test_mode)
    extractor.write_outputs(payload)
    print(f"Cases processed: {payload['_meta']['cases_processed']}")
    print(f"Evidence records: {payload['_meta']['evidence_records']}")


if __name__ == "__main__":
    main()
