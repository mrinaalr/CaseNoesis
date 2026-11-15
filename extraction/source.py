"""Where a record's metadata and text come from.

The layers after extraction (cases, people, events) need two things about a
record besides what is in the store: its index entry and its text. On the
collected corpus those come from the record index and the files beside it. On
the gold set and in tests they are held in memory. A layer takes a `Source`
and does not care which.
"""

from __future__ import annotations

from typing import Any, Iterable


class CorpusSource:
    """The collected corpus: the record index, and the text the engine read."""

    def __init__(self) -> None:
        self._index: dict[str, dict[str, Any]] | None = None

    def _entries(self) -> dict[str, dict[str, Any]]:
        if self._index is None:
            from encoding import corpus

            self._index = {entry["record_id"]: entry for entry in corpus.load_index()}
        return self._index

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries().values())

    def entry(self, record_id: str) -> dict[str, Any]:
        return self._entries().get(record_id) or {}

    def text(self, record_id: str) -> str | None:
        from extraction import pipeline

        entry = self._entries().get(record_id)
        loaded = pipeline.load_doc(entry) if entry else None
        return loaded[0].text if loaded else None


class MemorySource:
    """Records held in memory: `(entry, text)` pairs."""

    def __init__(self, records: Iterable[tuple[dict[str, Any], str]]) -> None:
        self._records = {entry["record_id"]: (entry, text) for entry, text in records}

    def entries(self) -> list[dict[str, Any]]:
        return [entry for entry, _ in self._records.values()]

    def entry(self, record_id: str) -> dict[str, Any]:
        return self._records.get(record_id, ({}, ""))[0]

    def text(self, record_id: str) -> str | None:
        found = self._records.get(record_id)
        return found[1] if found else None
