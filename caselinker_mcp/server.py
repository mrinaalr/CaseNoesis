"""CaseLinker MCP server — structured tools over the CaseLinker REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from caselinker_mcp.client import BULK_TIMEOUT, api_get, api_post, require_caselinker_key

PORT = int(os.getenv("PORT", 8001))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")

_GRAPH_TTL = 7200
_GRAPH_KEY_PREFIX = "caselinker:mcp:graph:"
_graph_store: dict[str, dict[str, Any]] = {}

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ONTOLOGY_DIR = _REPO_ROOT / "ontology"
_RUN_DIR = _REPO_ROOT / "run"
if str(_ONTOLOGY_DIR) not in sys.path:
    sys.path.insert(0, str(_ONTOLOGY_DIR))
if str(_RUN_DIR) not in sys.path:
    sys.path.insert(0, str(_RUN_DIR))

_redis_available = False
try:
    from redis_cache import REDIS_AVAILABLE as _redis_available
    from redis_cache import get_cached as _redis_get_cached
    from redis_cache import set_cached as _redis_set_cached
except ImportError:
    _redis_get_cached = None
    _redis_set_cached = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [caselinker_mcp] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("caselinker_mcp")

# message_path without trailing slash: Mount("/messages/") 307-redirects POST /messages,
# which breaks MCP clients that strip the slash when parsing the SSE endpoint event.
mcp = FastMCP("CaseLinker", message_path="/messages")

# Tag string -> API category for POST /api/return-tagged-cases
_TAG_CATEGORIES: dict[str, str] = {
    # case_topics
    "csam": "case_topics",
    "production": "case_topics",
    "possession": "case_topics",
    "online_only": "case_topics",
    "hands_on": "case_topics",
    "multi_state": "case_topics",
    "international": "case_topics",
    "family": "case_topics",
    "stranger": "case_topics",
    # severity_indicators
    "infant": "severity_indicators",
    "very_young": "severity_indicators",
    "under_10": "severity_indicators",
    "under_12": "severity_indicators",
    "rape": "severity_indicators",
    "physical_abuse": "severity_indicators",
    # investigation_type
    "proactive": "investigation_type",
    "reactive": "investigation_type",
    "undercover": "investigation_type",
    "cybertipline": "investigation_type",
    "online": "investigation_type",
    # perpetrator_status
    "registered_sex_offender": "registered_sex_offender",
    # platforms_used (common examples; unknown platform-like tags default here)
    "facebook": "platforms_used",
    "discord": "platforms_used",
    "kik": "platforms_used",
    "telegram": "platforms_used",
    "roblox": "platforms_used",
    "snapchat": "platforms_used",
    "instagram": "platforms_used",
    "tiktok": "platforms_used",
    "twitter": "platforms_used",
    "skype": "platforms_used",
    "omegle": "platforms_used",
    "minecraft": "platforms_used",
    "tor": "platforms_used",
    "dark_web": "platforms_used",
    "dropbox": "platforms_used",
    "youtube": "platforms_used",
    "twitch": "platforms_used",
    # relationship_to_victim
    "father": "relationship_to_victim",
    "mother": "relationship_to_victim",
    "parent": "relationship_to_victim",
    "brother": "relationship_to_victim",
    "sister": "relationship_to_victim",
    "uncle": "relationship_to_victim",
    "aunt": "relationship_to_victim",
    "cousin": "relationship_to_victim",
    "teacher": "relationship_to_victim",
    "coach": "relationship_to_victim",
}

_PLATFORM_LIKE = {
    "facebook",
    "discord",
    "kik",
    "telegram",
    "roblox",
    "snapchat",
    "instagram",
    "tiktok",
    "twitter",
    "skype",
    "omegle",
    "minecraft",
    "tor",
    "dark_web",
    "dropbox",
    "youtube",
    "twitch",
    "mewe",
    "fortnite",
    "xbox",
    "psn",
    "irc",
    "aim",
    "myspace",
    "craigslist",
    "mega",
    "onedrive",
    "googledrive",
    "google_drive",
    "limewire",
    "bittorrent",
    "kazaa",
}

_RELATIONSHIP_LIKE = {
    "father",
    "mother",
    "parent",
    "brother",
    "sister",
    "sibling",
    "uncle",
    "aunt",
    "cousin",
    "teacher",
    "coach",
    "stranger",
    "neighbor",
    "babysitter",
    "stepfather",
    "stepmother",
}

_SOURCES: list[dict[str, str]] = [
    {"code": "AZICAC", "name": "Arizona ICAC", "description": "Annual case reports and arrests"},
    {"code": "NCMEC", "name": "National Center for Missing & Exploited Children", "description": "Case summaries and CyberTipline-related publications"},
    {"code": "GBI", "name": "Georgia Bureau of Investigation", "description": "CEACC / Georgia ICAC press releases"},
    {"code": "IDAHO ICAC", "name": "Idaho Office of the Attorney General", "description": "ICAC newsroom press releases"},
    {"code": "TEXAS AG", "name": "Texas Office of the Attorney General", "description": "Cyber Crimes / ICAC-related press releases"},
    {"code": "MICHIGAN ICAC", "name": "Michigan State Police", "description": "MSP newsroom ICAC releases"},
    {"code": "SVICAC", "name": "Silicon Valley ICAC", "description": "Regional In The News articles"},
    {"code": "TBI ICAC", "name": "Tennessee Bureau of Investigation", "description": "TBI newsroom ICAC search results"},
    {"code": "SCAG ICAC", "name": "South Carolina Attorney General", "description": "ICAC-tagged news releases"},
    {"code": "NEWYORK SP", "name": "New York State Police", "description": "NYSP newsroom ICAC keyword search"},
    {"code": "ILLINOIS AG", "name": "Illinois Attorney General", "description": "ICAC press release search"},
    {"code": "PA AG", "name": "Pennsylvania Office of the Attorney General", "description": "Child Predator / ICAC-related releases"},
    {"code": "NJ AG", "name": "New Jersey Office of the Attorney General", "description": "ICAC site search"},
    {"code": "WCSO", "name": "Washoe County Sheriff's Office", "description": "Nevada ICAC newsroom search"},
    {"code": "DOJ CEOS", "name": "U.S. DOJ CEOS", "description": "Child Exploitation and Obscenity Section press releases"},
    {"code": "DOJ ARCHIVES", "name": "U.S. DOJ CEOS Archives", "description": "Archived CEOS criminal press releases (2002-2008)"},
    {"code": "USSS", "name": "U.S. Secret Service", "description": "ICAC-related newsroom press releases"},
    {"code": "US MARSHALS", "name": "U.S. Marshals Service", "description": "Press releases on child predators and recovered minors"},
    {"code": "NCIS", "name": "Naval Criminal Investigative Service", "description": "Child exploitation investigation press releases"},
    {"code": "ICE", "name": "U.S. Immigration and Customs Enforcement", "description": "HSI child-exploitation press releases"},
    {"code": "CBP", "name": "U.S. Customs and Border Protection", "description": "Child sexual exploitation border enforcement releases"},
    {"code": "ARMY CID", "name": "U.S. Army Criminal Investigation Division", "description": "ICAC releases"},
    {"code": "AF OSI", "name": "U.S. Air Force Office of Special Investigations", "description": "CSAM and exploitation press releases"},
]


def _infer_tag_category(tag: str) -> str:
    key = tag.strip().lower()
    if key in _TAG_CATEGORIES:
        return _TAG_CATEGORIES[key]
    if key in _PLATFORM_LIKE:
        return "platforms_used"
    if key in _RELATIONSHIP_LIKE:
        return "relationship_to_victim"
    return "platforms_used"


def _tags_to_api_payload(tags: list[str]) -> list[dict[str, str]]:
    return [{"tag": t.strip().lower(), "category": _infer_tag_category(t)} for t in tags if t.strip()]


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _public_base_url() -> str | None:
    """Resolve the public HTTPS base URL for MCP host/origin allowlists."""
    for key in ("MCP_PUBLIC_URL", "CASELINKER_API_URL", "RAILWAY_STATIC_URL"):
        raw = os.getenv(key, "").strip()
        if raw:
            return raw if "://" in raw else f"https://{raw}"
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if domain:
        return f"https://{domain}"
    return None


def configure_mcp_deployment() -> None:
    """Configure FastMCP SSE for reverse-proxy deployment (Railway, etc.).

    FastMCP 1.27.x has no base_url setting. Session POST paths are relative and
    built from ASGI root_path + message_path in mcp.server.sse. The Railway 421
    comes from transport_security rejecting Host headers outside localhost defaults.
    """
    if _truthy_env("MCP_DISABLE_DNS_REBINDING"):
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
        logger.info("MCP DNS rebinding protection disabled")
        return

    allowed_hosts: list[str] = [
        h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
    ]
    allowed_origins: list[str] = [
        o.strip() for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]

    if not allowed_hosts:
        base = _public_base_url()
        if base:
            parsed = urlparse(base)
            host = parsed.hostname
            if host:
                allowed_hosts = [host, f"{host}:*"]
                if not allowed_origins:
                    scheme = parsed.scheme or "https"
                    port = f":{parsed.port}" if parsed.port else ""
                    allowed_origins = [f"{scheme}://{host}{port}", f"{scheme}://{host}:*"]

    if allowed_hosts:
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
        logger.info("MCP transport_security hosts=%s origins=%s", allowed_hosts, allowed_origins)
    else:
        logger.info("MCP transport_security unchanged (localhost defaults)")


def _fix_mcp_message_post_routes(starlette_app: Any) -> Any:
    """Serve POST /messages?session_id=... without a 307 trailing-slash redirect.

    FastMCP may register Mount("/messages/", ...) which redirects bare /messages.
    Normalize to Mount("/messages", ...) so the ASGI handler is invoked directly.
    Do not wrap the ASGI app in a Starlette Route endpoint — that returns None and
    triggers ``TypeError: 'NoneType' object is not callable`` after the 202 is sent.
    """
    from starlette.routing import Mount

    patched: list[Any] = []
    for route in starlette_app.routes:
        if isinstance(route, Mount) and route.path.rstrip("/") == "/messages":
            patched.append(Mount("/messages", app=route.app))
        else:
            patched.append(route)

    starlette_app.router.routes = patched
    return starlette_app


def build_mcp_sse_app(mount_path: str | None = None) -> Any:
    """Build the MCP SSE Starlette app with deployment + auth middleware.

    When mounted under FastAPI at ``/mcp``, leave *mount_path* as ``None`` (default ``/``).
    FastMCP only prepends *mount_path* to the client-facing message URL in the SSE event;
    actual Starlette routes stay at ``/sse`` and ``/messages``. ASGI ``root_path`` from the
    FastAPI mount (``/mcp``) completes the client URL: ``/mcp/messages?session_id=...``.
    Do not pass ``mount_path="/mcp"`` here or the SSE event doubles the prefix.
    """
    configure_mcp_deployment()
    sse_app = mcp.sse_app(mount_path=mount_path)
    sse_app = _fix_mcp_message_post_routes(sse_app)
    return wrap_mcp_with_auth(sse_app)


_mcp_streamable_app: Any | None = None


def build_mcp_streamable_app() -> Any:
    """Build the MCP Streamable HTTP Starlette app with deployment + auth middleware.

    When mounted under FastAPI at ``/mcp-http``, set ``streamable_http_path`` to ``/`` so the
    public client URL is ``/mcp-http/`` (GET + POST on one endpoint). Do not set it to
    ``/mcp-http`` here — FastAPI's mount supplies the outer prefix, same as SSE.

    The Streamable HTTP session manager lifespan is **not** started here. When mounted under
    FastAPI, call :func:`get_mcp_streamable_session_manager` from the main app startup hook
    (see ``run/main.py``).
    """
    global _mcp_streamable_app
    if _mcp_streamable_app is not None:
        return _mcp_streamable_app

    configure_mcp_deployment()
    mcp.settings.streamable_http_path = "/"
    inner = mcp.streamable_http_app()
    # Mounted sub-app lifespans are not run by FastAPI; main startup runs session_manager.run().
    inner.router.lifespan_context = None
    _mcp_streamable_app = wrap_mcp_with_auth(inner)
    return _mcp_streamable_app


def get_mcp_streamable_session_manager() -> Any:
    """Return the shared Streamable HTTP session manager (lazy-builds the app)."""
    build_mcp_streamable_app()
    return mcp.session_manager


def _header_from_scope(scope: dict[str, Any], name: str) -> str:
    """Read a request header from an ASGI HTTP scope (case-insensitive)."""
    target = name.lower().encode("latin-1")
    for key, val in scope.get("headers", []):
        if key.lower() == target:
            return val.decode("latin-1")
    return ""


def _wrap_mcp_request_context(asgi_app: Any) -> Any:
    """Bind inbound CaseLinker-Key header to per-request context for REST API calls."""
    from starlette.types import Receive, Scope, Send

    from caselinker_mcp.client import bind_request_caselinker_key, reset_request_caselinker_key

    async def middleware(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await asgi_app(scope, receive, send)
            return
        inbound = _header_from_scope(scope, "CaseLinker-Key").strip() or None
        token = bind_request_caselinker_key(inbound)
        try:
            await asgi_app(scope, receive, send)
        finally:
            reset_request_caselinker_key(token)

    return middleware


def wrap_mcp_with_auth(asgi_app: Any) -> Any:
    """Per-request CaseLinker-Key forwarding + optional MCP_ACCESS_KEY bearer gate."""
    wrapped = _wrap_mcp_request_context(asgi_app)

    access_key = os.getenv("MCP_ACCESS_KEY", "").strip()
    if not access_key:
        return wrapped

    from starlette.responses import JSONResponse
    from starlette.types import Receive, Scope, Send

    async def auth_middleware(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await wrapped(scope, receive, send)
            return
        auth = _header_from_scope(scope, "Authorization")
        if auth != f"Bearer {access_key}":
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await wrapped(scope, receive, send)

    return auth_middleware


def _graph_key(graph_id: str) -> str:
    return f"{_GRAPH_KEY_PREFIX}{graph_id.strip()}"


def _graph_get(graph_id: str) -> dict[str, Any] | None:
    gid = graph_id.strip()
    if not gid:
        return None
    if _redis_available and _redis_get_cached:
        hit = _redis_get_cached(_graph_key(gid))
        if hit is not None:
            return hit
    return _graph_store.get(gid)


def _graph_put(graph_id: str, stored: dict[str, Any]) -> None:
    gid = graph_id.strip()
    if _redis_available and _redis_set_cached:
        if _redis_set_cached(_graph_key(gid), stored, ttl=_GRAPH_TTL):
            return
        logger.warning("Redis graph store write failed; using in-memory fallback for %s", gid)
    _graph_store[gid] = stored


def _store_graph_payload(payload: dict[str, Any]) -> str:
    from graph_utils import build_adjacency  # noqa: E402

    graph_id = str(uuid.uuid4())
    nodes = payload.get("nodes") or []
    node_index = {n["node_id"]: n for n in nodes if n.get("node_id")}
    stored = {
        "nodes": nodes,
        "edges": payload.get("edges") or [],
        "flat_nodes": payload.get("flat_nodes") or [],
        "metadata": payload.get("metadata") or {},
        "node_index": node_index,
        "adjacency": build_adjacency(payload.get("edges") or []),
    }
    _graph_put(graph_id, stored)
    return graph_id


@mcp.tool()
async def get_corpus_stats() -> dict[str, Any]:
    """Return corpus-wide statistics: total cases, sources, and feature counts."""
    try:
        result = await api_get("/api/stats")
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_corpus_stats failed")
        return {"error": str(e)}


@mcp.tool()
async def get_case(case_id: str) -> dict[str, Any]:
    """Fetch full detail for one case by ID (features, platforms, severity, charges, demographics, agencies, narrative).

    Public responses omit raw_data unless CASELINKER_KEY is a trusted key on the server.
    Example case_id values: 'azicac_2011_001', 'doj_ceos_2020_042' (format varies by source).
    """
    try:
        result = await api_get(f"/api/cases/{case_id.strip()}")
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_case failed")
        return {"error": str(e)}


@mcp.tool()
async def get_cases_page(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Return a paginated page of case summaries (slim fields, no full narratives). limit capped at 500."""
    try:
        capped = min(max(limit, 1), 500)
        result = await api_get("/api/cases-summaries-chunk", params={"limit": capped, "offset": max(offset, 0)})
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_cases_page failed")
        return {"error": str(e)}


