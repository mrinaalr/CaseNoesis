#!/usr/bin/env python3
"""
CaseLinker → CAC Ontology mapper.

Transforms a CaseLinker case dict (as returned by CaseStorage.get_case()) into a
typed RDF knowledge graph using the CAC Ontology v3.0.0 class vocabulary.

Uses rdflib 7.x with manual CAC namespace bindings.
(case-uco and case-uco-cac are not published on PyPI as of May 2026.)

Entry points
------------
map_case(case_dict)
    Map one case dict → (ConjunctiveGraph, list[str] warnings)

export_case(case_id, output_path, db_url=None)
    Full pipeline: load from DB → map → validate → write JSON-LD + Turtle.

validate(graph)
    Run pyshacl against cacontology-core-shapes.ttl.

CLI
---
python features_to_cac.py                  # runs test fixture azicac_2011_006
python features_to_cac.py <case_id>        # loads from DB (DATABASE_URL must be set)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rdflib import (
    XSD,
    Dataset,
    Graph,
    Literal,
    Namespace,
    RDF,
    RDFS,
    OWL,
    URIRef,
)
# rdflib 7.x: ConjunctiveGraph is deprecated; Dataset is the replacement.
# Keep the alias for backward-compatibility in type hints.
ConjunctiveGraph = Dataset
from rdflib.namespace import DCTERMS, SKOS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).parent
_REPO_ROOT = _THIS_DIR.parent
_CAC_ONTOLOGY_DIR = _REPO_ROOT.parent / "CAC-Ontology" / "ontology"
_OUTPUT_DIR = _THIS_DIR / "output"
_TEST_OUTPUT_DIR = _THIS_DIR / "graph_output"

# ---------------------------------------------------------------------------
# CAC / UCO Namespaces
# ---------------------------------------------------------------------------

BASE = Namespace("https://caselinker.up.railway.app/resource/")

CAC = Namespace("https://cacontology.projectvic.org#")
CAC_CORE = Namespace("https://cacontology.projectvic.org/core#")
CAC_GROOMING = Namespace("https://cacontology.projectvic.org/grooming#")
CAC_CUSTODIAL = Namespace("https://cacontology.projectvic.org/custodial#")
CAC_PLATFORMS = Namespace("https://cacontology.projectvic.org/platforms#")
CAC_LEGAL = Namespace("https://cacontology.projectvic.org/legal-outcomes#")
CAC_SEXTORTION = Namespace("https://cacontology.projectvic.org/sextortion#")
CAC_DETECTION = Namespace("https://cacontology.projectvic.org/detection#")
CAC_PRODUCTION = Namespace("https://cacontology.projectvic.org/production#")
CAC_TASKFORCE = Namespace("https://cacontology.projectvic.org/taskforce#")
CAC_NCMEC = Namespace("https://cacontology.projectvic.org/us/ncmec#")
CAC_MULTI = Namespace("https://cacontology.projectvic.org/multi-jurisdiction#")

UCO_CORE = Namespace("https://ontology.unifiedcyberontology.org/uco/core/")
UCO_ACTION = Namespace("https://ontology.unifiedcyberontology.org/uco/action/")
UCO_IDENTITY = Namespace("https://ontology.unifiedcyberontology.org/uco/identity/")
UCO_ROLE = Namespace("https://ontology.unifiedcyberontology.org/uco/role/")
UCO_LOCATION = Namespace("https://ontology.unifiedcyberontology.org/uco/location/")
GUFO = Namespace("http://purl.org/nemo/gufo#")

# Named graph URIs
GRAPH_DETERMINISTIC = BASE["graphs/deterministic"]
GRAPH_NLP = BASE["graphs/nlp"]

# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    """Convert a string to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = text.strip("-")
    return text or "unknown"


