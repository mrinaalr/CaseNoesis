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


def case_batching(text: str, org_name: str = "case") -> List[Dict[str, Any]]:
    """
    Split text corpus into individual cases by "In [Month]" patterns.
    Looks for patterns like "In January", "In February", etc. to identify case boundaries.
    
    Args:
        text: Large text block from PDF ingestion
        org_name: Organization name prefix for case IDs (e.g., "azicac")
        
    Returns:
        List of case dictionaries, each with 'case_text' and 'month_year'
    """
    cases = []
    
    # Normalize org name (lowercase, remove spaces/special chars)
    org_name = org_name.lower().replace(" ", "_").replace("-", "_")
    
    month_pattern = r'In (January|February|March|April|May|June|July|August|September|October|November|December)'
    
    matches = list(re.finditer(month_pattern, text, re.IGNORECASE))
    
    if not matches:
        from datetime import datetime
        year = str(datetime.now().year)
        return [{'case_text': text, 'month_year': None, 'case_id': f'{org_name}_{year}_unknown_001'}]
    
    # Track cases per year for proper numbering (resets each year)
    year_case_counts = {}
    
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
    Patterns: "infant", "very young", "under 5", "under 9", "produced", "created"
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
    
    # Extract "under X" patterns
    under_pattern = r'under\s+(\d+)'
    under_matches = re.finditer(under_pattern, case_text, re.IGNORECASE)
    for match in under_matches:
        try:
            age = int(match.group(1))
            severity_indicators.append(f'under_{age}')
        except (ValueError, IndexError):
            continue
    
    # Production indicators
    if re.search(r'\b(produced|created|made\s+movies?)\b', case_text, re.IGNORECASE):
        severity_indicators.append('production')
    
    return severity_indicators


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
    
    return topics



