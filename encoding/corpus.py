"""Index of what the collector has on disk: press rows, court PDFs, and
reference records (statutes, calibration reports, platform litigation, and
archived platform policy pages).

Read-only over `data/collected/`. The index (`data/encoded/index.jsonl`) holds
pointers and public metadata only: no article text, no party names. Every
collected record is indexed. All of it is public record under NHSR #8252.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTED = REPO_ROOT / "data" / "collected"
ENCODED = REPO_ROOT / "data" / "encoded"
INDEX_PATH = ENCODED / "index.jsonl"
INDEX_META_PATH = ENCODED / "index.meta.json"
INDEX_SCHEMA = "noesis-index/3"

PRESS = COLLECTED / "press_releases"
RECAP = COLLECTED / "recap"
REFERENCE = COLLECTED / "hyletic_data"
PROVENANCE_SUFFIX = ".provenance.json"

# Read in this order. A URL seen in an earlier file is not indexed again
# (the fraud study file already contains the earlier DOJ fraud bulk rows).
PRESS_FILES = (
    PRESS / "fraud" / "study_records.jsonl",
    PRESS / "fraud" / "state_records.jsonl",
)
PRESS_BULK_DIR = PRESS / "bulk" / "records"


def _short_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()[:16]


def press_record_id(source_url: str) -> str:
    return "pr-" + _short_hash(source_url.strip().encode("utf-8"))


def _press_files() -> list[Path]:
    files = [path for path in PRESS_FILES if path.is_file()]
    if PRESS_BULK_DIR.is_dir():
        files.extend(sorted(PRESS_BULK_DIR.glob("*.jsonl")))
    return files


def _iter_press() -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    for path in _press_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        with path.open("rb") as handle:
            offset = 0
            for raw in handle:
                start, offset = offset, offset + len(raw)
                if not raw.strip():
                    continue
                row = json.loads(raw)
                url = str(row.get("source_url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                domain = str(row.get("domain") or "unknown")
                entry: dict[str, Any] = {
                    "record_id": press_record_id(url),
                    "kind": "press",
                    "domain": domain,
                    "source_url": url,
                    "agency": row.get("agency") or None,
                    "pub_date": row.get("pub_date") or None,
                    "stage": row.get("stage") or None,
                    "bucket": row.get("bucket") or None,
                    "file": rel,
                    "offset": start,
                    "chars": len(str(row.get("body") or "")),
                }
                yield entry


def _court_metadata() -> dict[str, dict[str, Any]]:
    """PDF file name -> public locator fields, from the collector's logs."""
    found: dict[str, dict[str, Any]] = {}

    def note(pdf: Any, **fields: Any) -> None:
        name = Path(str(pdf or "")).name
        if name:
            slot = found.setdefault(name, {})
            for key, value in fields.items():
                if value and key not in slot:
                    slot[key] = value

    for manifest in sorted(RECAP.glob("*/court_manifest.json")):
        try:
            rows = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in rows if isinstance(rows, list) else []:
            note(
                row.get("filepath_local"),
                source_url=row.get("absolute_url"),
                court=row.get("court"),
                docket_number=row.get("docket_number"),
                filed=row.get("date_filed"),
            )
    for log in sorted(RECAP.glob("**/*.jsonl")):
        with log.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "pdf" not in row:
                    break
                note(
                    row.get("pdf"),
                    source_url=row.get("absolute_url") or row.get("download_url"),
                    court=row.get("court"),
                    docket_number=row.get("docket_number"),
                    filed=row.get("entry_date"),
                    press_url=row.get("press_url"),
                    collected_as=row.get("document_kind"),
                )
    return found


def _iter_court() -> Iterator[dict[str, Any]]:
    if not RECAP.is_dir():
        return
    metadata = _court_metadata()
    seen: dict[str, dict[str, Any]] = {}
    for path in sorted(RECAP.rglob("*.pdf")):
        folder = path.relative_to(RECAP).parts[0]
        if folder.startswith("_"):  # set aside by the collector, such as filings from civil cases
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            # The same bytes filed under another domain folder: one record, in
            # every domain it was collected for.
            seen[digest]["copies"] += 1
            if folder not in seen[digest]["domains"]:
                seen[digest]["domains"].append(folder)
            continue
        extra = metadata.get(path.name, {})
        entry: dict[str, Any] = {
            "record_id": "ct-" + digest[:16],
            "kind": "court",
            "domain": folder,
            "domains": [folder],
            "source_url": extra.get("source_url"),
            "agency": extra.get("court"),
            "pub_date": extra.get("filed"),
            "docket_number": extra.get("docket_number"),
            "press_url": extra.get("press_url"),
            "collected_as": extra.get("collected_as"),
            "file": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": digest,
            "bytes": path.stat().st_size,
            "copies": 1,
        }
        seen[digest] = entry
    yield from seen.values()


