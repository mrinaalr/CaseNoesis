#!/usr/bin/env python3
"""Free CourtListener / RECAP helpers. Never purchases PACER pages."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

COURTLISTENER_SEARCH = "https://www.courtlistener.com/api/rest/v4/search/"
COURTLISTENER_STORAGE = "https://storage.courtlistener.com"
USER_AGENT = "CaseNoesis-Collector/1.0 (research; UMass HRPO NHSR #8252; free public records)"
DEFAULT_TIMEOUT = 45.0
MIN_DELAY = 1.5
CRIMINAL_RE = re.compile(
    r"united states v\.|u\.s\. v\.|usa v\.|\bfraud\b|\btraffick|\bransomware\b|\bscam\b|"
    r"servitude|peonage|wire fraud|computer fraud|"
    r"child\s+exploit|child\s+porn|\bCSAM\b|enticement|sex\s+traffick|\bICAC\b|"
    r"sextortion|child\s+sexual",
    re.I,
)
SURNAME_NOISE_RE = re.compile(r"^(Elder|Woody Elder)\b", re.I)


def _on_topic(hit: dict[str, Any]) -> bool:
    blob = " ".join(
        str(hit.get(k) or "")
        for k in ("case_name", "description", "docket_number")
    )
    if SURNAME_NOISE_RE.search((hit.get("case_name") or "").strip()) and "fraud" not in blob.lower():
        return False
    return bool(CRIMINAL_RE.search(blob))


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    token = (
        os.getenv("COURTLISTENER_API_TOKEN")
        or os.getenv("COURTLISTENER_TOKEN")
        or ""
    ).strip()
    if token:
        headers["Authorization"] = f"Token {token}"
    return headers


def load_token_from_env_files(paths: list[Path]) -> str:
    existing = (os.getenv("COURTLISTENER_API_TOKEN") or os.getenv("COURTLISTENER_TOKEN") or "").strip()
    if existing:
        return existing
    for env_path in paths:
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("COURTLISTENER_API_TOKEN=") or line.startswith("COURTLISTENER_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip("'\"")
                if tok:
                    os.environ.setdefault("COURTLISTENER_API_TOKEN", tok)
                    return tok
    return ""


_last_call = 0.0


def _get(url: str, params: dict[str, Any] | None = None) -> requests.Response | None:
    global _last_call
    wait = MIN_DELAY - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(url, params=params, headers=_headers(), timeout=DEFAULT_TIMEOUT)
    _last_call = time.monotonic()
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        try:
            pause = min(float(retry_after), 45.0) if retry_after else 12.0
        except ValueError:
            pause = 12.0
        print(f"  [courtlistener] 429; sleeping {pause}s", file=sys.stderr)
        time.sleep(pause)
        wait = MIN_DELAY - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        resp = requests.get(url, params=params, headers=_headers(), timeout=DEFAULT_TIMEOUT)
        _last_call = time.monotonic()
    if resp.status_code == 429:
        print("  [courtlistener] still 429; skipping query", file=sys.stderr)
        return None
    resp.raise_for_status()
    return resp


def search_free(
    query: str,
    *,
    search_type: str = "r",
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Search CourtListener; keep only RECAP-available ($0) documents."""
    query = (query or "").strip()
    if not query:
        return []
    search_type = (search_type or "r").strip().lower()
    params = {"q": query, "type": search_type, "order_by": "score desc"}
    try:
        resp = _get(COURTLISTENER_SEARCH, params)
    except requests.RequestException as exc:
        print(f"  [courtlistener] search failed: {exc}", file=sys.stderr)
        return []
    if resp is None:
        return []
    payload = resp.json()
    out: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        nested = item.get("recap_documents") or []
        free_nested = []
        for doc in nested if isinstance(nested, list) else []:
            if not isinstance(doc, dict):
                continue
            fp = doc.get("filepath_local")
            if not (doc.get("is_available") and fp):
                continue
            free_nested.append(
                {
                    "id": doc.get("id"),
                    "description": doc.get("description") or doc.get("short_description"),
                    "filepath_local": fp,
                    "download_url": f"{COURTLISTENER_STORAGE}/{fp}",
                    "page_url": (
                        f"https://www.courtlistener.com{doc['absolute_url']}"
                        if doc.get("absolute_url") and not str(doc["absolute_url"]).startswith("http")
                        else doc.get("absolute_url")
                    ),
                }
            )
        fp = item.get("filepath_local")
        available = bool(item.get("is_available") and fp)
        if search_type == "rd" and not available:
            continue
        if search_type in {"r", "d"} and not free_nested and not available:
            continue
        abs_url = item.get("docket_absolute_url") or item.get("absolute_url") or ""
        if abs_url and not str(abs_url).startswith("http"):
            abs_url = f"https://www.courtlistener.com{abs_url}"
        rec = {
            "search_type": search_type,
            "case_name": item.get("caseName") or item.get("caseNameFull") or item.get("case_name"),
            "docket_number": item.get("docketNumber") or item.get("docket_number"),
            "court": item.get("court"),
            "date_filed": item.get("dateFiled") or item.get("date_filed"),
            "docket_id": item.get("docket_id") or (item.get("id") if search_type in ("r", "d") else None),
            "document_id": item.get("id") if search_type == "rd" else None,
            "filepath_local": fp if available else None,
            "download_url": f"{COURTLISTENER_STORAGE}/{fp}" if available else None,
            "absolute_url": abs_url,
            "free_nested_documents": free_nested,
            "query": query,
            "cost": "free",
            "observed": True,
            "inferred": False,
        }
        if not _on_topic(rec):
            continue
        out.append(rec)
        if len(out) >= max_results:
            break
    return out


