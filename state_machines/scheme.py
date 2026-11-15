"""State schemes: states as data, in layers, linked by a hierarchy.

A scheme is a tree of states. Each state has an id, a layer, a definition,
and at most one broader state in the layer above. Analyses run at a chosen
layer: a walk recorded at a fine state is projected to its ancestor there.

    milestone   what the offense has reached: the states of the machine
    track       how it was reached: by deception or coercion, value or a person taken
    source      another alphabet's states (the SDK's, CAC's, a hand-built close-read),
                placed under ESM states by a crosswalk

The goal changes what leverage means. Leverage held before the goal is
Conditioning; the same leverage held after it is Maintenance. The scheme
says so once, in `after_goal`, and projection applies it from the walk's
history, so a source state mapped to Coercion becomes RenewedCoercion after
exploitation without the source alphabet knowing about the goal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent / "schemes"
START = "start"
COMPLETED, DISRUPTED, UNRESOLVED = "Completed", "Disrupted", "Unresolved"
TERMINAL = (COMPLETED, DISRUPTED, UNRESOLVED)
STOP, DETECTED = "(stop)", "(detected)"
SAME = ("exactMatch", "closeMatch")


@dataclass(frozen=True)
class State:
    id: str
    layer: str
    definition: str = ""
    broader: str | None = None
    matches: tuple[tuple[str, str], ...] = ()  # (relation, iri)
    victim_is_source: bool | None = None
    script: str = ""
    iri: str = ""  # for a source state: its IRI in its own alphabet
    alphabet: str = ""


@dataclass
class Scheme:
    name: str
    version: str
    layers: tuple[str, ...]
    states: dict[str, State]
    goal: frozenset[str]
    after_goal: dict[str, str] = field(default_factory=dict)
    backbone: tuple[str, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    title: str = ""
    definition: str = ""
    terminals: dict[str, str] = field(default_factory=dict)
    by_iri: dict[str, str] = field(default_factory=dict)  # source IRI -> state id
    terminal_iris: dict[str, str] = field(default_factory=dict)  # source IRI -> terminal

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for s in self.states.values():
            if s.layer not in self.layers:
                raise ValueError(f"{s.id}: unknown layer {s.layer!r}")
            if s.broader is not None:
                parent = self.states.get(s.broader)
                if parent is None:
                    raise ValueError(f"{s.id}: broader {s.broader!r} is not a state")
                if self.layers.index(parent.layer) > self.layers.index(s.layer):
                    raise ValueError(f"{s.id}: broader {s.broader!r} is in a finer layer")
        for s in self.states:
            seen, node = set(), s
            while node is not None:
                if node in seen:
                    raise ValueError(f"{s}: cycle in broader")
                seen.add(node)
                node = self.states[node].broader
        for a, b in self.after_goal.items():
            if a not in self.states or b not in self.states:
                raise ValueError(f"after_goal {a} -> {b}: not states")
        for g in self.goal:
            if g not in self.states:
                raise ValueError(f"goal {g!r} is not a state")

    def ancestors(self, state: str) -> list[str]:
        """The state and every state above it, finest first."""
        out, node = [], state
        while node is not None:
            out.append(node)
            node = self.states[node].broader
        return out

    def at(self, state: str, layer: str) -> str | None:
        """The state's ancestor at `layer`. A state coarser than `layer` stands for itself
        (the evidence did not say more). None when the state has no ancestor there."""
        if state in (START, *TERMINAL):
            return state
        rank = self.layers.index(layer)
        for node in self.ancestors(state):
            if self.layers.index(self.states[node].layer) <= rank:
                return node
        return None

    def project(self, state: str, layer: str, reached: bool) -> str | None:
        """`state` at `layer`, given whether the goal had been reached before it."""
        target = self.at(state, layer)
        if reached and target in self.after_goal:
            return self.after_goal[target]
        return target

    def is_goal(self, state: str) -> bool:
        return state not in (START, *TERMINAL) and state in self.states and any(n in self.goal for n in self.ancestors(state))

    def at_layer(self, layer: str) -> list[str]:
        """States an analysis at `layer` can occupy: the layer's own states and coarser leaves."""
        return [s for s in self.states if self.at(s, layer) == s]

    def children(self, state: str) -> list[str]:
        return [s.id for s in self.states.values() if s.broader == state]

    def role(self, name: str) -> str | None:
        return self.roles.get(name)

    def extend(self, states: list[State], layer: str = "source") -> Scheme:
        """A copy with another alphabet's states added in `layer`, under the states they map to."""
        layers = self.layers + ((layer,) if layer not in self.layers else ())
        merged = dict(self.states)
        by_iri = dict(self.by_iri)
        for s in states:
            if s.id in merged and merged[s.id].layer != layer:
                raise ValueError(f"{s.id}: already a {merged[s.id].layer} state")
            merged[s.id] = s
            if s.iri:
                by_iri[s.iri] = s.id
        return replace(self, layers=layers, states=merged, by_iri=by_iri)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version, "layers": list(self.layers), "goal": sorted(self.goal),
            "backbone": list(self.backbone), "after_goal": self.after_goal, "roles": self.roles, "terminals": self.terminals,
            "states": [{"id": s.id, "layer": s.layer, "broader": s.broader, "definition": s.definition,
                        **({"matches": [{"relation": r, "iri": i} for r, i in s.matches]} if s.matches else {}),
                        **({"victim_is_source": s.victim_is_source} if s.victim_is_source is not None else {}),
                        **({"script": s.script} if s.script else {}), **({"iri": s.iri, "alphabet": s.alphabet} if s.iri else {})}
                       for s in self.states.values()],
        }


