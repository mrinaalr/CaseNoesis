"""People: the defendants of a case, and whose each value is.

Extraction numbers the people of one record: `person-1`, `person-2`. This
layer does two things with those numbers.

It links them across the records of a case. The same defendant is `person-1`
in the press release and `person-3` in the judgment; here they become one
case person, `p1`. Two record persons are one case person when they share a
surname and their given names do not conflict. Names are compared in memory,
read from the local text at the stored spans. No name is written.

It settles whose each term, amount and event is. The `attribution` field
holds the readers' votes. Where a record has one defendant, a value no vote
placed is that defendant's: the record cannot be giving it to anyone else.
Where a record has several and no vote settled, the value stays with no one.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

from extraction import names as name_rules, resolve, store

# Roles that belong to one person. A loss or a statutory maximum is the case's.
PERSONAL = {
    "sentence": ("imposed", "supervised_release", "probation"),
    "money": ("restitution", "forfeiture", "fine", "special_assessment", "bail"),
    "event": ("arrest", "complaint", "indictment", "information", "charge", "plea", "verdict", "conviction", "sentencing"),
}


def _finals(db: sqlite3.Connection, record_id: str, field: str) -> list[dict[str, Any]]:
    row = db.execute(
        "SELECT body FROM resolutions WHERE record_id = ? AND field = ? AND rule_set_version = ?",
        (record_id, field, resolve.RULE_SET_VERSION),
    ).fetchone()
    return json.loads(row["body"])["finals"] if row else []


def defendants(db: sqlite3.Connection, record_id: str) -> list[dict[str, Any]]:
    return [final for final in _finals(db, record_id, "party") if final["role"] == "defendant"]


def _compatible(left: tuple[str, str], right: tuple[str, str]) -> bool:
    (surname, given), (other_surname, other_given) = left, right
    if surname != other_surname:
        return False
    if not given or not other_given or given == other_given:
        return True
    return min(len(given), len(other_given)) == 1 and given[0] == other_given[0]


def _key(text: str, final: dict[str, Any]) -> tuple[str, str]:
    """The fullest form of this person's name among the record's mentions."""
    keys = [name_rules.person_key(text[start:end]) for start, end in final["spans"]]
    return max(keys, key=lambda key: (bool(key[1]), len(key[1]), len(key[0])), default=("", ""))


def link_case(members: list[tuple[str, list[dict[str, Any]], str | None]]) -> list[tuple[str, str, str, str]]:
    """`(person, record_id, record_person, basis)` rows for one case.
    `members` is `(record_id, defendant finals, text)` per record."""
    if len(members) == 1:
        record_id, finals, _ = members[0]
        return [(f"p{number}", record_id, final["value"], "single_record") for number, final in enumerate(finals, start=1)]
    known: list[tuple[str, str]] = []
    rows = []
    for record_id, finals, text in members:
        for final in finals:
            key = _key(text or "", final)
            for number, other in enumerate(known, start=1):
                if key[0] and _compatible(key, other):
                    if len(key[1]) > len(other[1]):
                        known[number - 1] = key  # keep the fuller given name
                    break
            else:
                known.append(key)
                number = len(known)
            rows.append((f"p{number}", record_id, final["value"], "name_match"))
    return rows


def build(db: sqlite3.Connection | None = None, source: Any = None) -> dict[str, Any]:
    """Rebuild `people` and `attributions` from the current decisions."""
    from extraction.source import CorpusSource

    db = db or store.connect()
    source = source or CorpusSource()
    db.execute("DELETE FROM people")
    db.execute("DELETE FROM attributions")
    by_case: dict[str, list[str]] = defaultdict(list)
    for row in db.execute("SELECT case_id, record_id FROM cases ORDER BY case_id, record_id"):
        by_case[row["case_id"]].append(row["record_id"])

    summary = {"cases": len(by_case), "people": 0, "people_in_more_than_one_record": 0,
               "attributions": {"vote": 0, "sole_defendant": 0}, "unattributed_in_multi_defendant_records": 0}
    for case_id, record_ids in by_case.items():
        found = {record_id: defendants(db, record_id) for record_id in record_ids}
        with_people = [record_id for record_id in record_ids if found[record_id]]
        members = [
            (record_id, found[record_id], source.text(record_id) if len(with_people) > 1 else None)
            for record_id in with_people
        ]
        rows = link_case(members) if members else []
        seen: dict[str, set[str]] = defaultdict(set)
        for person, record_id, record_person, basis in rows:
            db.execute("INSERT OR REPLACE INTO people (case_id, person, record_id, record_person, basis) VALUES (?,?,?,?,?)",
                       (case_id, person, record_id, record_person, basis))
            seen[person].add(record_id)
        summary["people"] += len(seen)
        summary["people_in_more_than_one_record"] += sum(1 for records in seen.values() if len(records) > 1)
        for record_id in record_ids:
            counts = _attribute(db, record_id, [final["value"] for final in found[record_id]])
            for key in ("vote", "sole_defendant"):
                summary["attributions"][key] += counts[key]
            summary["unattributed_in_multi_defendant_records"] += counts["unattributed"]
    db.commit()
    return summary


def _attribute(db: sqlite3.Connection, record_id: str, record_people: list[str]) -> dict[str, int]:
    """Write one record's attributions. Returns counts by basis."""
    voted: dict[tuple[str, int, int], dict[str, Any]] = {}
    for final in _finals(db, record_id, "attribution"):
        field, _, span = str(final["value"]).partition(":")
        start, _, end = span.partition("-")
        people = [person for person in final["role"].split("+") if person in record_people]
        if people:
            voted[(field, int(start), int(end))] = {"people": people, "status": final["status"]}
    counts = {"vote": 0, "sole_defendant": 0, "unattributed": 0}
    for field, roles in PERSONAL.items():
        for final in _finals(db, record_id, field):
            if final["role"] not in roles:
                continue
            for start, end in final["spans"]:
                found = voted.get((field, start, end))
                if found:
                    people, status, basis = found["people"], found["status"], "vote"
                elif len(record_people) == 1:
                    people, status, basis = record_people, "resolved", "sole_defendant"
                else:
                    counts["unattributed"] += 1 if record_people else 0
                    continue
                counts[basis] += 1
                value = final["value"]
                db.execute(
                    "INSERT INTO attributions (record_id, field, role, value, span_start, span_end, people, status, basis) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (record_id, field, final["role"], value if isinstance(value, str) else json.dumps(value), start, end,
                     json.dumps(people), status, basis),
                )
    return counts


def case_person(db: sqlite3.Connection, record_id: str) -> dict[str, str]:
    """`{record person: case person}` for one record."""
    return {row["record_person"]: row["person"] for row in db.execute(
        "SELECT record_person, person FROM people WHERE record_id = ?", (record_id,))}
