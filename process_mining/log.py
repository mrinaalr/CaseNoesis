"""The event log: one trace per defendant, built from the engine's events.

Process mining needs a case notion: whose sequence of events is a trace? A
prosecution has more than one answer. Co-defendants are charged together and
sentenced apart, so the docket is too coarse and the event too fine. The
trace here is a defendant in a case. An event that names no one (a release
that says "three people were charged") belongs to every defendant of the
case. A case with no known defendant is one trace.

The same events are also written as an object-centric event log (OCEL 2.0),
which keeps the case, its defendants and its records as separate objects and
does not force that choice on whoever reads it next.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# How much of an event's kind a model sees.
LEVELS = {
    "detailed": {},
    "coarse": {"complaint": "charge", "indictment": "charge", "information": "charge",
               "plea": "disposition", "verdict": "disposition", "conviction": "disposition"},
}


@dataclass
class Trace:
    case_id: str
    person: str
    events: list[dict[str, Any]] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)

    def activities(self, level: str = "detailed") -> tuple[str, ...]:
        names = LEVELS[level]
        return tuple(names.get(event["type"], event["type"]) for event in self.events)

    @property
    def fully_dated(self) -> bool:
        return all(event["order_basis"] == "date" for event in self.events)


def build(db: sqlite3.Connection, *, dated_only: bool = False, domain: str | None = None,
          kinds: tuple[str, ...] | None = None) -> list[Trace]:
    """Traces from the `events` table.

    `dated_only` keeps only events that have a date, so every order in the log
    is an order of dates and none is assumed. `kinds` keeps only some kinds of
    event (for instance, to leave out `offense`)."""
    people: dict[str, list[str]] = defaultdict(list)
    for row in db.execute("SELECT DISTINCT case_id, person FROM people ORDER BY case_id, person"):
        people[row["case_id"]].append(row["person"])
    domains: dict[str, str] = {}
    for row in db.execute("SELECT c.case_id, r.domain FROM cases c JOIN records r ON r.record_id = c.record_id ORDER BY c.case_id, r.kind DESC"):
        domains.setdefault(row["case_id"], row["domain"])
    schemes: dict[str, set[str]] = defaultdict(set)
    for row in db.execute("SELECT c.case_id, f.value FROM finals f JOIN cases c ON c.record_id = f.record_id WHERE f.field = 'scheme'"):
        schemes[row["case_id"]].add(row["value"])

    traces: dict[tuple[str, str], Trace] = {}
    for row in db.execute("SELECT * FROM events ORDER BY case_id, position"):
        case_id = row["case_id"]
        if domain and domains.get(case_id) != domain:
            continue
        if kinds and row["type"] not in kinds:
            continue
        if dated_only and not row["date"]:
            continue
        named = json.loads(row["people"])
        for person in named or people.get(case_id) or ["all"]:
            trace = traces.setdefault((case_id, person), Trace(case_id, person, attributes={
                "domain": domains.get(case_id), "schemes": sorted(schemes.get(case_id, ())),
            }))
            trace.events.append({
                "type": row["type"], "date": row["date"], "precision": row["precision"],
                "order_basis": row["order_basis"], "status": row["status"], "event_id": row["event_id"],
            })
    return [trace for _, trace in sorted(traces.items())]


def summary(traces: list[Trace]) -> dict[str, Any]:
    events = [event for trace in traces for event in trace.events]
    lengths = sorted(len(trace.events) for trace in traces)
    return {
        "traces": len(traces),
        "cases": len({trace.case_id for trace in traces}),
        "events": len(events),
        "events_with_a_date": sum(1 for event in events if event["date"]),
        "traces_ordered_by_dates_alone": sum(1 for trace in traces if trace.fully_dated),
        "events_per_trace": {
            "median": lengths[len(lengths) // 2] if lengths else 0,
            "max": lengths[-1] if lengths else 0,
            "one": sum(1 for n in lengths if n == 1),
            "two": sum(1 for n in lengths if n == 2),
            "three_or_more": sum(1 for n in lengths if n >= 3),
        },
    }


def _stamp(event_date: str) -> str:
    return (event_date if len(event_date) == 10 else event_date + "-01") + "T00:00:00Z"


def ocel(db: sqlite3.Connection) -> dict[str, Any]:
    """The dated events as an OCEL 2.0 log. Object types: case, defendant, record.
    OCEL requires a time on every event, so undated events are left out; the
    count of them is in the log's own summary, not in the file."""
    kinds = sorted({row[0] for row in db.execute("SELECT DISTINCT type FROM events WHERE date IS NOT NULL")})
    event_attributes = [{"name": "date_precision", "type": "string"}, {"name": "status", "type": "string"}]
    out: dict[str, Any] = {
        "objectTypes": [
            {"name": "case", "attributes": [{"name": "domain", "type": "string"}]},
            {"name": "defendant", "attributes": []},
            {"name": "record", "attributes": [{"name": "kind", "type": "string"}]},
        ],
        "eventTypes": [{"name": kind, "attributes": event_attributes} for kind in kinds],
        "objects": [], "events": [],
    }
    cases: dict[str, dict[str, Any]] = {}
    for row in db.execute(
        "SELECT c.case_id, c.record_id, r.kind, r.domain FROM cases c JOIN records r ON r.record_id = c.record_id "
        "WHERE c.case_id IN (SELECT case_id FROM events WHERE date IS NOT NULL) ORDER BY c.case_id, c.record_id"
    ):
        case = cases.setdefault(row["case_id"], {"domain": row["domain"], "records": []})
        case["records"].append(row["record_id"])
        out["objects"].append({
            "id": row["record_id"], "type": "record",
            "attributes": [{"name": "kind", "time": "1970-01-01T00:00:00Z", "value": row["kind"]}],
            "relationships": [{"objectId": row["case_id"], "qualifier": "record of"}],
        })
    defendants: dict[str, list[str]] = defaultdict(list)
    for row in db.execute("SELECT DISTINCT case_id, person FROM people ORDER BY case_id, person"):
        if row["case_id"] in cases:
            defendants[row["case_id"]].append(row["person"])
            out["objects"].append({
                "id": f"{row['case_id']}/{row['person']}", "type": "defendant", "attributes": [],
                "relationships": [{"objectId": row["case_id"], "qualifier": "defendant in"}],
            })
    for case_id, case in cases.items():
        out["objects"].append({
            "id": case_id, "type": "case",
            "attributes": [{"name": "domain", "time": "1970-01-01T00:00:00Z", "value": case["domain"]}],
            "relationships": [],
        })
    for row in db.execute("SELECT * FROM events WHERE date IS NOT NULL ORDER BY case_id, position"):
        evidence = json.loads(row["evidence"])
        related = [{"objectId": row["case_id"], "qualifier": "case"}]
        related += [{"objectId": f"{row['case_id']}/{person}", "qualifier": "defendant"}
                    for person in json.loads(row["people"]) or defendants.get(row["case_id"], [])]
        related += [{"objectId": record_id, "qualifier": "reported by"}
                    for record_id in sorted({report["record_id"] for report in evidence["reports"]})]
        out["events"].append({
            "id": f"e{row['event_id']}", "type": row["type"], "time": _stamp(row["date"]),
            "attributes": [{"name": "date_precision", "value": row["precision"]}, {"name": "status", "value": row["status"]}],
            "relationships": related,
        })
    return out


def write_ocel(db: sqlite3.Connection, path: Path) -> dict[str, int]:
    log = ocel(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
    return {"events": len(log["events"]), "objects": len(log["objects"]), "event_types": len(log["eventTypes"])}
