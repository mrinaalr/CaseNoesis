"""
Human adjudication overrides for victim-age gate REVIEW slots.

File format (JSON array):
  [{"case_id": "ncmec_2024_928", "age": 10, "decision": "keep"}]
  [{"case_id": "some_case", "age": 7, "decision": "drop"}]

Override ``keep`` promotes a slot (including REVIEW). Override ``drop`` removes
even auto-KEEP slots.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Tuple

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "victim_age_overrides.json"
)

_cache: Dict[Tuple[str, int], str] | None = None


def overrides_path() -> Path:
    return Path(os.environ.get("VICTIM_AGE_OVERRIDES_PATH", str(_DEFAULT_PATH)))


def load_victim_age_overrides(reload: bool = False) -> Dict[Tuple[str, int], str]:
    """Load overrides as ``{(case_id, age): 'keep'|'drop'}``."""
    global _cache
    if _cache is not None and not reload:
        return _cache

    path = overrides_path()
    out: Dict[Tuple[str, int], str] = {}
    if not path.is_file():
        _cache = out
        return out

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected JSON array")

    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"{path}[{i}]: expected object")
        cid = row.get("case_id")
        age = row.get("age")
        decision = (row.get("decision") or "").strip().lower()
        if not cid or age is None:
            raise ValueError(f"{path}[{i}]: need case_id and age")
        if decision not in ("keep", "drop"):
            raise ValueError(f"{path}[{i}]: decision must be keep or drop")
        out[(str(cid), int(age))] = decision

    _cache = out
    return out


def clear_overrides_cache() -> None:
    global _cache
    _cache = None
