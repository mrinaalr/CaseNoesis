# CaseLinker

**CaseLinker** is a project designed to group and visualize **statistical** and **contextual** information from cases involving crimes against children and child sexual exploitation & abuse (CSEA).

## Live Demo

**Try the latest version online:** [https://caselinker.up.railway.app/](https://caselinker.up.railway.app/)

The live release includes all features and a processed case corpus from publicly available ICAC / NCMEC / DOJ / State Attorneys General press materials. The corpus holds **5,086 cases** across **50** ingestion sources. Live counts and per-source coverage are on the in-app **Sources** page. These reports summarize investigations, arrests, and prosecutions, redacted for public release. No PII was processed; all data was already in the public domain. No installation required — just open the link in your browser.

## Technical Reports

- **Report #1: [CaseLinker: An Open-Source System for Cross-Case Analysis of Internet Crimes Against Children Reports](https://mrinaalr.github.io/website/CaseLinker.pdf)** - Initial technical report documenting the prototype architecture, deterministic extraction pipeline, and evaluation baseline on 47 cases.

- **Report #2: [Interpretable ML Approaches for Analyzing Internet Crimes Against Children Reports](https://mrinaalr.github.io/website/CaseLinker-%20Interpretable%20ML%20Approaches%20for%20Analyzing%20Internet%20Crimes%20Against%20Children%20Reports.pdf)** - Second report covering NER integration, dataset expansion to 207 cases, and emerging patterns from the expanded dataset including the distributed network of 215 law enforcement organizations.

- **Report #3: [5 Sources, 500 Cases, and Scaling Considerations](https://mrinaalr.github.io/website/Scaling.pdf)** - Third report covering the addition of 3 new sources, facet-tree search, and data utility.

## Motivation

This project was motivated by challenges I encountered with understanding child exploitation cases, including:

- **Fragmented data sources**: Cases are scattered across numerous organizations, states, and agencies
- **Cross-case analysis**: Identifying patterns, similarities, and connections between cases becomes challenging without a unified system, even when cases share common characteristics such as abuse patterns, platforms, or perpetrator demographics
- **Limitations in trend analysis**: Analyzing the evolution of child exploitation, the mediums in which it occurs, and recurring case topics
- **Emotional impact**: The challenge of repeatedly reading and processing highly disturbing case material

CaseLinker aims to address these challenges by serving as a tool for case analysis, enabling researchers, law enforcement, and advocacy organizations to better understand the landscape of child exploitation.

## Emphasis

- **Feature extraction**: Robust extraction of information from cases and explainability for clusters and analysis
- **Clustering and linking**: Cases based on shared characteristics such as victim context, platforms used, and law enforcement actions
- **Visualization**: With particular attention to tasteful presentation of case content, and pattern analysis across investigations

## System Architecture

CaseLinker follows a modular, layered architecture:

1. **Ingestion Layer**: Handles PDF data sources with text extraction and validation
2. **Processing Layer**: Extracts features, assigns comparison values, and fills case schema
3. **Storage Layer**: PostgreSQL (production) / SQLite (local development) - Database-agnostic implementation
4. **Clustering & Analysis Layer**: Case comparison, similarity detection, automated grouping, triage, and insights generation
5. **Visualization Layer**: Interactive web-based dashboards with D3.js visualizations (main charts, Search tree, analysis views)

## Installation

### Option 1: Use Live Demo (Recommended for Quick Testing)

**No installation required.** Visit the live deployment:
- **Live Application**: [https://caselinker.up.railway.app](https://caselinker.up.railway.app)

The live version includes all features and a processed case corpus. Created for quick testing and demonstrations.

### Option 2: Local Setup (Works Out of the Box)

```bash
# Clone the repository
git clone https://github.com/mrinaalr/CaseLinker.git
cd CaseLinker

# Run setup script (creates venv and installs dependencies)
./setup.sh

# Activate virtual environment
source venv/bin/activate

# Start the main application
python3 run/main.py
```

Then open your browser to:
- **Home**: http://localhost:8000/
- **Visualizations**: http://localhost:8000/visualization
- **Advanced Analysis**: http://localhost:8000/analysis
- **Clusters**: http://localhost:8000/clusters
- **Stats**: http://localhost:8000/stats
- **Search**: http://localhost:8000/search
- **Query**: http://localhost:8000/query 
- **Expand**: http://localhost:8000/expand 
- **Look Under the Hood**: http://localhost:8000/under-the-hood
- **Data Sources**: http://localhost:8000/sources
- **Triage**: http://localhost:8000/triage
- **Tech Landscape**: http://localhost:8000/tech-landscape
- **LLM (Query assistant)**: http://localhost:8000/llm
- **Case Studies**: http://localhost:8000/case-studies
- **Data Audit**: http://localhost:8000/audit
- **API Documentation**: http://localhost:8000/docs


**Database:** 
- **Production (Railway)**: PostgreSQL database with encrypted connections and managed backups
- **Local Development**: SQLite database (`caselinker.db`) - created automatically when running locally, initially empty


You can process additional PDFs to add more cases to the database.


## Usage

### ⚠️ Important: Data Content and Warning

**CaseLinker processes publicly available case reports and related records for research, analytical, and investigative workflow purposes.**

**While all source materials are drawn from public reports, content involves descriptions of child exploitation, abuse, or other disturbing criminal case details that may be difficult to read.**

**Please proceed with awareness of the sensitive nature of the material and use the project responsibly for research, academic, or authorized analytical purposes.**


## Two Main Entry Points

1. **`src/main.py`** - **CLI Tool for Processing PDFs**
   - Processes PDF files to extract and store cases in the database
   - Run this when you want to add new cases from PDF files
   - Extracts text, identifies sources, splits cases, extracts features, and stores them
   - Pre-computes clusters after storing new cases

2. **`run/main.py`** - **Main application**
   - Starts the web server that serves the visualization interface and API
   - Run this to access the web interface and visualizations
   - Uses pre-computes clusters on startup for fast performance
   - Provides REST API endpoints for case data, analysis, and statistics

**Typical use case:**
1. First, process PDFs with `src/main.py` to populate the database
2. Then, start the web server with `run/main.py` to view and analyze the cases

## Process Your Own PDF Files

**The local database starts empty.** To populate it with cases, you need to process PDF files you want to ingest.

### Finding PDF Sources

Visit the **Sources** page to see links for collecting sources:
- **Live Demo Sources Page**: [https://caselinker.up.railway.app/sources](https://caselinker.up.railway.app/sources)
- Or visit `/sources` when running locally: http://localhost:8000/sources

Processed sources include:
- **Arizona ICAC (AZICAC)**: Annual case reports and arrests (AZICAC)
- **National Center for Missing & Exploited Children (NCMEC)**: Case 
summaries and CyberTipline-related publications
- **Georgia Bureau of Investigation (GBI)**: CEACC / Georgia ICAC press releases
- **Idaho Office of Attorney General (Idaho ICAC)**: ICAC newsroom press releases
- **Texas Office of the Attorney General (Texas AG)**: Cyber Crimes / ICAC-related press releases
- **Michigan State Police (Michigan ICAC)**: MSP newsroom ICAC releases
- **Silicon Valley ICAC (SVICAC)**: Regional "In The News" articles
- **Tennessee Bureau of Investigation (TBI ICAC)**: TBI newsroom ICAC search results
- **South Carolina Attorney General (SCAG ICAC)**: ICAC-tagged news releases
- **New York State Police (NEWYORK SP)**: NYSP newsroom ICAC keyword search
- **Illinois Attorney General (ILLINOIS AG)**: ICAC press release search
- **Pennsylvania Office of the Attorney General (PA AG)**: Child Predator / ICAC-related releases
- **New Jersey Office of the Attorney General (NJ AG)**: ICAC site search
- **Washoe County Sheriff's Office (WCSO)**: Nevada ICAC newsroom search
- **Fresno County Sheriff's Office (FRESNO SO)**: ICAC site search
- **Osceola County Sheriff's Office (OSCEOLA SO)**: ICAC site search
- **Las Vegas Metropolitan Police Department (LVMPD)**: ICAC site search
- **San Jose Police Department (SJPD)**: ICAC / child exploitation press search
- **Los Angeles Police Department (LAPD)**: ICAC news search
- **Seattle Police Department (SPD)**: SPD Blotter ICAC search
- **San Diego Police Department (SDPD)**: City of San Diego ICAC site search
- **Colorado Springs Police Department (CSPD)**: ICAC site search
- **Hawaii Department of the Attorney General (HI AG)**: HICAC media and press
- **Cook County State's Attorney (CCSAO)**: ICAC unit news releases
- **South Florida ICAC (SOUTH FLORIDA ICAC)**: Regional task force news index
- **Florida Office of the Attorney General (FL AG)**: ICAC site search
- **Vermont Office of the Attorney General (VT AG)**: Child-related / ICAC releases
- **Rhode Island Office of the Attorney General (RI AG)**: ICAC site search
- **Ohio Attorney General (OHIO AG)**: ICAC / child-related news search
- **Delaware Department of Justice (DE AG)**: Child Predator Task Force / ICAC releases
- **Sedgwick County Sheriff's Office (SEDGWICK SO)**: Child exploitation press search
- **Anchorage Police Department (ANCHORAGE PD)**: Alaska ICAC-related releases
- **Mississippi Attorney General (MS AG)**: ICAC media releases
- **Montana Department of Justice (MT DOJ)**: Child-related press releases
- **New Mexico Attorney General's Office (NM AG)**: ICAC site search
- **North Carolina State Bureau of Investigation (NC SBI)**: ICAC news search
- **Louisiana Office of the Attorney General (LA AG)**: ICAC news releases
- **Utah Attorney General (UT AG)**: ICAC site search
- **Washington State Office of the Attorney General (WA AG)**: Child-related news search
- **Oregon Department of Justice (OREGON DOJ)**: ICAC site search
- **Wyoming Division of Criminal Investigation (WY DCI)**: ICAC / Computer Crime news
- **Iowa Division of Criminal Investigation (IA DCI)**: ICAC site search
- **Arkansas Department of Public Safety (ARKANSAS DPS)**: ICAC / ASP news search
- **Alabama Law Enforcement Agency (ALEA)**: SBI / ICAC news search
- **South Dakota Office of the Attorney General (SD AG)**: ICAC press releases
- **Kentucky State Police (KY SP)**: News archive ICAC search
- **Nebraska State Patrol (NE SP)**: Child exploitation press search
- **U.S. Army Criminal Investigation Division (ARMY CID)**: ICAC releases (USA.gov search)
- **U.S. DOJ CEOS (DOJ CEOS)**: Child Exploitation and Obscenity Section press releases
- **U.S. DOJ CEOS Archives (DOJ ARCHIVES)**: Archived CEOS criminal press releases (2002-2008)

### Processing PDFs to Populate Database

Once you have PDF files, process them using the CLI tool:

**Single PDF:**
```bash
source venv/bin/activate
python3 src/main.py "path/to/your/file.pdf"
```

**Multiple PDFs:**
```bash
python3 src/main.py "2011 Cases and Arrests – AZICAC.ORG.pdf" "2020 Reports" "2024-media-coverage-cybertipline-success-stories.pdf" 
```

**All PDFs under the repo** (e.g. after a fresh DB wipe):
```bash
./scripts/run/ingest_all_pdfs.sh

# Skip NCMEC/DOJ on first pass if you want state feeds first:

./scripts/run/ingest_all_pdfs.sh --no-aggregate
```

The system will:
1. Extract text from each PDF
2. Identify organization name from filename (AZICAC, NCMEC, etc.)
3. Batch cases, extract features, assign case IDs
4. Store all cases in the local SQLite database
5. Pre-compute clusters for fast visualization

## Using the Visualizations

Access the visualizations via the [live demo](https://caselinker.up.railway.app/visualization) or locally at http://localhost:8000/visualization.

1. **Case Group**: Displays cases matching specific groups (infant, very young, abuse, possession, online) 
2. **Severity Indicators**: Bar chart with color gradient showing severity levels (infant, very young, production, etc.). Click bars to view cases with highlighted severity text.
3. **Case Visualization**: Enter a Case ID (with autocomplete suggestions) to view comprehensive case details. The visualization displays structured information cards for platforms, severity indicators, case topics, investigation details, demographics, evidence volume, and prosecution outcomes with key information highlighted.
4. **Previous Perpetrator**: Pie chart showing registered sex offenders vs. non-registered. Click slices to view cases with highlighted perpetrator status.
5. **Environment**: Bar chart showing distribution of platforms and environments used (Facebook, online, chat, etc.). Click bars to view cases with highlighted platform text.
6. **Organizations Involved**: Horizontal bar chart showing law enforcement agencies involved (AZICAC, FBI, Phoenix Police, etc.). Click bars to view cases with highlighted agency names.

## Using Search

Access Search via the [live demo](https://caselinker.up.railway.app/search) or locally at http://localhost:8000/search

Search provides a **facet decision tree** over the stored case corpus: the server builds a deterministic partition tree from structured facets (not a precomputed file on disk). The view uses **D3.js** (SVG) to render cohort nodes and edges. You can limit tree depth, **prune** which partition dimensions apply and optionally filter allowed values per facet (extracted feature), then **click any node** (branch or leaf) to list **case IDs** in that cohort for use elsewhere (e.g. single-case visualization, manual cross-case analysis). Small cohorts (fewer than three cases) gate ID listing behind a demo access key. See `src/Storage Layer/facet_tree.py` and `/api/facet-tree` for the partition order and semantics.

## Triage and Experimental ML

Access Triage via the [live demo](https://caselinker.up.railway.app/triage) or locally at http://localhost:8000/triage. Current implementation uses **rule-based** priority tiers, **ML Classification for triage** (random forest or decision tree trained on features from the database with labels derived from deterministic rules), optionally constrained by the same facet-dimension filtering used in Search, and supports **paste-in live triage** that scores text in memory only and **does not write** to the database. For the full triage documentation (rules, bundle paths, APIs, live paste), see **`triage.md`** in the repo root.

**Experimental ML** ([live](https://caselinker.up.railway.app/ml-experimental), or http://localhost:8000/ml-experimental) is the in-app **documentation tab** for ML scope: what is production-adjacent (NER merge, triage model), what stays optional, and documents how ML functionality is evaluated and implemented. 

**Using Random Forest Model:** Place `triage_bundle.joblib` under `models/` at the repo root, or set `CASELINKER_TRIAGE_BUNDLE` to a file path, or `CASELINKER_MODELS_DIR` so the app looks for `triage_bundle.joblib` inside that directory. Train / create locally with:

```bash
python3 scripts/run/train_triage_model.py --model rf --out models/triage_bundle.joblib
```

Evaluate or reproduce metrics with `scripts/verify/test_triage.py` or `GET /api/triage-eval` (live DB, stratified train/test, same feature pipeline as training).


## Using Advanced Case Analysis

Navigate to [live demo](https://caselinker.up.railway.app/analysis) or run server locally and navigate to http://localhost:8000/analysis.


1. **Tag-Based Analysis (Run Advanced Analysis)**:
   - Select one or more tags from categories: Case Topics, Severity Indicators, Platforms & Environments, Investigation Types, Perpetrator Relationships, Perpetrator Status
   - Click "Run Advanced Analysis" to find all cases matching ALL selected tags (intersection logic)
   - View matching cases with highlighted text showing where tags were found in the raw case data
   - See case counts for each selected tag

2. **Automated Analysis (Run Automated Analysis)**:
   - Click "Run Automated Analysis" to run the full automated analysis pipeline
   - **Case Groups**: View cases grouped by similarity (platforms, demographics, topics, severity, investigation)
   - **Top Priority Cases**: See cases sorted by priority score (normalized to 5-10 scale) based on:
     - Severity indicators (35%): infant, rape, very_young, physical_abuse
     - Victim count (30%): Higher scores for multiple victims
      - Case type (25%): production, hands_on, possession, online_only
     - Severity phrases (15%): dangerous, stated, told, continue, attacked, out_of_control, attracted
     - Evidence volume (10%): images, videos, storage size
     - Registered sex offender (10%): Repeat offender status
   - **Automated Insights**: View insights about most common platforms, severity distribution, and case topics
   - **Patterns Detected**: See patterns like repeat offenders, relationship patterns, and investigation focus
   - **Top Keywords**: View most frequent keywords extracted from case text
   - **Expandable Details**: Click any box to view raw case data with highlighted priority indicators and detailed explanations of why the analysis prioritized/grouped the case

### Other Features

- **Sources Tab**: View data sources and access original case reports
- **Clusters Tab**: View pre-computed clusters and analyze case reports
- **Stats Tab**: Coverage over the dataset and case distributions
- **Tech Landscape**: Technology revolver (platforms, investigation tech, anonymization, P2P) by era
- **Query / Expand**: Custom analysis lab and build-your-own viz examples (public APIs)
- **LLM**: Natural-language queries over case statistics (SQL-backed; rate limited on production)
- **Case Studies Tab**: Era-organized narrative case studies (`data/case_studies.json`; optional `data/case_study_notes.json`)
- **Audit Tab**: Review extracted features case-by-case with interactive highlighting to verify extraction accuracy

## Project Structure

```
CaseLinker/
├── src/
│   ├── Ingestion Layer/              # PDF extraction, source detection, ingest_file
│   ├── Processing Layer/             # batching.py, processing.py, merge_processing.py
│   │   ├── Pattern Processing Layer/ # Regex / rule-based feature extraction
│   │   └── ML Processing Layer/      # NER, semantic concepts, content sanitization
│   ├── Storage Layer/                # SQLite + PostgreSQL storage, facet_tree.py
│   ├── Clustering & Analysis Layer/  # analysis.py, triage.py
│   ├── Visualization Layer/          # Server-side viz helpers
│   └── main.py                       # CLI: ingest PDFs → process → store
├── run/
│   ├── main.py                       # FastAPI app: pages + REST API
│   ├── redis_cache.py                # Optional Redis caching (production)
│   └── auth.py                       # Access gates / keys for sensitive views
├── scripts/
│   ├── stats/                        # Corpus statistics scripts
│   ├── verify/                       # Claims, uniqueness, ICAC TF alignment, triage tests
│   ├── run/                          # ingest_all_pdfs.sh, clear_postgres.py, train_triage_model.py
│   └── scraper/                      # fetch_source_urls.py, scrape_pdf.py
├── visualization/                    # Static HTML (served by run/main.py)
│   ├── assets/                       # caselinker-api.js, cover.png
│   ├── home.html                     # /
│   ├── index.html                    # /visualization
│   ├── search.html                   # /search (facet tree)
│   ├── analysis.html                 # /analysis
│   ├── clusters.html                 # /clusters
│   ├── stats.html                    # /stats
│   ├── query.html                    # /query
│   ├── expand.html                   # /expand
│   ├── triage.html                   # /triage
│   ├── ml-experimental.html          # /ml-experimental
│   ├── tech-landscape.html           # /tech-landscape
│   ├── LLM.html                      # /llm
│   ├── sources.html                  # /sources
│   ├── case-studies.html             # /case-studies
│   ├── audit.html                    # /audit
│   └── under-the-hood.html           # /under-the-hood
├── models/                           # triage_bundle.joblib (optional; see /triage)
├── data/                             # case_studies.json for /case-studies
├── setup.sh
├── requirements.txt                  # Core deps
├── requirements-ml.txt               # Optional ML / NER stack
├── config.py
├── caselinker.db                     # SQLite (local; created on first ingest)
├── triage.md                         # Triage rules and model docs
├── Procfile                          # Railway / Heroku start command
└── Architecture design.md
```

## Case Schema & Feature Extraction

Each case includes structured features extracted from case narratives:

### **Extracted Features (Regex-based)**
- **Perpetrator Demographics**: Age, registration status (registered sex offender)
- **Victim Demographics**: Age(s), count (when explicit), gender
- **Relationship**: Relationship to victim (father, mother, brother, stranger, etc.)
- **Platforms**: Social / messaging apps (e.g. Facebook Messenger, Instagram, Kik, Discord, TikTok, Twitter/X, Telegram, Skype, Omegle, MeWe), gaming surfaces (Roblox, Minecraft, Xbox Live, PSN, Fortnite), file hosting (Dropbox, Google Drive, Mega.nz, MediaFire, OneDrive), early-era chat (AIM, IRC, Yahoo Chat, MySpace, Craigslist), livestreaming (YouTube / YouTube Live, Twitch, generic webcam-platform phrasing), plus generic `online` / `chat` / `social media` when no named product matches.
- **Technology signals**: `investigation_technology` (e.g. PhotoDNA, CSAI Match, hash-matching language, CyberTipline variants), `anonymization_network` (Tor, I2P, dark web phrasing, cryptocurrency), and `p2p_clients` (LimeWire, BitTorrent, Kazaa, Gigatribe).
- **Charges**: Detailed prosecution charges with counts
- **Evidence Volume**: Images, videos, storage size (TB/GB), messages
- **Investigation Type**: Proactive, reactive, online, or undercover investigations
- **Agencies**: Law enforcement agencies involved (AZICAC, FBI, Phoenix Police, etc.)

### **Semantic Features (Pattern-based)**
- **Case Topics**: Themes such as production vs. possession, international cooperation, multi-state cases, hands-on vs. online-only, family vs. stranger, CSAM (`csam`)
- **Severity Indicators**: Age-based severity (infant, rape, very_young, under_10) and production indicators
- **Severity Phrases**: Non-traditional indicators extracted from case text (dangerous, stated, told, continue, attacked, out_of_control, attracted) - used for priority scoring

### **Preserved Data**
- **Raw Case Text**: Original case narrative preserved for reference
- **Metadata**: Source, date range, creation timestamps

## API Endpoints

- `GET /` - Home page
- `GET /visualization` - Interactive visualization page with multiple chart types (Timeline, Severity Indicators, Prosecution Outcomes, Previous Perpetrator, Environment, Organizations Involved)
- `GET /search` - Facet decision tree over stored cases (D3); prune filters; cohort case IDs via API
- `GET /query` - Custom analysis lab (browser-only JavaScript calling public APIs; see page for examples)
- `GET /expand` - Build-your-own viz examples (stats bars, facet tree text view, D3 histogram via public APIs)
- `GET /analysis` - Advanced case analysis page with tag-based filtering and automated analysis
- `GET /api/facet-tree` - Build facet tree JSON (`max_depth`, optional prune query params)
- `GET /api/facet-distinct` - Distinct primary-bucket values per facet (for Search prune UI)
- `POST /api/facet-cohort-members` - Case IDs for a facet path (same prune semantics as tree; small cohorts gated)
- `GET /triage` - Triage page (rules, model evaluation, corpus model tiers, live paste)
- `GET /ml-experimental` - Experimental ML documentation page
- `GET /api/triage-eval` - Stratified train/test metrics on live cases (same pipeline as `scripts/verify/test_triage.py`)
- `GET /api/triage-model-corpus` - Saved bundle predictions over live DB; optional `facet_constraints` JSON query param (rate limited)
- `POST /api/triage-live` - Classify pasted batch text in memory only; requires bundle; no persistence
- `GET /sources` - Data sources page
- `GET /case-studies` - Case studies reading room (eras + studies from `data/case_studies.json`)
- `GET /api/case-studies` - Case study content document (eras, studies, default form URL)
- `GET /api/case-studies/notes/{case_id}` - Community notes for a study id
- `POST /api/case-studies/notes/{case_id}` - Append a community note (rate limited)
- `GET /audit` - Data audit page for reviewing extracted features case-by-case
- `GET /api/cases` - Full bulk case export (localhost or `CaseLinker-Key` in `CASELINKER_TRUSTED_KEYS`)
- `GET /api/cases-summaries-chunk` - Public paginated summaries (`offset`, `limit` ≤ 500); UI loads the full timeline via many small responses, not one bulk JSON
- `POST /api/cases-summaries-by-ids` - Public batched summaries (max 500 ids per request) for cluster membership and similar flows
- `GET /api/cases/{case_id}` - Single case (public responses omit `raw_data`; narrative available as `case_text` for UI drill-down)
- `GET /api/automated-analysis` - Run automated analysis (case grouping, triage, insights)
- `POST /api/return-tagged-cases` - Get cases matching selected tags (intersection logic)
- `GET /api/stats` - Get case statistics (total cases, total victims, extracted features count, sources)
- `GET /docs` - Interactive API documentation

## Technology Stack

- **Backend**: Python 3, FastAPI, Uvicorn
- **Data Processing**: Pandas, NumPy
- **PDF Processing**: pdfplumber
- **Database**: PostgreSQL (production) / SQLite (local development)
  - Production: Railway PostgreSQL with encrypted connections
  - Local: SQLite database auto-created on first run
- **Visualization**: D3.js, HTML/CSS/JavaScript
- **ML/NER**: 
  - Stanza primary NER model; optional Transformers/spaCy paths in code
  - **Supervised triage (experimental)**: scikit-learn random forest or decision tree; labels from rule-based priority scores; `joblib` bundle loaded at inference time
- **Architecture**: Modular 5-layer design

## Deployment

CaseLinker can be deployed to cloud platforms for public access. The app includes a `Procfile` for deployment to Railway, Heroku, and similar platforms.


## Sources and Ethics
- **No Sensitive Data**: This system contains cases from publicly available sources (ICAC Task Forces Cases and Arrests, NCMEC CyberTipline Success Stories, DOJ CEOS Press Releases, and State Attorneys General's Office Press Releases). These reports are publicly available, summarize investigations, arrests, and case details, and are redacted for public release. All data was already in the public domain. This project received a determination from the University of Massachusetts Amherst Human Research Protection Office (HRPO Determination #7668); this research does not contain private or identifiable information under federal regulations [45 CFR 46.102(f)(1), (2)].
- **See `/sources` page for full disclaimer regarding data usage**

## Contributing

Contributors can help by:
- Adding ideas to the README
- Contributing to the architecture design
- Code implementation
