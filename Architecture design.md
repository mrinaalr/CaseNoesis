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
- **Case Batching**: Splits large text blocks into individual cases using regex patterns ("In [Month] of [Year]", "In [Month] [Year]", "during [Month] [Year]")
- **Feature Extraction**: Hybrid approach using regex for structured data and pattern-based matching for semantic features
- **Case ID Generation**: Creates unique case IDs in format `org_name_year_month_number` (e.g., `azicac_2013_january_001`)


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
  - severity_indicators: [str] (infant, very_young, under_5, under_9, production, created)
  - case_topics: [str] (production, possession, international, multi_state, hands_on, online_only, family, stranger)
  
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
- **Case Database** (PostgreSQL/MySQL):
  - keep it simple, store case data tables, ideally similar close together
  - ideally also store case entities in "rawish" format (preserve original structure + normalized fields)
  - encrypt db - use SQLCipher to start (prev exp) and improve as needed

- **Graph Database**: Not yet implemented (future enhancement for relationship mapping)



### 4. Clustering and Analysis Layer 

**Purpose**: Compare cases, detect clusters, identify trends, and select cases to display together.

**Components**:
- **Case Comparison**:
  - Compare cases against each other in database
  - Calculate similarity scores using assigned values
  - Identify potential links and relationships
  - Support multiple compare metrics 
- **Clustering**:
  - Group cases based on shared characteristics
  - Multi-dimensional clustering (by platform, method, victim, perpetrator, region, time, etc.)
- **Link Detection**:
  - Entity matching: organizations involved, victims demographics, platforms across cases
  - Pattern-based linking: deeper patterns in cases
- **Trend Detection**:
  - Analyze evolution of exploitation methods over time
  - Recurring case topics 
- **Case Selection**:
  - Select cases to display together based on clustering
  - Filter and group cases for visualization
  - Support user-defined grouping criteria


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


