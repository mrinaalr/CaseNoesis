"""Cases: which records are about the same prosecution.

A record id names one document. A case is a docket: the release that
announced it, the indictment, the plea agreement, the judgment. Records join
a case only on a link that cannot be a coincidence:

    press_link          the collector followed this press release to this filing
    courtlistener       two filings carry the same CourtListener docket id
    docket_and_court    two filings carry the same docket number in the same court

A docket number alone is not such a link. Federal districts number their
cases independently, so `1:23-cr-00123` exists in many courts. Two records
that share only a number are written to `case_candidates` for a person to
confirm, and are not merged.

A record with no link is a case of one.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import defaultdict
from typing import Any

from encoding import corpus
from extraction import fields, store

_DOCKET_ID = re.compile(r"courtlistener\.com/(?:docket|recap/gov\.uscourts\.[a-z]+\.)(\d+)")


class _Sets:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def _docket_numbers(db: sqlite3.Connection, record_id: str, entry: dict[str, Any]) -> list[str]:
    """Docket numbers a record carries: the collector's, then the ones the
    readers settled, most-cited first."""
    numbers = [value for _, _, value, _ in fields.iter_case_number(str(entry.get("docket_number") or ""))]
    rows = db.execute(
        "SELECT value, spans FROM finals WHERE record_id = ? AND field = 'case_number'", (record_id,)
    ).fetchall()
    for row in sorted(rows, key=lambda r: -len(r["spans"])):
        if row["value"] not in numbers:
            numbers.append(row["value"])
    return numbers


def build(db: sqlite3.Connection | None = None, source: Any = None) -> dict[str, Any]:
    """Rebuild the `cases` and `case_candidates` tables from scratch."""
    from extraction.source import CorpusSource

    db = db or store.connect()
    index = {entry["record_id"]: entry for entry in (source or CorpusSource()).entries()}
    record_ids = store.record_ids(db)
    sets = _Sets()
    basis: dict[str, set[str]] = defaultdict(set)
    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_number: dict[str, list[str]] = defaultdict(list)
    present = set(record_ids)

    for record_id in record_ids:
        sets.find(record_id)
        entry = index.get(record_id, {})
        match = _DOCKET_ID.search(str(entry.get("source_url") or ""))
        if match:
            by_key[("courtlistener", match.group(1))].append(record_id)
        press_url = entry.get("press_url")
        if press_url:
            press_id = corpus.press_record_id(str(press_url))
            if press_id in present:
                sets.union(record_id, press_id)
                basis[record_id].add("press_link")
                basis[press_id].add("press_link")
        numbers = _docket_numbers(db, record_id, entry)
        court = str(entry.get("agency") or "") if entry.get("kind") == "court" else ""
        for position, number in enumerate(numbers):
            # Only a filing's own number (the first) with its court is a strong key.
            if court and position == 0:
                by_key[("docket_and_court", f"{court}|{number}")].append(record_id)
            by_number[number].append(record_id)

    for (kind, _), members in by_key.items():
        for other in members[1:]:
            sets.union(members[0], other)
        if len(members) > 1:
            for member in members:
                basis[member].add(kind)

    groups: dict[str, list[str]] = defaultdict(list)
    for record_id in record_ids:
        groups[sets.find(record_id)].append(record_id)

    db.execute("DELETE FROM cases")
    db.execute("DELETE FROM case_candidates")
    case_of: dict[str, str] = {}
    for members in groups.values():
        case_id = "case-" + hashlib.sha256(min(members).encode("utf-8")).hexdigest()[:16]
        for member in members:
            case_of[member] = case_id
            db.execute(
                "INSERT INTO cases (case_id, record_id, basis) VALUES (?,?,?)",
                (case_id, member, ",".join(sorted(basis[member])) or "single"),
            )
    candidates = 0
    for number, members in by_number.items():
        distinct = sorted({case_of[m] for m in members})
        if len(distinct) < 2 or len(members) > 12:
            continue  # one case already, or a number too common to be a lead
        ordered = sorted(set(members))
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                if case_of[left] != case_of[right]:
                    db.execute(
                        "INSERT OR IGNORE INTO case_candidates (record_a, record_b, basis) VALUES (?,?,?)",
                        (left, right, f"docket_number_only:{number}"),
                    )
                    candidates += 1
    db.commit()
    sizes = [len(members) for members in groups.values()]
    return {
        "records": len(record_ids),
        "cases": len(groups),
        "cases_with_more_than_one_record": sum(1 for size in sizes if size > 1),
        "largest_case": max(sizes, default=0),
        "candidate_links": candidates,
    }


def case_id_of(db: sqlite3.Connection, record_id: str) -> str | None:
    row = db.execute("SELECT case_id FROM cases WHERE record_id = ?", (record_id,)).fetchone()
    return row["case_id"] if row else None
