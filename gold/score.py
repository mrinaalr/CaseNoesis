"""Run the engine on the gold corpus and compare what it stores with the truth.

Every score here is a count of things the engine stored against things the
documents state. Nothing is sampled and nothing is judged by a model.

    values       a settled value counts when its role and its value are both right
    tags         labels settled for a record against the labels its text carries
    parties      the defendants a record names
    attribution  of the terms, amounts and events the engine got right and
                 that belong to one person, how many it gave to the right person
    linking      the same defendant across the records of a case
    events       (kind, date, person) for every event a case's records report
    traces       a defendant's whole sequence of events, in order

Names are compared in memory to tell which numbered person is which invented
defendant. The gold corpus is invented, so its names are not anyone's.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from extraction import ENGINE_VERSION, cases, events as events_layer, names as name_rules, people as people_layer, pipeline, resolve, store
from extraction.readers import Doc, reader_versions
from extraction.source import MemorySource
from gold import build

RUNS = store.EXTRACTED / "gold"
VALUE_FIELDS = ("sentence", "money", "date", "statute", "case_number", "victim_count")
COARSE = {"complaint": "charge", "indictment": "charge", "information": "charge", "charge": "charge",
          "plea": "disposition", "verdict": "disposition", "conviction": "disposition"}


def source_for(records: list[dict[str, Any]]) -> MemorySource:
    return MemorySource((record["entry"], record["text"]) for record in records)


def run(records: list[dict[str, Any]], name: str) -> sqlite3.Connection:
    """Read the records into a fresh store under `data/extracted/gold/` and build every layer."""
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{name}.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    db = store.connect(path)
    run_id = store.begin_run(db, engine_version=ENGINE_VERSION, rule_set_version=resolve.RULE_SET_VERSION,
                             readers=reader_versions(), sdk_commit=None, code_revision=None, llm=False)
    for record in records:
        entry = record["entry"]
        doc = Doc(entry["record_id"], entry["kind"], entry["domain"], record["text"], entry, [])
        result = pipeline.read_doc(doc)
        stored = store.save_record(db, run_id, {
            "record_id": doc.record_id, "kind": doc.kind, "domain": doc.domain, "domains": entry.get("domains") or [doc.domain],
            "text_sha256": "gold", "text_source": "gold", "chars": len(doc.text),
        }, result["assertions"])
        store.save_resolutions(db, doc.record_id, resolve.resolve_record(stored))
    db.commit()
    source = source_for(records)
    cases.build(db, source)
    people_layer.build(db, source)
    events_layer.build(db, source)
    return db


class Tally:
    def __init__(self) -> None:
        self.tp = self.fp = self.fn = 0

    def add(self, tp: int = 0, fp: int = 0, fn: int = 0) -> None:
        self.tp, self.fp, self.fn = self.tp + tp, self.fp + fp, self.fn + fn

    def report(self) -> dict[str, Any]:
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn,
                **{k: None if v is None else round(v, 3) for k, v in (("precision", precision), ("recall", recall), ("f1", f1))}}


def _norm(field: str, value: Any, extras: dict[str, Any] | None = None) -> Any:
    if field == "sentence":
        extras = extras or {}
        if extras.get("life") or value == "life":
            return "life"
        return round(float(extras["months"]), 2) if extras.get("months") is not None else value
    if field == "money":
        return round(float(value), 2)
    if field == "statute":
        return re.sub(r"\([^)]*\)", "", str(value)).strip()
    return value


def _finals(db: sqlite3.Connection, record_id: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in db.execute("SELECT field, body FROM resolutions WHERE record_id = ? AND rule_set_version = ?",
                          (record_id, resolve.RULE_SET_VERSION)):
        out[row["field"]] = json.loads(row["body"])["finals"]
    return out


def _who(text: str, finals: list[dict[str, Any]], truth_names: dict[str, list[str]]) -> dict[str, str | None]:
    """`{record person: gold key}` for a record's settled parties."""
    gold = {key: max((name_rules.person_key(form) for form in forms), key=lambda k: len(k[1])) for key, forms in truth_names.items()}
    out: dict[str, str | None] = {}
    for final in finals:
        key = people_layer._key(text, final)
        out[final["value"]] = next((g for g, known in gold.items() if people_layer._compatible(key, known)), None)
    return out


