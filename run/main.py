"""
FastAPI Backend for CaseLinker
Provides API endpoints for visualization frontend
"""

from fastapi import FastAPI, Request, Query, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Any, Optional, Tuple
import sys
import json
import os
import logging
import time
from datetime import datetime
from pathlib import Path
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Storage Layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Clustering & Analysis Layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Visualization Layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Use PostgreSQL if DATABASE_URL is set, otherwise use SQLite
import os
if os.getenv("DATABASE_URL"):
    try:
        from storage_postgres import CaseStorage
        print("✅ Using PostgreSQL database")
    except ImportError:
        print("⚠️  PostgreSQL storage not available, falling back to SQLite")
        from storage import CaseStorage
else:
    from storage import CaseStorage
    print("✅ Using SQLite database (local development)")
from facet_tree import (
    DEFAULT_FACET_ORDER,
    build_facet_tree,
    cohort_members_for_path,
    count_nodes,
    distinct_field_values,
    enrich_cases_with_era_period,
    facet_order_subset,
    filter_cases_by_constraints,
    max_tree_depth,
)
from analysis import tag_threader, return_tagged_cases, run_automated_analysis
# Import Redis cache helper
try:
    from redis_cache import (
        REDIS_AVAILABLE, 
        get_cached, 
        set_cached, 
        get_cache_key,
        clear_all_cache
    )
except ImportError:
    # Fallback if redis_cache module not found
    REDIS_AVAILABLE = False
    def get_cached(key):
        return None
    def set_cached(key, value, ttl=3600):
        return False
    def get_cache_key(endpoint, **kwargs):
        return f"caselinker:{endpoint}"

app = FastAPI(title="CaseLinker API")

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _is_local_request(request: Request) -> bool:
    """Treat localhost traffic as internal for local development."""
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}


def _is_internal_api_request(request: Request) -> bool:
    """
    Internal API guard for sensitive endpoints.

    - Allows localhost requests (dev).
    - Allows requests with matching internal key header/query.
    """
    if _is_local_request(request):
        return True

    expected = os.getenv("CASELINKER_INTERNAL_API_KEY", "").strip()
    if not expected:
        return False

    provided = (
        request.headers.get("X-CaseLinker-Internal-Key")
        or request.query_params.get("internal_key")
        or ""
    ).strip()
    return bool(provided) and provided == expected


def _sanitize_case_for_public(case: Dict[str, Any]) -> Dict[str, Any]:
    """Remove raw narrative material from public case payloads."""
    case.pop("raw_data", None)
    extracted = case.get("extracted_features")
    if isinstance(extracted, dict):
        extracted.pop("raw_data", None)
        extracted.pop("case_text", None)
    return case


