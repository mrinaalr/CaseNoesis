"""Events: what happened in a case, when, to whom, in order.

A record reports events: "was indicted in March 2023", "pleaded guilty
today", "was sentenced on Sept. 8, 2023". Extraction settles each report as an
`event` value anchored on the words that say it. This layer gives each one a
date and a person, joins the reports of a case's records into one list, and
puts the list in order.

A date comes from one of three places, in this order:

    stated     a settled date in the same sentence whose role fits the event
    relative   "today" or "yesterday" beside the trigger, read against the
               record's publication date
    document   a charging document is itself the charge: its filing date

An event with none of these is kept with no date. It is known to have
happened by the time the record was published, and nothing more.

Two reports are one event when they are the same kind of event, their people
do not conflict, and their dates do not conflict. A month contains its days,
and an undated report matches a dated one. Two sentencings on different dates
stay two events: that is a resentencing, or an error in a record, and either
is worth seeing.

Order is by date. An event with no date is placed by where its kind falls in
a prosecution, after the last event that cannot follow it. `order_basis` says
which it was, so an analysis can keep to dated events when it needs to.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from extraction import people as people_layer, resolve, spans as sp, store

EVENTS_VERSION = "events_1.0"

# Where each kind of event falls in a prosecution. Used only to place events with no date.
RANK = {"offense": 0, "arrest": 1, "complaint": 1, "indictment": 2, "information": 2, "charge": 2,
        "plea": 3, "verdict": 3, "conviction": 3, "sentencing": 4}
# Date roles that can date each kind of event.
_DATE_ROLES = {
    "sentencing": ("sentencing",), "plea": ("plea",), "verdict": ("verdict",), "conviction": ("verdict", "plea"),
    "indictment": ("indictment",), "information": ("indictment",), "complaint": ("indictment", "filed"),
    "charge": ("indictment",), "arrest": ("arrest",),
}
_DOCUMENT_EVENT = {"indictment": "indictment", "information": "information", "complaint": "complaint"}
_TODAY = re.compile(r"\b(?:today|this\s+(?:morning|afternoon|evening)|earlier\s+today)\b", re.I)
_YESTERDAY = re.compile(r"\byesterday\b", re.I)
_REACH = 70


def _finals(db: sqlite3.Connection, record_id: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in db.execute(
        "SELECT field, body FROM resolutions WHERE record_id = ? AND rule_set_version = ?",
        (record_id, resolve.RULE_SET_VERSION),
    ):
        out[row["field"]] = json.loads(row["body"])["finals"]
    return out


def _precision(stamp: str | None) -> str:
    return "none" if not stamp else "month" if len(stamp) == 7 else "day"


def record_events(db: sqlite3.Connection, record_id: str, entry: dict[str, Any], text: str) -> list[dict[str, Any]]:
    """The events one record reports, each with a date where it has one."""
    finals = _finals(db, record_id)
    to_case = people_layer.case_person(db, record_id)
    everyone = sorted(set(to_case.values()))
    whose = {
        (row["span_start"], row["span_end"]): sorted({to_case[p] for p in json.loads(row["people"]) if p in to_case})
        for row in db.execute("SELECT span_start, span_end, people FROM attributions WHERE record_id = ? AND field = 'event'", (record_id,))
    }
    dates = [(start, end, final["value"], final["role"]) for final in finals.get("date", []) for start, end in final["spans"]]
    published = str(entry.get("pub_date") or "")[:10]
    out: list[dict[str, Any]] = []

    for final in finals.get("event", []):
        kind = final["role"]
        for start, end in final["spans"]:
            ss, se = sp.sentence_at(text, start, end)
            ss, se = max(ss, start - 600), min(se, end + 600)
            fitting = [d for d in dates if ss <= d[0] < se and d[3] in _DATE_ROLES.get(kind, ())]
            stamp, basis = None, "undated"
            if fitting:
                nearest = min(fitting, key=lambda d: min(abs(d[0] - end), abs(start - d[1])))
                stamp, basis = nearest[2], "stated"
            elif len(published) == 10 and entry.get("kind") == "press":
                near = text[max(ss, start - 30): min(se, end + _REACH)]
                if _TODAY.search(near):
                    stamp, basis = published, "relative"
                elif _YESTERDAY.search(near):
                    stamp, basis = (date.fromisoformat(published) - timedelta(days=1)).isoformat(), "relative"
            out.append({
                "type": kind, "date": stamp, "people": whose.get((start, end), []), "basis": basis,
                "record_id": record_id, "span": [start, end], "status": final["status"], "bound": published or None,
            })

    # A report that names no one, beside reports of the same kind that do: "a resident was
    # sentenced today ... a co-defendant was sentenced in March". It is about the defendants
    # the others are not about.
    for report in out:
        if not report["people"]:
            named = {p for other in out if other["type"] == report["type"] and other is not report for p in other["people"]}
            rest = sorted(set(everyone) - named)
            if named and rest:
                report["people"] = rest

    # A charging document is the charge it makes.
    filed = [final for final in finals.get("date", []) if final["role"] == "filed"]
    for final in finals.get("document_type", []):
        kind = _DOCUMENT_EVENT.get(final["value"])
        if kind and filed and entry.get("kind") == "court":
            stamp = max(filed, key=lambda f: len(f["spans"]))["value"]
            out.append({
                "type": kind, "date": stamp, "people": everyone, "basis": "document", "record_id": record_id,
                "span": final["spans"][0] if final["spans"] else None, "status": final["status"], "bound": None,
            })

    # When the conduct began: the earliest date the record gives for the offense.
    offense = sorted((final["value"], final) for final in finals.get("date", []) if final["role"] == "offense")
    if offense:
        stamp, final = offense[0]
        out.append({
            "type": "offense", "date": stamp, "people": everyone, "basis": "stated", "record_id": record_id,
            "span": final["spans"][0] if final["spans"] else None, "status": final["status"], "bound": None,
            "until": offense[-1][0] if len(offense) > 1 else None,
        })
    return out


def _dates_agree(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return True
    short, long_ = sorted((left, right), key=len)
    return long_.startswith(short)


def _people_agree(left: list[str], right: list[str]) -> bool:
    return not left or not right or bool(set(left) & set(right))


def merge(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reports of the same event, joined. Dated reports are placed first so an
    undated one can find the event it belongs to."""
    events: list[dict[str, Any]] = []
    ordered = sorted(reports, key=lambda r: (r["date"] is None, -len(r["date"] or ""), r["date"] or "", r["record_id"], str(r["span"])))
    for report in ordered:
        if report["type"] == "offense":
            # One per case: when the conduct began is the earliest date any record gives for it.
            known = next((event for event in events if event["type"] == "offense"), None)
            if known is not None:
                dates = [d for d in (known["date"], report["date"]) if d]
                known["date"] = min(dates, key=lambda d: d if len(d) == 10 else d + "-01") if dates else None
                known["until"] = max(filter(None, (known.get("until"), report.get("until"), known["date"], report["date"])), default=None)
                known["people"] = sorted(set(known["people"]) | set(report["people"]))
                known["evidence"].append({k: report[k] for k in ("record_id", "span", "basis", "status")})
                continue
        matches = [
            event for event in events
            if event["type"] == report["type"] and _dates_agree(event["date"], report["date"])
            and _people_agree(event["people"], report["people"])
        ]
        # A conviction with no stated kind is the plea or verdict the case's other records report.
        if not matches and report["type"] == "conviction":
            matches = [
                event for event in events
                if event["type"] in ("plea", "verdict") and _dates_agree(event["date"], report["date"])
                and _people_agree(event["people"], report["people"])
            ]
        if report["date"] is None:
            # A record that says "was sentenced today" and then gives each defendant's term
            # is reporting one sentencing. An undated report joins the one dated event of
            # its kind that the same record reports, whoever that event already names.
            same_record = [
                event for event in events
                if event["type"] == report["type"] and event["date"]
                and any(e["record_id"] == report["record_id"] for e in event["evidence"])
            ]
            if len({event["date"] for event in same_record}) == 1:
                matches = same_record[:1]
        if report["date"] is None and len({(e["date"], tuple(e["people"])) for e in matches}) > 1:
            # Which of several dated events an undated report means cannot be told. Prefer the same people.
            same = [e for e in matches if set(e["people"]) == set(report["people"])]
            matches = same[:1] or matches[:1]
        if matches:
            event = matches[0]
            if report["date"] and (event["date"] is None or len(report["date"]) > len(event["date"])):
                event["date"] = report["date"]
            event["people"] = sorted(set(event["people"]) | set(report["people"]))
            event["evidence"].append({k: report[k] for k in ("record_id", "span", "basis", "status")})
            if report.get("until"):
                event["until"] = max(event.get("until") or "", report["until"])
        else:
            events.append({
                "type": report["type"], "date": report["date"], "people": list(report["people"]),
                "evidence": [{k: report[k] for k in ("record_id", "span", "basis", "status")}],
                "until": report.get("until"), "bound": report.get("bound"),
            })
    return events