def _state(row: dict[str, Any]) -> State:
    return State(row["id"], row["layer"], row.get("definition", ""), row.get("broader"),
                 tuple((m["relation"], m["iri"]) for m in row.get("matches", [])), row.get("victim_is_source"),
                 row.get("script", ""), row.get("iri", ""), row.get("alphabet", ""))


def from_dict(data: dict[str, Any]) -> Scheme:
    return Scheme(data["name"], str(data.get("version", "")), tuple(data["layers"]), {r["id"]: _state(r) for r in data["states"]},
                  frozenset(data.get("goal", [])), dict(data.get("after_goal", {})), tuple(data.get("backbone", [])),
                  dict(data.get("roles", {})), data.get("title", ""), data.get("definition", ""), dict(data.get("terminals", {})))


def load(name: str = "esm", *, crosswalk: bool = True) -> Scheme:
    """A scheme from `schemes/<name>.json`, with its crosswalk's alphabets added as the source layer."""
    scheme = from_dict(json.loads((HERE / f"{name}.json").read_text(encoding="utf-8")))
    path = HERE / "crosswalk.json"
    if crosswalk and path.is_file():
        walk = json.loads(path.read_text(encoding="utf-8"))
        if walk.get("scheme") == scheme.name:
            scheme = with_crosswalk(scheme, walk)
    return scheme


def local_name(iri: str) -> str:
    return iri.rstrip("/").rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def with_crosswalk(scheme: Scheme, crosswalk: dict[str, Any]) -> Scheme:
    """Add the crosswalk's source states. A closeMatch or exactMatch maps the IRI onto the ESM state
    itself; a broadMatch adds the source state beneath it; `terminal` maps it onto an end."""
    added: list[State] = []
    by_iri, terminal_iris = {}, dict(scheme.terminal_iris)
    for row in crosswalk.get("mappings", []):
        relation, target = row["relation"], row["state"]
        if relation == "terminal":
            terminal_iris[row["iri"]] = target
            continue
        if target not in scheme.states:
            raise ValueError(f"crosswalk: {row['iri']} -> unknown state {target!r}")
        if relation in SAME:
            by_iri[row["iri"]] = target
            continue
        sid = f"{row['alphabet']}:{local_name(row['iri'])}"
        added.append(State(sid, "source", row.get("note", ""), target, (("broadMatch", scheme.states[target].id),), None, "", row["iri"], row["alphabet"]))
    out = scheme.extend(added)
    out.by_iri.update(by_iri)
    out.terminal_iris = terminal_iris
    return out
