"""One record through the engine: text, readers, gate, vote.

`read_record` is a pure function of the record and the code: no database, no
network. A worker process runs it and hands the result back; the parent
writes. That keeps a batch restartable and the store single-writer.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from encoding import corpus
from extraction import ENGINE_VERSION, fields, names as name_rules, resolve, store
from extraction.readers import Doc, llm, reader_versions, readers_for

ENCODED_RECORDS = corpus.ENCODED / "records"
SECTION_JOIN = "\n\n"


def _sdk_text_and_anchors(record_id: str) -> tuple[str, list[dict[str, Any]]] | None:
    """The text the SDK processor read, and its anchors as offsets into it."""
    folder = ENCODED_RECORDS / record_id
    content_path = folder / "extracted-content.json"
    if not content_path.is_file():
        return None
    content = json.loads(content_path.read_text(encoding="utf-8")).get("content") or {}
    offsets: dict[str, int] = {}
    parts: list[str] = []
    cursor = 0
    for section in content.get("sections") or []:
        text = str(section.get("text") or "")
        offsets[str(section.get("section_id"))] = cursor
        parts.append(text)
        cursor += len(text) + len(SECTION_JOIN)
    text = SECTION_JOIN.join(parts)

    anchors: list[dict[str, Any]] = []
    annotations_path, graph_path = folder / "annotations.jsonld", folder / "graph.jsonld"
    if annotations_path.is_file() and graph_path.is_file():
        nodes = {node.get("@id"): node for node in json.loads(graph_path.read_text(encoding="utf-8")).get("@graph", [])}
        annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
        annotations = annotations if isinstance(annotations, list) else annotations.get("@graph") or annotations.get("items") or []
        for annotation in annotations:
            if not isinstance(annotation, dict) or annotation.get("type") != "Annotation":
                continue
            target = annotation.get("target") or {}
            base = offsets.get(str(target.get("source") or "").rpartition("#")[2])
            position = next((s for s in target.get("selector") or [] if s.get("type") == "TextPositionSelector"), None)
            node = nodes.get(annotation.get("body"))
            if base is None or position is None or node is None:
                continue
            name = node.get("uco-core:name")
            events = node.get("uco-core:eventType") or []
            anchors.append({
                "start": base + int(position["start"]),
                "end": base + int(position["end"]),
                "label": name if isinstance(name, str) else "",
                "class": node.get("@type") if isinstance(node.get("@type"), str) else (node.get("@type") or [None])[0],
                "event_types": events if isinstance(events, list) else [events],
            })
    return text, anchors


def load_doc(entry: dict[str, Any]) -> tuple[Doc, str] | None:
    """The record's text and where it came from: the SDK's extraction when the
    record was encoded, the collector's own row for a press record that was not."""
    loaded = _sdk_text_and_anchors(entry["record_id"])
    if loaded is not None:
        text, anchors = loaded
        source = "sdk_extracted_content"
    elif entry["kind"] == "press":
        row = corpus.press_row(entry)
        text, anchors, source = str(row.get("body") or ""), [], "collector_row"
    else:
        return None
    if not text.strip():
        return None
    return Doc(entry["record_id"], entry["kind"], entry["domain"], text, entry, anchors), source


def _number_people(text: str, gated: list[dict[str, Any]]) -> None:
    """Replace each party's name with a number, in place.

    People are numbered in order of first appearance. Two spans are one person
    when they share a surname and their given names do not conflict. After
    this, no assertion holds a name: the value is `person-N` and the stored
    span text is the mask. The character offsets still point at the name in
    the local source text.
    """
    people: list[tuple[str, str]] = []
    rows = sorted((a for a in gated if a["field"] == "party" and a["span_ok"]), key=lambda a: a["span_start"])
    for item in rows:
        surname, given = name_rules.person_key(text[item["span_start"]: item["span_end"]])
        for number, (known_surname, known_given) in enumerate(people, start=1):
            initial = min(len(given), len(known_given)) == 1 and given[:1] == known_given[:1]
            if surname == known_surname and (not given or not known_given or given == known_given or initial):
                break
        else:
            people.append((surname, given))
            number = len(people)
        item["value"] = f"person-{number}"
        item["span_text"] = name_rules.MASK

    def number_of(start: int, end: int) -> int | None:
        surname, given = name_rules.person_key(text[start:end])
        for number, (known_surname, known_given) in enumerate(people, start=1):
            initial = min(len(given), len(known_given)) == 1 and given[:1] == known_given[:1]
            if surname == known_surname and (not given or not known_given or given == known_given or initial):
                return number
        return None

    # An attribution points at person spans. Its role becomes the numbers of
    # those people; a span that is not one of the record's parties is dropped.
    for item in gated:
        if item["field"] != "attribution" or not item["span_ok"] or item.get("role") not in (None, "unknown"):
            continue
        numbers = sorted({n for n in (number_of(a, b) for a, b in item["extras"].get("people") or []) if n is not None})
        item["role"] = "+".join(f"person-{n}" for n in numbers) if numbers else "unknown"


