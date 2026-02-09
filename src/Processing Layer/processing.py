"""
Processing Layer

Purpose: Extract features, assign comparison values, fill in basic schema, and prepare cases for clustering and analysis.

Design Ideas from Architecture:
- Select data to keep
- Assign cases values (for compare)
- Fill in case schema for each case according to Case Entity Schema:
  - id, source, date_range
  - Victim Context (anonymized): victim_count, victim_demographics
  - Perpetrator Context (anonymized): perpetrator_count, perpetrator_demographics, relationship_to_victim, previous_conviction
  - Technology & Methods: platforms_used, technologies, communication_methods
  - Law Enforcement: investigation_methods_and_teams, prosecution_outcome
  - Content Classification: severity_indicators, case_topics
  - Raw/Original Data: raw_data, extracted_features
  - Metadata: tags, notes, created_at, updated_at
"""

import pandas as pd
import re
from typing import Dict, List, Any, Optional


def case_batching(text: str) -> List[Dict[str, Any]]:
    """
    Split text corpus into individual cases by "In [Month]" patterns.
    Looks for patterns like "In January", "In February", etc. to identify case boundaries.
    
    Args:
        text: Large text block from PDF ingestion
        
    Returns:
        List of case dictionaries, each with 'case_text' and 'month_year'
    """
    cases = []
    
    month_pattern = r'In (January|February|March|April|May|June|July|August|September|October|November|December)'
    
    matches = list(re.finditer(month_pattern, text, re.IGNORECASE))
    
    if not matches:
        return [{'case_text': text, 'month_year': None, 'case_id': 'case_001'}]
    
    for i, match in enumerate(matches):
        month = match.group(1)
        start_pos = match.start()
        
        if i + 1 < len(matches):
            end_pos = matches[i + 1].start()
        else:
            end_pos = len(text)
        
        case_text = text[start_pos:end_pos].strip()
        
        # Extract year from case text - supports any year (2013, 2014, etc.)
        # Look for 4-digit year (1900-2099) in the case text
        year_match = re.search(r'\b(19|20)\d{2}\b', case_text)
        if year_match:
            year = year_match.group(0)
        else:
            # Fallback: use current year if no year found
            from datetime import datetime
            year = str(datetime.now().year)
        
        case_id = f"case_{year}_{month.lower()}_{i+1:03d}"
        
        cases.append({
            'case_text': case_text,
            'month_year': f"{month} {year}",
            'month': month,
            'year': year,
            'case_id': case_id
        })
    
    return cases


