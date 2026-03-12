# CaseLinker

**CaseLinker** is a project designed to group and visualize **statistical** and **contextual** information from cases involving crimes against children and child sexual exploitation & abuse (CSEA).

## Live Demo

**Try the latest version online:** [https://web-production-13a2.up.railway.app](https://web-production-13a2.up.railway.app)

The live deployment includes all features and 207 cases from publicly available Arizona ICAC / NCMEC annual reports (2011–2014 and 2022-2024). These reports summarize investigations, arrests, and prosecutions, redacted for public release. No PII was processed; all data was already in the public domain. No installation required—just open the link in your browser.

## Technical Reports

- **[Report #1: CaseLinker: An Open-Source System for Cross-Case Analysis of Internet Crimes Against Children Reports](https://mrinaalr.github.io/website/CaseLinker.pdf)** - Initial technical report documenting the prototype architecture, deterministic extraction pipeline, and evaluation baseline on 47 cases.

- **[Report #2: Interpretable ML Approaches for Analyzing Internet Crimes Against Children Reports](https://mrinaalr.github.io/website/CaseLinker-%20Interpretable%20ML%20Approaches%20for%20Analyzing%20Internet%20Crimes%20Against%20Children%20Reports.pdf)** - Second report covering NER integration, dataset expansion to 207 cases, and emerging patterns from the expanded dataset including the distributed network of 215 law enforcement organizations.


## Motivation

This project was motivated by challenges I encountered with understanding child exploitation cases, including:

- **Fragmented data sources**: Cases are scattered across numerous organizations, states, and agencies
- **Cross-case analysis**: Identifying patterns, similarities, and connections between cases becomes challenging without a unified system, even when cases share common characteristics such as perpetrators, platforms, or victim demographics
- **Limitations in trend analysis**: Analyzing the evolution of child exploitation, the mediums in which it occurs, and recurring case topics
- **Emotional impact**: The challenge of repeatedly reading and processing highly disturbing case material

CaseLinker aims to address these challenges by serving as a tool for case analysis, enabling researchers, law enforcement, and advocacy organizations to better understand the landscape of child exploitation.

## Emphasis

- **Clustering and linking**: Cases based on shared characteristics such as victim context, platforms used, and law enforcement actions
- **Visualization**: Cases with particular attention to tasteful presentation of case content, and pattern analysis across investigations
- **Feature extraction**: Robust extraction of information from cases and explainability for clusters and analysis

## System Architecture

CaseLinker follows a modular, layered architecture:

1. **Ingestion Layer**: Handles PDF data sources with text extraction and validation
2. **Processing Layer**: Extracts features, assigns comparison values, and fills case schema
3. **Storage Layer**: SQLite database (plain SQLite for maximum compatibility)
4. **Clustering & Analysis Layer**: Case comparison, similarity detection, automated grouping, triage, and insights generation
5. **Visualization Layer**: Interactive web-based dashboards with D3.js visualizations

## Installation

### Option 1: Use Live Demo (Recommended for Quick Testing)

**No installation required.** Visit the live deployment:
- **Live Application**: [https://web-production-13a2.up.railway.app](https://web-production-13a2.up.railway.app)

The live version includes all features and 207 processed cases. Created for quick testing and demonstrations.

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
- **Data Sources**: http://localhost:8000/sources
- **Data Audit**: http://localhost:8000/audit
- **API Documentation**: http://localhost:8000/docs

**Important:** The repository includes a database (`caselinker.db`) with 48 cases from NCMEC 2024 CyberTipline report and 47 cases from Arizona ICAC annual reports (2011–2014). These reports are publicly available, summarize investigations, arrests, and case details, and are redacted for public release. No PII was processed; all data was already in the public domain. This project received a determination from the University of Massachusetts Amherst Human Research Protection Office (HRPO Determination #7668) confirming that this research contains no private or identifiable information under federal regulations [45 CFR 46.102(f)(1), (2)].

**Database:** The database uses plain SQLite (no encryption) for maximum compatibility. The architecture supports merged, federated, or encrypted databases as needed. Researchers and orgs can encrypt the current implementation or swap out the database implementation with SQLCipher, PostgreSQL, or other database systems. 


You can process additional PDFs to add more cases to the database.


## Usage

### ⚠️ Important: Data Content and Warning

**This project processes sensitive case data related to child exploitation cases. The content may be disturbing and is intended for research and analysis purposes only.**

**Before proceeding, please ensure you are authorized to access and process this type of sensitive case data.**

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

To process case PDFs (single or multiple files):

**Single PDF:**
```bash
source venv/bin/activate
python3 -m src.main "path/to/your/file.pdf"
```

**Multiple PDFs:**
```bash
python3 src/main.py "2011 Cases and Arrests – AZICAC.ORG.pdf" "2020 Reports" "2024-media-coverage-cybertipline-success-stories.pdf" 
```

Or run interactively:
```bash
python3 -m src.main
```

When prompted, enter one or more PDF file paths separated by spaces (e.g., `2013 Cases.pdf 2014 Cases.pdf 2015 Cases.pdf`).

The system will:
1. Extract text from each PDF
2. Identify organization name from filename (AZICAC, FBI, NCMEC, etc.)
3. Batch cases, extract features, assign case IDs (format: `org_name_number`)
4. Store all cases in the database
5. Perform clustering computations and prepare to run main application


## Using the Visualizations

Access the visualizations via the [live demo](https://web-production-13a2.up.railway.app/visualization) or by running the server locally (`python3 run/main.py`) and navigating to http://localhost:8000/visualization.

1. **Case Group**: Displays cases matching specific groups (infant, very young, assault, posession, online) 
2. **Severity Indicators**: Bar chart with color gradient showing severity levels (infant, very young, production, etc.). Click bars to view cases with highlighted severity text.
3. **Case Visualization**: Enter a Case ID (with autocomplete suggestions) to view comprehensive case details. The visualization displays structured information cards for platforms, severity indicators, case topics, investigation details, demographics, evidence volume, and prosecution outcomes with key information highlighted.
4. **Previous Perpetrator**: Pie chart showing registered sex offenders vs. non-registered. Click slices to view cases with highlighted perpetrator status.
5. **Environment**: Bar chart showing distribution of platforms and environments used (Facebook, online, chat, etc.). Click bars to view cases with highlighted platform text.
6. **Organizations Involved**: Horizontal bar chart showing law enforcement agencies involved (AZICAC, FBI, Phoenix Police, etc.). Click bars to view cases with highlighted agency names.

## Using Advanced Case Analysis

Navigate to [live demo](https://web-production-13a2.up.railway.app/analysis) or run server locally (`python3 run/main.py`) and navigate to http://localhost:8000/analysis.


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
     - Severity phrases (15%): dangerous, stated, told, continue, attacked, out_of_control
     - Evidence volume (10%): images, videos, storage size
     - Registered sex offender (10%): Repeat offender status
   - **Automated Insights**: View insights about most common platforms, severity distribution, and case topics
   - **Patterns Detected**: See patterns like repeat offenders, relationship patterns, and investigation focus
   - **Top Keywords**: View most frequent keywords extracted from case text
   - **Expandable Details**: Click any box to view raw case data with highlighted priority indicators and detailed explanations of why the analysis prioritized/grouped the case

### Other Features

- **Sources Tab**: View data sources and access original case reports
- **Clusters Tab**: View pre computed clusters, analyze case reports
- **Audit Tab**: Review extracted features case-by-case with interactive highlighting to verify extraction accuracy


## Project Structure

```
CaseLinker/
├── src/
│   ├── Ingestion Layer/          # PDF extraction, file import
│   ├── Processing Layer/         # Feature extraction, case batching
│   ├── Storage Layer/            # Database storage
│   ├── Clustering & Analysis Layer/  # Case comparison, clustering
│   ├── Visualization Layer/      # Visualization data structures
│   └── main.py                  # CLI tool: Process PDFs and populate database
├── run/
│   └── main.py                  # Main application: Serves visualizations and API
├── visualization/
│   ├── home.html                # Home page
│   ├── index.html               # Interactive visualizations (Timeline, Severity, Outcomes, Perpetrator, Environment, Organizations)
│   ├── analysis.html            # Advanced case analysis page (tag-based filtering and automated analysis)
│   ├── sources.html             # Data sources page
│   └── audit.html               # Data audit page (case-by-case feature review)
├── setup.sh                     # Automated setup script
├── requirements.txt             # Python dependencies
├── config.py                    # Configuration settings
├── caselinker.db                # SQLite database with 207 processed cases
├── Procfile                     # Deployment configuration for Railway/Heroku
├── Architecture design.md       # System architecture documentation
```

## Case Schema & Feature Extraction

Each case includes structured features extracted from case narratives:

### **Extracted Features (Regex-based)**
- **Perpetrator Demographics**: Age, registration status (registered sex offender)
- **Victim Demographics**: Age(s), count (when explicit), gender
- **Relationship**: Relationship to victim (father, mother, brother, stranger, etc.)
- **Platforms**: Social media platforms and online methods (Facebook, online chat, etc.)
- **Charges**: Detailed prosecution charges with counts
- **Evidence Volume**: Images, videos, storage size (TB/GB), messages
- **Investigation Type**: Proactive, reactive, online, or undercover investigations
- **Agencies**: Law enforcement agencies involved (AZICAC, FBI, Phoenix Police, etc.)

### **Semantic Features (Pattern-based)**
- **Case Topics**: Themes such as production vs. possession, international cooperation, multi-state cases, hands-on vs. online-only, family vs. stranger, pornography
- **Severity Indicators**: Age-based severity (infant, rape, very_young, under_10) and production indicators
- **Severity Phrases**: Non-traditional indicators extracted from case text (dangerous, stated, told, continue, attacked, out_of_control) - used for priority scoring

### **Preserved Data**
- **Raw Case Text**: Original case narrative preserved for reference
- **Metadata**: Source, date range, creation timestamps

## API Endpoints

- `GET /` - Home page
- `GET /visualization` - Interactive visualization page with multiple chart types (Timeline, Severity Indicators, Prosecution Outcomes, Previous Perpetrator, Environment, Organizations Involved)
- `GET /analysis` - Advanced case analysis page with tag-based filtering and automated analysis
- `GET /sources` - Data sources page
- `GET /audit` - Data audit page for reviewing extracted features case-by-case
- `GET /api/cases` - Get all cases
- `GET /api/cases/{case_id}` - Get specific case
- `GET /api/automated-analysis` - Run automated analysis (case grouping, triage, insights)
- `POST /api/return-tagged-cases` - Get cases matching selected tags (intersection logic)
- `GET /api/stats` - Get case statistics (total cases, total victims, extracted features count, sources)
- `GET /docs` - Interactive API documentation

## Technology Stack

- **Backend**: Python 3, FastAPI, Uvicorn
- **Data Processing**: Pandas, NumPy
- **PDF Processing**: pdfplumber
- **Database**: SQLite (plain database for maximum compatibility)
- **Visualization**: D3.js, HTML/CSS/JavaScript
- **ML/NER**: Stanza (Stanford NLP), Transformers models for Named Entity Recognition
  - Extracts law enforcement organizations, ages, dates, and locations from case text
  - Hybrid approach: ML/NER supplements regex-based pattern extraction via MergeProcessing layer
  - Pattern processing takes precedence when both sources have data; NER fills gaps
- **Architecture**: Modular 5-layer design

## Deployment

CaseLinker can be deployed to cloud platforms for public access. The app includes a `Procfile` for deployment to Railway, Heroku, and similar platforms.


## Sources and Ethics
- **No Sensitive Data**: The database contains 207 cases from publicly available NCMEC / Arizona ICAC annual reports. These reports are publicly available, summarize investigations, arrests, and case details, and are redacted for public release. All data was already in the public domain. This project received a determination from the University of Massachusetts Amherst Human Research Protection Office (HRPO Determination #7668) confirming that the research contains no private or identifiable information under federal regulations [45 CFR 46.102(f)(1), (2)].
- **See `/sources` page for full disclaimer regarding data usage**


## Contributing

Contributors can help by:
- Adding ideas to the README
- Contributing to the architecture design
- Code implementation