def _mask_span_text(text: str, gated: list[dict[str, Any]]) -> None:
    """Remove names from the span text of every assertion, in place.

    A span is usually a number, a citation or a cue word. It can also be a
    whole sentence: the SDK anchors a charge on the sentence that states it,
    and that sentence names the people charged. The stored span text is for
    reading a decision back without the source; it must not carry a name. The
    offsets are unchanged and still point at the source text."""
    known = {text[a["span_start"]: a["span_end"]] for a in gated if a["field"] == "party" and a["span_ok"]}
    pattern = name_rules.mask_pattern(name_rules.find_names(text, known))
    if pattern is None:
        return
    for item in gated:
        if item["field"] != "party" and item.get("span_text"):
            item["span_text"] = name_rules.scrub(item["span_text"], pattern)


def read_doc(doc: Doc, *, use_llm: bool = False, llm_transport=None) -> dict[str, Any]:
    """Readers, gate, vote, over a `Doc` already in memory."""
    raw: list[dict[str, Any]] = []
    for reader in readers_for(doc.kind):
        raw.extend(reader.fn(doc))
    gated = [fields.gate_assertion(doc.text, item) for item in raw]
    _mask_span_text(doc.text, gated)
    _number_people(doc.text, gated)
    for index, item in enumerate(gated):
        item["seq"] = -(index + 1)
    resolutions = resolve.resolve_record(gated)
    if use_llm:
        open_mentions = [
            {"field": name, "span": entry["spans"][0]}
            for name, resolution in resolutions.items()
            for entry in resolution["review"] if entry["spans"]
        ]
        extra = [fields.gate_assertion(doc.text, item) for item in llm.ask(doc, open_mentions, llm_transport)]
        _mask_span_text(doc.text, extra)
        _number_people(doc.text, gated + extra)
        if extra:
            for index, item in enumerate(extra, start=len(gated)):
                item["seq"] = -(index + 1)
            gated += extra
            resolutions = resolve.resolve_record(gated)
    return {"assertions": gated, "resolutions": resolutions}


def read_record(entry: dict[str, Any], use_llm: bool = False) -> dict[str, Any]:
    """Everything the store needs for one indexed record, or a skip reason."""
    try:
        loaded = load_doc(entry)
        if loaded is None:
            return {"record_id": entry["record_id"], "skipped": "no_text"}
        doc, source = loaded
        result = read_doc(doc, use_llm=use_llm)
    except Exception as error:  # one bad record must not stop a batch
        return {"record_id": entry["record_id"], "skipped": f"{type(error).__name__}: {error}"}
    result["record"] = {
        "record_id": doc.record_id, "kind": doc.kind, "domain": doc.domain,
        "domains": entry.get("domains") or [doc.domain],
        "text_sha256": hashlib.sha256(doc.text.encode("utf-8")).hexdigest(),
        "text_source": source, "chars": len(doc.text),
    }
    return result


def _job(args: tuple[dict[str, Any], bool]) -> dict[str, Any]:
    return read_record(*args)


def _code_revision() -> str | None:
    done = subprocess.run(["git", "-C", str(corpus.REPO_ROOT), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True, check=False)
    return done.stdout.strip() or None


def run(entries: list[dict[str, Any]], *, workers: int = 1, force: bool = False, db_path: Path | None = None) -> dict[str, Any]:
    """Read many records and store the result. A record whose text has not
    changed since it was last read is skipped unless `force`."""
    from encoding import sdk

    use_llm = llm.enabled()
    db = store.connect(db_path)
    known = {} if force else store.known_text_hashes(db)
    pending = [entry for entry in entries if entry["record_id"] not in known] if not force else entries
    summary: dict[str, Any] = {"selected": len(entries), "already_read": len(entries) - len(pending), "read": 0, "skipped": {}}
    if not pending:
        return summary
    try:
        sdk_commit = sdk.pin_status()["commit"]
    except sdk.SdkUnavailable:
        sdk_commit = None
    run_id = store.begin_run(
        db, engine_version=ENGINE_VERSION, rule_set_version=resolve.RULE_SET_VERSION, readers=reader_versions(),
        sdk_commit=sdk_commit, code_revision=_code_revision(), llm=use_llm,
    )
    jobs = [(entry, use_llm) for entry in pending]

    def results():
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                yield from pool.map(_job, jobs, chunksize=32)
        else:
            yield from map(_job, jobs)

    for count, result in enumerate(results(), start=1):
        if "skipped" in result:
            summary["skipped"][result["skipped"]] = summary["skipped"].get(result["skipped"], 0) + 1
            continue
        stored = store.save_record(db, run_id, result["record"], result["assertions"])
        # Re-vote over stored rows so decisions carry real assertion ids.
        store.save_resolutions(db, result["record"]["record_id"], resolve.resolve_record(stored))
        summary["read"] += 1
        if count % 500 == 0:
            db.commit()
    db.commit()
    summary["run_id"] = run_id
    return summary


def reresolve(*, kind: str | None = None, db_path: Path | None = None) -> dict[str, Any]:
    """Vote again over stored assertions under the current rule set. Reads no record."""
    db = store.connect(db_path)
    ids = store.record_ids(db, kind=kind)
    for count, record_id in enumerate(ids, start=1):
        store.save_resolutions(db, record_id, resolve.resolve_record(store.current_assertions(db, record_id)))
        if count % 500 == 0:
            db.commit()
    db.commit()
    return {"records": len(ids), "rule_set_version": resolve.RULE_SET_VERSION}