def score(db: sqlite3.Connection, records: list[dict[str, Any]], truth: dict[str, dict[str, Any]],
          gold_cases: list[dict[str, Any]]) -> dict[str, Any]:
    tallies: dict[str, Tally] = defaultdict(Tally)
    by_shape: dict[str, Tally] = defaultdict(Tally)
    misses: list[dict[str, Any]] = []
    attribution = {"right": 0, "wrong": 0, "none": 0, "by_basis": defaultdict(lambda: [0, 0]),
                   "several_defendants": {"right": 0, "wrong": 0, "none": 0}}
    who_by_record: dict[str, dict[str, str | None]] = {}

    for record in records:
        record_id, text, gold = record["record_id"], record["text"], truth[record["record_id"]]
        finals = _finals(db, record_id)

        for field in VALUE_FIELDS:
            wanted = {(tuple(sorted(item["roles"])), _norm(field, item["value"])) for item in gold["values"] if item["field"] == field}
            allowed = {(tuple(sorted(item["roles"])), _norm(field, item["value"])) for item in gold["optional"] if item["field"] == field}
            predicted = {(final["role"], _norm(field, final["value"], final["extras"])) for final in finals.get(field, [])}
            hit = {w for w in wanted if any(role in w[0] and value == w[1] for role, value in predicted)}
            extra = {p for p in predicted if not any(p[0] in roles and p[1] == value for roles, value in wanted | allowed)}
            tallies[field].add(tp=len(hit), fp=len(extra), fn=len(wanted - hit))
            by_shape[record["shape"]].add(tp=len(hit), fp=len(extra), fn=len(wanted - hit))
            misses += [{"record_id": record_id, "shape": record["shape"], "field": field, "kind": "missed", "roles": list(w[0]), "value": w[1]} for w in wanted - hit]
            misses += [{"record_id": record_id, "shape": record["shape"], "field": field, "kind": "extra", "roles": [p[0]], "value": p[1]} for p in extra]

        for field in build.render.TAG_FIELDS:
            if field in gold["unscored"]:
                continue
            ignored = {item.partition(":")[2] for item in gold["unscored"] if item.startswith(field + ":")}
            wanted = set(gold["tags"][field])
            predicted = {final["value"] for final in finals.get(field, [])} - (ignored - wanted)
            tallies[field].add(tp=len(wanted & predicted), fp=len(predicted - wanted), fn=len(wanted - predicted))
            misses += [{"record_id": record_id, "shape": record["shape"], "field": field, "kind": "missed", "value": label} for label in wanted - predicted]
            misses += [{"record_id": record_id, "shape": record["shape"], "field": field, "kind": "extra", "value": label} for label in predicted - wanted]

        parties = [final for final in finals.get("party", []) if final["role"] == "defendant"]
        who = _who(text, parties, gold["names"])
        who_by_record[record_id] = who
        found = {key for key in who.values() if key}
        tallies["party"].add(tp=len(found), fp=sum(1 for key in who.values() if key is None), fn=len(set(gold["defendants"]) - found))
        misses += [{"record_id": record_id, "shape": record["shape"], "field": "party", "kind": "missed", "value": key} for key in set(gold["defendants"]) - found]
        misses += [{"record_id": record_id, "shape": record["shape"], "field": "party", "kind": "extra", "value": person} for person, key in who.items() if key is None]

        # Attribution, over personal values the engine extracted correctly.
        rows = db.execute("SELECT field, role, value, people, basis FROM attributions WHERE record_id = ?", (record_id,)).fetchall()
        given: dict[tuple[str, str, Any], list[tuple[frozenset, str]]] = defaultdict(list)
        extras_of = {(field, final["role"], str(final["value"])): final["extras"] for field in ("sentence", "money") for final in finals.get(field, [])}
        for row in rows:
            if row["field"] not in ("sentence", "money"):
                continue
            raw = row["value"] if row["field"] == "sentence" else json.loads(row["value"])
            value = _norm(row["field"], raw, extras_of.get((row["field"], row["role"], str(raw))))
            people = frozenset(who.get(person) for person in json.loads(row["people"]))
            given[(row["field"], row["role"], value)].append((people, row["basis"]))
        seen = set()
        for item in gold["values"]:
            if "persons" not in item or item["field"] not in ("sentence", "money"):
                continue
            value = _norm(item["field"], item["value"])
            mark = (item["field"], tuple(item["roles"]), value, tuple(item["persons"]))
            predicted_roles = {final["role"] for final in finals.get(item["field"], []) if _norm(item["field"], final["value"], final["extras"]) == value}
            role = next((r for r in item["roles"] if r in predicted_roles), None)
            if mark in seen or role is None:
                continue
            seen.add(mark)
            candidates = given.get((item["field"], role, value), [])
            want = frozenset(item["persons"])
            several = len(gold["defendants"]) > 1
            if not candidates:
                outcome = "none"
            else:
                outcome = "right" if any(people == want for people, _ in candidates) else "wrong"
                basis = candidates[0][1]
                attribution["by_basis"][basis][0 if outcome == "right" else 1] += 1
            attribution[outcome] += 1
            if several:
                attribution["several_defendants"][outcome] += 1
            if outcome != "right":
                misses.append({"record_id": record_id, "shape": record["shape"], "field": "attribution", "kind": outcome,
                               "value": value, "roles": [role], "want": sorted(want)})

    # Case linking and person linking.
    case_of = {row["record_id"]: row["case_id"] for row in db.execute("SELECT record_id, case_id FROM cases")}
    gold_case_of = {record["record_id"]: record["case_id"] for record in records}
    ids = sorted(gold_case_of)
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            same_gold, same_found = gold_case_of[left] == gold_case_of[right], case_of.get(left) == case_of.get(right)
            tallies["case_link"].add(tp=int(same_gold and same_found), fp=int(same_found and not same_gold), fn=int(same_gold and not same_found))
    person_of = {(row["record_id"], row["record_person"]): (row["case_id"], row["person"]) for row in db.execute("SELECT * FROM people")}
    nodes = [(record_id, person, key) for record_id, who in who_by_record.items() for person, key in who.items() if key]
    for i, (rec_a, per_a, key_a) in enumerate(nodes):
        for rec_b, per_b, key_b in nodes[i + 1:]:
            if rec_a == rec_b or gold_case_of[rec_a] != gold_case_of[rec_b]:
                continue
            same_gold = key_a == key_b
            same_found = person_of.get((rec_a, per_a)) == person_of.get((rec_b, per_b)) and (rec_a, per_a) in person_of
            tallies["person_link"].add(tp=int(same_gold and same_found), fp=int(same_found and not same_gold), fn=int(same_gold and not same_found))

    # Events and traces, per gold case.
    trace = {"exact": 0, "total": 0}
    records_of: dict[str, list[str]] = defaultdict(list)
    for record in records:
        records_of[record["case_id"]].append(record["record_id"])
    for gold_case in gold_cases:
        members = records_of.get(gold_case["case_id"], [])
        if not members:
            continue
        wanted = _gold_events([event for record_id in members for event in truth[record_id]["events"]])
        key_of: dict[tuple[str, str], str] = {}
        for record_id in members:
            for person, key in who_by_record[record_id].items():
                if key and (record_id, person) in person_of:
                    key_of[person_of[(record_id, person)]] = key
        found: set[tuple[str, str | None, str]] = set()
        for found_case in sorted({case_of[m] for m in members if m in case_of}):
            for event in events_layer.timeline(db, found_case):
                keys = [key_of.get((found_case, person)) for person in event["people"]] or [None]
                found |= {(event["type"], event["date"], key) for key in keys}
        for name, simplify in (("event", lambda t: t), ("event_coarse", lambda t: COARSE.get(t, t))):
            want = {(simplify(t), d, k) for t, d, k in wanted}
            have = {(simplify(t), d, k) for t, d, k in found if k is not None}
            loose = name == "event_coarse"
            hit = {w for w in want if any(_same_event(w, h, loose) for h in have)}
            extra = {h for h in have if not any(_same_event(w, h, loose) for w in want)}
            unplaced = sum(1 for t, d, k in found if k is None)
            tallies[name].add(tp=len(hit), fp=len(extra) + (unplaced if name == "event" else 0), fn=len(want - hit))
            if name == "event":
                misses += [{"record_id": members[0], "shape": "case", "field": "event", "kind": "missed", "value": list(w)} for w in want - hit]
                misses += [{"record_id": members[0], "shape": "case", "field": "event", "kind": "extra", "value": list(h)} for h in extra]
        for key in sorted({k for _, _, k in wanted}):
            want_seq = _sequence({(t, d) for t, d, k in wanted if k == key})
            have_seq = _sequence({(t, d) for t, d, k in found if k == key})
            trace["total"] += 1
            trace["exact"] += int(want_seq == have_seq)

    process = _process(db, records, truth, gold_cases, case_of, who_by_record, person_of, tallies)
    attribution["by_basis"] = {basis: {"right": pair[0], "wrong": pair[1]} for basis, pair in attribution["by_basis"].items()}
    placed = attribution["right"] + attribution["wrong"]
    attribution["accuracy_when_placed"] = round(attribution["right"] / placed, 3) if placed else None
    attribution["coverage"] = round(placed / (placed + attribution["none"]), 3) if placed + attribution["none"] else None
    return {
        "records": len(records), "cases": len({r["case_id"] for r in records}),
        "fields": {name: tally.report() for name, tally in sorted(tallies.items())},
        "values_by_shape": {name: tally.report() for name, tally in sorted(by_shape.items())},
        "attribution": attribution,
        "traces": {**trace, "exact_rate": round(trace["exact"] / trace["total"], 3) if trace["total"] else None},
        "process": process,
        "misses": misses,
    }


