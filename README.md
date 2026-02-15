# CaseLinker

**CaseLinker** is a project designed to group and visualize **statistical** and **contextual** information from cases involving crimes against children and child sexual exploitation & abuse (CSEA).

## 🌐 Live Demo

**Try the latest version online:** [https://web-production-13a2.up.railway.app](https://web-production-13a2.up.railway.app)

The live deployment includes all features and 47 processed cases from AZICAC reports (2011-2014). No installation required—just open the link in your browser.

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
- **Statistical analysis**: Cases and broader child exploitation trends over time

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

The live version includes all features and 47 processed cases. Perfect for quick testing and demonstrations.

### Option 2: Local Setup (Works Out of the Box)

```bash
# Clone the repository
git clone https://github.com/mrinaalr/CaseLinker.git
cd CaseLinker

# Run setup script (creates venv and installs dependencies)
./setup.sh

# Activate virtual environment
source venv/bin/activate

# Start the visualization server
python3 run/main.py
```

Then open your browser to:
- **Home**: http://localhost:8000/
- **Visualizations**: http://localhost:8000/visualization
- **Advanced Analysis**: http://localhost:8000/analysis
- **Data Sources**: http://localhost:8000/sources
- **Data Audit**: http://localhost:8000/audit
- **API Documentation**: http://localhost:8000/docs

**Important:** The repository includes a database (`caselinker.db`) with processed cases from AZICAC reports (2011-2014). The database uses plain SQLite (no encryption) for maximum compatibility across all platforms including Railway.

You can process additional PDFs to add more cases to the database.

### Manual Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### ⚠️ Important: Data Source and Warning

**This project processes sensitive case data related to child exploitation cases. The content may be disturbing and is intended for research and analysis purposes only.**

**Before proceeding, please ensure you are authorized to access and process this type of sensitive case data.**

### Process Your Own PDF Files

To process case PDFs (single or multiple files):

**Single PDF:**
```bash
source venv/bin/activate
python3 -m src.main "path/to/your/file.pdf"
```

**Multiple PDFs:**
```bash
python3 -m src.main "file1.pdf" "file2.pdf" "file3.pdf"
```

**Example - Process all 4 years (2011-2014):**
```bash
python3 src/main.py "2011 Cases and Arrests – AZICAC.ORG.pdf" "2012 Cases and Arrests – AZICAC.ORG.pdf" "2013 Cases and Arrests – AZICAC.ORG.pdf" "2014 Cases and Arrests – AZICAC.ORG.pdf"
```

Or run interactively:
```bash
python3 -m src.main
```

When prompted, enter one or more PDF file paths separated by spaces (e.g., `2013 Cases.pdf 2014 Cases.pdf 2015 Cases.pdf`).

The system will:
1. Extract text from each PDF
2. Identify organization name from filename (AZICAC, FBI, NCMEC, etc.)
3. Split cases by month patterns ("In [Month] of [Year]", "In [Month] [Year]", "during [Month] [Year]")
4. Extract features and assign case IDs (format: `org_name_year_month_number`)
5. Store all cases in the database
6. Display summary with cases broken down by source

**Note:** The database file (`caselinker.db`) is included in the repository. It contains 47 processed cases from publicly available AZICAC case reports (2011-2014) with extracted features including platforms, agencies, severity indicators, case topics, prosecution outcomes, victim/perpetrator demographics, and evidence volume.

### Using the Visualization

1. **Timeline View**: See all cases plotted on an interactive timeline. Filter by year range using the dropdown. Click on case points to view detailed information.
2. **Severity Indicators**: Bar chart with color gradient showing severity levels (infant, very young, production, etc.). Click bars to view cases with highlighted severity text.
3. **Prosecution Outcomes**: Bar chart showing case distribution across prosecution categories (No Charges Listed, Sexual Exploitation of a Minor, Booked, Arrested). Click bars to view cases with highlighted outcome details.
4. **Previous Perpetrator**: Pie chart showing registered sex offenders vs. non-registered. Click slices to view cases with highlighted perpetrator status.
5. **Environment**: Bar chart showing distribution of platforms and environments used (Facebook, online, chat, etc.). Click bars to view cases with highlighted platform text.
6. **Organizations Involved**: Horizontal bar chart showing law enforcement agencies involved (AZICAC, FBI, Phoenix Police, etc.). Click bars to view cases with highlighted agency names.

### Using Advanced Case Analysis

1. **Tag-Based Analysis (🔬 Run Advanced Analysis)**:
   - Select one or more tags from categories: Case Topics, Severity Indicators, Platforms & Environments, Investigation Types, Perpetrator Relationships, Perpetrator Status
   - Click "Run Advanced Analysis" to find all cases matching ALL selected tags (intersection logic)
   - View matching cases with highlighted text showing where tags were found in the raw case data
   - See case counts for each selected tag

2. **Automated Analysis (⚡ Run Automated Analysis)**:
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
- **Audit Tab**: Review extracted features case-by-case with interactive highlighting to verify extraction accuracy


## Project Structure

```
CaseLinker/
├── src/
│   ├── Ingestion Layer/          # PDF extraction, file import
│   ├── Processing Layer/         # Feature extraction, case batching
│   ├── Storage Layer/            # Database storage with encryption
│   ├── Clustering & Analysis Layer/  # Case comparison, clustering
│   ├── Visualization Layer/      # Visualization data structures
│   └── main.py                  # Main entry point
├── run/
│   └── main.py                  # FastAPI backend server
├── visualization/
│   ├── home.html                # Home page
│   ├── index.html               # Interactive visualizations (Timeline, Severity, Outcomes, Perpetrator, Environment, Organizations)
│   ├── analysis.html            # Advanced case analysis page (tag-based filtering and automated analysis)
│   ├── sources.html             # Data sources page
│   └── audit.html               # Data audit page (case-by-case feature review)
├── setup.sh                     # Automated setup script
├── requirements.txt             # Python dependencies
├── config.py                    # Configuration settings
├── caselinker.db                # SQLite database with 47 processed cases (2011-2014)
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
- **Architecture**: Modular 5-layer design

## Deployment

CaseLinker can be deployed to cloud platforms for public access. The app includes a `Procfile` for deployment to Railway, Heroku, Render, and similar platforms.

### Railway Deployment

**Live Demo:** [https://web-production-13a2.up.railway.app](https://web-production-13a2.up.railway.app)

The database uses plain SQLite (no encryption) for maximum compatibility. The database file is included in the repository and will work immediately on Railway.

## Security

- **Database**: Plain SQLite database for maximum compatibility across platforms
- **No Sensitive Data**: Only publicly available case information is processed
- **Disclaimer**: See `/sources` page for full disclaimer regarding data usage

## Current Status

 **Implemented:**
- PDF ingestion and case batching (splits cases by month patterns: "In [Month]" and "[Month] [Year],")
- Multi-PDF processing support (process multiple PDFs in a single run)
- Text cleanup: Comprehensive URL removal and artifact cleanup
- Feature extraction (regex-based for structured data, pattern-based for semantic features):
  - **Structured features**: Demographics, platforms, evidence, prosecution, investigation (95%+ coverage for critical fields)
  - **Semantic features**: Severity indicators (infant, rape, very_young, under_10, production), case topics (production, possession, hands_on, online_only, family, stranger, international, multi_state, pornography)
  - **Severity phrases**: Non-traditional indicators (dangerous, stated, told, continue, attacked, out_of_control)
- Database storage (47 processed cases from 2011-2014 AZICAC reports)
- 6 interactive visualizations with click-to-view case details and text highlighting:
  - Timeline (bottom-up chronological view with color-coded severity)
  - Severity Indicators (color-coded by severity level)
  - Prosecution Outcomes (booking status and charges)
  - Previous Perpetrator (registered sex offender status)
  - Environment (platforms and online methods)
  - Organizations Involved (law enforcement agencies)
- **Advanced Case Analysis** with two modes:
  - **Tag-Based Analysis**: Select multiple tags (case topics, severity indicators, platforms, etc.) to find cases matching all selected tags, with highlighted matching features
  - **Automated Analysis**: Case grouping, triage, and insights generation:
    - Case grouping by similarity (platforms, demographics, topics, severity, investigation)
    - Priority triage with normalized scores (5-10 scale) based on:
      - Severity indicators (35%): infant, rape, very_young, physical_abuse
      - Victim count (30%): Aggressive scoring for multiple victims
      - Case type (25%): production, hands_on, possession, online_only
      - Severity phrases (15%): dangerous, stated, told, continue, attacked, out_of_control
      - Evidence volume (10%): images, videos, storage size
      - Registered sex offender (10%): Repeat offender status
    - Automated insights (platform analysis, severity distribution, case topics)
    - Pattern detection (repeat offenders, relationship patterns, investigation focus)
    - Semantic keyword extraction (frequency-based from case text)
    - Expandable detail views with raw case data and analysis explanations
- Web interface with navigation, filtering, and year range selection
- Data audit page for reviewing extracted features with interactive source text highlighting



## Contributing

Contributors can help by:
- Adding ideas to the README
- Contributing to the architecture design
- Code implementation
