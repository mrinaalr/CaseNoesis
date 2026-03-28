"""
Processing Layer

Purpose: Extract features, assign comparison values, fill in basic schema, and prepare cases for clustering and analysis.

Design Ideas from Architecture:
- Select data to keep
- Assign cases values (for compare)
- Fill in case schema for each case according to Case Entity Schema:
  - id, source, date_range
  - Case Context (anonymized): victim_count, case_demographics
  - Perpetrator Context (anonymized): perpetrator_count, perpetrator_demographics, relationship_to_victim, previous_conviction
  - Technology & Methods: platforms_used, technologies, communication_methods
  - Law Enforcement: prosecution_outcome (agencies/orgs in extracted_features)
  - Content Classification: severity_indicators, case_topics
  - Raw/Original Data: raw_data, extracted_features
  - Metadata: created_at, updated_at
"""

import pandas as pd
import re
from typing import Dict, List, Any, Optional

# Import batching functions from shared batching module
import sys
from pathlib import Path
_batching_path = Path(__file__).parent.parent / "batching.py"
import importlib.util
spec = importlib.util.spec_from_file_location("batching", _batching_path)
batching = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batching)

# Import batching functions
case_batching = batching.case_batching
clean_artifacts_from_text = batching.clean_artifacts_from_text
clean_urls_from_text = batching.clean_artifacts_from_text  # Backward compatibility alias


# case_batching and all batching functions are now imported from batching module
# Removed: case_batching, _batch_azicac_cases, _batch_ncmec_cases, _batch_ncmec_2024_cases, _batch_ncmec_media_cases
# These are now in ../batching.py