def download_free_pdf(url: str, dest: Path) -> dict[str, Any]:
    """Download a storage.courtlistener.com PDF. Refuses PACER/ecf hosts."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "storage.courtlistener.com" not in host and "courtlistener.com" not in host:
        return {
            "ok": False,
            "error": f"refusing non-CourtListener host {host} (no PACER purchases)",
            "cost": "blocked",
        }
    if "pacer" in host or "ecf." in host:
        return {"ok": False, "error": "refusing PACER/ECF host", "cost": "blocked"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"}
    token = (os.getenv("COURTLISTENER_API_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Token {token}"
    global _last_call
    wait = MIN_DELAY - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT, stream=True)
    _last_call = time.monotonic()
    resp.raise_for_status()
    ctype = (resp.headers.get("Content-Type") or "").lower()
    data = resp.content
    if "pdf" not in ctype and not data.startswith(b"%PDF"):
        return {
            "ok": False,
            "error": f"not a PDF (content-type={ctype})",
            "bytes": len(data),
        }
    dest.write_bytes(data)
    return {
        "ok": True,
        "path": str(dest),
        "bytes": dest.stat().st_size,
        "source_url": url,
        "cost": "free",
        "observed": True,
        "inferred": False,
    }


def collect_free_court_records(
    queries: list[str],
    *,
    dest_dir: Path,
    max_records: int = 5,
    per_query: int = 5,
) -> list[dict[str, Any]]:
    """Search then download up to max_records free RECAP PDFs."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    collected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query in queries:
        if len(collected) >= max_records:
            break
        hits = search_free(query, search_type="r", max_results=per_query)
        if not hits:
            continue
        for hit in hits:
            candidates: list[dict[str, Any]] = []
            if hit.get("download_url"):
                candidates.append(
                    {
                        "download_url": hit["download_url"],
                        "description": hit.get("case_name"),
                        "id": hit.get("document_id"),
                    }
                )
            candidates.extend(hit.get("free_nested_documents") or [])
            for doc in candidates:
                if len(collected) >= max_records:
                    break
                url = doc.get("download_url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                slug = str(doc.get("id") or len(collected) + 1)
                dest = dest_dir / f"{slug}.pdf"
                result = download_free_pdf(url, dest)
                record = {
                    **hit,
                    "chosen_document": doc,
                    "download": result,
                    "query": query,
                }
                if result.get("ok"):
                    collected.append(record)
                    break
    (dest_dir / "court_manifest.json").write_text(
        json.dumps(collected, indent=2, default=str),
        encoding="utf-8",
    )
    return collected
