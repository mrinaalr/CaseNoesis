"""Readers: independent witnesses over one record.

A reader takes a `Doc` and returns assertions. It never sees another reader's
output, never merges, and never decides. Each assertion names its method; the
method's family is what the resolver counts.

    family            method               what it reads
    surface_pattern   regex                fixed phrasings anchored on the value
    clause            clause_cue           the clause around every typed token
    lookup            statute_table        a citation, against the statute table
    sdk_rule          sdk_processor        the pinned SDK's document processor
    metadata          collector_metadata   what the collector recorded (no span)
    llm               llm                  optional; sentence windows; must quote
    human             human                verdicts in config/extraction_overrides.json

A reader registers for the record kinds it applies to. To add one, write a
function `(Doc) -> list[assertion]` and call `register_reader`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

KINDS = ("press", "court", "reference")

FAMILY = {
    "regex": "surface_pattern",
    "clause_cue": "clause",
    "statute_table": "lookup",
    "sdk_processor": "sdk_rule",
    "collector_metadata": "metadata",
    "llm": "llm",
    "human": "human",
}


@dataclass
class Doc:
    record_id: str
    kind: str
    domain: str
    text: str
    entry: dict[str, Any] = field(default_factory=dict)
    # SDK anchors over this same text: [{"start", "end", "label", "class", "event_types"}]
    sdk_anchors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Reader:
    name: str
    kinds: tuple[str, ...]
    fn: Callable[[Doc], list[dict[str, Any]]]
    version: str
    order: int = 100


_READERS: dict[str, Reader] = {}


def register_reader(
    name: str, kinds: tuple[str, ...], fn: Callable[[Doc], list[dict[str, Any]]], *, version: str, order: int = 100
) -> None:
    _READERS[name] = Reader(name, kinds, fn, version, order)


def readers_for(kind: str) -> list[Reader]:
    _load()
    return sorted((r for r in _READERS.values() if kind in r.kinds), key=lambda r: (r.order, r.name))


def reader_versions() -> dict[str, str]:
    _load()
    return {name: reader.version for name, reader in sorted(_READERS.items())}


def assertion(
    field_name: str, value: Any, role: str | None, method: str, version: str, confidence: float,
    start: int | None, end: int | None, **extras: Any,
) -> dict[str, Any]:
    return {
        "field": field_name, "value": value, "role": role or "unknown", "method": method,
        "method_version": version, "family": FAMILY[method], "confidence": confidence,
        "span_start": start, "span_end": end, "extras": {k: v for k, v in extras.items() if v is not None},
    }


_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from extraction.readers import clause, llm, lookup, metadata, overrides, patterns, sdk  # noqa: F401
