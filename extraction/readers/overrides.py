"""Human verdicts.

`config/extraction_overrides.json` holds one list per record id:

    {"pr-0123456789abcdef": [
        {"field": "money", "span_start": 1047, "span_end": 1060, "role": "loss"},
        {"field": "scheme", "value": "romance", "span_start": 220, "span_end": 233, "role": "present"}
    ]}

A verdict goes through the same span gate as every other assertion, then wins
the vote for its mention. The file is optional and is committed only when a
person writes one.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from extraction.readers import Doc, assertion, register_reader

VERSION = "overrides_1.0"
METHOD = "human"
OVERRIDES_PATH = Path(__file__).resolve().parents[2] / "config" / "extraction_overrides.json"


@lru_cache(maxsize=1)
def _overrides() -> dict[str, list[dict[str, Any]]]:
    if not OVERRIDES_PATH.is_file():
        return {}
    return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))


def read(doc: Doc) -> list[dict[str, Any]]:
    return [
        assertion(
            row["field"], row.get("value"), row["role"], METHOD, VERSION, 1.0,
            row.get("span_start"), row.get("span_end"), note=row.get("note"),
        )
        for row in _overrides().get(doc.record_id, [])
    ]


register_reader("human", ("press", "court", "reference"), read, version=VERSION, order=90)
