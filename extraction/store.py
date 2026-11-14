"""The assertion store: SQLite, local only, under `data/extracted/`.

    runs          one row per extraction run: readers, versions, SDK commit
    records       one row per record: text hash, the run that last read it
    assertions    every reader's claim, append-only, with its span and gate result
    resolutions   one decision per record and field, per rule set
    finals        resolved values, flattened for cohort queries
    review_queue  mentions the vote left open
    cases         records grouped into cases, with the basis for each link
    people        each defendant of a case, and which numbered person that is in each record
    attributions  whose each term, amount, and event is, per record
    events        what happened in each case, in order, with the records that say so

Assertions are never updated. A record read again gets new assertion rows
under a new run, and `records.run_id` moves to that run. Resolution reads the
current run's rows and can be redone at any time without reading a record.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTRACTED = REPO_ROOT / "data" / "extracted"
DB_PATH = EXTRACTED / "noesis.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    rule_set_version TEXT NOT NULL,
    readers TEXT NOT NULL,
    sdk_commit TEXT,
    code_revision TEXT,
    llm INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS records (
    record_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    domain TEXT NOT NULL,
    domains TEXT,
    text_sha256 TEXT NOT NULL,
    text_source TEXT NOT NULL,
    chars INTEGER NOT NULL,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    extracted_at TEXT NOT NULL,
    assertions INTEGER NOT NULL,
    span_failures INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS assertions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value TEXT,
    role TEXT NOT NULL,
    method TEXT NOT NULL,
    method_version TEXT NOT NULL,
    family TEXT NOT NULL,
    confidence REAL NOT NULL,
    span_start INTEGER,
    span_end INTEGER,
    span_text TEXT,
    span_ok INTEGER NOT NULL,
    extras TEXT
);
CREATE INDEX IF NOT EXISTS assertions_record ON assertions(record_id, run_id);
CREATE TABLE IF NOT EXISTS resolutions (
    record_id TEXT NOT NULL,
    field TEXT NOT NULL,
    rule_set_version TEXT NOT NULL,
    status TEXT NOT NULL,
    body TEXT NOT NULL,
    resolved_at TEXT NOT NULL,
    PRIMARY KEY (record_id, field, rule_set_version)
);
CREATE TABLE IF NOT EXISTS finals (
    record_id TEXT NOT NULL,
    field TEXT NOT NULL,
    role TEXT NOT NULL,
    value TEXT,
    value_number REAL,
    status TEXT NOT NULL,
    families TEXT NOT NULL,
    spans TEXT NOT NULL,
    extras TEXT
);
CREATE INDEX IF NOT EXISTS finals_record ON finals(record_id);
CREATE INDEX IF NOT EXISTS finals_lookup ON finals(field, role, value);
CREATE TABLE IF NOT EXISTS review_queue (
    record_id TEXT NOT NULL,
    field TEXT NOT NULL,
    state TEXT NOT NULL,
    value TEXT,
    span_start INTEGER,
    span_end INTEGER,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS review_record ON review_queue(record_id);
CREATE INDEX IF NOT EXISTS review_field ON review_queue(field, state);
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    basis TEXT NOT NULL,
    PRIMARY KEY (case_id, record_id)
);
CREATE INDEX IF NOT EXISTS cases_record ON cases(record_id);
CREATE TABLE IF NOT EXISTS graphs (
    record_id TEXT PRIMARY KEY,
    graph_sha256 TEXT NOT NULL,
    nodes INTEGER NOT NULL,
    name_check TEXT NOT NULL,
    conforms INTEGER,
    built_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
    case_id TEXT NOT NULL,
    person TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_person TEXT NOT NULL,
    basis TEXT NOT NULL,
    PRIMARY KEY (record_id, record_person)
);
CREATE INDEX IF NOT EXISTS people_case ON people(case_id, person);
CREATE TABLE IF NOT EXISTS attributions (
    record_id TEXT NOT NULL,
    field TEXT NOT NULL,
    role TEXT NOT NULL,
    value TEXT,
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    people TEXT NOT NULL,
    status TEXT NOT NULL,
    basis TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attributions_record ON attributions(record_id);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    type TEXT NOT NULL,
    date TEXT,
    precision TEXT NOT NULL,
    people TEXT NOT NULL,
    status TEXT NOT NULL,
    order_basis TEXT NOT NULL,
    evidence TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_case ON events(case_id, position);
CREATE TABLE IF NOT EXISTS case_candidates (
    record_a TEXT NOT NULL,
    record_b TEXT NOT NULL,
    basis TEXT NOT NULL,
    PRIMARY KEY (record_a, record_b)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(SCHEMA)
    return db


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def begin_run(db: sqlite3.Connection, *, engine_version: str, rule_set_version: str, readers: dict[str, str],
              sdk_commit: str | None, code_revision: str | None, llm: bool) -> int:
    cursor = db.execute(
        "INSERT INTO runs (started_at, engine_version, rule_set_version, readers, sdk_commit, code_revision, llm) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now(), engine_version, rule_set_version, _dump(readers), sdk_commit, code_revision, int(llm)),
    )
    db.commit()
    return int(cursor.lastrowid)


def save_record(db: sqlite3.Connection, run_id: int, record: dict[str, Any], assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert one record's gated assertions under `run_id`. Returns them with ids."""
    stored = []
    for item in assertions:
        cursor = db.execute(
            "INSERT INTO assertions (record_id, run_id, field, value, role, method, method_version, family, "
            "confidence, span_start, span_end, span_text, span_ok, extras) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record["record_id"], run_id, item["field"], _dump(item.get("value")), item["role"], item["method"],
                item["method_version"], item["family"], float(item["confidence"]), item.get("span_start"),
                item.get("span_end"), item.get("span_text"), int(item["span_ok"]), _dump(item.get("extras") or {}),
            ),
        )
        stored.append({**item, "id": int(cursor.lastrowid)})
    db.execute(
        "INSERT OR REPLACE INTO records (record_id, kind, domain, domains, text_sha256, text_source, chars, run_id, "
        "extracted_at, assertions, span_failures) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["record_id"], record["kind"], record["domain"], _dump(record.get("domains") or [record["domain"]]),
            record["text_sha256"], record["text_source"], record["chars"], run_id, now(), len(stored),
            sum(1 for item in stored if not item["span_ok"] and item["family"] not in ("metadata",)),
        ),
    )
    return stored


