"""Read-only views over the store, for the command line and the MCP server.

Every function answers from stored assertions, decisions, and graphs. None
reads a model and none writes. Any passage of record text a view returns has
names masked first.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from encoding import corpus
from extraction import fields, names as name_rules, pipeline, resolve, spans as sp, store

MAX_ROWS = 200


def _db() -> sqlite3.Connection:
    return store.connect()


def status() -> dict[str, Any]:
    """Counts: records read, assertions by family, decisions by field, the review queue, cases, graphs."""
    db = _db()
    q = lambda query, *args: store.rows(db, query, args)  # noqa: E731
    indexed: dict[str, int] = {}
    for entry in corpus.load_index():
        indexed[entry["kind"]] = indexed.get(entry["kind"], 0) + 1
    by_field: dict[str, dict[str, int]] = {}
    for row in q("SELECT field, status, COUNT(*) n FROM resolutions WHERE rule_set_version = ? GROUP BY field, status",
                 resolve.RULE_SET_VERSION):
        by_field.setdefault(row["field"], {})[row["status"]] = row["n"]
    finals: dict[str, dict[str, int]] = {}
    for row in q("SELECT field, status, COUNT(*) n FROM finals GROUP BY field, status"):
        finals.setdefault(row["field"], {})[row["status"]] = row["n"]
    review: dict[str, dict[str, int]] = {}
    for row in q("SELECT field, state, COUNT(*) n FROM review_queue GROUP BY field, state"):
        review.setdefault(row["field"], {})[row["state"]] = row["n"]
    families = {
        row["family"]: {"assertions": row["n"], "span_ok": row["ok"]}
        for row in q(
            "SELECT a.family, COUNT(*) n, SUM(a.span_ok) ok FROM assertions a JOIN records r "
            "ON r.record_id = a.record_id AND r.run_id = a.run_id GROUP BY a.family"
        )
    }
    cases = q("SELECT COUNT(DISTINCT case_id) cases, COUNT(*) records FROM cases")[0]
    multi = q("SELECT COUNT(*) n FROM (SELECT case_id FROM cases GROUP BY case_id HAVING COUNT(*) > 1)")[0]["n"]
    graphs = q("SELECT COUNT(*) built, SUM(conforms) conforming, SUM(conforms IS NOT NULL) gated, "
               "SUM(name_check = 'pass') name_check_pass FROM graphs")[0]
    last_run = q("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1")
    return {
        "rule_set_version": resolve.RULE_SET_VERSION,
        "indexed": indexed,
        "read": {row["kind"]: row["n"] for row in q("SELECT kind, COUNT(*) n FROM records GROUP BY kind")},
        "text_source": {row["text_source"]: row["n"] for row in q("SELECT text_source, COUNT(*) n FROM records GROUP BY text_source")},
        "families": families,
        "decisions": by_field,
        "finals": finals,
        "review_queue": review,
        "cases": {**cases, "with_more_than_one_record": multi,
                  "candidate_links": q("SELECT COUNT(*) n FROM case_candidates")[0]["n"]},
        "people": q("SELECT COUNT(*) n FROM (SELECT DISTINCT case_id, person FROM people)")[0]["n"],
        "attributions": {row["basis"]: row["n"] for row in q("SELECT basis, COUNT(*) n FROM attributions GROUP BY basis")},
        "events": {
            "total": q("SELECT COUNT(*) n FROM events")[0]["n"],
            "with_a_date": q("SELECT COUNT(*) n FROM events WHERE date IS NOT NULL")[0]["n"],
            "by_kind": {row["type"]: row["n"] for row in q("SELECT type, COUNT(*) n FROM events GROUP BY type ORDER BY n DESC")},
        },
        "graphs": graphs,
        "last_run": ({**last_run[0], "readers": json.loads(last_run[0]["readers"])} if last_run else None),
    }


_INDEX: dict[str, dict[str, Any]] = {}


def _entry(record_id: str) -> dict[str, Any] | None:
    if not _INDEX:
        _INDEX.update({entry["record_id"]: entry for entry in corpus.load_index()})
    return _INDEX.get(record_id)


def _windows(record_id: str, spans: list[tuple[int, int]]) -> dict[tuple[int, int], str]:
    """The sentence around each span, names masked. Empty when the text is not on disk."""
    entry = _entry(record_id)
    loaded = pipeline.load_doc(entry) if entry else None
    if loaded is None:
        return {}
    text = loaded[0].text
    pattern = name_rules.masker(text)
    out = {}
    for start, end in spans:
        s, e = sp.sentence_at(text, start, end)
        s, e = max(s, start - 300), min(e, end + 300)
        out[(start, end)] = name_rules.scrub(text[s:start] + "⟦" + text[start:end] + "⟧" + text[end:e], pattern).strip()
    return out


def record(record_id: str, *, windows: bool = True) -> dict[str, Any]:
    """One record: what was settled, by which families, and what is open."""
    db = _db()
    row = db.execute("SELECT * FROM records WHERE record_id = ?", (record_id,)).fetchone()
    if row is None:
        return {"error": f"{record_id} has not been read"}
    decisions = {
        r["field"]: json.loads(r["body"])
        for r in db.execute(
            "SELECT field, body FROM resolutions WHERE record_id = ? AND rule_set_version = ?",
            (record_id, resolve.RULE_SET_VERSION),
        )
    }
    spans = [tuple(entry["spans"][0]) for d in decisions.values() for entry in d["review"] if entry["spans"]]
    shown = _windows(record_id, spans) if windows and spans else {}
    out_fields = {}
    for name, decision in decisions.items():
        review = [
            {**entry, "window": shown.get(tuple(entry["spans"][0]))} if entry["spans"] else entry
            for entry in decision["review"]
        ]
        out_fields[name] = {
            "status": decision["status"],
            "finals": [
                {k: final[k] for k in ("value", "role", "status", "families", "spans")} | {"extras": final["extras"]}
                for final in decision["finals"]
            ],
            "review": review,
            "unassigned": decision["unassigned"],
        }
    case = db.execute("SELECT case_id, basis FROM cases WHERE record_id = ?", (record_id,)).fetchone()
    graph = db.execute("SELECT nodes, name_check, conforms FROM graphs WHERE record_id = ?", (record_id,)).fetchone()
    return {
        "record_id": record_id, "kind": row["kind"], "domains": json.loads(row["domains"]),
        "text_source": row["text_source"], "chars": row["chars"], "assertions": row["assertions"],
        "case": dict(case) if case else None, "graph": dict(graph) if graph else None, "fields": out_fields,
    }


def review_queue(field: str = "", state: str = "", kind: str = "", limit: int = 25, windows: bool = True) -> dict[str, Any]:
    """Open mentions, with the sentence around each (names masked)."""
    db = _db()
    query = "SELECT q.* FROM review_queue q JOIN records r ON r.record_id = q.record_id WHERE 1=1"
    args: list[Any] = []
    for column, value in (("q.field", field), ("q.state", state), ("r.kind", kind)):
        if value:
            query, args = f"{query} AND {column} = ?", [*args, value]
    total = db.execute(query.replace("q.*", "COUNT(*)"), args).fetchone()[0]
    rows = store.rows(db, query + " ORDER BY q.record_id, q.span_start LIMIT ?", [*args, max(1, min(limit, MAX_ROWS))])
    items = []
    for row in rows:
        detail = json.loads(row["detail"])
        item = {"record_id": row["record_id"], "field": row["field"], **detail}
        if windows and row["span_start"] is not None:
            item["window"] = _windows(row["record_id"], [(row["span_start"], row["span_end"])]).get(
                (row["span_start"], row["span_end"]))
        items.append(item)
    return {"total": total, "shown": len(items), "items": items}


def search(field: str, value: str = "", role: str = "", kind: str = "", domain: str = "", status: str = "",
           minimum: float | None = None, maximum: float | None = None, limit: int = 50) -> dict[str, Any]:
    """Records with a settled value: a cohort by field, role, label, or numeric range."""
    if fields.get(field) is None:
        return {"error": f"unknown field {field!r}", "fields": [spec.name for spec in fields.all_fields()]}
    db = _db()
    query = "SELECT f.record_id, f.role, f.value, f.value_number, f.status, f.families FROM finals f JOIN records r ON r.record_id = f.record_id WHERE f.field = ?"
    args: list[Any] = [field]
    for column, item in (("f.value", value), ("f.role", role), ("r.kind", kind), ("f.status", status)):
        if item:
            query, args = f"{query} AND {column} = ?", [*args, item]
    if domain:
        query, args = query + " AND r.domains LIKE ?", [*args, f'%"{domain}"%']
    if minimum is not None:
        query, args = query + " AND f.value_number >= ?", [*args, minimum]
    if maximum is not None:
        query, args = query + " AND f.value_number <= ?", [*args, maximum]
    total = db.execute(f"SELECT COUNT(DISTINCT record_id) FROM ({query})", args).fetchone()[0]
    rows = store.rows(db, query + " ORDER BY f.record_id LIMIT ?", [*args, max(1, min(limit, MAX_ROWS))])
    return {"records": total, "shown": len(rows), "rows": rows}


def distribution(field: str, kind: str = "", domain: str = "", by: str = "value", limit: int = 40) -> dict[str, Any]:
    """How often each settled label or role occurs, counted in records."""
    if fields.get(field) is None:
        return {"error": f"unknown field {field!r}", "fields": [spec.name for spec in fields.all_fields()]}
    column = "f.role" if by == "role" else "f.value"
    db = _db()
    query = f"SELECT {column} AS label, COUNT(DISTINCT f.record_id) AS records FROM finals f JOIN records r ON r.record_id = f.record_id WHERE f.field = ?"
    args: list[Any] = [field]
    if kind:
        query, args = query + " AND r.kind = ?", [*args, kind]
    if domain:
        query, args = query + " AND r.domains LIKE ?", [*args, f'%"{domain}"%']
    rows = store.rows(db, query + f" GROUP BY {column} ORDER BY records DESC LIMIT ?", [*args, max(1, min(limit, MAX_ROWS))])
    return {"field": field, "by": by, "rows": rows}


def case(case_or_record_id: str) -> dict[str, Any]:
    """A case: its records, the basis for each link, and what each record settled."""
    db = _db()
    case_id = case_or_record_id
    if not case_id.startswith("case-"):
        row = db.execute("SELECT case_id FROM cases WHERE record_id = ?", (case_or_record_id,)).fetchone()
        if row is None:
            return {"error": f"{case_or_record_id} is in no case. Run: python -m extraction cases"}
        case_id = row["case_id"]
    members = store.rows(db, "SELECT c.record_id, c.basis, r.kind, r.domains FROM cases c JOIN records r ON r.record_id = c.record_id WHERE c.case_id = ?", [case_id])
    if not members:
        return {"error": f"no case {case_id}"}
    for member in members:
        member["domains"] = json.loads(member["domains"])
        member["finals"] = store.rows(
            db, "SELECT field, role, value, status FROM finals WHERE record_id = ? ORDER BY field, role", [member["record_id"]]
        )
    ids = [member["record_id"] for member in members]
    marks = ",".join("?" * len(ids))
    candidates = store.rows(db, f"SELECT * FROM case_candidates WHERE record_a IN ({marks}) OR record_b IN ({marks})", ids + ids)
    return {"case_id": case_id, "records": members, "candidate_links": candidates}


def timeline(case_or_record_id: str) -> dict[str, Any]:
    """One case's events in order: what happened, when, to which defendant,
    which records say so, and whether each date was stated, read from "today",
    or taken from a filing date. Defendants are `p1`, `p2`; no names."""
    from extraction import events as events_layer

    db = _db()
    row = db.execute("SELECT case_id FROM cases WHERE case_id = ? OR record_id = ? LIMIT 1", (case_or_record_id, case_or_record_id)).fetchone()
    if row is None:
        return {"error": f"{case_or_record_id} is in no case. Run: python -m extraction cases"}
    case_id = row["case_id"]
    people = store.rows(db, "SELECT person, record_id, record_person, basis FROM people WHERE case_id = ? ORDER BY person, record_id", [case_id])
    owned = store.rows(
        db,
        "SELECT a.record_id, a.field, a.role, a.value, a.people, a.status, a.basis FROM attributions a JOIN cases c ON c.record_id = a.record_id "
        "WHERE c.case_id = ? AND a.field IN ('sentence', 'money') ORDER BY a.record_id, a.span_start", [case_id],
    )
    for item in owned:
        item["people"] = json.loads(item["people"])
    return {
        "case_id": case_id,
        "records": [r["record_id"] for r in store.rows(db, "SELECT record_id FROM cases WHERE case_id = ? ORDER BY record_id", [case_id])],
        "defendants": people,
        "events": events_layer.timeline(db, case_id),
        "terms_and_amounts": owned,
    }


def agreement() -> dict[str, Any]:
    """How the readers compare, with no labels needed: per field, how many
    mentions two families settled together, how many one family settled, and
    how many they contested. Not an accuracy figure."""
    db = _db()
    out: dict[str, dict[str, int]] = {}
    for row in store.rows(db, "SELECT field, status, COUNT(*) n FROM finals GROUP BY field, status"):
        out.setdefault(row["field"], {})[row["status"]] = row["n"]
    for row in store.rows(db, "SELECT field, state, COUNT(*) n FROM review_queue GROUP BY field, state"):
        out.setdefault(row["field"], {})[row["state"]] = row["n"]
    for name, counts in out.items():
        settled = counts.get("agreed", 0) + counts.get("resolved", 0) + counts.get("human", 0)
        total = settled + sum(counts.get(state, 0) for state in ("contested", "weak", "self_contradiction"))
        counts["settled_share"] = round(settled / total, 3) if total else 0.0
    return out