def _process(db, records, truth, gold_cases, case_of, who_by_record, person_of, tallies) -> dict[str, Any]:
    """Process mining on what the engine extracted against process mining on the truth.

    Departures: the order check is run on the true events of each defendant and
    on the extracted ones, and the (case, defendant, kind of departure) triples
    are compared. Models: a tree is mined from the true traces and another from
    the extracted traces, and each log is replayed on the other's tree."""
    from process_mining import conform, discover, log as log_layer, views

    records_of: dict[str, list[str]] = defaultdict(list)
    for record in records:
        records_of[record["case_id"]].append(record["record_id"])
    found_traces = {(t.case_id, t.person): t for t in log_layer.build(db)}
    true_log: list[tuple[str, ...]] = []
    found_log: list[tuple[str, ...]] = []
    planted = {"stated": 0, "flagged": 0}
    for gold_case in gold_cases:
        members = records_of.get(gold_case["case_id"], [])
        if not members:
            continue
        wanted = _gold_events([event for record_id in members for event in truth[record_id]["events"]])
        key_of = {person_of[(r, p)]: key for r in members for p, key in who_by_record[r].items() if key and (r, p) in person_of}
        case_flagged = False
        for key in sorted({k for _, _, k in wanted}):
            ordered = events_layer.order([{"type": t, "date": d, "people": []} for t, d, k in sorted(wanted, key=lambda e: (e[1] or "", e[0])) if k == key])
            true_trace = log_layer.Trace(gold_case["case_id"], key, [
                {"type": e["type"], "date": e["date"], "precision": events_layer._precision(e["date"]), "order_basis": e["order_basis"]} for e in ordered])
            true_log.append(tuple(a for a in true_trace.activities() if a in views.PROCEDURAL))
            want = {d["kind"] for d in conform.check_order(true_trace)}
            mine = next((t for (case_id, person), t in found_traces.items() if key_of.get((case_id, person)) == key), None)
            have = {d["kind"] for d in conform.check_order(mine)} if mine else set()
            if mine:
                found_log.append(tuple(a for a in mine.activities() if a in views.PROCEDURAL))
            tallies["departure"].add(tp=len(want & have), fp=len(have - want), fn=len(want - have))
            case_flagged = case_flagged or bool(want)
        if gold_case["planted"]:
            planted["stated"] += int(case_flagged)
            planted["flagged"] += int(any(
                conform.check_order(t) for (case_id, _), t in found_traces.items() if case_id in {case_of.get(m) for m in members}))
    true_counts, found_counts = discover.variants(true_log), discover.variants(found_log)
    out: dict[str, Any] = {"planted_cases_whose_records_state_the_departure": planted["stated"], "of_those_flagged_from_extraction": planted["flagged"]}
    for noise in (0.0, 0.2):
        true_tree, found_tree = discover.mine(true_counts, noise), discover.mine(found_counts, noise)
        try:
            out[f"noise_{noise}"] = {
                "same_model": true_tree == found_tree,
                "true_log_on_extracted_model": conform.fitness(true_counts, found_tree)["fitness"],
                "extracted_log_on_true_model": conform.fitness(found_counts, true_tree)["fitness"],
                "extracted_log_on_extracted_model": conform.fitness(found_counts, found_tree)["fitness"],
            }
        except discover.TooLarge:
            out[f"noise_{noise}"] = {"same_model": true_tree == found_tree, "note": "model allows too many paths to replay"}
    out["distinct_paths"] = {"true": len(true_counts), "extracted": len(found_counts), "shared": len(set(true_counts) & set(found_counts))}
    return out