def save_resolutions(db: sqlite3.Connection, record_id: str, resolutions: dict[str, dict[str, Any]]) -> None:
    """Replace one record's decisions, finals, and review rows."""
    db.execute("DELETE FROM finals WHERE record_id = ?", (record_id,))
    db.execute("DELETE FROM review_queue WHERE record_id = ?", (record_id,))
    stamp = now()
    for name, resolution in resolutions.items():
        db.execute(
            "INSERT OR REPLACE INTO resolutions (record_id, field, rule_set_version, status, body, resolved_at) "
            "VALUES (?,?,?,?,?,?)",
            (record_id, name, resolution["rule_set_version"], resolution["status"], _dump(resolution), stamp),
        )
        for final in resolution["finals"]:
            value = final["value"]
            db.execute(
                "INSERT INTO finals (record_id, field, role, value, value_number, status, families, spans, extras) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    record_id, name, final["role"], value if isinstance(value, str) else _dump(value),
                    float(value) if isinstance(value, (int, float)) else final["extras"].get("months"),
                    final["status"], ",".join(final["families"]), _dump(final["spans"]), _dump(final["extras"]),
                ),
            )
        for entry in resolution["review"]:
            span = entry["spans"][0] if entry["spans"] else [None, None]
            db.execute(
                "INSERT INTO review_queue (record_id, field, state, value, span_start, span_end, detail) VALUES (?,?,?,?,?,?,?)",
                (record_id, name, entry["state"], _dump(entry["value"]), span[0], span[1], _dump(entry)),
            )


def current_assertions(db: sqlite3.Connection, record_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT a.* FROM assertions a JOIN records r ON r.record_id = a.record_id AND r.run_id = a.run_id "
        "WHERE a.record_id = ? ORDER BY a.id",
        (record_id,),
    ).fetchall()
    return [_assertion(row) for row in rows]


def _assertion(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["value"] = json.loads(item["value"]) if item["value"] is not None else None
    item["extras"] = json.loads(item["extras"] or "{}")
    return item


def record_ids(db: sqlite3.Connection, *, kind: str | None = None, domain: str | None = None) -> list[str]:
    query, args = "SELECT record_id FROM records WHERE 1=1", []
    if kind:
        query, args = query + " AND kind = ?", [*args, kind]
    if domain:
        query, args = query + " AND domains LIKE ?", [*args, f'%"{domain}"%']
    return [row[0] for row in db.execute(query + " ORDER BY record_id", args)]


def known_text_hashes(db: sqlite3.Connection) -> dict[str, str]:
    return {row[0]: row[1] for row in db.execute("SELECT record_id, text_sha256 FROM records")}


def prune(db: sqlite3.Connection) -> int:
    """Drop assertion rows from runs a record has since been read again under."""
    cursor = db.execute(
        "DELETE FROM assertions WHERE NOT EXISTS (SELECT 1 FROM records r WHERE r.record_id = assertions.record_id "
        "AND r.run_id = assertions.run_id)"
    )
    db.commit()
    return cursor.rowcount


def rows(db: sqlite3.Connection, query: str, args: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(query, tuple(args))]
