"""Resolved values, written back as a CASE/UCO graph and validated.

One graph per record, built with the pinned SDK's `CASEGraph` and checked by
the same gate as the SDK's own record graphs (`encoding.sdk.gate`): SHACL
plus the closed-world concept check.

Only resolved values go in, as typed literals and closed-vocabulary labels:
a term, an amount, a citation, a docket number, a tag. People are in it as
numbered nodes with a role. The graph holds no passage from the record and no
name, and it is checked against the names found in the record's text before
it is kept.

    record          uco-observable:ObservableObject, tagged with the record id, the
                    case id, and every settled label (stage, scheme, channel, ...)
    case            case-investigation:Investigation with legalproc:caseIdentifier
    defendant       uco-identity:Person named "Defendant 1", "Defendant 2", ... with a
                    uco-role:Role. With one defendant, legalproc:chargedWith links the
                    person to the charges and each term is linked to the person
    agency          uco-identity:Organization: the publishing office or the court
    statute         legalproc:FederalCharge for a cited section in the statute table
    term            legalproc:Sentence (imposed, supervised release, probation, prior)
                    legalproc:PotentialPenalty (exposure)
    amount          legalproc:RestitutionOrder, ForfeitureOrder, Sentence (fine),
                    PretrialReleaseCondition (bail), PotentialPenalty (fine exposure)
                    uco-core:Assertion for a loss, proceeds, or another amount the
                    legal-process vocabulary has no class for
    victim count    uco-core:Assertion with legalproc:reportedVictimCount
    provenance      one case-investigation:InvestigativeAction naming the engine,
                    its rule set, the record it read, and the nodes it produced

Where each value was read is in `annotations.jsonld` beside the graph: one
Web Annotation per node and span, as character positions into the record text.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from encoding import corpus, redact, sdk
from extraction import ENGINE_VERSION, cases, names as name_rules, pipeline, resolve, statutes, store

GRAPHS = store.EXTRACTED / "graphs"
TOOL_NAME = "casenoesis-extraction"

_SENTENCE_KIND = {"imposed": "custodial", "prior": "custodial", "supervised_release": "supervised-release", "probation": "probation"}
_TAG_FIELDS = ("stage", "document_type", "offense", "scheme", "channel", "platform")


def _iri(*parts: Any) -> str:
    from case_uco import deterministic_uuid

    return f"urn:uuid:{deterministic_uuid('casenoesis-extraction', *map(str, parts))}"


def _extension_context() -> dict[str, str]:
    manifest = sdk.extension_manifests().get("legalproc") or {}
    return dict(manifest.get("namespaces") or {})


def _decimal(value: float) -> dict[str, str]:
    return {"@type": "xsd:decimal", "@value": f"{value:.2f}"}


def _evidence(final: dict[str, Any]) -> list[str]:
    return [f"resolution:{final['status']}", *(f"family:{family}" for family in final["families"])]


def graph_dir(record_id: str) -> Path:
    return GRAPHS / record_id


def _finals(db: sqlite3.Connection, record_id: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in db.execute(
        "SELECT field, body FROM resolutions WHERE record_id = ? AND rule_set_version = ?",
        (record_id, resolve.RULE_SET_VERSION),
    ):
        out[row["field"]] = json.loads(row["body"])["finals"]
    return out


def _one_per_term(finals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One node per role and length. "87 months" and "87-month" are one term
    written two ways: keep the better-supported wording and all the spans."""
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for final in finals:
        extras = final["extras"]
        key = (final["role"], "life" if extras.get("life") else extras.get("months", final["value"]))
        kept = merged.get(key)
        if kept is None:
            merged[key] = {**final, "spans": list(final["spans"]), "families": list(final["families"])}
            continue
        if final["status"] == "agreed" and kept["status"] != "agreed":
            kept["value"], kept["status"] = final["value"], final["status"]
        kept["spans"] += [span for span in final["spans"] if span not in kept["spans"]]
        kept["families"] = sorted(set(kept["families"]) | set(final["families"]))
    return list(merged.values())