@mcp.tool()
async def get_cases_by_ids(case_ids: list[str]) -> dict[str, Any]:
    """Batch-fetch summaries for specific case IDs (max 500 per call)."""
    try:
        ids = [cid.strip() for cid in case_ids if cid and cid.strip()][:500]
        if not ids:
            return {"error": "Provide at least one case id"}
        result = await api_post("/api/cases-summaries-by-ids", {"ids": ids})
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_cases_by_ids failed")
        return {"error": str(e)}


@mcp.tool()
async def filter_cases_by_tags(tags: list[str]) -> dict[str, Any]:
    """Return cases matching ALL supplied tags (intersection logic).

    Tag dimensions (pass plain tag strings; category is inferred automatically):
      - case_topics: csam, production, possession, online_only, hands_on,
                     multi_state, international, family, stranger
      - severity_indicators: infant, very_young, under_10, rape, physical_abuse
      - platforms_used: facebook, discord, kik, telegram, roblox,
                        snapchat, tor, dark_web, and others
      - investigation_types: proactive, reactive, undercover, cybertipline
      - perpetrator_relationships: father, stranger, teacher, coach, etc.
      - perpetrator_status: registered_sex_offender

    Example: filter_cases_by_tags(["discord", "infant"]) returns cases involving
    Discord where an infant was a victim.
    """
    try:
        payload = _tags_to_api_payload(tags)
        if not payload:
            return {"cases": [], "count": 0, "note": "No tags provided; returning empty result."}
        result = await api_post("/api/return-tagged-cases", payload)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("filter_cases_by_tags failed")
        return {"error": str(e)}


