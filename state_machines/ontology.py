"""Trajectories and fitted machines, written in the SDK's trajectories and means extensions.

Two kinds of graph, both validated by the SDK gate before they are kept.

**A record's trajectory** (`data/extracted/esm/records/<record>.ttl`):

    traj:State              one per state of the alphabet, shared across graphs (same IRI everywhere)
    traj:PhaseAssertion     one per act: the state it occupies, its place in the telling, the interval
                            the record dates it to (open when the record gives no date), a confidence
                            from how the act was settled, and the record it was read from
    traj:Trajectory         the record's assertions, in order. The last carries terminalPolarity
                            "disrupted" when the record narrates detection after it
    traj:Transition         one per step, triggered by and enacting a uco-action:Action for the act,
                            with the technology its sentence names as uco-action:instrument
    means:Goal              reaching the goal state, pursued by the record's offender
    means:Option            one per act and technology its sentence names: the means used, the state
                            it was taken from, the transition it enacted
    means:OffenderCapability  the capability to use that means, evidenced by its use in the record

**A fitted machine** (`data/extracted/esm/models/<domain>-<kind>.ttl`): every trajectory it was
learned from, the transitions observed among states, one traj:TransitionEstimate per
(state, action, next state) with T(s'|s,a) and its counts, and a traj:StateMachineModel generated
by an analysis run of this code.

What is not written, by design of the extensions: no reward, no value, no policy. No
means:Selection either: a record shows the option taken and not the menu it was taken from.
No means:OptionAssessment: frictions are a researcher's reading and are not in a record.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from extraction import store
from state_machines import machine as m

ESM = store.EXTRACTED / "esm"
TRAJ = Namespace("http://example.org/ontology/trajectories/")
MEANS = Namespace("http://example.org/ontology/means/")
CORE = Namespace("https://ontology.unifiedcyberontology.org/uco/core/")
ACTION = Namespace("https://ontology.unifiedcyberontology.org/uco/action/")
IDENTITY = Namespace("https://ontology.unifiedcyberontology.org/uco/identity/")
OBSERVABLE = Namespace("https://ontology.unifiedcyberontology.org/uco/observable/")
TOOL = Namespace("https://ontology.unifiedcyberontology.org/uco/tool/")
ANALYSIS = Namespace("https://ontology.unifiedcyberontology.org/uco/analysis/")
PROV = Namespace("http://www.w3.org/ns/prov#")
TIME = Namespace("http://www.w3.org/2006/time#")
CONFIDENCE = {"agreed": 90, "human": 95, "resolved": 75}


def iri(*parts: Any) -> URIRef:
    from case_uco import deterministic_uuid

    return URIRef(f"urn:uuid:{deterministic_uuid('casenoesis-esm', *map(str, parts))}")


def _graph() -> Graph:
    g = Graph()
    for prefix, ns in (("traj", TRAJ), ("means", MEANS), ("uco-core", CORE), ("uco-action", ACTION), ("uco-identity", IDENTITY),
                       ("uco-observable", OBSERVABLE), ("uco-tool", TOOL), ("uco-analysis", ANALYSIS), ("prov", PROV), ("time", TIME)):
        g.bind(prefix, ns)
    return g


def state_node(g: Graph, alphabet: str, state: str) -> URIRef:
    node = iri("state", alphabet, state)
    g.add((node, RDF.type, TRAJ.State))
    g.add((node, CORE.name, Literal(state)))
    g.add((node, CORE.description, Literal(f"State '{state}' of the '{alphabet}' alphabet.")))
    return node


def _interval(g: Graph, key: tuple[Any, ...], stamp: str | None) -> URIRef:
    node = iri("interval", *key)
    g.add((node, RDF.type, TIME.ProperInterval))
    if stamp:
        year, month = int(stamp[:4]), int(stamp[5:7])
        first = date.fromisoformat(stamp) if len(stamp) == 10 else date(year, month, 1)
        last = first if len(stamp) == 10 else date(year + month // 12, month % 12 + 1, 1).fromordinal(date(year + month // 12, month % 12 + 1, 1).toordinal() - 1)
        for edge, day, clock in ((TIME.hasBeginning, first, "00:00:00"), (TIME.hasEnd, last, "23:59:59")):
            instant = iri("instant", *key, edge)
            g.add((instant, RDF.type, TIME.Instant))
            g.add((instant, TIME.inXSDDateTimeStamp, Literal(f"{day.isoformat()}T{clock}Z", datatype=XSD.dateTimeStamp)))
            g.add((node, edge, instant))
    return node


def _instrument(g: Graph, label: str) -> URIRef:
    node = iri("instrument", label)
    g.add((node, RDF.type, CORE.UcoObject))
    g.add((node, CORE.name, Literal(label)))
    return node


def add_trajectory(g: Graph, trajectory: dict[str, Any], *, alphabet: str = "phase", states: m.StateMap = m.phase_state,
                   goal: tuple[str, ...] = ("harm",)) -> URIRef | None:
    """Add one record's trajectory to `g`. Returns the trajectory node, or None when it has no offender act."""
    record_id = trajectory["record_id"]
    acts = [a for a in trajectory["acts"] if a["kind"] != "detection"]
    if not acts:
        return None
    walked = m.steps(trajectory, states=states)
    disrupted = bool(walked) and walked[-1][2] == m.DISRUPTED
    record = iri("record", record_id)
    g.add((record, RDF.type, OBSERVABLE.ObservableObject))
    g.add((record, CORE.name, Literal(f"Record {record_id}")))
    actor = iri("actor", record_id)
    g.add((actor, RDF.type, IDENTITY.Person))
    g.add((actor, CORE.name, Literal("Offender")))
    g.add((actor, CORE.description, Literal("The offender whose acts the record narrates. No name is held.")))
    goal_node = iri("goal", record_id, *goal)
    g.add((goal_node, RDF.type, MEANS.Goal))
    g.add((goal_node, CORE.name, Literal(f"Reach {' or '.join(goal)}")))
    g.add((goal_node, MEANS.pursuedBy, actor))

    trajectory_node = iri("trajectory", record_id, alphabet)
    g.add((trajectory_node, RDF.type, TRAJ.Trajectory))
    g.add((trajectory_node, CORE.name, Literal(f"Trajectory of {record_id} ({alphabet} states)")))
    previous_state = state_node(g, alphabet, m.START)
    for index, act in enumerate(acts):
        here = states(act)
        state = state_node(g, alphabet, here)
        assertion = iri("assertion", record_id, alphabet, index)
        g.add((assertion, RDF.type, TRAJ.PhaseAssertion))
        g.add((assertion, CORE.name, Literal(f"Act {index}: {act['kind']}")))
        g.add((assertion, TRAJ.assertsState, state))
        g.add((assertion, TRAJ.atInterval, _interval(g, (record_id, index), act.get("date"))))
        g.add((assertion, TRAJ.sequenceIndex, Literal(index, datatype=XSD.nonNegativeInteger)))
        g.add((assertion, PROV.wasDerivedFrom, record))
        facet = iri("confidence", record_id, alphabet, index)
        g.add((facet, RDF.type, CORE.ConfidenceFacet))
        g.add((facet, CORE.confidence, Literal(CONFIDENCE.get(act.get("status"), 70), datatype=XSD.nonNegativeInteger)))
        g.add((assertion, CORE.hasFacet, facet))
        if index == len(acts) - 1 and disrupted:
            g.add((assertion, TRAJ.isTerminal, Literal(True)))
            g.add((assertion, TRAJ.terminalPolarity, Literal("disrupted")))
        g.add((trajectory_node, TRAJ.hasPhaseAssertion, assertion))

        action = iri("action", record_id, index)
        g.add((action, RDF.type, ACTION.Action))
        g.add((action, CORE.name, Literal(act["kind"])))
        g.add((action, ACTION.performer, actor))
        labels = sorted(set((act.get("means") or {}).get("platform", []) + (act.get("means") or {}).get("channel", [])))
        instruments = [_instrument(g, label) for label in labels]
        for instrument in instruments:
            g.add((action, ACTION.instrument, instrument))
        transition = iri("transition", record_id, alphabet, index)
        g.add((transition, RDF.type, TRAJ.Transition))
        g.add((transition, CORE.name, Literal(f"{act['kind']}")))
        g.add((transition, TRAJ.fromState, previous_state))
        g.add((transition, TRAJ.toState, state))
        g.add((transition, TRAJ.trigger, action))
        g.add((transition, TRAJ.enactsAction, action))
        # One option per means: an act that used two technologies walked two options at once.
        for label, instrument in zip(labels, instruments):
            option = iri("option", record_id, index, label)
            g.add((option, RDF.type, MEANS.Option))
            g.add((option, CORE.name, Literal(f"{act['kind']} by {label}")))
            g.add((option, MEANS.servesGoal, goal_node))
            g.add((option, MEANS.availableAt, previous_state))
            g.add((option, MEANS.usesInstrument, instrument))
            g.add((option, MEANS.enactedTransition, transition))
            g.add((option, PROV.wasDerivedFrom, record))
            capability = iri("capability", record_id, index, label)
            g.add((capability, RDF.type, MEANS.OffenderCapability))
            g.add((capability, CORE.name, Literal(f"Can {act['kind']} by {label}")))
            g.add((capability, CORE.description, Literal("Evidenced by its use in the record, not by a separate statement of capability.")))
            g.add((capability, MEANS.possessedBy, actor))
            g.add((capability, MEANS.enablesOption, option))
            g.add((capability, PROV.wasDerivedFrom, record))
        previous_state = state
    return trajectory_node


