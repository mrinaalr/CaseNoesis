"""Resolution: one decision per mention, by evidence family.

Assertions are never edited or merged here. This module reads them and writes
a decision, so the corpus can be re-resolved under a new rule set without
re-reading a single record.

Rule set `noesis_resolve_v1.0` (after CaseLinker `resolve_v3.0`):

1. A human verdict wins.
2. `unknown` is an abstention, never a competing role.
3. Votes count by family. Two methods in one family are one vote. A family
   that asserts two roles for one mention abstains.
4. Two families that disagree veto the mention. It never finalizes.
5. One role from two families is `agreed`. One family at confidence >= 0.7 is
   `resolved`. Anything weaker is `needs_review`.
6. Settled mentions finalize while other mentions in the same record stay open
   (`partial`).
7. A witness with no span (collector metadata) can corroborate or contest a
   mention another family found in the text. It never creates a value.
8. A role in the field's excluded list ("not a sentence", "boilerplate") is a
   real vote and is never stored as a value.

A mention is a span for a mention field and a label for a tag field.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from extraction import fields

RULE_SET_VERSION = "noesis_resolve_v1.0"
SINGLE_FAMILY_MIN_CONFIDENCE = 0.7

SETTLED = ("agreed", "resolved", "human")
_RANK = {"resolved": 0, "agreed": 1, "human": 2}


def _aid(assertion: dict[str, Any]) -> Any:
    return assertion.get("id") if assertion.get("id") is not None else assertion.get("seq")


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) < 0.005
    return left == right


def _vote(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Family votes for one mention: a settled role, a contest, or an abstention."""
    humans = [a for a in items if a.get("family") == "human" and (a.get("role") or "unknown") != "unknown"]
    if humans:
        return {"state": "human", "role": humans[-1]["role"], "families": ["human"], "support": humans[-1:]}
    by_family: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for assertion in items:
        role = assertion.get("role") or "unknown"
        if role != "unknown":
            by_family[str(assertion.get("family"))][role].append(assertion)
    votes: dict[str, str] = {}
    contradictions = []
    for family, roles in by_family.items():
        if len(roles) == 1:
            votes[family] = next(iter(roles))
        else:
            contradictions.append({"family": family, "roles": sorted(roles)})
    out: dict[str, Any] = {}
    if contradictions:
        out["self_contradictions"] = contradictions
    distinct = sorted(set(votes.values()))
    if len(distinct) > 1:
        out["state"] = "contested"
        out["roles"] = {role: sorted(f for f, v in votes.items() if v == role) for role in distinct}
        return out
    if not distinct:
        out["state"] = "self_contradiction" if contradictions else "unassigned"
        return out
    role = distinct[0]
    families = sorted(f for f, v in votes.items() if v == role)
    support = [a for f in families for a in by_family[f][role]]
    # A span-less witness cannot settle a mention by itself (rule 7).
    spanned = [a for a in support if a.get("span_ok")]
    best = max((float(a.get("confidence") or 0) for a in spanned), default=0.0)
    out.update(role=role, families=families, support=support)
    if not spanned:
        out["state"] = "unassigned"
    elif len(families) >= 2:
        out["state"] = "agreed"
    elif best >= SINGLE_FAMILY_MIN_CONFIDENCE:
        out["state"] = "resolved"
    else:
        out["state"] = "weak"
    return out


def _mention_key(spec: fields.FieldSpec, assertion: dict[str, Any]) -> Any:
    if spec.shape == "tag":
        return ("label", assertion.get("value"))
    return ("span", assertion.get("span_start"), assertion.get("span_end"))


def resolve_field(spec: fields.FieldSpec, assertions: list[dict[str, Any]]) -> dict[str, Any]:
    """One field of one record. `assertions` are gated rows for that field."""
    spanned = [a for a in assertions if a.get("span_ok")]
    spanless = [a for a in assertions if not a.get("span_ok") and a.get("family") in ("metadata", "human")]
    mentions: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for assertion in spanned:
        mentions[_mention_key(spec, assertion)].append(assertion)
    # Attach each span-less witness to every mention with the same value.
    for witness in spanless:
        for items in mentions.values():
            if _same_value(items[0].get("value"), witness.get("value")):
                items.append(witness)

    finals: dict[tuple[str, str], dict[str, Any]] = {}
    review: list[dict[str, Any]] = []
    unassigned = 0
    states: list[str] = []
    for key in sorted(mentions, key=lambda k: tuple(str(part) for part in k)):
        items = mentions[key]
        vote = _vote(items)
        state = vote["state"]
        anchors = sorted({(a["span_start"], a["span_end"]) for a in items if a.get("span_ok")})
        value = next(a.get("value") for a in items if a.get("span_ok"))
        if state == "unassigned":
            unassigned += 1
            continue
        states.append(state)
        if state in SETTLED:
            role = vote["role"]
            if role in spec.excluded_roles:
                continue
            support = vote["support"]
            slot = finals.setdefault((role, repr(value)), {
                "value": value, "role": role, "status": state, "spans": [], "families": set(),
                "methods": set(), "assertion_ids": set(), "confidence": 0.0, "extras": {},
            })
            if _RANK[state] > _RANK[slot["status"]]:
                slot["status"] = state
            slot["spans"].extend(span for span in anchors if span not in slot["spans"])
            slot["families"].update(vote["families"])
            slot["methods"].update(str(a.get("method")) for a in support)
            slot["assertion_ids"].update(i for i in map(_aid, support) if i is not None)
            slot["confidence"] = max(slot["confidence"], *(float(a.get("confidence") or 0) for a in support))
            for assertion in support:
                for name, item in (assertion.get("extras") or {}).items():
                    if name not in ("gate_reason", "cue_pattern", "cue"):
                        slot["extras"].setdefault(name, item)
        else:
            entry: dict[str, Any] = {"state": state, "value": value, "spans": [list(span) for span in anchors]}
            if "roles" in vote:
                entry["roles"] = vote["roles"]
            if "role" in vote:
                entry["role"] = vote["role"]
                entry["families"] = vote["families"]
            if "self_contradictions" in vote:
                entry["self_contradictions"] = vote["self_contradictions"]
            review.append(entry)

    final_list = [
        {
            **slot,
            "spans": [list(span) for span in sorted(slot["spans"])],
            "families": sorted(slot["families"]),
            "methods": sorted(slot["methods"]),
            "assertion_ids": sorted(slot["assertion_ids"], key=str),
            "confidence": round(slot["confidence"], 3),
        }
        for slot in finals.values()
    ]
    final_list.sort(key=lambda item: (item["spans"][0] if item["spans"] else [1 << 30], item["role"]))

    if not spanned:
        status = "empty"
    elif final_list and review:
        status = "partial"
    elif final_list:
        status = "agreed" if all(item["status"] in ("agreed", "human") for item in final_list) else "resolved"
    elif any(entry["state"] == "contested" for entry in review):
        status = "disagreement"
    elif review:
        status = "needs_review"
    else:
        status = "unassigned" if unassigned else "empty"
    return {
        "field": spec.name,
        "status": status,
        "rule_set_version": RULE_SET_VERSION,
        "finals": final_list,
        "review": review,
        "unassigned": unassigned,
        "mentions": len(mentions),
    }


def resolve_record(assertions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every registered field of one record. Fields with no assertion are left out."""
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assertion in assertions:
        by_field[str(assertion.get("field"))].append(assertion)
    out: dict[str, dict[str, Any]] = {}
    for spec in fields.all_fields():
        if spec.name in by_field:
            out[spec.name] = resolve_field(spec, by_field[spec.name])
    return out
