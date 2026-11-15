"""Trajectories, fitted machines and the state scheme, written in the SDK's trajectories and means extensions.

Every graph is validated by the SDK gate before it is kept.

**The scheme** (`state_machines/schemes/esm.ttl`): a skos:ConceptScheme. Each state is a traj:State
and a skos:Concept, with skos:broader to the state above it, its definition, and its links to
other vocabularies (skos:closeMatch to CAC, skos:relatedMatch where only related). Each crosswalked
state of another alphabet is written with skos:broadMatch or skos:closeMatch to the ESM state it falls under.

**A record's trajectory** (`data/extracted/esm/records/<record>.ttl`):

    traj:State              the finest state each act reached, with its broader states up to the milestone
    traj:PhaseAssertion     one per act: that state, its place in the telling, the interval the record
                            dates it to (open when undated), a confidence from how the act was settled,
                            and the record it was read from
    traj:Trajectory         the record's assertions, in order. The last carries terminalPolarity
                            "completed" when the goal was reached, "disrupted" when detection is
                            narrated first; an unresolved telling makes no terminal claim
    traj:Transition         one per step, enacting a uco-action:Action for the act, with the technology
                            its sentence names as uco-action:instrument
    means:Goal              reaching the goal, pursued by the record's offender
    means:Option            one per act and technology its sentence names
    means:OffenderCapability  the capability to use that means, evidenced by its use in the record

**A fitted machine** (`data/extracted/esm/models/<domain>-<kind>-<layer>.ttl`): every trajectory it was
learned from, the transitions observed among states at its layer, one traj:TransitionEstimate per
(state, action, next state) with T(s'|s,a) and its counts, and a traj:StateMachineModel generated
by an analysis run of this code.

Not written, by design of the extensions: reward, value, policy; means:Selection (a record shows the
option taken, not the menu); means:OptionAssessment (frictions are not in a record).
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from extraction import store
from state_machines import machine as m, readers
from state_machines import scheme as sc
from state_machines.scheme import COMPLETED, DISRUPTED, START, TERMINAL, Scheme
from state_machines.walks import Walk, steps

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
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
SCHEME_TTL = sc.HERE / "esm.ttl"
CONFIDENCE = {"agreed": 90, "human": 95, "resolved": 75}


def iri(*parts: Any) -> URIRef:
    from case_uco import deterministic_uuid

    return URIRef(f"urn:uuid:{deterministic_uuid('casenoesis-esm', *map(str, parts))}")


def _graph() -> Graph:
    g = Graph()
    for prefix, ns in (("traj", TRAJ), ("means", MEANS), ("uco-core", CORE), ("uco-action", ACTION), ("uco-identity", IDENTITY),
                       ("uco-observable", OBSERVABLE), ("uco-tool", TOOL), ("uco-analysis", ANALYSIS), ("prov", PROV), ("time", TIME), ("skos", SKOS)):
        g.bind(prefix, ns)
    return g


def scheme_node(g: Graph, scheme: Scheme) -> URIRef:
    node = iri("scheme", scheme.name)
    g.add((node, RDF.type, SKOS.ConceptScheme))
    g.add((node, SKOS.prefLabel, Literal(scheme.title or scheme.name, lang="en")))
    if scheme.definition:
        g.add((node, SKOS.definition, Literal(scheme.definition, lang="en")))
    return node


def state_node(g: Graph, scheme: Scheme, state: str) -> URIRef:
    """A state, with its definition, its links, and every state above it."""
    if state == START:
        node = iri("state", scheme.name, START)
        g.add((node, RDF.type, TRAJ.State))
        g.add((node, CORE.name, Literal(START)))
        return node
    s = scheme.states[state]
    if s.iri:  # another alphabet's state keeps its own IRI
        node = URIRef(s.iri)
        g.add((node, RDF.type, TRAJ.State))
        if s.broader:
            g.add((node, SKOS.broadMatch, state_node(g, scheme, s.broader)))
        return node
    node = iri("state", scheme.name, state)
    if (node, RDF.type, TRAJ.State) in g:
        return node
    g.add((node, RDF.type, TRAJ.State))
    g.add((node, RDF.type, SKOS.Concept))
    g.add((node, CORE.name, Literal(state)))
    g.add((node, SKOS.prefLabel, Literal(state, lang="en")))
    g.add((node, SKOS.inScheme, scheme_node(g, scheme)))
    if s.definition:
        g.add((node, SKOS.definition, Literal(s.definition, lang="en")))
    if s.broader:
        g.add((node, SKOS.broader, state_node(g, scheme, s.broader)))
    else:
        g.add((node, SKOS.topConceptOf, scheme_node(g, scheme)))
    for relation, target in s.matches:
        g.add((node, SKOS[relation], URIRef(target)))
    return node


def scheme_graph(scheme: Scheme | None = None, *, check: bool = True, path: Path | None = None) -> dict[str, Any]:
    """The scheme and its crosswalk as one graph."""
    scheme = scheme or sc.load()
    g = _graph()
    for state in scheme.states:
        state_node(g, scheme, state)
    for source, target in scheme.by_iri.items():
        if source != target and not scheme.states.get(target, sc.State("", "milestone")).iri:
            node = URIRef(source)
            g.add((node, RDF.type, TRAJ.State))
            g.add((node, SKOS.closeMatch, state_node(g, scheme, target)))
    out = write(g, path or SCHEME_TTL)
    if check:
        out.update(gate(Path(out["path"])))
    return out


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


def add_trajectory(g: Graph, walk: Walk, scheme: Scheme, *, statuses: list[str] | None = None, dates: list[str | None] | None = None) -> URIRef | None:
    """Add one walk to `g`. Returns the trajectory node, or None when it has no event."""
    if not walk.events:
        return None
    record_id = walk.id
    end = steps(walk, scheme, "milestone")[-1][2]
    polarity = {COMPLETED: "completed", DISRUPTED: "disrupted"}.get(end)
    record = iri("record", record_id)
    g.add((record, RDF.type, OBSERVABLE.ObservableObject))
    g.add((record, CORE.name, Literal(f"Record {record_id}")))
    actor = iri("actor", record_id)
    g.add((actor, RDF.type, IDENTITY.Person))
    g.add((actor, CORE.name, Literal("Offender")))
    g.add((actor, CORE.description, Literal("The offender whose acts the record narrates. No name is held.")))
    goal_label = ", ".join(sorted(scheme.goal))
    goal_node = iri("goal", record_id, goal_label)
    g.add((goal_node, RDF.type, MEANS.Goal))
    g.add((goal_node, CORE.name, Literal(f"Reach {goal_label}")))
    g.add((goal_node, MEANS.pursuedBy, actor))

    trajectory_node = iri("trajectory", record_id, scheme.name)
    g.add((trajectory_node, RDF.type, TRAJ.Trajectory))
    g.add((trajectory_node, CORE.name, Literal(f"Trajectory of {record_id}")))
    previous_state = state_node(g, scheme, START)
    reached = False
    for index, event in enumerate(walk.events):
        # An act that reaches nothing before any state (money moved before a victim is reached) stays at `start`.
        own = scheme.states.get(event.state)
        recorded = scheme.project(event.state, scheme.layers[-1] if own is not None and own.iri else "track", reached)
        reached = reached or scheme.is_goal(event.state)
        state = state_node(g, scheme, recorded)
        assertion = iri("assertion", record_id, scheme.name, index)
        g.add((assertion, RDF.type, TRAJ.PhaseAssertion))
        g.add((assertion, CORE.name, Literal(f"Act {index}: {event.action}")))
        g.add((assertion, TRAJ.assertsState, state))
        g.add((assertion, TRAJ.atInterval, _interval(g, (record_id, index), dates[index] if dates and index < len(dates) else None)))
        g.add((assertion, TRAJ.sequenceIndex, Literal(index, datatype=XSD.nonNegativeInteger)))
        g.add((assertion, PROV.wasDerivedFrom, record))
        facet = iri("confidence", record_id, scheme.name, index)
        g.add((facet, RDF.type, CORE.ConfidenceFacet))
        status = statuses[index] if statuses and index < len(statuses) else None
        g.add((facet, CORE.confidence, Literal(CONFIDENCE.get(status, 70), datatype=XSD.nonNegativeInteger)))
        g.add((assertion, CORE.hasFacet, facet))
        if index == len(walk.events) - 1 and polarity:
            g.add((assertion, TRAJ.isTerminal, Literal(True)))
            g.add((assertion, TRAJ.terminalPolarity, Literal(polarity)))
        g.add((trajectory_node, TRAJ.hasPhaseAssertion, assertion))

        action = iri("action", record_id, index)
        g.add((action, RDF.type, ACTION.Action))
        g.add((action, CORE.name, Literal(event.action)))
        g.add((action, ACTION.performer, actor))
        labels = sorted(set(event.means))
        instruments = [_instrument(g, label) for label in labels]
        for instrument in instruments:
            g.add((action, ACTION.instrument, instrument))
        transition = iri("transition", record_id, scheme.name, index)
        g.add((transition, RDF.type, TRAJ.Transition))
        g.add((transition, CORE.name, Literal(event.action)))
        g.add((transition, TRAJ.fromState, previous_state))
        g.add((transition, TRAJ.toState, state))
        g.add((transition, TRAJ.trigger, action))
        g.add((transition, TRAJ.enactsAction, action))
        # One option per means: an act that used two technologies walked two options at once.
        for label, instrument in zip(labels, instruments):
            option = iri("option", record_id, index, label)
            g.add((option, RDF.type, MEANS.Option))
            g.add((option, CORE.name, Literal(f"{event.action} by {label}")))
            g.add((option, MEANS.servesGoal, goal_node))
            g.add((option, MEANS.availableAt, previous_state))
            g.add((option, MEANS.usesInstrument, instrument))
            g.add((option, MEANS.enactedTransition, transition))
            g.add((option, PROV.wasDerivedFrom, record))
            capability = iri("capability", record_id, index, label)
            g.add((capability, RDF.type, MEANS.OffenderCapability))
            g.add((capability, CORE.name, Literal(f"Can {event.action} by {label}")))
            g.add((capability, CORE.description, Literal("Evidenced by its use in the record, not by a separate statement of capability.")))
            g.add((capability, MEANS.possessedBy, actor))
            g.add((capability, MEANS.enablesOption, option))
            g.add((capability, PROV.wasDerivedFrom, record))
        previous_state = state
    return trajectory_node


def _conduct(trajectory: dict[str, Any], scheme: Scheme) -> tuple[Walk, list[str | None], list[str | None]]:
    """A conduct trajectory as a walk, with each kept act's status and date."""
    walk = readers.from_conduct(trajectory, scheme)
    kept: list[dict[str, Any]] = []
    for act in trajectory["acts"]:  # the acts the reader made events of, in the same order
        if act["kind"] == "detection" and kept:
            break
        if act["kind"] in readers.ROLE:
            kept.append(act)
    return walk, [a.get("status") for a in kept], [a.get("date") for a in kept]


