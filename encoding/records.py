"""The SDK's own document processor over collected records.

No extraction logic lives here. `process_document_file` from the pinned SDK
reads a press body or a court PDF and writes a CASE/UCO graph, the extracted
text, and Web Annotation anchors. This module feeds it, then adds what the
collector knows and the processor cannot see: the public URL the bytes came
from, following the SDK's public-record-capture recipe.

Output, per record, under `data/encoded/records/<record_id>/` (local only):

    graph.jsonld            SDK record graph plus the source URL
    extracted-content.json  the text the processor read (stays on this machine)
    annotations.jsonld      character anchors for every extracted entity
    record.json             status, hashes, entity counts, SDK commit
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from encoding import corpus, redact, sdk

RECORDS = corpus.ENCODED / "records"
RECORD_SCHEMA = "noesis-record/1"


def record_dir(record_id: str) -> Path:
    return RECORDS / record_id


def _processor():
    """The SDK document processor module, imported from the pinned checkout."""
    path = str(sdk.sdk_root() / "mcp_server")
    if path not in sys.path:
        sys.path.insert(0, path)
    import document_processor  # type: ignore[import-not-found]

    return document_processor


def _iri(*parts: str) -> str:
    from case_uco import deterministic_uuid

    return f"urn:uuid:{deterministic_uuid('casenoesis', *parts)}"


def _add_collection_provenance(graph_path: Path, entry: dict[str, Any]) -> None:
    """Attach the public address and the retrieval to the SDK's source node.

    A retrieval time is written only when the collector recorded one
    (reference records). A publication date is a date with no clock time, so
    it stays in a description (public-record-capture recipe).
    """
    from case_uco import CASEGraph

    graph = CASEGraph(kb_prefix="urn:uuid:")
    graph.load_file(str(graph_path))
    document = json.loads(graph_path.read_text(encoding="utf-8"))
    source_id = next(
        node["@id"]
        for node in document["@graph"]
        if any(str(tag).startswith("source-file-kind:") for tag in node.get("uco-core:tag") or [])
    )
    record_id = entry["record_id"]
    tags = [f"noesis-record:{record_id}", f"kind:{entry['kind']}", f"domain:{entry['domain']}"]
    tags += [
        f"{key}:{entry[key]}"
        for key in ("stage", "bucket", "slug", "version_pin")
        if entry.get(key)
    ]
    graph.add_property(source_id, "uco-core:tag", tags)

    url = entry.get("source_url")
    if url:
        published = entry.get("pub_date")
        retrieved = entry.get("retrieved_at")
        what = {"press": "Press release", "court": "Court filing"}.get(entry["kind"], "Reference record")
        note = f"{what} address the collector read."
        if published:
            note += f" Dated {published} by the source; a date with no time is not written as a timestamp."
        url_id = _iri("url", record_id)
        graph.upsert_node(
            url_id,
            types=["uco-observable:URL"],
            properties={
                "uco-core:name": f"Source address for {record_id}",
                "uco-core:description": [note],
                "uco-core:hasFacet": [
                    {
                        "@id": _iri("url-facet", record_id),
                        "@type": "uco-observable:URLFacet",
                        "uco-observable:fullValue": url,
                    }
                ],
            },
        )
        retrieval: dict[str, Any] = {
            "uco-core:name": f"Collector retrieval of {record_id}",
            "uco-action:actionStatus": "Success",
            "uco-action:object": [{"@id": url_id}],
            "uco-action:result": [{"@id": source_id}],
        }
        if retrieved:
            retrieval["uco-core:description"] = [
                "The CaseNoesis collector read this address and stored the content."
            ]
            retrieval["uco-action:endTime"] = {"@type": "xsd:dateTime", "@value": retrieved}
        else:
            retrieval["uco-core:description"] = [
                "The CaseNoesis collector read this address and stored the content. "
                "It did not record a retrieval time for this row, so none is asserted."
            ]
        graph.upsert_node(
            _iri("retrieval", record_id),
            types=["case-investigation:InvestigativeAction"],
            properties=retrieval,
        )
    graph.write(str(graph_path))


def _write_status(folder: Path, status: dict[str, Any]) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "record.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status


def read_status(record_id: str) -> dict[str, Any] | None:
    path = record_dir(record_id) / "record.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def process_one(entry: dict[str, Any], *, force: bool = False, gate: bool = False) -> dict[str, Any]:
    """Run the SDK processor on one indexed record. Returns its status row."""
    record_id = entry["record_id"]
    folder = record_dir(record_id)
    base = {
        "schema": RECORD_SCHEMA,
        "record_id": record_id,
        "kind": entry["kind"],
        "domain": entry["domain"],
        "domains": entry.get("domains") or [entry["domain"]],
    }
    if not force:
        previous = read_status(record_id)
        if previous is not None and previous.get("status") == "encoded":
            return previous
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    if entry["kind"] != "press":
        # A file on disk: the processor picks the reader from the extension.
        source = corpus.REPO_ROOT / entry["file"]
        file_kind, temporary = None, None
    else:
        body = str(corpus.press_row(entry).get("body") or "")
        source = temporary = folder / f"{record_id}.txt"
        temporary.write_text(body, encoding="utf-8")
        file_kind = "plain_text"

    processor = _processor()
    graph_path = folder / "graph.jsonld"
    started = time.time()
    try:
        result = processor.process_document_file(source.resolve(), graph_path, file_kind=file_kind)
    except ValueError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        return _write_status(folder, {**base, "status": "failed", "reason": str(error)})
    if temporary is not None:
        temporary.unlink()
    # The processor writes each sidecar twice (shared name and stem name).
    for duplicate in folder.glob("graph.*.json*"):
        duplicate.unlink()

    _add_collection_provenance(graph_path, entry)
    redaction = redact.redact_record(folder)
    classes: dict[str, int] = {}
    for item in result.records:
        classes[item.ontology_class] = classes.get(item.ontology_class, 0) + 1
    pin = sdk.pin_status()
    status: dict[str, Any] = {
        **base,
        "status": "encoded",
        "source_url": entry.get("source_url"),
        "pub_date": entry.get("pub_date"),
        "agency": entry.get("agency"),
        "stage": entry.get("stage"),
        "bucket": entry.get("bucket"),
        "source_sha256": result.sha256,
        "source_bytes": result.byte_size,
        "entities": dict(sorted(classes.items())),
        "entity_count": len(result.records),
        "truncated": bool(result.truncated),
        "required_extensions": list(result.required_extensions),
        "injection_warnings": list(result.injection_warnings),
        "processor": {"name": processor.TOOL_NAME, "version": processor.TOOL_VERSION},
        "sdk_commit": pin["commit"],
        "sdk_pinned": pin["pinned"],
        "redaction": redaction,
        "seconds": round(time.time() - started, 3),
    }
    if gate:
        receipt = sdk.gate(graph_path)
        sdk.write_receipt(graph_path, receipt)
        status["conforms"] = receipt["conforms"]
    return _write_status(folder, status)


def _process_safely(args: tuple[dict[str, Any], bool, bool]) -> dict[str, Any]:
    entry, force, gate = args
    try:
        return process_one(entry, force=force, gate=gate)
    except Exception as error:  # one bad record must not stop a batch
        return {
            "record_id": entry["record_id"],
            "kind": entry["kind"],
            "domain": entry["domain"],
            "status": "failed",
            "reason": f"{type(error).__name__}: {error}",
        }


def run(
    entries: list[dict[str, Any]],
    *,
    workers: int = 1,
    force: bool = False,
    gate: bool = False,
) -> dict[str, Any]:
    """Process many records. Returns counts by status and by entity class."""
    started = time.time()
    jobs = [(entry, force, gate) for entry in entries]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_process_safely, jobs, chunksize=16))
    else:
        rows = [_process_safely(job) for job in jobs]
    return {**tally(rows), "seconds": round(time.time() - started, 1)}


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    entities: dict[str, int] = {}
    conforming = gated = 0
    failures: list[dict[str, str]] = []
    for row in rows:
        label = row["status"] if row["status"] == "encoded" else f"{row['status']}:{row.get('reason')}"
        statuses[label] = statuses.get(label, 0) + 1
        for name, count in (row.get("entities") or {}).items():
            entities[name] = entities.get(name, 0) + count
        if "conforms" in row:
            gated += 1
            conforming += bool(row["conforms"])
        if row["status"] == "failed" and len(failures) < 10:
            failures.append({"record_id": row["record_id"], "reason": str(row.get("reason"))})
    summary: dict[str, Any] = {
        "records": len(rows),
        "statuses": dict(sorted(statuses.items())),
        "entities": dict(sorted(entities.items(), key=lambda item: -item[1])),
    }
    if gated:
        summary["gated"] = gated
        summary["conforming"] = conforming
    if failures:
        summary["failures"] = failures
    return summary


def _gate_one(record_id: str) -> dict[str, Any]:
    folder = record_dir(record_id)
    status = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    try:
        receipt = sdk.gate(folder / "graph.jsonld")
        sdk.write_receipt(folder / "graph.jsonld", receipt)
        status["conforms"] = receipt["conforms"]
    except Exception as error:  # report it, keep the batch going
        status["conforms"] = False
        status["gate_error"] = f"{type(error).__name__}: {error}"
    return _write_status(folder, status)


def _redact_one(record_id: str) -> dict[str, Any]:
    folder = record_dir(record_id)
    status = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    report = redact.redact_record(folder)
    status["redaction"] = report
    status.pop("title", None)
    # The graph changed, so an earlier receipt no longer describes it.
    status.pop("conforms", None)
    sdk.receipt_path(folder / "graph.jsonld").unlink(missing_ok=True)
    return _write_status(folder, status)


def redact_encoded(*, kind: str | None = None, workers: int = 1, force: bool = False) -> dict[str, Any]:
    """Redact every encoded record that has not been through this redaction
    version. Each one loses its receipt and must be gated again."""
    pending = [
        row["record_id"]
        for row in encoded_statuses()
        if row["status"] == "encoded"
        and (kind is None or row["kind"] == kind)
        and (force or (row.get("redaction") or {}).get("version") != redact.REDACTION_VERSION)
    ]
    if workers > 1 and pending:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_redact_one, pending, chunksize=16))
    else:
        rows = [_redact_one(record_id) for record_id in pending]
    return {"redacted_now": len(rows), **redaction_summary(kind=kind)}


def redaction_summary(*, kind: str | None = None) -> dict[str, Any]:
    done = [row["redaction"] for row in encoded_statuses() if row.get("redaction") and (kind is None or row["kind"] == kind)]
    return {
        "redacted": len(done),
        "people_renamed": sum(item.get("people_renamed", 0) for item in done),
        "names_masked": sum(item["names_masked"] for item in done),
        "addresses_cut": sum(item["addresses_cut"] for item in done),
        "name_check_failed": sum(1 for item in done if item["name_check"] != "pass"),
    }


def gate_encoded(*, kind: str | None = None, workers: int = 1) -> dict[str, Any]:
    """Validate every encoded record graph that has no receipt yet."""
    pending = [
        row["record_id"]
        for row in encoded_statuses()
        if row["status"] == "encoded"
        and "conforms" not in row
        and (kind is None or row["kind"] == kind)
    ]
    if workers > 1 and pending:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_gate_one, pending, chunksize=8))
    else:
        rows = [_gate_one(record_id) for record_id in pending]
    gated = [row for row in encoded_statuses() if "conforms" in row and (kind is None or row["kind"] == kind)]
    return {
        "gated_now": len(rows),
        "gated_total": len(gated),
        "conforming": sum(1 for row in gated if row["conforms"]),
        "not_conforming": [row["record_id"] for row in gated if not row["conforms"]][:20],
    }


def encoded_statuses() -> list[dict[str, Any]]:
    """Status rows for every record that has been through the processor."""
    if not RECORDS.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(RECORDS.glob("*/record.json"))
    ]


def status() -> dict[str, Any]:
    """The pinned SDK, what the collector has, and what has been encoded."""
    encoded: dict[str, int] = {}
    gated = conforming = 0
    for row in encoded_statuses():
        label = row["status"] if row["status"] == "encoded" else f"{row['status']}:{row.get('reason')}"
        key = f"{row['kind']}/{label}"
        encoded[key] = encoded.get(key, 0) + 1
        if "conforms" in row:
            gated += 1
            conforming += bool(row["conforms"])
    pin = sdk.pin_status()
    return {
        "sdk": {key: pin[key] for key in ("tag", "commit", "pinned", "case_uco", "case_utils")},
        "collected": corpus.summarize(corpus.load_index()),
        "encoded": dict(sorted(encoded.items())),
        "gated": gated,
        "conforming": conforming,
        "redaction": redaction_summary(),
    }
