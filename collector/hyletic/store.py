#!/usr/bin/env python3
"""On-disk capture for data/collected/hyletic_data/.

One object is raw bytes plus a sidecar. The sidecar is the provenance a later
CASE-UCO load can cite: URL, retrieval time, sha256, HTTP status. Curator
labels (catalog_role, see_also) are filing notes. They are not observed facts
and they are not inferred graph edges.

Layout::

    data/collected/hyletic_data/<collection>/<slug>/<filename>
    data/collected/hyletic_data/<collection>/<slug>/<filename>.provenance.json
    data/collected/hyletic_data/<collection>/manifest.jsonl
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO / "data" / "collected" / "hyletic_data"
USER_AGENT = (
    "CaseNoesis-Hyletic/1.0 (public-record research; "
    "UMass HRPO NHSR #8252 covers exploitation case records only)"
)
SCHEMA = "casenoesis.hyletic.capture.v1"
BLOCKED_HOSTS = {
    "pacer.uscourts.gov",
    "ecf.pacer.uscourts.gov",
    "pcl.uscourts.gov",
}
MAX_BYTES = 40_000_000


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", (text or "doc").strip()).strip("-._")
    return (slug or "doc")[:80]


def collection_dir(name: str, root: Path | None = None) -> Path:
    base = Path(root) if root else DEFAULT_ROOT
    if not base.is_absolute():
        base = REPO / base
    path = base / safe_slug(name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _host_blocked(url: str) -> str:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if host in BLOCKED_HOSTS or host.endswith(".pacer.uscourts.gov"):
        return host
    return ""


def fetch_url(url: str, *, timeout: float = 60.0, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    """GET one public URL. Returns raw bytes. Refuses PACER hosts."""
    blocked = _host_blocked(url)
    if blocked:
        return {"ok": False, "error": f"refusing host {blocked}", "source_url": url, "pacer_purchases": 0}
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc), "source_url": url, "pacer_purchases": 0}
    final = resp.url or url
    blocked = _host_blocked(final)
    if blocked:
        return {"ok": False, "error": f"redirect refused {blocked}", "source_url": url, "pacer_purchases": 0}
    data = resp.content or b""
    if len(data) > max_bytes:
        return {
            "ok": False,
            "error": f"body {len(data)} exceeds {max_bytes}",
            "source_url": url,
            "http_status": resp.status_code,
            "pacer_purchases": 0,
        }
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}",
            "source_url": url,
            "http_status": resp.status_code,
            "pacer_purchases": 0,
        }
    mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return {
        "ok": True,
        "data": data,
        "source_url": url,
        "final_url": final,
        "http_status": resp.status_code,
        "mime_type": mime,
        "pacer_purchases": 0,
    }


def save_bytes(
    *,
    collection: str,
    slug: str,
    filename: str,
    data: bytes,
    source_url: str,
    root: Path | None = None,
    http_status: int | None = None,
    mime_type: str = "",
    version_pin: str = "",
    title: str = "",
    catalog_role: str = "",
    see_also: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write bytes and a sidecar. Skip when the same hash is already stored."""
    folder = collection_dir(collection, root) / safe_slug(slug)
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_slug(filename) if "." not in filename else filename.replace("/", "_")
    dest = folder / name
    digest = sha256_bytes(data)
    sidecar_path = Path(str(dest) + ".provenance.json")
    if dest.is_file() and sidecar_path.is_file():
        try:
            prior = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prior = {}
        if prior.get("content_sha256") == digest and prior.get("source_url") == source_url:
            prior["skipped"] = "unchanged"
            return prior

    record: dict[str, Any] = {
        "schema": SCHEMA,
        "collection": safe_slug(collection),
        "slug": safe_slug(slug),
        "filename": dest.name,
        "title": title,
        "catalog_role": catalog_role,
        "see_also": list(see_also or []),
        "relationship_status": "curator_label",
        "source_url": source_url,
        "retrieved_at": utcnow(),
        "content_sha256": digest,
        "byte_length": len(data),
        "http_status": http_status,
        "mime_type": mime_type,
        "version_pin": version_pin,
        "observed": True,
        "inferred": False,
        "pacer_purchases": 0,
        "relative_path": str(dest.relative_to(collection_dir(collection, root).parent)),
    }
    if extra:
        record["extra"] = extra
    dest.write_bytes(data)
    sidecar_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    manifest = collection_dir(collection, root) / "manifest.jsonl"
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    _append_public(record)
    record["ok"] = True
    record["skipped"] = ""
    return record


_PUBLIC_KIND = {
    "wayback": "wayback",
    "statutes": "statute",
    "calibration": "calibration",
    "litigation": "litigation",
}


def _append_public(record: dict[str, Any]) -> None:
    kind = _PUBLIC_KIND.get(str(record.get("collection") or ""))
    if not kind:
        return
    import sys

    collector = Path(__file__).resolve().parents[1]
    if str(collector) not in sys.path:
        sys.path.insert(0, str(collector))
    import public_lookup

    extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}
    original = str(extra.get("original_url") or record.get("source_url") or "")
    public_lookup.append_lookup(
        kind,
        domain=str(record.get("slug") or record.get("catalog_role") or ""),
        agency=public_lookup._host(original),
        title=str(record.get("title") or ""),
        pub_date=str(record.get("version_pin") or record.get("retrieved_at") or ""),
        source_url=str(record.get("source_url") or ""),
    )


def save_failure(
    *,
    collection: str,
    slug: str,
    source_url: str,
    error: str,
    root: Path | None = None,
    title: str = "",
    catalog_role: str = "",
) -> dict[str, Any]:
    record = {
        "schema": SCHEMA,
        "collection": safe_slug(collection),
        "slug": safe_slug(slug),
        "title": title,
        "catalog_role": catalog_role,
        "source_url": source_url,
        "retrieved_at": utcnow(),
        "ok": False,
        "error": error,
        "observed": False,
        "inferred": False,
        "pacer_purchases": 0,
    }
    manifest = collection_dir(collection, root) / "manifest.jsonl"
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