def add_model(g: Graph, fitted: m.Machine, trajectory_nodes: list[URIRef], *, name: str, alphabet: str = "phase") -> URIRef:
    """Add a fitted machine: transitions, estimates with counts, and the model node."""
    from extraction import ENGINE_VERSION

    tool = iri("tool", m.MACHINE_VERSION)
    g.add((tool, RDF.type, TOOL.Tool))
    g.add((tool, CORE.name, Literal("CaseNoesis state machine estimator")))
    g.add((tool, CORE.description, Literal(f"{m.MACHINE_VERSION}, engine {ENGINE_VERSION}")))
    run = iri("run", name, alphabet)
    g.add((run, RDF.type, ANALYSIS.Analysis))
    g.add((run, CORE.name, Literal(f"Estimate transitions: {name}")))
    g.add((run, ACTION.instrument, tool))
    g.add((run, PROV.wasAssociatedWith, tool))
    model = iri("model", name, alphabet)
    g.add((model, RDF.type, TRAJ.StateMachineModel))
    g.add((model, RDF.type, ANALYSIS.AnalyticResult))
    g.add((model, CORE.name, Literal(f"State machine: {name} ({alphabet} states, {fitted.level} actions)")))
    g.add((model, PROV.wasGeneratedBy, run))
    g.add((model, TRAJ.initialState, state_node(g, alphabet, m.START)))
    for node in trajectory_nodes:
        g.add((model, TRAJ.learnedFrom, node))
    for row in fitted.estimates():
        if row["to"] in m.TERMINAL:
            continue  # terminal outcomes are on the assertions, not states of the alphabet
        trigger = iri("model-action", name, row["action"])
        g.add((trigger, RDF.type, ACTION.Action))
        g.add((trigger, CORE.name, Literal(row["action"])))
        transition = iri("model-transition", name, alphabet, row["from"], row["action"], row["to"])
        g.add((transition, RDF.type, TRAJ.Transition))
        g.add((transition, CORE.name, Literal(f"{row['from']} -[{row['action']}]-> {row['to']}")))
        g.add((transition, TRAJ.fromState, state_node(g, alphabet, row["from"])))
        g.add((transition, TRAJ.toState, state_node(g, alphabet, row["to"])))
        g.add((transition, TRAJ.trigger, trigger))
        g.add((model, TRAJ.hasTransition, transition))
        estimate = iri("estimate", name, alphabet, row["from"], row["action"], row["to"])
        g.add((estimate, RDF.type, TRAJ.TransitionEstimate))
        g.add((estimate, CORE.name, Literal(f"T({row['to']} | {row['from']}, {row['action']})")))
        g.add((estimate, TRAJ.ofTransition, transition))
        g.add((estimate, TRAJ.transitionProbability, Literal(f"{row['probability']:.4f}", datatype=XSD.decimal)))
        g.add((estimate, TRAJ.sampleBasis, Literal(f"{row['times']} of {row['of']} steps from {row['from']} by {row['action']}; maximum likelihood")))
        g.add((estimate, PROV.wasGeneratedBy, run))
        g.add((model, TRAJ.hasTransitionEstimate, estimate))
    return model