def add_model(g: Graph, fitted: m.Machine, trajectory_nodes: list[URIRef], *, name: str) -> URIRef:
    """Add a fitted machine: transitions, estimates with counts, and the model node."""
    from extraction import ENGINE_VERSION

    tool = iri("tool", m.MACHINE_VERSION)
    g.add((tool, RDF.type, TOOL.Tool))
    g.add((tool, CORE.name, Literal("CaseNoesis state machine estimator")))
    g.add((tool, CORE.description, Literal(f"{m.MACHINE_VERSION}, engine {ENGINE_VERSION}")))
    alphabet = f"{fitted.scheme.name}-{fitted.layer}"
    run = iri("run", name, alphabet)
    g.add((run, RDF.type, ANALYSIS.Analysis))
    g.add((run, CORE.name, Literal(f"Estimate transitions: {name}")))
    g.add((run, ACTION.instrument, tool))
    g.add((run, PROV.wasAssociatedWith, tool))
    model = iri("model", name, alphabet)
    g.add((model, RDF.type, TRAJ.StateMachineModel))
    g.add((model, RDF.type, ANALYSIS.AnalyticResult))
    g.add((model, CORE.name, Literal(f"State machine: {name} ({fitted.scheme.name} {fitted.layer} states, {fitted.level} actions)")))
    g.add((model, PROV.wasGeneratedBy, run))
    g.add((model, TRAJ.initialState, state_node(g, fitted.scheme, START)))
    for node in trajectory_nodes:
        g.add((model, TRAJ.learnedFrom, node))
    for row in fitted.estimates():
        if row["to"] in TERMINAL:
            continue  # terminal outcomes are on the assertions, not states of the alphabet
        trigger = iri("model-action", name, row["action"])
        g.add((trigger, RDF.type, ACTION.Action))
        g.add((trigger, CORE.name, Literal(row["action"])))
        transition = iri("model-transition", name, alphabet, row["from"], row["action"], row["to"])
        g.add((transition, RDF.type, TRAJ.Transition))
        g.add((transition, CORE.name, Literal(f"{row['from']} -[{row['action']}]-> {row['to']}")))
        g.add((transition, TRAJ.fromState, state_node(g, fitted.scheme, row["from"])))
        g.add((transition, TRAJ.toState, state_node(g, fitted.scheme, row["to"])))
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


