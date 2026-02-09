# Visualization Plan

## Recommended Approach: HTML + D3.js (Start Simple)

### Why HTML + D3.js First:
- ✅ No build step - just open HTML file
- ✅ D3.js is perfect for timelines, graphs, interactive charts
- ✅ Easy to iterate and test
- ✅ Can upgrade to React later if needed
- ✅ Works great for HCI/data viz projects

### Architecture:
```
Python Backend (FastAPI/Flask)
    ↓ (JSON API)
HTML + D3.js Frontend
    ├─ Timeline visualization
    ├─ Case detail views (expandable)
    ├─ Filtering controls
    ├─ Clustering visualization
    └─ Graph network view
```

## Components Needed:

### 1. Timeline View (Primary)
- Horizontal timeline with cases as points/bars
- Color-coded by month
- Click to expand case details
- Filter by date range

### 2. Case Detail Panel (Expandable)
- Shows when case is clicked
- All extracted features
- Raw case text (collapsible)
- Related cases

### 3. Filtering Sidebar
- Filter by month, year
- Filter by source
- Filter by platforms (when extracted)
- Filter by topics (when extracted)

### 4. Clustering View
- Visual grouping of similar cases
- Interactive clusters
- Show connections

### 5. Graph Network View
- D3.js force-directed graph
- Cases as nodes
- Similarity as edges (weighted)
- Interactive exploration

## Tech Stack:

**Backend:**
- FastAPI (lightweight, fast, auto-docs)
- Endpoints: `/api/cases`, `/api/cases/{id}`, `/api/clusters`, etc.

**Frontend:**
- HTML + CSS + JavaScript
- D3.js v7 (latest)
- No framework needed initially

**Optional (Later):**
- React + D3.js (if you want component-based)
- TypeScript (for type safety)

## File Structure:
```
CaseLinker/
├── src/                    # Python backend
├── visualization/
│   ├── index.html          # Main dashboard
│   ├── js/
│   │   ├── timeline.js     # Timeline component
│   │   ├── filters.js      # Filtering logic
│   │   ├── case-detail.js  # Case detail view
│   │   └── graph.js        # Network graph
│   ├── css/
│   │   └── styles.css      # Styling
│   └── data/               # Sample data (for testing)
└── api/                    # FastAPI backend
    └── main.py
```

## Next Steps:
1. Create simple HTML + D3.js timeline
2. Connect to Python backend (FastAPI)
3. Add case detail expansion
4. Add filtering
5. Add clustering view
6. Add graph network view