@mcp.tool()
async def get_facet_tree(max_depth: int = 4) -> dict[str, Any]:
    """Return the facet decision tree showing how the corpus partitions across structured dimensions.

    Dimensions include platform, severity, topic, investigation type, and related facets.
    max_depth range 1-6; deeper values yield finer cohorts.
    """
    try:
        depth = min(max(max_depth, 1), 6)
        result = await api_get("/api/facet-tree", params={"max_depth": depth})
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_facet_tree failed")
        return {"error": str(e)}


@mcp.tool()
async def get_cohort_members(path: list[dict[str, str]]) -> dict[str, Any]:
    """Return case IDs for a facet-tree cohort path.

    Each step: {"facet": "<dimension>", "value": "<value>"} (or use "field" instead of "facet").

    Example path:
      [{"facet": "platform", "value": "discord"},
       {"facet": "severity", "value": "infant"}]

    Small cohorts (<3 cases) may omit case_ids unless a demo access key is configured on the server.
    """
    try:
        result = await api_post("/api/facet-cohort-members", {"facet_path": path})
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_cohort_members failed")
        return {"error": str(e)}


@mcp.tool()
async def run_automated_analysis() -> dict[str, Any]:
    """Run automated corpus analysis: similarity groups, top-priority cases, platform insights, patterns, top keywords."""
    try:
        result = await api_get("/api/automated-analysis")
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("run_automated_analysis failed")
        return {"error": str(e)}


