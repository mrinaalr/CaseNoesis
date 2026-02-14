# CaseLinker

**CaseLinker** is a project designed to group and visualize **statistical** and **contextual** information from cases involving crimes against children and child sexual exploitation & abuse (CSEA).

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
3. **Storage Layer**: SQLite database with SQLCipher encryption support for secure case storage
4. **Clustering & Analysis Layer**: Case comparison, similarity detection, and clustering (basic implementation)
5. **Visualization Layer**: Interactive web-based dashboards with D3.js visualizations

## Installation

### Quick Setup (Works Out of the Box)

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

**Important:** The repository includes an encrypted database (`caselinker.db`) with processed cases from AZICAC reports (2013-2014). 

- **If SQLCipher is installed**: The encrypted database will work immediately
- **If SQLCipher is NOT installed**: The system will create a new unencrypted database. You can either:
  - Process your own PDFs using `python3 -m src.main`
  - Install SQLCipher to use the included encrypted database

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

To process additional case PDFs:

```bash
source venv/bin/activate
python3 -m src.main
```

When prompted, enter the path to your PDF file (e.g., `2014 Cases and Arrests – AZICAC.ORG.pdf`).

Or provide the file path directly:
```bash
python3 -m src.main "path/to/your/file.pdf"
```

The system will:
1. Extract text from the PDF
2. Split cases by month patterns ("In [Month] of [Year]")
3. Store cases in the encrypted database
4. Display processed cases

**Note:** The database file (`caselinker.db`) is encrypted with SQLCipher and included in the repository. It contains 25 processed cases from publicly available AZICAC case reports (2013-2014) with extracted features including platforms, agencies, severity indicators, case topics, and prosecution outcomes.

### Using the Visualization

1. **Timeline View**: See all cases plotted on an interactive timeline. Filter by year range using the dropdown. Click on case points to view detailed information.
2. **Severity Indicators**: Bar chart with color gradient showing severity levels (infant, very young, production, etc.). Click bars to view cases with highlighted severity text.
3. **Prosecution Outcomes**: Bar chart showing case distribution across prosecution categories (No Charges Listed, Sexual Exploitation of a Minor, Booked, Arrested). Click bars to view cases with highlighted outcome details.
4. **Previous Perpetrator**: Pie chart showing registered sex offenders vs. non-registered. Click slices to view cases with highlighted perpetrator status.
5. **Environment**: Bar chart showing distribution of platforms and environments used (Facebook, online, chat, etc.). Click bars to view cases with highlighted platform text.
6. **Organizations Involved**: Horizontal bar chart showing law enforcement agencies involved (AZICAC, FBI, Phoenix Police, etc.). Click bars to view cases with highlighted agency names.
7. **Sources Tab**: View data sources and access original case reports
8. **Audit Tab**: Review extracted features case-by-case with interactive highlighting to verify extraction accuracy


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
│   ├── analysis.html            # Advanced analysis page (placeholder)
│   ├── sources.html             # Data sources page
│   └── audit.html               # Data audit page (case-by-case feature review)
├── setup.sh                     # Automated setup script
├── requirements.txt             # Python dependencies
├── config.py                    # Configuration settings
├── caselinker.db                # Encrypted database (SQLCipher) with 25 processed cases
├── Procfile                     # Deployment configuration for Railway/Heroku
├── Architecture design.md       # System architecture documentation
├── FEATURE_EXTRACTION_ASSESSMENT.md  # Feature extraction quality assessment
├── RAILWAY_DEPLOY.md            # Step-by-step Railway deployment guide
└── HOSTING.md                   # Hosting options and deployment guide
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
- **Case Topics**: Themes such as production vs. possession, international cooperation, multi-state cases, hands-on vs. online-only, family vs. stranger
- **Severity Indicators**: Age-based severity (infant, very young, under 5, under 9) and production indicators

### **Preserved Data**
- **Raw Case Text**: Original case narrative preserved for reference
- **Metadata**: Source, date range, creation timestamps

## API Endpoints

- `GET /` - Home page
- `GET /visualization` - Interactive visualization page with multiple chart types (Timeline, Severity Indicators, Prosecution Outcomes, Previous Perpetrator, Environment, Organizations Involved)
- `GET /sources` - Data sources page
- `GET /audit` - Data audit page for reviewing extracted features case-by-case
- `GET /api/cases` - Get all cases
- `GET /api/cases/{case_id}` - Get specific case
- `GET /api/stats` - Get case statistics (total cases, total victims, extracted features count, sources)
- `GET /docs` - Interactive API documentation

## Technology Stack

- **Backend**: Python 3, FastAPI, Uvicorn
- **Data Processing**: Pandas, NumPy
- **PDF Processing**: pdfplumber
- **Database**: SQLite with SQLCipher encryption (optional, falls back to regular SQLite)
- **Visualization**: D3.js, HTML/CSS/JavaScript
- **Architecture**: Modular 5-layer design

## Deployment

CaseLinker can be deployed to cloud platforms for public access. The app includes a `Procfile` for deployment to Railway, Heroku, Render, and similar platforms. See `HOSTING.md` for deployment options and instructions.

## Security

- **Database Encryption**: Case data is encrypted using SQLCipher (256-bit AES) when available
- **Graceful Fallback**: If SQLCipher is not installed, the system uses regular SQLite
- **No Sensitive Data**: Only publicly available case information is processed
- **Disclaimer**: See `/sources` page for full disclaimer regarding data usage

## Current Status

 **Implemented:**
- PDF ingestion and case batching (splits cases by month patterns: "In [Month] of [Year]")
- Feature extraction (regex-based for structured data, pattern-based for semantic features)
- Database storage with SQLCipher encryption support (25 processed cases from 2013-2014 AZICAC reports)
- 6 interactive visualizations with click-to-view case details and text highlighting:
  - Timeline (bottom-up chronological view)
  - Severity Indicators (color-coded by severity level)
  - Prosecution Outcomes (booking status and charges)
  - Previous Perpetrator (registered sex offender status)
  - Environment (platforms and online methods)
  - Organizations Involved (law enforcement agencies)
- Web interface with navigation, filtering, and year range selection
- Data audit page for reviewing extracted features with interactive source text highlighting



## Contributing

Contributors can help by:
- Adding ideas to the README
- Contributing to the architecture design
- Code implementation
