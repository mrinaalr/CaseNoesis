"""No names in graphs.

The SDK's document processor writes what it reads: a `Person` node per name,
narrative text windows on events, e-mail addresses, file names. The source
text is public record and stays on this machine beside the graph. The graph
is derived data, and derived data carries no person's name. People stay in
it; their names do not.

`redact_record` rewrites one record's `graph.jsonld` and `annotations.jsonld`
in place, before the graph is validated:

1. Every `Person` node stays, with its relationships, and loses its name. It
   is renamed `Person 1`, `Person 2`, ... in order of appearance. The graph
   still says a person is there and what they are linked to.
2. Names are collected from those nodes and from the text (case captions,
   "Name, 45, of City", honorifics; see `extraction/names.py`) and masked in
   every string left in the graph.
3. Passages copied out of the record are withheld: the narrative window on
   each event, and any extracted string longer than 60 characters (the
   opening of the document on the source node). Character spans stay in the
   annotations, so a passage can still be read locally.
4. The local part of every e-mail address is replaced. The domain stays.
5. A CourtListener address loses its trailing slug, which repeats the case
   caption. Any other address whose path spells a name is cut to its host and
   tagged with the SHA-256 of the full address; the full address stays in the
   local index under the record id.
6. An annotation on a person keeps its character position and loses its
   quote. Other quotes are masked; long quotes are dropped and keep their
   positions.

Then it checks: no collected full name may occur anywhere in either file.
The result of that check is written to `record.json`. Name-finding is
rule-based and tuned to over-mask; a name no rule recognizes can survive.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from extraction import names as name_rules

REDACTION_VERSION = "redact_1.0"
WITHHELD = "Text window withheld. The character span is in annotations.jsonld."
MAX_QUOTE = 60
PERSON_NOTE = "A person named in the record. The name is withheld; the character span is in annotations.jsonld."
_PSEUDONYM = re.compile(r"Person \d+")

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")
_COURTLISTENER = re.compile(r"^(https?://www\.courtlistener\.com/(?:docket|recap)/[\w./-]*?\d+/)(?:[a-z0-9]+(?:-[a-z0-9]+)+/?)$")
_URL_KEYS = ("uco-observable:fullValue",)
# Properties that hold text copied out of the record. A short one is a token
# (a citation, an amount). A long one is a passage, and is withheld.
_TEXT_KEYS = ("uco-observable:stringValue",)


def _types(node: dict[str, Any]) -> list[str]:
    value = node.get("@type")
    return value if isinstance(value, list) else [value] if value else []


def _text_of(folder: Path) -> str:
    path = folder / "extracted-content.json"
    if not path.is_file():
        return ""
    content = json.loads(path.read_text(encoding="utf-8")).get("content") or {}
    return "\n\n".join(str(section.get("text") or "") for section in content.get("sections") or [])


def _safe_url(url: str, tokens: set[str]) -> tuple[str, str | None]:
    """The address to write, and the hash to tag it with when it was cut."""
    trimmed = _COURTLISTENER.match(url)
    if trimmed:
        url = trimmed.group(1)
    try:
        parts = urlsplit(url)
    except ValueError:  # not an address a parser accepts; nothing to cut
        return url, None
    words = {word for word in re.split(r"[^a-z]+", (parts.path + "?" + parts.query).lower()) if len(word) >= 4}
    if words & tokens:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return f"{parts.scheme}://{parts.netloc}/", digest
    return url, None


def redact_graph(graph: dict[str, Any], annotations: Any, text: str) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    nodes: list[dict[str, Any]] = graph.get("@graph", [])
    people = [node["@id"] for node in nodes if "uco-identity:Person" in _types(node)]
    known = [
        node.get("uco-core:name") for node in nodes
        if node.get("@id") in people and not _PSEUDONYM.fullmatch(str(node.get("uco-core:name")))
    ]
    found = name_rules.find_names(text, [name for name in known if isinstance(name, str)])
    pattern = name_rules.mask_pattern(found)
    url_tokens = {token.lower() for token in name_rules.name_tokens(found) if " " not in token and len(token) >= 4}
    # A person stays in the graph as a node with its relationships. Only the
    # name goes: the node is renamed by its order of appearance.
    pseudonym = {node_id: f"Person {number}" for number, node_id in enumerate(people, start=1)}
    removed: set[str] = set()

    changed = 0
    cut_urls = 0

    cuts: list[str] = []  # hashes of addresses cut inside the node being cleaned

    def clean(value: Any, key: str | None) -> Any:
        nonlocal changed, cut_urls
        if isinstance(value, dict):
            if set(value) == {"@id"} and value["@id"] in removed:
                return None
            out = {}
            for name, item in value.items():
                cleaned = clean(item, name)
                if cleaned is None and item is not None:
                    continue
                out[name] = cleaned
            return out
        if isinstance(value, list):
            return [item for item in (clean(item, key) for item in value) if item is not None]
        if not isinstance(value, str) or key in ("@id", "@type", "@value"):
            return value  # identifiers and typed literals (a hash, a time, a size) are not prose
        if key in _TEXT_KEYS and len(value) > MAX_QUOTE and value != WITHHELD:
            changed += 1
            return WITHHELD
        if key in _URL_KEYS and value.startswith(("http://", "https://")):
            safe, digest = _safe_url(value, url_tokens)
            if digest:
                cut_urls += 1
                cuts.append(digest)
            new = safe
        else:
            new = name_rules.scrub(_EMAIL.sub(r"[redacted]@\1", value), pattern)
        changed += new != value
        return new

    kept: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("@id") in removed:
            continue
        if node.get("@id") in pseudonym:
            renamed = node.get("uco-core:name") != pseudonym[node["@id"]]
            node = {**node, "uco-core:name": pseudonym[node["@id"]], "uco-core:description": PERSON_NOTE}
            changed += renamed
        if "uco-core:Event" in _types(node) and node.get("uco-core:description") not in (None, WITHHELD):
            node = {**node, "uco-core:description": WITHHELD}
            changed += 1
        cuts.clear()
        cleaned = clean(node, None)
        # A cut address: tag the node that holds it with the hash.
        digests = [digest for digest in cuts if f"source-url-sha256:{digest}" not in str(cleaned.get("uco-core:tag"))]
        if digests:
            tags = cleaned.get("uco-core:tag") or []
            tags = tags if isinstance(tags, list) else [tags]
            cleaned["uco-core:tag"] = [*tags, *(f"source-url-sha256:{digest}" for digest in digests)]
            description = cleaned.get("uco-core:description") or []
            description = description if isinstance(description, list) else [description]
            cleaned["uco-core:description"] = [
                *description,
                "The address path is withheld because it spells a person's name. The full address is in the local index.",
            ]
        kept.append(cleaned)
    graph = {**graph, "@graph": kept}

    dropped_annotations = 0
    if annotations is not None:
        items = annotations if isinstance(annotations, list) else annotations.get("@graph") or annotations.get("items") or []
        cleaned_items = []
        for item in items:
            if isinstance(item, dict) and item.get("body") in removed:
                dropped_annotations += 1
                continue
            if isinstance(item, dict) and isinstance(item.get("target"), dict):
                selectors = []
                for selector in item["target"].get("selector") or []:
                    if selector.get("type") == "TextQuoteSelector":
                        exact = str(selector.get("exact") or "")
                        if len(exact) > MAX_QUOTE or item.get("body") in pseudonym:
                            continue
                        selector = {**selector, "exact": name_rules.scrub(_EMAIL.sub(r"[redacted]@\1", exact), pattern)}
                    selectors.append(selector)
                item = {**item, "target": {**item["target"], "selector": selectors}}
            cleaned_items.append(item)
        if isinstance(annotations, list):
            annotations = cleaned_items
        elif "@graph" in annotations:
            annotations = {**annotations, "@graph": cleaned_items}
        else:
            annotations = {**annotations, "items": cleaned_items}

    serialized = json.dumps(graph, ensure_ascii=False) + json.dumps(annotations, ensure_ascii=False)
    leaks = name_rules.leaks(serialized, found)
    report = {
        "version": REDACTION_VERSION,
        "people_renamed": len(people),
        "names_masked": len(found),
        "strings_changed": changed,
        # A count of the graph as it now stands, so a second pass reports the same.
        "addresses_cut": serialized.count("source-url-sha256:"),
        "name_check": "pass" if not leaks else "fail",
        "names_remaining": len(leaks),
    }
    return graph, annotations, report


def redact_record(folder: Path) -> dict[str, Any]:
    """Redact one encoded record in place. Running it twice changes nothing."""
    graph_path, annotations_path = folder / "graph.jsonld", folder / "annotations.jsonld"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    annotations = json.loads(annotations_path.read_text(encoding="utf-8")) if annotations_path.is_file() else None
    graph, annotations, report = redact_graph(graph, annotations, _text_of(folder))
    graph_path.write_text(json.dumps(graph, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    if annotations is not None:
        annotations_path.write_text(json.dumps(annotations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
