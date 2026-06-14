#!/usr/bin/env python3
"""Build and validate CAC knowledge graphs from PACER facts files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

PACER_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = PACER_DIR / "facts.txt"
SDK_ROOT = PACER_DIR.parents[2] / "CASE-UCO-SDK"
CASE_VALIDATE = SDK_ROOT / ".venv/bin/case_validate"

CHARGE_LABELS: dict[str, str] = {
    "conspiracy_to_produce_csam": "Conspiracy to produce CSAM",
    "conspiracy_receive_distribute_csam": "Conspiracy to receive and distribute CSAM",
    "child_exploitation_enterprise": "Child exploitation enterprise",
    "production_of_csam": "Production of CSAM",
    "receipt_distribution_csam": "Receipt and distribution of CSAM",
    "cyberstalking": "Cyberstalking",
    "aggravated_identity_theft": "Aggravated identity theft",
    "wire_fraud": "Wire fraud",
    "coercion_enticement_minor": "Coercion and enticement of a minor",
    "travel_intent_illicit_sexual_conduct": "Travel with intent to engage in illicit sexual conduct",
    "sexual_exploitation_of_child": "Sexual exploitation of a child",
    "attempted_receipt_csam": "Attempted receipt of CSAM",
}

COERCION_LABELS: dict[str, str] = {
    "threat_of_exposure": "threat of exposure",
    "quota_demand": "quota demands",
    "false_promise_of_deletion": "false promise of deletion",
    "victim_recruitment": "victim recruitment",
    "impersonation": "impersonation (posed as teen/influencer)",
    "directed_production": "directed production of images",
    "flattery_as_inducement": "flattery as inducement",
    "persistent_solicitation": "persistent solicitation",
}

HARM_LABELS: dict[str, str] = {
    "self_harm_disclosure_present": "self-harm disclosure present",
    "victim_distress_documented": "victim distress documented",
    "victim_vulnerability_disclosed": "victim vulnerability disclosed",
    "self_harm_history_present": "self-harm history present",
}

PLATFORM_ROLE_LABELS: dict[str, str] = {
    "victim_identification": "victim identification",
    "coercion_primary": "primary coercion",
    "storage_and_distribution": "storage and distribution",
    "coercion_and_contact": "coercion and contact",
}

CURATED_ONTOLOGY_FILES = [
    "ontology/ontology/cacontology-core-spine.ttl",
    "ontology/ontology/cacontology-core-spine-shapes.ttl",
    "ontology/ontology/cacontology-core.ttl",
    "ontology/ontology/cacontology-core-shapes.ttl",
    "ontology/ontology/cacontology-extremist-enterprises.ttl",
    "ontology/ontology/cacontology-sextortion.ttl",
    "ontology/ontology/cacontology-platforms.ttl",
    "ontology/ontology/cacontology-legal-outcomes.ttl",
    "ontology/ontology/cacontology-usa-federal-law.ttl",
    "ontology/ontology/cacontology-multi-jurisdiction.ttl",
    "ontology/ontology/cacontology-asset-forfeiture.ttl",
    "ontology/ontology/cacontology-victim-impact.ttl",
    "ontology/ontology/cacontology-grooming.ttl",
    "ontology/ontology/cacontology-us-ncmec.ttl",
]

CONTEXT = {
    "@vocab": "http://example.org/local#",
    "case-investigation": "https://ontology.caseontology.org/case/investigation/",
    "kb": "http://example.org/kb/",
    "uco-action": "https://ontology.unifiedcyberontology.org/uco/action/",
    "uco-core": "https://ontology.unifiedcyberontology.org/uco/core/",
    "uco-identity": "https://ontology.unifiedcyberontology.org/uco/identity/",
    "uco-location": "https://ontology.unifiedcyberontology.org/uco/location/",
    "uco-observable": "https://ontology.unifiedcyberontology.org/uco/observable/",
    "uco-role": "https://ontology.unifiedcyberontology.org/uco/role/",
    "uco-victim": "https://ontology.unifiedcyberontology.org/uco/victim/",
    "cacontology": "https://cacontology.projectvic.org#",
    "cac-core": "https://cacontology.projectvic.org/core#",
    "cacontology-platforms": "https://cacontology.projectvic.org/platforms#",
    "cacontology-sextortion": "https://cacontology.projectvic.org/sextortion#",
    "cacontology-extremist-enterprises": "https://cacontology.projectvic.org/extremist-enterprises#",
    "cacontology-legal-outcomes": "https://cacontology.projectvic.org/legal-outcomes#",
    "cacontology-usa-federal-law": "https://cacontology.projectvic.org/usa-federal-law#",
    "cacontology-multi-jurisdiction": "https://cacontology.projectvic.org/multi-jurisdiction#",
    "cacontology-asset-forfeiture": "https://cacontology.projectvic.org/asset-forfeiture#",
    "cacontology-victim-impact": "https://cacontology.projectvic.org/victim-impact#",
    "cacontology-grooming": "https://cacontology.projectvic.org/grooming#",
    "cacontology-us-ncmec": "https://cacontology.projectvic.org/us/ncmec#",
    "cacontology-gufo": "https://cacontology.projectvic.org/gufo#",
    "gufo": "http://purl.org/nemo/gufo#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


def xs(value: str, typ: str) -> dict[str, str]:
    return {"@type": typ, "@value": value}


def desc(text: str) -> dict[str, str]:
    return xs(text, "xsd:string")


def slug_from_facts_path(facts_path: Path) -> str:
    stem = facts_path.stem
    if stem.endswith("_facts"):
        stem = stem[: -len("_facts")]
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", stem).strip("-").lower()
    if not slug:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", facts_path.parent.name).strip("-").lower()
    return slug


def output_path_for(facts_path: Path) -> Path:
    return facts_path.with_name(f"{slug_from_facts_path(facts_path)}.jsonld")


def case_token(case_number: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", case_number).strip("-").lower()


def load_facts(facts_path: Path) -> dict[str, Any]:
    text = facts_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{facts_path} must contain a YAML mapping at the top level")
    return data


def read_manifest(manifest_path: Path) -> list[Path]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    paths: list[Path] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line)
        paths.append(candidate if candidate.is_absolute() else manifest_path.parent / candidate)
    if not paths:
        raise ValueError(f"No facts files listed in {manifest_path}")
    return paths


def timeline_date(timeline: list[str], *keywords: str) -> str | None:
    for entry in timeline:
        for keyword in keywords:
            if keyword in entry.lower():
                match = re.match(r"(\d{4}-\d{2}-\d{2})", entry)
                if match:
                    return f"{match.group(1)}T00:00:00Z"
    return None


def charge_count_label(charge: dict[str, Any]) -> str:
    if "count" in charge:
        return str(charge["count"])
    if "counts" in charge:
        return str(charge["counts"])
    return "?"


def charge_display_label(charge: dict[str, Any]) -> str:
    raw = str(charge.get("label", "unknown_charge"))
    return CHARGE_LABELS.get(raw, raw.replace("_", " ").title())


def make_ids(slug: str, case_number: str) -> dict[str, str]:
    token = case_token(case_number)
    prefix = f"kb:{slug}-{token}"
    return {
        "bundle": f"{prefix}-bundle",
        "investigation": f"{prefix}-investigation",
        "prosecution": f"{prefix}-prosecution",
        "prosecutor": f"{prefix}-prosecutor",
        "pretrial_phase": f"{prefix}-pretrial-phase",
        "indictment": f"{prefix}-indictment",
        "enterprise": f"{prefix}-enterprise",
        "hierarchy": f"{prefix}-enterprise-hierarchy",
        "leadership_relator": f"{prefix}-leadership-relator",
        "exploitation_relator": f"{prefix}-exploitation-relator",
        "defendant": f"{prefix}-person-defendant",
        "subject": f"{prefix}-subject",
        "victim_role": f"{prefix}-victim-role",
        "sextortion": f"{prefix}-sextortion",
        "enticement": f"{prefix}-enticement",
        "grooming": f"{prefix}-grooming-solicitation",
        "conspiracy": f"{prefix}-conspiracy",
        "impersonation": f"{prefix}-impersonation",
        "recruitment": f"{prefix}-recruitment",
        "location_court": f"{prefix}-location-court",
        "location_abroad": f"{prefix}-location-abroad",
        "extradition": f"{prefix}-extradition",
        "forfeiture": f"{prefix}-forfeiture",
        "forfeiture_asset": f"{prefix}-forfeiture-asset",
        "impact": f"{prefix}-impact",
        "provenance": f"{prefix}-provenance",
        "provenance_action": f"{prefix}-provenance-action",
    }


def platform_id(slug: str, case_number: str, name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return f"kb:{slug}-{case_token(case_number)}-platform-{safe}"


def coconspirator_id(slug: str, case_number: str, index: int) -> str:
    return f"kb:{slug}-{case_token(case_number)}-co-conspirator-{index}"


def build_platform_node(
    *,
    platform: dict[str, Any],
    platform_iri: str,
    ban_evasion: dict[str, Any],
    basis_word: str = "Alleged",
) -> dict[str, Any]:
    name = str(platform["name"])
    role = PLATFORM_ROLE_LABELS.get(str(platform.get("role", "")), str(platform.get("role", "unknown")))
    affordances = ", ".join(str(a).replace("_", " ") for a in platform.get("affordances_abused", []))
    ban_note = ""
    name_lower = name.lower()
    if ban_evasion.get("observed"):
        if "snapchat" in name_lower and ban_evasion.get("snapchat_accounts_min"):
            ban_note = f" Minimum {ban_evasion['snapchat_accounts_min']} accounts recreated after bans."
        elif "instagram" in name_lower and ban_evasion.get("instagram_accounts_min"):
            ban_note = f" Minimum {ban_evasion['instagram_accounts_min']} accounts recreated after bans."

    node: dict[str, Any] = {
        "@id": platform_iri,
        "uco-core:name": name,
        "uco-core:description": desc(
            f"{basis_word} role: {role}. Affordances abused: {affordances}.{ban_note}"
        ),
    }
    if name_lower == "dropbox":
        node["@type"] = ["uco-observable:ObservableObject", "cacontology-platforms:FileHostingService"]
    else:
        node["@type"] = ["uco-observable:ObservableObject", "cacontology-platforms:SocialMediaPlatform"]
        node["cacontology-platforms:platformType"] = "social_network"
    return node


def build_charge_nodes(
    *,
    charges: list[dict[str, Any]],
    slug: str,
    case_number: str,
    evidentiary: str,
    doc_ref: str,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for charge in charges:
        count_label = charge_count_label(charge)
        label = charge_display_label(charge)
        statute = str(charge.get("statute", "unknown"))
        charge_iri = f"kb:{slug}-{case_token(case_number)}-charge-{count_label.replace('-', '_')}"
        disposition = charge.get("disposition")
        disposition_text = f" Disposition: {str(disposition).replace('_', ' ')}." if disposition else ""
        nodes.append(
            {
                "@id": charge_iri,
                "@type": "cacontology-legal-outcomes:FederalCharge",
                "uco-core:name": label,
                "rdfs:label": label,
                "uco-core:description": desc(
                    f"Count {count_label} under {statute}. "
                    f"Evidentiary basis: {evidentiary} ({doc_ref}).{disposition_text}"
                ),
            }
        )
    return nodes


def build_provenance_nodes(
    g: dict[str, str],
    *,
    provenance: dict[str, Any],
    doc_ref: str,
) -> list[dict[str, Any]]:
    provenance_source = str(provenance.get("source", "PACER"))
    return [
        {
            "@id": g["provenance_action"],
            "@type": "case-investigation:InvestigativeAction",
            "uco-core:name": f"{provenance_source} extraction",
            "rdfs:label": f"{provenance_source} extraction",
            "uco-core:description": desc(
                f"Extraction from {doc_ref}; retrieval={provenance.get('retrieval_method', 'unknown')}, "
                f"extraction={provenance.get('extraction_method', 'unknown')}, "
                f"human_reviewed={provenance.get('human_reviewed', False)}."
            ),
        },
        {
            "@id": g["provenance"],
            "@type": "case-investigation:ProvenanceRecord",
            "uco-core:name": f"Provenance — {doc_ref}",
            "uco-core:description": desc(f"Source: {provenance_source}, {doc_ref}."),
            "case-investigation:object": [{"@id": g["investigation"]}, {"@id": g["provenance_action"]}],
        },
    ]


def finalize_graph(nodes: list[dict[str, Any]], bundle_id: str) -> list[dict[str, Any]]:
    object_refs = [node["@id"] for node in nodes if node["@id"] != bundle_id]
    nodes[0]["uco-core:object"] = [{"@id": ref} for ref in object_refs]
    return nodes


def build_graph(facts: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    if "enterprise" in facts:
        return build_enterprise_graph(facts, slug)
    if "offense" in facts:
        return build_enticement_graph(facts, slug)
    raise ValueError("Facts file must contain either 'enterprise' or 'offense' section")


def build_enterprise_graph(facts: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    case = facts["case"]
    offender = facts.get("offender", {})
    enterprise = facts.get("enterprise", {})
    platforms = facts.get("platforms", [])
    ban_evasion = facts.get("ban_evasion", {})
    coercion = facts.get("coercion_mechanisms", [])
    harm = facts.get("victim_harm_indicators", [])
    charges = facts.get("charges", [])
    stacking = facts.get("charge_stacking_note", {})
    forfeiture = facts.get("forfeiture", {})
    timeline = facts.get("procedural_timeline", [])
    provenance = facts.get("provenance", {})

    case_number = str(case["case_number"])
    court = str(case.get("court", "Unknown court"))
    date_filed = str(case.get("date_filed", "unknown"))
    evidentiary = str(case.get("evidentiary_basis", "alleged"))
    offender_label = str(offender.get("label", "Defendant-1"))

    g = make_ids(slug, case_number)
    offense_begin = timeline_date(timeline, "complaint") or f"{date_filed}T00:00:00Z"
    indictment_date = timeline_date(timeline, "indictment") or f"{date_filed}T00:00:00Z"
    extradition_date = timeline_date(timeline, "extradited", "arrest")

    victim_count = int(enterprise.get("victim_count_approx", 1))
    co_conspirator_min = int(enterprise.get("co_conspirator_count_min", 2))
    co_conspirators = max(0, co_conspirator_min - 1)

    platform_iris: dict[str, str] = {}
    platform_nodes: list[dict[str, Any]] = []
    for platform in platforms:
        iri = platform_id(slug, case_number, str(platform["name"]))
        platform_iris[str(platform["name"]).lower()] = iri
        platform_nodes.append(
            build_platform_node(
                platform=platform,
                platform_iri=iri,
                ban_evasion=ban_evasion,
                basis_word=evidentiary.capitalize(),
            )
        )

    charge_nodes = build_charge_nodes(
        charges=charges,
        slug=slug,
        case_number=case_number,
        evidentiary=evidentiary,
        doc_ref=str(provenance.get("document", "source document")),
    )

    coercion_text = ", ".join(COERCION_LABELS.get(str(c), str(c).replace("_", " ")) for c in coercion)
    harm_text = "; ".join(HARM_LABELS.get(str(h), str(h).replace("_", " ")) for h in harm)

    stacking_text = ""
    if stacking.get("observed"):
        stacking_text = (
            f" Charge stacking observed: {str(stacking.get('description', '')).replace('_', ' ')}."
        )

    ban_text = ""
    if ban_evasion.get("observed"):
        ban_text = (
            f" Ban evasion alleged: {ban_evasion.get('snapchat_accounts_min', '?')}+ Snapchat accounts and "
            f"{ban_evasion.get('instagram_accounts_min', '?')}+ Instagram accounts recreated after platform enforcement."
        )

    doc_ref = str(provenance.get("document", "source document"))
    provenance_source = str(provenance.get("source", "PACER"))

    nodes: list[dict[str, Any]] = [
        {
            "@id": g["bundle"],
            "@type": "uco-core:Bundle",
            "uco-core:name": f"{court} {case_number} (CAC Enhanced)",
            "uco-core:description": desc(
                f"CAC knowledge graph for {case_number} derived from {doc_ref}. "
                f"All conduct is {evidentiary.upper()}. Coded extraction only — no victim-identifying detail."
            ),
        },
        {
            "@id": g["investigation"],
            "@type": ["case-investigation:Investigation", "cacontology:CACInvestigation"],
            "uco-core:name": f"U.S. v. {offender_label} — {case_number}",
            "uco-core:description": desc(
                f"Federal prosecution in {court}. Approximately {victim_count} alleged victims "
                f"(minimum age {enterprise.get('victim_min_age_alleged', 'unknown')})."
                f"{stacking_text}{ban_text}"
            ),
            "case-investigation:focus": [
                "Child Sexual Exploitation Enterprise",
                "Sextortion",
                "CSAM Production and Distribution",
                "Platform Ban Evasion",
            ],
            "case-investigation:investigationForm": "case",
            "case-investigation:investigationStatus": "open",
            "uco-core:startTime": xs(offense_begin, "xsd:dateTime"),
        },
        {
            "@id": g["prosecution"],
            "@type": "cacontology-usa-federal-law:FederalProsecution",
            "uco-core:name": f"Federal prosecution — {case_number}",
            "rdfs:label": f"Federal prosecution — {case_number}",
            "gufo:hasBeginPointInXSDDateTimeStamp": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology-usa-federal-law:hasProsecutionBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology-usa-federal-law:prosecutedBy": {"@id": g["prosecutor"]},
            "cacontology-usa-federal-law:hasLegalPhase": {"@id": g["pretrial_phase"]},
            "cacontology-usa-federal-law:prosecutionComplexity": "highly-complex",
            "cacontology-usa-federal-law:prosecutionSeverity": "aggravated-felony",
            "cacontology-usa-federal-law:prosecutionStatus": "active",
        },
        {
            "@id": g["prosecutor"],
            "@type": "cacontology-usa-federal-law:FederalProsecutorRole",
            "uco-core:name": court,
            "rdfs:label": court,
            "cacontology-usa-federal-law:hasRoleBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology-usa-federal-law:roleSpecialization": "child-exploitation",
        },
        {
            "@id": g["pretrial_phase"],
            "@type": ["cac-core:Phase", "cacontology-usa-federal-law:PreTrialPhase"],
            "uco-core:name": "Pre-trial phase",
            "rdfs:label": "Pre-trial phase",
            "cacontology:hasPhaseBeginPoint": xs(indictment_date, "xsd:dateTimeStamp"),
        },
        {
            "@id": g["indictment"],
            "@type": "cacontology:MultiDefendantIndictment",
            "uco-core:name": doc_ref,
            "rdfs:label": doc_ref,
            "uco-core:description": desc(
                f"Indictment filed {date_filed}. {len(charges)} charge groups alleged."
            ),
        },
        {
            "@id": g["enterprise"],
            "@type": ["uco-identity:Organization", "cacontology-extremist-enterprises:ChildExploitationEnterprise"],
            "uco-core:name": f"Alleged child exploitation enterprise ({enterprise.get('statute', '18 U.S.C. 2252A(g)')})",
            "rdfs:label": f"Alleged child exploitation enterprise ({enterprise.get('statute', '18 U.S.C. 2252A(g)')})",
            "uco-core:description": desc(
                f"Large-scale alleged enterprise with minimum {co_conspirator_min} co-conspirators and "
                f"approximately {victim_count} victims.{ban_text}"
            ),
            "cacontology-extremist-enterprises:leadershipCount": xs("1", "xsd:nonNegativeInteger"),
            "cacontology-extremist-enterprises:membershipRequirements": (
                "Alleged co-conspirators coordinated systematic online child exploitation using "
                "multiple platforms with ban-evasion account recreation."
            ),
            "cacontology-extremist-enterprises:hasHierarchy": {"@id": g["hierarchy"]},
            "cacontology-extremist-enterprises:hasLeadershipRelation": {"@id": g["leadership_relator"]},
            "cacontology-extremist-enterprises:hasExploitationRelation": {"@id": g["exploitation_relator"]},
            "cacontology-extremist-enterprises:hasMember": [{"@id": g["defendant"]}]
            + [{"@id": coconspirator_id(slug, case_number, i)} for i in range(2, 2 + co_conspirators)],
            "cacontology-extremist-enterprises:hasOperationalBeginDate": xs(offense_begin, "xsd:dateTimeStamp"),
        },
        {
            "@id": g["hierarchy"],
            "@type": "cacontology-extremist-enterprises:EnterpriseHierarchy",
            "uco-core:name": "Alleged enterprise hierarchy",
            "rdfs:label": "Alleged enterprise hierarchy",
            "cacontology-extremist-enterprises:hierarchyComplexity": "moderate",
        },
        {"@id": g["leadership_relator"], "@type": "gufo:Relator", "rdfs:label": "Alleged enterprise leadership relation"},
        {"@id": g["exploitation_relator"], "@type": "gufo:Relator", "rdfs:label": "Alleged perpetrator-victim exploitation relation"},
        {
            "@id": g["defendant"],
            "@type": "uco-identity:Person",
            "uco-core:name": offender_label,
            "uco-core:description": desc(
                f"Principal alleged offender; {str(offender.get('nationality_context', 'unknown')).replace('_', ' ')}."
            ),
        },
        {
            "@id": g["subject"],
            "@type": ["case-investigation:Subject", "cacontology:OffenderRole"],
            "uco-core:name": f"{offender_label} — principal subject",
            "rdfs:label": f"{offender_label} — principal subject",
            "cacontology:hasRoleBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology:participatesInEvent": [{"@id": g["sextortion"]}, {"@id": g["conspiracy"]}],
        },
        {
            "@id": g["victim_role"],
            "@type": ["uco-victim:Victim", "cacontology:VictimRole"],
            "uco-core:name": "Alleged victim population (aggregate)",
            "rdfs:label": "Alleged victim population (aggregate)",
            "cacontology:hasRoleBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology:participatesInEvent": [{"@id": g["sextortion"]}, {"@id": g["conspiracy"]}],
            "uco-core:description": desc(
                f"Aggregate victim role for approximately {victim_count} alleged victims; no identifying detail."
            ),
        },
        {
            "@id": g["sextortion"],
            "@type": ["cacontology-sextortion:SextortionIncident", "cacontology-sextortion:SocialMediaSextortion"],
            "uco-core:name": "Alleged social media sextortion scheme",
            "rdfs:label": "Alleged social media sextortion scheme",
            "gufo:hasBeginPointInXSDDateTimeStamp": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology-sextortion:incidentType": "social_media_threat",
            "cacontology-sextortion:severityLevel": "extreme",
            "cacontology-sextortion:victimCount": xs(str(min(victim_count, 100)), "xsd:nonNegativeInteger"),
            "uco-core:startTime": xs(offense_begin, "xsd:dateTime"),
            "uco-core:description": desc(f"Alleged coercion via {coercion_text}. {harm_text.capitalize()}."),
        },
        {
            "@id": g["conspiracy"],
            "@type": "cacontology:ConspiracyToCommitCSA",
            "uco-core:name": "Alleged conspiracy to commit CSA",
            "rdfs:label": "Alleged conspiracy to commit CSA",
            "gufo:hasBeginPointInXSDDateTimeStamp": xs(offense_begin, "xsd:dateTimeStamp"),
        },
        {
            "@id": g["impersonation"],
            "@type": "cacontology-sextortion:IdentityImpersonation",
            "uco-core:name": "Alleged impersonation",
            "rdfs:label": "Alleged impersonation",
            "gufo:hasBeginPointInXSDDateTimeStamp": xs(offense_begin, "xsd:dateTimeStamp"),
        },
        {
            "@id": g["recruitment"],
            "@type": "cacontology:VictimRecruitment",
            "uco-core:name": "Alleged coerced victim recruitment",
            "rdfs:label": "Alleged coerced victim recruitment",
        },
        {
            "@id": g["location_court"],
            "@type": "uco-location:Location",
            "uco-core:name": court,
        },
        {
            "@id": g["location_abroad"],
            "@type": "uco-location:Location",
            "uco-core:name": "Location outside United States (alleged)",
            "uco-core:description": desc(
                f"Defendant alleged abroad at time of offense."
                + (f" Extradited {extradition_date[:10]}." if extradition_date else "")
            ),
        },
        {
            "@id": g["extradition"],
            "@type": "cacontology-multi-jurisdiction:ExtraditionRequest",
            "uco-core:name": f"Extradition proceedings — {offender_label}",
            "rdfs:label": f"Extradition proceedings — {offender_label}",
            "uco-core:description": desc("; ".join(str(t) for t in timeline if "extradition" in t.lower() or "extradited" in t.lower())),
        },
        {
            "@id": g["forfeiture_asset"],
            "@type": "uco-observable:ObservableObject",
            "uco-core:name": "Alleged criminal proceeds (forfeiture target)",
        },
        {
            "@id": g["forfeiture"],
            "@type": "cacontology-asset-forfeiture:AssetForfeitureAction",
            "uco-core:name": f"Alleged asset forfeiture under {forfeiture.get('statute', '18 U.S.C. 2253')}",
            "rdfs:label": f"Alleged asset forfeiture under {forfeiture.get('statute', '18 U.S.C. 2253')}",
            "gufo:hasBeginPointInXSDDateTimeStamp": xs(indictment_date, "xsd:dateTimeStamp"),
            "cacontology-gufo:forfeitureBeginTime": xs(indictment_date, "xsd:dateTime"),
            "cacontology-asset-forfeiture:targetedAsset": {"@id": g["forfeiture_asset"]},
            "uco-core:description": desc(f"Forfeiture status: {forfeiture.get('status', 'unknown')}."),
        },
        {
            "@id": g["impact"],
            "@type": "cacontology-victim-impact:ComprehensiveImpactAssessment",
            "uco-core:name": "Alleged victim harm indicators",
            "rdfs:label": "Alleged victim harm indicators",
            "cacontology-victim-impact:assessmentDate": xs(indictment_date, "xsd:dateTime"),
            "cacontology-victim-impact:assessmentType": "documented_harm_indicators",
            "cacontology-victim-impact:assessorCredentials": "indictment_extraction_agent",
            "cac-core:assesses": {"@id": g["sextortion"]},
            "uco-core:description": desc(f"Coded harm indicators only: {harm_text}."),
        },
    ]

    nodes.extend(
        build_provenance_nodes(g, provenance=provenance, doc_ref=doc_ref)
    )

    for i in range(2, 2 + co_conspirators):
        nodes.append(
            {
                "@id": coconspirator_id(slug, case_number, i),
                "@type": "uco-identity:Person",
                "uco-core:name": f"Alleged co-conspirator {i - 1}",
                "uco-core:description": desc(
                    f"Unnamed alleged co-conspirator in enterprise (minimum {co_conspirator_min} total)."
                ),
            }
        )

    nodes.extend(platform_nodes)
    nodes.extend(charge_nodes)

    relationships: list[dict[str, Any]] = [
        {
            "@id": f"kb:{slug}-{case_token(case_number)}-rel-subject",
            "@type": "uco-core:Relationship",
            "uco-core:name": f"{offender_label} subject role",
            "uco-core:source": {"@id": g["defendant"]},
            "uco-core:target": {"@id": g["subject"]},
            "uco-core:kindOfRelationship": "has_role",
            "uco-core:isDirectional": xs("true", "xsd:boolean"),
        },
        {
            "@id": f"kb:{slug}-{case_token(case_number)}-rel-enterprise-sextortion",
            "@type": "uco-core:Relationship",
            "uco-core:name": "Enterprise conducted sextortion",
            "uco-core:source": {"@id": g["enterprise"]},
            "uco-core:target": {"@id": g["sextortion"]},
            "uco-core:kindOfRelationship": "conducted",
            "uco-core:isDirectional": xs("true", "xsd:boolean"),
        },
        {
            "@id": f"kb:{slug}-{case_token(case_number)}-rel-investigation-jurisdiction",
            "@type": "uco-core:Relationship",
            "uco-core:name": "Investigation jurisdiction",
            "uco-core:source": {"@id": g["investigation"]},
            "uco-core:target": {"@id": g["location_court"]},
            "uco-core:kindOfRelationship": "located_at",
            "uco-core:isDirectional": xs("true", "xsd:boolean"),
        },
    ]

    for platform in platforms:
        name = str(platform["name"])
        iri = platform_iris[name.lower()]
        role = str(platform.get("role", ""))
        if role in {"victim_identification", "coercion_primary"}:
            relationships.append(
                {
                    "@id": f"kb:{slug}-{case_token(case_number)}-rel-sextortion-{name.lower()}",
                    "@type": "uco-core:Relationship",
                    "uco-core:name": f"Sextortion used {name}",
                    "uco-core:source": {"@id": g["sextortion"]},
                    "uco-core:target": {"@id": iri},
                    "uco-core:kindOfRelationship": "used_platform",
                    "uco-core:isDirectional": xs("true", "xsd:boolean"),
                }
            )
        if role == "storage_and_distribution":
            relationships.append(
                {
                    "@id": f"kb:{slug}-{case_token(case_number)}-rel-enterprise-{name.lower()}",
                    "@type": "uco-core:Relationship",
                    "uco-core:name": f"Enterprise used {name} for distribution",
                    "uco-core:source": {"@id": g["enterprise"]},
                    "uco-core:target": {"@id": iri},
                    "uco-core:kindOfRelationship": "used_platform",
                    "uco-core:isDirectional": xs("true", "xsd:boolean"),
                }
            )

    nodes.extend(relationships)

    return finalize_graph(nodes, g["bundle"])


def build_enticement_graph(facts: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    case = facts["case"]
    offender = facts.get("offender", {})
    offense = facts.get("offense", {})
    platforms = facts.get("platforms", [])
    coercion = facts.get("coercion_mechanisms", [])
    harm = facts.get("victim_harm_indicators", [])
    charges = facts.get("charges", [])
    forfeiture = facts.get("forfeiture", {})
    disposition = facts.get("disposition", {})
    timeline = facts.get("procedural_timeline", [])
    provenance = facts.get("provenance", {})
    multi_victim = facts.get("multi_victim_context", {})
    post_offense = facts.get("post_offense_conduct", {})
    parallel = facts.get("parallel_prosecution", {})

    case_number = str(case["case_number"])
    court = str(case.get("court", "Unknown court"))
    date_filed = str(case.get("date_filed", "unknown"))
    evidentiary = str(case.get("evidentiary_basis", "alleged"))
    status = str(case.get("status", "unknown"))
    offender_label = str(offender.get("label", "Defendant-1"))
    basis_word = evidentiary.capitalize()

    g = make_ids(slug, case_number)
    offense_begin = timeline_date(timeline, "indictment", "arrest") or f"{date_filed}T00:00:00Z"
    plea_date = timeline_date(timeline, "guilty plea")
    if not plea_date and disposition.get("plea_date"):
        plea_date = f"{disposition['plea_date']}T00:00:00Z"
    sentencing_date = timeline_date(timeline, "sentencing")
    if not sentencing_date and disposition.get("sentencing_date"):
        sentencing_date = f"{disposition['sentencing_date']}T00:00:00Z"
    if not sentencing_date:
        sentencing_date = f"{date_filed}T00:00:00Z"

    victim_count = 1
    if multi_victim.get("additional_minors_solicited"):
        victim_count += int(multi_victim.get("additional_count_approx", 0))

    doc_ref = str(provenance.get("document", "source document"))

    platform_iris: dict[str, str] = {}
    platform_nodes: list[dict[str, Any]] = []
    for platform in platforms:
        iri = platform_id(slug, case_number, str(platform["name"]))
        platform_iris[str(platform["name"]).lower()] = iri
        platform_nodes.append(
            build_platform_node(
                platform=platform,
                platform_iri=iri,
                ban_evasion={},
                basis_word=basis_word,
            )
        )

    charge_nodes = build_charge_nodes(
        charges=charges,
        slug=slug,
        case_number=case_number,
        evidentiary=evidentiary,
        doc_ref=doc_ref,
    )

    coercion_text = ", ".join(COERCION_LABELS.get(str(c), str(c).replace("_", " ")) for c in coercion)
    harm_text = "; ".join(HARM_LABELS.get(str(h), str(h).replace("_", " ")) for h in harm)

    parallel_text = ""
    if parallel.get("state_case_present"):
        parallel_text = (
            f" Parallel state prosecution in {parallel.get('jurisdiction', 'unknown state')} "
            f"({parallel.get('relationship', 'dual sovereign')})."
        )

    post_offense_text = ""
    if isinstance(post_offense, dict):
        conduct = post_offense.get("items", [])
        if isinstance(conduct, list):
            conduct = [str(x).replace("_", " ") for x in conduct]
            if conduct:
                post_offense_text = f" Post-offense conduct: {', '.join(conduct)}."
        if post_offense.get("obstruction_present"):
            post_offense_text += " Obstruction present."

    investigation_status = "closed" if status == "sentenced" else "open"
    prosecution_status = "resolved" if status == "sentenced" else "active"

    nodes: list[dict[str, Any]] = [
        {
            "@id": g["bundle"],
            "@type": "uco-core:Bundle",
            "uco-core:name": f"{court} {case_number} (CAC Enhanced)",
            "uco-core:description": desc(
                f"CAC knowledge graph for {case_number} derived from {doc_ref}. "
                f"Evidentiary basis: {evidentiary.upper()}. Coded extraction only — no victim-identifying detail."
            ),
        },
        {
            "@id": g["investigation"],
            "@type": ["case-investigation:Investigation", "cacontology:CACInvestigation"],
            "uco-core:name": f"U.S. v. {offender_label} — {case_number}",
            "uco-core:description": desc(
                f"Federal online enticement prosecution in {court}. Single primary victim "
                f"(age {offense.get('victim_age_at_offense', 'unknown')} at offense)."
                f"{parallel_text}{post_offense_text}"
            ),
            "case-investigation:focus": [
                "Online Enticement",
                "Grooming and Solicitation",
                "Interstate Travel",
            ],
            "case-investigation:investigationForm": "case",
            "case-investigation:investigationStatus": investigation_status,
            "uco-core:startTime": xs(offense_begin, "xsd:dateTime"),
        },
        {
            "@id": g["prosecution"],
            "@type": "cacontology-usa-federal-law:FederalProsecution",
            "uco-core:name": f"Federal prosecution — {case_number}",
            "rdfs:label": f"Federal prosecution — {case_number}",
            "gufo:hasBeginPointInXSDDateTimeStamp": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology-usa-federal-law:hasProsecutionBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology-usa-federal-law:hasProsecutionEndPoint": xs(sentencing_date, "xsd:dateTimeStamp"),
            "cacontology-usa-federal-law:prosecutedBy": {"@id": g["prosecutor"]},
            "cacontology-usa-federal-law:hasLegalPhase": {"@id": g["pretrial_phase"]},
            "cacontology-usa-federal-law:prosecutionComplexity": "moderate",
            "cacontology-usa-federal-law:prosecutionSeverity": "aggravated-felony",
            "cacontology-usa-federal-law:prosecutionStatus": prosecution_status,
        },
        {
            "@id": g["prosecutor"],
            "@type": "cacontology-usa-federal-law:FederalProsecutorRole",
            "uco-core:name": court,
            "rdfs:label": court,
            "cacontology-usa-federal-law:hasRoleBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology-usa-federal-law:roleSpecialization": "child-exploitation",
        },
        {
            "@id": g["pretrial_phase"],
            "@type": ["cac-core:Phase", "cacontology-usa-federal-law:PreTrialPhase"],
            "uco-core:name": "Pre-trial through sentencing phase",
            "rdfs:label": "Pre-trial through sentencing phase",
            "cacontology:hasPhaseBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology:hasPhaseEndPoint": xs(sentencing_date, "xsd:dateTimeStamp"),
        },
        {
            "@id": g["indictment"],
            "@type": "cacontology:MultiDefendantIndictment",
            "uco-core:name": doc_ref,
            "rdfs:label": doc_ref,
            "uco-core:description": desc(
                f"Indictment filed {date_filed}. {len(charges)} counts; "
                f"guilty plea {plea_date[:10] if plea_date else 'unknown'}."
            ),
        },
        {
            "@id": g["defendant"],
            "@type": "uco-identity:Person",
            "uco-core:name": offender_label,
            "uco-core:description": desc(
                f"Principal offender; {str(offender.get('location_at_offense', 'unknown')).replace('_', ' ')}."
                + (" Age misrepresentation to victim." if offender.get("age_misrepresentation") else "")
            ),
        },
        {
            "@id": g["subject"],
            "@type": ["case-investigation:Subject", "cacontology:OffenderRole"],
            "uco-core:name": f"{offender_label} — principal subject",
            "rdfs:label": f"{offender_label} — principal subject",
            "cacontology:hasRoleBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology:participatesInEvent": [{"@id": g["grooming"]}],
        },
        {
            "@id": g["victim_role"],
            "@type": ["uco-victim:Victim", "cacontology:VictimRole"],
            "uco-core:name": "Victim (single primary)",
            "rdfs:label": "Victim (single primary)",
            "cacontology:hasRoleBeginPoint": xs(offense_begin, "xsd:dateTimeStamp"),
            "cacontology:participatesInEvent": [{"@id": g["grooming"]}],
            "uco-core:description": desc(
                f"Primary victim age {offense.get('victim_age_at_offense', 'unknown')} at offense; no identifying detail."
            ),
        },
        {
            "@id": g["grooming"],
            "@type": [
                "cacontology:GroomingSolicitation",
                "cacontology-us-ncmec:OnlineEnticementIncident",
            ],
            "uco-core:name": "Online enticement to contact (proven)",
            "rdfs:label": "Online enticement to contact (proven)",
            "cacontology-us-ncmec:incidentCode": "OE",
            "gufo:hasBeginPointInXSDDateTimeStamp": xs(offense_begin, "xsd:dateTimeStamp"),
            "uco-core:startTime": xs(offense_begin, "xsd:dateTime"),
            "cacontology:participatesInEvent": [
                {"@id": g["subject"]},
                {"@id": g["victim_role"]},
            ],
            "uco-core:description": desc(
                f"{basis_word} {str(offense.get('type', 'online enticement')).replace('_', ' ')} under "
                f"{offense.get('statute_of_conviction', 'unknown')}. Coercion via {coercion_text}. "
                f"Online-to-in-person contact: {offense.get('online_to_inperson', False)}; "
                f"interstate travel: {offense.get('interstate_travel', False)}; "
                f"physical contact: {offense.get('physical_contact_occurred', False)}."
            ),
        },
        {
            "@id": g["location_court"],
            "@type": "uco-location:Location",
            "uco-core:name": court,
        },
        {
            "@id": g["forfeiture_asset"],
            "@type": "uco-observable:ObservableObject",
            "uco-core:name": "Criminal proceeds (forfeiture target)",
        },
        {
            "@id": g["forfeiture"],
            "@type": "cacontology-asset-forfeiture:AssetForfeitureAction",
            "uco-core:name": "Asset forfeiture",
            "rdfs:label": "Asset forfeiture",
            "gufo:hasBeginPointInXSDDateTimeStamp": xs(sentencing_date, "xsd:dateTimeStamp"),
            "cacontology-gufo:forfeitureBeginTime": xs(sentencing_date, "xsd:dateTime"),
            "cacontology-asset-forfeiture:targetedAsset": {"@id": g["forfeiture_asset"]},
            "uco-core:description": desc(f"Forfeiture status: {forfeiture.get('status', 'unknown')}."),
        },
        {
            "@id": g["impact"],
            "@type": "cacontology-victim-impact:ComprehensiveImpactAssessment",
            "uco-core:name": "Victim harm indicators",
            "rdfs:label": "Victim harm indicators",
            "cacontology-victim-impact:assessmentDate": xs(sentencing_date, "xsd:dateTime"),
            "cacontology-victim-impact:assessmentType": "documented_harm_indicators",
            "cacontology-victim-impact:assessorCredentials": "statement_of_offense_extraction_agent",
            "cac-core:assesses": {"@id": g["grooming"]},
            "uco-core:description": desc(f"Coded harm indicators only: {harm_text}."),
        },
    ]

    nodes.extend(build_provenance_nodes(g, provenance=provenance, doc_ref=doc_ref))
    nodes.extend(platform_nodes)
    nodes.extend(charge_nodes)

    relationships: list[dict[str, Any]] = [
        {
            "@id": f"kb:{slug}-{case_token(case_number)}-rel-subject",
            "@type": "uco-core:Relationship",
            "uco-core:name": f"{offender_label} subject role",
            "uco-core:source": {"@id": g["defendant"]},
            "uco-core:target": {"@id": g["subject"]},
            "uco-core:kindOfRelationship": "has_role",
            "uco-core:isDirectional": xs("true", "xsd:boolean"),
        },
        {
            "@id": f"kb:{slug}-{case_token(case_number)}-rel-investigation-jurisdiction",
            "@type": "uco-core:Relationship",
            "uco-core:name": "Investigation jurisdiction",
            "uco-core:source": {"@id": g["investigation"]},
            "uco-core:target": {"@id": g["location_court"]},
            "uco-core:kindOfRelationship": "located_at",
            "uco-core:isDirectional": xs("true", "xsd:boolean"),
        },
    ]

    for platform in platforms:
        name = str(platform["name"])
        iri = platform_iris[name.lower()]
        relationships.append(
            {
                "@id": f"kb:{slug}-{case_token(case_number)}-rel-grooming-{name.lower()}",
                "@type": "uco-core:Relationship",
                "uco-core:name": f"Enticement used {name}",
                "uco-core:source": {"@id": g["grooming"]},
                "uco-core:target": {"@id": iri},
                "uco-core:kindOfRelationship": "used_platform",
                "uco-core:isDirectional": xs("true", "xsd:boolean"),
            }
        )

    nodes.extend(relationships)
    return finalize_graph(nodes, g["bundle"])


def write_graph(facts_path: Path, output_path: Path) -> None:
    facts = load_facts(facts_path)
    slug = slug_from_facts_path(facts_path)
    document = {"@context": CONTEXT, "@graph": build_graph(facts, slug)}
    output_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")


def validate_graph(output_path: Path) -> bool:
    ext_dir = SDK_ROOT / "extensions/cac"
    ontology_graphs = [str(ext_dir / rel) for rel in CURATED_ONTOLOGY_FILES]
    cmd = [
        str(CASE_VALIDATE),
        "--built-version",
        "case-1.4.0",
        "--inference",
        "rdfs",
        "--allow-info",
    ]
    for graph_path in ontology_graphs:
        cmd.extend(["--ontology-graph", graph_path])
    cmd.append(str(output_path))

    print(f"Validating {output_path.name} with {len(ontology_graphs)} ontology graphs...")
    result = subprocess.run(cmd, cwd=SDK_ROOT, capture_output=True, text=True)
    if "Conforms: True" in result.stdout:
        print("Conforms: True")
        return True
    print(result.stdout[-4000:])
    if result.stderr:
        print(result.stderr[-2000:], file=sys.stderr)
    return False


def process_facts_file(facts_path: Path, *, validate: bool) -> int:
    if not facts_path.exists():
        print(f"Facts file not found: {facts_path}", file=sys.stderr)
        return 1
    output_path = output_path_for(facts_path)
    write_graph(facts_path, output_path)
    if not validate:
        return 0
    if not CASE_VALIDATE.exists():
        print("case_validate not found; graph written but not validated.", file=sys.stderr)
        return 1
    return 0 if validate_graph(output_path) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build CAC JSON-LD graphs from PACER facts files.",
        epilog=(
            "Examples:\n"
            "  python build_facts_graphs.py\n"
            "  python build_facts_graphs.py ALASKA/alaska_facts.txt\n"
            "  python build_facts_graphs.py --facts ALASKA/alaska_facts.txt"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "facts_files",
        nargs="*",
        help="Optional specific facts .txt file(s). If omitted, reads facts.txt manifest.",
    )
    parser.add_argument(
        "--facts",
        dest="facts_flag",
        metavar="FILE",
        help="Build graph from a specific facts file (alias for positional argument).",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help=f"Manifest of facts files to build (default: {DEFAULT_MANIFEST.name})",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip case_validate after writing JSON-LD.",
    )
    return parser.parse_args(argv)


def resolve_facts_paths(args: argparse.Namespace) -> list[Path]:
    explicit = list(args.facts_files)
    if args.facts_flag:
        explicit.append(args.facts_flag)
    if explicit:
        resolved: list[Path] = []
        for item in explicit:
            path = Path(item)
            resolved.append(path if path.is_absolute() else PACER_DIR / path)
        return resolved
    return read_manifest(Path(args.manifest))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    facts_paths = resolve_facts_paths(args)
    exit_code = 0
    for facts_path in facts_paths:
        print(f"Building from {facts_path}...")
        result = process_facts_file(facts_path, validate=not args.no_validate)
        if result != 0:
            exit_code = result
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
