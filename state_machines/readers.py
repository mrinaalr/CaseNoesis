"""Readers: any source into walks.

    from_conduct   acts read from a record (extraction/conduct.py), placed at ESM track states
    from_graph     trajectories in a graph of the SDK's trajectories extension, in any alphabet
    from_json      walks written by any other extractor, with any extra states they use
    read           a .ttl or .json file, whichever it is

**Acts to states.** Each act kind has a role, and the role says what the act
can reach:

    prepare    setup                       start -> Preparation
    reach      contact, recruit, access    start, Preparation -> Solicitation, Recruitment, Intrusion
    deceive    deception                   -> Deception, unless coercion is already held
    coerce     threat, control             -> Coercion
    press      demand, transport           keep the leverage held; if none yet, Conditioning
    extract    transfer, exploit           -> ValueTaken, PersonExploited
    deliver    supply                      -> ContrabandSupplied
    after      movement, concealment       after the goal: -> Laundering, Concealment. Before: no change

An act that reaches nothing new is an event that stays in its state. A
demand says nothing on its own about whether the victim is deceived or
coerced, so it leaves the walk at Conditioning until an act does.
Leverage after the goal is the same leverage; the scheme turns it into
Maintenance when the walk is projected.

**Graphs to walks.** A trajectory's phase assertions, in sequence order,
each asserting a state. A state is placed by the crosswalk, or by a
skos:closeMatch, exactMatch, broadMatch or broader the graph itself
gives to a placed state. A state placed by neither is kept in the source
layer, unplaced above it, and counted. The action is the domain
technique the transition enacts, else `(step)`. A last assertion with
terminalPolarity "disrupted" ends the walk by detection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from state_machines.scheme import DETECTED, START, STOP, Scheme, State, local_name
from state_machines.walks import Event, Walk, from_dict

ROLE = {
    "setup": "prepare",
    "contact": "reach", "recruit": "reach", "access": "reach",
    "deception": "deceive", "threat": "coerce", "control": "coerce",
    "demand": "press", "transport": "press",
    "transfer": "extract", "exploit": "extract",
    "supply": "deliver",
    "movement": "after", "concealment": "after",
}
ENTRY = {"contact": "Solicitation", "recruit": "Recruitment", "access": "Intrusion",
         "transfer": "ValueTaken", "exploit": "PersonExploited", "supply": "ContrabandSupplied",
         "movement": "Laundering", "concealment": "Concealment"}
NEEDS = ("Preparation", "Conditioning", "Deception", "Coercion", *ENTRY.values())


def _means(act: dict[str, Any]) -> tuple[str, ...]:
    means = act.get("means") or {}
    return tuple(sorted(set(means.get("platform", []) + means.get("channel", []))))


def from_conduct(trajectory: dict[str, Any], scheme: Scheme) -> Walk:
    """One record's acts as a walk at ESM track states."""
    missing = [s for s in NEEDS if s not in scheme.states]
    if missing:
        raise ValueError(f"scheme {scheme.name} lacks the states the act reader places: {missing}")
    events: list[Event] = []
    state, mode, reached, ended_by = START, None, False, STOP
    for act in trajectory["acts"]:
        kind = act["kind"]
        if kind == "detection":
            if events:
                ended_by = DETECTED
                break
            continue
        role = ROLE.get(kind)
        if role is None:
            continue
        if role == "prepare":
            state = "Preparation" if state == START else state
        elif role == "reach":
            state = ENTRY[kind] if state in (START, "Preparation") else state
        elif role in ("deceive", "coerce", "press"):
            if role == "coerce" or mode == "Coercion":
                mode = "Coercion"
            elif role == "deceive":
                mode = "Deception"
            state = mode or "Conditioning"
        elif role in ("extract", "deliver"):
            state, reached = ENTRY[kind], True
        elif role == "after" and reached:
            state = ENTRY[kind]
        events.append(Event(kind, state, _means(act)))
    return Walk(trajectory["record_id"], trajectory.get("domain", ""), events, ended_by, "conduct",
                {"record_kind": trajectory.get("record_kind", "")})


def from_json(data: dict[str, Any] | list[Any], scheme: Scheme) -> tuple[list[Walk], Scheme]:
    """`{"states": [...], "walks": [...]}` or a bare list of walks. Extra states go in the source layer
    and may name an ESM state as `broader`."""
    rows = data if isinstance(data, list) else data.get("walks", [])
    extra = [] if isinstance(data, list) else data.get("states", [])
    if extra:
        scheme = scheme.extend([State(s["id"], "source", s.get("definition", ""), s.get("broader"), (), s.get("victim_is_source"),
                                      "", s.get("iri", ""), s.get("alphabet", "json")) for s in extra])
    return [from_dict(w) for w in rows], scheme


