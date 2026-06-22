"""CAC ontology IRIs for PACER state machines (read from ontology, not hardcoded from memory)."""

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
STATE_MACHINES_WORKSPACE = PKG_DIR
REPO_ROOT = PKG_DIR.parent
ONTOLOGY_DIR = REPO_ROOT / "ontology"
GRAPHS_DIR = PKG_DIR / "graphs"
LSTAR_JSON = PKG_DIR / "data" / "lstar_all_cases.json"

CORE_NS = "https://cacontology.projectvic.org/core#"
CAC_NS = "https://cacontology.projectvic.org#"
GROOMING_NS = "https://cacontology.projectvic.org/grooming#"
SEXTORTION_NS = "https://cacontology.projectvic.org/sextortion#"
PLATFORMS_NS = "https://cacontology.projectvic.org/platforms#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
RDFS_SUBCLASS_OF = "http://www.w3.org/2000/01/rdf-schema#subClassOf"

# Must match cac-core:precedes in cacontology-core-spine.ttl (source of truth).
PRECEDES = "https://cacontology.projectvic.org/core#precedes"
HAS_STEP = f"{CAC_NS}hasStep"
CAC_INVESTIGATION = f"{CAC_NS}CACInvestigation"
PHASE = f"{CORE_NS}Phase"

INITIAL_CONTACT_PHASE = f"{GROOMING_NS}InitialContactPhase"
TRUST_BUILDING_PHASE = f"{GROOMING_NS}TrustBuildingPhase"
SEXUALIZATION_PHASE = f"{GROOMING_NS}SexualizationPhase"
EXPLOITATION_PHASE = f"{GROOMING_NS}ExploitationPhase"
MAINTENANCE_PHASE = f"{GROOMING_NS}MaintenancePhase"
THREAT_MECHANISM = f"{SEXTORTION_NS}ThreatMechanism"
COERCION_CYCLE = f"{SEXTORTION_NS}CoercionCycle"
CHANNEL_MIGRATION_EVENT = f"{PLATFORMS_NS}ChannelMigrationEvent"

AFFORDANCE_MISUSE = f"{PLATFORMS_NS}AffordanceMisuse"
ENABLES_TRANSITION_FROM = f"{PLATFORMS_NS}enablesTransitionFrom"
ENABLES_TRANSITION_TO = f"{PLATFORMS_NS}enablesTransitionTo"
AFFORDANCE_CLASS = f"{PLATFORMS_NS}affordanceClass"
MISUSE_DESCRIPTION = f"{PLATFORMS_NS}misuseDescription"

ANONYMITY = f"{PLATFORMS_NS}Anonymity"
EPHEMERALITY = f"{PLATFORMS_NS}Ephemerality"
UNMONITORED_COMMUNICATION = f"{PLATFORMS_NS}UnmonitoredCommunication"
CONTACT_DISCOVERY = f"{PLATFORMS_NS}ContactDiscovery"
DISTRIBUTION_INFRASTRUCTURE = f"{PLATFORMS_NS}DistributionInfrastructure"
COORDINATION = f"{PLATFORMS_NS}Coordination"
COERCION_LEVERAGE = f"{PLATFORMS_NS}CoercionLeverage"

CASE_FILES = (
    "enticement.jsonld",
    "production.jsonld",
    "sextortion.jsonld",
    "enterprise.jsonld",
    "trafficking.jsonld",
)

CASE_META = {
    "enticement": {
        "title": "ENTICEMENT",
        "citation": "United States v. Rehman (D.D.C. 1:23-cr-00064)",
    },
    "sextortion": {
        "title": "SEXTORTION",
        "citation": "United States v. Amin (D. Alaska 3:22-cr-00055)",
    },
    "production": {
        "title": "PRODUCTION",
        "citation": "United States v. Pathmanathan (D.D.C. 1:22-cr-00150)",
    },
    "enterprise": {
        "title": "ENTERPRISE",
        "citation": "United States v. Bermudez et al. (E.D.N.Y. 1:25-cr-00361)",
    },
    "trafficking": {
        "title": "TRAFFICKING",
        "citation": "United States v. Riley (D. Haw. 1:23-cr-00071)",
    },
}


def local_name(iri: str) -> str:
    if "#" in iri:
        return iri.rsplit("#", 1)[-1]
    return iri.rstrip("/").rsplit("/", 1)[-1]


def display_type(iri: str) -> str:
    name = local_name(iri)
    if iri.startswith(GROOMING_NS):
        return f"cacontology-grooming:{name}"
    if iri.startswith(SEXTORTION_NS):
        return f"cacontology-sextortion:{name}"
    if iri.startswith(PLATFORMS_NS):
        return f"cacontology-platforms:{name}"
    if iri.startswith(CORE_NS):
        return f"cac-core:{name}"
    return name
