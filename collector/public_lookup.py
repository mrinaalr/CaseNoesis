"""One public JSONL per source type, same row as press_lookup.jsonl.

No article text and no PDF path. A row is enough to fetch the record again.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
PUBLIC = REPO / "data" / "collected" / "public"
NHSR = "UMass HRPO NHSR #8252 (16 Sep 2026)"

FILES = {
    "press": "press_lookup.jsonl",
    "recap": "recap_lookup.jsonl",
    "wayback": "wayback_lookup.jsonl",
    "statute": "statute_lookup.jsonl",
    "calibration": "calibration_lookup.jsonl",
    "litigation": "litigation_lookup.jsonl",
}


def read_lookup(path: Path) -> list[dict]:
    """Read one public JSONL. Blank lines are skipped. Order is file order."""
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def lookup_paths(public_dir: Path | None = None) -> list[Path]:
    root = public_dir or PUBLIC
    return [root / name for name in FILES.values()]

_seen: dict[str, set[str]] = {}


def _norm(url: str) -> str:
    """Dedup key. Keeps the query (?p=101 and ?p=202 are different pages); drops utm_* and #fragment."""
    text = (url or "").strip().split("#")[0]
    base, _, query = text.partition("?")
    kept = [part for part in query.split("&") if part and not part.lower().startswith("utm_")]
    base = base.rstrip("/")
    return f"{base}?{'&'.join(kept)}" if kept else base


CAPTION_PLACEHOLDER = "case"


def neutral_docket_url(url: str) -> str:
    """Replace the case caption at the end of a CourtListener docket address.

    CourtListener writes the caption as the last path segment, for example
    /docket/73715928/104/united-states-v-antonio-michel/. That segment names a
    party. CourtListener does not use it to find the record: any word in that
    place opens the same page. It cannot simply be dropped, though, because
    /docket/73715928/104/ opens the whole docket instead of entry 104, and
    /docket/5471876/ is a 404. So the caption becomes the fixed word "case".

    Only paths under /docket/ on www.courtlistener.com (or courtlistener.com)
    change. storage.courtlistener.com PDF addresses and every other host are
    returned unchanged. The query string is kept; a #fragment is dropped.
    """
    text = (url or "").strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in {"courtlistener.com", "www.courtlistener.com"}:
        return text
    segments = [part for part in parsed.path.split("/") if part]
    if not segments or segments[0] != "docket":
        return text
    numbers: list[str] = []
    for part in segments[1:]:
        if not part.isdigit():
            break
        numbers.append(part)
    if not numbers:
        return text
    path = "/docket/" + "/".join(numbers) + f"/{CAPTION_PLACEHOLDER}/"
    return parsed._replace(path=path, fragment="").geturl()


def _date(value: str) -> str:
    raw = (value or "").strip()
    if len(raw) >= 14 and raw[:14].isdigit() and raw.startswith(("19", "20")):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if len(raw) >= 10 and raw[4:5] == "-" and raw[:4].isdigit():
        return raw[:10]
    return ""


def _load_seen(kind: str) -> set[str]:
    if kind in _seen:
        return _seen[kind]
    path = PUBLIC / FILES[kind]
    found: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = _norm(neutral_docket_url(str(rec.get("source_url") or "")))
            if url:
                found.add(url)
    _seen[kind] = found
    return found


def append_lookup(
    kind: str,
    *,
    domain: str = "",
    agency: str = "",
    title: str = "",
    pub_date: str = "",
    source_url: str = "",
) -> bool:
    """Append one public lookup row. Skip a URL already in that file.

    A CourtListener docket address loses its case caption first (see
    neutral_docket_url), so no caller can write a party name into source_url.
    """
    if kind not in FILES:
        raise ValueError(f"unknown public lookup {kind}")
    url = neutral_docket_url(source_url)
    if not url:
        return False
    seen = _load_seen(kind)
    key = _norm(url)
    if key in seen:
        return False
    row = {
        "kind": kind,
        "domain": domain or "",
        "agency": agency or "",
        "title": (title or "")[:500],
        "pub_date": _date(pub_date),
        "source_url": url,
        "nhsr": NHSR,
    }
    PUBLIC.mkdir(parents=True, exist_ok=True)
    with (PUBLIC / FILES[kind]).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    seen.add(key)
    return True


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def backfill() -> dict[str, int]:
    """Write public rows for captures already on disk. Does not rewrite press_lookup."""
    counts = {name: 0 for name in FILES}
    collected = REPO / "data" / "collected"
    for path in (collected / "press_releases").rglob("*_resolved.json"):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rows, list):
            continue
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            if append_lookup(
                "press",
                domain=str(rec.get("domain") or ""),
                agency=str(rec.get("agency") or ""),
                title=str(rec.get("title") or ""),
                pub_date=str(rec.get("pub_date") or ""),
                source_url=str(rec.get("source_url") or ""),
            ):
                counts["press"] += 1
    for side in (collected / "hyletic_data").rglob("*.provenance.json"):
        try:
            rec = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        kind = {"wayback": "wayback", "statutes": "statute", "calibration": "calibration", "litigation": "litigation"}.get(
            str(rec.get("collection") or "")
        )
        if not kind or not rec.get("content_sha256"):
            continue
        extra = rec.get("extra") if isinstance(rec.get("extra"), dict) else {}
        original = str(extra.get("original_url") or rec.get("source_url") or "")
        if append_lookup(
            kind,
            domain=str(rec.get("slug") or ""),
            agency=_host(original),
            title=str(rec.get("title") or ""),
            pub_date=str(rec.get("version_pin") or rec.get("retrieved_at") or ""),
            source_url=str(rec.get("source_url") or ""),
        ):
            counts[kind] += 1
    recap = collected / "recap"
    for path in list(recap.rglob("*.jsonl")) + list(recap.rglob("court_*.json")) + list(recap.rglob("court_manifest.json")):
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text) if path.suffix == ".json" else None
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload if isinstance(payload, list) else []
        if payload is None:
            rows = []
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        elif isinstance(payload, dict):
            rows = [payload]
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            download = rec.get("download") if isinstance(rec.get("download"), dict) else {}
            url = str(
                download.get("source_url")
                or rec.get("source_url")
                or rec.get("download_url")
                or rec.get("absolute_url")
                or ""
            )
            domain = str(rec.get("domain") or rec.get("press_domain") or path.parts[-2])
            if domain in {"manifests", "from_press", "bulk"}:
                domain = str(rec.get("press_domain") or rec.get("domain") or "trafficking")
            if append_lookup(
                "recap",
                domain=domain,
                agency=str(rec.get("court") or rec.get("agency") or ""),
                title=str(rec.get("case_name") or rec.get("title") or rec.get("description") or rec.get("press_title") or ""),
                pub_date=str(rec.get("date_filed") or rec.get("pub_date") or rec.get("entry_date") or ""),
                source_url=url,
            ):
                counts["recap"] += 1
    return counts


if __name__ == "__main__":
    print(json.dumps(backfill()))