def _to_xsd_datetime_stamp(value: Any) -> Optional[str]:
    """
    Normalize a CaseLinker date/year string into an ``xsd:dateTimeStamp``
    lexical form (RFC 3339 with a timezone offset).

    CaseLinker stores dates as ``"YYYY"``, ``"YYYY-MM"``, ``"YYYY-MM-DD"``,
    or already-ISO timestamps. The CAC core-shapes file requires
    ``xsd:dateTimeStamp`` for phase begin/end points, which mandates a
    full date + time + timezone. We pin missing components to ``-01``
    and ``00:00:00Z`` so the literal validates.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Already a full timestamp with timezone?
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$", s):
        return s
    # ISO datetime missing timezone
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s):
        return (s.split("+")[0].split("-", 3)[-1] and s) + ("Z" if not s.endswith("Z") else "")
    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return f"{s}T00:00:00Z"
    # YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", s):
        return f"{s}-01T00:00:00Z"
    # YYYY
    if re.match(r"^\d{4}$", s):
        return f"{s}-01-01T00:00:00Z"
    return None


# ---------------------------------------------------------------------------
# PLATFORM_MAP
# 35 canonical platform labels → (CAC class, extra properties dict)
# SKIP sentinel means: do not create a platform node.
# ---------------------------------------------------------------------------

_SKIP = "__SKIP__"

PLATFORM_MAP: Dict[str, Tuple[str, Dict[str, Any]]] = {
    # --- Social Media ---
    "Facebook":                 ("SocialMediaPlatform",      {}),
    "Instagram":                ("SocialMediaPlatform",      {}),
    "TikTok":                   ("SocialMediaPlatform",      {}),
    "Twitter / X":              ("SocialMediaPlatform",      {}),
    "MeWe":                     ("SocialMediaPlatform",      {}),
    "MySpace":                  ("SocialMediaPlatform",      {"platformType": "legacy"}),
    "Craigslist":               ("SocialMediaPlatform",      {"platformType": "classifieds"}),
    "social media":             ("SocialMediaPlatform",      {"platformSpecificity": "generic"}),
    # --- Messaging ---
    "Facebook Messenger":       ("MessagingService",         {}),
    "WhatsApp":                 ("MessagingService",         {"encryptionLevel": "end-to-end"}),
    "Telegram":                 ("MessagingService",         {}),
    "Snapchat":                 ("MessagingService",         {"encryptionLevel": "end-to-end"}),
    "Skype":                    ("MessagingService",         {}),
    "Kik":                      ("MessagingService",         {}),
    "Discord":                  ("MessagingService",         {}),
    "AOL Instant Messenger":    ("MessagingService",         {"platformType": "legacy"}),
    "Yahoo Chat":               ("MessagingService",         {"platformType": "legacy"}),
    # --- Anonymous Chat ---
    "Omegle":                   ("AnonymousChatPlatform",    {"guestAccountsAllowed": "true", "identityVerificationRequired": "false"}),
    "IRC":                      ("AnonymousChatPlatform",    {"platformType": "legacy"}),
    "chat":                     ("AnonymousChatPlatform",    {"platformSpecificity": "generic"}),
    # --- Video Streaming ---
    "YouTube":                  ("VideoStreamingPlatform",   {}),
    "YouTube Live":             ("VideoStreamingPlatform",   {}),
    "Twitch":                   ("VideoStreamingPlatform",   {}),
    "Webcam platform":          ("VideoStreamingPlatform",   {"allowsAnonymousChat": "true"}),
    # --- Gaming ---
    "Roblox":                   ("GamePlatform",             {"allowsAnonymousChat": "true"}),
    "Minecraft":                ("GamePlatform",             {}),
    "Xbox Live":                ("GamePlatform",             {}),
    "PlayStation Network":      ("GamePlatform",             {}),
    "Fortnite":                 ("GamePlatform",             {}),
    # --- File Hosting ---
    "Dropbox":                  ("FileHostingService",       {}),
    "Google Drive":             ("FileHostingService",       {}),
    "Mega.nz":                  ("FileHostingService",       {"encryptionLevel": "end-to-end"}),
    "MediaFire":                ("FileHostingService",       {}),
    "OneDrive":                 ("FileHostingService",       {}),
    # --- P2P (FileHostingService with platformType=p2p) ---
    "LimeWire":                 ("FileHostingService",       {"platformType": "p2p"}),
    "BitTorrent":               ("FileHostingService",       {"platformType": "p2p"}),
    "Kazaa":                    ("FileHostingService",       {"platformType": "p2p", "platformVersion": "legacy"}),
    "Gigatribe":                ("FileHostingService",       {"platformType": "p2p"}),
    # --- Dark Web ---
    "Tor":                      ("DarkWebService",           {}),
    "I2P":                      ("DarkWebService",           {}),
    "dark web":                 ("DarkWebService",           {}),
    # --- SKIP ---
    "online":                   (_SKIP,                      {}),
}

_PLATFORM_CLASS_URI: Dict[str, URIRef] = {
    "SocialMediaPlatform":   CAC_PLATFORMS.SocialMediaPlatform,
    "MessagingService":      CAC_PLATFORMS.MessagingService,
    "AnonymousChatPlatform": CAC_PLATFORMS.AnonymousChatPlatform,
    "VideoStreamingPlatform":CAC_PLATFORMS.VideoStreamingPlatform,
    "GamePlatform":          CAC_PLATFORMS.GamePlatform,
    "FileHostingService":    CAC_PLATFORMS.FileHostingService,
    "DarkWebService":        CAC_PLATFORMS.DarkWebService,
}

# ---------------------------------------------------------------------------
# TOPIC_MAP
# case_topics values → (CAC class URI, spine branch, extra_triples_fn_name)
# ---------------------------------------------------------------------------

# Each entry: (primary_class_uri, creates_second_node: bool, second_class_uri | None)
TOPIC_MAP: Dict[str, Dict[str, Any]] = {
    "production": {
        "class": CAC_PRODUCTION.ProductionOffense,
        "severity": 3,
        "secondary_charge_class": CAC_LEGAL.CSAM_Production,
    },
    "possession": {
        "class": CAC.CSAMIncident,
        "severity": 2,
        "secondary_charge_class": CAC_LEGAL.CSAM_Possession,
    },
    "csam": {
        "class": CAC.CSAMIncident,
        "severity": 2,
        "secondary_charge_class": None,
    },
    "international": {
        "class": CAC_MULTI.MultiJurisdictionalInvestigation,
        "severity": 0,
        "crosses_borders": True,
    },
    "multi_state": {
        "class": CAC_MULTI.MultiJurisdictionalInvestigation,
        "severity": 0,
        "crosses_borders": False,
    },
    "hands_on": {
        "class": CAC.ChildSexualAbuseEvent,
        "severity": 3,
    },
    "online_only": {
        # Resolved at mapping time: GroomingSolicitation if grooming present, else ChildSexualAbuseEvent
        "class": CAC.ChildSexualAbuseEvent,
        "class_if_grooming": CAC.GroomingSolicitation,
        "severity": 1,
    },
    "family": {
        "class": CAC_CUSTODIAL.FamilialRelationship,
        "severity": 0,
    },
    "stranger": {
        "class": CAC_GROOMING.OnlinePredator,
        "severity": 0,
    },
    "grooming": {
        "class": CAC_GROOMING.OnlineGrooming,
        "severity": 1,
    },
}

# ---------------------------------------------------------------------------
# INVESTIGATION_TYPE_MAP
# ---------------------------------------------------------------------------

INVESTIGATION_TYPE_MAP: Dict[str, Optional[URIRef]] = {
    "undercover": CAC_TASKFORCE.UndercoverUnit,
    "proactive":  CAC_TASKFORCE.ProactiveOperation,
    "reactive":   CAC_TASKFORCE.ReactiveOperation,
    "online":     CAC_TASKFORCE.TaskForceOperation,
    "unknown":    None,  # No operation node; set investigationStatus=unknown on investigation
}

# ---------------------------------------------------------------------------
# PROSECUTION_STATUS_MAP
# ---------------------------------------------------------------------------

PROSECUTION_STATUS_MAP: Dict[str, Optional[URIRef]] = {
    "convicted":      CAC_LEGAL.SentencingPhase,
    "charged":        CAC_LEGAL.LegalProcessPhase,
    "arrested":       CAC.InitialPhase,
    "pleaded_guilty": CAC_LEGAL.PleaBargaining,
    "acquitted":      CAC_LEGAL.TrialProceeding,
}

# Charge type patterns → CAC charge class
# Applied via case-insensitive substring matching on the charge string.
CHARGE_PATTERN_MAP: List[Tuple[str, URIRef]] = [
    ("production",                  CAC_LEGAL.CSAM_Production),
    ("causing production",          CAC_LEGAL.CSAM_CausingProduction),
    ("distribution",                CAC_LEGAL.CSAM_Distribution),
    ("dissemination",               CAC_LEGAL.CSAM_Distribution),
    ("possession",                  CAC_LEGAL.CSAM_Possession),
    ("sex trafficking",             CAC_LEGAL.SexTrafficking),
    ("trafficking",                 CAC_LEGAL.SexTrafficking),
    ("sextortion",                  CAC_LEGAL.SextortionCharge),
    ("online enticement",           CAC_LEGAL.OnlineEnticement),
    ("enticement",                  CAC_LEGAL.OnlineEnticement),
    ("luring",                      CAC_LEGAL.OnlineEnticement),
    ("traveling to meet",           CAC_LEGAL.TravelingToMeetAfterComputerLure),
    ("travel to meet",              CAC_LEGAL.TravelingToMeetAfterComputerLure),
    ("coercion",                    CAC_LEGAL.CSAM_CausingProduction),
]

SENTENCE_PATTERN_MAP: List[Tuple[str, URIRef]] = [
    ("life",              CAC_LEGAL.LifeImprisonmentSentence),
    ("mandatory minimum", CAC_LEGAL.MandatoryMinimumSentencing),
    ("probation",         CAC_LEGAL.ProbationSentence),
    ("supervised release",CAC_LEGAL.SupervisedRelease),
    (r"\$",               CAC_LEGAL.MonetaryPenalty),
    ("year",              CAC_LEGAL.PrisonSentence),
    ("month",             CAC_LEGAL.PrisonSentence),
]

# ---------------------------------------------------------------------------
# SEVERITY_MAP
# severity_indicators list → (severityLevel int, extra CAC node class or None)
# ---------------------------------------------------------------------------

SEVERITY_MAP: Dict[str, Tuple[int, Optional[URIRef]]] = {
    "infant":                (3, None),
    "very_young":            (2, None),
    "under_12":              (2, None),
    "sexual_abuse":          (3, None),
    "physical_abuse":        (3, None),
    "multiple_perpetrators": (1, CAC.ConspiracyToCommitCSA),
}

# ---------------------------------------------------------------------------
# ROLE_MAP
# relationship_to_victim → (custodial class, relationship class)
# ---------------------------------------------------------------------------

ROLE_MAP: Dict[str, Tuple[URIRef, URIRef]] = {
    # Generic family label (when specific relationship not parsed)
    "family":       (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.FamilialRelationship),
    # Specific family members
    "father":       (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.CaregiverRelationship),
    "mother":       (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.CaregiverRelationship),
    "parent":       (CAC_CUSTODIAL.CaregiverRelationship,      CAC_CUSTODIAL.CaregiverRelationship),
    "brother":      (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.FamilialRelationship),
    "sister":       (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.FamilialRelationship),
    "sibling":      (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.FamilialRelationship),
    "uncle":        (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.Relative),
    "aunt":         (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.Relative),
    "cousin":       (CAC_CUSTODIAL.FamilialRelationship,       CAC_CUSTODIAL.Relative),
    # Positions of trust
    "teacher":      (CAC_CUSTODIAL.Teacher,                    CAC_CUSTODIAL.PositionOfTrust),
    "coach":        (CAC_CUSTODIAL.Coach,                      CAC_CUSTODIAL.PositionOfTrust),
    "mentor":       (CAC_CUSTODIAL.Mentor,                     CAC_CUSTODIAL.PositionOfTrust),
    "babysitter":   (CAC_CUSTODIAL.Babysitter,                 CAC_CUSTODIAL.PositionOfTrust),
    "guardian":     (CAC_CUSTODIAL.Guardian,                   CAC_CUSTODIAL.CaregiverRelationship),
    "family friend":(CAC_CUSTODIAL.FamilyFriend,               CAC_CUSTODIAL.PositionOfTrust),
    "stranger":     (CAC_GROOMING.OnlinePredator,              CAC_GROOMING.OnlinePredator),
}

# ---------------------------------------------------------------------------
# AGENCY tiering patterns
# ---------------------------------------------------------------------------

_STATE_ATTORNEY_PATTERN = re.compile(
    r"Attorney General|County Attorney|District Attorney|State Attorney|"
    r"State Police|Bureau of Investigation|\bGBI\b|\bCBI\b|\bBCI\b|\bMBI\b|\bSBI\b|"
    r"Department of Public Safety|State Bureau",
    re.I,
)

_FEDERAL_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bFBI\b|Federal Bureau of Investigation", re.I), "fbi"),
    (re.compile(r"\bHSI\b|Homeland Security Investigations?", re.I), "hsi"),
    (re.compile(r"\bICE\b|Immigration and Customs Enforcement", re.I), "ice"),
    (re.compile(r"\bUSMS\b|U\.?S\.? Marshals?", re.I), "usms"),
    (re.compile(r"\bUSAO\b|U\.?S\.? Attorney", re.I), "usao"),
    (re.compile(r"\bDEA\b|Drug Enforcement Administration", re.I), "dea"),
    (re.compile(r"\bATF\b", re.I), "atf"),
    (re.compile(r"\bNCMEC\b|National Center for Missing", re.I), "ncmec"),
    (re.compile(r"\bCEOS\b|Child Exploitation and Obscenity", re.I), "ceos"),
    (re.compile(r"\bDOJ\b|Department of Justice", re.I), "doj"),
]

_ICAC_PATTERN = re.compile(r"ICAC\b|Internet Crimes Against Children", re.I)

# ---------------------------------------------------------------------------
# TECHNOLOGY_SIGNAL_MAP
# ---------------------------------------------------------------------------

INVESTIGATION_TECH_MAP: Dict[str, URIRef] = {
    "PhotoDNA":      CAC_DETECTION.ContentHashingAction,
    "CSAI Match":    CAC_DETECTION.AutomatedDetectionAction,
    "hash matching": CAC_DETECTION.ContentHashingAction,
    "CyberTipline":  CAC_NCMEC.NCMECCybertipReport,
}

ANON_NETWORK_MAP: Dict[str, URIRef] = {
    "Tor":            CAC_PLATFORMS.DarkWebService,
    "I2P":            CAC_PLATFORMS.DarkWebService,
    "dark web":       CAC_PLATFORMS.DarkWebService,
    "cryptocurrency": CAC_PLATFORMS.CryptocurrencyService,
}

# P2P clients reuse PLATFORM_MAP
P2P_CLIENT_MAP: Dict[str, str] = {
    "LimeWire":   "LimeWire",
    "BitTorrent": "BitTorrent",
    "Kazaa":      "Kazaa",
    "Gigatribe":  "Gigatribe",
}

# ---------------------------------------------------------------------------
# NLP concept thresholds for v1
# ---------------------------------------------------------------------------

NLP_CONCEPT_MAP: Dict[str, Tuple[float, URIRef]] = {
    "grooming":              (0.45, CAC_GROOMING.OnlineGrooming),
    "sextortion":            (0.45, CAC_SEXTORTION.SextortionIncident),
    "production_csam":       (0.50, CAC_PRODUCTION.ProductionOffense),
    "possession_csam":       (0.50, CAC.CSAMIncident),
    "dissemination":         (0.45, CAC_LEGAL.CSAM_Distribution),
    "exploitive_positions":  (0.45, CAC_CUSTODIAL.PositionOfTrust),
    "registered_sex_offender":(0.45, None),   # applied as flag on OffenderRole
    "evidence_seizure":      (0.45, CAC_PRODUCTION.ProducedContent),
}


# ===========================================================================
# Graph builder
# ===========================================================================

class CaseToCAC:
    """
    Maps a single CaseLinker case dict to a CAC Ontology RDF graph.

    Usage::

        mapper = CaseToCAC()
        g, warnings = mapper.map_case(case_dict)
        jsonld = g.serialize(format="json-ld", indent=2)
    """

    def __init__(self) -> None:
        # In-process singleton registry: slug → URIRef (shared across calls)
        self._platform_registry: Dict[str, URIRef] = {}
        self._agency_registry: Dict[str, URIRef] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def map_case(
        self, case: Dict[str, Any]
    ) -> Tuple[ConjunctiveGraph, List[str]]:
        """
        Map one case dict to a ConjunctiveGraph.

        Returns
        -------
        (graph, warnings)
            graph    : rdflib ConjunctiveGraph with two named graphs
                       (deterministic + nlp)
            warnings : list of human-readable warning strings for unmapped values
        """
        warnings: List[str] = []
        cg = ConjunctiveGraph()
        self._bind_namespaces(cg)

        det_g = cg.get_context(GRAPH_DETERMINISTIC)
        nlp_g = cg.get_context(GRAPH_NLP)
        self._bind_namespaces(det_g)
        self._bind_namespaces(nlp_g)

        case_id = case.get("id", "unknown")

        # --- investigation shell (always created) ---
        inv_uri = self.build_investigation_shell(det_g, case, warnings)

        # --- deterministic mapping steps ---
        platform_uris = self.map_platforms(det_g, case, inv_uri, warnings)
        event_uris = self.map_topics(det_g, case, inv_uri, warnings)
        victim_uris, offender_uris = self.map_roles(det_g, case, inv_uri, event_uris, warnings)
        self.map_severity(det_g, case, event_uris, offender_uris, warnings)
        self.map_prosecution(det_g, case, inv_uri, warnings)
        self.map_agencies(det_g, case, inv_uri, warnings)
        self.map_technology(det_g, case, inv_uri, warnings)
        self.map_investigation_type(det_g, case, inv_uri, warnings)

        # SHACL: set hasRoleBeginPoint on roles from case start date
        self._apply_role_temporal(det_g, case, victim_uris, offender_uris)

        # SHACL: add participatesInEvent on roles + hasFacet on CSAMIncident
        self._apply_shacl_required_triples(det_g, case, event_uris, victim_uris, offender_uris)

        # --- NLP mapping (separate named graph) ---
        self.map_nlp_features(nlp_g, case, inv_uri, warnings)

        return cg, warnings

    def validate(
        self, graph: ConjunctiveGraph
    ) -> Tuple[bool, str]:
        """
        Run pyshacl against cacontology-core-shapes.ttl.

        Returns
        -------
        (conforms, report_text)
        """
        shapes_path = _CAC_ONTOLOGY_DIR / "cacontology-core-shapes.ttl"
        if not shapes_path.exists():
            return False, f"SHACL shapes file not found at {shapes_path}"

        try:
            from pyshacl import validate as shacl_validate

            data_graph = Graph()
            for ctx in graph.graphs():
                for triple in ctx:
                    data_graph.add(triple)

            shapes_graph = Graph()
            shapes_graph.parse(str(shapes_path), format="turtle")

            conforms, _results_graph, results_text = shacl_validate(
                data_graph=data_graph,
                shacl_graph=shapes_graph,
                inference="none",
                advanced=False,
                allow_infos=True,
                abort_on_first=False,
            )
            return conforms, results_text
        except ImportError:
            return False, "pyshacl not installed"
        except Exception as exc:
            return False, f"SHACL validation error: {exc}"

    def export_case(
        self,
        case_id: str,
        output_dir: Optional[Path] = None,
        db_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Full pipeline: load from DB → map → validate → write files.

        Returns a result dict with keys:
            case_id, node_count, edge_count, node_types, warnings,
            shacl_conforms, shacl_report, jsonld_path, ttl_path
        """
        output_dir = output_dir or _OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        case = self._load_from_db(case_id, db_url)
        if case is None:
            raise ValueError(
                f"Case '{case_id}' not found. Ensure DATABASE_URL is set and the case exists."
            )

        graph, warnings = self.map_case(case)

        jsonld_path = output_dir / f"{case_id}.jsonld"
        ttl_path = output_dir / f"{case_id}.ttl"
        graph.serialize(destination=str(jsonld_path), format="json-ld", indent=2)
        graph.serialize(destination=str(ttl_path), format="turtle")

        conforms, shacl_report = self.validate(graph)
        summary = self._graph_summary(graph)

        return {
            "case_id": case_id,
            **summary,
            "warnings": warnings,
            "shacl_conforms": conforms,
            "shacl_report": shacl_report,
            "jsonld_path": str(jsonld_path),
            "ttl_path": str(ttl_path),
        }

    # ------------------------------------------------------------------
    # Step 1: Investigation shell
    # ------------------------------------------------------------------

    def build_investigation_shell(
        self,
        g: Graph,
        case: Dict[str, Any],
        warnings: List[str],
    ) -> URIRef:
        """Create the root CACInvestigation node and its metadata."""
        case_id = case.get("id", "unknown")
        inv_uri = BASE[f"case/{case_id}"]

        g.add((inv_uri, RDF.type, CAC.CACInvestigation))
        g.add((inv_uri, RDF.type, CAC_CORE.EnduringEntity))
        g.add((inv_uri, DCTERMS.identifier, Literal(case_id)))

        if case.get("source"):
            g.add((inv_uri, DCTERMS.source, Literal(case["source"])))
        if case.get("source_url"):
            g.add((inv_uri, DCTERMS.source, URIRef(case["source_url"])))
        if case.get("notes"):
            g.add((inv_uri, RDFS.comment, Literal(case["notes"])))
        if case.get("tags"):
            tags = case["tags"] if isinstance(case["tags"], list) else [case["tags"]]
            for tag in tags:
                g.add((inv_uri, SKOS.altLabel, Literal(str(tag))))
        if case.get("created_at"):
            g.add((inv_uri, DCTERMS.created, Literal(str(case["created_at"]))))
        if case.get("updated_at"):
            g.add((inv_uri, DCTERMS.modified, Literal(str(case["updated_at"]))))

        # Date range → phase begin/end (xsd:dateTimeStamp required by CAC SHACL)
        date_range = case.get("date_range") or {}
        if isinstance(date_range, dict):
            start = _to_xsd_datetime_stamp(date_range.get("start") or case.get("date_start"))
            end = _to_xsd_datetime_stamp(date_range.get("end") or case.get("date_end"))
            if start:
                g.add((inv_uri, CAC.hasPhaseBeginPoint,
                       Literal(start, datatype=XSD.dateTimeStamp)))
            if end:
                g.add((inv_uri, CAC.hasPhaseEndPoint,
                       Literal(end, datatype=XSD.dateTimeStamp)))

        return inv_uri

    # ------------------------------------------------------------------
    # Step 2: Platforms
    # ------------------------------------------------------------------

    def map_platforms(
        self,
        g: Graph,
        case: Dict[str, Any],
        inv_uri: URIRef,
        warnings: List[str],
    ) -> List[URIRef]:
        """Create platform nodes (shared singletons) and link to investigation."""
        platforms_raw = case.get("platforms_used") or []
        if isinstance(platforms_raw, str):
            try:
                platforms_raw = json.loads(platforms_raw)
            except (json.JSONDecodeError, TypeError):
                platforms_raw = [platforms_raw]

        # Also pick up p2p_clients and anonymization_network labels
        p2p = case.get("p2p_clients") or []
        anon = case.get("anonymization_network") or []
        all_platforms = list(platforms_raw) + list(p2p) + [
            label for label in anon if label in PLATFORM_MAP
        ]

        uris: List[URIRef] = []
        seen: set = set()
        for label in all_platforms:
            if label in seen:
                continue
            seen.add(label)

            mapping = PLATFORM_MAP.get(label)
            if mapping is None:
                warnings.append(f"PLATFORM_MAP: unmapped label '{label}' — skipped")
                continue

            class_name, extra_props = mapping
            if class_name == _SKIP:
                continue

            class_uri = _PLATFORM_CLASS_URI.get(class_name)
            if class_uri is None:
                warnings.append(f"PLATFORM_MAP: unknown class '{class_name}' for '{label}'")
                continue

            slug = _slug(label)
            p_uri = self._get_or_create_platform(g, slug, label, class_uri, extra_props)
            g.add((inv_uri, CAC.usesChannel, p_uri))
            uris.append(p_uri)

        return uris

    def _get_or_create_platform(
        self,
        g: Graph,
        slug: str,
        label: str,
        class_uri: URIRef,
        extra_props: Dict[str, str],
    ) -> URIRef:
        """Return a shared singleton platform URIRef, creating it if new."""
        uri = self._platform_registry.get(slug)
        if uri is None:
            uri = BASE[f"platform/{slug}"]
            self._platform_registry[slug] = uri
            g.add((uri, RDF.type, class_uri))
            g.add((uri, RDF.type, CAC_CORE.DigitalSystemEntity))
            g.add((uri, RDFS.label, Literal(label)))
            for prop_name, prop_val in extra_props.items():
                prop_uri = CAC_PLATFORMS[prop_name]
                g.add((uri, prop_uri, Literal(prop_val)))
        else:
            # Node already registered; just add triples to current graph
            for triple in [
                (uri, RDF.type, class_uri),
                (uri, RDFS.label, Literal(label)),
            ]:
                g.add(triple)
        return uri

    # ------------------------------------------------------------------
    # Step 3: Topics → Event nodes
    # ------------------------------------------------------------------

    def map_topics(
        self,
        g: Graph,
        case: Dict[str, Any],
        inv_uri: URIRef,
        warnings: List[str],
    ) -> Dict[str, URIRef]:
        """
        Create event nodes from case_topics.

        Returns a dict of {topic_key: event_uri} for use by downstream steps.
        """
        topics_raw = case.get("case_topics") or []
        if isinstance(topics_raw, str):
            try:
                topics_raw = json.loads(topics_raw)
            except (json.JSONDecodeError, TypeError):
                topics_raw = [topics_raw]

        case_id = case.get("id", "unknown")
        event_uris: Dict[str, URIRef] = {}

        # Normalise: if both "csam" and "possession" are present, merge into one CSAMIncident
        topics_set = set(topics_raw)
        if "csam" in topics_set and "possession" in topics_set:
            topics_set.discard("csam")  # keep "possession" to drive the node

        # Determine if grooming is present (for online_only resolution)
        has_grooming = (
            "grooming" in topics_set
            or self._nlp_score(case, "grooming") >= 0.45
        )

        # Multi-jurisdiction: merge international + multi_state into one node
        multi_juris_uri: Optional[URIRef] = None
        has_international = "international" in topics_set
        has_multi_state = "multi_state" in topics_set
        if has_international or has_multi_state:
            mj_uri = BASE[f"case/{case_id}/event/multi-jurisdiction"]
            g.add((mj_uri, RDF.type, CAC_MULTI.MultiJurisdictionalInvestigation))
            g.add((mj_uri, RDF.type, CAC_CORE.Event))
            if has_international:
                g.add((mj_uri, CAC_MULTI.crossesBorders, Literal(True)))
            g.add((inv_uri, CAC.hasStep, mj_uri))
            event_uris["international"] = mj_uri
            event_uris["multi_state"] = mj_uri
            multi_juris_uri = mj_uri
            topics_set.discard("international")
            topics_set.discard("multi_state")

        for topic in topics_set:
            config = TOPIC_MAP.get(topic)
            if config is None:
                warnings.append(f"TOPIC_MAP: unmapped topic '{topic}' — skipped")
                continue

            # Resolve online_only → GroomingSolicitation vs ChildSexualAbuseEvent
            if topic == "online_only":
                class_uri = (
                    config["class_if_grooming"]
                    if has_grooming
                    else config["class"]
                )
            elif topic == "family":
                # "family" topic creates a relationship node, handled in map_roles
                event_uris["family"] = None
                continue
            elif topic == "stranger":
                # handled in map_roles
                event_uris["stranger"] = None
                continue
            else:
                class_uri = config["class"]

            slug_key = _slug(topic)
            evt_uri = BASE[f"case/{case_id}/event/{slug_key}"]
            g.add((evt_uri, RDF.type, class_uri))
            g.add((evt_uri, RDF.type, CAC_CORE.Event))
            g.add((inv_uri, CAC.hasStep, evt_uri))
            event_uris[topic] = evt_uri

        return event_uris

    # ------------------------------------------------------------------
    # Step 4: Roles + Person nodes
    # ------------------------------------------------------------------

    def map_roles(
        self,
        g: Graph,
        case: Dict[str, Any],
        inv_uri: URIRef,
        event_uris: Dict[str, URIRef],
        warnings: List[str],
    ) -> Tuple[List[URIRef], List[URIRef]]:
        """
        Create VictimRole, OffenderRole, and Person nodes.

        Returns (victim_uris, offender_uris).
        """
        case_id = case.get("id", "unknown")
        victim_uris: List[URIRef] = []
        offender_uris: List[URIRef] = []

        # --- Victims ---
        victim_count = case.get("victim_count") or 1
        case_demo = case.get("case_demographics") or {}
        if isinstance(case_demo, str):
            try:
                case_demo = json.loads(case_demo)
            except (json.JSONDecodeError, TypeError):
                case_demo = {}

        age_range = None
        if isinstance(case_demo, dict):
            age_range = case_demo.get("age_range")
            if not age_range and case_demo.get("ages"):
                ages = case_demo["ages"]
                if ages:
                    age_range = {"min": min(ages), "max": max(ages)}

        for n in range(1, int(victim_count) + 1):
            person_uri = BASE[f"case/{case_id}/person/victim/{n}"]
            role_uri = BASE[f"case/{case_id}/role/victim/{n}"]

            g.add((person_uri, RDF.type, UCO_IDENTITY.Person))
            g.add((role_uri, RDF.type, CAC.VictimRole))
            g.add((role_uri, RDF.type, UCO_ROLE.VictimRole))
            g.add((role_uri, CAC_CORE.hasRole, person_uri))
            g.add((inv_uri, CAC.involvesVictim, role_uri))

            if age_range and isinstance(age_range, dict):
                if age_range.get("min") is not None:
                    g.add((person_uri, CAC_PRODUCTION.victimAge,
                           Literal(age_range["min"], datatype=XSD.integer)))

            # Link to event nodes
            for evt_uri in event_uris.values():
                if evt_uri is not None:
                    g.add((evt_uri, CAC.involvesVictim, role_uri))

            victim_uris.append(role_uri)

        # --- Offenders ---
        perp_ages = case.get("perpetrator_age")
        if perp_ages is None:
            perp_ages = []
        elif isinstance(perp_ages, (int, float)):
            perp_ages = [int(perp_ages)]
        elif isinstance(perp_ages, list):
            perp_ages = [int(a) for a in perp_ages if a is not None]
        else:
            perp_ages = []

        perp_count = max(1, int(case.get("perpetrator_count") or len(perp_ages) or 1))
        is_rso = bool(case.get("perpetrator_registered_sex_offender", False))

        for n in range(1, perp_count + 1):
            person_uri = BASE[f"case/{case_id}/person/offender/{n}"]
            role_uri = BASE[f"case/{case_id}/role/offender/{n}"]

            g.add((person_uri, RDF.type, UCO_IDENTITY.Person))
            g.add((role_uri, RDF.type, CAC.OffenderRole))
            g.add((role_uri, RDF.type, UCO_ROLE.OffenderRole))
            g.add((role_uri, CAC_CORE.hasRole, person_uri))
            g.add((inv_uri, CAC.involvesOffender, role_uri))

            # Age (only if we have it for this index)
            if n - 1 < len(perp_ages):
                g.add((person_uri, CAC_DETECTION.ageEstimate,
                       Literal(perp_ages[n - 1], datatype=XSD.integer)))

            if is_rso:
                g.add((role_uri, CAC.perpetratorRegisteredSexOffender,
                       Literal(True, datatype=XSD.boolean)))

            offender_uris.append(role_uri)

        # --- Relationship node ---
        rel = case.get("relationship_to_victim")
        if isinstance(rel, str):
            rel = rel.lower().strip()
        role_config = ROLE_MAP.get(rel) if rel else None

        if role_config:
            rel_class, secondary_class = role_config
            rel_uri = BASE[f"case/{case_id}/relationship/{_slug(rel)}"]
            g.add((rel_uri, RDF.type, rel_class))
            g.add((rel_uri, RDF.type, CAC_CUSTODIAL.CustodialRelationship))
            g.add((rel_uri, CAC_CUSTODIAL.relationshipType, Literal(rel)))

            if victim_uris:
                g.add((rel_uri, CAC_CUSTODIAL.involvesChild, victim_uris[0]))
            for off_uri in offender_uris:
                g.add((rel_uri, CAC_CUSTODIAL.involvesCustodian, off_uri))

            # Trust violation for familial / custodial relationships
            is_familial = rel in {
                "family", "father", "mother", "parent", "brother", "sister",
                "sibling", "uncle", "aunt", "cousin", "guardian",
                "babysitter", "family friend",
            }
            is_professional = rel in {"teacher", "coach", "mentor", "childcare provider"}
            if is_familial or is_professional:
                tv_uri = BASE[f"case/{case_id}/event/trust-violation"]
                g.add((tv_uri, RDF.type, CAC_CUSTODIAL.TrustViolation))
                g.add((tv_uri, RDF.type,
                       CAC_CUSTODIAL.CustodialAbuse if is_familial
                       else CAC_CUSTODIAL.AuthorityAbuse))
                g.add((tv_uri, CAC_CUSTODIAL.violatesRelationship, rel_uri))
                g.add((inv_uri, CAC.hasStep, tv_uri))
        elif rel and rel not in ("stranger", "unknown", ""):
            warnings.append(f"ROLE_MAP: unmapped relationship '{rel}' — OffenderRole only")

        return victim_uris, offender_uris

    # ------------------------------------------------------------------
    # Step 5: Severity → event properties + conspiracy node
    # ------------------------------------------------------------------

    def map_severity(
        self,
        g: Graph,
        case: Dict[str, Any],
        event_uris: Dict[str, URIRef],
        offender_uris: List[URIRef],
        warnings: List[str],
    ) -> None:
        """Apply severity indicators to event nodes and create conspiracy node if needed."""
        severity_raw = case.get("severity_indicators") or []
        if isinstance(severity_raw, str):
            try:
                severity_raw = json.loads(severity_raw)
            except (json.JSONDecodeError, TypeError):
                severity_raw = [severity_raw]

        case_id = case.get("id", "unknown")

        max_level = 0
        create_conspiracy = False

        for indicator in severity_raw:
            config = SEVERITY_MAP.get(indicator)
            if config is None:
                warnings.append(f"SEVERITY_MAP: unmapped indicator '{indicator}' — skipped")
                continue
            level, extra_class = config
            max_level = max(max_level, level)
            if indicator == "multiple_perpetrators":
                create_conspiracy = True

        # Apply severityLevel to all event nodes
        if max_level > 0:
            for evt_uri in event_uris.values():
                if evt_uri is not None:
                    g.add((evt_uri, CAC.severityLevel,
                           Literal(max_level, datatype=XSD.integer)))

        # Conspiracy node for multiple perpetrators
        if create_conspiracy and len(offender_uris) > 1:
            conspiracy_uri = BASE[f"case/{case_id}/event/conspiracy"]
            g.add((conspiracy_uri, RDF.type, CAC.ConspiracyToCommitCSA))
            g.add((conspiracy_uri, RDF.type, CAC_CORE.Event))
            g.add((conspiracy_uri, CAC.conspiracyMemberCount,
                   Literal(len(offender_uris), datatype=XSD.integer)))
            inv_uri = BASE[f"case/{case_id}"]
            g.add((inv_uri, CAC.hasStep, conspiracy_uri))
            for off_uri in offender_uris:
                g.add((conspiracy_uri, CAC.participatesInConspiracy, off_uri))

    # ------------------------------------------------------------------
    # Step 5b: Investigation type → operation node
    # ------------------------------------------------------------------

    def map_investigation_type(
        self,
        g: Graph,
        case: Dict[str, Any],
        inv_uri: URIRef,
        warnings: List[str],
    ) -> Optional[URIRef]:
        """Create a TaskForce operation node from investigation_type."""
        inv_type = (case.get("investigation_type") or "").lower().strip()
        if not inv_type:
            return None

        op_class = INVESTIGATION_TYPE_MAP.get(inv_type)
        if op_class is None and inv_type != "unknown":
            warnings.append(f"INVESTIGATION_TYPE_MAP: unmapped type '{inv_type}' — skipped")
            return None
        if inv_type == "unknown":
            g.add((inv_uri, CAC.investigationStatus, Literal("unknown")))
            return None

        case_id = case.get("id", "unknown")
        op_uri = BASE[f"case/{case_id}/operation"]
        g.add((op_uri, RDF.type, op_class))
        g.add((op_uri, RDF.type, CAC_CORE.Event))
        g.add((inv_uri, CAC.hasStep, op_uri))
        return op_uri

    # ------------------------------------------------------------------
    # Step 5c: SHACL-required temporal triples on roles
    # ------------------------------------------------------------------

    def _apply_role_temporal(
        self,
        g: Graph,
        case: Dict[str, Any],
        victim_uris: List[URIRef],
        offender_uris: List[URIRef],
    ) -> None:
        """
        Set cacontology:hasRoleBeginPoint on every Role node.
        Uses date_start (or date_range.start) as the begin point.
        This satisfies the SHACL MinCount constraint on Role nodes.
        """
        date_range = case.get("date_range") or {}
        start = _to_xsd_datetime_stamp(
            (date_range.get("start") if isinstance(date_range, dict) else None)
            or case.get("date_start")
        )
        if not start:
            return

        begin_lit = Literal(start, datatype=XSD.dateTimeStamp)
        for uri in victim_uris + offender_uris:
            g.add((uri, CAC.hasRoleBeginPoint, begin_lit))

    # ------------------------------------------------------------------
    # Step 5d: SHACL-required structural triples
    # ------------------------------------------------------------------

    def _apply_shacl_required_triples(
        self,
        g: Graph,
        case: Dict[str, Any],
        event_uris: Dict[str, URIRef],
        victim_uris: List[URIRef],
        offender_uris: List[URIRef],
    ) -> None:
        """
        Apply SHACL-required triples that the shapes validate:

        1. CSAMIncident → uco-core:hasFacet (ContentDataFacet stub)
        2. ChildSexualAbuseEvent → victim/offender roles via
           cacontology:participatesInEvent (SPARQL shape checks this)
        """
        case_id = case.get("id", "unknown")
        UCO_OBS = Namespace("https://ontology.unifiedcyberontology.org/uco/observable/")

        for topic, evt_uri in event_uris.items():
            if evt_uri is None:
                continue

            # CSAMIncident → add a minimal ContentDataFacet
            is_csam = (
                (evt_uri, RDF.type, CAC.CSAMIncident) in g
                or (evt_uri, RDF.type, CAC_PRODUCTION.ProductionOffense) in g
            )
            if is_csam:
                facet_uri = BASE[f"case/{case_id}/facet/{_slug(topic)}"]
                g.add((facet_uri, RDF.type, UCO_OBS.ContentDataFacet))
                g.add((evt_uri, UCO_CORE.hasFacet, facet_uri))

            # ChildSexualAbuseEvent (and subclasses) → participatesInEvent on roles
            is_csa_event = any(
                (evt_uri, RDF.type, cls) in g
                for cls in [
                    CAC.ChildSexualAbuseEvent,
                    CAC.CSAMIncident,
                    CAC_PRODUCTION.ProductionOffense,
                    CAC.GroomingSolicitation,
                    CAC_SEXTORTION.SextortionIncident,
                ]
            )
            if is_csa_event:
                for v_uri in victim_uris:
                    g.add((v_uri, CAC.participatesInEvent, evt_uri))
                for o_uri in offender_uris:
                    g.add((o_uri, CAC.participatesInEvent, evt_uri))

    # ------------------------------------------------------------------
    # Step 6: Prosecution
    # ------------------------------------------------------------------

    def map_prosecution(
        self,
        g: Graph,
        case: Dict[str, Any],
        inv_uri: URIRef,
        warnings: List[str],
    ) -> None:
        """Create CriminalCharge, CriminalSentence, and Phase nodes."""
        case_id = case.get("id", "unknown")

        prosecution = case.get("prosecution_outcome")
        if not prosecution and case.get("prosecution_outcomes"):
            rows = case["prosecution_outcomes"]
            if rows:
                prosecution = rows[0]

        if not prosecution or not isinstance(prosecution, dict):
            return

        # Status → phase
        status = (
            prosecution.get("booking_status")
            or prosecution.get("status")
            or ""
        ).lower().strip()
        phase_class = PROSECUTION_STATUS_MAP.get(status)
        if phase_class:
            phase_uri = BASE[f"case/{case_id}/phase/{_slug(status)}"]
            g.add((phase_uri, RDF.type, phase_class))
            g.add((phase_uri, RDF.type, CAC_CORE.Phase))
            g.add((inv_uri, CAC.hasPhase, phase_uri))
            g.add((inv_uri, CAC.currentPhase, phase_uri))
            # SHACL: every Phase node requires a begin point. Use the case's
            # date_start as a best-available approximation (the prosecution
            # phase typically begins during the case lifecycle).
            date_range = case.get("date_range") or {}
            start = _to_xsd_datetime_stamp(
                (date_range.get("start") if isinstance(date_range, dict) else None)
                or case.get("date_start")
            )
            if start:
                g.add((phase_uri, CAC.hasPhaseBeginPoint,
                       Literal(start, datatype=XSD.dateTimeStamp)))
        elif status:
            warnings.append(f"PROSECUTION_STATUS_MAP: unmapped status '{status}' — skipped")

        # Charges
        charges_raw = prosecution.get("charges") or []
        if isinstance(charges_raw, str):
            try:
                charges_raw = json.loads(charges_raw)
            except (json.JSONDecodeError, TypeError):
                charges_raw = []

        for i, charge in enumerate(charges_raw, start=1):
            if isinstance(charge, dict):
                charge_str = str(charge.get("charge") or "")
                count = charge.get("count", 1)
            else:
                charge_str = str(charge)
                count = 1

            charge_class = self._match_charge(charge_str, warnings)
            if charge_class is None:
                continue

            charge_uri = BASE[f"case/{case_id}/charge/{i}"]
            g.add((charge_uri, RDF.type, charge_class))
            g.add((charge_uri, RDF.type, CAC_LEGAL.CriminalCharge))
            if count and count != 1:
                g.add((charge_uri, CAC_LEGAL.indictmentCounts,
                       Literal(int(count), datatype=XSD.integer)))
            g.add((charge_uri, RDFS.label, Literal(charge_str)))
            g.add((inv_uri, CAC_LEGAL.hasCharge, charge_uri))

        # Sentence
        jail_str = str(prosecution.get("jail") or prosecution.get("sentences") or "")
        if jail_str:
            sentence_class = self._match_sentence(jail_str)
            sent_uri = BASE[f"case/{case_id}/sentence/1"]
            g.add((sent_uri, RDF.type, sentence_class))
            g.add((sent_uri, RDF.type, CAC_LEGAL.CriminalSentence))
            g.add((sent_uri, RDFS.label, Literal(jail_str)))
            g.add((inv_uri, CAC_LEGAL.resultsSentence, sent_uri))

    # ------------------------------------------------------------------
    # Step 7: Agencies
    # ------------------------------------------------------------------

    def map_agencies(
        self,
        g: Graph,
        case: Dict[str, Any],
        inv_uri: URIRef,
        warnings: List[str],
    ) -> List[URIRef]:
        """Create agency nodes (shared singletons) and link to investigation."""
        agencies_raw = case.get("agencies_involved") or []
        if isinstance(agencies_raw, str):
            try:
                agencies_raw = json.loads(agencies_raw)
            except (json.JSONDecodeError, TypeError):
                agencies_raw = [agencies_raw]

        case_id = case.get("id", "unknown")
        uris: List[URIRef] = []
        seen: set = set()

        for agency_name in agencies_raw:
            if not agency_name or agency_name in seen:
                continue
            seen.add(agency_name)

            slug, class_uri = self._classify_agency(agency_name)
            ag_uri = self._get_or_create_agency(g, slug, agency_name, class_uri)

            # NCMEC also triggers a CyberTipline node
            if re.search(r"\bNCMEC\b|National Center for Missing", agency_name, re.I):
                tip_uri = BASE[f"case/{case_id}/cybertip"]
                g.add((tip_uri, RDF.type, CAC_NCMEC.NCMECCybertipReport))
                g.add((tip_uri, CAC_NCMEC.supportedBy, ag_uri))
                g.add((inv_uri, CAC.hasStep, tip_uri))

            g.add((inv_uri, CAC_MULTI.involvesAgency, ag_uri))
            uris.append(ag_uri)

        return uris

    def _classify_agency(
        self, name: str
    ) -> Tuple[str, URIRef]:
        """Return (slug, CAC agency class URI) for an agency name string."""
        for pattern, fixed_slug in _FEDERAL_PATTERNS:
            if pattern.search(name):
                return fixed_slug, CAC_MULTI.FederalAgency

        if _ICAC_PATTERN.search(name):
            return _slug(name), CAC_TASKFORCE.StateICACtaskForce

        if _STATE_ATTORNEY_PATTERN.search(name):
            return _slug(name), CAC_MULTI.StateAgency

        return _slug(name), CAC_MULTI.LocalAgency

    def _get_or_create_agency(
        self,
        g: Graph,
        slug: str,
        label: str,
        class_uri: URIRef,
    ) -> URIRef:
        """Return shared singleton agency URIRef, creating it if new."""
        uri = self._agency_registry.get(slug)
        if uri is None:
            uri = BASE[f"agency/{slug}"]
            self._agency_registry[slug] = uri
            g.add((uri, RDF.type, class_uri))
            g.add((uri, RDF.type, CAC_CORE.OrganizationLikeEntity))
            g.add((uri, RDFS.label, Literal(label)))
        else:
            g.add((uri, RDF.type, class_uri))
        return uri

    # ------------------------------------------------------------------
    # Step 8: Technology signals
    # ------------------------------------------------------------------

    def map_technology(
        self,
        g: Graph,
        case: Dict[str, Any],
        inv_uri: URIRef,
        warnings: List[str],
    ) -> None:
        """Create detection technology, anonymization network, and P2P nodes."""
        case_id = case.get("id", "unknown")

        # Investigation technology
        for tech in (case.get("investigation_technology") or []):
            class_uri = INVESTIGATION_TECH_MAP.get(tech)
            if class_uri is None:
                warnings.append(f"TECHNOLOGY_MAP: unmapped tech '{tech}' — skipped")
                continue
            slug = _slug(tech)
            tech_uri = BASE[f"case/{case_id}/tech/{slug}"]
            g.add((tech_uri, RDF.type, class_uri))
            g.add((tech_uri, RDFS.label, Literal(tech)))
            g.add((inv_uri, CAC.usesMethod, tech_uri))

        # Anonymization networks
        for net in (case.get("anonymization_network") or []):
            class_uri = ANON_NETWORK_MAP.get(net)
            if class_uri is None:
                warnings.append(f"ANON_MAP: unmapped network '{net}' — skipped")
                continue
            slug = _slug(net)
            plat_uri = self._get_or_create_platform(
                g, slug, net, class_uri, {}
            )
            g.add((inv_uri, CAC.usesChannel, plat_uri))

    # ------------------------------------------------------------------
    # Step 9: NLP features (separate named graph)
    # ------------------------------------------------------------------

    def map_nlp_features(
        self,
        g: Graph,
        case: Dict[str, Any],
        inv_uri: URIRef,
        warnings: List[str],
    ) -> None:
        """
        Map NLP-derived semantic concept scores into the NLP named graph.
        Each node gets a cac-core:hasConfidence annotation.
        """
        case_id = case.get("id", "unknown")
        ml = case.get("ml_features") or {}
        if isinstance(ml, str):
            try:
                ml = json.loads(ml)
            except (json.JSONDecodeError, TypeError):
                ml = {}

        semantic = ml.get("semantic_severity") or {}
        scores = semantic.get("scores") or {}
        if not scores:
            return

        for concept, (threshold, class_uri) in NLP_CONCEPT_MAP.items():
            score = scores.get(concept)
            if score is None:
                continue
            if score < threshold:
                continue

            # registered_sex_offender → flag on offender roles, not a separate node
            if concept == "registered_sex_offender":
                for n in range(1, 10):
                    off_uri = BASE[f"case/{case_id}/role/offender/{n}"]
                    # Add triple only if role node was already created (check existence)
                    if (off_uri, RDF.type, None) in g:
                        g.add((off_uri, CAC.perpetratorRegisteredSexOffender,
                               Literal(True, datatype=XSD.boolean)))
                continue

            if class_uri is None:
                continue

            slug = _slug(concept)
            node_uri = BASE[f"case/{case_id}/nlp/{slug}"]
            g.add((node_uri, RDF.type, class_uri))
            g.add((node_uri, RDF.type, CAC_CORE.Event))

            result_uri = BASE[f"case/{case_id}/nlp/{slug}/confidence"]
            g.add((result_uri, RDF.type, CAC_CORE.AssessmentResult))
            g.add((result_uri, CAC_CORE.hasConfidence,
                   Literal(round(float(score), 4), datatype=XSD.decimal)))
            g.add((result_uri, CAC_CORE.assesses, node_uri))
            g.add((result_uri, CAC_CORE.generatedBy, inv_uri))

            g.add((inv_uri, CAC.hasStep, node_uri))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _nlp_score(case: Dict[str, Any], concept: str) -> float:
        """Safely extract a semantic concept score from ml_features."""
        ml = case.get("ml_features") or {}
        if isinstance(ml, str):
            try:
                ml = json.loads(ml)
            except (json.JSONDecodeError, TypeError):
                return 0.0
        return float(
            (ml.get("semantic_severity") or {}).get("scores", {}).get(concept, 0.0)
        )

    @staticmethod
    def _match_charge(charge_str: str, warnings: List[str]) -> Optional[URIRef]:
        """Match a charge string to a CAC charge class via pattern table."""
        lower = charge_str.lower()
        for pattern, class_uri in CHARGE_PATTERN_MAP:
            if pattern.lower() in lower:
                return class_uri
        warnings.append(
            f"CHARGE_MAP: could not classify charge '{charge_str}' — skipped"
        )
        return None

    @staticmethod
    def _match_sentence(sent_str: str) -> URIRef:
        """Match a sentence string to a CAC sentence class."""
        lower = sent_str.lower()
        for pattern, class_uri in SENTENCE_PATTERN_MAP:
            if re.search(pattern, lower):
                return class_uri
        return CAC_LEGAL.PrisonSentence  # safe default

    @staticmethod
    def _bind_namespaces(g: Graph) -> None:
        """Bind all namespace prefixes onto a graph."""
        g.bind("caselinker", BASE)
        g.bind("cacontology", CAC)
        g.bind("cac-core", CAC_CORE)
        g.bind("cacontology-grooming", CAC_GROOMING)
        g.bind("cacontology-custodial", CAC_CUSTODIAL)
        g.bind("cacontology-platforms", CAC_PLATFORMS)
        g.bind("cacontology-legal-outcomes", CAC_LEGAL)
        g.bind("cacontology-sextortion", CAC_SEXTORTION)
        g.bind("cacontology-detection", CAC_DETECTION)
        g.bind("cacontology-production", CAC_PRODUCTION)
        g.bind("cacontology-taskforce", CAC_TASKFORCE)
        g.bind("cacontology-us-ncmec", CAC_NCMEC)
        g.bind("cacontology-multi", CAC_MULTI)
        g.bind("uco-core", UCO_CORE)
        g.bind("uco-identity", UCO_IDENTITY)
        g.bind("uco-role", UCO_ROLE)
        g.bind("uco-location", UCO_LOCATION)
        g.bind("gufo", GUFO)
        g.bind("dcterms", DCTERMS)
        g.bind("skos", SKOS)

    @staticmethod
    def _graph_summary(cg: ConjunctiveGraph) -> Dict[str, Any]:
        """Count nodes, edges, and node types across all named graphs."""
        subjects: set = set()
        predicates: set = set()
        type_counts: Dict[str, int] = {}
        edge_count = 0

        for ctx in cg.graphs():
            for s, p, o in ctx:
                subjects.add(s)
                edge_count += 1
                if p == RDF.type and isinstance(o, URIRef):
                    label = o.split("#")[-1].split("/")[-1]
                    type_counts[label] = type_counts.get(label, 0) + 1

        return {
            "node_count": len(subjects),
            "edge_count": edge_count,
            "node_types": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        }

    @staticmethod
    def _load_from_db(
        case_id: str, db_url: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Load a case dict from a database.

        Priority order:
          1. Local SQLite (caselinker.db at repo root, configured via config.DATABASE_PATH)
          2. PostgreSQL via DATABASE_URL (when running against the cloud DB)
        Returns None if neither is available or the case is not found.
        """
        # ── 1. Local SQLite via storage.CaseStorage ──────────────────────────
        case = CaseToCAC._load_from_local_sqlite(case_id)
        if case is not None:
            return case

        # ── 2. PostgreSQL fallback ───────────────────────────────────────────
        url = db_url or os.getenv("DATABASE_URL")
        if not url:
            return None
        try:
            storage_layer_dir = str(_REPO_ROOT / "src" / "Storage Layer")
            if storage_layer_dir not in sys.path:
                sys.path.insert(0, storage_layer_dir)
            # Local import: storage_postgres is a sibling of storage.py
            from storage_postgres import CaseStorage as PgCaseStorage  # type: ignore
            return PgCaseStorage().get_case(case_id)
        except Exception as exc:
            logger.warning("PostgreSQL load failed for '%s': %s", case_id, exc)
            return None

    @staticmethod
    def _load_from_local_sqlite(case_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a case from the local SQLite DB (caselinker.db) using the
        CaseLinker SQLite CaseStorage class. Returns None if the DB file is
        absent, the module fails to import, or the case is not found.
        """
        # Try repo-root caselinker.db first, then DATABASE_PATH from config
        db_path = _REPO_ROOT / "caselinker.db"
        if not db_path.is_file():
            try:
                cfg_path = _REPO_ROOT / "config.py"
                if cfg_path.is_file():
                    cfg_ns: Dict[str, Any] = {}
                    exec(cfg_path.read_text(), cfg_ns)
                    configured = cfg_ns.get("DATABASE_PATH")
                    if configured:
                        candidate = Path(configured)
                        if not candidate.is_absolute():
                            candidate = _REPO_ROOT / candidate
                        if candidate.is_file():
                            db_path = candidate
            except Exception as exc:
                logger.debug("config.py lookup failed: %s", exc)

        if not db_path.is_file():
            return None

        try:
            storage_layer_dir = str(_REPO_ROOT / "src" / "Storage Layer")
            if storage_layer_dir not in sys.path:
                sys.path.insert(0, storage_layer_dir)
            # storage.py imports case_storage_utils via top-level name, so the
            # "Storage Layer" dir must be on sys.path before the import.
            from storage import CaseStorage as SqliteCaseStorage  # type: ignore
            return SqliteCaseStorage(db_path=str(db_path)).get_case(case_id)
        except Exception as exc:
            logger.warning("SQLite load failed for '%s' (db=%s): %s",
                           case_id, db_path, exc)
            return None


# ===========================================================================
# Test fixture
# ===========================================================================

AZICAC_2011_006_FIXTURE: Dict[str, Any] = {
    "id": "azicac_2011_006",
    "source": "AZICAC",
    "source_url": None,
    "date_start": "2011",
    "date_end": "2011",
    "date_range": {"start": "2011", "end": "2011"},
    "victim_count": 1,
    "perpetrator_count": 2,
    "case_demographics": {
        "ages": [8],
        "age_range": {"min": 8, "max": 8},
        "gender": "unknown",
    },
    "perpetrator_age": [32, 41],
    "perpetrator_registered_sex_offender": False,
    "relationship_to_victim": "family",
    "previous_conviction": None,
    "platforms_used": [],
    "p2p_clients": ["LimeWire"],
    "anonymization_network": [],
    "investigation_type": "proactive",
    "agencies_involved": ["FBI", "AZICAC", "Maricopa County Attorney's Office"],
    "organizations": ["Maricopa County Attorney's Office"],
    "locations": ["Mesa, Arizona"],
    "prosecution_outcome": {
        "booking_status": "convicted",
        "charges": [
            {"count": 1, "charge": "CSAM Production"},
            {"count": 1, "charge": "CSAM Production"},
        ],
        "jail": "15 years",
    },
    "prosecution_outcomes": [],
    "evidence_volume": {
        "images": None,
        "videos": None,
        "storage_size": None,
        "messages": None,
    },
    "severity_indicators": ["under_12", "sexual_abuse", "multiple_perpetrators"],
    "case_topics": ["production", "hands_on", "family", "csam"],
    "severity_phrases": ["dangerous"],
    "investigation_technology": [],
    "tags": [],
    "notes": None,
    "ml_features": {
        "semantic_severity": {
            "scores": {
                "grooming": 0.31,
                "production_csam": 0.72,
                "possession_csam": 0.28,
                "sextortion": 0.12,
                "dissemination": 0.20,
                "evidence_seizure": 0.48,
                "exploitive_positions": 0.51,
                "registered_sex_offender": 0.30,
            },
            "phrases": ["dangerous"],
            "concept_metadata": {"model": "all-MiniLM-L6-v2", "threshold": 0.35},
        }
    },
    "created_at": "2026-05-26T00:00:00",
    "updated_at": "2026-05-26T00:00:00",
}

# Expected node types from MAPPING_PLAN.md §6.2
_EXPECTED_NODE_TYPES = {
    "CACInvestigation",
    "ProductionOffense",
    "ChildSexualAbuseEvent",
    "ConspiracyToCommitCSA",
    "VictimRole",
    "OffenderRole",
    "Person",
    "FamilialRelationship",
    "CustodialAbuse",
    "FileHostingService",       # LimeWire (p2p)
    "ProactiveOperation",
    "FederalAgency",
    "StateICACtaskForce",
    "StateAgency",
    "CSAM_Production",
    "PrisonSentence",
    "SentencingPhase",
}


# ===========================================================================
# CLI / test runner
# ===========================================================================

def run_test(case_dict: Dict[str, Any], output_dir: Path) -> None:
    """
    Map a case, validate, write output, and print a summary report.

    Compares actual node types against expected types from MAPPING_PLAN.md §6.2.
    """
    case_id = case_dict.get("id", "unknown")
    print(f"\n{'='*60}")
    print(f"  CaseLinker → CAC Ontology Test Run")
    print(f"  Case: {case_id}")
    print(f"{'='*60}\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    mapper = CaseToCAC()
    graph, warnings = mapper.map_case(case_dict)
    summary = mapper._graph_summary(graph)

    # Write outputs
    jsonld_path = output_dir / f"{case_id}.jsonld"
    ttl_path = output_dir / f"{case_id}.ttl"
    graph.serialize(destination=str(jsonld_path), format="json-ld", indent=2)

    # Turtle does not preserve named graphs — flatten the Dataset's named
    # graphs into a single rdflib.Graph for the .ttl file so it is non-empty
    # and usable for SPARQL / inspection.
    flat = Graph()
    for ctx in graph.graphs():
        for triple in ctx:
            flat.add(triple)
    for prefix, ns in graph.namespaces():
        flat.bind(prefix, ns, replace=True)
    flat.serialize(destination=str(ttl_path), format="turtle")

    print(f"Output files written:")
    print(f"  {jsonld_path}")
    print(f"  {ttl_path}")
    print()

    # Node / edge counts
    print(f"Graph statistics:")
    print(f"  Nodes (unique subjects): {summary['node_count']}")
    print(f"  Edges (triples):         {summary['edge_count']}")
    print()

    # Node type breakdown
    print("Node types created:")
    for type_name, count in summary["node_types"].items():
        print(f"  {count:3d}  {type_name}")
    print()

    # Warnings
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ⚠  {w}")
    else:
        print("Warnings: none")
    print()

    # Expected vs actual node type comparison
    actual_types = set(summary["node_types"].keys())
    missing = _EXPECTED_NODE_TYPES - actual_types
    unexpected = actual_types - _EXPECTED_NODE_TYPES - {
        # These are acceptable additions not in the original plan
        "EnduringEntity", "Event", "Phase", "Role", "AssessmentResult",
        "CriminalCharge", "CriminalSentence", "TrustViolation",
        "OrganizationLikeEntity", "DigitalSystemEntity", "CustodialRelationship",
    }

    print("MAPPING_PLAN.md §6.2 node type comparison:")
    if not missing:
        print("  ✓ All expected node types present")
    else:
        print(f"  ✗ Missing expected types ({len(missing)}):")
        for t in sorted(missing):
            print(f"      - {t}")

    if unexpected:
        print(f"  + Unexpected (but valid) types ({len(unexpected)}):")
        for t in sorted(unexpected):
            print(f"      + {t}")
    print()

    # SHACL validation
    print("SHACL validation:")
    conforms, shacl_report = mapper.validate(graph)
    if conforms:
        print("  ✓ Conforms — all SHACL constraints satisfied")
    else:
        print("  ✗ Does not fully conform")
        if shacl_report:
            for line in shacl_report.splitlines()[:40]:
                print(f"    {line}")
            if len(shacl_report.splitlines()) > 40:
                print(f"    ... ({len(shacl_report.splitlines()) - 40} more lines)")
    print()

    print("Status: MAPPED ✓" + ("  VALID ✓" if conforms else "  VALID ✗"))
    print()


def _load_case_with_fallback(case_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Load a case for the CLI runner.

    Returns ``(case_dict, source)`` where source is one of:
      ``"sqlite"``, ``"postgres"``, ``"fixture"``, ``"missing"``.

    Fixture is only used as a last-resort training-wheels fallback for
    azicac_2011_006 when no DB is reachable.
    """
    sqlite_case = CaseToCAC._load_from_local_sqlite(case_id)
    if sqlite_case is not None:
        return sqlite_case, "sqlite"

    if os.getenv("DATABASE_URL"):
        pg_case = CaseToCAC._load_from_db(case_id)
        if pg_case is not None:
            return pg_case, "postgres"

    if case_id == "azicac_2011_006":
        return AZICAC_2011_006_FIXTURE, "fixture"

    return None, "missing"


def main() -> None:
    """
    CLI entry point.

    Default behaviour: load real cases from the local SQLite DB
    (caselinker.db at the repo root). PostgreSQL is used as a fallback
    when DATABASE_URL is set. The azicac_2011_006 fixture is the last
    resort and is only kept as training wheels for environments without
    any DB.

    Usage::

        python features_to_cac.py
            → loads azicac_2011_006 from local DB (or fixture if DB absent)

        python features_to_cac.py <case_id> [<case_id> ...]
            → loads each case_id from local DB and writes its graph
    """
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    case_ids: List[str] = sys.argv[1:] if len(sys.argv) > 1 else ["azicac_2011_006"]

    print(f"Loading {len(case_ids)} case(s) from local SQLite DB at "
          f"{_REPO_ROOT / 'caselinker.db'}")
    print()

    overall_ok = True
    for case_id in case_ids:
        case, source = _load_case_with_fallback(case_id)
        if case is None:
            print(f"✗ '{case_id}' not found in any data source (sqlite/postgres/fixture)")
            overall_ok = False
            continue

        marker = {
            "sqlite":   "  → loaded from LOCAL SQLite",
            "postgres": "  → loaded from PostgreSQL (DATABASE_URL)",
            "fixture":  "  → loaded from in-code FIXTURE (training wheels)",
        }.get(source, "")
        print(marker)
        run_test(case, _TEST_OUTPUT_DIR)

    if not overall_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
