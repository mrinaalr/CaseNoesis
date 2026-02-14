# CaseLinker Architecture

## Overview

CaseLinker is designed as a system for ingesting, processing, clustering, and visualizing case related data, specifically cases related to CSEA. This means often cases will be a) scrapped from websites b) not cleanly formatted c) have sensitive components d) have varing levels of details (think azicac vs fbi cases vs ncmec reports) 


## System Architecture

### High-Level Components

```
┌─────────────────────────────────────┐
│      Data Sources                   │
│ for now start with one source,      │  
| azicac 2014 cases and arrests,      │
| modular so can upload website / pdf │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Data Ingestion Layer           │
│  - Import                           │  
│  - Data validation                  │
│  - Basic cleaning, panda based      │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Data Processing Layer          │
│  - select data to keep              │
│  - extract features (for compare)   |
|  - fill in case schema for each case|
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Data Storage Layer             │
│  - Case database [rawish]           │
│  - Graph database ( weighting)      │
│  - requires quick retrieval,look-ups│
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Clustering & Analysis Layer    │
│  - Select cases to display together │
|  - Compares based on saved case data|
│  - Trend detection                  │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Visualization Layer            │
│  - Interactive dashboards           │
│  - Graphs (!!)                      │
│  - Filtering                        │
│  - Expandable case/data  views      │
└─────────────────────────────────────┘
```

## Core Components


### 1. Data Ingestion Layer

**Purpose**: Handle diverse, messy data sources and normalize them into a consistent format for processing.

**Components**:
- **PDF Text Extraction**: Uses `pdfplumber` to extract text from PDF case files
- **Text Validation**: Basic validation and cleaning of extracted text
- **Error Handling**: Suppresses warnings and handles extraction errors gracefully 



### 2. Data Processing Layer

**Purpose**: Extract features, assign comparison values, fill in basic schema, and prepare cases for clustering and analysis.

**Components**:
- **Text Cleanup**: Removes URLs, URL fragments, and formatting artifacts from extracted PDF text
- **Case Batching**: Splits large text blocks into individual cases using regex patterns:
  - Primary: "In [Month]" (e.g., "In January", "In February") - case-sensitive for "In"
  - Secondary: "[Month] [Year]," (e.g., "July 2012,", "September 2012,")
- **Feature Extraction**: Hybrid approach:
  - **Regex-based** (high accuracy): Demographics, platforms, evidence, prosecution, investigation
  - **Pattern-based** (semantic): Severity indicators, case topics, severity phrases
- **Case ID Generation**: Creates unique case IDs in format `org_name_year_month_number` (e.g., `azicac_2013_january_001`)
- **Comparison Values**: Assigns normalized feature vectors for similarity calculation


**Case Entity Schema**:

- select relevant, consistent case characteristics to be compared and analyzed
- Based on analysis of actual case data from AZICAC reports (2013-2014)

```yaml
Case:
  - id: unique identifier
  - source: organization/jurisdiction (e.g., "AZICAC", "FBI", "NCMEC")
  - date_range: {start, end} or single date
  
  # Victim Context (anonymized)
  - victim_count: number (when explicitly mentioned)
  - victim_demographics: {ages: [int], age_range: {min, max}, gender: str}
  
  # Perpetrator Context (anonymized)
  - perpetrator_age: int (extracted from "X year old man/woman")
  - perpetrator_registered_sex_offender: bool
  - relationship_to_victim: str (father, mother, brother, sister, uncle, aunt, cousin, stranger, teacher, unknown)
  - previous_conviction: {is_registered: bool, age_at_first_offense: int}
  
  # Technology & Platforms
  - platforms_used: [str] (Facebook, Instagram, Snapchat, Discord, WhatsApp, online, chat)
  
  # Law Enforcement
  - investigation_type: str (proactive, reactive, online, undercover, unknown)
  - agencies_involved: [str] (AZICAC, FBI, Phoenix Police, ICAC, HSI, MCSO, DPS, etc.)
  - prosecution_outcome: {charges: [{count: int, charge: str}], booking_status: str, jail: str}
  
  # Evidence & Content
  - evidence_volume: {images: int, videos: int, storage_size: str, messages: int}
  
  # Content Classification
  - severity_indicators: [str] (infant, rape, very_young, under_10, production)
  - case_topics: [str] (production, possession, international, multi_state, hands_on, online_only, family, stranger, pornography)
  - severity_phrases: [str] (dangerous, stated, told, continue, attacked, out_of_control)  # Non-traditional severity indicators
  
  # Raw/Original Data
  - raw_data: original case data (preserved for reference)
  - case_text: full case text
  
  # Metadata
  - tags: [custom tags]
  - notes: case summary
  - created_at, updated_at
```