def record_graph(trajectory: dict[str, Any], *, check: bool = False, scheme: Scheme | None = None) -> dict[str, Any]:
    scheme = scheme or sc.load()
    walk, statuses, dates = _conduct(trajectory, scheme)
    g = _graph()
    if add_trajectory(g, walk, scheme, statuses=statuses, dates=dates) is None:
        return {"record_id": trajectory["record_id"], "skipped": "no offender act"}
    out = {"record_id": trajectory["record_id"], **write(g, ESM / "records" / f"{trajectory['record_id']}.ttl")}
    if check:
        out.update(gate(Path(out["path"])))
    return out


def model_graph(trajectories: list[dict[str, Any]], name: str, *, layer: str = "milestone", check: bool = True, scheme: Scheme | None = None) -> dict[str, Any]:
    scheme = scheme or sc.load()
    g = _graph()
    converted = [_conduct(t, scheme) for t in trajectories]
    nodes = [node for node in (add_trajectory(g, w, scheme, statuses=s, dates=d) for w, s, d in converted) if node is not None]
    fitted = m.fit([w for w, _, _ in converted], scheme, layer=layer)
    add_model(g, fitted, nodes, name=f"{name}-{layer}")
    out = {"model": f"{name}-{layer}", "trajectories": len(nodes), **write(g, ESM / "models" / f"{name}-{layer}.ttl")}
    if check:
        out.update(gate(Path(out["path"])))
    return out