def build_record_graph(db: sqlite3.Connection, record_id: str, entry: dict[str, Any], text: str) -> dict[str, Any]:
    """Write `graph.jsonld` and `annotations.jsonld` for one record. Returns a status row."""
    from case_uco import CASEGraph

    record = db.execute("SELECT * FROM records WHERE record_id = ?", (record_id,)).fetchone()
    finals = _finals(db, record_id)
    case_id = cases.case_id_of(db, record_id) or "case-" + hashlib.sha256(record_id.encode()).hexdigest()[:16]
    agency = str(entry.get("agency") or "").strip()
    # The office name comes from the collector, not the text. A place in it
    # ("USAO - Rhode Island") that a name rule also matched is not a person.
    found_names = {name for name in name_rules.find_names(text) if name.lower() not in agency.lower()}
    url_tokens = {t.lower() for t in name_rules.name_tokens(found_names) if " " not in t and len(t) >= 4}

    graph = CASEGraph(kb_prefix="urn:uuid:")
    # Declare the legal-process extension's prefix, read from the pinned SDK.
    graph.load(json.dumps({"@context": _extension_context(), "@graph": []}))
    annotations: list[dict[str, Any]] = []
    produced: list[str] = []
    text_source = f"urn:sha256:{record['text_sha256']}"

    def anchor(node_id: str, final: dict[str, Any]) -> None:
        for start, end in final["spans"]:
            annotations.append({
                "id": _iri("anchor", node_id, start, end), "type": "Annotation", "body": node_id,
                "target": {"source": text_source, "selector": [{"type": "TextPositionSelector", "start": start, "end": end}]},
            })

    def node(key: tuple[Any, ...], types: str, properties: dict[str, Any], final: dict[str, Any]) -> str:
        node_id = _iri(record_id, *key)
        tags = [f"noesis-record:{record_id}", *_evidence(final), *properties.pop("tags", [])]
        graph.upsert_node(node_id, types=[types], properties={**properties, "uco-core:tag": tags})
        produced.append(node_id)
        anchor(node_id, final)
        return node_id

    # The record itself, tagged with every settled label.
    record_node = _iri("record", record_id)
    tags = [f"noesis-record:{record_id}", f"noesis-case:{case_id}", f"kind:{record['kind']}"]
    tags += [f"domain:{domain}" for domain in json.loads(record["domains"])]
    for field_name in _TAG_FIELDS:
        for final in finals.get(field_name, []):
            tags.append(f"{field_name}:{final['value']}")
            anchor(record_node, final)
    for final in finals.get("date", []):
        # A date with no clock time is not written as a timestamp.
        tags.append(f"date-{final['role']}:{final['value']}")
        anchor(record_node, final)
    for final in finals.get("statute", []):
        tags.append(f"statute-cited:{final['value']}")
    properties: dict[str, Any] = {
        "uco-core:name": f"Record {record_id}",
        "uco-core:description": [f"A public {record['kind']} record read by the CaseNoesis extraction engine."],
        "uco-core:tag": tags,
    }
    digest = entry.get("sha256")
    if digest:
        properties["uco-core:hasFacet"] = [{
            "@id": _iri("content", record_id), "@type": "uco-observable:ContentDataFacet",
            "uco-observable:hash": [{
                "@id": _iri("hash", record_id), "@type": "uco-types:Hash", "uco-types:hashMethod": "SHA256",
                "uco-types:hashValue": {"@type": "xsd:hexBinary", "@value": str(digest).upper()},
            }],
        }]
    graph.upsert_node(record_node, types=["uco-observable:ObservableObject"], properties=properties)

    url = entry.get("source_url")
    if url:
        safe, cut = redact._safe_url(str(url), url_tokens)
        url_node = _iri("url", record_id)
        url_properties: dict[str, Any] = {
            "uco-core:name": f"Source address for {record_id}",
            "uco-core:hasFacet": [{"@id": _iri("url-facet", record_id), "@type": "uco-observable:URLFacet", "uco-observable:fullValue": safe}],
        }
        if cut:
            url_properties["uco-core:tag"] = [f"source-url-sha256:{cut}"]
            url_properties["uco-core:description"] = [
                "The address path is withheld because it spells a person's name. The full address is in the local index."
            ]
        graph.upsert_node(url_node, types=["uco-observable:URL"], properties=url_properties)

    for final in finals.get("statute", []):
        extras = final["extras"]
        entry_ = statutes.lookup(extras.get("title", "0"), extras.get("section", ""))
        if entry_ is None:
            continue
        node(("statute", final["value"]), "legalproc:FederalCharge", {
            "uco-core:name": f"Offense statute cited: {final['value']}",
            "legalproc:statuteCitation": final["value"],
            "legalproc:jurisdictionKind": "federal",
            "tags": [f"offense:{entry_.label}"],
        }, final)

    for final in _one_per_term(finals.get("sentence", [])):
        role, extras = final["role"], final["extras"]
        months = extras.get("months")
        term_tags = [f"term-months:{months:g}"] if months is not None else ["term:life"] if extras.get("life") else []
        if role in _SENTENCE_KIND:
            node(("sentence", role, final["value"]), "legalproc:Sentence", {
                "uco-core:name": f"Term {role.replace('_', ' ')}: {final['value']}",
                "legalproc:sentenceStatus": "imposed",
                "legalproc:sentenceKind": _SENTENCE_KIND[role],
                "legalproc:sentenceTerm": final["value"],
                "legalproc:outcomeScope": "prior-history" if role == "prior" else "current-case",
                "tags": term_tags,
            }, final)
        elif role == "exposure":
            bound = "mandatory-minimum" if extras.get("bound") == "minimum" else "statutory-maximum"
            node(("penalty", final["value"], bound), "legalproc:PotentialPenalty", {
                "uco-core:name": f"Potential penalty ({bound}): {final['value']}",
                "legalproc:potentialPenaltyKind": bound,
                "legalproc:outcomeScope": "current-case",
                "tags": term_tags,
            }, final)

    for final in finals.get("money", []):
        role, amount = final["role"], float(final["value"])
        money = {"legalproc:monetaryAmount": _decimal(amount), "legalproc:currencyCode": "USD"}
        label = f"USD {amount:,.2f}"
        key = ("money", role, f"{amount:.2f}")
        if role == "restitution":
            node(key, "legalproc:RestitutionOrder", {"uco-core:name": f"Restitution: {label}", **money}, final)
        elif role == "forfeiture":
            node(key, "legalproc:ForfeitureOrder", {"uco-core:name": f"Forfeiture: {label}", **money}, final)
        elif role == "fine":
            node(key, "legalproc:Sentence", {
                "uco-core:name": f"Fine: {label}", "legalproc:sentenceStatus": "imposed",
                "legalproc:sentenceKind": "fine-as-sentence", "legalproc:outcomeScope": "current-case", **money,
            }, final)
        elif role == "exposure_fine":
            node(key, "legalproc:PotentialPenalty", {
                "uco-core:name": f"Potential fine (statutory-maximum): {label}",
                "legalproc:potentialPenaltyKind": "statutory-maximum", "legalproc:outcomeScope": "current-case", **money,
            }, final)
        elif role == "bail":
            node(key, "legalproc:PretrialReleaseCondition", {
                "uco-core:name": f"Bail or bond: {label}", "legalproc:releaseConditionKind": "bail", **money,
            }, final)
        else:
            node(key, "uco-core:Assertion", {
                "uco-core:name": f"Reported {role.replace('_', ' ')}: {label}",
                "uco-core:statement": [f"The record reports a {role.replace('_', ' ')} amount of {label}."],
                "tags": [f"money-role:{role}"], **money,
            }, final)

    for final in finals.get("victim_count", []):
        count = int(final["value"])
        node(("victims", count), "uco-core:Assertion", {
            "uco-core:name": f"Reported victim count: {count}",
            "uco-core:statement": [f"The record reports {'at least ' if final['extras'].get('lower_bound') else ''}{count} victims."],
            "legalproc:victimFactStatus": "reported",
            "legalproc:reportedVictimCount": {"@type": "xsd:nonNegativeInteger", "@value": str(count)},
        }, final)

    # People: a node per defendant, numbered, with a role. No name.
    charges = [n for n in produced if graph.get(n)["@type"] == "legalproc:FederalCharge"]
    terms = [n for n in produced if graph.get(n)["@type"] == "legalproc:Sentence"]
    defendants = finals.get("party", [])
    people: list[str] = []
    if defendants:
        role_node = _iri(record_id, "role", "defendant")
        graph.upsert_node(role_node, types=["uco-role:Role"], properties={
            "uco-core:name": "Defendant",
            "uco-core:description": ["The role of a person the record reports as charged, convicted, or sentenced."],
            "uco-core:tag": [f"noesis-record:{record_id}"],
        })
        produced.append(role_node)
        for number, final in enumerate(defendants, start=1):
            person = node(("party", final["value"]), "uco-identity:Person", {
                "uco-core:name": f"Defendant {number}",
                "uco-core:description": ["A defendant the record names. The name is withheld; the character span is in annotations.jsonld."],
                "tags": ["party-role:defendant"],
            }, final)
            people.append(person)
            produced.append(graph.create_relationship(person, role_node, "Has_Role")["@id"])
    if len(people) == 1:
        # With one defendant, the charges and terms in the record are that
        # person's. With several, the record does not say whose is whose.
        if charges:
            graph.add_property(people[0], "legalproc:chargedWith", [{"@id": charge} for charge in charges])
        for term in terms:
            produced.append(graph.create_relationship(
                term, people[0], "Applies_To",
                description="The record names one defendant, so its terms are linked to that defendant.",
            )["@id"])
    if len(charges) == 1:
        for term in terms:
            graph.add_property(term, "legalproc:appliesTo", [{"@id": charges[0]}])

    case_node = _iri("case", case_id)
    case_properties: dict[str, Any] = {
        "uco-core:name": f"Case {case_id}",
        "uco-core:tag": [f"noesis-case:{case_id}"],
        "uco-core:object": [{"@id": record_node}, *({"@id": node_id} for node_id in produced)],
    }
    identifiers = [final["value"] for final in finals.get("case_number", [])]
    if identifiers:
        case_properties["legalproc:caseIdentifier"] = identifiers
        for final in finals["case_number"]:
            anchor(case_node, final)
    graph.upsert_node(case_node, types=["case-investigation:Investigation"], properties=case_properties)

    # The office that issued the release, or the court the filing is in.
    if agency and not name_rules.is_name(agency):
        agency_node = _iri("agency", agency)
        graph.upsert_node(agency_node, types=["uco-identity:Organization"], properties={"uco-core:name": agency})
        graph.create_relationship(
            agency_node, case_node, "Associated_With",
            description="The office that published the record." if record["kind"] == "press" else "The court the filing was made in.",
        )

    tool_node = _iri("tool", ENGINE_VERSION)
    graph.upsert_node(tool_node, types=["uco-tool:Tool"], properties={"uco-core:name": TOOL_NAME, "uco-tool:version": ENGINE_VERSION})
    action: dict[str, Any] = {
        "uco-core:name": f"Extraction and resolution of {record_id}",
        "uco-core:description": [
            f"Readers wrote span-anchored assertions; rule set {resolve.RULE_SET_VERSION} settled them by evidence family. "
            "Only settled values are in this graph."
        ],
        "uco-action:actionStatus": "Success",
        "uco-action:object": [{"@id": record_node}],
        "uco-action:instrument": [{"@id": tool_node}],
        "uco-core:tag": [f"run:{record['run_id']}", f"rule-set:{resolve.RULE_SET_VERSION}"],
    }
    if produced:
        action["uco-action:result"] = [{"@id": node_id} for node_id in produced]
    graph.upsert_node(_iri("action", record_id), types=["case-investigation:InvestigativeAction"], properties=action)

    folder = graph_dir(record_id)
    folder.mkdir(parents=True, exist_ok=True)
    graph_path = folder / "graph.jsonld"
    graph.write(str(graph_path))
    (folder / "annotations.jsonld").write_text(json.dumps(annotations, indent=2) + "\n", encoding="utf-8")
    serialized = graph_path.read_text(encoding="utf-8")
    leaked = name_rules.leaks(serialized, found_names)
    return {
        "record_id": record_id,
        "graph_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "nodes": len(json.loads(serialized)["@graph"]),
        "name_check": "pass" if not leaked else "fail",
    }