@mcp.tool()
async def triage_text(text: str) -> dict[str, Any]:
    """Score external case narrative text in memory only (nothing written to the database).

    Returns priority tier (1-3), rule-based dimension scores, and ML classification when the
    triage bundle is loaded on the server.
    """
    try:
        if not text.strip():
            return {"error": "text is required"}
        result = await api_post("/api/triage-live", {"raw": text})
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("triage_text failed")
        return {"error": str(e)}


@mcp.tool()
async def get_triage_eval_metrics() -> dict[str, Any]:
    """Return stratified train/test metrics for the triage classifier on the live corpus (precision, recall, F1 per tier)."""
    try:
        result = await api_get("/api/triage-eval")
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_triage_eval_metrics failed")
        return {"error": str(e)}


@mcp.tool()
async def get_knowledge_graph(pool: str = "compare") -> dict[str, Any]:
    """Return the merged CAC ontology knowledge graph.

    pool options:
      - "compare": stratified compare pool (universe subset)
      - "all": big_bang pool merged
      - "universe": full corpus graph pool
      - "analysis": bridge-dense ~1000 case pool

    Nodes represent cases, entities, and ontology classes; edges encode relationships.
    """
    try:
        pool_val = pool.strip().lower() if pool else "compare"
        if pool_val not in ("compare", "all", "universe", "analysis"):
            pool_val = "compare"
        result = await api_get("/api/ontology/merged", params={"pool": pool_val})
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_knowledge_graph failed")
        return {"error": str(e)}


