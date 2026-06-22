"""Build /api/lifecycle/cases payload from L* computation output."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from state_machines.iris import (
    CASE_META,
    LSTAR_JSON,
    REPO_ROOT,
    STATE_MACHINES_WORKSPACE,
    display_type,
    local_name,
)

CASE_ORDER = ("enticement", "production", "sextortion", "enterprise", "trafficking")


def _ensure_lstar_json() -> dict[str, Any]:
    if LSTAR_JSON.is_file():
        return json.loads(LSTAR_JSON.read_text(encoding="utf-8"))
    script = STATE_MACHINES_WORKSPACE / "compute_lstar.py"
    subprocess.run([sys.executable, str(script)], check=True, cwd=REPO_ROOT)
    return json.loads(LSTAR_JSON.read_text(encoding="utf-8"))


def load_lstar_raw() -> dict[str, Any]:
    """Return full state_machines/data/lstar_all_cases.json (compute if missing)."""
    return _ensure_lstar_json()


def _transitions_for_case(
    phase_details: list[dict[str, Any]],
    affordance_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    for i in range(len(phase_details) - 1):
        src = phase_details[i]
        dst = phase_details[i + 1]
        aff_iri = dst.get("affordance_on_arrival")
        aff_name = local_name(aff_iri) if aff_iri else None
        if aff_name:
            for row in affordance_rows:
                if (
                    row.get("from") == display_type(src["type"])
                    and row.get("to") == display_type(dst["type"])
                    and row.get("affordance") == aff_name
                ):
                    break
        transitions.append(
            {
                "from_uri": src["uri"],
                "to_uri": dst["uri"],
                "from_type": src["type"],
                "to_type": dst["type"],
                "from_label": src.get("label"),
                "to_label": dst.get("label"),
                "affordance": aff_iri,
                "affordance_name": aff_name,
            }
        )
    return transitions


def build_lifecycle_payload(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    data = raw if raw is not None else _ensure_lstar_json()
    comparison = data.get("cross_case_comparison", {})
    type_cases = comparison.get("type_cases", {})
    fundamental = comparison.get("fundamental") or comparison.get("backbone", [])
    n_cases = data.get("n_cases", 5)

    cross_case: dict[str, dict[str, Any]] = {}
    for iri, cases in type_cases.items():
        cross_case[iri] = {
            "count": len(cases),
            "cases": cases,
            "display": display_type(iri),
            "short_name": local_name(iri),
        }

    cases_out: list[dict[str, Any]] = []
    for case_id in CASE_ORDER:
        block = data.get("cases", {}).get(case_id, {})
        meta = CASE_META.get(case_id, {})
        phase_details = block.get("phase_details", [])
        phases = []
        for p in phase_details:
            ptype = p.get("type", "")
            coverage = len(type_cases.get(ptype, []))
            phases.append(
                {
                    **p,
                    "type_display": display_type(ptype),
                    "short_type": local_name(ptype),
                    "coverage": coverage,
                    "is_fundamental": ptype in fundamental,
                }
            )
        cases_out.append(
            {
                "id": case_id,
                "case_name": meta.get("title", case_id.upper()),
                "citation": block.get("citation") or meta.get("citation", ""),
                "offense_type": meta.get("title", case_id.upper()),
                "trajectory": block.get("phase_sequence", []),
                "trajectory_display": [
                    display_type(t) for t in block.get("phase_sequence", [])
                ],
                "phases": phases,
                "transitions": _transitions_for_case(
                    phase_details, data.get("affordance_annotations", [])
                ),
                "path_weight": block.get("path_weight"),
            }
        )

    shared_transitions = len(data.get("raw_transitions", []))
    canonical_types = set()
    for case in cases_out:
        for p in case["phases"]:
            canonical_types.add(p.get("type"))

    return {
        "n_cases": n_cases,
        "canonical_stage_count": len(canonical_types),
        "shared_transition_count": shared_transitions,
        "fundamental": fundamental,
        "fundamental_display": [display_type(t) for t in fundamental],
        "cross_case": cross_case,
        "affordance_annotations": data.get("affordance_annotations", []),
        "cases": cases_out,
    }
