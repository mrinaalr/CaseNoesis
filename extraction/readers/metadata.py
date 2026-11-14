"""Collector metadata: what the collector recorded about the record.

These claims have no span, so none of them can create a value. Each one
attaches to a mention another reader found in the text with the same value,
where it corroborates or contests (resolution rule 7). A publication date the
text never states stays in the index and out of the resolved fields.
"""

from __future__ import annotations

from typing import Any

from extraction import fields, profiles
from extraction.readers import Doc, assertion, register_reader

VERSION = "collector_index_1.1"
METHOD = "collector_metadata"

# The collector's press stage, set from the release title when it was collected.
_STAGE = {
    "sentenced": ("sentenced",),
    "plea_or_convicted": ("plea", "convicted"),
    "early": ("charged", "arrested"),
}


def read(doc: Doc) -> list[dict[str, Any]]:
    entry = doc.entry
    out: list[dict[str, Any]] = []
    date = str(entry.get("pub_date") or "")[:10]
    if len(date) == 10:
        # A release dated the day of the sentencing states one date with two
        # meanings. The publication date stays in the index and makes no claim
        # about a date in the text. A filing date does: it is what "Filed" says.
        role = "filed" if doc.kind == "court" else None
        if role:
            out.append(assertion("date", date, role, METHOD, VERSION, 0.9, None, None, source="pub_date"))
    for start, end, value, extras in fields.iter_case_number(str(entry.get("docket_number") or "")):
        out.append(assertion("case_number", value, "cited", METHOD, VERSION, 0.9, None, None, source="docket_number"))
    for label in _STAGE.get(str(entry.get("stage") or ""), ()):
        out.append(assertion("stage", label, "present", METHOD, VERSION, 0.8, None, None, source="stage"))
    scheme = profiles.bucket_label(doc.domain, entry.get("bucket"))
    if scheme:
        out.append(assertion("scheme", scheme, "present", METHOD, VERSION, 0.7, None, None, source="bucket"))
    # What the collector searched for when it fetched this filing: the docket's own name for it.
    filed_as = {"statement_of_offense": "factual_basis", "factual_basis": "factual_basis", "complaint_affidavit": "complaint"}.get(
        str(entry.get("collected_as") or ""))
    if doc.kind == "court" and filed_as:
        out.append(assertion("document_type", filed_as, "present", METHOD, VERSION, 0.8, None, None, source="collected_as"))
    if doc.kind == "court" and "transcripts" in (entry.get("domains") or [entry.get("domain")]):
        out.append(assertion("document_type", "transcript", "present", METHOD, VERSION, 0.8, None, None, source="folder"))
    return out


register_reader("metadata", ("press", "court", "reference"), read, version=VERSION, order=50)
