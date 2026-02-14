"""
FastAPI Backend for CaseLinker
Provides API endpoints for visualization frontend
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from typing import List, Dict, Any
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Storage Layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Clustering & Analysis Layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "Visualization Layer"))

from storage import CaseStorage
from analysis import tag_threader, return_tagged_cases, run_automated_analysis
from visualization import create_timeline_visualization, filter_cases

app = FastAPI(title="CaseLinker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage
try:
    from config import DATABASE_PATH
except ImportError:
    DATABASE_PATH = "caselinker.db"

# Fix path for Railway - Procfile runs from 'run/' directory, so go up one level
# Check if we're in the 'run' directory and adjust path accordingly
if Path(__file__).parent.name == 'run':
    # We're in the run directory, database is one level up
    db_path = Path(__file__).parent.parent / DATABASE_PATH
else:
    # We're in the root directory
    db_path = Path(DATABASE_PATH)

# Initialize storage - will create database if it doesn't exist
storage = CaseStorage(str(db_path))

# Log database status on startup
try:
    test_cases = storage.get_all_cases()
    print(f"📊 Database: {db_path}")
    print(f"📁 Cases in database: {len(test_cases)}")
    if len(test_cases) == 0:
        print(f"⚠️  Warning: Database exists but contains 0 cases. Check if database file is in the correct location.")
except Exception as e:
    print(f"⚠️  Database initialization warning: {e}")
    print(f"   Looking for database at: {db_path}")
    print(f"   Database exists: {db_path.exists()}")


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
def get_all_cases():
    """Get all cases from database"""
    try:
        cases = storage.get_all_cases()
        return cases if cases else []
    except Exception as e:
        # Handle case where database doesn't exist or is empty
        return []


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    """Get a specific case by ID"""
    case = storage.get_case(case_id)
    if not case:
        return {"error": "Case not found"}, 404
    return case


@app.get("/api/timeline")
def get_timeline():
    """Get timeline visualization data"""
    cases = storage.get_all_cases()
    timeline_data = create_timeline_visualization(cases)
    return timeline_data


@app.get("/api/stats")
def get_stats():
    """Get statistics about cases"""
    try:
        cases = storage.get_all_cases()
    except Exception:
        cases = []
    
    if not cases:
        return {
            "total_cases": 0,
            "total_victims": 0,
            "sources": [],
            "source_count": 0,
            "unique_features": 0,
            "date_range": {"start": None, "end": None}
        }
    
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
    
    return {
        "total_cases": len(cases),
        "total_victims": total_victims,
        "sources": list(sources),
        "source_count": len(sources),
        "unique_features": total_features,
        "date_range": {
            "start": min((c.get('date_range', {}).get('start') for c in cases if c.get('date_range', {}).get('start')), default=None),
            "end": max((c.get('date_range', {}).get('end') for c in cases if c.get('date_range', {}).get('end')), default=None)
        }
    }


@app.post("/api/tag-threader")
def get_tag_threader(selected_tags: List[Dict[str, str]]):
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
def get_tagged_cases(selected_tags: List[Dict[str, str]]):
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


@app.get("/api/automated-analysis")
async def automated_analysis_endpoint():
    """
    Run automated analysis on all cases.
    Returns case groups, triaged cases, and insights.
    """
    try:
        cases = storage.get_all_cases()
        
        # Run automated analysis
        analysis_results = run_automated_analysis(cases)
        
        return {
            "success": True,
            "analysis": analysis_results
        }
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
    if True:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        return HTMLResponse(content="<h1>Under the Hood</h1><p>Page not found</p>", status_code=404)



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