def write(g: Graph, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(path, format="turtle")
    return {"path": str(path), "triples": len(g), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def gate(path: Path) -> dict[str, Any]:
    from encoding import sdk

    receipt = sdk.gate(path, extensions=["trajectories", "means"])
    sdk.write_receipt(path, receipt)
    return {"conforms": receipt["conforms"], "violations": receipt.get("violation_count"), "publishable": receipt.get("publishable")}


def record_graph(trajectory: dict[str, Any], *, check: bool = False) -> dict[str, Any]:
    g = _graph()
    if add_trajectory(g, trajectory) is None:
        return {"record_id": trajectory["record_id"], "skipped": "no offender act"}
    out = {"record_id": trajectory["record_id"], **write(g, ESM / "records" / f"{trajectory['record_id']}.ttl")}
    if check:
        out.update(gate(Path(out["path"])))
    return out


def model_graph(trajectories: list[dict[str, Any]], name: str, *, check: bool = True) -> dict[str, Any]:
    g = _graph()
    nodes = [node for node in (add_trajectory(g, t) for t in trajectories) if node is not None]
    fitted = m.fit(trajectories)
    add_model(g, fitted, nodes, name=name)
    out = {"model": name, "trajectories": len(nodes), **write(g, ESM / "models" / f"{name}.ttl")}
    if check:
        out.update(gate(Path(out["path"])))
    return out
