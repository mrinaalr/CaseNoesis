"""Conduct sequences: the acts a record narrates, in order.

Extraction settles each act as a `conduct` value: the words that report it
and what kind of act it is. This layer turns the acts of one record into a
sequence: each with the date its sentence gives, the defendant it belongs to,
and its place in the telling.

The unit is the record, not the case. A statement of offense tells the whole
offense once, in order. Two records of one case tell the same acts again in
different words, and joining them would need to decide which sentences
describe the same act; that is not attempted. An analysis of a case's conduct
uses the record that narrates the most.

**Order.** A narrative of facts is told in the order things happened, and
most of its sentences carry no date. The sequence is therefore the order of
telling. Where every act has a date the dates are also checked: `dated` says
how many acts have one and `in_date_order` whether the telling follows them.

**Means.** The claim this layer exists to test is that technology enters an
offense through its actions. So each act carries its means: the channel and
platform labels whose cue is in the same sentence as the act. "Contacted the
victim on WhatsApp" is a `contact` by `whatsapp`; the same act in another
case is a `contact` by `phone_call`. A record-level label says a platform
appears somewhere in the case. This says at which step.

**Detection is kept.** What investigators did (an undercover contact, a
search) is part of the narrative and marks where the offense met its end. It
is in the sequence under its own kind so that an analysis can keep or drop it.

Acts are collapsed where they repeat with nothing between: ten sentences
about ten wires are one `transfer` step in the path and ten rows here.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from typing import Any

from extraction import people as people_layer, resolve, spans as sp, store

CONDUCT_VERSION = "conduct_1.0"
_PARAGRAPH = re.compile(r"\n[ \t]*(?:\d{1,3}|[a-z])[.)][ \t]+(?=\S)")


def record_acts(db: sqlite3.Connection, record_id: str, text: str) -> list[dict[str, Any]]:
    """One record's acts in the order it tells them."""
    finals: dict[str, list[dict[str, Any]]] = {}
    for row in db.execute("SELECT field, body FROM resolutions WHERE record_id = ? AND field IN ('conduct', 'date', 'channel', 'platform') AND rule_set_version = ?",
                          (record_id, resolve.RULE_SET_VERSION)):
        finals[row["field"]] = json.loads(row["body"])["finals"]
    to_case = people_layer.case_person(db, record_id)
    whose = {
        (row["span_start"], row["span_end"]): sorted({to_case[p] for p in json.loads(row["people"]) if p in to_case})
        for row in db.execute("SELECT span_start, span_end, people FROM attributions WHERE record_id = ? AND field = 'conduct'", (record_id,))
    }
    dates = sorted((start, end, final["value"]) for final in finals.get("date", []) if final["role"] in ("offense", "arrest")
                   for start, end in final["spans"])
    # The technology a sentence names is the means of the act that sentence reports.
    cues = sorted((start, field, final["value"]) for field in ("channel", "platform") for final in finals.get(field, [])
                  for start, _ in final["spans"])
    acts = []
    for final in finals.get("conduct", []):
        for start, end in final["spans"]:
            ss, se = sp.sentence_at(text, start, end)
            ss, se = max(ss, start - 600), min(se, end + 400)
            # A numbered paragraph is a unit of its own. A sentence that ends "... Company A." is
            # not split from the next by the sentence rules, and the next paragraph's date is not this act's.
            before = [m.start() for m in _PARAGRAPH.finditer(text, ss, start)]
            after = _PARAGRAPH.search(text, end, se)
            ss, se = (before[-1] if before else ss), (after.start() if after else se)
            inside = [d for d in dates if ss <= d[0] < se]
            stamp = min(inside, key=lambda d: abs(d[0] - start))[2] if inside else None
            means: dict[str, list[str]] = {"channel": [], "platform": []}
            for position, field, label in cues:
                if ss <= position < se and label not in means[field]:
                    means[field].append(label)
            acts.append({"kind": final["role"], "date": stamp, "people": whose.get((start, end), []),
                         "means": {field: sorted(labels) for field, labels in means.items() if labels},
                         "status": final["status"], "span": (start, end)})
    acts.sort(key=lambda act: act["span"])
    return acts


def build(db: sqlite3.Connection | None = None, source: Any = None) -> dict[str, Any]:
    """Rebuild the `conduct` table from the current decisions."""
    from extraction.source import CorpusSource

    db = db or store.connect()
    source = source or CorpusSource()
    db.execute("DELETE FROM conduct")
    case_of = {row["record_id"]: row["case_id"] for row in db.execute("SELECT record_id, case_id FROM cases")}
    record_ids = [row[0] for row in db.execute("SELECT DISTINCT record_id FROM finals WHERE field = 'conduct' ORDER BY record_id")]
    summary: dict[str, Any] = {"records_with_acts": 0, "acts": 0, "with_a_date": 0, "by_kind": defaultdict(int)}
    for count, record_id in enumerate(record_ids, start=1):
        text = source.text(record_id)
        if not text:
            continue
        acts = record_acts(db, record_id, text)
        summary["records_with_acts"] += bool(acts)
        for position, act in enumerate(acts):
            db.execute(
                "INSERT INTO conduct (record_id, case_id, position, kind, date, precision, people, means, status, span_start, span_end) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (record_id, case_of.get(record_id), position, act["kind"], act["date"],
                 "none" if not act["date"] else "month" if len(act["date"]) == 7 else "day",
                 json.dumps(act["people"]), json.dumps(act["means"], sort_keys=True), act["status"], act["span"][0], act["span"][1]),
            )
            summary["acts"] += 1
            summary["with_a_date"] += bool(act["date"])
            summary["by_kind"][act["kind"]] += 1
        if count % 2000 == 0:
            db.commit()
    db.commit()
    summary["by_kind"] = dict(sorted(summary["by_kind"].items(), key=lambda item: -item[1]))
    return summary


def sequence(db: sqlite3.Connection, record_id: str) -> list[dict[str, Any]]:
    """One record's acts, in order."""
    return [
        {"position": row["position"], "kind": row["kind"], "date": row["date"], "precision": row["precision"],
         "people": json.loads(row["people"]), "means": json.loads(row["means"]), "status": row["status"]}
        for row in db.execute("SELECT * FROM conduct WHERE record_id = ? ORDER BY position", (record_id,))
    ]


def path(acts: list[dict[str, Any]], *, with_detection: bool = True) -> tuple[str, ...]:
    """The kinds in order, with a run of one kind counted once."""
    out: list[str] = []
    for act in acts:
        if act["kind"] == "detection" and not with_detection:
            continue
        if not out or out[-1] != act["kind"]:
            out.append(act["kind"])
    return tuple(out)


def in_date_order(acts: list[dict[str, Any]]) -> bool | None:
    """Whether the telling follows the dates. None when fewer than two acts are dated."""
    stamps = [act["date"] if len(act["date"]) == 10 else act["date"] + "-01" for act in acts if act["date"]]
    return None if len(stamps) < 2 else stamps == sorted(stamps)
