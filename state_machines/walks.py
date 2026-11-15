"""Walks: the one form every source is read into, and every analysis reads.

A walk is a sequence of events, each an action and the state it left the
offense in, recorded at the finest state the evidence supports, and how
the telling ended: `(stop)` (it stops) or `(detected)` (detection is
narrated). Where the states came from does not matter here: the act
reader, a hand-built graph, or any extractor that writes the JSON form.

    {"id": "...", "domain": "...", "source": "...",
     "events": [{"action": "contact", "state": "Solicitation", "means": ["whatsapp"]}, ...],
     "ended_by": "(stop)"}

At a layer, a walk is a list of steps (state, action, next state) from
`start` to a terminal state:

    Completed    the goal was reached
    Disrupted    detection was narrated before it
    Unresolved   the telling ended before it

An event the layer cannot place (a source state with no mapping) is left
out and counted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from state_machines.scheme import COMPLETED, DETECTED, DISRUPTED, START, STOP, TERMINAL, UNRESOLVED, Scheme


@dataclass(frozen=True)
class Event:
    action: str
    state: str
    means: tuple[str, ...] = ()


@dataclass
class Walk:
    id: str
    domain: str
    events: list[Event]
    ended_by: str = STOP
    source: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "domain": self.domain, "source": self.source, "ended_by": self.ended_by,
                "events": [{"action": e.action, "state": e.state, **({"means": list(e.means)} if e.means else {})} for e in self.events],
                **({"meta": self.meta} if self.meta else {})}


def from_dict(data: dict[str, Any]) -> Walk:
    events = [Event(e.get("action") or "(step)", e["state"], tuple(e.get("means") or ())) for e in data["events"]]
    return Walk(str(data["id"]), data.get("domain", ""), events, data.get("ended_by", STOP), data.get("source", ""), data.get("meta", {}))


def action_of(event: Event, level: str) -> str:
    """`contact` at the act level, `contact[whatsapp]` at the means level."""
    if level == "means" and event.means:
        return f"{event.action}[{'+'.join(sorted(set(event.means)))}]"
    return event.action


def steps(walk: Walk, scheme: Scheme, layer: str = "milestone", level: str = "act") -> list[tuple[str, str, str]]:
    """The walk at `layer` as (state, action, next state), ending in a terminal state.
    A repeat of the same step is counted once."""
    out: list[tuple[str, str, str]] = []
    state, reached = START, False
    for event in walk.events:
        nxt = scheme.project(event.state, layer, reached)
        if nxt is None:
            continue
        if nxt in TERMINAL:
            break
        step = (state, action_of(event, level), nxt)
        if not out or out[-1] != step:
            out.append(step)
        state, reached = nxt, reached or scheme.is_goal(nxt)
    if not out:
        return out
    if walk.ended_by == DETECTED:
        out.append((state, DETECTED, COMPLETED if reached else DISRUPTED))
    else:
        out.append((state, STOP, COMPLETED if reached else UNRESOLVED))
    return out


def path(walk: Walk, scheme: Scheme, layer: str = "milestone") -> list[str]:
    """States occupied in order, a run of one state counted once, ending in the terminal state."""
    out: list[str] = []
    for _, _, nxt in steps(walk, scheme, layer):
        if not out or out[-1] != nxt:
            out.append(nxt)
    return out


def unplaced(walk: Walk, scheme: Scheme, layer: str) -> int:
    return sum(1 for e in walk.events if scheme.at(e.state, layer) is None)


def predicate(walk: Walk, scheme: Scheme) -> str:
    """The exploitation predicate: is the victim the source of what the offender takes?

    passes        a goal state with victim_is_source true was reached
    fails         goal states were reached, and every one says the victim is not the source
    unspecified   the goal was reached at a state that does not say
    not_reached   the goal was never reached"""
    said: list[bool | None] = []
    for event in walk.events:
        if event.state not in scheme.states or not scheme.is_goal(event.state):
            continue
        flag = next((scheme.states[n].victim_is_source for n in scheme.ancestors(event.state)
                     if scheme.states[n].victim_is_source is not None), None)
        said.append(flag)
    if not said:
        return "not_reached"
    if any(f is True for f in said):
        return "passes"
    if all(f is False for f in said):
        return "fails"
    return "unspecified"
