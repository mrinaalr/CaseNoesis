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
from analysis import cluster_cases, find_similar_cases
from visualization import create_timeline_visualization, filter_cases

app = FastAPI(title="CaseLinker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage with encryption key from config
try:
    from config import DATABASE_PATH, DB_ENCRYPTION_KEY, ENABLE_ENCRYPTION
    # Only use encryption if enabled AND SQLCipher is available
    from storage import SQLCIPHER_AVAILABLE
    encryption_key = DB_ENCRYPTION_KEY if (ENABLE_ENCRYPTION and SQLCIPHER_AVAILABLE) else None
except ImportError:
    DATABASE_PATH = "caselinker.db"
    encryption_key = None
    try:
        from storage import SQLCIPHER_AVAILABLE
    except:
        SQLCIPHER_AVAILABLE = False

# Initialize storage - will create database if it doesn't exist
storage = CaseStorage(DATABASE_PATH, encryption_key=encryption_key)


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
    
    return {
        "total_cases": len(cases),
        "total_victims": total_victims,
        "sources": list(sources),
        "source_count": len(sources),
        "date_range": {
            "start": min((c.get('date_range', {}).get('start') for c in cases if c.get('date_range', {}).get('start')), default=None),
            "end": max((c.get('date_range', {}).get('end') for c in cases if c.get('date_range', {}).get('end')), default=None)
        }
    }


@app.get("/api/clusters")
def get_clusters(threshold: float = 0.5):
    """Get case clusters"""
    cases = storage.get_all_cases()
    clusters = cluster_cases(cases, threshold=threshold)
    return {"clusters": clusters, "count": len(clusters)}


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



if __name__ == "__main__":
    import uvicorn
    import sys
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
    
    # Disable reload when running directly (causes warning)
    # Use: uvicorn api.main:app --reload (from project root) for reload
    uvicorn.run(app, host=API_HOST, port=API_PORT, reload=False)
