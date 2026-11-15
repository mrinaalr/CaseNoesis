"""The pinned SDK's document processor, as a reader.

`encoding/` already ran the processor and kept its Web Annotation anchors:
a character span and an exact quote for every entity it found. This reader
turns those anchors into assertions. The SDK names things and does not say
what they are for, so on a mention field it abstains on the role: it confirms
that a statute, an amount, a date, or a docket number is there, and the gate
re-reads the value from the text at that span. On `channel` and
`document_type` it votes for a label.

Nothing here calls the SDK. A record that was not encoded has no anchors and
this reader says nothing about it.
"""

from __future__ import annotations

from typing import Any

from extraction.readers import Doc, assertion, register_reader

VERSION = "sdk_anchors_1.0"
METHOD = "sdk_processor"

# Prefix of the SDK node name -> (field, role)
_BY_LABEL = (
    ("Statute ", "statute", "cited"),
    ("Amount ", "money", None),
    ("Federal case ", "case_number", "cited"),
    ("Date ", "date", None),
)
_CRYPTO = ("Bitcoin address", "Ethereum address", "Tron address", "Hosted wallet", "Cryptocurrency")


def read(doc: Doc) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for anchor in doc.sdk_anchors:
        label, start, end = anchor.get("label") or "", anchor["start"], anchor["end"]
        sdk_class = anchor.get("class")
        events = anchor.get("event_types") or []
        for prefix, field_name, role in _BY_LABEL:
            if label.startswith(prefix):
                out.append(assertion(field_name, None, role, METHOD, VERSION, 0.8, start, end, sdk_class=sdk_class))
                break
        else:
            if sdk_class == "uco-identity:Person":
                # The SDK says a person is named here and nothing about who.
                out.append(assertion("party", None, None, METHOD, VERSION, 0.8, start, end, sdk_class=sdk_class))
            elif label.startswith(_CRYPTO) or sdk_class == "cryptoinv:VirtualAssetServiceProvider":
                out.append(assertion("channel", "cryptocurrency", "present", METHOD, VERSION, 0.8, start, end, sdk_class=sdk_class))
            elif "indictment count reference" in events:
                out.append(assertion("document_type", "indictment", "present", METHOD, VERSION, 0.7, start, end, sdk_class=sdk_class))
            elif "criminal charge" in events:
                out.append(assertion("stage", "charged", "present", METHOD, VERSION, 0.6, start, end, sdk_class=sdk_class))
    return out


register_reader("sdk", ("press", "court", "reference"), read, version=VERSION, order=40)