_INDEX: dict[str, dict[str, Any]] = {}


def _index() -> dict[str, dict[str, Any]]:
    """The record index, read once per process."""
    if not _INDEX:
        _INDEX.update({entry["record_id"]: entry for entry in corpus.load_index()})
    return _INDEX


def _build_one(args: tuple[str, bool]) -> dict[str, Any]:
    record_id, gate = args
    db = store.connect()
    try:
        entry = _index().get(record_id)
        loaded = pipeline.load_doc(entry) if entry else None
        if loaded is None:
            return {"record_id": record_id, "error": "no_text"}
        status = build_record_graph(db, record_id, entry, loaded[0].text)
        if status["name_check"] != "pass":
            # A graph that names a person is not kept.
            (graph_dir(record_id) / "graph.jsonld").unlink()
            return {**status, "error": "name_check_failed"}
        if gate:
            path = graph_dir(record_id) / "graph.jsonld"
            receipt = sdk.gate(path)
            sdk.write_receipt(path, receipt)
            status["conforms"] = receipt["conforms"]
            if not receipt["conforms"]:
                status["messages"] = receipt.get("messages") or receipt.get("verification_errors")
        return status
    except Exception as error:  # report it, keep the batch going
        return {"record_id": record_id, "error": f"{type(error).__name__}: {error}"}
    finally:
        db.close()


