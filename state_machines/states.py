"""States: the condition an offense is in, separate from the acts that move it.

A state is a milestone the offense has reached, read from the acts before it.
The same act can leave different states and lead to different ones: a
deception before anything is taken conditions the victim; the same deception
after a payment renews leverage, and the offense is in maintenance.

    Preparation      the means are being set up; no victim reached yet
    InitialContact   a victim (a person, or a system) has been reached
    Conditioning     leverage is held: trust, deception, a demand, a threat, control
    Exploitation     value or a person has been taken, or the offense's harm delivered
    Maintenance      leverage renewed after exploitation; the offense continues

The four after Preparation are the backbone of the Exploitation State
Machine, and correspond to the CAC grooming phases of the same names. CAC
defines them for child sexual exploitation; here they are used for every
domain, which is what lets the backbone be tested across domains, so the
alignment is recorded as skos:closeMatch, not exactMatch.

Terminal states:

    Completed        exploitation was reached (the offense succeeded, whether or not it was later detected)
    Disrupted        detection is narrated before exploitation was reached
    Unresolved       the telling ends before exploitation, with no detection narrated

Acts move states by their role:

    prepare   setup                                         start -> Preparation
    reach     contact, recruit, access                      start, Preparation -> InitialContact
    leverage  deception, demand, threat, control, transport before exploitation -> Conditioning; after -> Maintenance
    extract   transfer, exploit                             -> Exploitation (from Maintenance too: a renewed extraction)
    deliver   supply                                        -> Exploitation
    after     movement, concealment                         no change

An act whose role does not move the current state is a step that stays in
it. That keeps every act an action and leaves the state to say only what has
been reached.

**Exploitation predicate.** A trajectory is exploitative when the victim is
the source of what the offender takes: it reaches Exploitation by an
`extract` act (value transferred from, or labor, sex or images taken from, the
person harmed). Reaching it only by `deliver` (contraband supplied to buyers)
is harm without a victim as the source of the reward.
"""

from __future__ import annotations

from typing import Any

PREPARATION, CONTACT, CONDITIONING, EXPLOITATION, MAINTENANCE = (
    "Preparation", "InitialContact", "Conditioning", "Exploitation", "Maintenance")
STATES = (PREPARATION, CONTACT, CONDITIONING, EXPLOITATION, MAINTENANCE)
BACKBONE = (CONTACT, CONDITIONING, EXPLOITATION, MAINTENANCE)
START = "start"
COMPLETED, DISRUPTED, UNRESOLVED = "Completed", "Disrupted", "Unresolved"
TERMINAL = (COMPLETED, DISRUPTED, UNRESOLVED)
STOP = "(stop)"
DETECTED = "(detected)"

CAC_GROOMING = "https://cacontology.projectvic.org/grooming#"
CAC_MATCH = {CONTACT: CAC_GROOMING + "InitialContactPhase", CONDITIONING: CAC_GROOMING + "ConditioningPhase",
             EXPLOITATION: CAC_GROOMING + "ExploitationPhase", MAINTENANCE: CAC_GROOMING + "MaintenancePhase"}

ROLE = {
    "setup": "prepare",
    "contact": "reach", "recruit": "reach", "access": "reach",
    "deception": "leverage", "demand": "leverage", "threat": "leverage", "control": "leverage", "transport": "leverage",
    "transfer": "extract", "exploit": "extract",
    "supply": "deliver",
    "movement": "after", "concealment": "after",
}
_BEFORE = (START, PREPARATION, CONTACT, CONDITIONING)


def next_state(state: str, kind: str) -> str:
    """The state an act of `kind` moves the offense to from `state`."""
    role = ROLE[kind]
    if role == "prepare":
        return PREPARATION if state == START else state
    if role == "reach":
        return CONTACT if state in (START, PREPARATION) else state
    if role == "leverage":
        if state in _BEFORE:
            return CONDITIONING
        return MAINTENANCE
    if role in ("extract", "deliver"):
        return EXPLOITATION
    return state


def action_of(act: dict[str, Any], level: str = "act") -> str:
    """An act as an action: `contact`, or `contact[whatsapp]` at the means level."""
    if level == "act":
        return act["kind"]
    means = act.get("means") or {}
    labels = sorted(set(means.get("platform", []) + means.get("channel", [])))
    return f"{act['kind']}[{'+'.join(labels)}]" if labels else act["kind"]


def steps(trajectory: dict[str, Any], *, level: str = "act") -> list[tuple[str, str, str]]:
    """A trajectory as (state, action, next state) triples from `start` to a terminal state.

    A repeat of the same step is counted once. Detection ends the trajectory:
    in Completed if exploitation was reached, in Disrupted if not. A telling
    that ends without detection takes `(stop)` to Completed or Unresolved."""
    out: list[tuple[str, str, str]] = []
    state, reached = START, False
    for act in trajectory["acts"]:
        if act["kind"] == "detection":
            if out:
                out.append((state, DETECTED, COMPLETED if reached else DISRUPTED))
                return out
            continue
        nxt = next_state(state, act["kind"])
        step = (state, action_of(act, level), nxt)
        if not out or out[-1] != step:
            out.append(step)
        state, reached = nxt, reached or nxt == EXPLOITATION
    if out:
        out.append((state, STOP, COMPLETED if reached else UNRESOLVED))
    return out


def path(trajectory: dict[str, Any]) -> list[str]:
    """The states a trajectory occupies, in order, a run of one state counted once, ending in its terminal state."""
    out: list[str] = []
    for _, _, nxt in steps(trajectory):
        if not out or out[-1] != nxt:
            out.append(nxt)
    return out


def predicate(trajectory: dict[str, Any]) -> str:
    """`passes`: exploitation reached by taking from the victim. `fails`: reached only by supplying
    contraband. `not_reached`: the telling never reaches exploitation."""
    extracted = delivered = False
    state = START
    for act in trajectory["acts"]:
        if act["kind"] == "detection":
            break
        nxt = next_state(state, act["kind"])
        if nxt == EXPLOITATION:
            extracted |= ROLE[act["kind"]] == "extract"
            delivered |= ROLE[act["kind"]] == "deliver"
        state = nxt
    return "passes" if extracted else "fails" if delivered else "not_reached"