def from_graph(graph: Any, scheme: Scheme, *, domain: str = "") -> tuple[list[Walk], Scheme, dict[str, Any]]:
    """Every traj:Trajectory in an rdflib graph, as walks, with the scheme extended by any states
    the graph places itself or leaves unplaced."""
    from rdflib import Namespace, URIRef
    from rdflib.namespace import RDF

    traj = Namespace("http://example.org/ontology/trajectories/")
    skos = Namespace("http://www.w3.org/2004/02/skos/core#")
    action_class = URIRef("https://ontology.unifiedcyberontology.org/uco/action/Action")
    links = (skos.closeMatch, skos.exactMatch, skos.broadMatch, skos.broader)

    def placed(iri: str) -> str | None:
        return scheme.by_iri.get(iri) or (iri if iri in scheme.states else None)

    added: dict[str, State] = {}
    unplaced: set[str] = set()

    def state_of(node: URIRef) -> str | None:
        iri = str(node)
        if iri in scheme.terminal_iris:
            return None
        found = placed(iri) or (added[iri].id if iri in added else None)
        if found:
            return found
        for link in links:
            for target in graph.objects(node, link):
                above = placed(str(target))
                if above:
                    if link in (skos.closeMatch, skos.exactMatch):
                        return above
                    added[iri] = State(f"graph:{local_name(iri)}", "source", "", above, ((link.split("#")[-1], str(target)),), None, "", iri, "graph")
                    return added[iri].id
        unplaced.add(iri)
        added[iri] = State(f"graph:{local_name(iri)}", "source", "", None, (), None, "", iri, "graph")
        return added[iri].id

    def technique(source: URIRef | None, target: URIRef) -> str:
        for transition in graph.subjects(traj.toState, target):
            if source is not None and (transition, traj.fromState, source) not in graph:
                continue
            for action in graph.objects(transition, traj.enactsAction):
                kinds = sorted(local_name(str(t)) for t in graph.objects(action, RDF.type) if t != action_class)
                if kinds:
                    return kinds[0]
        return "(step)"

    walks, polarity_disagrees = [], 0
    for node in sorted(graph.subjects(RDF.type, traj.Trajectory)):
        rows = []
        for assertion in graph.objects(node, traj.hasPhaseAssertion):
            index = graph.value(assertion, traj.sequenceIndex)
            rows.append((int(index) if index is not None else 10**9, str(assertion), assertion))
        events, previous, ended_by, polarity = [], None, STOP, None
        for _, _, assertion in sorted(rows):
            target = graph.value(assertion, traj.assertsState)
            if target is None:
                continue
            polarity = str(graph.value(assertion, traj.terminalPolarity) or "") or polarity
            sid = state_of(target)
            if sid is None:  # a terminal state of the source alphabet
                break
            events.append(Event(technique(previous, target), sid))
            previous = target
        if polarity == "disrupted":
            ended_by = DETECTED
        walk = Walk(local_name(str(node)), domain, events, ended_by, "graph", {"source_polarity": polarity})
        walks.append(walk)
    out = scheme.extend(list({s.id: s for s in added.values()}.values())) if added else scheme
    for walk in walks:
        reached = any(out.is_goal(e.state) for e in walk.events if out.at(e.state, "milestone"))
        ours = "completed" if reached else ("disrupted" if walk.ended_by == DETECTED else None)
        walk.meta["polarity_agrees"] = ours == walk.meta["source_polarity"] or (ours is None and not walk.meta["source_polarity"])
        polarity_disagrees += not walk.meta["polarity_agrees"]
    report = {"trajectories": len(walks), "states_added_from_graph": sorted(s.id for s in added.values() if s.broader),
              "states_unplaced": sorted(unplaced), "source_polarity_disagrees_with_goal": polarity_disagrees}
    return walks, out, report


def read(path: str | Path, scheme: Scheme, *, domain: str = "") -> tuple[list[Walk], Scheme, dict[str, Any]]:
    path = Path(path)
    if path.suffix == ".json":
        walks, out = from_json(json.loads(path.read_text(encoding="utf-8")), scheme)
        return walks, out, {"trajectories": len(walks)}
    from rdflib import Graph

    return from_graph(Graph().parse(path), scheme, domain=domain or path.stem)
