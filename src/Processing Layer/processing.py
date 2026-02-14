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


def clean_urls_from_text(text: str) -> str:
    """
    Remove URLs from case text, specifically patterns like:
    - "https://www.azicac.org/2012-cases-and-arrests/ 7/8 2/14/26, 10:32 AM 2012 Cases and Arrests - AZICAC.ORG"
    - "5/12 2/14/26, 10:37 AM 2011 Cases and Arrests – AZICAC.ORG"
    - "/2011-cases-and-arrests/" (URL path fragments in middle of text)
    
    Removes all text from "http" (or page numbers before it) up to and including "AZICAC.ORG"
    Also removes URL path fragments like "/2011-cases-and-arrests/"
    Preserves the rest of the case text.
    
    Args:
        text: Case text that may contain URLs
        
    Returns:
        Cleaned text with URLs removed
    """
    if not text:
        return text
    
    # Pattern 1: Match from http/https to AZICAC.ORG (case-insensitive)
    # Matches: "https://www.azicac.org/... AZICAC.ORG"
    pattern1 = r'https?://.*?azicac\.org'
    
    # Pattern 2: Match page numbers/date patterns that lead to AZICAC.ORG
    # Matches: "5/12 2/14/26, 10:37 AM 2011 Cases and Arrests – AZICAC.ORG"
    # This matches from page numbers/date all the way to AZICAC.ORG
    pattern2 = r'\d+/\d+\s+\d+/\d+/\d+.*?azicac\.org'
    
    # Pattern 3: Match URL path fragments like "/2011-cases-and-arrests/" or "/2012-cases-and-arrests/"
    # These appear in the middle of case text without http:// prefix
    pattern3 = r'/\d{4}-cases-and-arrests/'
    
    # Pattern 4: Match standalone "azicac.org" or "AZICAC.ORG" (without http://)
    # Matches: "azicac.org" or "AZICAC.ORG" anywhere in text
    pattern4 = r'\bazicac\.org\b'
    
    # Pattern 5: Match any remaining http/https URLs (catch-all cleanup)
    pattern5 = r'https?://[^\s]+'
    
    # Remove patterns in order (most specific first), case-insensitive
    cleaned_text = re.sub(pattern1, '', text, flags=re.IGNORECASE)
    cleaned_text = re.sub(pattern2, '', cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(pattern3, '', cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(pattern4, '', cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(pattern5, '', cleaned_text, flags=re.IGNORECASE)
    
    # Clean up any double spaces or trailing whitespace that might result
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
    cleaned_text = cleaned_text.strip()
    
    return cleaned_text


def case_batching(text: str, org_name: str = "case") -> List[Dict[str, Any]]:
    """
    Split text corpus into individual cases by multiple month/year patterns.
    
    Primary pattern: "In [Month]" (e.g., "In January", "In February")
    Secondary pattern: "[Month] [Year]," (e.g., "July 2012,", "September 2012,")
    
    Args:
        text: Large text block from PDF ingestion
        org_name: Organization name prefix for case IDs (e.g., "azicac")
        
    Returns:
        List of case dictionaries, each with 'case_text' and 'month_year'
    """
    cases = []
    
    # Normalize org name (lowercase, remove spaces/special chars)
    org_name = org_name.lower().replace(" ", "_").replace("-", "_")
    
    months = r'(January|February|March|April|May|June|July|August|September|October|November|December)'
    
    # Primary pattern: "In [Month]" (official method) - "In" must be uppercase
    pattern1 = rf'In {months}'
    
    # Secondary pattern: "[Month] [Year]," (with comma)
    pattern2 = rf'{months}\s+(\d{{4}}),'
    
    all_matches = []
    
    # Find all matches from primary pattern - case-sensitive for "In", case-insensitive for month
    for match in re.finditer(pattern1, text, re.IGNORECASE):
        # Check that "In" is actually uppercase (not "in")
        match_text = text[match.start():match.start()+2]
        if match_text != 'In':
            continue  # Skip if lowercase "in"
        all_matches.append({
            'pos': match.start(),
            'month': match.group(1),
            'year': None,  # Will extract from case text
            'pattern': 'primary'
        })
    
    # Find all matches from secondary pattern (with comma)
    for match in re.finditer(pattern2, text, re.IGNORECASE):
        all_matches.append({
            'pos': match.start(),
            'month': match.group(1),
            'year': match.group(2),
            'pattern': 'secondary_comma'
        })
    
    # Remove duplicates: if positions are close, keep the highest priority pattern
    # Priority: primary > secondary_comma
    # Sort by position first
    all_matches.sort(key=lambda x: x['pos'])
    
    # Deduplicate: prefer higher priority patterns if positions are close
    pattern_priority = {'primary': 2, 'secondary_comma': 1}
    unique_matches = []
    for match in all_matches:
        is_duplicate = False
        for i, existing in enumerate(unique_matches):
            if abs(match['pos'] - existing['pos']) < 15:  # Within 15 chars
                match_priority = pattern_priority.get(match['pattern'], 0)
                existing_priority = pattern_priority.get(existing['pattern'], 0)
                
                # If existing has higher priority, skip this one
                if existing_priority > match_priority:
                    is_duplicate = True
                    break
                # If this has higher priority, replace existing
                elif match_priority > existing_priority:
                    unique_matches[i] = match
                    is_duplicate = True  # Mark as handled
                    break
                # If same priority and same position, skip duplicate
                elif match_priority == existing_priority and match['pos'] == existing['pos']:
                    is_duplicate = True
                    break
        if not is_duplicate:
            unique_matches.append(match)
    
    # Sort again after deduplication
    unique_matches.sort(key=lambda x: x['pos'])
    
    if not unique_matches:
        from datetime import datetime
        year = str(datetime.now().year)
        return [{'case_text': text, 'month_year': None, 'case_id': f'{org_name}_{year}_unknown_001'}]
    
    # Track cases per year for proper numbering (resets each year)
    year_case_counts = {}
    
    for i, match_info in enumerate(unique_matches):
        month = match_info['month']
        start_pos = match_info['pos']
        
        # Determine end position
        if i + 1 < len(unique_matches):
            end_pos = unique_matches[i + 1]['pos']
        else:
            end_pos = len(text)
        
        case_text = text[start_pos:end_pos].strip()
        
        # Clean URLs from case text before processing
        case_text = clean_urls_from_text(case_text)
        
        # Extract year
        if match_info['year']:
            # Year already extracted from pattern
            year = match_info['year']
        else:
            # Extract year from case text - supports any year (2013, 2014, etc.)
            # Look for 4-digit year (1900-2099) in the case text
            year_match = re.search(r'\b(19|20)\d{2}\b', case_text)
            if year_match:
                year = year_match.group(0)
            else:
                # Fallback: use current year if no year found
                from datetime import datetime
                year = str(datetime.now().year)
        
        # Track case number per year (resets each year)
        if year not in year_case_counts:
            year_case_counts[year] = 0
        year_case_counts[year] += 1
        case_number = year_case_counts[year]
        
        case_id = f"{org_name}_{year}_{month.lower()}_{case_number:03d}"
        
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
        
        # Extract org name from source (e.g., "AZICAC" -> "azicac")
        # If source is not available, try to extract from source_file name
        org_name = source.lower() if source and source != 'unknown' else 'case'
        if org_name == 'case' and source_file:
            # Try to extract org name from filename (e.g., "2014 Cases and Arrests – AZICAC.ORG.pdf")
            org_match = re.search(r'([A-Z]+)', source_file)
            if org_match:
                org_name = org_match.group(1).lower()
        
        case_batches = case_batching(extracted_text, org_name=org_name)
        
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
    Based on analysis of actual AZICAC case data (2013-2014).
    
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
    
    # Extract all features
    victim_demo = extract_victim_demographics(raw_case)
    perp_demo = extract_perpetrator_demographics(raw_case)
    evidence_vol = extract_evidence_volume(raw_case)
    prosecution = extract_prosecution_outcome(raw_case)
    investigation = extract_investigation_info(raw_case)
    
    features = {
        'id': raw_case.get('case_id') or raw_case.get('id'),
        'source': raw_case.get('source', 'unknown'),
        'date_range': date_range,
        # Victim context
        'victim_count': extract_victim_count(raw_case),
        'victim_demographics': victim_demo,
        # Perpetrator context
        'perpetrator_age': perp_demo.get('age') if isinstance(perp_demo, dict) else None,
        'perpetrator_registered_sex_offender': perp_demo.get('is_registered') if isinstance(perp_demo, dict) else False,
        'relationship_to_victim': extract_relationship(raw_case),
        'previous_conviction': extract_previous_conviction(raw_case),
        # Technology & platforms
        'platforms_used': extract_platforms(raw_case),
        # Law enforcement
        'investigation_type': investigation.get('type') if isinstance(investigation, dict) else None,
        'agencies_involved': investigation.get('agencies', []) if isinstance(investigation, dict) else [],
        'prosecution_outcome': prosecution,
        # Evidence & content
        'evidence_volume': evidence_vol,
        # Content classification
        'severity_indicators': extract_severity(raw_case),
        'case_topics': extract_topics(raw_case),
        'severity_phrases': extract_severity_phrases(raw_case),  # Key severity phrases
        # Raw data
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
    date_range = case_features.get('date_range') or {}
    evidence_vol = case_features.get('evidence_volume') or {}
    
    # Calculate victim age range from ages list
    victim_age_range = None
    if isinstance(victim_demo, dict):
        ages = victim_demo.get('ages', [])
        if ages:
            victim_age_range = {'min': min(ages), 'max': max(ages)}
        elif victim_demo.get('age_range'):
            victim_age_range = victim_demo.get('age_range')
    
    comparison_values = {
        'platform_vector': case_features.get('platforms_used', []),
        'demographic_vector': {
            'victim_age_range': victim_age_range,
            'victim_count': case_features.get('victim_count'),
            'perpetrator_age': case_features.get('perpetrator_age'),
            'perpetrator_registered': case_features.get('perpetrator_registered_sex_offender', False),
        },
        'relationship_vector': [case_features.get('relationship_to_victim')] if case_features.get('relationship_to_victim') else [],
        'investigation_vector': {
            'type': case_features.get('investigation_type'),
            'agencies': case_features.get('agencies_involved', []),
        },
        'evidence_vector': {
            'images': evidence_vol.get('images') if isinstance(evidence_vol, dict) else None,
            'videos': evidence_vol.get('videos') if isinstance(evidence_vol, dict) else None,
            'storage_size': evidence_vol.get('storage_size') if isinstance(evidence_vol, dict) else None,
        },
        'temporal_value': date_range.get('start') if isinstance(date_range, dict) else None,
        'topic_vector': case_features.get('case_topics', []),
        'severity_vector': case_features.get('severity_indicators', []),
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
    """
    Extract victim count when explicitly mentioned.
    Pattern: "X victims", "X children", "X minors", "at least X children"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    # Pattern: "2 victims", "4 victims", "at least 15 children"
    patterns = [
        r'(\d+)\s+(victim|victims)',
        r'(\d+)\s+(child|children|minor|minors)',
        r'at\s+least\s+(\d+)\s+(child|children)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, case_text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                continue
    
    return None


def extract_victim_demographics(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract victim demographics: ages, age ranges, gender.
    Patterns: "7 years old", "ages 4 thru 10", "13 year old female", "4 year old boy"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    demographics = {
        'ages': [],
        'age_range': None,
        'gender': None
    }
    
    # Extract individual ages: "7 years old", "13 year old"
    age_pattern = r'(\d+)\s+year\s+old'
    age_matches = re.finditer(age_pattern, case_text, re.IGNORECASE)
    for match in age_matches:
        try:
            age = int(match.group(1))
            # Check if it's a victim age (not perpetrator - perpetrators usually have "X year old man/woman")
            context = case_text[max(0, match.start()-30):match.end()+10].lower()
            if 'victim' in context or 'child' in context or ('year old' in context and 'man' not in context and 'woman' not in context):
                demographics['ages'].append(age)
        except (ValueError, IndexError):
            continue
    
    # Extract age ranges: "ages 4 thru 10"
    range_pattern = r'ages?\s+(\d+)\s+thru\s+(\d+)'
    range_match = re.search(range_pattern, case_text, re.IGNORECASE)
    if range_match:
        try:
            min_age = int(range_match.group(1))
            max_age = int(range_match.group(2))
            demographics['age_range'] = {'min': min_age, 'max': max_age}
        except (ValueError, IndexError):
            pass
    
    # Extract gender: "female", "boy", "girl"
    if re.search(r'\b(female|girl)\b', case_text, re.IGNORECASE):
        demographics['gender'] = 'female'
    elif re.search(r'\b(male|boy)\b', case_text, re.IGNORECASE):
        demographics['gender'] = 'male'
    
    # Remove duplicates and sort ages
    demographics['ages'] = sorted(list(set(demographics['ages'])))
    
    return demographics if demographics['ages'] or demographics['age_range'] or demographics['gender'] else None


def extract_perpetrator_demographics(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract perpetrator demographics: age, registration status.
    Pattern: "62 year old man", "30 year old man", "registered sex offender"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    demographics = {
        'age': None,
        'is_registered': False
    }
    
    # Extract age: "X year old man/woman"
    age_pattern = r'(\d+)\s+year\s+old\s+(man|woman|male|female)'
    age_match = re.search(age_pattern, case_text, re.IGNORECASE)
    if age_match:
        try:
            demographics['age'] = int(age_match.group(1))
        except (ValueError, IndexError):
            pass
    
    # Check for registered sex offender
    if re.search(r'registered\s+sex\s+offender', case_text, re.IGNORECASE):
        demographics['is_registered'] = True
    
    return demographics if demographics['age'] is not None or demographics['is_registered'] else None


def extract_relationship(case: Dict[str, Any]) -> Optional[str]:
    """
    Extract relationship to victim.
    Patterns: "biological father", "father", "mother", "brother", "sister", "uncle", "aunt", "cousin", "stranger", "teacher"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    # Relationship patterns (in order of specificity)
    relationships = [
        (r'biological\s+(father|mother|parent)', ['biological_father', 'biological_mother', 'biological_parent']),
        (r'\b(father|mother|parent)\b', ['father', 'mother', 'parent']),
        (r'\b(brother|sister|sibling)\b', ['brother', 'sister', 'sibling']),
        (r'\b(uncle|aunt|cousin)\b', ['uncle', 'aunt', 'cousin']),
        (r'\b(teacher|stranger)\b', ['teacher', 'stranger']),
    ]
    
    for pattern, rel_list in relationships:
        match = re.search(pattern, case_text, re.IGNORECASE)
        if match:
            matched_text = match.group(0).lower()
            # Map to standardized relationship
            for rel in rel_list:
                if rel.replace('_', ' ') in matched_text or rel in matched_text:
                    return rel
            # Fallback: return the matched group
            return match.group(1).lower() if match.lastindex else matched_text
    
    return None


def extract_previous_conviction(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract previous conviction information.
    Patterns: "registered sex offender", "arrested when he was 16 years old"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    prev_conviction = {
        'is_registered': False,
        'age_at_first_offense': None
    }
    
    # Check for registered sex offender
    if re.search(r'registered\s+sex\s+offender', case_text, re.IGNORECASE):
        prev_conviction['is_registered'] = True
    
    # Extract age at first offense: "arrested when he was 16 years old"
    age_pattern = r'arrested\s+when\s+(he|she|they)\s+was\s+(\d+)\s+years?\s+old'
    age_match = re.search(age_pattern, case_text, re.IGNORECASE)
    if age_match:
        try:
            prev_conviction['age_at_first_offense'] = int(age_match.group(2))
        except (ValueError, IndexError):
            pass
    
    return prev_conviction if prev_conviction['is_registered'] or prev_conviction['age_at_first_offense'] else None


def extract_platforms(case: Dict[str, Any]) -> List[str]:
    """
    Extract platforms and online methods used.
    Patterns: "Facebook", "Instagram", "Snapchat", "Discord", "WhatsApp", "online", "chat"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return []
    
    platforms = []
    platform_patterns = {
        'Facebook': r'\bFacebook\b',
        'Instagram': r'\bInstagram\b',
        'Snapchat': r'\bSnapchat\b',
        'Discord': r'\bDiscord\b',
        'WhatsApp': r'\bWhatsApp\b',
        'online': r'\bonline\b',
        'chat': r'\bchat(ting|ted|s)?\b',
        'social media': r'\bsocial\s+media\b',
    }
    
    for platform, pattern in platform_patterns.items():
        if re.search(pattern, case_text, re.IGNORECASE):
            platforms.append(platform)
    
    return platforms


def extract_evidence_volume(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract evidence volume: images, videos, storage size, messages.
    Patterns: "over 600 images", "1.5TB", "200,000 images", "10,000 chat messages"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    evidence = {
        'images': None,
        'videos': None,
        'storage_size': None,
        'messages': None
    }
    
    # Extract image counts: "over 600 images", "200,000 images", "over 1,000 images"
    image_patterns = [
        r'(over|more\s+than|approximately)?\s*(\d{1,3}(?:[,\.]\d{3})*)\s+images?',
        r'(\d{1,3}(?:[,\.]\d{3})*)\s+pictures?',
    ]
    for pattern in image_patterns:
        match = re.search(pattern, case_text, re.IGNORECASE)
        if match:
            try:
                num_str = match.group(2) if match.lastindex >= 2 else match.group(1)
                num_str = num_str.replace(',', '').replace('.', '')
                evidence['images'] = int(num_str)
                break
            except (ValueError, IndexError, AttributeError):
                continue
    
    # Extract video counts: "videos", "movies"
    video_patterns = [
        r'(\d{1,3}(?:[,\.]\d{3})*)\s+videos?',
        r'(\d{1,3}(?:[,\.]\d{3})*)\s+movies?',
    ]
    for pattern in video_patterns:
        match = re.search(pattern, case_text, re.IGNORECASE)
        if match:
            try:
                num_str = match.group(1).replace(',', '').replace('.', '')
                evidence['videos'] = int(num_str)
                break
            except (ValueError, IndexError):
                continue
    
    # Extract storage size: "1.5TB", "10GB", "500MB"
    storage_pattern = r'(\d+\.?\d*)\s*(TB|GB|MB)'
    storage_match = re.search(storage_pattern, case_text, re.IGNORECASE)
    if storage_match:
        try:
            size = storage_match.group(1)
            unit = storage_match.group(2).upper()
            evidence['storage_size'] = f"{size}{unit}"
        except (ValueError, IndexError):
            pass
    
    # Extract message counts: "10,000 chat messages"
    message_pattern = r'(\d{1,3}(?:[,\.]\d{3})*)\s+(chat\s+)?messages?'
    message_match = re.search(message_pattern, case_text, re.IGNORECASE)
    if message_match:
        try:
            num_str = message_match.group(1).replace(',', '').replace('.', '')
            evidence['messages'] = int(num_str)
        except (ValueError, IndexError):
            pass
    
    return evidence if any(evidence.values()) else None


def extract_investigation_info(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract investigation type and agencies involved.
    Types: "proactive", "reactive", "online", "undercover"
    Agencies: "AZICAC", "FBI", "Phoenix Police", "ICAC", "HSI", "MCSO", "DPS"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    investigation = {
        'type': None,
        'agencies': []
    }
    
    # Extract investigation type
    type_patterns = {
        'proactive': r'proactive\s+investigation',
        'reactive': r'reactive\s+investigation',
        'online': r'online\s+investigation',
        'undercover': r'undercover\s+(operation|investigation)',
    }
    
    for inv_type, pattern in type_patterns.items():
        if re.search(pattern, case_text, re.IGNORECASE):
            investigation['type'] = inv_type
            break
    
    # Extract agencies
    agencies = [
        'AZICAC', 'FBI', 'Phoenix Police', 'ICAC', 'HSI', 'MCSO', 'DPS',
        'Maricopa County', 'Las Vegas', 'Colorado', 'Texas', 'California',
        'Australian Federal Police', 'Chandler Police', 'Buckeye'
    ]
    
    for agency in agencies:
        if re.search(r'\b' + re.escape(agency) + r'\b', case_text, re.IGNORECASE):
            investigation['agencies'].append(agency)
    
    return investigation if investigation['type'] or investigation['agencies'] else None


def extract_prosecution_outcome(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract prosecution outcome: charges, booking status, jail.
    Patterns: "10 counts of sexual exploitation of a minor", "booked", "Maricopa County Jail"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    outcome = {
        'charges': [],
        'booking_status': None,
        'jail': None
    }
    
    # Extract charges: "10 counts of sexual exploitation of a minor", "32 counts Dangerous Crimes Against Children"
    charge_pattern = r'(\d+)\s+counts?\s+of\s+([^,\.]+?)(?:,|\.|$)'
    charge_matches = re.finditer(charge_pattern, case_text, re.IGNORECASE)
    for match in charge_matches:
        try:
            count = int(match.group(1))
            charge = match.group(2).strip()
            outcome['charges'].append({'count': count, 'charge': charge})
        except (ValueError, IndexError):
            continue
    
    # Extract booking status: "booked", "arrested", "charged"
    if re.search(r'\bbooked\b', case_text, re.IGNORECASE):
        outcome['booking_status'] = 'booked'
    elif re.search(r'\barrested\b', case_text, re.IGNORECASE):
        outcome['booking_status'] = 'arrested'
    elif re.search(r'\bcharged\b', case_text, re.IGNORECASE):
        outcome['booking_status'] = 'charged'
    
    # Extract jail: "Maricopa County Jail", "non-bondable"
    jail_pattern = r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+County\s+Jail)'
    jail_match = re.search(jail_pattern, case_text)
    if jail_match:
        outcome['jail'] = jail_match.group(1)
    
    if re.search(r'non-bondable', case_text, re.IGNORECASE):
        outcome['jail'] = (outcome['jail'] or '') + ' (non-bondable)'
    
    return outcome if outcome['charges'] or outcome['booking_status'] or outcome['jail'] else None


def extract_severity(case: Dict[str, Any]) -> List[str]:
    """
    Extract severity indicators.
    Patterns: "infant", "very young", "under X" (where X < 10 merged to "under_10"), "produced", "created"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return []
    
    severity_indicators = []
    
    # Age-based severity
    if re.search(r'\binfants?\b', case_text, re.IGNORECASE):
        severity_indicators.append('infant')
    if re.search(r'very\s+young\s+children', case_text, re.IGNORECASE):
        severity_indicators.append('very_young')
    
    # Extract "under X" patterns - merge all under 10 into "under_10"
    under_pattern = r'under\s+(\d+)'
    under_matches = re.finditer(under_pattern, case_text, re.IGNORECASE)
    has_under_10 = False
    for match in under_matches:
        try:
            age = int(match.group(1))
            if age < 10:
                has_under_10 = True
            else:
                # Keep ages 10 and above as separate indicators
                severity_indicators.append(f'under_{age}')
        except (ValueError, IndexError):
            continue
    
    if has_under_10:
        severity_indicators.append('under_10')
    
    # Production indicators
    if re.search(r'\b(produced|created|made\s+movies?)\b', case_text, re.IGNORECASE):
        severity_indicators.append('production')
    
    # Rape indicators - severe sexual violence
    if re.search(r'\b(rape|raped|raping)\b', case_text, re.IGNORECASE):
        severity_indicators.append('rape')
    
    return list(set(severity_indicators))  # Remove duplicates


def extract_topics(case: Dict[str, Any]) -> List[str]:
    """
    Extract case topics/themes (semantic extraction - placeholder for KeyBERT).
    Topics: production, possession, international, multi_state, hands_on, online_only, family, stranger
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return []
    
    topics = []
    
    # Production vs possession
    if re.search(r'\b(produced|created|made|molest|molesting)\b', case_text, re.IGNORECASE):
        topics.append('production')
    if re.search(r'\b(trading|downloading|possessing|collecting)\b', case_text, re.IGNORECASE):
        topics.append('possession')
    
    # International cooperation
    if re.search(r'\b(Australia|Philippines|Japan|international|overseas)\b', case_text, re.IGNORECASE):
        topics.append('international')
    
    # Multi-state
    states = ['Colorado', 'Texas', 'California', 'Las Vegas', 'Arizona']
    state_count = sum(1 for state in states if re.search(r'\b' + re.escape(state) + r'\b', case_text, re.IGNORECASE))
    if state_count > 1:
        topics.append('multi_state')
    
    # Hands-on vs online-only
    if re.search(r'\b(molest|molesting|hands?\s+on|sexually\s+abused|sexually\s+assaulted)\b', case_text, re.IGNORECASE):
        topics.append('hands_on')
    elif re.search(r'\b(online|chat|trading\s+images?)\b', case_text, re.IGNORECASE) and 'hands_on' not in topics:
        topics.append('online_only')
    
    # Family vs stranger
    if re.search(r'\b(father|mother|parent|brother|sister|uncle|aunt|cousin|biological)\b', case_text, re.IGNORECASE):
        topics.append('family')
    elif re.search(r'\bstranger\b', case_text, re.IGNORECASE):
        topics.append('stranger')
    
    # Pornography/material type indicators
    if re.search(r'\b(porn|pornography|pornographic)\b', case_text, re.IGNORECASE):
        topics.append('pornography')
    
    return list(set(topics))  # Remove duplicates


def extract_severity_phrases(case: Dict[str, Any]) -> List[str]:
    """
    Extract key severity phrases from case text that indicate high severity.
    These are non-traditional indicators that show escalation, ongoing abuse, or dangerous behavior.
    
    Phrases: "dangerous", "stated", "told", "continue", "attacked", "out of control"
    
    Args:
        case: Case dictionary with 'case_text'
        
    Returns:
        List of severity phrases found in the case text
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return []
    
    severity_phrases = []
    case_text_lower = case_text.lower()
    
    # Key severity phrases with context awareness
    phrase_patterns = {
        'dangerous': r'\bdangerous\b',
        'stated': r'\b(stated|states|stating)\b',  # Victim statements/disclosures
        'told': r'\b(told|tells|telling)\b',  # Victim disclosures
        'continue': r'\b(continue|continued|continuing)\b',  # Ongoing abuse
        'attacked': r'\b(attacked|attack|attacking)\b',  # Physical violence
        'out_of_control': r'\bout\s+of\s+control\b',  # Escalation indicator
    }
    
    for phrase_key, pattern in phrase_patterns.items():
        if re.search(pattern, case_text_lower, re.IGNORECASE):
            severity_phrases.append(phrase_key)
    
    return list(set(severity_phrases))  # Remove duplicates