def _extract_case_text_value(case: Dict[str, Any]) -> str:
    """Best-effort extraction of case narrative text from a case payload."""
    direct = case.get("case_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    raw_data = case.get("raw_data")
    if isinstance(raw_data, dict):
        text = raw_data.get("case_text")
        if isinstance(text, str) and text.strip():
            return text
    elif isinstance(raw_data, str) and raw_data.strip():
        try:
            parsed = json.loads(raw_data)
            if isinstance(parsed, dict):
                text = parsed.get("case_text")
                if isinstance(text, str) and text.strip():
                    return text
        except Exception:
            pass
    return ""


def _attach_case_text_to_automated_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure triaged cases include `case_text` for public automated-analysis UI.
    Keeps `raw_data` out of response while preserving quick modal rendering.
    """
    if not isinstance(analysis, dict):
        return analysis

    triaged = analysis.get("triaged_cases")
    if not isinstance(triaged, list) or not triaged:
        return analysis

    ids = []
    for c in triaged:
        if isinstance(c, dict):
            cid = c.get("id")
            if isinstance(cid, str) and cid:
                ids.append(cid)
    ids = list(dict.fromkeys(ids))
    if not ids:
        return analysis

    full_cases = storage.get_cases_by_ids(ids, include_raw_data=True) or []
    text_by_id: Dict[str, str] = {}
    for fc in full_cases:
        if not isinstance(fc, dict):
            continue
        cid = fc.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        text = _extract_case_text_value(fc)
        if text:
            text_by_id[cid] = text

    for c in triaged:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        if not c.get("case_text"):
            case_text = text_by_id.get(cid, "")
            if case_text:
                c["case_text"] = case_text
        # Never expose raw_data via this endpoint.
        c.pop("raw_data", None)

    return analysis


def _case_summary_slim(case: Dict[str, Any]) -> Dict[str, Any]:
    """Slim case shape for chunk/by-ids summary APIs (no narratives/raw blobs)."""
    out = {
        "id": case.get("id"),
        "source": case.get("source"),
        "source_url": case.get("source_url"),
        "date_start": case.get("date_start"),
        "date_end": case.get("date_end"),
        "date_range": case.get("date_range"),
        "victim_count": case.get("victim_count"),
        "perpetrator_count": case.get("perpetrator_count"),
        "relationship_to_victim": case.get("relationship_to_victim"),
        "platforms_used": case.get("platforms_used"),
        "severity_indicators": case.get("severity_indicators"),
        "case_topics": case.get("case_topics"),
        "tags": case.get("tags"),
        "investigation_type": case.get("investigation_type"),
        "agencies_involved": case.get("agencies_involved"),
        "organizations": case.get("organizations"),
        # Needed by visualization/index.html Previous Perpetrator chart and stats (slim API otherwise omits it).
        "perpetrator_registered_sex_offender": case.get("perpetrator_registered_sex_offender"),
    }
    return out


class CaseIdsBody(BaseModel):
    """Up to 500 case ids per request for batched summaries (no raw narratives)."""

    ids: List[str] = Field(..., min_length=1)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    logger.info(
        f"{request.method} {request.url.path}",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "process_time": round(process_time, 3),
            "client_ip": request.client.host if request.client else None
        }
    )
    
    return response

# Initialize storage
if os.getenv("DATABASE_URL"):
    # PostgreSQL - use DATABASE_URL directly
    storage = CaseStorage()
    db_path = None  # PostgreSQL doesn't use file path
else:
    # SQLite - use file path
    try:
        from config import DATABASE_PATH
    except ImportError:
        DATABASE_PATH = "caselinker.db"
    
    # Fix path for Railway - Procfile runs from 'run/' directory, so go up one level
    if Path(__file__).parent.name == 'run':
        db_path = Path(__file__).parent.parent / DATABASE_PATH
    else:
        db_path = Path(DATABASE_PATH)
    
    storage = CaseStorage(str(db_path))

# Facet tree API: rebuilt when case count changes (not persisted to disk)
_facet_tree_cache_payload: Optional[Dict[str, Any]] = None
_facet_tree_cache_key: Optional[tuple] = None


def _parse_facet_constraints_param(raw: Optional[str]) -> Dict[str, List[str]]:
    """Query JSON: { field_key: [allowed values, ...], ... }; any tag on the case may match."""
    if not raw or not str(raw).strip():
        return {}
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return {}
        valid_keys = {k for k, _ in DEFAULT_FACET_ORDER}
        out: Dict[str, List[str]] = {}
        for k, v in obj.items():
            fk = str(k)
            if fk not in valid_keys:
                continue
            if isinstance(v, list):
                out[fk] = [str(x) for x in v if x is not None and str(x).strip() != ""]
            elif v is not None and str(v).strip():
                out[fk] = [str(v).strip()]
        return out
    except json.JSONDecodeError:
        return {}


def _parse_include_facets_param(raw: Optional[str]) -> Optional[List[str]]:
    """Comma-separated field keys for ``/api/facet-tree``.

    ``None`` (query param absent): full DEFAULT order.
    Present but empty (e.g. ``?include_facets=``): no partition fields — one cohort.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return []
    valid = {k for k, _ in DEFAULT_FACET_ORDER}
    parts = [p.strip() for p in s.split(",") if p.strip()]
    filtered = [p for p in parts if p in valid]
    return filtered or None


def _triage_saved_bundle_corpus_live(constraints: Dict[str, List[str]]) -> Dict[str, Any]:
    """
    Run the saved triage bundle on live DB cases (facet-filtered when constraints are set).
    Response shape matches the former /api/triage-model-corpus JSON-file contract; no
    triage_corpus_predictions.json is read.
    """
    try:
        from triage import build_corpus_predictions_payload, default_bundle_path, load_triage_bundle
    except ImportError as e:
        logger.warning("triage live corpus: import failed: %s", e)
        return {
            "corpus_predictions_available": False,
            "model_case_ids_by_tier": {},
            "corpus_class_names": [],
            "n_cases": 0,
            "facet_filter_applied": bool(constraints),
            "corpus_predictions_stale": False,
        }

    try:
        bundle_path = default_bundle_path()
        bundle = load_triage_bundle(bundle_path)
    except FileNotFoundError:
        return {
            "corpus_predictions_available": False,
            "model_case_ids_by_tier": {},
            "corpus_class_names": [],
            "n_cases": 0,
            "facet_filter_applied": bool(constraints),
            "corpus_predictions_stale": False,
        }
    except Exception:
        logger.exception("triage live corpus: bundle load failed")
        return {
            "corpus_predictions_available": False,
            "model_case_ids_by_tier": {},
            "corpus_class_names": [],
            "n_cases": 0,
            "facet_filter_applied": bool(constraints),
            "corpus_predictions_stale": False,
        }

    bp_resolved = str(Path(bundle_path).resolve())
    cases = storage.get_all_cases(include_raw_data=False) or []
    enrich_cases_with_era_period(cases)
    filtered = filter_cases_by_constraints(cases, constraints) if constraints else cases

    if not filtered:
        cn = list(bundle.class_names)
        return {
            "corpus_predictions_available": True,
            "model_case_ids_by_tier": {n: [] for n in cn},
            "corpus_class_names": cn,
            "n_cases": 0,
            "corpus_predictions_stale": False,
            "facet_filter_applied": bool(constraints),
            "corpus_predictions_meta": {
                "generated_at": datetime.now().isoformat(),
                "bundle_path": bp_resolved,
                "n_cases_db": len(cases),
                "n_cases_in_view": 0,
                "source": "live_db",
            },
        }

    try:
        payload = build_corpus_predictions_payload(filtered, bundle, bp_resolved)
    except Exception:
        logger.exception("triage live corpus: inference failed")
        return {
            "corpus_predictions_available": False,
            "model_case_ids_by_tier": {},
            "corpus_class_names": [],
            "n_cases": 0,
            "facet_filter_applied": bool(constraints),
            "corpus_predictions_stale": False,
        }

    return {
        "corpus_predictions_available": True,
        "model_case_ids_by_tier": payload["model_case_ids_by_tier"],
        "corpus_class_names": payload["class_names"],
        "n_cases": payload["n_cases"],
        "corpus_predictions_stale": False,
        "facet_filter_applied": bool(constraints),
        "corpus_predictions_meta": {
            "generated_at": payload["generated_at"],
            "bundle_path": payload["bundle_path"],
            "n_cases_db": len(cases),
            "n_cases_in_view": payload["n_cases"],
            "source": "live_db",
        },
    }


def _facet_tree_cache_key_tuple(
    case_count: int,
    max_depth: Optional[int],
    constraints: Dict[str, List[str]],
    include_facets: Optional[List[str]],
) -> tuple:
    if include_facets is None:
        inc = "*"
    elif len(include_facets) == 0:
        inc = ""
    else:
        inc = ",".join(sorted(include_facets))
    cons = json.dumps(constraints, sort_keys=True, ensure_ascii=True)
    return (case_count, max_depth, cons, inc)

# Cached case count (avoids DB hit on every request - case count rarely changes)
_case_count_cache = None
_case_count_cache_time = 0.0
_CASE_COUNT_TTL = 30  # seconds


def _perpetrator_age_bin_label(age: int) -> str:
    """Label for stats chart: ages 18–19 use explicit bin (perp ages are filtered to 18+)."""
    if 18 <= age <= 19:
        return "18-19"
    lo = (age // 5) * 5
    return f"{lo}-{lo + 4}"


def get_case_count() -> int:
    """
    Lightweight helper for counting cases.
    Cached for 30s to avoid DB hit on every cluster-groups/stats request.
    """
    global _case_count_cache, _case_count_cache_time
    try:
        now = time.time()
        if _case_count_cache is not None and (now - _case_count_cache_time) < _CASE_COUNT_TTL:
            return _case_count_cache
        count = storage.get_case_count()
        _case_count_cache = count
        _case_count_cache_time = now
        return count
    except Exception:
        return _case_count_cache if _case_count_cache is not None else 0


def _slim_for_cluster_groups(case_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Strip case objects to ID strings only - frontend only needs IDs for the bubble chart.
    Full case data is fetched via /api/cases when user clicks. Reduces payload 10-50x.
    """
    if not case_groups:
        return []
    result = []
    for group in case_groups:
        slim_group = {k: v for k, v in group.items() if k != 'cases' and k != 'internal_groups'}
        cases = group.get('cases', [])
        slim_group['cases'] = [
            c.get('id') if isinstance(c, dict) else (c if isinstance(c, str) else None)
            for c in cases
        ]
        slim_group['cases'] = [x for x in slim_group['cases'] if x]
        internal = group.get('internal_groups', [])
        slim_group['internal_groups'] = [
            {
                'cases': [
                    c.get('id') if isinstance(c, dict) else (c if isinstance(c, str) else None)
                    for c in ig.get('cases', [])
                ],
                'size': ig.get('size', 0)
            }
            for ig in internal
        ]
        for ig in slim_group['internal_groups']:
            ig['cases'] = [x for x in ig['cases'] if x]
        result.append(slim_group)
    return result

# In-process cache for /api/cases to keep local/dev fast even without Redis
_cases_cache = {
    "include_raw_false": None,
    "include_raw_true": None,
}
_cases_cache_case_count = 0

# Log database status on startup and pre-compute clusters
try:
    test_cases = storage.get_all_cases()
    if db_path:
        print(f"Database active with path: {db_path}")
    else:
        print(f"Database active: PostgreSQL (via DATABASE_URL)")
    print(f"Cases in database: {len(test_cases)}")
    if len(test_cases) == 0:
        if db_path:
            print(f"⚠️  Warning: Database exists but contains 0 cases. Check if database file is in the correct location.")
        else:
            print(f"⚠️  Warning: PostgreSQL database contains 0 cases. Process PDFs to add cases.")
    else:
        # Pre-compute clusters on startup (background, non-blocking)
        # Also warms cluster-groups cache so first /clusters request is fast
        import threading
        def precompute_clusters_background():
            global _cluster_groups_cache, _cluster_groups_cache_case_count, _tags_cache, _tags_cache_case_count
            try:
                print("Pre-computing clusters in background...")
                cases = storage.get_all_cases(include_raw_data=False)
                if cases:
                    # Warm tags cache (tags rarely change)
                    case_topics = set()
                    severity_indicators = set()
                    platforms_used = set()
                    investigation_types = set()
                    relationships = set()
                    status = set()
                    for c in cases:
                        for t in (c.get('case_topics') or []):
                            if t: case_topics.add(t)
                        for s in (c.get('severity_indicators') or []):
                            if s: severity_indicators.add(s)
                        for p in (c.get('platforms_used') or []):
                            if p: platforms_used.add(p)
                        if c.get('investigation_type'): investigation_types.add(c['investigation_type'])
                        if c.get('relationship_to_victim'): relationships.add(c['relationship_to_victim'])
                        if c.get('perpetrator_registered_sex_offender'): status.add('registered_sex_offender')
                    tags_result = {
                        "case_topics": sorted(case_topics), "severity_indicators": sorted(severity_indicators),
                        "platforms_used": sorted(platforms_used), "investigation_types": sorted(investigation_types),
                        "relationships": sorted(relationships), "status": sorted(status)
                    }
                    _tags_cache = tags_result
                    _tags_cache_case_count = len(cases)
                    set_cached(get_cache_key('tags', version=len(cases)), tags_result, ttl=86400)
                    from analysis import run_automated_analysis
                    cluster_data = run_automated_analysis(cases)
                    storage.store_precomputed_clusters(cluster_data, len(cases))
                    case_count = len(cases)
                    # Warm cache: in-memory + Redis so /api/cluster-groups is fast on first request
                    slim_groups = _slim_for_cluster_groups(cluster_data.get('case_groups', []))
                    result = {"success": True, "case_groups": slim_groups, "cached": True, "source": "startup"}
                    cache_key = get_cache_key('cluster-groups', version=case_count)
                    set_cached(cache_key, result, ttl=86400)
                    _cluster_groups_cache = result
                    _cluster_groups_cache_case_count = case_count
                    print(f"✅ Pre-computed clusters stored and cache warmed ({case_count} cases)")
            except Exception as e:
                print(f"⚠️  Error pre-computing clusters: {e}")
        
        cluster_thread = threading.Thread(target=precompute_clusters_background, daemon=True)
        cluster_thread.start()
except Exception as e:
    print(f"⚠️  Database initialization warning: {e}")
    if db_path:
        print(f"   Looking for database at: {db_path}")
        print(f"   Database exists: {db_path.exists()}")
    else:
        print(f"   Using PostgreSQL (check DATABASE_URL environment variable)")


@app.get("/", response_class=HTMLResponse)
async def serve_home():
    """Serve the home page"""
    html_path = Path(__file__).parent.parent / "visualization" / "home.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>CaseLinker</h1><p>Home page not found. Go to <a href='/visualization'>/visualization</a></p>", status_code=404)


@app.get("/api/cases")
@limiter.limit("100/minute")
def get_all_cases(request: Request, include_raw_data: bool = False):
    """
    Get all cases from database.
    Uses Redis caching for fast responses (shared across all workers/instances).
    
    Args:
        include_raw_data: If True, include full raw_data (slower, larger payload).
                         Default False for faster initial loads.
    """
    global _cases_cache, _cases_cache_case_count

    # Bulk export is intentionally internal-only.
    if not _is_internal_api_request(request):
        raise HTTPException(
            status_code=403,
            detail="Bulk case access is restricted to internal requests.",
        )

    try:
        # Get current case count for cache versioning
        current_case_count = get_case_count()

        # If Redis is available, prefer shared cache (works across workers)
        if REDIS_AVAILABLE:
            cache_key = get_cache_key(
                "cases",
                version=current_case_count,
                include_raw_data=include_raw_data,
            )

            cached_result = get_cached(cache_key)
            if cached_result is not None:
                return cached_result

        # Fallback / additional in-process cache for this worker
        cache_key_local = "include_raw_true" if include_raw_data else "include_raw_false"
        if (
            _cases_cache[cache_key_local] is not None
            and _cases_cache_case_count == current_case_count
        ):
            return _cases_cache[cache_key_local]

        # Cache miss - load from database
        cases = storage.get_all_cases(include_raw_data=include_raw_data)
        result = cases if cases else []

        # Update local in-process cache
        _cases_cache[cache_key_local] = result
        _cases_cache_case_count = current_case_count

        # Store in Redis cache (1 hour TTL) if available
        if REDIS_AVAILABLE:
            try:
                cache_key = get_cache_key(
                    "cases",
                    version=current_case_count,
                    include_raw_data=include_raw_data,
                )
                set_cached(cache_key, result, ttl=3600)
            except Exception:
                # If Redis write fails, it's non-fatal
                pass

        return result
    except Exception:
        # Last-resort fallback to direct database query
        try:
            return storage.get_all_cases(include_raw_data=include_raw_data) or []
        except Exception:
            return []


@app.get("/api/cases-summaries-chunk")
@limiter.limit("240/minute")
def cases_summaries_chunk(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(300, ge=1, le=500),
):
    """
    Public paginated case summaries (slim fields, no raw narratives).
    Lets timelines load the full corpus via many small responses instead of one bulk JSON.
    """
    try:
        slice_cases = storage.get_cases_slim_chunk(offset, limit)
        return {
            "offset": offset,
            "limit": limit,
            "count": len(slice_cases),
            "summaries": [_case_summary_slim(c) for c in slice_cases],
        }
    except Exception:
        return {"offset": offset, "limit": limit, "count": 0, "summaries": []}


@app.post("/api/cases-summaries-by-ids")
@limiter.limit("120/minute")
def cases_summaries_by_ids(request: Request, body: CaseIdsBody):
    """
    Public batched summaries for known case ids (e.g. cluster membership).
    Caps at 500 ids per request; does not expose the whole database in one call.
    """
    raw = body.ids
    seen = set()
    ids: List[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip() and x not in seen:
            seen.add(x)
            ids.append(x)
        if len(ids) >= 500:
            break
    if not ids:
        raise HTTPException(status_code=400, detail="Provide at least one case id")
    try:
        cases = storage.get_cases_by_ids(ids, include_raw_data=False)
        return {"summaries": [_case_summary_slim(c) for c in cases]}
    except Exception:
        return {"summaries": []}


@app.get("/api/case-count")
@limiter.limit("120/minute")
def get_case_count_endpoint(request: Request):
    """
    Total cases only (single COUNT query). For headers and spinners without downloading /api/cases.

    Redis-cached briefly so repeat reloads do not each hit the database; UIs also use sessionStorage.
    """
    try:
        if REDIS_AVAILABLE:
            cache_key = get_cache_key("case-count-slim")
            cached = get_cached(cache_key)
            if cached is not None:
                if isinstance(cached, dict) and "count" in cached:
                    return cached
                try:
                    return {"count": int(cached)}
                except (TypeError, ValueError):
                    pass
        n = storage.get_case_count()
        out = {"count": n}
        if REDIS_AVAILABLE:
            set_cached(get_cache_key("case-count-slim"), out, ttl=60)
        return out
    except Exception:
        return {"count": 0}


@app.get("/api/facet-distinct")
@limiter.limit("60/minute")
def get_facet_distinct(request: Request):
    """
    Distinct tag values per facet field (union of all tags on cases), for prune filters.
    The facet tree still partitions by primary bucket per level; filters match if any tag fits.
    """
    try:
        cases = storage.get_all_cases(include_raw_data=False) or []
        enrich_cases_with_era_period(cases)
        options: Dict[str, Any] = {}
        for field_key, label in DEFAULT_FACET_ORDER:
            options[field_key] = {
                "label": label,
                "values": distinct_field_values(cases, field_key),
            }
        return {"total_cases": len(cases), "facets": options}
    except Exception as e:
        logger.exception("facet-distinct failed: %s", e)
        return {"error": str(e), "total_cases": 0, "facets": {}}


@app.get("/api/facet-tree")
@limiter.limit("60/minute")
def get_facet_tree(
    request: Request,
    max_depth: Optional[int] = Query(
        None,
        description="Limit facet levels (see DEFAULT_FACET_ORDER in facet_tree). Omit for full tree.",
        ge=1,
        le=32,
    ),
    facet_constraints: Optional[str] = Query(
        None,
        description='JSON object mapping field keys to allowed value lists (any tag on case may match), e.g. {"case_topics":["family"]}',
    ),
    include_facets: Optional[str] = Query(
        None,
        description="Comma-separated facet field keys (subset, order follows DEFAULT). Omit for all dimensions. "
        "Send empty (include_facets=) for no splits — single cohort.",
    ),
):
    """
    Deterministic facet decision tree over the case store (group-centric cohorts).
    Built in memory from `get_all_cases(include_raw_data=False)` — not stored as a separate file.
    Cached per (case_count, max_depth, constraints, include_facets).
    """
    global _facet_tree_cache_payload, _facet_tree_cache_key

    try:
        current_count = get_case_count()
        constraints = _parse_facet_constraints_param(facet_constraints)
        include_list = _parse_include_facets_param(include_facets)
        cache_key = _facet_tree_cache_key_tuple(current_count, max_depth, constraints, include_list)
        if _facet_tree_cache_payload is not None and _facet_tree_cache_key == cache_key:
            return _facet_tree_cache_payload

        all_cases = storage.get_all_cases(include_raw_data=False) or []
        enrich_cases_with_era_period(all_cases)
        source_count = len(all_cases)
        cases = filter_cases_by_constraints(all_cases, constraints)
        order = facet_order_subset(DEFAULT_FACET_ORDER, include_list)
        active_constraints = {k: v for k, v in constraints.items() if v}
        root_label = "Matching cases" if active_constraints else None
        root = build_facet_tree(
            cases,
            facet_order=order,
            max_depth=max_depth,
            root_label=root_label,
        )
        payload = {
            "total_cases": len(cases),
            "source_case_count": source_count,
            "node_count": count_nodes(root),
            "tree_max_depth": max_tree_depth(root),
            "max_depth_param": max_depth,
            "facet_levels": len(order),
            "facet_levels_full": len(DEFAULT_FACET_ORDER),
            "facet_order": [{"field": k, "label": lab} for k, lab in order],
            "prune_constraints": constraints,
            "include_facets": include_list,
            "root": root.to_dict(),
        }
        _facet_tree_cache_payload = payload
        _facet_tree_cache_key = cache_key
        return payload
    except Exception as e:
        logger.exception("facet-tree failed: %s", e)
        return {
            "error": str(e),
            "total_cases": 0,
            "source_case_count": 0,
            "node_count": 0,
            "tree_max_depth": 0,
            "max_depth_param": max_depth,
            "facet_levels": len(DEFAULT_FACET_ORDER),
            "facet_levels_full": len(DEFAULT_FACET_ORDER),
            "facet_order": [
                {"field": k, "label": lab} for k, lab in DEFAULT_FACET_ORDER
            ],
            "prune_constraints": {},
            "include_facets": None,
            "root": None,
        }


COHORT_SMALL_THRESHOLD = 3
COHORT_DEMO_ACCESS_KEY = os.getenv("COHORT_DEMO_ACCESS_KEY", "demo")


class FacetCohortMembersBody(BaseModel):
    facet_path: List[Dict[str, Any]] = Field(default_factory=list)
    facet_constraints: Dict[str, List[str]] = Field(default_factory=dict)
    access_key: Optional[str] = None


def _facet_path_tuples(raw_path: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for step in raw_path:
        if not isinstance(step, dict):
            continue
        fk = step.get("facet") or step.get("field")
        val = step.get("value")
        if fk is not None and val is not None:
            out.append((str(fk), str(val)))
    return out


@app.post("/api/facet-cohort-members")
@limiter.limit("60/minute")
def post_facet_cohort_members(request: Request, body: FacetCohortMembersBody):
    """
    Case IDs for the cohort at a facet-tree node: same prune constraints as the tree,
    then each path step matches if the case has that value among its tags for the field.
    IDs are omitted for
    small cohorts (n < 3) unless access_key matches the demo key.
    """
    try:
        all_cases = storage.get_all_cases(include_raw_data=False) or []
        enrich_cases_with_era_period(all_cases)
        constraints = body.facet_constraints or {}
        cases = filter_cases_by_constraints(all_cases, constraints)
        path_tuples = _facet_path_tuples(body.facet_path)
        members = cohort_members_for_path(cases, path_tuples)
        ids = sorted(
            str(c["id"])
            for c in members
            if c.get("id") is not None and str(c.get("id")).strip() != ""
        )
        count = len(ids)
        key_ok = (body.access_key or "").strip() == COHORT_DEMO_ACCESS_KEY
        if count < COHORT_SMALL_THRESHOLD:
            if not key_ok:
                return {
                    "count": count,
                    "case_ids": None,
                    "requires_access_key": True,
                    "threshold": COHORT_SMALL_THRESHOLD,
                    "message": (
                        "This cohort has fewer than three cases. Listing IDs is gated "
                        "because small sets raise mosaic and adversarial-use risk. "
                        "Enter the demo access key to reveal case IDs for use elsewhere "
                        "in the system (for example case visualization)."
                    ),
                }
        return {
            "count": count,
            "case_ids": ids,
            "requires_access_key": False,
            "threshold": COHORT_SMALL_THRESHOLD,
        }
    except Exception as e:
        logger.exception("facet-cohort-members failed: %s", e)
        return {"error": str(e), "count": 0, "case_ids": None, "requires_access_key": False}


# Cache for unique tags (invalidates when cases change)
_tags_cache = None
_tags_cache_case_count = 0

# In-memory cache for cluster-groups (avoids Redis round-trip on repeat requests)
_cluster_groups_cache = None
_cluster_groups_cache_case_count = None

@app.get("/api/tags")
@limiter.limit("60/minute")
def get_unique_tags(request: Request):
    """
    Get unique tags/topics from all cases for populating selectors.
    Uses in-memory -> Redis -> DB. Tags rarely change when cases are static.
    """
    global _tags_cache, _tags_cache_case_count

    try:
        current_case_count = get_case_count()

        # 1. In-memory cache
        if _tags_cache is not None and _tags_cache_case_count == current_case_count:
            out = {k: _tags_cache[k] for k in ("case_topics", "severity_indicators", "platforms_used", "investigation_types", "relationships", "status")}
            out["cached"] = True
            return out

        # 2. Redis cache
        cache_key = get_cache_key('tags', version=current_case_count)
        cached = get_cached(cache_key)
        if cached is not None:
            _tags_cache = cached
            _tags_cache_case_count = current_case_count
            out = {k: cached[k] for k in ("case_topics", "severity_indicators", "platforms_used", "investigation_types", "relationships", "status")}
            out["cached"] = True
            return out

        # 3. Compute from cases
        cases = storage.get_all_cases(include_raw_data=False)
        
        # Extract unique values
        case_topics = set()
        severity_indicators = set()
        platforms_used = set()
        investigation_types = set()
        relationships = set()
        status = set()
        
        for case in cases:
            # Case Topics
            topics = case.get('case_topics', [])
            if isinstance(topics, list):
                case_topics.update(t for t in topics if t)
            
            # Severity Indicators
            severity = case.get('severity_indicators', [])
            if isinstance(severity, list):
                severity_indicators.update(s for s in severity if s)
            
            # Platforms
            platforms = case.get('platforms_used', [])
            if isinstance(platforms, list):
                platforms_used.update(p for p in platforms if p)
            
            # Investigation Type
            inv_type = case.get('investigation_type')
            if inv_type:
                investigation_types.add(inv_type)
            
            # Relationship
            rel = case.get('relationship_to_victim')
            if rel:
                relationships.add(rel)
            
            # Registered Sex Offender
            if case.get('perpetrator_registered_sex_offender'):
                status.add('registered_sex_offender')
        
        result = {
            "case_topics": sorted(list(case_topics)),
            "severity_indicators": sorted(list(severity_indicators)),
            "platforms_used": sorted(list(platforms_used)),
            "investigation_types": sorted(list(investigation_types)),
            "relationships": sorted(list(relationships)),
            "status": sorted(list(status))
        }
        _tags_cache = result
        _tags_cache_case_count = current_case_count
        set_cached(cache_key, result, ttl=86400)

        out = {k: result[k] for k in ("case_topics", "severity_indicators", "platforms_used", "investigation_types", "relationships", "status")}
        out["cached"] = False
        return out
    except Exception as e:
        from error_handler import handle_error
        return handle_error(e)


@app.get("/api/cases/{case_id}")
@limiter.limit("100/minute")
def get_case(request: Request, case_id: str):
    """Get a specific case by ID"""
    case = storage.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    # Public callers can still fetch a case, but never raw narrative payloads.
    if not _is_internal_api_request(request):
        case = _sanitize_case_for_public(case)
    return case


@app.get("/api/stats")
@limiter.limit("60/minute")
def get_stats(request: Request):
    """
    Get statistics about cases.
    Uses Redis caching for fast responses.
    """
    try:
        # Get current case count for cache versioning
        current_case_count = get_case_count()
        
        # Build cache key
        cache_key = get_cache_key('stats', version=current_case_count)
        
        # Try Redis cache first
        cached_result = get_cached(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Cache miss - compute stats (no raw_data needed - faster)
        try:
            cases = storage.get_all_cases(include_raw_data=False)
        except Exception:
            cases = []
        
        if not cases:
            result = {
                "total_cases": 0,
                "total_victims": 0,
                "sources": [],
                "source_count": 0,
                "unique_features": 0,
                "unique_organizations": 0,
                "date_range": {"start": None, "end": None}
            }
            set_cached(cache_key, result, ttl=3600)
            return result
        
        # Calculate total victims
        total_victims = 0
        for case in cases:
            victim_count = case.get('victim_count')
            if victim_count and isinstance(victim_count, (int, float)):
                total_victims += victim_count
            elif case.get('raw_data', {}).get('victim_count'):
                try:
                    total_victims += int(case['raw_data']['victim_count'])
                except:
                    pass
        
        # Get unique sources
        sources = set()
        for case in cases:
            source = case.get('source') or case.get('raw_data', {}).get('source')
            if source:
                sources.add(source)
        
        # Calculate total extracted features - DIRECT COUNT from actual database data
        total_features = 0
        for case in cases:
            # Count array/list features - each item counts as 1 feature
            platforms = case.get('platforms_used', [])
            if isinstance(platforms, list) and platforms:
                total_features += len([p for p in platforms if p])
            
            topics = case.get('case_topics', [])
            if isinstance(topics, list) and topics:
                total_features += len([t for t in topics if t])
            
            severity = case.get('severity_indicators', [])
            if isinstance(severity, list) and severity:
                total_features += len([s for s in severity if s])
            
            agencies = case.get('agencies_involved', [])
            if isinstance(agencies, list) and agencies:
                total_features += len([a for a in agencies if a])
        
        # Calculate unique organizations (already normalized at ingestion time)
        def parse_field(field):
            """Parse JSON string fields or return list/array as-is"""
            if isinstance(field, str):
                try:
                    return json.loads(field)
                except:
                    return []
            return field if field else []
        
        unique_orgs = set()
        for case in cases:
            agencies = parse_field(case.get('agencies_involved', []))
            organizations = parse_field(case.get('organizations', []))
            # Organizations are already normalized at ingestion time, just count unique ones
            for org in agencies + organizations:
                if org and isinstance(org, str) and org.strip():
                    unique_orgs.add(org.strip())
            
            # Count single-value features (1 if exists)
            if case.get('investigation_type'):
                total_features += 1
            if case.get('relationship_to_victim'):
                total_features += 1
            if case.get('perpetrator_registered_sex_offender') is True:
                total_features += 1
            if case.get('perpetrator_age') is not None:
                total_features += 1
            if case.get('victim_count') and isinstance(case.get('victim_count'), (int, float)) and case.get('victim_count') > 0:
                total_features += 1
            
            # Count complex objects (1 if has any data)
            evidence = case.get('evidence_volume')
            if evidence and isinstance(evidence, dict):
                if evidence.get('images') or evidence.get('videos') or evidence.get('storage_size'):
                    total_features += 1
            
            prosecution = case.get('prosecution_outcome')
            if prosecution and isinstance(prosecution, dict):
                if prosecution.get('booking_status') or prosecution.get('charges') or prosecution.get('jail'):
                    total_features += 1
            
            victim_demo = case.get('victim_demographics')
            if victim_demo and isinstance(victim_demo, dict):
                if victim_demo.get('ages') or victim_demo.get('age_range') or victim_demo.get('gender'):
                    total_features += 1
        
        result = {
            "total_cases": len(cases),
            "total_victims": total_victims,
            "sources": list(sources),
            "source_count": len(sources),
            "unique_features": total_features,
            "unique_organizations": len(unique_orgs),
            "date_range": {
                "start": min((c.get('date_range', {}).get('start') for c in cases if c.get('date_range', {}).get('start')), default=None),
                "end": max((c.get('date_range', {}).get('end') for c in cases if c.get('date_range', {}).get('end')), default=None)
            }
        }
        
        # Store in Redis cache (1 hour TTL)
        set_cached(cache_key, result, ttl=3600)
        
        return result
    except Exception as e:
        # Fallback to direct computation
        try:
            cases = storage.get_all_cases()
            return {
                "total_cases": len(cases) if cases else 0,
                "total_victims": 0,
                "sources": [],
                "source_count": 0,
                "unique_features": 0,
                "unique_organizations": 0,
                "date_range": {"start": None, "end": None}
            }
        except:
            return {
                "total_cases": 0,
                "total_victims": 0,
                "sources": [],
                "source_count": 0,
                "unique_features": 0,
                "unique_organizations": 0,
                "date_range": {"start": None, "end": None}
            }


@app.post("/api/tag-threader")
@limiter.limit("60/minute")
def get_tag_threader(request: Request, selected_tags: List[Dict[str, str]]):
    """
    Query cases matching selected tags and create threaded tag links.
    
    Args:
        selected_tags: List of dictionaries with 'tag' and 'category' keys
            Example: [{"tag": "production", "category": "case_topics"}]
    
    Returns:
        Dictionary with intersection cases and tag results
    """
    cases = storage.get_all_cases()
    result = tag_threader(cases, selected_tags)
    return result


@app.post("/api/return-tagged-cases")
@limiter.limit("60/minute")
def get_tagged_cases(request: Request, selected_tags: List[Dict[str, str]]):
    """
    Return all cases matching the selected tags.
    
    Args:
        selected_tags: List of dictionaries with 'tag' and 'category' keys
            Example: [{"tag": "production", "category": "case_topics"}]
    
    Returns:
        List of case dictionaries matching ALL selected tags
    """
    cases = storage.get_all_cases()
    matching_cases = return_tagged_cases(cases, selected_tags)
    return {"cases": matching_cases}


@app.get("/api/case-ids-by-filter")
@limiter.limit("100/minute")
def get_case_ids_by_filter(
    request: Request,
    organization: str = None,
    relationship: str = None,
    prosecution_status: str = None,
    age_range: str = None,
    severity_indicator: str = None,
    platform: str = None,
    year: str = None,
    investigation_type: str = None
):
    """
    Get case IDs filtered by various criteria.
    Returns just the case IDs that match the filter.
    """
    try:
        cases = storage.get_all_cases(include_raw_data=False)
        
        import json
        def parse_field(field):
            if isinstance(field, str):
                try:
                    return json.loads(field)
                except:
                    return []
            return field if field else []
        
        filtered_cases = cases
        
        # Filter by organization (organizations already normalized at ingestion time)
        if organization:
            org_search = organization.strip()
            filtered_cases = [
                c for c in filtered_cases
                if org_search in [org.strip() for org in parse_field(c.get('agencies_involved', []))] or
                   org_search in [org.strip() for org in parse_field(c.get('organizations', []))]
            ]
        
        # Filter by relationship
        if relationship:
            filtered_cases = [
                c for c in filtered_cases
                if c.get('relationship_to_victim') == relationship
            ]
        
        # Filter by prosecution status
        if prosecution_status:
            def normalize_prosecution_status(prosecution):
                """
                Mirror the logic used in stats aggregation so bar counts and
                filtered case IDs stay in sync.
                """
                if not prosecution:
                    return None
                if isinstance(prosecution, dict):
                    # Same fallback chain as in stats: booking_status → status → 'prosecuted'
                    return (
                        prosecution.get('booking_status')
                        or prosecution.get('status')
                        or 'prosecuted'
                    )
                return str(prosecution)

            filtered_cases = [
                c for c in filtered_cases
                if normalize_prosecution_status(c.get('prosecution_outcome')) == prosecution_status
            ]
        
        # Filter by age range (e.g., "25-29")
        # Match bubble chart logic: only count ages between 18-99
        if age_range:
            try:
                age_min, age_max = map(int, age_range.split('-'))
                filtered_cases = [
                    c for c in filtered_cases
                    if c.get('perpetrator_age') and (
                        (isinstance(c.get('perpetrator_age'), list) and
                         any(age_min <= age <= age_max for age in c.get('perpetrator_age') 
                             if isinstance(age, (int, float)) and 18 <= age <= 99)) or
                        (isinstance(c.get('perpetrator_age'), (int, float)) and 
                         18 <= c.get('perpetrator_age') <= 99 and
                         age_min <= c.get('perpetrator_age') <= age_max)
                    )
                ]
            except:
                pass
        
        # Filter by severity indicator
        if severity_indicator:
            filtered_cases = [
                c for c in filtered_cases
                if severity_indicator in parse_field(c.get('severity_indicators', []))
            ]
        
        # Filter by platform
        if platform:
            filtered_cases = [
                c for c in filtered_cases
                if platform in parse_field(c.get('platforms_used', []))
            ]
        
        # Filter by year
        if year:
            filtered_cases = [
                c for c in filtered_cases
                if (c.get('date_start') and str(c.get('date_start'))[:4] == year) or
                   (isinstance(c.get('date_range'), dict) and 
                    c.get('date_range').get('start') and 
                    str(c.get('date_range').get('start'))[:4] == year)
            ]
        
        # Filter by investigation type
        if investigation_type:
            filtered_cases = [
                c for c in filtered_cases
                if c.get('investigation_type') == investigation_type
            ]
        
        case_ids = [c.get('id') for c in filtered_cases if c.get('id')]
        
        return {
            "case_ids": case_ids,
            "count": len(case_ids),
            "filter": {
                "organization": organization,
                "relationship": relationship,
                "prosecution_status": prosecution_status,
                "age_range": age_range,
                "severity_indicator": severity_indicator,
                "platform": platform,
                "year": year,
                "investigation_type": investigation_type
            }
        }
    except Exception as e:
        from error_handler import handle_error
        return handle_error(e)


@app.post("/api/cache/clear")
@limiter.limit("10/hour")  # Rate limit to prevent abuse
def clear_cache(request: Request):
    """
    Clear all cached data (useful when code changes but case count stays same).
    Requires authentication token or environment variable for security.
    """
    try:
        # Simple security: require CACHE_CLEAR_TOKEN env var or query param
        token = request.query_params.get('token') or os.getenv('CACHE_CLEAR_TOKEN')
        expected_token = os.getenv('CACHE_CLEAR_TOKEN', 'dev-cache-clear-token')
        
        if token != expected_token:
            return {"error": "Unauthorized. Provide ?token=YOUR_TOKEN or set CACHE_CLEAR_TOKEN env var"}
        
        if REDIS_AVAILABLE:
            cleared = clear_all_cache()
            return {
                "success": True,
                "message": f"Cleared {cleared} cache entries",
                "cache_type": "Redis"
            }
        else:
            return {
                "success": True,
                "message": "No Redis cache to clear (using direct database queries)",
                "cache_type": "None"
            }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/stats-detailed")
@limiter.limit("60/minute")
def get_detailed_stats(request: Request):
    """
    Get detailed statistics for visualization charts.
    Returns feature coverage, platform trends, organization involvement, etc.
    Uses Redis caching for fast responses.
    """
    try:
        # Get current case count for cache versioning
        current_case_count = get_case_count()
        
        # Build cache key
        cache_key = get_cache_key('stats-detailed', version=current_case_count)
        
        # Try Redis cache first
        cached_result = get_cached(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Cache miss - compute stats
        cases = storage.get_all_cases(include_raw_data=False)
        total_cases = len(cases)
        
        if total_cases == 0:
            empty_result = {
                "feature_coverage": {},
                "platform_trends": {},
                "top_organizations": [],
                "agency_frequency": {},
                "relationship_distribution": [],
                "prosecution_distribution": [],
                "perpetrator_age_data": [],
                "severity_indicators_top": [],
                "investigation_type_distribution": [],
                "total_cases": 0
            }
            set_cached(cache_key, empty_result, ttl=3600)
            return empty_result
        
        # 1. Feature Extraction Coverage
        feature_coverage = {}
        
        # Parse JSON fields safely
        import json
        def parse_field(field):
            if isinstance(field, str):
                try:
                    return json.loads(field)
                except:
                    return []
            return field if field else []
        
        # Calculate coverage for each feature type
        severity_count = sum(1 for c in cases if parse_field(c.get('severity_indicators', [])))
        prosecution_count = sum(1 for c in cases if c.get('prosecution_outcome'))
        relationship_count = sum(1 for c in cases if c.get('relationship_to_victim'))
        platforms_count = sum(1 for c in cases if parse_field(c.get('platforms_used', [])))
        investigation_count = sum(1 for c in cases if c.get('investigation_type'))
        victim_count = sum(1 for c in cases if c.get('victim_count') is not None)
        perp_age_count = sum(1 for c in cases if c.get('perpetrator_age') is not None)
        perp_registry_count = sum(1 for c in cases if c.get('perpetrator_registered_sex_offender') is True)
        evidence_count = sum(1 for c in cases if c.get('evidence_volume') and isinstance(c.get('evidence_volume'), dict) and any(c.get('evidence_volume', {}).values()))
        agencies_count = sum(1 for c in cases if parse_field(c.get('agencies_involved', [])))
        date_count = sum(1 for c in cases if c.get('date_start') or c.get('date_range'))
        # Severity phrases: dangerous, stated, told, continue, attacked, out_of_control
        severity_phrases_count = sum(1 for c in cases if parse_field(c.get('severity_phrases', [])))
        locations_count = sum(1 for c in cases if parse_field(c.get('locations', [])))
        
        feature_coverage = {
            "Severity Indicators": (severity_count / total_cases * 100) if total_cases > 0 else 0,
            "Severity Phrases": (severity_phrases_count / total_cases * 100) if total_cases > 0 else 0,
            "Prosecution": (prosecution_count / total_cases * 100) if total_cases > 0 else 0,
            "Relationship to Victim": (relationship_count / total_cases * 100) if total_cases > 0 else 0,
            "Platforms Used": (platforms_count / total_cases * 100) if total_cases > 0 else 0,
            "Investigation Type": (investigation_count / total_cases * 100) if total_cases > 0 else 0,
            "Victim Count": (victim_count / total_cases * 100) if total_cases > 0 else 0,
            "Perpetrator Age": (perp_age_count / total_cases * 100) if total_cases > 0 else 0,
            "Registry Status": (perp_registry_count / total_cases * 100) if total_cases > 0 else 0,
            "Evidence": (evidence_count / total_cases * 100) if total_cases > 0 else 0,
            "Agencies Involved": (agencies_count / total_cases * 100) if total_cases > 0 else 0,
            "Date Range": (date_count / total_cases * 100) if total_cases > 0 else 0,
            "Locations": (locations_count / total_cases * 100) if total_cases > 0 else 0
        }
        
        # 2. Platform Usage Over Time
        from collections import defaultdict, Counter
        import json
        platform_by_year = defaultdict(lambda: defaultdict(int))
        
        for case in cases:
            year = None
            date_start = case.get('date_start') or (case.get('date_range', {}) if isinstance(case.get('date_range'), dict) else {}).get('start')
            if date_start:
                try:
                    year = str(date_start)[:4]
                except:
                    pass
            
            if not year:
                # Try to extract from raw_data
                raw_data = case.get('raw_data', {})
                if isinstance(raw_data, dict):
                    month_year = raw_data.get('month_year', '')
                    if month_year:
                        # Handle formats like "September 2025" or just "2025"
                        if ' ' in month_year:
                            year_match = month_year.split()[-1]
                        elif month_year.isdigit() and len(month_year) == 4:
                            # month_year is just a year like "2022" or "2023"
                            year_match = month_year
                        else:
                            year_match = None
                        if year_match and year_match.isdigit():
                            year = year_match
            
            if year and year.isdigit() and 2010 <= int(year) <= 2025:
                platforms = parse_field(case.get('platforms_used', []))
                for platform in platforms:
                    platform_by_year[year][platform] += 1
        
        # Get top 7 platforms overall
        all_platforms = Counter()
        for year_data in platform_by_year.values():
            all_platforms.update(year_data)
        top_platforms = [p[0] for p in all_platforms.most_common(7)]
        
        platform_trends = {
            "years": sorted(platform_by_year.keys()),
            "platforms": top_platforms,
            "data": {}
        }
        
        for year in platform_trends["years"]:
            platform_trends["data"][year] = {platform: platform_by_year[year][platform] for platform in top_platforms}
        
        # 3. Top Organizations
        # Organizations are already normalized at ingestion time, just count them
        # Count each organization once per case (deduplicate within case)
        org_counter = Counter()
        for case in cases:
            agencies = parse_field(case.get('agencies_involved', []))
            organizations = parse_field(case.get('organizations', []))
            # Combine and deduplicate within this case
            case_orgs = set()
            for org in agencies + organizations:
                if org and isinstance(org, str) and org.strip():
                    case_orgs.add(org.strip())
            # Count each org once per case
            for org in case_orgs:
                org_counter[org] += 1
        
        top_organizations = [{"name": name, "count": count} for name, count in org_counter.most_common(15)]
        
        # 4. Agency Frequency Distribution
        # Count how many organizations appear in exactly N cases
        org_frequency = Counter(org_counter.values())
        agency_frequency = {
            "cases_per_org": sorted(org_frequency.keys()),
            "num_organizations": [org_frequency[k] for k in sorted(org_frequency.keys())]
        }
        
        # 5. Relationship to Victim Distribution
        relationship_counter = Counter()
        for case in cases:
            rel = case.get('relationship_to_victim')
            if rel:
                relationship_counter[rel] += 1
        relationship_distribution = [{"name": name, "count": count} for name, count in relationship_counter.most_common()]
        
        # 6. Prosecution Distribution
        prosecution_counter = Counter()
        for case in cases:
            prosecution = case.get('prosecution_outcome')
            if prosecution:
                if isinstance(prosecution, dict):
                    status = prosecution.get('booking_status') or prosecution.get('status') or 'prosecuted'
                else:
                    status = str(prosecution)
                prosecution_counter[status] += 1
        prosecution_distribution = [{"name": name, "count": count} for name, count in prosecution_counter.most_common()]
        
        # 7. Perpetrator Age Data (for bubble chart)
        # Count unique cases per age bin (not individual age occurrences)
        # This matches the filter behavior so bubble counts match filter results
        age_bins = defaultdict(set)  # Use set to track unique case IDs
        for case in cases:
            case_id = case.get('id')
            ages = case.get('perpetrator_age')
            if ages and case_id:
                case_ages = []
                if isinstance(ages, list):
                    case_ages = [int(a) for a in ages if isinstance(a, (int, float)) and 18 <= a <= 99]
                elif isinstance(ages, (int, float)) and 18 <= ages <= 99:
                    case_ages = [int(ages)]
                
                # Add case to each age bin it belongs to
                for age in case_ages:
                    bin_key = _perpetrator_age_bin_label(age)
                    age_bins[bin_key].add(case_id)
        
        # Convert sets to counts
        perpetrator_age_data = [
            {"age": age, "count": len(case_ids)} 
            for age, case_ids in sorted(age_bins.items(), key=lambda x: int(x[0].split('-')[0]))
        ]
        
        # 8. Severity Indicators (most common)
        severity_counter = Counter()
        for case in cases:
            severities = parse_field(case.get('severity_indicators', []))
            for sev in severities:
                severity_counter[sev] += 1
        severity_indicators_top = [{"name": name.replace('_', ' ').title(), "count": count} for name, count in severity_counter.most_common(10)]
        
        # 9. Investigation Type Distribution
        investigation_counter = Counter()
        for case in cases:
            inv_type = case.get('investigation_type')
            if inv_type:
                investigation_counter[inv_type] += 1
        investigation_type_distribution = [{"name": name.replace('_', ' ').title(), "count": count} for name, count in investigation_counter.most_common()]
        
        result = {
            "feature_coverage": feature_coverage,
            "platform_trends": platform_trends,
            "top_organizations": top_organizations,
            "agency_frequency": agency_frequency,
            "relationship_distribution": relationship_distribution,
            "prosecution_distribution": prosecution_distribution,
            "perpetrator_age_data": perpetrator_age_data,
            "severity_indicators_top": severity_indicators_top,
            "investigation_type_distribution": investigation_type_distribution,
            "total_cases": total_cases
        }
        
        # Store in Redis cache (1 hour TTL)
        set_cached(cache_key, result, ttl=3600)
        
        return result
    except Exception as e:
        from error_handler import handle_error
        return handle_error(e)

@app.get("/api/cluster-groups")
@limiter.limit("60/minute")
async def cluster_groups_endpoint(request: Request):
    """
    Lightweight endpoint for cluster / case-group visualizations.
    Returns slimmed case_groups (IDs only) - full case data fetched on click.
    Uses in-memory cache -> Redis -> DB to minimize latency.
    """
    global _cluster_groups_cache, _cluster_groups_cache_case_count
    try:
        current_case_count = get_case_count()
        
        # 1. In-memory cache (fastest - no network/DB)
        if (_cluster_groups_cache is not None and
                _cluster_groups_cache_case_count == current_case_count):
            _cluster_groups_cache['_cache_source'] = 'memory'
            return _cluster_groups_cache
        
        cache_key = get_cache_key('cluster-groups', version=current_case_count)
        
        # 2. Redis cache
        cached_result = get_cached(cache_key)
        if cached_result is not None:
            cached_result['_cache_source'] = 'redis'
            _cluster_groups_cache = cached_result
            _cluster_groups_cache_case_count = current_case_count
            return cached_result

        # 3. Slim table (small fetch, ~10KB vs ~1MB full blob)
        slim_groups = storage.get_cluster_groups_slim(current_case_count)
        if slim_groups and len(slim_groups) > 0:
            result = {
                "success": True,
                "case_groups": slim_groups,
                "cached": True,
                "source": "database"
            }
            set_cached(cache_key, result, ttl=86400)
            _cluster_groups_cache = result
            _cluster_groups_cache_case_count = current_case_count
            return result

        # 4. Full precomputed (fallback for old data before slim table)
        precomputed = storage.get_precomputed_clusters(current_case_count)
        if precomputed and isinstance(precomputed, dict) and precomputed.get('case_groups'):
            raw_groups = precomputed.get('case_groups', [])
            slim_groups = _slim_for_cluster_groups(raw_groups)
            result = {
                "success": True,
                "case_groups": slim_groups,
                "cached": True,
                "source": "database"
            }
            set_cached(cache_key, result, ttl=86400)
            storage.store_cluster_groups_slim(raw_groups, current_case_count)  # backfill slim table
            _cluster_groups_cache = result
            _cluster_groups_cache_case_count = current_case_count
            return result
        
        # 5. Fallback: compute on-demand, then store
        print("⚠️  No pre-computed cluster groups found, computing on-demand (this is slow once)...")
        cases = storage.get_all_cases(include_raw_data=True)
        analysis_results = run_automated_analysis(cases)
        storage.store_precomputed_clusters(analysis_results, current_case_count)
        
        raw_groups = analysis_results.get('case_groups', [])
        slim_groups = _slim_for_cluster_groups(raw_groups)
        result = {
            "success": True,
            "case_groups": slim_groups,
            "cached": False,
            "source": "computed"
        }
        set_cached(cache_key, result, ttl=86400)
        _cluster_groups_cache = result
        _cluster_groups_cache_case_count = current_case_count
        return result
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.get("/api/automated-analysis")
@limiter.limit("30/minute")
async def automated_analysis_endpoint(request: Request):
    """
    Full automated analysis (case groups, triaged cases, insights).
    Uses Redis caching + pre-computed clusters from database for fast response.
    Falls back to computing if pre-computed clusters not available.
    """
    try:
        current_case_count = get_case_count()
        cache_key = get_cache_key('automated-analysis', version=current_case_count)
        
        cached_result = get_cached(cache_key)
        if cached_result is not None:
            analysis = cached_result.get("analysis")
            if isinstance(analysis, dict):
                cached_result["analysis"] = _attach_case_text_to_automated_analysis(analysis)
            cached_result['_cache_source'] = 'redis'
            return cached_result
        
        precomputed = storage.get_precomputed_clusters(current_case_count)
        if precomputed:
            precomputed = _attach_case_text_to_automated_analysis(precomputed)
            result = {
                "success": True,
                "analysis": precomputed,
                "cached": True,
                "source": "database"
            }
            set_cached(cache_key, result, ttl=86400)
            return result
        
        print("⚠️  No pre-computed clusters found, computing on-demand (this is slow)...")
        cases = storage.get_all_cases(include_raw_data=True)
        analysis_results = run_automated_analysis(cases)
        analysis_results = _attach_case_text_to_automated_analysis(analysis_results)
        storage.store_precomputed_clusters(analysis_results, current_case_count)
        
        result = {
            "success": True,
            "analysis": analysis_results,
            "cached": False,
            "source": "computed"
        }
        set_cached(cache_key, result, ttl=86400)
        return result
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.get("/api")
def api_root():
    """API root endpoint"""
    return {"message": "CaseLinker API", "version": "1.0"}

@app.get("/visualization", response_class=HTMLResponse)
async def serve_visualization():
    """Serve the HTML visualization page"""
    html_path = Path(__file__).parent.parent / "visualization" / "index.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Visualization not found</h1>", status_code=404)

@app.get("/analysis", response_class=HTMLResponse)
async def serve_analysis():
    """Serve the HTML analysis page"""
    html_path = Path(__file__).parent.parent / "visualization" / "analysis.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Analysis page not found</h1>", status_code=404)

@app.get("/clusters", response_class=HTMLResponse)
async def serve_clusters():
    """Serve the HTML clusters page"""
    html_path = Path(__file__).parent.parent / "visualization" / "clusters.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Clusters page not found</h1>", status_code=404)

@app.get("/api/location-stats")
@limiter.limit("60/minute")
def get_location_stats(request: Request):
    """
    Get aggregated location statistics (no raw cases).
    Returns location data with counts and case IDs for US map visualization.
    This endpoint is optimized for performance - returns only aggregated data.
    """
    try:
        # Get current case count for cache versioning
        current_case_count = get_case_count()
        
        # Build cache key
        cache_key = get_cache_key('location-stats', version=current_case_count)
        
        # Try Redis cache first
        cached_result = get_cached(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Cache miss - aggregate location data
        cases = storage.get_all_cases(include_raw_data=False)
        
        # Aggregate locations
        location_map = {}
        for case in cases:
            locations = case.get('locations', [])
            if isinstance(locations, str):
                import json
                try:
                    locations = json.loads(locations)
                except:
                    locations = []
            
            if not isinstance(locations, list):
                locations = []
            
            case_id = case.get('id', 'unknown')
            
            for loc in locations:
                if loc and isinstance(loc, str) and loc.strip():
                    loc_clean = loc.strip()
                    if loc_clean not in location_map:
                        location_map[loc_clean] = {
                            'location': loc_clean,
                            'count': 0,
                            'caseIds': []
                        }
                    location_map[loc_clean]['count'] += 1
                    location_map[loc_clean]['caseIds'].append(case_id)
        
        # Convert to list
        location_data = list(location_map.values())
        
        # Store in cache (1 hour TTL)
        set_cached(cache_key, location_data, ttl=3600)
        
        return location_data
    except Exception as e:
        # Fallback to empty list on error
        return []


@app.get("/stats", response_class=HTMLResponse)
async def serve_stats():
    """Serve the HTML stats page"""
    html_path = Path(__file__).parent.parent / "visualization" / "stats.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Stats page not found</h1>", status_code=404)

@app.get("/search", response_class=HTMLResponse)
async def serve_search():
    """Serve the HTML search page"""
    html_path = Path(__file__).parent.parent / "visualization" / "search.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Search page not found</h1>", status_code=404)


@app.get("/query", response_class=HTMLResponse)
async def serve_query():
    """Custom analysis: browser-side JS snippets calling public APIs only."""
    html_path = Path(__file__).parent.parent / "visualization" / "query.html"
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Query page not found</h1>", status_code=404)


@app.get("/expand", response_class=HTMLResponse)
async def serve_expand():
    """Build-your-own visualization: examples using public CaseLinker APIs."""
    html_path = Path(__file__).parent.parent / "visualization" / "expand.html"
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Expand page not found</h1>", status_code=404)


@app.get("/triage", response_class=HTMLResponse)
async def serve_triage():
    """Serve the triage ML evaluation page"""
    html_path = Path(__file__).parent.parent / "visualization" / "triage.html"
    if html_path.exists():
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Triage page not found</h1>", status_code=404)


@app.get("/api/triage-eval")
def api_triage_eval(
    model: str = Query("rf", description="rf or tree"),
    criterion: str = Query("entropy", description="gini, entropy, or log_loss"),
    no_agencies: bool = Query(False),
    seed: int = Query(42),
    test_size: float = Query(0.2, ge=0.05, le=0.45),
):
    """
    Run the same 80/20-style eval as scripts/test_triage.py on the live DB,
    using train_triage_model.train_pipeline and rule-based triage labels.
    """
    try:
        import math

        import numpy as np
        from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
        from sklearn.model_selection import train_test_split
        from train_triage_model import (
            cases_to_dataframe,
            make_labels,
            priority_scores_by_id,
            train_pipeline,
        )
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Triage eval unavailable: {e}") from e

    if model not in ("rf", "tree"):
        raise HTTPException(status_code=400, detail="model must be rf or tree")
    if criterion not in ("gini", "entropy", "log_loss"):
        raise HTTPException(status_code=400, detail="criterion must be gini, entropy, or log_loss")

    cases = storage.get_all_cases(include_raw_data=False)
    min_cases = max(20, int(math.ceil(1.0 / test_size)) + 5)
    if len(cases) < min_cases:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {min_cases} cases for stratified split; found {len(cases)}",
        )

    use_agencies = not no_agencies
    id_to_score = priority_scores_by_id(cases)
    scores = np.array([id_to_score[c["id"]] for c in cases])
    y, class_names, bin_edges = make_labels(scores, n_bins=3)
    df = cases_to_dataframe(cases, include_agencies=use_agencies)
    X = df.drop(columns=["id"])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y
    )

    pipe = train_pipeline(
        X_train,
        y_train,
        model,
        seed,
        use_agencies=use_agencies,
        criterion=criterion,
    )
    y_pred = pipe.predict(X_test)

    acc = float(accuracy_score(y_test, y_pred))
    cm = confusion_matrix(y_test, y_pred, labels=list(range(len(class_names))))
    report_dict = classification_report(
        y_test, y_pred, target_names=class_names, zero_division=0, output_dict=True
    )

    case_ids_by_tier: Dict[str, List[str]] = {name: [] for name in class_names}
    for i, c in enumerate(cases):
        tier = class_names[int(y[i])]
        cid = c.get("id")
        if cid is not None:
            case_ids_by_tier[tier].append(str(cid))
    for tier in case_ids_by_tier:
        case_ids_by_tier[tier] = sorted(case_ids_by_tier[tier])

    out: Dict[str, Any] = {
        "n_cases": len(cases),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "accuracy": acc,
        "classification_report": report_dict,
        "confusion_matrix": cm.tolist(),
        "class_names": class_names,
        "bin_edges": bin_edges,
        "case_ids_by_tier": case_ids_by_tier,
        "model": model,
        "criterion": criterion,
        "use_agencies": use_agencies,
        "seed": seed,
        "test_size": test_size,
    }

    try:
        corp = _triage_saved_bundle_corpus_live({})
        if corp.get("corpus_predictions_available"):
            out["corpus_predictions_available"] = True
            out["model_case_ids_by_tier"] = corp["model_case_ids_by_tier"]
            out["corpus_class_names"] = corp["corpus_class_names"]
            out["corpus_predictions_meta"] = corp.get("corpus_predictions_meta") or {}
            out["corpus_predictions_stale"] = False
        else:
            out["corpus_predictions_available"] = False
    except Exception:
        out["corpus_predictions_available"] = False

    return out


@app.get("/api/triage-model-corpus")
@limiter.limit("60/minute")
def api_triage_model_corpus(
    request: Request,
    facet_constraints: Optional[str] = Query(
        None,
        description='JSON object: { field_key: [allowed values, ...], ... }; any tag may match.',
    ),
):
    """
    Model-predicted tiers from the saved bundle over the live database (and optional
    facet filter). Does not read triage_corpus_predictions.json.
    """
    constraints = _parse_facet_constraints_param(facet_constraints)
    return _triage_saved_bundle_corpus_live(constraints)


class LiveTriageRequest(BaseModel):
    raw: str = Field("", description="Pasted batch text (Case 1 : … Case 2 : …)")


@app.post("/api/triage-live")
def api_triage_live(body: LiveTriageRequest):
    """
    Process pasted narratives through the normal extraction pipeline (in memory only),
    classify tiers with the saved triage bundle. Does not persist case text or features.
    """
    if not (body.raw or "").strip():
        raise HTTPException(status_code=400, detail="raw text is required")

    try:
        from triage import run_live_triage
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Live triage unavailable: {e}") from e

    try:
        out = run_live_triage(body.raw)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("live triage failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("message", "empty_input"))

    return {
        "class_names": out["class_names"],
        "case_ids_by_tier": out["case_ids_by_tier"],
        "predictions": out["predictions"],
        "n_cases": out["n_cases"],
        "bundle_path": out.get("bundle_path"),
        "use_agencies": out.get("use_agencies"),
    }


@app.get("/sources", response_class=HTMLResponse)
async def serve_sources():
    """Serve the HTML sources page"""
    html_path = Path(__file__).parent.parent / "visualization" / "sources.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Sources page not found</h1>", status_code=404)

@app.get("/audit", response_class=HTMLResponse)
async def serve_audit():
    """Serve the HTML audit page"""
    html_path = Path(__file__).parent.parent / "visualization" / "audit.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Audit page not found</h1>", status_code=404)


@app.get("/under-the-hood", response_class=HTMLResponse)
async def serve_under_the_hood():
    """Serve the HTML under-the-hood architecture page"""
    html_path = Path(__file__).parent.parent / "visualization" / "under-the-hood.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Under the Hood</h1><p>Page not found</p>", status_code=404)

@app.get("/ml-experimental", response_class=HTMLResponse)
async def serve_ml_experimental():
    """Serve the HTML ML experimental page"""
    html_path = Path(__file__).parent.parent / "visualization" / "ml-experimental.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>ML Experimental page not found</h1>", status_code=404)


_viz_assets = Path(__file__).resolve().parent.parent / "visualization" / "assets"
if _viz_assets.is_dir():
    app.mount("/viz-assets", StaticFiles(directory=str(_viz_assets)), name="viz_assets")


if __name__ == "__main__":
    import uvicorn
    import sys
    import os
    from pathlib import Path
    
    # Add project root to path for config import
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    try:
        from config import API_HOST, API_PORT, API_RELOAD
    except ImportError:
        # Fallback to defaults if config not found
        API_HOST = "0.0.0.0"
        API_PORT = 8000
        API_RELOAD = False
    
    # Use environment variables for production hosting (Railway, Render, etc.)
    port = int(os.environ.get("PORT", API_PORT))
    host = os.environ.get("HOST", API_HOST)
    
    # Disable reload when running directly (causes warning)
    # Use: uvicorn run.main:app --reload (from project root) for reload
    uvicorn.run(app, host=host, port=port, reload=False)
