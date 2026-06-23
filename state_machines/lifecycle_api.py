"""Build /api/lifecycle/cases payload from L* computation output."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from state_machines.iris import (
    CANONICAL_CASE_IDS,
    CASE_META,
    LSTAR_JSON,
    REPO_ROOT,
    STATE_MACHINES_WORKSPACE,
    display_type,
    infer_modality,
    local_name,
    modality_label,
)
from state_machines.trajectory import cross_case_comparison


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


def _canonical_fundamental(data: dict[str, Any]) -> list[str]:
    sequences = {
        case_id: data["cases"][case_id]["phase_sequence"]
        for case_id in CANONICAL_CASE_IDS
        if case_id in data.get("cases", {})
    }
    return cross_case_comparison(sequences)["fundamental"]


def _canonical_type_cases(data: dict[str, Any]) -> dict[str, list[str]]:
    sequences = {
        case_id: data["cases"][case_id]["phase_sequence"]
        for case_id in CANONICAL_CASE_IDS
        if case_id in data.get("cases", {})
    }
    return cross_case_comparison(sequences)["type_cases"]


def _build_case_record(
    case_id: str,
    block: dict[str, Any],
    meta: dict[str, Any],
    *,
    tier: str,
    type_cases: dict[str, list[str]],
    fundamental: list[str],
    affordance_rows: list[dict[str, Any]],
    n_canonical: int,
) -> dict[str, Any]:
    modality = infer_modality(case_id, meta)
    phase_details = block.get("phase_details", [])
    phases = []
    for phase in phase_details:
        ptype = phase.get("type", "")
        coverage = len(type_cases.get(ptype, []))
        phases.append(
            {
                **phase,
                "type_display": display_type(ptype),
                "short_type": local_name(ptype),
                "coverage": coverage,
                "is_fundamental": ptype in fundamental,
            }
        )

    title = meta.get("title", case_id.upper())
    if tier == "expansion":
        offense_type = modality_label(modality)
        case_name = meta.get("corpus_id") or case_id
    else:
        offense_type = title
        case_name = title

    return {
        "id": case_id,
        "tier": tier,
        "case_name": case_name,
        "citation": block.get("citation") or meta.get("citation", ""),
        "offense_type": offense_type,
        "modality": modality,
        "modality_label": modality_label(modality),
        "corpus_id": meta.get("corpus_id"),
        "defendant": meta.get("defendant"),
        "trajectory": block.get("phase_sequence", []),
        "trajectory_display": [
            display_type(t) for t in block.get("phase_sequence", [])
        ],
        "phases": phases,
        "transitions": _transitions_for_case(phase_details, affordance_rows),
        "path_weight": block.get("path_weight"),
        "n_canonical": n_canonical,
    }


def build_lifecycle_payload(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    data = raw if raw is not None else _ensure_lstar_json()
    fundamental = _canonical_fundamental(data)
    type_cases = _canonical_type_cases(data)
    n_canonical = len(CANONICAL_CASE_IDS)
    affordance_rows = data.get("affordance_annotations", [])
    all_cases = data.get("cases", {})

    canonical_cases: list[dict[str, Any]] = []
    for case_id in CANONICAL_CASE_IDS:
        block = all_cases.get(case_id, {})
        meta = CASE_META.get(case_id, {})
        canonical_cases.append(
            _build_case_record(
                case_id,
                block,
                meta,
                tier="canonical",
                type_cases=type_cases,
                fundamental=fundamental,
                affordance_rows=affordance_rows,
                n_canonical=n_canonical,
            )
        )

    expansion_cases: list[dict[str, Any]] = []
    for case_id in sorted(all_cases):
        if case_id in CANONICAL_CASE_IDS:
            continue
        block = all_cases[case_id]
        meta = CASE_META.get(case_id, {})
        expansion_cases.append(
            _build_case_record(
                case_id,
                block,
                meta,
                tier="expansion",
                type_cases=type_cases,
                fundamental=fundamental,
                affordance_rows=affordance_rows,
                n_canonical=n_canonical,
            )
        )

    cross_case: dict[str, dict[str, Any]] = {}
    for iri, cases in type_cases.items():
        cross_case[iri] = {
            "count": len(cases),
            "cases": cases,
            "display": display_type(iri),
            "short_name": local_name(iri),
        }

    shared_transitions = len(data.get("raw_transitions", []))
    canonical_types = set()
    for case in canonical_cases:
        for phase in case["phases"]:
            canonical_types.add(phase.get("type"))

    return {
        "n_cases": data.get("n_cases", n_canonical),
        "n_canonical": n_canonical,
        "n_expansion": len(expansion_cases),
        "canonical_stage_count": len(canonical_types),
        "shared_transition_count": shared_transitions,
        "fundamental": fundamental,
        "fundamental_display": [display_type(t) for t in fundamental],
        "cross_case": cross_case,
        "affordance_annotations": affordance_rows,
        "canonical_cases": canonical_cases,
        "expansion_cases": expansion_cases,
        "cases": canonical_cases,
    }