def process_cases(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Process cases: split text into cases, extract features and assign comparison values.
    Converts DataFrame rows into structured case dictionaries.
    Fills in case schema for each case as specified in architecture.
    
    Args:
        df: DataFrame from ingestion layer (parsed PDF data with 'extracted_text')
        
    Returns:
        List of structured case dictionaries with extracted features and comparison values
    """
    processed_cases = []
    
    for idx, row in df.iterrows():
        extracted_text = row.get('extracted_text', '')
        source = row.get('source', 'unknown')
        source_file = row.get('source_file', 'unknown')
        
        case_batches = case_batching(extracted_text)
        
        for case_batch in case_batches:
            raw_case = {
                'case_text': case_batch.get('case_text'),
                'month_year': case_batch.get('month_year'),
                'month': case_batch.get('month'),
                'year': case_batch.get('year'),
                'case_id': case_batch.get('case_id'),
                'source': source,
                'source_file': source_file
            }
            
            case_features = extract_features(raw_case)
            
            case_with_values = assign_comparison_values(case_features)
            
            from datetime import datetime
            case_with_values['created_at'] = datetime.now().isoformat()
            case_with_values['updated_at'] = datetime.now().isoformat()
            
            processed_cases.append(case_with_values)
    
    return processed_cases


def extract_features(raw_case: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract structured features from raw case data.
    
    Args:
        raw_case: Raw case dictionary (from case_batching or DataFrame row)
        
    Returns:
        Structured case dictionary with all extracted features
    """
    case_text = raw_case.get('case_text', '')
    month = raw_case.get('month')
    year = raw_case.get('year')
    
    date_range = None
    if month and year:
        date_range = extract_date_range(raw_case)
    
    features = {
        'id': raw_case.get('case_id') or raw_case.get('id'),
        'source': raw_case.get('source', 'unknown'),
        'date_range': date_range,
        'victim_count': extract_victim_count(raw_case),
        'victim_demographics': extract_victim_demographics(raw_case),
        'perpetrator_count': extract_perpetrator_count(raw_case),
        'perpetrator_demographics': extract_perpetrator_demographics(raw_case),
        'relationship_to_victim': extract_relationship(raw_case),
        'previous_conviction': extract_previous_conviction(raw_case),
        'platforms_used': extract_platforms(raw_case),
        'technologies': extract_technologies(raw_case),
        'communication_methods': extract_communication_methods(raw_case),
        'investigation_methods_and_teams': extract_investigation_methods(raw_case),
        'prosecution_outcome': extract_prosecution_outcome(raw_case),
        'severity_indicators': extract_severity(raw_case),
        'case_topics': extract_topics(raw_case),
        'raw_data': raw_case,
        'case_text': case_text,
    }
    
    return features

def assign_comparison_values(case_features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assign normalized values for case comparison.
    Creates feature vectors for similarity calculation.
    These values are used by the Clustering & Analysis Layer for comparing cases.
    
    Args:
        case_features: Extracted features dictionary
        
    Returns:
        Dictionary with comparison values/weights added to case_features
    """
    victim_demo = case_features.get('victim_demographics') or {}
    perp_demo = case_features.get('perpetrator_demographics') or {}
    date_range = case_features.get('date_range') or {}
    
    comparison_values = {
        'platform_vector': case_features.get('platforms_used', []),
        'technology_vector': case_features.get('technologies', []),
        'method_vector': case_features.get('communication_methods', []),
        'demographic_vector': {
            'victim_age_range': victim_demo.get('age_range') if isinstance(victim_demo, dict) else None,
            'victim_region': victim_demo.get('region') if isinstance(victim_demo, dict) else None,
            'perp_age_range': perp_demo.get('age_range') if isinstance(perp_demo, dict) else None,
            'perp_region': perp_demo.get('region') if isinstance(perp_demo, dict) else None,
        },
        'temporal_value': date_range.get('start') if isinstance(date_range, dict) else None,
        'topic_vector': case_features.get('case_topics', []),
    }
    
    case_features['comparison_values'] = comparison_values
    return case_features


def extract_date_range(case: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Extract date range from case data."""
    month = case.get('month')
    year = case.get('year')
    
    if month and year:
        from datetime import datetime
        try:
            month_num = datetime.strptime(month, '%B').month
            date_str = f"{year}-{month_num:02d}-01"
            return {'start': date_str, 'end': None}
        except:
            pass
    
    return None


def extract_victim_count(case: Dict[str, Any]) -> Optional[int]:
    """Extract victim count."""
    return None


def extract_victim_demographics(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract victim demographics (anonymized)."""
    return None


def extract_perpetrator_count(case: Dict[str, Any]) -> Optional[int]:
    """Extract perpetrator count."""
    return None


def extract_perpetrator_demographics(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract perpetrator demographics (anonymized)."""
    return None


def extract_relationship(case: Dict[str, Any]) -> Optional[str]:
    """Extract relationship to victim."""
    return None


def extract_previous_conviction(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract previous conviction info."""
    return None


def extract_platforms(case: Dict[str, Any]) -> List[str]:
    """Extract platforms used."""
    return []


def extract_technologies(case: Dict[str, Any]) -> List[str]:
    """Extract technologies used."""
    return []


def extract_communication_methods(case: Dict[str, Any]) -> List[str]:
    """Extract communication methods."""
    return []


def extract_investigation_methods(case: Dict[str, Any]) -> List[str]:
    """Extract investigation methods and teams."""
    return []


def extract_prosecution_outcome(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract prosecution outcome."""
    return None


def extract_severity(case: Dict[str, Any]) -> List[str]:
    """Extract severity indicators."""
    return []


def extract_topics(case: Dict[str, Any]) -> List[str]:
    """Extract case topics."""
    return []



