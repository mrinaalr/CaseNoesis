"""CaseNoesis MCP server — local stdio tools for collection and analysis.

Not hosted. Agents talk to this process over stdio; corpus tools wrap the
local FastAPI at CASENOESIS_API_URL (default http://localhost:8000).
Collector WRITE tools write files on this machine and do not need the API.
"""

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

from casenoesis_mcp.client import BULK_TIMEOUT, DEFAULT_TIMEOUT, api_get, api_post, require_caselinker_key

PORT = int(os.getenv("PORT", 8001))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")


def collector_disk_write_enabled() -> bool:
    """Collector WRITE tools write to this machine's disk.

    Local stdio: enabled. Railway (if this process were ever started there): off.
    Override with MCP_COLLECTOR_WRITE=1|0.
    """
    flag = os.getenv("MCP_COLLECTOR_WRITE", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_NAME"):
        return False
    return True


_COLLECTOR_WRITE_ENABLED = collector_disk_write_enabled()

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
    format="%(asctime)s [casenoesis_mcp] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("casenoesis_mcp")

# message_path without trailing slash: Mount("/messages/") 307-redirects POST /messages,
# which breaks MCP clients that strip the slash when parsing the SSE endpoint event.
mcp = FastMCP("CaseNoesis", message_path="/messages")

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

    With ``redirect_slashes=False`` on the inner router, Starlette no longer 307s
    bare ``/messages`` to ``/messages/``, but the Mount regex still only fully
    matches ``/messages/...``. Prepend an exact ``Route("/messages", …)`` so the
    URL advertised in the SSE ``endpoint`` event is handled without a redirect.

    The Route wrapper must not return a Starlette Response — ``handle_post_message``
    is an ASGI app that sends the response itself (same pattern as FastMCP's Mount).
    """
    from starlette.routing import Mount, Route

    messages_handler: Any | None = None
    patched: list[Any] = []
    for route in starlette_app.routes:
        if isinstance(route, Mount) and route.path.rstrip("/") == "/messages":
            messages_handler = route.app
            patched.append(Mount("/messages", app=route.app))
        else:
            patched.append(route)

    if messages_handler is not None:

        async def _messages_exact(request: Any) -> None:
            await messages_handler(request.scope, request.receive, request._send)

        patched.insert(0, Route("/messages", endpoint=_messages_exact, methods=["POST"]))

    starlette_app.router.routes = patched
    return starlette_app


_SSE_STREAM_PATH = "/sse"
_NON_SSE_STREAM_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _sse_misroute_response_body(scope: dict[str, Any]) -> dict[str, Any]:
    """Build JSON body for POST (etc.) mistakenly sent to the SSE stream URL."""
    root_path = scope.get("root_path", "").rstrip("/")
    messages_example = f"{root_path}/messages?session_id=<from SSE endpoint event>"
    base = _public_base_url()
    streamable_url = f"{base.rstrip('/')}/mcp-http/" if base else f"{root_path.replace('/mcp', '/mcp-http')}/"
    return {
        "detail": "POST is not accepted on the SSE stream endpoint.",
        "hint": (
            "SSE uses two URLs: open GET …/sse, read the endpoint event, then POST JSON-RPC to "
            "…/messages?session_id=…. Or use Streamable HTTP (single URL for GET+POST)."
        ),
        "sse_messages_url": messages_example,
        "streamable_http_url": streamable_url,
    }


def _is_sse_stream_path(path: str) -> bool:
    """True when the request targets the SSE stream URL (not /messages).

    FastAPI ``app.mount("/mcp", …)`` forwards the full path ``/mcp/sse`` when the
    mounted target is a bare ASGI callable; Starlette TestClient uses ``/sse`` only.
    """
    normalized = path.rstrip("/") or "/"
    return normalized == _SSE_STREAM_PATH or normalized.endswith(_SSE_STREAM_PATH)


def _wrap_sse_misroute_hint(asgi_app: Any) -> Any:
    """Return 405 with transport hints when clients POST to /sse instead of /messages."""
    from starlette.responses import JSONResponse
    from starlette.types import Receive, Scope, Send

    async def middleware(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "").rstrip("/") or "/"
            method = scope.get("method", "GET").upper()
            if method in _NON_SSE_STREAM_METHODS and _is_sse_stream_path(path):
                response = JSONResponse(
                    _sse_misroute_response_body(scope),
                    status_code=405,
                    headers={"Allow": "GET, HEAD"},
                )
                await response(scope, receive, send)
                return
        await asgi_app(scope, receive, send)

    return middleware


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
    # Starlette Router default redirect_slashes=True 307s POST /messages → /messages/
    # before the Mount handler runs; the SSE endpoint event advertises bare /messages.
    sse_app.router.redirect_slashes = False
    sse_app = _fix_mcp_message_post_routes(sse_app)
    return _wrap_sse_misroute_hint(wrap_mcp_with_auth(sse_app))


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

    from casenoesis_mcp.client import bind_request_caselinker_key, reset_request_caselinker_key

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
async def get_facet_tree(
    max_depth: int = 4,
    facet_constraints_json: str = "",
    include_facets: str = "",
    case_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return the facet decision tree showing how cases partition across structured dimensions.

    Full corpus (default): calls GET /api/facet-tree with optional prune filters.
    Sub-corpus: pass case_ids to build the tree locally from caselinker.db (MCP-only, no API).

    facet_constraints_json: JSON object mapping facet field keys to allowed value lists, e.g.
      {"source": ["DOJ CEOS", "ICE"], "case_topics": ["online_only"]}
    include_facets: comma-separated field keys to split on (subset of DEFAULT_FACET_ORDER).
    max_depth: 1-11 for local builds; API path caps at 6 unless case_ids is set.
    """
    try:
        if case_ids:
            from facet_local import (  # noqa: E402
                _parse_constraints,
                _parse_include_facets,
                build_facet_tree_payload,
                load_cases_by_ids,
            )

            ids = [c.strip() for c in case_ids if c and c.strip()]
            if not ids:
                return {"error": "case_ids is empty"}
            cases = await asyncio.to_thread(load_cases_by_ids, ids)
            if not cases:
                return {"error": "No matching cases in database", "requested": len(ids)}
            depth = max_depth if max_depth > 0 else None
            payload = await asyncio.to_thread(
                build_facet_tree_payload,
                cases,
                max_depth=depth,
                facet_constraints=_parse_constraints(facet_constraints_json),
                include_facets=_parse_include_facets(include_facets),
            )
            payload.pop("_root_node", None)
            payload.pop("_cases", None)
            payload["mode"] = "local_subset"
            payload["input_case_ids"] = len(ids)
            return payload

        depth = min(max(max_depth, 1), 6)
        params: dict[str, str] = {"max_depth": str(depth)}
        if facet_constraints_json.strip():
            params["facet_constraints"] = facet_constraints_json.strip()
        if include_facets and include_facets.strip():
            params["include_facets"] = include_facets.strip()
        result = await api_get("/api/facet-tree", params=params)
        out = result if isinstance(result, dict) else {"data": result}
        out["mode"] = "api_corpus"
        return out
    except Exception as e:
        logger.exception("get_facet_tree failed")
        return {"error": str(e)}


@mcp.tool()
async def get_cohort_members(
    path: list[dict[str, str]],
    facet_constraints_json: str = "",
    case_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return case IDs for a facet-tree cohort path.

    Each step: {"facet": "<dimension>", "value": "<value>"} (or use "field" instead of "facet").

    Example path:
      [{"facet": "platforms_used", "value": "discord"},
       {"facet": "severity_indicators", "value": "infant"}]

  Pass case_ids to resolve cohort membership locally (MCP-only). Otherwise uses the API.
  facet_constraints_json: same prune JSON as get_facet_tree (applied before path matching).

    Small cohorts (<3 cases) on the API path may omit case_ids unless a demo access key is set.
    """
    try:
        if case_ids:
            from facet_local import (  # noqa: E402
                _parse_constraints,
                cohort_members_payload,
                load_cases_by_ids,
            )

            ids = [c.strip() for c in case_ids if c and c.strip()]
            cases = await asyncio.to_thread(load_cases_by_ids, ids)
            if not cases:
                return {"error": "No matching cases in database", "requested": len(ids)}
            out = await asyncio.to_thread(
                cohort_members_payload,
                cases,
                path,
                _parse_constraints(facet_constraints_json),
            )
            out["mode"] = "local_subset"
            return out

        body: dict[str, Any] = {"facet_path": path}
        constraints = facet_constraints_json.strip()
        if constraints:
            try:
                parsed = json.loads(constraints)
                if isinstance(parsed, dict):
                    body["facet_constraints"] = parsed
            except json.JSONDecodeError:
                return {"error": "facet_constraints_json must be valid JSON"}
        result = await api_post("/api/facet-cohort-members", body)
        out = result if isinstance(result, dict) else {"data": result}
        out["mode"] = "api_corpus"
        return out
    except Exception as e:
        logger.exception("get_cohort_members failed")
        return {"error": str(e)}


@mcp.tool()
async def tree_traversal(
    case_ids: list[str] | None = None,
    use_pacer_pool: bool = False,
    pacer_min_confidence: str = "low",
    random_count: int = 25,
    targeted_count: int = 25,
    max_depth: int = 0,
    facet_constraints_json: str = "",
    include_facets: str = "",
    targeted_path: list[dict[str, str]] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """MCP-only facet tree traversal over a case subset (not the full corpus).

    Builds a 10-level facet tree (search UI order) directly from caselinker.db — no REST API.
    Returns random_count cases from random tree walks plus targeted_count from diverse
    leaf cohorts (or an explicit targeted_path).

    Typical workflow for the 50-case PACER lookup:
      1. python collector/pacer/corpus2pacer.py  →  data/collected/PACER/pacer_cases.json
      2. tree_traversal(use_pacer_pool=true, random_count=25, targeted_count=25)

    use_pacer_pool: load IDs from data/collected/PACER/pacer_cases.json instead of case_ids.
    pacer_min_confidence: low | medium | high when use_pacer_pool is true.
    max_depth: 0 = full facet depth for the included dimensions; else cap levels.
    targeted_path: optional explicit facet path for the targeted half; else auto-diverse leaves.
    seed: optional RNG seed for reproducible samples.
    """
    try:
        from facet_local import tree_traversal_payload  # noqa: E402

        depth = None if max_depth <= 0 else max_depth
        return await asyncio.to_thread(
            tree_traversal_payload,
            case_ids=case_ids,
            use_pacer_pool=use_pacer_pool,
            pacer_min_confidence=pacer_min_confidence,
            random_count=max(random_count, 0),
            targeted_count=max(targeted_count, 0),
            max_depth=depth,
            facet_constraints_json=facet_constraints_json,
            include_facets=include_facets,
            targeted_path=targeted_path,
            seed=seed,
        )
    except FileNotFoundError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("tree_traversal failed")
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


# REST helpers below are public (no trusted-key gate). get_all_cases and
# get_lifecycle_* require a trusted CaseLinker-Key (403 without). get_case and
# llm_chat are public but return richer data / skip daily caps when trusted.


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
async def get_lifecycle_cases() -> dict[str, Any]:
    """PACER exploitation lifecycle swimlanes payload (trusted key required).

    Wraps GET /api/lifecycle/cases — five offense types as CAC state machines with
    fundamental stages, cross-case coverage, affordance annotations, and per-case
    phase trajectories. The public /lifecycle page embeds this data; API access
    requires CASELINKER_KEY in CASELINKER_TRUSTED_KEYS.
    """
    try:
        if err := require_caselinker_key():
            return err
        result = await api_get("/api/lifecycle/cases", timeout=DEFAULT_TIMEOUT)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_lifecycle_cases failed")
        return {"error": str(e)}


@mcp.tool()
async def get_lifecycle_lstar() -> dict[str, Any]:
    """Full L* computation output for all PACER cases (trusted key required).

    Wraps GET /api/lifecycle/lstar — raw state_machines/data/lstar_all_cases.json including
    transition_matrix, global_lstar, cross_case_comparison, and per-case
    phase_details. Use get_lifecycle_cases for the visualization-oriented payload.
    """
    try:
        if err := require_caselinker_key():
            return err
        result = await api_get("/api/lifecycle/lstar", timeout=DEFAULT_TIMEOUT)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.exception("get_lifecycle_lstar failed")
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


# --- Free public records (outside corpus) ---


@mcp.tool()
async def search_doj_press_releases(
    title_term: str,
    page: int = 0,
    pagesize: int = 20,
    require_regex: str = "",
) -> dict[str, Any]:
    """Search the public DOJ News API by title substring (free, no key).

    Use for press releases. Does not fetch justice.gov HTML (Akamai).
    Optional require_regex filters title+body.
    """
    try:
        from casenoesis_mcp.public_records import search_doj_press_releases as _search

        return await _search(
            title_term,
            page=page,
            pagesize=pagesize,
            require_regex=require_regex,
        )
    except Exception as e:
        logger.exception("search_doj_press_releases failed")
        return {"error": str(e)}


@mcp.tool()
async def search_courtlistener(
    query: str,
    search_type: str = "r",
    free_only: bool = True,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search CourtListener / RECAP for free public court records (no PACER fees).

    search_type: r=dockets+nested filings, rd=filings only, d=docket metadata, o=opinions.
    free_only=True keeps only RECAP-available downloads. Never buys PACER pages.
    """
    try:
        from casenoesis_mcp.public_records import search_courtlistener as _search

        return await _search(
            query,
            search_type=search_type,
            free_only=free_only,
            max_results=max_results,
        )
    except Exception as e:
        logger.exception("search_courtlistener failed")
        return {"error": str(e)}


@mcp.tool()
async def list_free_recap_documents(
    docket_id: str,
    max_results: int = 20,
) -> dict[str, Any]:
    """List RECAP filings for a CourtListener docket_id that are free to download ($0)."""
    try:
        from casenoesis_mcp.public_records import list_free_recap_documents as _list

        return await _list(docket_id, max_results=max_results)
    except Exception as e:
        logger.exception("list_free_recap_documents failed")
        return {"error": str(e)}


@mcp.tool()
async def resolve_free_recap_download(document_id: str) -> dict[str, Any]:
    """Resolve a RECAP document id to a free storage.courtlistener.com URL when available.

    Returns cost=not free via RECAP when the filing is not in the free archive (do not PACER-fetch).
    """
    try:
        from casenoesis_mcp.public_records import resolve_free_recap_download as _resolve

        return await _resolve(document_id)
    except Exception as e:
        logger.exception("resolve_free_recap_download failed")
        return {"error": str(e)}


# --- Press-release collector suite: READ always; WRITE local only ---

logger.info(
    "Collector disk WRITE tools %s (MCP_COLLECTOR_WRITE / Railway gate)",
    "enabled" if _COLLECTOR_WRITE_ENABLED else "disabled",
)


@mcp.tool()
async def probe_press_url(url: str, jina_fallback: bool = True) -> dict[str, Any]:
    """READ. Probe one press-release URL without writing a PDF.

    justice.gov uses DOJ API resolve (Akamai blocks live HTML). Other hosts use HTML/Jina extract.
    """
    try:
        from casenoesis_mcp.collector_tools import probe_press_url as _probe

        return await asyncio.to_thread(_probe, url, jina_fallback=jina_fallback)
    except Exception as e:
        logger.exception("probe_press_url failed")
        return {"error": str(e), "write": False}


if _COLLECTOR_WRITE_ENABLED:

    @mcp.tool()
    async def harvest_doj_press_topic(
        title_term: str,
        require_regex: str = "",
        max_keep: int = 1,
        limit_pages: int = 1,
        slug: str = "",
        keep_early: bool = True,
        out_dir: str = "",
    ) -> dict[str, Any]:
        """WRITE (local MCP only). DOJ News API harvest → resolved JSON on disk.

        Creates files under collector/sources/ or out_dir. Does not ingest into sqlite.
        """
        try:
            from casenoesis_mcp.collector_tools import harvest_doj_press_topic as _harvest

            return await asyncio.to_thread(
                _harvest,
                title_term,
                require_regex=require_regex,
                max_keep=max_keep,
                limit_pages=limit_pages,
                slug=slug,
                keep_early=keep_early,
                out_dir=out_dir,
            )
        except Exception as e:
            logger.exception("harvest_doj_press_topic failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def fetch_press_listing_urls(
        listing_url: str,
        out_name: str = "mcp_listing_urls.txt",
        same_host: bool = True,
        path_prefix: str = "",
        require_any: str = "",
        max_urls: int = 20,
        out_dir: str = "",
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Listing/search page → url-file."""
        try:
            from casenoesis_mcp.collector_tools import fetch_press_listing_urls as _fetch

            return await asyncio.to_thread(
                _fetch,
                listing_url,
                out_name=out_name,
                same_host=same_host,
                path_prefix=path_prefix,
                require_any=require_any,
                max_urls=max_urls,
                out_dir=out_dir,
            )
        except Exception as e:
            logger.exception("fetch_press_listing_urls failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def resolve_press_urls(
        urls: list[str] | None = None,
        url_file: str = "",
        out_name: str = "mcp_urls_resolved.json",
        out_dir: str = "",
        limit: int = 0,
    ) -> dict[str, Any]:
        """WRITE (local MCP only). URL-path router → resolved JSON for build_press_pdf."""
        try:
            from casenoesis_mcp.collector_tools import resolve_press_urls as _resolve

            return await asyncio.to_thread(
                _resolve,
                urls,
                url_file=url_file,
                out_name=out_name,
                out_dir=out_dir,
                limit=limit,
            )
        except Exception as e:
            logger.exception("resolve_press_urls failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def build_press_pdf(
        doj_file: str = "",
        url_file: str = "",
        out_name: str = "MCP_PRESS.pdf",
        out_dir: str = "",
        limit: int = 1,
        jina_fallback: bool = True,
        insecure: bool = False,
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Build merged press-release PDF under out_dir.

        Does NOT ingest into the database.
        """
        try:
            from casenoesis_mcp.collector_tools import build_press_pdf as _build

            return await asyncio.to_thread(
                _build,
                doj_file=doj_file,
                url_file=url_file,
                out_name=out_name,
                out_dir=out_dir,
                limit=limit,
                jina_fallback=jina_fallback,
                insecure=insecure,
            )
        except Exception as e:
            logger.exception("build_press_pdf failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def collect_case_dual_path(
        title_term: str,
        topic_slug: str = "",
        require_regex: str = "",
        out_dir: str = "",
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Dual-path A/B collect + CourtListener search for one topic."""
        try:
            from casenoesis_mcp.collector_tools import collect_case_dual_path as _dual

            return await asyncio.to_thread(
                _dual,
                title_term,
                topic_slug=topic_slug,
                require_regex=require_regex,
                out_dir=out_dir,
            )
        except Exception as e:
            logger.exception("collect_case_dual_path failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def collect_conduct_documents(
        domain: str = "fraud", max_docs: int = 40, pages: int = 1, kind: str = "", search_only: bool = False
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Collect the filings that narrate an offense. Free RECAP only; never PACER.

        Three kinds: statement_of_offense (statements of offense and of facts),
        factual_basis (factual bases, resumes, proffers, stipulated facts), and
        complaint_affidavit (criminal complaints with the agent's affidavit).
        Searches CourtListener at the document level for filings RECAP already
        holds, in one offense domain: fraud, trafficking, forced_labor, cyber,
        csea, extortion, drugs, firearms, corruption, stalking, smuggling,
        racketeering, a comma-separated list, or all. Saves PDFs under
        data/collected/recap/<domain>/. search_only reports how many are free
        and downloads nothing. Each search page is one API call against a quota
        of 50 an hour; at most 300 documents and 3 pages per call.
        """
        try:
            from casenoesis_mcp.collector_tools import collect_conduct_documents as _collect

            return await asyncio.to_thread(_collect, domain=domain, max_docs=max_docs, pages=pages, kind=kind, search_only=search_only)
        except Exception as e:
            logger.exception("collect_conduct_documents failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def download_free_recap(
        document_id: str = "",
        docket_id: str = "",
        domain: str = "fraud",
        out_dir: str = "",
        max_docs: int = 1,
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Download a known free RECAP filing into data/collected/recap/.

        Pass document_id for one filing, or docket_id to take up to max_docs free
        documents on that docket. Refuses PACER/ECF. Pair with search_courtlistener
        → list_free_recap_documents → resolve_free_recap_download when scouting.
        """
        try:
            from casenoesis_mcp.collector_tools import download_free_recap as _dl

            return await asyncio.to_thread(
                _dl,
                document_id=document_id,
                docket_id=docket_id,
                domain=domain,
                out_dir=out_dir,
                max_docs=max_docs,
            )
        except Exception as e:
            logger.exception("download_free_recap failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def fetch_seed_docs(seeds: str, out_dir: str = "", limit: int = 0) -> dict[str, Any]:
        """WRITE (local MCP only). Download a public-document seed into data/collected/hyletic_data/.
        """
        try:
            from casenoesis_mcp.collector_tools import fetch_seed_docs as _fetch

            return await asyncio.to_thread(_fetch, seeds=seeds, out_dir=out_dir, limit=limit)
        except Exception as e:
            logger.exception("fetch_seed_docs failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def harvest_wayback_policy(
        profile: str = "",
        out_dir: str = "",
        limit: int = 1,
        snapshots: int = 1,
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Dated Wayback snapshot of a platform policy page."""
        try:
            from casenoesis_mcp.collector_tools import harvest_wayback_policy as _harvest

            return await asyncio.to_thread(
                _harvest, profile=profile, out_dir=out_dir, limit=limit, snapshots=snapshots
            )
        except Exception as e:
            logger.exception("harvest_wayback_policy failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def harvest_platform_litigation(
        profile: str = "",
        out_dir: str = "",
        max_docs: int = 1,
    ) -> dict[str, Any]:
        """WRITE (local MCP only). One free RECAP platform-litigation filing. Never PACER."""
        try:
            from casenoesis_mcp.collector_tools import harvest_platform_litigation as _harvest

            return await asyncio.to_thread(
                _harvest, profile=profile, out_dir=out_dir, max_docs=max_docs
            )
        except Exception as e:
            logger.exception("harvest_platform_litigation failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def harvest_statutes(profile: str = "", out_dir: str = "", limit: int = 1) -> dict[str, Any]:
        """WRITE (local MCP only). GovInfo PDF for citations in the statute profile."""
        try:
            from casenoesis_mcp.collector_tools import harvest_statutes as _harvest

            return await asyncio.to_thread(_harvest, profile=profile, out_dir=out_dir, limit=limit)
        except Exception as e:
            logger.exception("harvest_statutes failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def harvest_calibration(profile: str = "", out_dir: str = "", limit: int = 1) -> dict[str, Any]:
        """WRITE (local MCP only). Public calibration reports. Not raw CyberTipline cases."""
        try:
            from casenoesis_mcp.collector_tools import harvest_calibration as _harvest

            return await asyncio.to_thread(_harvest, profile=profile, out_dir=out_dir, limit=limit)
        except Exception as e:
            logger.exception("harvest_calibration failed")
            return {"error": str(e), "write": True}

    @mcp.tool()
    async def reproduce_from_lookup(
        lookup: str = "",
        kind: str = "",
        limit: int = 1,
        run: bool = False,
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Refetch public JSONL rows. run=false returns the plan and does not fetch. Never PACER."""
        try:
            from casenoesis_mcp.collector_tools import reproduce_from_lookup as _reproduce

            return await asyncio.to_thread(
                _reproduce, lookup=lookup, kind=kind, limit=limit, run=run
            )
        except Exception as e:
            logger.exception("reproduce_from_lookup failed")
            return {"error": str(e), "write": True}


# ---------------------------------------------------------------------------
# SDK encoding: collected record -> CASE/UCO graph, on the pinned SDK.
# See docs/sdk-encoding.md.
# ---------------------------------------------------------------------------


@mcp.tool()
async def encoding_status() -> dict[str, Any]:
    """READ. The pinned SDK, and counts of collected and encoded records."""
    try:
        from encoding import records as record_layer

        return await asyncio.to_thread(record_layer.status)
    except Exception as e:
        logger.exception("encoding_status failed")
        return {"error": str(e), "write": False}


@mcp.tool()
async def gate_graph(graph_path: str) -> dict[str, Any]:
    """READ. Validate one graph under data/encoded/ with the pinned SDK.

    SHACL plus the closed-world concept check. Returns the receipt; files nothing.
    """
    try:
        from encoding import corpus, sdk

        resolved = Path(graph_path).expanduser().resolve()
        if not resolved.is_relative_to(corpus.ENCODED.resolve()):
            return {"error": f"Path must be under {corpus.ENCODED}", "write": False}
        return await asyncio.to_thread(sdk.gate, resolved)
    except Exception as e:
        logger.exception("gate_graph failed")
        return {"error": str(e), "write": False}


if _COLLECTOR_WRITE_ENABLED:

    @mcp.tool()
    async def encoding_process_records(
        kind: str = "",
        domain: str = "",
        limit: int = 25,
        record_ids: list[str] | None = None,
        gate: bool = True,
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Run the SDK document processor over collected records.

        Rule-based, no model. Writes a CASE/UCO graph per record under
        data/encoded/records/, removes names from it, and validates it. Records
        already encoded are skipped; a record that failed before is tried again.
        At most 200 per call.
        """
        try:
            from encoding import corpus
            from encoding import records as record_layer

            def _run() -> dict[str, Any]:
                entries = corpus.load_index()
                if record_ids:
                    wanted = set(record_ids)
                    entries = [e for e in entries if e["record_id"] in wanted]
                else:
                    if kind:
                        entries = [e for e in entries if e["kind"] == kind]
                    if domain:
                        entries = [e for e in entries if corpus.in_domain(e, domain)]
                    entries = [
                        e for e in entries
                        if (record_layer.read_status(e["record_id"]) or {}).get("status") != "encoded"
                    ]
                return record_layer.run(entries[: max(1, min(limit, 200))], gate=gate)

            return await asyncio.to_thread(_run)
        except Exception as e:
            logger.exception("encoding_process_records failed")
            return {"error": str(e), "write": True}


# ---------------------------------------------------------------------------
# Extraction engine: readers, span gate, family vote, review queue, cases.
# Every tool answers from stored assertions and decisions. None calls a model
# and none writes a value. Record text in a result has names masked.
# See Architecture design.md, section 5.
# ---------------------------------------------------------------------------


MAX_ROWS_PROCESS = 200


async def _explore(name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        from extraction import explore

        return await asyncio.to_thread(getattr(explore, name), *args, **kwargs)
    except Exception as e:
        logger.exception("extraction %s failed", name)
        return {"error": str(e), "write": False}


@mcp.tool()
async def extraction_status() -> dict[str, Any]:
    """READ. The extraction engine at a glance.

    Records read, assertions by reader family, decisions by field and status,
    the review queue by field and state, cases, and graphs built and validated.
    """
    return await _explore("status")


@mcp.tool()
async def extraction_fields() -> dict[str, Any]:
    """READ. The field registry: every field, its roles, and its labels.

    Call this first to learn what `extraction_search` and `extraction_count`
    accept. Also lists the readers and which evidence family each belongs to.
    """
    try:
        from extraction import fields, profiles
        from extraction.readers import FAMILY, reader_versions

        return {
            "fields": {
                spec.name: {
                    "shape": spec.shape,
                    "roles": list(spec.roles),
                    "never_stored": list(spec.excluded_roles),
                    "labels": list(spec.vocabulary)
                    or (list(profiles.labels(spec.name)) if spec.name in ("scheme", "channel", "platform") else []),
                    "description": spec.description,
                }
                for spec in fields.all_fields()
            },
            "readers": reader_versions(),
            "families": FAMILY,
        }
    except Exception as e:
        logger.exception("extraction_fields failed")
        return {"error": str(e), "write": False}


@mcp.tool()
async def extraction_record(record_id: str) -> dict[str, Any]:
    """READ. One record: every settled value, which families settled it, and what is open.

    Each open mention comes with the sentence around it, the mention marked
    ⟦like this⟧ and names masked. People appear as person-1, person-2.
    """
    return await _explore("record", record_id)


@mcp.tool()
async def extraction_review_queue(
    field: str = "", state: str = "", kind: str = "", limit: int = 25
) -> dict[str, Any]:
    """READ. Mentions the vote left open, for a person to decide.

    state: contested (two families disagree), weak (one family, low
    confidence), or self_contradiction (one family said two things).
    A verdict goes in config/extraction_overrides.json; no tool writes one.
    """
    return await _explore("review_queue", field, state, kind, limit)


@mcp.tool()
async def extraction_search(
    field: str,
    value: str = "",
    role: str = "",
    kind: str = "",
    domain: str = "",
    status: str = "",
    minimum: float | None = None,
    maximum: float | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """READ. A cohort: records with a settled value for a field.

    Examples: field="scheme", value="romance", domain="fraud";
    field="money", role="loss", minimum=1000000;
    field="sentence", role="imposed", minimum=120 (months).
    status="agreed" keeps only values two reader families settled together.
    """
    return await _explore("search", field, value, role, kind, domain, status, minimum, maximum, limit)


@mcp.tool()
async def extraction_count(field: str, by: str = "value", kind: str = "", domain: str = "", limit: int = 40) -> dict[str, Any]:
    """READ. How many records settled each label (by="value") or role (by="role") of a field."""
    return await _explore("distribution", field, kind, domain, by, limit)


@mcp.tool()
async def extraction_case(case_or_record_id: str) -> dict[str, Any]:
    """READ. A case: the records in it, why each was linked, and what each settled.

    Also lists candidate links: records that share only a docket number, which
    is not enough to merge them.
    """
    return await _explore("case", case_or_record_id)


@mcp.tool()
async def case_timeline(case_or_record_id: str) -> dict[str, Any]:
    """READ. One case's events in order, with its defendants and whose each term and amount is.

    Each event has a kind (arrest, complaint, indictment, information, charge,
    plea, verdict, conviction, sentencing, offense), a date where a record
    gives one, the defendants it applies to (p1, p2; no names), the records
    that report it, and how its date was read: stated in the text, read from
    "today" against the publication date, or taken from a filing date. An
    event with no date is placed by where its kind falls in a prosecution, and
    `order_basis` says so.
    """
    return await _explore("timeline", case_or_record_id)


async def _process(name: str, **kwargs: Any) -> dict[str, Any]:
    try:
        from process_mining import views

        return await asyncio.to_thread(getattr(views, name), **kwargs)
    except Exception as e:
        logger.exception("process mining %s failed", name)
        return {"error": str(e), "write": False}


@mcp.tool()
async def process_log() -> dict[str, Any]:
    """READ. The event log process mining runs on: traces (one per defendant per case),
    events by kind, how many events have a date, and how long traces are."""
    return await _process("log_summary")


@mcp.tool()
async def process_variants(level: str = "detailed", dated_only: bool = False, domain: str = "", limit: int = 20) -> dict[str, Any]:
    """READ. The paths cases take, most common first, each with its share of traces.

    level "coarse" folds complaint, indictment and information into "charge"
    and plea, verdict and conviction into "disposition". dated_only keeps only
    events with a date, so no order in the result is assumed.
    Records report what they report: a path of "plea > sentencing" means the
    records of that case mention those two steps, not that nothing else happened.
    """
    return await _process("variants", level=level, dated_only=dated_only, domain=domain, limit=max(1, min(limit, MAX_ROWS_PROCESS)))


@mcp.tool()
async def process_model(level: str = "detailed", noise: float = 0.2, dated_only: bool = False, domain: str = "") -> dict[str, Any]:
    """READ. The process model discovered from the event log by the Inductive Miner.

    Returns the process tree (sequence, one-of, any-order, loop), how well the
    log replays on it, and the directly-follows graph with the median days
    between steps where both are dated to the day. noise in [0, 1]: 0 keeps
    every behaviour seen, higher values drop rare orderings from the model.
    The model describes prosecuted cases as their public records report them.
    """
    return await _process("model", level=level, noise=max(0.0, min(noise, 1.0)), dated_only=dated_only, domain=domain)


@mcp.tool()
async def process_conformance(domain: str = "", limit: int = 20) -> dict[str, Any]:
    """READ. Traces that depart from the order of a federal prosecution.

    Three kinds: `order` (two dated events in an order procedure does not
    allow, such as a sentencing dated before the plea), `repeat` (the same
    step on two dates: a resentencing, a superseding indictment), and
    `plea_and_verdict`. A missing step is never counted: records are
    incomplete. A departure is either something that happened in the case or
    an error in a record or in the reading of it. This says where to look.
    """
    return await _process("conformance", domain=domain, limit=max(1, min(limit, MAX_ROWS_PROCESS)))


@mcp.tool()
async def conduct_summary() -> dict[str, Any]:
    """READ. The acts read from records: how many, by kind, how many carry a date or name a technology.

    An act is a step of the offense itself: setup, contact, deception, demand,
    threat, transfer, movement, access, recruit, transport, control, exploit,
    supply, concealment, and detection (what investigators did). Acts are read
    by rule readers that know a fixed set of verbs; a filing that tells the
    same act in other words is missed.
    """
    return await _process("conduct_summary")


@mcp.tool()
async def conduct_record(record_id: str) -> dict[str, Any]:
    """READ. One record's acts in the order it tells them: kind, phase, date, the technology
    named in the act's sentence, and the path at the means, act and phase levels. No names, no text."""
    return await _process("conduct_record", record_id=record_id)


@mcp.tool()
async def conduct_paths(level: str = "act", domain: str = "", kind: str = "", noise: float = 0.2, limit: int = 15) -> dict[str, Any]:
    """READ. The paths offenses take, at one level of abstraction.

    level: "means" (the act with its technology, such as contact[whatsapp]),
    "act" (the act alone), or "phase" (preparation, approach, leverage, harm,
    exit). kind: "court" keeps filings such as statements of offense, "press"
    keeps releases. Returns the most common paths and, for act and phase, the
    process tree the Inductive Miner finds with how well the paths replay on it.
    """
    if level not in ("means", "act", "phase"):
        return {"error": "level must be means, act or phase", "write": False}
    return await _process("conduct_paths", level=level, domain=domain, kind=kind, noise=max(0.0, min(noise, 1.0)), limit=max(1, min(limit, MAX_ROWS_PROCESS)))


@mcp.tool()
async def conduct_transitions(level: str = "act", domain: str = "", kind: str = "") -> dict[str, Any]:
    """READ. A first-order transition model of offenses: from each step, how often each step follows,
    with counts, and the entropy of what follows. The observed side of a Markov model."""
    if level not in ("means", "act", "phase"):
        return {"error": "level must be means, act or phase", "write": False}
    return await _process("conduct_transitions", level=level, domain=domain, kind=kind)


@mcp.tool()
async def conduct_compare(kind: str = "", min_trajectories: int = 25) -> dict[str, Any]:
    """READ. How far apart the offense domains are at the phase, act and means levels.

    Jensen-Shannon divergence between each pair of domains, over steps and over
    transitions, beside the same figure with domain labels shuffled. Read the
    gap above the shuffled figure, not the raw number: a coarser level has
    fewer categories and that alone lowers a divergence. This is a measurement
    over what records narrate, read by rule readers. It is not a test result.
    """
    return await _process("conduct_compare", kind=kind, min_trajectories=max(2, int(min_trajectories)))


@mcp.tool()
async def conduct_means(domain: str = "", kind: str = "") -> dict[str, Any]:
    """READ. Which technology is named at which act, per domain: at what step of an offense
    each channel or platform is used."""
    return await _process("conduct_means", domain=domain, kind=kind)


async def _esm(name: str, **kwargs: Any) -> dict[str, Any]:
    try:
        from state_machines import analysis

        return await asyncio.to_thread(getattr(analysis, name), **kwargs)
    except Exception as e:
        logger.exception("state machine %s failed", name)
        return {"error": str(e), "write": False}


@mcp.tool()
async def esm_machine(kind: str = "", domain: str = "", level: str = "act") -> dict[str, Any]:
    """READ. The Exploitation State Machine fitted to the acts read from records.

    States are milestones the offense has reached: Preparation, InitialContact,
    Conditioning, Exploitation, Maintenance (the last four close to the CAC
    grooming phases). Actions are kinds of act, or acts with their technology at
    level "means". Returns the action space at each state, the observed policy,
    and every T(s'|s,a) estimate with its counts. Terminal: Completed (exploitation
    reached), Disrupted (detection narrated first), Unresolved.
    """
    if level not in ("act", "means"):
        return {"error": "level must be act or means", "write": False}
    return await _esm("machine_report", kind=kind, domain=domain, level=level)


@mcp.tool()
async def esm_invariance(kind: str = "", min_trajectories: int = 80, repeats: int = 50) -> dict[str, Any]:
    """READ. Do domains share states while differing in acts and technology?

    Jensen-Shannon divergence between domains at three levels (transitions
    between states; the act taken at each state; the act and its technology),
    each beside the divergence with domain labels shuffled, on equal-size
    subsamples. The claim that states hold while actions vary predicts little
    excess at the state level and clear excess at the other two.
    """
    return await _esm("invariance_report", kind=kind, minimum=max(20, int(min_trajectories)), repeats=max(5, min(int(repeats), 200)))


@mcp.tool()
async def esm_decide(kind: str = "", domain: str = "", nulls: int = 100) -> dict[str, Any]:
    """READ. The goal-conditioned decision model (goal: Exploitation) and its tests.

    Rewards are declared, not estimated: `uniform`, and the researcher's
    friction table when config/esm_costs.json exists. For each: L*, observed
    paths beside it, the share of choices that are optimal, a fitted
    rationality beta against random cost models, and the same results under
    nine feasibility cutoffs. Published at the level of states and kinds of act only.
    """
    return await _esm("decision_report", kind=kind, domain=domain, nulls=max(10, min(int(nulls), 500)))


@mcp.tool()
async def esm_laws(kind: str = "") -> dict[str, Any]:
    """READ. Backbone and laws read off observed trajectories, per domain.

    Coverage of each state and the backbone at each threshold; contact primacy
    (InitialContact before Exploitation); conditioning before exploitation;
    maintenance after it; Exploitation-Maintenance loops; what avoiding each
    pre-exploitation state would leave; and the exploitation predicate (the
    victim is the source of what is taken). Use kind="court" for narratives
    told from the start.
    """
    return await _esm("laws_report", kind=kind)


@mcp.tool()
async def process_case(case_or_record_id: str) -> dict[str, Any]:
    """READ. One case against the discovered model and against procedure: its timeline,
    each defendant's path aligned with the closest path the model allows, and any
    departure from procedural order."""
    return await _process("case", case_id=case_or_record_id)


@mcp.tool()
async def graph_sparql(query: str, limit: int = 200) -> dict[str, Any]:
    """READ. SPARQL over the local triple store of engine graphs.

    One named graph per record: urn:casenoesis:record:<record-id>. The default
    graph is the union of all of them. Prefixes uco-core, uco-identity,
    uco-observable, uco-role, uco-action, case-investigation, legalproc, and
    xsd are added for you. Settled labels are tags on the record node:
    "scheme:romance", "channel:cryptocurrency", "stage:sentenced".
    Read-only; updates are refused. No names are in the store.

    Example: SELECT ?g ?amount WHERE { GRAPH ?g { ?o a legalproc:RestitutionOrder ;
    legalproc:monetaryAmount ?amount . FILTER(?amount >= 1000000) } }
    """
    try:
        from extraction import triples

        return await asyncio.to_thread(triples.query, query, limit)
    except Exception as e:
        logger.exception("graph_sparql failed")
        return {"error": str(e), "write": False}


@mcp.tool()
async def graph_store_status() -> dict[str, Any]:
    """READ. The local triple store: how many record graphs and quads, where it is, and example queries."""
    try:
        from extraction import triples

        return {**await asyncio.to_thread(triples.status), "examples": triples.EXAMPLES}
    except Exception as e:
        logger.exception("graph_store_status failed")
        return {"error": str(e), "write": False}


@mcp.tool()
async def extraction_agreement() -> dict[str, Any]:
    """READ. How the reader families compare, per field.

    Counts of mentions two families settled together, one family settled, and
    families contested. This measures agreement between readers. It is not an
    accuracy figure; no labelled sample exists yet.
    """
    return await _explore("agreement")


if _COLLECTOR_WRITE_ENABLED:

    @mcp.tool()
    async def extraction_run(
        kind: str = "",
        domain: str = "",
        limit: int = 200,
        record_ids: list[str] | None = None,
        build_graphs: bool = False,
    ) -> dict[str, Any]:
        """WRITE (local MCP only). Read collected records with the extraction engine.

        Runs the readers, the span gate, and the vote, and stores assertions and
        decisions in data/extracted/noesis.db. Then relinks cases, links defendants
        across each case's records, and rebuilds every case's timeline. Records already read are skipped.
        Deterministic; no model unless CASENOESIS_LLM=1 is set on this machine.
        build_graphs also writes and validates a CASE/UCO graph per record and
        loads it into the local triple store.
        At most 2,000 records per call.
        """
        try:
            from encoding import corpus
            from extraction import cases as case_layer
            from extraction import graph as graph_layer
            from extraction import pipeline, store

            def _run() -> dict[str, Any]:
                entries = corpus.load_index()
                if record_ids:
                    wanted = set(record_ids)
                    entries = [e for e in entries if e["record_id"] in wanted]
                else:
                    if kind:
                        entries = [e for e in entries if e["kind"] == kind]
                    if domain:
                        entries = [e for e in entries if corpus.in_domain(e, domain)]
                    known = store.known_text_hashes(store.connect())
                    entries = [e for e in entries if e["record_id"] not in known]
                chosen = entries[: max(1, min(limit, 2000))]
                out: dict[str, Any] = {"read": pipeline.run(chosen)}
                out["cases"] = case_layer.build()
                # People and events are rebuilt from the decisions, so they follow every run.
                from extraction import events as event_layer
                from extraction import people as people_layer

                out["people"] = people_layer.build()
                from extraction import conduct as conduct_layer

                built = conduct_layer.build()
                out["conduct"] = {key: built[key] for key in ("records_with_acts", "acts", "with_a_date")}
                events_built = event_layer.build()
                out["events"] = {key: events_built[key] for key in ("cases_with_events", "events", "by_type")}
                if build_graphs:
                    from extraction import triples

                    out["graphs"] = graph_layer.build([e["record_id"] for e in chosen], gate=True)
                    out["triple_store"] = triples.load()
                return out

            return await asyncio.to_thread(_run)
        except Exception as e:
            logger.exception("extraction_run failed")
            return {"error": str(e), "write": True}


if __name__ == "__main__":
    # CaseNoesis MCP is a private local agent host (stdio). It is not a public
    # CaseLinker-style SSE/HTTP service. Opt in to local HTTP only with
    # CASENOESIS_MCP_HTTP=1 (still bind localhost, never 0.0.0.0).
    allow_http = os.getenv("CASENOESIS_MCP_HTTP", "").strip().lower() in {"1", "true", "yes", "on"}
    if MCP_TRANSPORT != "stdio" and not allow_http:
        logger.error(
            "CaseNoesis MCP is stdio-only. Use Cursor mcp.json, or set "
            "CASENOESIS_MCP_HTTP=1 MCP_TRANSPORT=sse for a local loopback debug server."
        )
        sys.exit(2)
    if MCP_TRANSPORT == "sse" and allow_http:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = PORT
        _sse_app = build_mcp_sse_app()
        import uvicorn

        uvicorn.run(_sse_app, host="127.0.0.1", port=PORT)
    else:
        mcp.run(transport="stdio")