@mcp.tool()
async def get_case_graph_manifest() -> dict[str, Any]:
    """Return per-case ontology graph metadata: which cases are encoded, class mappings, entity counts.

    Call this before get_knowledge_graph to understand graph coverage.
    """
    try:
        result = await api_get("/api/ontology/cases")
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_case_graph_manifest failed")
        return {"error": str(e)}


@mcp.tool()
async def get_case_studies() -> dict[str, Any]:
    """Return era-based narrative case studies across four technological eras of ICAC work."""
    try:
        result = await api_get("/api/case-studies")
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_case_studies failed")
        return {"error": str(e)}


@mcp.tool()
async def q1_platform_evidence(platform: str | None = None, tier: str | None = None) -> dict[str, Any]:
    """Query Q1 platform harm evidence as a cohort source for case2cac and get_case.

    Without platform: platform index with case_count and per-tier counts (stated, inferred, named_only).
    With platform: matching case IDs (same format as get_case / case2cac), each with tier and evidence_quote.
    Optional tier filter: stated, inferred, or named_only.

    Example: q1_platform_evidence(\"Snapchat\") then case2cac on returned case_ids.
    """
    try:
        params: dict[str, str] = {}
        if platform and platform.strip():
            params["platform"] = platform.strip()
        if tier and tier.strip():
            params["tier"] = tier.strip().lower()
        result = await api_get("/api/q1/platform-evidence", params=params or None)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("q1_platform_evidence failed")
        return {"error": str(e)}


@mcp.tool()
async def list_sources() -> dict[str, Any]:
    """List ingestion sources in the CaseLinker corpus.

    No JSON API exists at /sources (HTML page only); returns the documented source catalog.
    """
    try:
        return {"sources": _SOURCES, "count": len(_SOURCES), "note": "Static catalog from project documentation; /sources is HTML only."}
    except Exception as e:
        logger.exception("list_sources failed")
        return {"error": str(e)}


