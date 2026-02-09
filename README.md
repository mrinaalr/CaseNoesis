# CaseLinker

**CaseLinker** is a project designed to group and visualize **statistical** and **contextual** information from cases involving online child victimization, CSAM, and child sexual exploitation & abuse (CSEA).

## Motivation

This project was motivated by challenges I encountered with understanding child exploitation cases, including:

- **Fragmented data sources**: Cases are scattered across numerous organizations, states, and agencies
- **Cross-case analysis**: Identifying patterns, similarities, and connections between cases becomes challenging without a unified system, even when cases share common characteristics such as perpetrators, technologies, or victim demographics
- **Limitations in trend analysis**: Analyzing the evolution of child exploitation, the mediums in which it occurs, and recurring case topics
- **Emotional impact**: The burden of repeatedly reading and processing highly disturbing case material

CaseLinker aims to address these challenges by serving as a tool for case analysis, enabling researchers, law enforcement, and advocacy organizations to better understand the landscape of child exploitation.

## Emphasis

- **Clustering and linking**: Cases based on shared characteristics such as victim context, technologies used, and law enforcement actions
- **Visualization**: Cases with particular attention to tasteful presentation of case content, and pattern analysis across investigations
- **Statistical analysis**: Cases and broader child exploitation trends over time

## System Architecture

CaseLinker follows a modular, layered architecture:

1. **Ingestion Layer**: Handles diverse data sources (PDF, CSV, text files) with validation and sanitization
2. **Processing Layer**: Extracts features, assigns comparison values, and fills case schema. Automatically splits cases by month patterns
3. **Storage Layer**: SQLite database with SQLCipher encryption support for secure case storage
4. **Clustering & Analysis Layer**: Case comparison, similarity detection, clustering, and trend analysis
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
- **Timeline Visualization**: http://localhost:8000/visualization
- **Advanced Analysis**: http://localhost:8000/analysis
- **Data Sources**: http://localhost:8000/sources
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

**Note:** The database file (`caselinker.db`) is encrypted with SQLCipher and included in the repository. It contains processed case data from publicly available AZICAC case reports.

### Using the Visualization

1. **Timeline View**: See all cases plotted on an interactive timeline. Filter by year range using the dropdown.
2. **Analysis Tab**: Select topics (or add custom topics) to perform advanced clustering and pattern detection.
3. **Sources Tab**: View data sources and access original case reports.


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
│   ├── index.html               # Timeline visualization
│   ├── analysis.html            # Advanced analysis page
│   └── sources.html             # Data sources page
├── setup.sh                     # Automated setup script
├── requirements.txt             # Python dependencies
├── config.py                    # Configuration settings
├── caselinker.db                # Encrypted database (SQLCipher)
└── Architecture design.md       # System architecture documentation
```

## Case Schema

Each case includes:
- **Identification**: Unique ID, source, date range
- **Victim Context**: Count, demographics (anonymized)
- **Perpetrator Context**: Count, demographics, relationship to victim
- **Technology & Methods**: Platforms, technologies, communication methods
- **Law Enforcement**: Investigation methods, prosecution outcomes
- **Content Classification**: Severity indicators, case topics
- **Raw Data**: Original case data preserved for reference

## API Endpoints

- `GET /` - Home page
- `GET /visualization` - Timeline visualization page
- `GET /analysis` - Advanced analysis page
- `GET /sources` - Data sources page
- `GET /api/cases` - Get all cases
- `GET /api/cases/{case_id}` - Get specific case
- `GET /api/timeline` - Get timeline visualization data
- `GET /api/clusters` - Get case clusters
- `GET /api/stats` - Get case statistics
- `GET /docs` - Interactive API documentation

## Technology Stack

- **Backend**: Python 3, FastAPI, Uvicorn
- **Data Processing**: Pandas, NumPy
- **PDF Processing**: pdfplumber
- **Database**: SQLite with SQLCipher encryption (optional, falls back to regular SQLite)
- **Visualization**: D3.js, HTML/CSS/JavaScript
- **Architecture**: Modular 5-layer design

## Security

- **Database Encryption**: Case data is encrypted using SQLCipher (256-bit AES) when available
- **Graceful Fallback**: If SQLCipher is not installed, the system uses regular SQLite
- **No Sensitive Data**: Only publicly available case information is processed
- **Disclaimer**: See `/sources` page for full disclaimer regarding data usage



## Contributing

Contributors can help by:
- Adding ideas to the README
- Contributing to the architecture design
- Code implementation