def _gold_events(events: list[dict[str, Any]]) -> set[tuple[str, str | None, str]]:
    """Truth events of a case as (kind, date, person), keeping the most exact date of each."""
    best: dict[tuple[str, str], list[str | None]] = defaultdict(list)
    for event in events:
        for person in event["persons"]:
            dates = best[(event["type"], person)]
            stamp = event["date"]
            if stamp is None:
                if not dates:
                    dates.append(None)
                continue
            if None in dates:
                dates.remove(None)
            for index, known in enumerate(dates):
                if known.startswith(stamp):
                    break
                if stamp.startswith(known):
                    dates[index] = stamp
                    break
            else:
                dates.append(stamp)
    out = set()
    for (kind, person), dates in best.items():
        if kind == "offense":
            dates = [min(dates, key=lambda d: (d or "9999") if len(d or "") == 10 else (d or "9999") + "-01")]
        out |= {(kind, stamp, person) for stamp in dates}
    return out


def _same_event(want: tuple[str, str | None, str], have: tuple[str, str | None, str], loose: bool) -> bool:
    if want[0] != have[0] or want[2] != have[2]:
        return False
    if want[1] == have[1]:
        return True
    return loose and want[1] is not None and have[1] is not None and (want[1].startswith(have[1]) or have[1].startswith(want[1]))


def _sequence(events: set[tuple[str, str | None]]) -> list[str]:
    ordered = events_layer.order([{"type": kind, "date": stamp, "people": []} for kind, stamp in sorted(events, key=lambda e: (e[1] or "", e[0]))])
    return [COARSE.get(event["type"], event["type"]) for event in ordered]


def evaluate(split: str | None, name: str) -> dict[str, Any]:
    records, truth, gold_cases = build.load(split)
    db = run(records, name)
    report = score(db, records, truth, gold_cases)
    report["split"] = split or "all"
    report["readers"] = reader_versions()
    report["syntax"] = os.environ.get("CASENOESIS_SYNTAX", "") == "1"
    return report