def order(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Events in order: by date, then by kind. An event with no date goes
    after the last event of its kind's stage or earlier."""
    def key(event: dict[str, Any]) -> tuple[str, int]:
        stamp = event["date"]
        return (stamp if len(stamp) == 10 else stamp + "-01", RANK.get(event["type"], 9))

    dated = sorted((e for e in events if e["date"]), key=key)
    for event in dated:
        event["order_basis"] = "date"
    out = list(dated)
    for event in sorted((e for e in events if not e["date"]), key=lambda e: RANK.get(e["type"], 9)):
        event["order_basis"] = "kind"
        rank = RANK.get(event["type"], 9)
        position = 0
        for index, other in enumerate(out):
            if RANK.get(other["type"], 9) <= rank:
                position = index + 1
        out.insert(position, event)
    return out


def build(db: sqlite3.Connection | None = None, source: Any = None) -> dict[str, Any]:
    """Rebuild the `events` table: every case's events, in order."""
    from extraction.source import CorpusSource

    db = db or store.connect()
    source = source or CorpusSource()
    db.execute("DELETE FROM events")
    by_case: dict[str, list[str]] = defaultdict(list)
    for row in db.execute("SELECT case_id, record_id FROM cases ORDER BY case_id, record_id"):
        by_case[row["case_id"]].append(row["record_id"])
    has_events = {row[0] for row in db.execute(
        "SELECT DISTINCT record_id FROM finals WHERE field IN ('event', 'date', 'document_type')")}
    summary: dict[str, Any] = {"cases": len(by_case), "cases_with_events": 0, "events": 0, "by_type": {}, "by_order_basis": {}, "by_date_basis": {}}
    for count, (case_id, record_ids) in enumerate(by_case.items(), start=1):
        reports: list[dict[str, Any]] = []
        for record_id in record_ids:
            if record_id not in has_events:
                continue
            text = source.text(record_id)
            if text:
                reports += record_events(db, record_id, source.entry(record_id), text)
        events = order(merge(reports))
        summary["cases_with_events"] += bool(events)
        for position, event in enumerate(events):
            status = "agreed" if any(e["status"] == "agreed" for e in event["evidence"]) else event["evidence"][0]["status"]
            db.execute(
                "INSERT INTO events (case_id, position, type, date, precision, people, status, order_basis, evidence) VALUES (?,?,?,?,?,?,?,?,?)",
                (case_id, position, event["type"], event["date"], _precision(event["date"]), json.dumps(event["people"]),
                 status, event["order_basis"], json.dumps({"reports": event["evidence"], "until": event.get("until"), "bound": event.get("bound")})),
            )
            summary["events"] += 1
            summary["by_type"][event["type"]] = summary["by_type"].get(event["type"], 0) + 1
            summary["by_order_basis"][event["order_basis"]] = summary["by_order_basis"].get(event["order_basis"], 0) + 1
            for report in event["evidence"]:
                summary["by_date_basis"][report["basis"]] = summary["by_date_basis"].get(report["basis"], 0) + 1
        if count % 2000 == 0:
            db.commit()
    db.commit()
    return summary


def timeline(db: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    """One case's events in order."""
    rows = db.execute("SELECT * FROM events WHERE case_id = ? ORDER BY position", (case_id,)).fetchall()
    return [
        {"position": row["position"], "type": row["type"], "date": row["date"], "precision": row["precision"],
         "people": json.loads(row["people"]), "status": row["status"], "order_basis": row["order_basis"],
         **json.loads(row["evidence"])}
        for row in rows
    ]
