"""Statute lookup: what a citation means, from the statute table.

Two claims, both anchored on text:

- A cited section in the table names an offense. The span is the citation.
- A term with no cue of its own, in a record that cites a statute whose
  mandatory minimum or statutory maximum is exactly that term, is exposure,
  not a sentence. The span is the term.
"""

from __future__ import annotations

from typing import Any

from extraction import fields, spans as sp, statutes
from extraction.readers import Doc, assertion, register_reader

VERSION = statutes.TABLE_VERSION
METHOD = "statute_table"


def read(doc: Doc) -> list[dict[str, Any]]:
    text = doc.text
    out: list[dict[str, Any]] = []
    cited: dict[tuple[str, str], statutes.Statute] = {}
    for start, end, value, extras in fields.iter_statute(text):
        entry = statutes.lookup(extras["title"], extras["section"])
        if entry is None:
            continue
        cited.setdefault((extras["title"], extras["section"]), entry)
        out.append(assertion("offense", entry.label, "present", METHOD, VERSION, 0.8, start, end, statute=value))
    if not cited:
        return out
    for start, end, value, extras in fields.iter_duration(text):
        months = extras.get("months")
        if months is None or sp.sentence_kind(text, start, end) != "unknown":
            continue
        for (title, section), entry in cited.items():
            bound = "maximum" if months == entry.max_months else "minimum" if months == entry.min_months else None
            if bound:
                out.append(assertion(
                    "sentence", value, "exposure", METHOD, VERSION, 0.8, start, end,
                    statute=f"{title} U.S.C. § {section}", bound=bound, months=months,
                ))
                break
    return out


register_reader("lookup", ("press", "court", "reference"), read, version=VERSION, order=30)