### 3. Storage Layer

**Purpose**: Store cases and relationships with fast retrieval and lookup capabilities.

**Components**:
- **Case Database** (SQLite):
  - Simple, efficient storage with normalized tables
  - Stores case entities in "rawish" format (preserves original structure + normalized fields)
  - Uses plain SQLite for maximum compatibility across platforms (Railway, local, etc.)
  - Proper indexing for fast queries (source, date_start, case_topics)
  - JSON storage for complex fields (platforms, topics, severity indicators, etc.)

**Current Implementation**:
- SQLite database (`caselinker.db`) with 47 processed cases (2011-2014)
- Tables: `cases`, `victim_demographics`, `perpetrator_demographics`, `prosecution_outcomes`
- Full raw data preservation in `raw_data` and `extracted_features` fields
- Fast retrieval with proper indexing

**Future Enhancements**:
- Graph Database: Not yet implemented (future enhancement for relationship mapping)
- Database encryption: Considered but deferred for MVP to ensure cross-platform compatibility



### 4. Clustering and Analysis Layer 

**Purpose**: Compare cases, detect clusters, identify trends, and select cases to display together.

**Components**:
- **Tag-Based Filtering**:
  - Filter cases by multiple tags (intersection logic)
  - Categories: Case Topics, Severity Indicators, Platforms, Investigation Types, Relationships, RSO Status
  - Returns cases matching ALL selected tags with highlighted matching text
- **Case Comparison**:
  - Weighted Jaccard similarity using comparison values
  - Multi-dimensional comparison (platforms, demographics, topics, severity, investigation)
  - Similarity threshold: 0.35 for grouping
- **Case Grouping**:
  - Groups similar cases based on shared characteristics
  - Multi-dimensional clustering (by platform, method, victim, perpetrator, region, time, etc.)
- **Priority Triage**:
  - Multi-factor priority scoring (normalized to 5-10 scale):
    - Severity indicators (35%): infant, rape, very_young, production, etc.
    - Victim count (30%): Aggressive scoring for multiple victims
    - Case type (25%): production, hands_on, possession, online_only
    - Severity phrases (15%): dangerous, stated, told, continue, attacked, out_of_control
    - Evidence volume (10%): images, videos, storage size
    - Registered sex offender (10%): Repeat offender status
  - Scores normalized: lowest case → 5.0, highest case → 10.0
- **Automated Insights**:
  - Platform analysis: Most common platforms used
  - Severity distribution: Distribution of severity indicators
  - Case topic analysis: Most common case topics
  - Pattern detection: Repeat offenders, relationship patterns, investigation focus
  - Keyword extraction: Frequency-based semantic keywords from case text
- **Trend Detection**:
  - Analyze evolution of exploitation methods over time
  - Recurring case topics
  - Investigation type distribution


### 5. Visualization Layer

**Purpose**: Present case data, clusters, and trends in an interactive, tasteful, and informative way

**Implemented Visualizations** (using D3.js):
- **Timeline**: Bottom-up chronological view of all cases with year filtering and click-to-view case details
- **Severity Indicators**: Color-coded bar chart (infant = darkest red, none = lightest) with click-to-view cases and text highlighting
- **Prosecution Outcomes**: Bar chart showing case distribution (No Charges Listed, Sexual Exploitation of a Minor, Booked, Arrested) with click-to-view cases
- **Previous Perpetrator**: Pie chart showing registered sex offender status with click-to-view cases
- **Environment**: Bar chart showing platforms and online methods used, with click-to-view cases and text highlighting
- **Organizations Involved**: Horizontal bar chart showing law enforcement agencies with click-to-view cases and text highlighting

**Features**:
- Interactive filtering by year range
- Click-to-view case details with highlighted source text
- Dynamic statistics that update based on selected visualization and filters
- Responsive design with modern UI
- Data audit page for reviewing extracted features with interactive source text highlighting