@mcp.tool()
async def case2cac(case_ids: list[str]) -> dict[str, Any]:
    """Generate a CAC ontology graph on-demand for the given case IDs.

    Case IDs must come from prior search/filter tool calls — do not fabricate IDs.
    Hard cap: first 1000 IDs are processed silently (Q1 full-cohort research).

    MCP-only. Not exposed as a REST endpoint.

    Returns graph_id plus a structural summary; use graph_id with traversal tools.
    """
    try:
        from graph_generate import generate_graph_for_ids  # noqa: E402
        from graph_utils import build_graph_summary  # noqa: E402

        ids = [cid.strip() for cid in case_ids if cid and cid.strip()][:1000]
        if not ids:
            return {
                "graph_id": None,
                "summary": {
                    "node_count": 0,
                    "edge_count": 0,
                    "cases_mapped": [],
                    "concept_distribution": [],
                    "bridge_nodes": [],
                    "cac_classes_covered": [],
                },
                "note": "No case ids provided.",
            }

        t0 = time.perf_counter()
        payload = await asyncio.to_thread(generate_graph_for_ids, ids)
        elapsed = time.perf_counter() - t0
        mapped = payload.get("metadata", {}).get("cases_mapped") or []
        skipped = payload.get("metadata", {}).get("skipped") or []
        logger.info(
            "case2cac: requested=%d mapped=%d elapsed=%.2fs",
            len(ids),
            len(mapped),
            elapsed,
        )

        if not mapped:
            return {
                "error": "No cases could be mapped to CAC graphs.",
                "requested": ids,
                "skipped": skipped,
            }

        graph_id = _store_graph_payload(payload)
        summary = build_graph_summary(
            payload.get("nodes") or [],
            payload.get("edges") or [],
            payload.get("flat_nodes") or [],
            payload.get("metadata") or {},
        )
        return {"graph_id": graph_id, "summary": summary}
    except Exception as e:
        logger.exception("case2cac failed")
        return {"error": str(e)}


@mcp.tool()
async def graph_get_neighbors(graph_id: str, node_id: str) -> dict[str, Any]:
    """Return all nodes directly connected to node_id in a session graph from case2cac."""
    try:
        from graph_utils import enrich_neighbors  # noqa: E402

        graph = _graph_get(graph_id)
        if not graph:
            return {"error": "Graph not found. Call case2cac first."}
        neighbors = enrich_neighbors(graph, node_id.strip())
        return {"graph_id": graph_id, "node_id": node_id, "neighbors": neighbors}
    except Exception as e:
        logger.exception("graph_get_neighbors failed")
        return {"error": str(e)}


@mcp.tool()
async def graph_find_cases_by_concept(graph_id: str, concept: str) -> dict[str, Any]:
    """Find case IDs in a session graph linked to nodes matching a CAC class, affordance, or keyword."""
    try:
        from graph_utils import find_cases_by_concept  # noqa: E402

        graph = _graph_get(graph_id)
        if not graph:
            return {"error": "Graph not found. Call case2cac first."}
        return find_cases_by_concept(graph, concept)
    except Exception as e:
        logger.exception("graph_find_cases_by_concept failed")
        return {"error": str(e)}


@mcp.tool()
async def graph_summarize(graph_id: str) -> dict[str, Any]:
    """Return a structural summary of a session graph (types, bridges, co-occurrence, edge distribution)."""
    try:
        from graph_utils import summarize_graph  # noqa: E402

        graph = _graph_get(graph_id)
        if not graph:
            return {"error": "Graph not found. Call case2cac first."}
        return summarize_graph(graph)
    except Exception as e:
        logger.exception("graph_summarize failed")
        return {"error": str(e)}


@mcp.tool()
async def graph_compare_cohorts(graph_id_a: str, graph_id_b: str) -> dict[str, Any]:
    """Compare two session graphs from separate case2cac calls (e.g. Discord vs Roblox cohorts)."""
    try:
        from graph_utils import compare_graphs  # noqa: E402

        graph_a = _graph_get(graph_id_a)
        graph_b = _graph_get(graph_id_b)
        if not graph_a or not graph_b:
            return {"error": "One or both graphs not found. Call case2cac first for each cohort."}
        return compare_graphs(graph_a, graph_b)
    except Exception as e:
        logger.exception("graph_compare_cohorts failed")
        return {"error": str(e)}


