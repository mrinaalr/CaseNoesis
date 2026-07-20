"""SPARQL transition-function queries over CAC-native PACER state machine graphs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rdflib import ConjunctiveGraph, Graph, URIRef
from rdflib.namespace import RDF, RDFS

from state_machines.iris import (
    AFFORDANCE_CLASS,
    AFFORDANCE_MISUSE,
    CAC_INVESTIGATION,
    CASE_FILES,
    DISRUPTED_TARGET,
    DISRUPTS_CHAIN,
    ENABLES_TRANSITION_FROM,
    ENABLES_TRANSITION_TO,
    HAS_STEP,
    MISUSE_DESCRIPTION,
    PHASE,
    PRECEDES,
    GRAPHS_DIR,
    SKOS_DEFINITION,
    SKOS_PREF_LABEL,
    TERMINAL_POLARITY,
    TRAJ_ASSERTS_STATE,
    TRAJ_AT_INTERVAL,
    TRAJ_ENACTS_ACTION,
    TRAJ_FROM_STATE,
    TRAJ_HAS_PHASE_ASSERTION,
    TRAJ_HAS_TRANSITION,
    TRAJ_INITIAL_STATE,
    TRAJ_IS_TERMINAL,
    TRAJ_PHASE_ASSERTION,
    TRAJ_SEQUENCE_INDEX,
    TRAJ_STATE_MACHINE_MODEL,
    TRAJ_TERMINAL_POLARITY,
    TRAJ_TO_STATE,
    TRAJ_TRAJECTORY,
    TRAJ_TRANSITION,
    UCO_ACTION_INSTRUMENT,
    esm_display_name,
    local_name,
)

QUERY_PHASES = """
PREFIX cac-core: <https://cacontology.projectvic.org/core#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?case_graph ?phase ?phase_type
WHERE {
  GRAPH ?case_graph {
    ?phase rdf:type ?phase_type .
    ?phase_type rdfs:subClassOf* cac-core:Phase .
  }
}
ORDER BY ?case_graph ?phase
"""

QUERY_TRANSITION_MATRIX = """
PREFIX cac-core: <https://cacontology.projectvic.org/core#>
PREFIX noesis: <https://ontology.casenoesis.project/noesis/offense-trajectories#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?from_type ?to_type (COUNT(DISTINCT ?case_graph) AS ?case_count)
WHERE {
  GRAPH ?case_graph {
    ?from_phase rdf:type ?from_type .
    ?to_phase rdf:type ?to_type .
    ?from_phase (cac-core:precedes|noesis:precedes) ?to_phase .
  }
}
GROUP BY ?from_type ?to_type
ORDER BY DESC(?case_count)
"""

QUERY_AFFORDANCE_ANNOTATIONS = """
PREFIX cac-platforms: <https://cacontology.projectvic.org/platforms#>
PREFIX noesis: <https://ontology.casenoesis.project/noesis/offense-trajectories#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?from_type ?to_type ?affordance_class (COUNT(DISTINCT ?case_graph) AS ?case_count)
WHERE {
  GRAPH ?case_graph {
    {
      ?misuse rdf:type noesis:AffordanceMisuse .
      ?misuse noesis:enablesTransitionFrom ?from_phase .
      ?misuse noesis:enablesTransitionTo ?to_phase .
      ?misuse noesis:affordanceClass ?affordance_class .
    }
    UNION
    {
      ?misuse rdf:type cac-platforms:AffordanceMisuse .
      ?misuse cac-platforms:enablesTransitionFrom ?from_phase .
      ?misuse cac-platforms:enablesTransitionTo ?to_phase .
      ?misuse cac-platforms:affordanceClass ?affordance_class .
    }
    ?from_phase rdf:type ?from_type .
    ?to_phase rdf:type ?to_type .
  }
}
GROUP BY ?from_type ?to_type ?affordance_class
ORDER BY DESC(?case_count)
"""


def _rdflib_format_for(path: Path) -> str:
    """CAC CSAM graphs are JSON-LD; SDK trajectories ESM graphs are Turtle."""
    return "turtle" if path.suffix.lower() in (".ttl", ".turtle") else "json-ld"


def load_state_machine_graphs(
    directory: Path | None = None,
    filenames: tuple[str, ...] = CASE_FILES,
) -> ConjunctiveGraph:
    """Load case graphs into a ConjunctiveGraph (one named graph per file).

    Handles both CAC-native JSON-LD CSAM graphs and real CASE-UCO SDK
    trajectories ESM graphs (Turtle) transparently, keyed by file suffix.
    """
    directory = directory or GRAPHS_DIR
    cg = ConjunctiveGraph(identifier=URIRef("urn:caselinker:state-machines"))
    for filename in filenames:
        path = directory / filename
        graph_uri = URIRef(f"urn:caselinker:case:{path.stem}")
        g = Graph()
        g.parse(data=path.read_text(encoding="utf-8"), format=_rdflib_format_for(path))
        ctx = cg.get_context(graph_uri)
        for triple in g:
            ctx.add(triple)
    return cg


def known_case_graph_uris(
    filenames: tuple[str, ...] = CASE_FILES,
) -> list[URIRef]:
    return [URIRef(f"urn:caselinker:case:{Path(f).stem}") for f in filenames]


def _rows(graph: ConjunctiveGraph, query: str) -> list[dict[str, Any]]:
    return [
        {str(k): v for k, v in row.asdict().items()}
        for row in graph.query(query)
    ]


def query_phases_per_case(graph: ConjunctiveGraph) -> list[dict[str, Any]]:
    return _rows(graph, QUERY_PHASES)


def query_transition_matrix(graph: ConjunctiveGraph) -> list[dict[str, Any]]:
    return _rows(graph, QUERY_TRANSITION_MATRIX)


def query_affordance_annotations(graph: ConjunctiveGraph) -> list[dict[str, Any]]:
    return _rows(graph, QUERY_AFFORDANCE_ANNOTATIONS)


def weighted_transition_matrix(
    graph: ConjunctiveGraph,
    filenames: tuple[str, ...] = CASE_FILES,
) -> tuple[dict[tuple[str, str], float], int]:
    """Return ((from_type, to_type) -> weight), N case graphs."""
    n = len(filenames)
    raw = query_transition_matrix(graph)
    matrix: dict[tuple[str, str], float] = {}
    for row in raw:
        key = (str(row["from_type"]), str(row["to_type"]))
        matrix[key] = int(row["case_count"]) / n if n else 0.0
    return matrix, n


def _ctx(cg: ConjunctiveGraph, case_graph: URIRef) -> Graph:
    return cg.get_context(case_graph)


def _phase_nodes_in_graph(cg: ConjunctiveGraph, case_graph: URIRef) -> set[str]:
    ctx = _ctx(cg, case_graph)
    sequence_predicates = (
        URIRef(PRECEDES),
        URIRef("https://ontology.casenoesis.project/noesis/offense-trajectories#precedes"),
    )
    nodes: set[str] = set()
    for inv in ctx.subjects(RDF.type, URIRef(CAC_INVESTIGATION)):
        for step in ctx.objects(inv, URIRef(HAS_STEP)):
            nodes.add(str(step))
    for sequence_predicate in sequence_predicates:
        for s, _, o in ctx.triples((None, sequence_predicate, None)):
            nodes.add(str(s))
            nodes.add(str(o))
    return nodes


def ordered_phase_sequence(cg: ConjunctiveGraph, case_graph: URIRef) -> list[str]:
    """
    Follow cac-core:precedes from the node with no incoming edge to the terminal node.
    Includes all hasStep nodes in traversal order.
    """
    nodes = _phase_nodes_in_graph(cg, case_graph)
    if not nodes:
        return []

    incoming: dict[str, set[str]] = {n: set() for n in nodes}
    outgoing: dict[str, str | None] = {n: None for n in nodes}

    ctx = _ctx(cg, case_graph)
    sequence_predicates = (
        URIRef(PRECEDES),
        URIRef("https://ontology.casenoesis.project/noesis/offense-trajectories#precedes"),
    )
    for sequence_predicate in sequence_predicates:
        for s, _, o in ctx.triples((None, sequence_predicate, None)):
            s_id, o_id = str(s), str(o)
            if s_id in nodes and o_id in nodes:
                incoming[o_id].add(s_id)
                outgoing[s_id] = o_id

    starts = [n for n in nodes if not incoming[n]]
    if not starts:
        return sorted(nodes)
    if len(starts) > 1:
        step_order = []
        for inv in ctx.subjects(RDF.type, URIRef(CAC_INVESTIGATION)):
            step_order.extend(str(s) for s in ctx.objects(inv, URIRef(HAS_STEP)))
        starts.sort(key=lambda n: step_order.index(n) if n in step_order else 999)
    start = starts[0]

    sequence: list[str] = []
    current: str | None = start
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        sequence.append(current)
        current = outgoing.get(current)

    return sequence


def phase_type_for_instance(cg: ConjunctiveGraph, case_graph: URIRef, phase_uri: str) -> str | None:
    ctx = _ctx(cg, case_graph)
    skip = {
        str(RDF.Property),
        str(RDFS.Resource),
        "http://www.w3.org/2002/07/owl#NamedIndividual",
    }
    types = [
        str(t)
        for _, _, t in ctx.triples((URIRef(phase_uri), RDF.type, None))
        if str(t) not in skip and not str(t).endswith("AffordanceMisuse")
    ]
    if not types:
        return None
    specific = [t for t in types if t != PHASE]
    return specific[0] if specific else types[0]


def ordered_type_sequence(cg: ConjunctiveGraph, case_graph: URIRef) -> list[str]:
    return [
        t
        for uri in ordered_phase_sequence(cg, case_graph)
        if (t := phase_type_for_instance(cg, case_graph, uri)) is not None
    ]


def affordance_on_arrival(
    cg: ConjunctiveGraph,
    case_graph: URIRef,
    phase_uri: str,
) -> tuple[str | None, str | None]:
    """Return (affordance_class_iri, misuse_description) for transition into phase_uri."""
    ctx = _ctx(cg, case_graph)
    affordance_patterns = (
        (
            URIRef(AFFORDANCE_MISUSE),
            URIRef(ENABLES_TRANSITION_TO),
            URIRef(AFFORDANCE_CLASS),
            URIRef(MISUSE_DESCRIPTION),
        ),
        (
            URIRef("https://cacontology.projectvic.org/platforms#AffordanceMisuse"),
            URIRef("https://cacontology.projectvic.org/platforms#enablesTransitionTo"),
            URIRef("https://cacontology.projectvic.org/platforms#affordanceClass"),
            URIRef("https://cacontology.projectvic.org/platforms#misuseDescription"),
        ),
    )
    for misuse_type, transition_to, affordance_class, misuse_description in affordance_patterns:
        for misuse in ctx.subjects(RDF.type, misuse_type):
            target = ctx.value(misuse, transition_to)
            if target and str(target) == phase_uri:
                aff = ctx.value(misuse, affordance_class)
                desc = ctx.value(misuse, misuse_description)
                return (str(aff) if aff else None, str(desc) if desc else None)
    return None, None


def phase_metadata(
    cg: ConjunctiveGraph,
    case_graph: URIRef,
    phase_uri: str,
) -> dict[str, str | None]:
    ctx = _ctx(cg, case_graph)
    node = URIRef(phase_uri)
    label = ctx.value(node, RDFS.label)
    comment = ctx.value(node, RDFS.comment)
    ptype = phase_type_for_instance(cg, case_graph, phase_uri)
    disrupts = ctx.value(node, URIRef(DISRUPTS_CHAIN))
    disrupted = ctx.value(node, URIRef(DISRUPTED_TARGET))
    disrupts_chain = disrupts is not None and str(disrupts).lower() in ("true", "1")
    terminal_polarity = ctx.value(node, URIRef(TERMINAL_POLARITY))
    return {
        "uri": phase_uri,
        "type": ptype,
        "label": str(label) if label else None,
        "comment": str(comment) if comment else None,
        "disrupts_chain": disrupts_chain,
        "disrupted_target": str(disrupted) if disrupted else None,
        "terminal_polarity": str(terminal_polarity) if terminal_polarity else None,
    }


def case_graphs(
    cg: ConjunctiveGraph,
    filenames: tuple[str, ...] = CASE_FILES,
) -> list[URIRef]:
    return known_case_graph_uris(filenames)


# ===========================================================================
# ESM branch — read real CASE-UCO SDK trajectories graphs natively.
#
# These graphs use traj:Trajectory / traj:PhaseAssertion / traj:Transition /
# traj:StateMachineModel over per-domain SKOS state schemes (ef:/ex:/traf:) or
# case-local traj:State instances (racketeering). There is NO cac-core:precedes
# spine and NO noesis:AffordanceMisuse edge; the abused affordance rides on
# uco-action:instrument of the transition's enactsAction. Nothing here touches
# the CAC readers above.
# ===========================================================================

_UCO_CORE_NAME = URIRef("https://ontology.unifiedcyberontology.org/uco/core/name")
_UCO_CORE_DESCRIPTION = URIRef("https://ontology.unifiedcyberontology.org/uco/core/description")


def is_esm_graph(cg: ConjunctiveGraph, case_graph: URIRef) -> bool:
    """True when the named graph carries a traj:Trajectory (SDK ESM graph)."""
    ctx = _ctx(cg, case_graph)
    return any(ctx.subjects(RDF.type, URIRef(TRAJ_TRAJECTORY)))


def _esm_state_chain_from_model(cg: ConjunctiveGraph, case_graph: URIRef) -> list[str]:
    """Ordered state IRIs from the StateMachineModel: initialState, then the
    unique fromState->toState transition chain. Handles multi-trajectory graphs
    (e.g. elder_scheme) where sequenceIndex alone would interleave paths."""
    ctx = _ctx(cg, case_graph)
    next_state: dict[str, str] = {}
    for tr in ctx.subjects(RDF.type, URIRef(TRAJ_TRANSITION)):
        frm = ctx.value(tr, URIRef(TRAJ_FROM_STATE))
        to = ctx.value(tr, URIRef(TRAJ_TO_STATE))
        if frm is not None and to is not None:
            next_state[str(frm)] = str(to)

    start = None
    for model in ctx.subjects(RDF.type, URIRef(TRAJ_STATE_MACHINE_MODEL)):
        init = ctx.value(model, URIRef(TRAJ_INITIAL_STATE))
        if init is not None:
            start = str(init)
            break
    if start is None:
        targets = set(next_state.values())
        sources = [s for s in next_state if s not in targets]
        start = sources[0] if sources else None
    if start is None:
        return []

    chain: list[str] = []
    seen: set[str] = set()
    cur: str | None = start
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = next_state.get(cur)
    return chain


def _esm_assertions_by_state(cg: ConjunctiveGraph, case_graph: URIRef) -> dict[str, list[dict[str, Any]]]:
    """state IRI -> list of PhaseAssertion metadata dicts, sorted by sequenceIndex."""
    ctx = _ctx(cg, case_graph)
    out: dict[str, list[dict[str, Any]]] = {}
    for pa in ctx.subjects(RDF.type, URIRef(TRAJ_PHASE_ASSERTION)):
        state = ctx.value(pa, URIRef(TRAJ_ASSERTS_STATE))
        if state is None:
            continue
        seq = ctx.value(pa, URIRef(TRAJ_SEQUENCE_INDEX))
        is_terminal = ctx.value(pa, URIRef(TRAJ_IS_TERMINAL))
        polarity = ctx.value(pa, URIRef(TRAJ_TERMINAL_POLARITY))
        desc = ctx.value(pa, _UCO_CORE_DESCRIPTION)
        rec = {
            "assertion": str(pa),
            "sequence_index": int(seq) if seq is not None else 999,
            "is_terminal": str(is_terminal).lower() in ("true", "1") if is_terminal is not None else False,
            "terminal_polarity": str(polarity) if polarity is not None else None,
            "description": str(desc) if desc is not None else None,
        }
        out.setdefault(str(state), []).append(rec)
    for recs in out.values():
        recs.sort(key=lambda r: r["sequence_index"])
    return out


def esm_ordered_states(cg: ConjunctiveGraph, case_graph: URIRef) -> list[str]:
    """Canonical ordered state IRIs for the ESM machine.

    Primary: StateMachineModel transition chain. Fallback: the longest single
    trajectory's PhaseAssertions ordered by sequenceIndex mapped to assertsState.
    """
    chain = _esm_state_chain_from_model(cg, case_graph)
    if chain:
        return chain
    ctx = _ctx(cg, case_graph)
    best: list[str] = []
    for traj in ctx.subjects(RDF.type, URIRef(TRAJ_TRAJECTORY)):
        ordered: list[tuple[int, str]] = []
        for pa in ctx.objects(traj, URIRef(TRAJ_HAS_PHASE_ASSERTION)):
            state = ctx.value(pa, URIRef(TRAJ_ASSERTS_STATE))
            seq = ctx.value(pa, URIRef(TRAJ_SEQUENCE_INDEX))
            if state is not None:
                ordered.append((int(seq) if seq is not None else 999, str(state)))
        ordered.sort()
        states = [s for _, s in ordered]
        if len(states) > len(best):
            best = states
    return best


_DOMAIN_STATE_LABELS: dict[str, str] | None = None


def _domain_state_label_map() -> dict[str, str]:
    """skos:prefLabel / uco-core:name from SDK domain-extension T-Boxes (ef/ex/traf).

    Instance graphs reference those State IRIs but do not restate the labels;
    pull them once from the sibling CASE-UCO-SDK checkout when available.
    """
    global _DOMAIN_STATE_LABELS
    if _DOMAIN_STATE_LABELS is not None:
        return _DOMAIN_STATE_LABELS

    labels: dict[str, str] = {}
    # CaseNoesis and CASE-UCO-SDK are sibling repos under Projects/
    sdk_root = Path(__file__).resolve().parents[2] / "CASE-UCO-SDK" / "extensions"
    for folder in ("elder-fraud", "extortion", "trafficking"):
        path = sdk_root / folder / f"{folder}.ttl"
        if not path.is_file():
            continue
        g = Graph()
        try:
            g.parse(path, format="turtle")
        except Exception:  # noqa: BLE001
            continue
        for s, _, o in g.triples((None, URIRef(SKOS_PREF_LABEL), None)):
            labels[str(s)] = str(o)
        for s, _, o in g.triples((None, _UCO_CORE_NAME, None)):
            labels.setdefault(str(s), str(o))
    _DOMAIN_STATE_LABELS = labels
    return labels


def _humanize_camel_local_name(name: str) -> str:
    """InitialAccess → 'Initial access'; EarningsCollection → 'Earnings collection'."""
    if not name:
        return name
    if " " in name or "-" in name:
        return name
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    if not spaced:
        return name
    return spaced[0].upper() + spaced[1:].lower()


def _esm_ui_label(state_iri: str, pref: str | None, name: str | None) -> str:
    """Human-readable phase name for swimlane headers/cards — never a prefixed IRI."""
    for candidate in (pref, name, _domain_state_label_map().get(state_iri)):
        if candidate and str(candidate).strip():
            text = str(candidate).strip()
            # Drop accidental prefix if a label was stored as 'ex:Demand'
            if ":" in text and " " not in text and "/" not in text:
                text = text.rsplit(":", 1)[-1]
                return _humanize_camel_local_name(text)
            return text
    return _humanize_camel_local_name(local_name(state_iri))


def esm_state_display(state_iri: str) -> str:
    """Compact ontology id for logs / tooling (ef:InitialContact, …). Not a UI label."""
    return esm_display_name(state_iri)


def esm_state_metadata(
    cg: ConjunctiveGraph,
    case_graph: URIRef,
    state_iri: str,
    assertions_by_state: dict[str, list[dict[str, Any]]] | None = None,
    is_last: bool = False,
) -> dict[str, Any]:
    """Occupancy metadata for a state: label (skos/name/humanized), blurb, terminal."""
    ctx = _ctx(cg, case_graph)
    node = URIRef(state_iri)
    pref = ctx.value(node, URIRef(SKOS_PREF_LABEL))
    name = ctx.value(node, _UCO_CORE_NAME)
    definition = ctx.value(node, URIRef(SKOS_DEFINITION))
    label = _esm_ui_label(
        state_iri,
        str(pref) if pref is not None else None,
        str(name) if name is not None else None,
    )

    assertions_by_state = assertions_by_state or _esm_assertions_by_state(cg, case_graph)
    recs = assertions_by_state.get(state_iri, [])
    # Terminal status is a property of the last machine state; use its assertion.
    terminal_rec = next((r for r in recs if r["is_terminal"]), None)
    blurb = str(definition) if definition is not None else (recs[0]["description"] if recs else None)
    is_terminal = is_last and terminal_rec is not None
    return {
        "uri": state_iri,
        "type": state_iri,          # ESM state IRI is its own type identity
        "state_display": esm_state_display(state_iri),  # ontology id (logs / badge)
        "label": label,             # human UI label (no prefix, spaced)
        "comment": blurb,
        "definition": str(definition) if definition is not None else None,
        "terminal_polarity": terminal_rec["terminal_polarity"] if terminal_rec else None,
        "is_terminal": is_terminal,
        "disrupts_chain": False,
        "disrupted_target": None,
    }


def esm_affordance_on_arrival(
    cg: ConjunctiveGraph,
    case_graph: URIRef,
    state_iri: str,
) -> tuple[str | None, str | None]:
    """(affordance_label, misuse_description) from the incoming transition's
    enactsAction -> uco-action:instrument. Empty for the initial state."""
    ctx = _ctx(cg, case_graph)
    for tr in ctx.subjects(RDF.type, URIRef(TRAJ_TRANSITION)):
        to = ctx.value(tr, URIRef(TRAJ_TO_STATE))
        if to is None or str(to) != state_iri:
            continue
        for action in ctx.objects(tr, URIRef(TRAJ_ENACTS_ACTION)):
            instrument = ctx.value(action, URIRef(UCO_ACTION_INSTRUMENT))
            if instrument is None:
                continue
            inst_name = ctx.value(instrument, _UCO_CORE_NAME)
            inst_desc = ctx.value(instrument, _UCO_CORE_DESCRIPTION)
            action_desc = ctx.value(action, _UCO_CORE_DESCRIPTION)
            label = str(inst_name) if inst_name is not None else local_name(str(instrument))
            desc = str(inst_desc or action_desc or "")
            return label, (desc or None)
    return None, None


def esm_case_summary(cg: ConjunctiveGraph, case_graph: URIRef) -> dict[str, Any]:
    """Native ESM read: ordered own-state sequence + per-state occupancy details
    + affordance-on-arrival. Shapes align with the CAC case block keys the
    lifecycle payload consumes (phase_sequence / phase_details / transitions)."""
    states = esm_ordered_states(cg, case_graph)
    assertions_by_state = _esm_assertions_by_state(cg, case_graph)
    n = len(states)
    phase_details: list[dict[str, Any]] = []
    for i, state_iri in enumerate(states, start=1):
        meta = esm_state_metadata(
            cg, case_graph, state_iri, assertions_by_state, is_last=(i == n)
        )
        aff_label, aff_desc = esm_affordance_on_arrival(cg, case_graph, state_iri)
        phase_details.append(
            {
                **meta,
                "index": i,
                "affordance_on_arrival": aff_label,
                "affordance_on_arrival_desc": aff_desc,
            }
        )
    return {
        "machine_kind": "esm",
        "phase_sequence": states,
        "phase_sequence_display": [esm_state_display(s) for s in states],
        "phase_details": phase_details,
    }
