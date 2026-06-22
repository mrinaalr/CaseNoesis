"""L*_{g,A} computation over PACER CAC-native state machine graphs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
REPO_ROOT = WORKSPACE.parent
sys.path.insert(0, str(REPO_ROOT))

from state_machines.iris import (  # noqa: E402
    CASE_META,
    EXPLOITATION_PHASE,
    INITIAL_CONTACT_PHASE,
    LSTAR_JSON,
    display_type,
    local_name,
)
from state_machines.sparql_queries import (  # noqa: E402
    affordance_on_arrival,
    case_graphs,
    load_state_machine_graphs,
    ordered_phase_sequence,
    ordered_type_sequence,
    phase_metadata,
    query_affordance_annotations,
    query_phases_per_case,
    query_transition_matrix,
    weighted_transition_matrix,
)
from state_machines.trajectory import (  # noqa: E402
    compute_lstar,
    cross_case_comparison,
    path_weight_for_sequence,
)

OUTPUT_PATH = LSTAR_JSON


def _case_id_from_graph(graph_uri: str) -> str:
    return graph_uri.rsplit(":", 1)[-1]


def _format_phase_line(
    index: int,
    meta: dict,
    aff_class: str | None,
    is_terminal: bool,
) -> list[str]:
    lines = []
    type_display = display_type(meta["type"] or "")
    terminal = " [TERMINAL]" if is_terminal else ""
    lines.append(f"  {index}. {type_display}{terminal}")
    if meta["label"]:
        detail = meta["label"]
        if meta["comment"]:
            detail += f" — {meta['comment'].split('.')[0]}"
        lines.append(f'     "{detail}"')
    if aff_class:
        lines.append(f"     Affordance on arrival: {local_name(aff_class)}")
    return lines


def main() -> None:
    cg = load_state_machine_graphs()
    matrix, n_cases = weighted_transition_matrix(cg)
    raw_transitions = query_transition_matrix(cg)
    affordances = query_affordance_annotations(cg)
    phases_per_case = query_phases_per_case(cg)

    sequences: dict[str, list[str]] = {}
    case_results: dict[str, dict] = {}

    global_lstar = compute_lstar(matrix, INITIAL_CONTACT_PHASE, EXPLOITATION_PHASE, n_cases)

    for graph in case_graphs(cg):
        case_id = _case_id_from_graph(str(graph))
        phase_uris = ordered_phase_sequence(cg, graph)
        type_seq = ordered_type_sequence(cg, graph)
        sequences[case_id] = type_seq
        path_weight, step_weights = path_weight_for_sequence(type_seq, matrix)

        phase_details = []
        for i, uri in enumerate(phase_uris, start=1):
            meta = phase_metadata(cg, graph, uri)
            aff, _ = affordance_on_arrival(cg, graph, uri)
            phase_details.append(
                {
                    **meta,
                    "affordance_on_arrival": aff,
                    "index": i,
                    "is_terminal": i == len(phase_uris),
                }
            )

        case_lstar = compute_lstar(matrix, INITIAL_CONTACT_PHASE, EXPLOITATION_PHASE, n_cases)
        case_lstar["case_sequence"] = type_seq
        case_lstar["case_path_weight"] = path_weight
        case_lstar["case_step_weights"] = {
            f"{a}|{b}": w for (a, b), w in step_weights.items()
        }
        case_lstar["weights"] = {
            f"{a}|{b}": w for (a, b), w in case_lstar["weights"].items()
        }

        meta = CASE_META.get(case_id, {"title": case_id.upper(), "citation": case_id})
        case_results[case_id] = {
            "title": meta["title"],
            "citation": meta["citation"],
            "phase_sequence": type_seq,
            "phase_details": phase_details,
            "lstar": case_lstar,
            "path_weight": path_weight,
        }

        print("═" * 55)
        print(f"{meta['title']} — {meta['citation']}")
        print("═" * 55)
        print("Phases (CAC-native):")
        for i, uri in enumerate(phase_uris, start=1):
            meta_p = phase_metadata(cg, graph, uri)
            aff, _ = affordance_on_arrival(cg, graph, uri)
            for line in _format_phase_line(
                i, meta_p, aff, is_terminal=(i == len(phase_uris))
            ):
                print(line)

        traj = " → ".join(display_type(t) for t in type_seq)
        all_one = path_weight == 1.0 or abs(path_weight - 1.0) < 1e-9
        weight_note = (
            f"All weights 1.0 (N={n_cases} — degenerate but correct)"
            if all_one
            else f"weighted by cross-case frequencies (N={n_cases})"
        )
        print(f"\nL*_{{g,A}} (N={n_cases}): {traj}")
        print(f"Path weight: {path_weight:.4f} | {weight_note}")
        print("─" * 55)
        print()

    comparison = cross_case_comparison(sequences)

    print("═" * 55)
    print(f"CROSS-CASE COMPARISON (all {n_cases} offense types)")
    print("═" * 55)
    print("Fundamental (appears in all 5):")
    print(
        "  "
        + ", ".join(display_type(t) for t in comparison["fundamental"])
        or "  (none)"
    )
    print("\nVariant stages:")
    for t, count in comparison["variant"]:
        cases = comparison["type_cases"][t]
        print(f"  {local_name(t):24} {count}/{n_cases}  ({', '.join(cases)})")
    if comparison["unique"]:
        print("\nUnique (one case only):")
        for t in comparison["unique"]:
            cases = comparison["type_cases"][t]
            print(f"  {local_name(t):24} ({cases[0]})")

    payload = {
        "n_cases": n_cases,
        "transition_matrix": {
            f"{display_type(a)} → {display_type(b)}": w
            for (a, b), w in sorted(matrix.items())
        },
        "raw_transitions": [
            {
                "from": display_type(str(r["from_type"])),
                "to": display_type(str(r["to_type"])),
                "case_count": int(r["case_count"]),
                "weight": matrix.get(
                    (str(r["from_type"]), str(r["to_type"])), 0.0
                ),
            }
            for r in raw_transitions
        ],
        "affordance_annotations": [
            {
                "from": display_type(str(r["from_type"])),
                "to": display_type(str(r["to_type"])),
                "affordance": local_name(str(r["affordance_class"])),
                "case_count": int(r["case_count"]),
            }
            for r in affordances
        ],
        "phases_sparql": [
            {
                "case": _case_id_from_graph(str(r["case_graph"])),
                "phase": str(r["phase"]),
                "type": display_type(str(r["phase_type"])),
            }
            for r in phases_per_case
        ],
        "global_lstar": {
            **{
                **global_lstar,
                "weights": {
                    f"{a}|{b}": w
                    for (a, b), w in global_lstar["weights"].items()
                },
            },
            "trajectory_display": [display_type(t) for t in global_lstar["trajectory"]],
        },
        "cases": case_results,
        "cross_case_comparison": {
            **comparison,
            "fundamental_display": [display_type(t) for t in comparison["fundamental"]],
            "variant_display": [
                (display_type(t), count) for t, count in comparison["variant"]
            ],
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