def _iter_reference() -> Iterator[dict[str, Any]]:
    """One entry per captured reference file. The collector wrote a provenance
    sidecar beside each one, with the address and the retrieval time."""
    if not REFERENCE.is_dir():
        return
    seen: dict[str, dict[str, Any]] = {}
    for sidecar in sorted(REFERENCE.rglob("*" + PROVENANCE_SUFFIX)):
        path = sidecar.with_name(sidecar.name[: -len(PROVENANCE_SUFFIX)])
        if not path.is_file():
            continue
        try:
            capture = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            seen[digest]["copies"] += 1
            continue
        seen[digest] = {
            "record_id": "rf-" + digest[:16],
            "kind": "reference",
            "domain": str(capture.get("collection") or path.relative_to(REFERENCE).parts[0]),
            "source_url": capture.get("source_url"),
            "retrieved_at": capture.get("retrieved_at"),
            "title": capture.get("title"),
            "slug": capture.get("slug"),
            "bucket": capture.get("catalog_role"),
            "version_pin": capture.get("version_pin"),
            "file": path.relative_to(REPO_ROOT).as_posix(),
            "sha256": digest,
            "bytes": path.stat().st_size,
            "copies": 1,
        }
    yield from seen.values()


def build_index() -> dict[str, Any]:
    """Rebuild `data/encoded/index.jsonl` from what is on disk."""
    ENCODED.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with INDEX_PATH.open("w", encoding="utf-8") as out:
        for entry in (*_iter_press(), *_iter_court(), *_iter_reference()):
            entry = {key: value for key, value in entry.items() if value is not None}
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")
            key = f"{entry['kind']}/{entry['domain']}"
            counts[key] = counts.get(key, 0) + 1
    INDEX_META_PATH.write_text(json.dumps(_signature(), indent=2) + "\n", encoding="utf-8")
    return counts


def _signature() -> dict[str, Any]:
    """What the index was built from, cheap to recompute: each press file's
    size and modification time (press rows are read back by byte offset), and
    the count and newest modification time of the court and reference files."""
    press = {}
    for path in _press_files():
        stat = path.stat()
        press[path.relative_to(REPO_ROOT).as_posix()] = [stat.st_size, stat.st_mtime_ns]
    files = [path for path in RECAP.rglob("*.pdf")] if RECAP.is_dir() else []
    files += [path for path in REFERENCE.rglob("*" + PROVENANCE_SUFFIX)] if REFERENCE.is_dir() else []
    return {
        "schema": INDEX_SCHEMA,
        "press": press,
        "files": len(files),
        "newest": max((path.stat().st_mtime_ns for path in files), default=0),
    }


def index_is_current() -> bool:
    if not (INDEX_PATH.is_file() and INDEX_META_PATH.is_file()):
        return False
    try:
        return json.loads(INDEX_META_PATH.read_text(encoding="utf-8")) == _signature()
    except (OSError, json.JSONDecodeError):
        return False


def load_index() -> list[dict[str, Any]]:
    """The index, rebuilt first when the collected files have changed under it.
    A stale index would read press rows from the wrong byte offsets."""
    if not index_is_current():
        build_index()
    with INDEX_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def press_row(entry: dict[str, Any]) -> dict[str, Any]:
    """The full collector row for a press index entry, body included."""
    with (REPO_ROOT / entry["file"]).open("rb") as handle:
        handle.seek(entry["offset"])
        return json.loads(handle.readline())


def in_domain(entry: dict[str, Any], domain: str) -> bool:
    return domain in (entry.get("domains") or [entry["domain"]])


def summarize(entries: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_kind: dict[str, dict[str, int]] = {}
    for entry in entries:
        slot = by_kind.setdefault(entry["kind"], {})
        for domain in entry.get("domains") or [entry["domain"]]:
            slot[domain] = slot.get(domain, 0) + 1
    return by_kind