@mcp.tool()
async def export_case_graph_ttl(
    graph_id: str,
    case_id: str | None = None,
    pool: str | None = None,
) -> dict[str, Any]:
    """Export a session graph from case2cac as JSON-LD + Turtle RDF.

    Reads flat_nodes from the session graph store, strips merge metadata (_cases, etc.),
    and serializes via rdflib. Call case2cac first to obtain graph_id.

    Optional case_id + pool (e.g. pool=\"analysis\") writes {case_id}.jsonld and
    {case_id}.ttl under ontology/graph_output/{pool}/ for Patterns graph explorer.
    """
    try:
        from graph_utils import flat_nodes_to_exports  # noqa: E402

        stored = _graph_get(graph_id)
        if not stored:
            return {"error": "Graph not found. Call case2cac first."}

        flat_nodes = stored.get("flat_nodes") or []
        if not flat_nodes:
            return {"error": "Graph has no flat_nodes to export."}

        jsonld, turtle, triple_count, node_count = await asyncio.to_thread(
            flat_nodes_to_exports, flat_nodes
        )
        if triple_count == 0 or not jsonld:
            return {"error": "No RDF triples could be reconstructed from flat_nodes."}

        result: dict[str, Any] = {
            "graph_id": graph_id.strip(),
            "jsonld": jsonld,
            "turtle": turtle,
            "triple_count": triple_count,
            "node_count": node_count,
        }

        pool_norm = (pool or "").strip().lower()
        cid = (case_id or "").strip()
        if pool_norm and cid:
            allowed = {"analysis", "universe", "big_bang"}
            if pool_norm == "all":
                pool_norm = "big_bang"
            if pool_norm not in allowed:
                return {"error": f"pool must be one of: {', '.join(sorted(allowed))}"}

            out_dir = _ONTOLOGY_DIR / "graph_output" / pool_norm
            out_dir.mkdir(parents=True, exist_ok=True)
            jsonld_path = out_dir / f"{cid}.jsonld"
            ttl_path = out_dir / f"{cid}.ttl"
            jsonld_path.write_text(
                json.dumps(jsonld, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            ttl_path.write_text(turtle, encoding="utf-8")
            result["saved"] = {
                "case_id": cid,
                "pool": pool_norm,
                "jsonld_path": str(jsonld_path.relative_to(_REPO_ROOT)),
                "ttl_path": str(ttl_path.relative_to(_REPO_ROOT)),
            }

        return result
    except Exception as e:
        logger.exception("export_case_graph_ttl failed")
        return {"error": str(e)}


# REST helpers below are public (no trusted-key gate). Only get_all_cases
# requires a trusted CaseLinker-Key (403 without). get_case and llm_chat
# are public but return richer data / skip daily caps when trusted.


@mcp.tool()
async def get_all_cases(include_raw_data: bool = False) -> dict[str, Any]:
    """Bulk-export every case in the corpus (trusted key required).

    Wraps GET /api/cases. Returns 403 unless CASELINKER_KEY is in
    CASELINKER_TRUSTED_KEYS on the server. Set include_raw_data=True for full
    raw narrative payloads (much larger). Prefer get_cases_page for public access.
    """
    try:
        if err := require_caselinker_key():
            return err
        result = await api_get(
            "/api/cases",
            params={"include_raw_data": include_raw_data},
            timeout=BULK_TIMEOUT,
        )
        if isinstance(result, list):
            return {"count": len(result), "cases": result}
        return result if isinstance(result, dict) else {"cases": result}
    except Exception as e:
        logger.exception("get_all_cases failed")
        return {"error": str(e)}


@mcp.tool()
async def get_case_count() -> dict[str, Any]:
    """Return total case count only (fast COUNT query). Wraps GET /api/case-count."""
    try:
        result = await api_get("/api/case-count")
        return result if isinstance(result, dict) else {"count": result}
    except Exception as e:
        logger.exception("get_case_count failed")
        return {"error": str(e)}


@mcp.tool()
async def get_facet_distinct() -> dict[str, Any]:
    """Distinct tag values per facet field for search prune filters. Wraps GET /api/facet-distinct."""
    try:
        result = await api_get("/api/facet-distinct")
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_facet_distinct failed")
        return {"error": str(e)}


@mcp.tool()
async def get_unique_tags() -> dict[str, Any]:
    """All unique tag values across the corpus (topics, severity, platforms, etc.). Wraps GET /api/tags."""
    try:
        result = await api_get("/api/tags")
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_unique_tags failed")
        return {"error": str(e)}


@mcp.tool()
async def tag_threader(tags: list[str]) -> dict[str, Any]:
    """Tag-threader analysis: intersection cases plus threaded tag links. Wraps POST /api/tag-threader."""
    try:
        payload = _tags_to_api_payload(tags)
        if not payload:
            return {"error": "Provide at least one tag"}
        result = await api_post("/api/tag-threader", payload)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("tag_threader failed")
        return {"error": str(e)}


@mcp.tool()
async def get_case_ids_by_filter(
    organization: str = "",
    relationship: str = "",
    prosecution_status: str = "",
    age_range: str = "",
    severity_indicator: str = "",
    platform: str = "",
    year: str = "",
    investigation_type: str = "",
) -> dict[str, Any]:
    """Filter case IDs by organization, platform, severity, year, etc. Wraps GET /api/case-ids-by-filter."""
    try:
        params = {
            k: v
            for k, v in {
                "organization": organization.strip(),
                "relationship": relationship.strip(),
                "prosecution_status": prosecution_status.strip(),
                "age_range": age_range.strip(),
                "severity_indicator": severity_indicator.strip(),
                "platform": platform.strip(),
                "year": year.strip(),
                "investigation_type": investigation_type.strip(),
            }.items()
            if v
        }
        result = await api_get("/api/case-ids-by-filter", params=params or None)
        return result if isinstance(result, dict) else {"case_ids": result}
    except Exception as e:
        logger.exception("get_case_ids_by_filter failed")
        return {"error": str(e)}


@mcp.tool()
async def get_stats_detailed() -> dict[str, Any]:
    """Detailed visualization stats: feature coverage, platform trends, org frequency, etc. Wraps GET /api/stats-detailed."""
    try:
        result = await api_get("/api/stats-detailed", timeout=BULK_TIMEOUT)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_stats_detailed failed")
        return {"error": str(e)}


@mcp.tool()
async def get_technology_revolver() -> dict[str, Any]:
    """Technology revolver: platforms and investigation tech by era. Wraps GET /api/technology-revolver."""
    try:
        result = await api_get("/api/technology-revolver", timeout=BULK_TIMEOUT)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_technology_revolver failed")
        return {"error": str(e)}


@mcp.tool()
async def get_cluster_groups() -> dict[str, Any]:
    """Pre-computed similarity cluster groups (case IDs only). Wraps GET /api/cluster-groups."""
    try:
        result = await api_get("/api/cluster-groups", timeout=BULK_TIMEOUT)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_cluster_groups failed")
        return {"error": str(e)}


@mcp.tool()
async def get_location_stats() -> dict[str, Any]:
    """Aggregated location counts and case IDs for map visualizations. Wraps GET /api/location-stats."""
    try:
        result = await api_get("/api/location-stats", timeout=BULK_TIMEOUT)
        if isinstance(result, list):
            return {"locations": result, "count": len(result)}
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_location_stats failed")
        return {"error": str(e)}


@mcp.tool()
async def get_triage_model_corpus(facet_constraints_json: str = "") -> dict[str, Any]:
    """Saved triage bundle predictions over the live corpus. Wraps GET /api/triage-model-corpus.

    Optional facet_constraints_json: JSON object mapping facet field keys to allowed value lists.
    """
    try:
        params: dict[str, str] = {}
        if facet_constraints_json.strip():
            params["facet_constraints"] = facet_constraints_json.strip()
        result = await api_get("/api/triage-model-corpus", params=params or None, timeout=BULK_TIMEOUT)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_triage_model_corpus failed")
        return {"error": str(e)}


@mcp.tool()
async def get_case_study_notes(case_id: str) -> dict[str, Any]:
    """Community notes for a case study id. Wraps GET /api/case-studies/notes/{case_id}."""
    try:
        cid = case_id.strip()
        if not cid:
            return {"error": "case_id is required"}
        result = await api_get(f"/api/case-studies/notes/{cid}")
        return result if isinstance(result, dict) else {"notes": result}
    except Exception as e:
        logger.exception("get_case_study_notes failed")
        return {"error": str(e)}


@mcp.tool()
async def llm_chat(question: str, model: str = "", provider: str = "") -> dict[str, Any]:
    """Natural-language SQL assistant over the cases table. Wraps POST /api/llm/chat.

    Requires GROQ_API_KEY or Gemini keys on the server. Trusted CASELINKER_KEY holders
    are exempt from the public daily rate cap. Read-only SELECT on cases only.
    """
    try:
        if not question.strip():
            return {"error": "question is required"}
        body: dict[str, str] = {"question": question.strip()}
        if model.strip():
            body["model"] = model.strip()
        if provider.strip():
            body["provider"] = provider.strip()
        result = await api_post("/api/llm/chat", body, timeout=120.0)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("llm_chat failed")
        return {"error": str(e)}


if __name__ == "__main__":
    if MCP_TRANSPORT == "sse":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = PORT
        _sse_app = build_mcp_sse_app()
        import uvicorn

        uvicorn.run(_sse_app, host="0.0.0.0", port=PORT)
    else:
        mcp.run(transport="stdio")