# Production topic: CSAM / explicit media-creation phrasing only. Bare "created" or "produced"
# are excluded (e.g. "created new program", "produced evidence"). Optional words allowed
# between verb and object (e.g. "created bad videos").
_PRODUCTION_TOPIC_RE = re.compile(
    r"""
    \bproduction\s+of\b
    | \bminor\s+production\b
    | \bproduced\s+(?:\S+\s+){0,5}(?:movies?|videos?|images?|photos?|child|csam|porn(?:ography)?|material)\b
    | \bcreated\s+(?:\S+\s+){0,5}(?:movies?|videos?|images?|photos?|child|csam|porn(?:ography)?)\b
    | \bmade\s+(?:\S+\s+){0,5}(?:movies?|videos?|images?|photos?)\b
    | \btook\s+(?:\S+\s+){0,5}photos?\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


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
        
        case_batches = case_batching(extracted_text, org_name=org_name, source=source, source_file=source_file)
        
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
            # Copy any additional fields from batch (e.g., 'state' for NCMEC cases)
            if 'state' in case_batch:
                raw_case['state'] = case_batch['state']
            
            case_features = extract_features(raw_case)
            
            case_with_values = assign_comparison_values(case_features)
            
            from datetime import datetime
            # Use same timestamp for both created_at and updated_at for new cases
            timestamp = datetime.now().isoformat()
            case_with_values['created_at'] = timestamp
            case_with_values['updated_at'] = timestamp
            
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
    case_demo = extract_case_demographics(raw_case)
    perp_demo = extract_perpetrator_demographics(raw_case)
    evidence_vol = extract_evidence_volume(raw_case)
    prosecution = extract_prosecution_outcome(raw_case)
    investigation = extract_investigation_info(raw_case)
    
    features = {
        'id': raw_case.get('case_id') or raw_case.get('id'),
        'source': raw_case.get('source', 'unknown'),
        'date_range': date_range,
        # Case context
        'victim_count': extract_victim_count(raw_case),
        'case_demographics': case_demo,
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
    case_demo = case_features.get('case_demographics') or {}
    date_range = case_features.get('date_range') or {}
    evidence_vol = case_features.get('evidence_volume') or {}
    
    # Calculate case age range from ages list
    case_age_range = None
    if isinstance(case_demo, dict):
        ages = case_demo.get('ages', [])
        if ages:
            case_age_range = {'min': min(ages), 'max': max(ages)}
        elif case_demo.get('age_range'):
            case_age_range = case_demo.get('age_range')
    
    # Handle perpetrator_age (can be single int or list)
    perpetrator_age = case_features.get('perpetrator_age')
    multiple_perpetrators = False
    if isinstance(perpetrator_age, list):
        multiple_perpetrators = len(perpetrator_age) > 1
    elif perpetrator_age is not None:
        # Convert single int to list for consistency
        perpetrator_age = [perpetrator_age]
    
    # Add multiple_perpetrators to severity if applicable (gives more weight)
    severity_vector = case_features.get('severity_indicators', [])
    if not isinstance(severity_vector, list):
        severity_vector = []
    if multiple_perpetrators and 'multiple_perpetrators' not in severity_vector:
        severity_vector = severity_vector.copy()
        severity_vector.append('multiple_perpetrators')
        # Update the case_features severity_indicators field
        case_features['severity_indicators'] = severity_vector
    
    comparison_values = {
        'platform_vector': case_features.get('platforms_used', []),
        'demographic_vector': {
            'case_age_range': case_age_range,
            'victim_count': case_features.get('victim_count'),
            'perpetrator_age': perpetrator_age,  # Now always a list (or None)
            'multiple_perpetrators': multiple_perpetrators,  # Flag for clustering
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
        'severity_vector': severity_vector,  # Includes multiple_perpetrators flag
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
        except (ValueError, AttributeError):
            # Invalid month name or year format
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


def extract_case_demographics(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract case demographics: ages, age ranges, gender (all ages from case, not just victim-specific).
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
            # Victims must be <= 17 (18+ are perpetrators)
            if age >= 18:
                continue
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
            # Cap max age at 17 for victims (18+ are perpetrators)
            if max_age >= 18:
                max_age = 17
            if min_age <= max_age:
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
    Patterns: 
    - "25 year old Scottsdale man" (allows location between "old" and "man")
    - "21 year old Goodyear, AZ resident" (supports "resident" as well as man/woman/male/female)
    - "30 year old man" (simple case)
    - "registered sex offender"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None
    
    demographics = {
        'age': None,
        'is_registered': False
    }
    
    # Extract age: "X year old [optional location] man/woman/male/female/resident"
    # Allows for patterns like "25 year old Scottsdale man" or "21 year old Goodyear, AZ resident"
    age_pattern = r'(\d+)\s+year\s+old\s+(?:\w+(?:\s*,\s*\w+)*\s+)?(man|woman|male|female|resident)'
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
    Patterns: "father", "mother", "brother", "sister", "uncle", "aunt", "cousin", "stranger", "teacher"
    Defaults to "stranger" if no relationship is found (non-family, non-teacher cases).
    Note: "biological father" is extracted as "father" (same as "mother").
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return 'stranger'  # Default to stranger if no text
    
    # Check for family relationships (father, mother, parent)
    # Note: "biological father" is extracted as "father" (removed biological prefix)
    if re.search(r'\bfather\b', case_text, re.IGNORECASE):
        return 'father'
    if re.search(r'\bmother\b', case_text, re.IGNORECASE):
        return 'mother'
    if re.search(r'\bparent\b', case_text, re.IGNORECASE):
        return 'parent'
    
    # Check for siblings
    if re.search(r'\bbrother\b', case_text, re.IGNORECASE):
        return 'brother'
    if re.search(r'\bsister\b', case_text, re.IGNORECASE):
        return 'sister'
    if re.search(r'\bsibling\b', case_text, re.IGNORECASE):
        return 'sibling'
    
    # Check for extended family
    if re.search(r'\buncle\b', case_text, re.IGNORECASE):
        return 'uncle'
    if re.search(r'\baunt\b', case_text, re.IGNORECASE):
        return 'aunt'
    if re.search(r'\bcousin\b', case_text, re.IGNORECASE):
        return 'cousin'
    
    # Check for teacher
    if re.search(r'\bteacher\b', case_text, re.IGNORECASE):
        return 'teacher'
    
    # Check for stranger (explicit mention)
    if re.search(r'\bstranger\b', case_text, re.IGNORECASE):
        return 'stranger'
    
    # Default to stranger if no relationship found
    # (If it's not family or teacher, it's likely a stranger)
    return 'stranger'


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
    
    # Gate: need narrative signal — "investigation" or "operation(s)" (covers e.g. "proactive operation").
    has_inv_signal = (
        re.search(r'\binvestigation\b', case_text, re.IGNORECASE)
        or re.search(r'\boperations?\b', case_text, re.IGNORECASE)
    )
    if not has_inv_signal:
        return None

    # Now check for specific types.
    # IMPORTANT: Check "undercover" FIRST because it's more specific and might be missed
    # if "proactive" is checked first (e.g., "proactive undercover investigation").
    # Patterns allow optional words (including hyphens) between type and "investigation",
    # e.g., "proactive joint investigation", "proactive Internet investigation",
    # "reactive multi-agency investigation".
    type_patterns = {
        "undercover": r'\bunder\s*cover\b|\bundercover\b(?:\s+(?:\S+\s+)*(?:operation|operations|investigation|detective[s]?))?',
        "proactive": r'\bproactive\b\s+(?:\S+\s+)*(?:investigation|operation[s]?)',
        "reactive": r'\breactive\b\s+(?:\S+\s+)*(?:investigation|operation[s]?)',
        "online": r'\bonline\b\s+(?:\S+\s+)*(?:investigation|operation[s]?)',
    }
    
    for inv_type, pattern in type_patterns.items():
        if re.search(pattern, case_text, re.IGNORECASE):
            investigation['type'] = inv_type
            break
    
    # If no subtype phrase matched, set to "unknown"
    if not investigation['type']:
        investigation['type'] = 'unknown'
    
    # Extract agencies
    agencies = [
        'AZICAC', 'FBI', 'Phoenix Police', 'ICAC', 'HSI', 'MCSO', 'DPS',
        'Maricopa County', 'Las Vegas', 'Colorado', 'Texas', 'California',
        'Australian Federal Police', 'Chandler Police', 'Buckeye'
    ]
    
    for agency in agencies:
        if re.search(r'\b' + re.escape(agency) + r'\b', case_text, re.IGNORECASE):
            investigation['agencies'].append(agency)
    
    return investigation


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
    Patterns: "infant", "very young", "under X" (where X < 12 merged to "under_12"), 
    "physical_abuse", "rape"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return []
    
    severity_indicators = []
    
    # Age-based severity
    if re.search(r'\binfants?\b', case_text, re.IGNORECASE):
        severity_indicators.append('infant')
    if re.search(r'very\s+young', case_text, re.IGNORECASE):
        severity_indicators.append('very_young')
    
    # Extract "under X" patterns - only keep "under_12" (12 and younger only)
    # Remove all other "under_X" indicators (under_13, under_14, under_15, under_16, under_17, under_18, under_40, under_311, etc.)
    under_pattern = r'under\s+(\d+)'
    under_matches = re.finditer(under_pattern, case_text, re.IGNORECASE)
    has_under_12 = False
    for match in under_matches:
        try:
            age = int(match.group(1))
            if age <= 12:
                # Only keep ages 12 and younger as "under_12"
                has_under_12 = True
            # Don't add any other "under_X" indicators - they are removed
        except (ValueError, IndexError):
            continue
    
    # Extract "X year old" patterns - check if age < 12
    age_pattern = r'(\d+)\s+year\s+old'
    age_matches = re.finditer(age_pattern, case_text, re.IGNORECASE)
    for match in age_matches:
        try:
            age = int(match.group(1))
            if age < 12:
                has_under_12 = True
        except (ValueError, IndexError):
            continue
    
    # Extract "age X" or "aged X" patterns - check if age < 12
    age_context_pattern = r'\b(age|aged)\s+(\d+)'
    age_context_matches = re.finditer(age_context_pattern, case_text, re.IGNORECASE)
    for match in age_context_matches:
        try:
            age = int(match.group(2))
            if age < 12:
                has_under_12 = True
        except (ValueError, IndexError):
            continue
    
    if has_under_12:
        severity_indicators.append('under_12')
    
    # Sexual abuse indicators - severe sexual violence (includes rape, assault, etc.)
    if re.search(r'\b(rape|raped|raping|sexual\s+assault|sexually\s+assaulted|sexual\s+abuse|sexually\s+abused|molest|molested|molesting)\b', case_text, re.IGNORECASE):
        severity_indicators.append('sexual_abuse')
    
    return list(set(severity_indicators))  # Remove duplicates


def extract_topics(case: Dict[str, Any]) -> List[str]:
    """
    Extract case topics/themes using pattern-based matching.
    Topics: production, possession, international, multi_state, hands_on, online_only, family, stranger, pornography

    Production requires phrase-level cues (e.g. "production of", "minor production", "created … videos",
    "produced child …"); bare "created"/"produced" alone do not tag production.

    Note: physical_abuse is extracted as a severity indicator, not a topic, to avoid redundancy with hands_on.
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return []
    
    topics = []
    
    # Production vs possession (see _PRODUCTION_TOPIC_RE)
    if _PRODUCTION_TOPIC_RE.search(case_text):
        topics.append('production')
    if re.search(r'\b(trading|downloading|possessing|collecting|possessed|traded|possession|dissemination)\b', case_text, re.IGNORECASE):
        topics.append('possession')
    
    # International cooperation
    if re.search(r'\b(Australia|Philippines|Japan|India|Thailand|international|overseas)\b', case_text, re.IGNORECASE):
        topics.append('international')
    
    # Multi-state
    states = ['Colorado', 'Texas', 'California', 'Las Vegas', 'Arizona', 'Florida', 'New York', 'Ohio', 'Pennsylvania', 'Virginia', 'Washington', 'Oregon', 'Washington DC', 'Maryland', 'Massachusetts', 'New Jersey', 'New Mexico', 'New Hampshire', 'Rhode Island', 'Connecticut', 'Delaware', 'Maine', 'Michigan', 'Minnesota', 'Missouri', 'Nebraska', 'Nevada', 'North Carolina', 'North Dakota', 'South Carolina', 'South Dakota', 'Tennessee', 'Utah', 'Vermont', 'Wisconsin', 'Wyoming']
    state_count = sum(1 for state in states if re.search(r'\b' + re.escape(state) + r'\b', case_text, re.IGNORECASE))
    if state_count > 1:
        topics.append('multi_state')
    
    # Hands-on vs online-only
    # Check for sexual abuse first (excludes from online_only)
    has_sexual_abuse = re.search(r'\b(rape|raped|raping|sexual\s+assault|sexually\s+assaulted|sexual\s+abuse|sexually\s+abused|molest|molested|molesting)\b', case_text, re.IGNORECASE)
    
    if re.search(r'\b(molest|molesting|hands?\s+on|sexually\s+abused|sexually\s+assaulted)\b', case_text, re.IGNORECASE):
        topics.append('hands_on')
    elif re.search(r'\b(online|chat|trading\s+images?)\b', case_text, re.IGNORECASE) and 'hands_on' not in topics and not has_sexual_abuse:
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
        'continue': r'\b(continued)\b',  # Ongoing abuse
        'attacked': r'\b(attacked|attack|attacking)\b',  # Physical violence
        'out_of_control': r'\bout\s+of\s+control\b',  # Escalation indicator
    }
    
    for phrase_key, pattern in phrase_patterns.items():
        if re.search(pattern, case_text_lower, re.IGNORECASE):
            severity_phrases.append(phrase_key)
    
    return list(set(severity_phrases))  # Remove duplicates



