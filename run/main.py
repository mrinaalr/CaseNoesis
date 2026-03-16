"""
FastAPI Backend for CaseLinker
Provides API endpoints for visualization frontend
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from typing import List, Dict, Any
import sys
import json
import os
import logging
import time
from pathlib import Path
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Storage Layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Clustering & Analysis Layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Visualization Layer"))

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
from analysis import tag_threader, return_tagged_cases, run_automated_analysis
from visualization import create_timeline_visualization, filter_cases

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

# Fast case-count helper that uses the already-initialized storage
def get_case_count() -> int:
    """
    Lightweight helper for counting cases.
    Uses the shared storage instance so we don't re-open connections.
    """
    try:
        return storage.get_case_count()
    except Exception:
        return 0

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
        import threading
        def precompute_clusters_background():
            try:
                print("Pre-computing clusters in background...")
                cases = storage.get_all_cases(include_raw_data=False)
                if cases:
                    from analysis import run_automated_analysis
                    cluster_data = run_automated_analysis(cases)
                    storage.store_precomputed_clusters(cluster_data, len(cases))
                    print(f"✅ Pre-computed clusters stored ({len(cases)} cases)")
            except Exception as e:
                print(f"⚠️  Error pre-computing clusters: {e}")
        
        # Start background thread (non-blocking)
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

# Cache for unique tags (invalidates when cases change)
_tags_cache = None
_tags_cache_case_count = 0

@app.get("/api/tags")
@limiter.limit("60/minute")
def get_unique_tags(request: Request):
    """
    Get unique tags/topics from all cases for populating selectors.
    Much faster than loading all cases - returns only unique values.
    """
    global _tags_cache, _tags_cache_case_count
    
    try:
        # Quick check: get case count first (fast query)
        current_case_count = get_case_count()
        
        # Return cached tags if case count hasn't changed
        if _tags_cache is not None and _tags_cache_case_count == current_case_count:
            return {
                "case_topics": _tags_cache["case_topics"],
                "severity_indicators": _tags_cache["severity_indicators"],
                "platforms_used": _tags_cache["platforms_used"],
                "investigation_types": _tags_cache["investigation_types"],
                "relationships": _tags_cache["relationships"],
                "status": _tags_cache["status"],
                "cached": True
            }
        
        # Load cases (without raw_data for speed)
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
        
        # Cache the results
        _tags_cache = {
            "case_topics": sorted(list(case_topics)),
            "severity_indicators": sorted(list(severity_indicators)),
            "platforms_used": sorted(list(platforms_used)),
            "investigation_types": sorted(list(investigation_types)),
            "relationships": sorted(list(relationships)),
            "status": sorted(list(status))
        }
        _tags_cache_case_count = current_case_count
        
        return {
            "case_topics": _tags_cache["case_topics"],
            "severity_indicators": _tags_cache["severity_indicators"],
            "platforms_used": _tags_cache["platforms_used"],
            "investigation_types": _tags_cache["investigation_types"],
            "relationships": _tags_cache["relationships"],
            "status": _tags_cache["status"],
            "cached": False
        }
    except Exception as e:
        from error_handler import handle_error
        return handle_error(e)


@app.get("/api/cases/{case_id}")
@limiter.limit("100/minute")
def get_case(request: Request, case_id: str):
    """Get a specific case by ID"""
    case = storage.get_case(case_id)
    if not case:
        return {"error": "Case not found"}, 404
    return case


@app.get("/api/timeline")
@limiter.limit("60/minute")
def get_timeline(request: Request):
    """Get timeline visualization data"""
    cases = storage.get_all_cases()
    timeline_data = create_timeline_visualization(cases)
    return timeline_data


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
        
        # Cache miss - compute stats
        try:
            cases = storage.get_all_cases()
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
            filtered_cases = [
                c for c in filtered_cases
                if c.get('prosecution_outcome') and (
                    (isinstance(c.get('prosecution_outcome'), dict) and 
                     (c.get('prosecution_outcome').get('booking_status') == prosecution_status or
                      c.get('prosecution_outcome').get('status') == prosecution_status)) or
                    str(c.get('prosecution_outcome')) == prosecution_status
                )
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
                        year_match = month_year.split()[-1] if ' ' in month_year else None
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
                    bin_key = f"{age // 5 * 5}-{age // 5 * 5 + 4}"
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
    
    Returns ONLY the pre-computed case_groups (no full triage/insights blob),
    so payloads are smaller and faster for the clusters page.
    """
    try:
        current_case_count = get_case_count()
        cache_key = get_cache_key('cluster-groups', version=current_case_count)
        
        # Try Redis cache first
        cached_result = get_cached(cache_key)
        if cached_result is not None:
            cached_result['_cache_source'] = 'redis'
            return cached_result
        
        # Try pre-computed clusters from database
        precomputed = storage.get_precomputed_clusters(current_case_count)
        if precomputed and isinstance(precomputed, dict) and precomputed.get('case_groups'):
            result = {
                "success": True,
                "case_groups": precomputed.get('case_groups', []),
                "cached": True,
                "source": "database"
            }
            set_cached(cache_key, result, ttl=86400)
            return result
        
        # Fallback: compute once on-demand, then store
        print("⚠️  No pre-computed cluster groups found, computing on-demand (this is slow once)...")
        cases = storage.get_all_cases(include_raw_data=False)
        analysis_results = run_automated_analysis(cases)
        storage.store_precomputed_clusters(analysis_results, current_case_count)
        
        result = {
            "success": True,
            "case_groups": analysis_results.get('case_groups', []),
            "cached": False,
            "source": "computed"
        }
        set_cached(cache_key, result, ttl=86400)
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
            cached_result['_cache_source'] = 'redis'
            return cached_result
        
        precomputed = storage.get_precomputed_clusters(current_case_count)
        if precomputed:
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