def build(record_ids: list[str] | None = None, *, kind: str | None = None, gate: bool = False,
          workers: int = 1, force: bool = False, limit: int = 0) -> dict[str, Any]:
    """Write graphs for read records. A record whose graph exists is skipped unless `force`."""
    from concurrent.futures import ProcessPoolExecutor

    db = store.connect()
    ids = record_ids or store.record_ids(db, kind=kind)
    if not force:
        done = {row[0] for row in db.execute("SELECT record_id FROM graphs WHERE conforms IS NOT NULL OR ? = 0", (int(gate),))}
        ids = [record_id for record_id in ids if record_id not in done]
    if limit:
        ids = ids[:limit]
    jobs = [(record_id, gate) for record_id in ids]
    if workers > 1 and jobs:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_build_one, jobs, chunksize=8))
    else:
        rows = [_build_one(job) for job in jobs]
    errors: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    for row in rows:
        if "error" in row:
            errors[row["error"][:80]] = errors.get(row["error"][:80], 0) + 1
            continue
        db.execute(
            "INSERT OR REPLACE INTO graphs (record_id, graph_sha256, nodes, name_check, conforms, built_at) VALUES (?,?,?,?,?,?)",
            (row["record_id"], row["graph_sha256"], row["nodes"], row["name_check"],
             None if "conforms" not in row else int(row["conforms"]), store.now()),
        )
        if row.get("conforms") is False and len(failures) < 5:
            failures.append({"record_id": row["record_id"], "messages": row.get("messages")})
    db.commit()
    built = [row for row in rows if "error" not in row]
    summary: dict[str, Any] = {"built": len(built), "errors": errors}
    if gate:
        summary["conforming"] = sum(1 for row in built if row.get("conforms"))
        if failures:
            summary["not_conforming"] = failures
    return summary
