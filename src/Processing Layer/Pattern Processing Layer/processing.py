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
  - Technology & Methods: platforms_used (column; includes Gen AI tool); investigation_technology,
    anonymization_network, p2p_clients (in extracted_features JSON)
  - Content Classification: case_topics includes ``ai_csam`` (AI-generated / synthetic CSAM product),
    ``sextortion`` (regex: sextort*, sexual extortion, related blackmail/threat phrasing)
  - Law Enforcement: prosecution_outcome (agencies/orgs in extracted_features)
  - Content Classification: severity_indicators, case_topics
  - Raw/Original Data: raw_data, extracted_features
  - Metadata: created_at, updated_at
"""

import pandas as pd
import re
from typing import Any, Dict, List, Optional, Tuple

# Import batching functions from shared batching module
import sys
from pathlib import Path
_batching_path = Path(__file__).parent.parent / "batching.py"
import importlib.util
spec = importlib.util.spec_from_file_location("batching", _batching_path)
batching = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batching)
try_append_source_url_continuation = batching.try_append_source_url_continuation
consume_same_line_slug_after_url = batching.consume_same_line_slug_after_url

# Import batching functions
case_batching = batching.case_batching
clean_artifacts_from_text = batching.clean_artifacts_from_text
clean_urls_from_text = batching.clean_artifacts_from_text  # Backward compatibility alias


def _extract_source_url(case_text: str) -> str:
    """Extract URL only from `Source: <url>` lines."""
    if not isinstance(case_text, str) or not case_text:
        return ""
    lines = case_text.splitlines()
    break_re = re.compile(r"^(?:[A-Za-z][A-Za-z ]{0,40}:|Case\s+\d+\s*:)", re.IGNORECASE)
    for i, line in enumerate(lines):
        m = re.match(r"^\s*Source:\s*(https?://\S*)", line, flags=re.IGNORECASE)
        if not m:
            continue
        url = m.group(1).strip()
        spaced_slug_segments = 0
        extra, add = consume_same_line_slug_after_url(url, line[m.end() :])
        url = extra
        spaced_slug_segments += add
        j = i + 1
        while j < len(lines):
            nxt = lines[j].strip()
            if not nxt or break_re.match(nxt):
                break
            if nxt.lower().startswith("http://") or nxt.lower().startswith("https://"):
                break
            tup = try_append_source_url_continuation(url, nxt, spaced_slug_segments)
            if tup is None:
                break
            frag, is_spaced = tup
            url += frag
            if is_spaced:
                spaced_slug_segments += 1
            j += 1
            if url.lower().endswith(".pdf"):
                break
        return url.rstrip('.,);]')
    return ""


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
    | \bproduced\s+(?:\S+\s+){0,5}(?:movies?|videos?|images?|photos?|child|csam|material|child\s+porn(?:ography)?|child\s+sexual\s+abuse\s+material)\b
    | \bcreated\s+(?:\S+\s+){0,5}(?:movies?|videos?|images?|photos?|child|csam|child\s+porn(?:ography)?|child\s+sexual\s+abuse\s+material)\b
    | \bmade\s+(?:\S+\s+){0,5}(?:movies?|videos?|images?|photos?)\b
    | \btook\s+(?:\S+\s+){0,5}photos?\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# CSAM material (topic key: ``csam``). Matches common legal/report phrasing only—not bare "porn"/"pornography".
_CSAM_TOPIC_RE = re.compile(
    r"""
    \bcsam\b
    | \bchild\s+sexual\s+abuse\s+material\b
    | \bchild\s+pornography\b
    | \bchild\s+pornographic\b
    | \bchild\s+porn\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

from ai_extraction_patterns import (
    AI_CSAM_IMPLIES_TOOL_RE,
    AI_CSAM_SEMANTIC_THRESHOLD,
    AI_CSAM_TOPIC_RE,
    GEN_AI_TOOL_RE,
    SEXTORTION_TOPIC_RE,
)

_AI_CSAM_TOPIC_RE = AI_CSAM_TOPIC_RE
_GEN_AI_TOOL_RE = GEN_AI_TOOL_RE
_AI_CSAM_IMPLIES_TOOL_RE = AI_CSAM_IMPLIES_TOOL_RE


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
        source_url = row.get('source_url')
        
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
                'source_file': source_file,
            }
            if isinstance(source_url, str) and source_url.strip():
                raw_case['source_url'] = source_url.strip()
            # Copy any additional fields from batch (e.g., 'state' for NCMEC, 'source_url' for SVICAC)
            if 'state' in case_batch:
                raw_case['state'] = case_batch['state']
            if 'source_url' in case_batch:
                raw_case['source_url'] = case_batch['source_url']
            if not raw_case.get('source_url'):
                inferred_url = _extract_source_url(raw_case.get('case_text', ''))
                if inferred_url:
                    raw_case['source_url'] = inferred_url
            
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
    
    # Month+year (e.g. AZICAC) or year-only (e.g. SVICAC article year from URL/body)
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
        'investigation_types': investigation.get('types', []) if isinstance(investigation, dict) else [],
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
    # P2P / Tor / detection tech — persisted in extracted_features (not duplicated on cases row)
    features.update(extract_technology_signals(raw_case))

    # If offense product is tagged, infer Gen AI tool when press release names AI as instrument.
    topics = list(features.get("case_topics") or [])
    platforms = list(features.get("platforms_used") or [])
    case_text = raw_case.get("case_text") or ""
    if "ai_csam" in topics and "Gen AI" not in platforms:
        if _AI_CSAM_IMPLIES_TOOL_RE.search(case_text) or _GEN_AI_TOOL_RE.search(case_text):
            platforms.append("Gen AI")
    features["platforms_used"] = sorted(set(platforms))
    features["case_topics"] = topics

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
            'types': case_features.get('investigation_types') or [],
            'type': case_features.get('investigation_type'),
            'agencies': case_features.get('agencies_involved', []),
        },
        'technology_signal_vector': {
            'investigation_technology': case_features.get('investigation_technology') or [],
            'anonymization_network': case_features.get('anonymization_network') or [],
            'p2p_clients': case_features.get('p2p_clients') or [],
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
    """
    Publication-oriented dates from batching only: ``month`` / ``year`` on the raw case
    (PDF split, URL, or lead line). Does not scan full narrative for years (avoids
    historical mentions skewing timelines).
    """
    from datetime import datetime

    month = case.get("month")
    year = case.get("year")
    if not year:
        return None

    if month and year:
        try:
            month_num = datetime.strptime(month, "%B").month
            ys = str(year).strip()
            date_str = f"{ys}-{month_num:02d}-01"
            return {"start": date_str, "end": None}
        except (ValueError, AttributeError):
            pass

    # Year-only (e.g. SVICAC: publication year from article URL or lead text)
    if not month:
        ys = str(year).strip()
        if re.match(r"^\d{4}$", ys):
            return {"start": f"{ys}-01-01", "end": f"{ys}-12-31"}

    return None


_VICTIM_COUNT_INT = r'(\d{1,3}(?:,\d{3})+|\d+)'

_VICTIM_COUNT_POSITIVE_RES: Tuple[re.Pattern, ...] = (
    re.compile(rf'{_VICTIM_COUNT_INT}\s+(?:minor\s+)?victims?\b', re.I),
    re.compile(rf'{_VICTIM_COUNT_INT}\s+child\s+victims?\b', re.I),
    re.compile(
        rf'rescued\s+{_VICTIM_COUNT_INT}\s+(?:child|children|minor|minors)\b',
        re.I,
    ),
    re.compile(
        rf'{_VICTIM_COUNT_INT}\s+(?:child|children|minor|minors)\s+were\s+rescued\b',
        re.I,
    ),
    re.compile(
        rf'identified\s+{_VICTIM_COUNT_INT}\s+children\s+'
        r'(?:living|residing|that were|as new victims)\b',
        re.I,
    ),
    re.compile(
        rf'(?:abused|exploited|harmed|molested|victimized)\s+{_VICTIM_COUNT_INT}\s+'
        r'(?:child|children|minor|minors)\b',
        re.I,
    ),
    re.compile(rf'involved\s+{_VICTIM_COUNT_INT}\s+child\s+victims?\b', re.I),
    re.compile(
        rf'{_VICTIM_COUNT_INT}\s+(?:child|children|minor|minors)\s+'
        r'(?:were\s+)?(?:abused|exploited|harmed)\b',
        re.I,
    ),
    re.compile(
        rf'involving\s+{_VICTIM_COUNT_INT}\s+'
        r'(?:child|children|minor|minors|juveniles)\b',
        re.I,
    ),
    re.compile(
        rf'at\s+least\s+{_VICTIM_COUNT_INT}\s+(?:child|children)\b'
        r'(?!\s+(?:predators?|porn|charges)\b)',
        re.I,
    ),
)

_VICTIM_COUNT_EXCLUSION_RES: Tuple[re.Pattern, ...] = (
    re.compile(
        rf'{_VICTIM_COUNT_INT}\s+child\s+'
        r'(?:predators?|offenders?|individuals|defendants|pornographers?|pedophiles?)\b',
        re.I,
    ),
    re.compile(rf'{_VICTIM_COUNT_INT}\s+child\s+porn\b', re.I),
    re.compile(rf'{_VICTIM_COUNT_INT}\s+child\s+porn-?related\s+charges\b', re.I),
    re.compile(rf'{_VICTIM_COUNT_INT}\s+child\s+exploitation\s+charges\b', re.I),
    re.compile(rf'\bcharged\s+{_VICTIM_COUNT_INT}\b', re.I),
    re.compile(rf'\barrested\s+{_VICTIM_COUNT_INT}\b', re.I),
    re.compile(rf'{_VICTIM_COUNT_INT}\s+offenders?\s+were\s+arrested\b', re.I),
)


def _parse_victim_count_digits(raw: str) -> Optional[int]:
    try:
        return int(raw.replace(',', ''))
    except ValueError:
        return None


def _victim_count_match_excluded(case_text: str, start: int, end: int) -> bool:
    """True when the match sits in offender/charge/arrest headline context."""
    window_start = max(0, start - 30)
    window_end = min(len(case_text), end + 90)
    window = case_text[window_start:window_end]
    return any(pat.search(window) for pat in _VICTIM_COUNT_EXCLUSION_RES)


def extract_victim_count(case: Dict[str, Any]) -> Optional[int]:
    """
    Extract victim count only from explicit victim-clause phrasing.

    Comma-aware integers (e.g. ``1,140``) are parsed whole; offender/charge
    headlines and arrest counts are excluded. Returns ``None`` when no clause matches.
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None

    counts: List[int] = []
    for pattern in _VICTIM_COUNT_POSITIVE_RES:
        for match in pattern.finditer(case_text):
            if _victim_count_match_excluded(case_text, match.start(), match.end()):
                continue
            value = _parse_victim_count_digits(match.group(1))
            if value is not None:
                counts.append(value)

    if not counts:
        return None
    return max(counts)


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
    
    # Offender age: man/woman/male/resident only — not "female" (victim/decoy phrasing).
    perp_age_re = re.compile(
        r'(\d+)\s+year\s+old\s+(?:\w+(?:\s*,\s*\w+)*\s+)?(man|woman|male|resident)\b',
        re.IGNORECASE,
    )
    victim_ctx_re = re.compile(
        r'\b(?:'
        r'victim|victims|undercover|decoy|'
        r'profile\s+of|believed\s+(?:he|she|they)\s+was|'
        r'communicating\s+with\s+a|pretending\s+to\s+be|'
        r'year\s+old\s+(?:female|girl|boy)|'
        r'(?:female|girl|boy)\s+victim'
        r')\b',
        re.IGNORECASE,
    )

    for age_match in perp_age_re.finditer(case_text):
        try:
            age = int(age_match.group(1))
        except (ValueError, IndexError):
            continue
        if age < 18:
            continue
        window_start = max(0, age_match.start() - 90)
        window_end = min(len(case_text), age_match.end() + 90)
        window = case_text[window_start:window_end]
        if victim_ctx_re.search(window):
            continue
        demographics['age'] = age
        break
    
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


# Ordered (most specific first): canonical label shown in viz / facets, regex against case_text.
# Social / messaging, gaming, file hosting, early-era surfaces, livestreaming — offender or
# contact-side environments (stored on cases.platforms_used JSON column).
_PLATFORM_SPECS: List[Tuple[str, str]] = [
    ("Facebook Messenger", r"Facebook\s+Messenger|\bFB\s+Messenger\b"),
    ("Facebook", r"\bFacebook\b"),
    ("Instagram", r"\bInstagram\b"),
    ("Snapchat", r"\bSnapchat\b"),
    ("TikTok", r"\bTikTok\b"),
    ("Twitter / X", r"\bTwitter\b|\bX\s*\(\s*formerly\s+Twitter\s*\)|\btwitter\.com\b|\bx\.com\b"),
    ("WhatsApp", r"\bWhatsApp\b"),
    ("Telegram", r"\bTelegram\b"),
    ("Skype", r"\bSkype\b"),
    ("Kik", r"\bKik\b"),
    ("Discord", r"\bDiscord\b"),
    # Dating / hookup surfaces
    ("Grindr", r"\bGrindr\b"),
    ("Skout", r"\bSkout\b"),
    # Social / content platforms
    ("Reddit", r"\bReddit\b"),
    ("Tumblr", r"\bTumblr\b"),
    ("Yubo", r"\bYubo\b"),
    # Encrypted / anonymous messaging
    ("Wickr", r"\bWickr\b"),
    ("Chat Avenue", r"\bChat\s+Avenue\b"),
    ("Omegle", r"\bOmegle\b"),
    ("Whisper", r"(?<![A-Za-z])Whisper(?![A-Za-z])"),
    ("MeWe", r"\bMeWe\b"),
    ("Roblox", r"\bRoblox\b"),
    ("Minecraft", r"\bMinecraft\b"),
    ("Wizard 101", r"\bWizard\s*101\b"),
    ("Call of Duty", r"\bCall\s+of\s+Duty\b"),
    ("CS:GO", r"\bCS:GO\b|\bCSGO\b|Counter[- ]Strike(?:\s*:\s*Global\s+Offensive|\s+Global\s+Offensive)?"),
    ("Steam", r"\bSteam\b"),
    ("Xbox Live", r"\bXbox\s+Live\b|\bXbox\b"),
    ("PlayStation Network", r"\bPSN\b|PlayStation\s+Network"),
    ("Fortnite", r"\bFortnite\b"),
    ("Oculus", r"\bOculus\b|\bMeta\s+Quest\b"),
    ("VRChat", r"\bVRChat\b"),
    ("Monkey", r"\bapp called Monkey\b|\bMonkey\b(?=[^\n]{0,80}video chat with strangers)"),
    ("Chatroulette", r"\bChatroulette\b|\bChat\s+Roulette\b"),
    ("YouNow", r"\bYouNow\b"),
    ("Dropbox", r"\bDropbox\b"),
    ("Google Drive", r"Google\s+Drive|\bGDrive\b"),
    ("Mega.nz", r"\bmega\.nz\b|\bMEGA\b"),
    ("MediaFire", r"\bMediaFire\b"),
    ("OneDrive", r"\bOneDrive\b"),
    ("iCloud", r"\biCloud\b"),
    # Financial transfer
    ("Cash App", r"\bCash\s*App\b|\bCashApp\b"),
    # P2P distribution (also in extract_technology_signals; platforms_used for Q1 table)
    ("BitTorrent", r"\bBitTorrent\b"),
    ("LimeWire", r"\bLimeWire\b|\bLime\s*Wire\b"),
    ("Kazaa", r"\bKazaa\b"),
    # Anonymization — context-required; no bare \bTor\b (avoids senator/director/factor substrings)
    (
        "Tor",
        r"\bTor\s+[Bb]rowser\b|\bTor\s+[Nn]etwork\b|\bthe\s+Tor\s+network\b"
        r"|\bvia\s+Tor\b|\busing\s+Tor\b|\bthrough\s+Tor\b|\bTor\s+to\s+access\b",
    ),
    ("IMVU", r"\bIMVU\b"),
    # AIM must match uppercase only (IGNORECASE would hit prose "aim" = goal). Handled in extract_platforms.
    ("AOL Instant Messenger", r"AOL\s+Instant\s+Messenger"),
    ("IRC", r"\bIRC\b|Internet\s+Relay\s+Chat"),
    ("Yahoo Chat", r"Yahoo\s+Chat|\bYahoo!\s+Messenger\b"),
    ("MySpace", r"\bMySpace\b"),
    ("Craigslist", r"\bCraigslist\b"),
    ("YouTube Live", r"YouTube\s+Live"),
    ("YouTube", r"\bYouTube\b"),
    ("Twitch", r"\bTwitch\b"),
    ("Webcam platform", r"\bMyFreeCams\b|\bMFC\b(?!\s+Pennsylvania)|\bwebcam\s+platform\b|\bwebcam\b"),
    # Named generative products (tool → also adds Gen AI umbrella when matched)
    ("ChatGPT", r"\bChat\s*GPT\b|\bChatGPT\b"),
    ("Stable Diffusion", r"\bStable\s+Diffusion\b"),
    ("Midjourney", r"\bMidjourney\b"),
    ("DALL-E", r"\bDALL[\s-]?E\b"),
    # Generics (after named brands)
    ("online", r"\bonline\b"),
    # Avoid tagging "Internet Relay Chat" / "...Relay Chat" as generic chat (IRC row handles IRC).
    ("chat", r"(?<![Rr]elay\s)\bchat(ting|ted|s)?\b"),
    ("social media", r"\bsocial\s+media\b"),
]


def extract_platforms(case: Dict[str, Any]) -> List[str]:
    """
    Extract platforms and online methods used (contact / distribution surfaces).

    Named brands and early-era chat surfaces map to stable labels for ``platforms_used``.
    Generic ``online`` / ``chat`` / ``social media`` are last so specific hits win visually
    in the same list.
    """
    case_text = case.get("case_text", "")
    if not case_text:
        return []

    found: List[str] = []
    seen = set()
    if _GEN_AI_TOOL_RE.search(case_text):
        found.append("Gen AI")
        seen.add("Gen AI")
    for label, pattern in _PLATFORM_SPECS:
        if label in seen:
            continue
        if label == "AOL Instant Messenger":
            if re.search(r"\bAIM\b", case_text) or re.search(
                pattern, case_text, re.IGNORECASE
            ):
                found.append(label)
                seen.add(label)
            continue
        # Valve Steam (case-sensitive — avoids STEAM education-program acronyms).
        if label == "Steam":
            if re.search(pattern, case_text):
                found.append(label)
                seen.add(label)
            continue
        # Whisper app (case-sensitive — avoids prose "whisper").
        if label == "Whisper":
            if re.search(pattern, case_text):
                found.append(label)
                seen.add(label)
            continue
        # Tor — case-sensitive pattern only (no bare "tor" substring matches).
        if label == "Tor":
            if re.search(pattern, case_text):
                found.append(label)
                seen.add(label)
            continue
        if re.search(pattern, case_text, re.IGNORECASE):
            found.append(label)
            seen.add(label)
            if label in ("ChatGPT", "Stable Diffusion", "Midjourney", "DALL-E"):
                if "Gen AI" not in seen:
                    found.append("Gen AI")
                    seen.add("Gen AI")

    return sorted(found)


def extract_technology_signals(case: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Non-platform technology cues stored in ``extracted_features`` (slim blob, merged on read).

    Buckets:
    - ``investigation_technology``: LE / platform detection tooling (PhotoDNA, hashing, etc.)
    - ``anonymization_network``: Tor, I2P, dark web phrasing, cryptocurrency as financial layer
    - ``p2p_clients``: historical P2P / file-trading clients (distinct from cloud file *hosting*
      labels in ``platforms_used`` where applicable)
    """
    case_text = case.get("case_text", "")
    if not case_text:
        return {}

    inv: List[str] = []
    anon: List[str] = []
    p2p: List[str] = []

    _inv_specs = [
        ("PhotoDNA", r"PhotoDNA"),
        ("CSAI Match", r"CSAI\s*Match|Content\s+Safety\s+API"),
        ("hash matching", r"hash\s+match(?:ing|es)?|matched\s+against\s+known\s+hashes|perceptual\s+hash"),
        ("CyberTipline", r"Cyber\s*Tipline|CyberTip|Cybertipline|Cyber\s*Tip\s*Line"),
    ]
    _anon_specs = [
        ("Tor", r"\bTor\s+Browser\b|\bTor\s+network\b|\bvia\s+Tor\b|\bon\s+Tor\b|\bTor\s+Project\b"),
        ("I2P", r"\bI2P\b"),
        ("dark web", r"dark\s*web|darkweb"),
        ("cryptocurrency", r"\bBitcoin\b|\bEthereum\b|\bcryptocurrency\b|\bcrypto\s+wallet\b"),
    ]
    _p2p_specs = [
        ("LimeWire", r"\bLimeWire\b"),
        ("BitTorrent", r"\bBitTorrent\b|\btorrent\s+file\b|\btorrenting\b"),
        ("Kazaa", r"\bKazaa\b"),
        ("Gigatribe", r"\bGigatribe\b"),
    ]
    def _collect(specs: List[Tuple[str, str]], bucket: List[str]) -> None:
        sset = set()
        for label, pat in specs:
            if label in sset:
                continue
            if re.search(pat, case_text, re.IGNORECASE):
                bucket.append(label)
                sset.add(label)

    _collect(_inv_specs, inv)
    _collect(_anon_specs, anon)
    _collect(_p2p_specs, p2p)

    out: Dict[str, List[str]] = {}
    if inv:
        out["investigation_technology"] = sorted(inv)
    if anon:
        out["anonymization_network"] = sorted(anon)
    if p2p:
        out["p2p_clients"] = sorted(p2p)
    return out


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


_INVESTIGATION_TYPE_PRIORITY = (
    "undercover", "proactive", "reactive", "online", "unknown", "cybertip",
)
_CYBERTIP_PATTERN = (
    r"Cyber\s*Tipline|CyberTip(?:line)?|Cybertipline|Cyber\s*Tip\s*Line"
    r"|missingkids\.org/cybertipline|NCMEC\s+(?:Cyber\s*)?Tipline"
)
_METHOD_TYPE_KEYS = frozenset({"undercover", "proactive", "reactive", "online"})


def _primary_investigation_type(types: List[str]) -> Optional[str]:
    for label in _INVESTIGATION_TYPE_PRIORITY:
        if label in types:
            return label
    return types[0] if types else None


def extract_investigation_info(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract investigation type(s) and agencies involved.

    Types (non-exclusive): "proactive", "reactive", "online", "undercover", "cybertip"
    A case may be both undercover and cybertip (e.g. CyberTipline report leading to UC work).

    Agencies: "AZICAC", "FBI", "Phoenix Police", "ICAC", "HSI", "MCSO", "DPS"
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None

    types: List[str] = []

    if re.search(_CYBERTIP_PATTERN, case_text, re.IGNORECASE):
        types.append("cybertip")

    # Gate for method subtypes: need "investigation" or "operation(s)" in narrative.
    has_inv_signal = (
        re.search(r'\binvestigation\b', case_text, re.IGNORECASE)
        or re.search(r'\boperations?\b', case_text, re.IGNORECASE)
    )
    if has_inv_signal:
        # Check "undercover" before "proactive" (e.g. "proactive undercover investigation").
        type_patterns = {
            "undercover": r'\bunder\s*cover\b|\bundercover\b(?:\s+(?:\S+\s+)*(?:operation|operations|investigation|detective[s]?))?',
            "proactive": r'\bproactive\b\s+(?:\S+\s+)*(?:investigation|operation[s]?)',
            "reactive": r'\breactive\b\s+(?:\S+\s+)*(?:investigation|operation[s]?)',
            "online": r'\bonline\b\s+(?:\S+\s+)*(?:investigation|operation[s]?)',
        }
        for inv_type, pattern in type_patterns.items():
            if re.search(pattern, case_text, re.IGNORECASE) and inv_type not in types:
                types.append(inv_type)
        if not any(t in _METHOD_TYPE_KEYS for t in types):
            types.append("unknown")

    if not types:
        return None

    investigation = {
        'types': types,
        'type': _primary_investigation_type(types),
        'agencies': [],
    }

    # Extract agencies (state names alone are not agencies — use NER/full names)
    agencies = [
        'AZICAC', 'FBI', 'Phoenix Police', 'ICAC', 'HSI', 'MCSO', 'DPS',
        'NCMEC', 'CEOS', 'USMS', 'USSS', 'ICE', 'DOJ',
    ]

    for agency in agencies:
        for alias_pat, alias_flags in _agency_aliases(agency):
            if re.search(alias_pat, case_text, alias_flags):
                investigation['agencies'].append(agency)
                break

    return investigation


# Spelled-out / alternate forms → canonical regex agency label
_AGENCY_EXTRA_PATTERNS: Dict[str, List[Tuple[str, int]]] = {
    "NCMEC": [(r"National Center for Missing", re.I)],
    "CEOS": [(r"Child Exploitation and Obscenity Section", re.I)],
    "USMS": [(r"U\.?\s*S\.?\s*Marshals(?:\s+Service)?", re.I),
              (r"United States Marshals(?:\s+Service)?", re.I)],
    "USSS": [(r"U\.?\s*S\.?\s*Secret Service", re.I),
             (r"United States Secret Service", re.I)],
    "DOJ": [(r"Department of Justice", re.I)],
    "ICE": [(r"Immigration and Customs Enforcement", re.I)],
}


def _agency_aliases(agency: str) -> List[Tuple[str, int]]:
    """
    Build the list of regex patterns that should count as a mention of
    ``agency`` in case narrative text.

    For all-uppercase abbreviations (e.g. ``FBI``, ``HSI``, ``ICAC``,
    ``DPS``, ``MCSO``), source documents frequently spell them with
    interleaved dots — ``F.B.I.``, ``H.S.I.``, ``I.C.A.C.``. The default
    ``\\b<word>\\b`` regex misses those forms because ``.`` is a word
    boundary, so we also generate a dotted-letter variant. The canonical
    label (``FBI``) is always what gets stored.

    Returns ``(pattern, flags)`` tuples. Short acronyms that double as
    common English words (``ICE``) use case-sensitive matching only.
    """
    # ICE lowercase is a common English word; DOJ acronym in URLs — case-sensitive.
    case_sensitive = frozenset({"ICE", "DOJ"})
    flags = 0 if agency in case_sensitive else re.I
    patterns: List[Tuple[str, int]] = [
        (r'(?<![A-Za-z])' + re.escape(agency) + r'(?![A-Za-z])', flags)
    ]
    if (
        len(agency) >= 2
        and ' ' not in agency
        and agency.isupper()
        and agency.isalpha()
        and agency not in case_sensitive
    ):
        dotted = r'(?<![A-Za-z])' + r'\.?'.join(re.escape(c) for c in agency) + r'\.?(?![A-Za-z])'
        patterns.append((dotted, re.I))
    patterns.extend(_AGENCY_EXTRA_PATTERNS.get(agency, []))
    return patterns


def _normalize_prosecution_charge_text(charge: str) -> str:
    """Collapse whitespace/newlines in a captured charge phrase."""
    return re.sub(r'\s+', ' ', charge).strip()


# Headline/byline pollution often glued to regex captures (e.g. "…pornography BY SHELLI POOLE").
_PROSECUTION_CHARGE_BYLINE_RE = re.compile(
    r'\bBY\s+[A-Z][A-Z\s\'\.-]{2,}(?:\s+'
    r'(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|'
    r'SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\b)?',
    re.IGNORECASE,
)


def _is_junk_prosecution_charge(charge: str) -> bool:
    """Reject digit-only, too-short, or byline-contaminated charge captures."""
    if not charge:
        return True
    if len(charge) < 4:
        return True
    if re.fullmatch(r'\d+', charge):
        return True
    alnum = re.sub(r'[^\w\s]', '', charge).strip()
    if len(alnum) < 4:
        return True
    if re.match(r'^(?:By|Source|Posted|Updated)\b', charge, re.IGNORECASE):
        return True
    if _PROSECUTION_CHARGE_BYLINE_RE.search(charge):
        return True
    return False


# Terminal-stage-wins precedence (low → high). If text mentions both
# "arrested" and "convicted", booking_status becomes "convicted".
#
# "acquitted" is intentionally omitted: ICAC press releases are success stories;
# "acquitted" usually refers to a prior case or partial acquittal, not the outcome
# of the featured prosecution.
_PROSECUTION_STATUS_PRECEDENCE: Tuple[Tuple[int, str, str], ...] = (
    (1, r'\barrested\b', 'arrested'),
    (2, r'\bbooked\b', 'booked'),
    (3, r'\bcharged\b', 'charged'),
    (4, r'\bindicted\b', 'indicted'),
    (5, r'\b(?:pleaded|pled)\s+guilty\b', 'pleaded_guilty'),
    (6, r'\bconvicted\b', 'convicted'),
    (7, r'\bsentenced\b', 'sentenced'),
)

# "N count(s) [of] CHARGE" — stop at newline (not comma-only) to avoid swallowing bylines.
_CHARGE_COUNT_RE = re.compile(
    r'(\d+)\s+counts?\s+(?:of\s+)?([^\n,;]+?)(?=\s*(?:,|\.|;|\n|$))',
    re.IGNORECASE,
)

# Bare charge phrases when no "N counts" prefix is present (longest / specific first).
_BARE_CHARGE_PHRASES: Tuple[Tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pat, re.IGNORECASE), label)
    for pat, label in [
        (r'\bsexual exploitation of a minor\b', 'sexual exploitation of a minor'),
        (r'\bsexual exploitation of\s+a\s+child\b', 'sexual exploitation of a child'),
        (r'\bsexual exploitation of children\b', 'sexual exploitation of children'),
        (r'\bchild sexual abuse material\b', 'child sexual abuse material'),
        (r'\bchild pornography\b', 'child pornography'),
        (r'\bchild porn\b', 'child porn'),
        (r'\bpossession of child pornography\b', 'possession of child pornography'),
        (r'\bdistribution of child pornography\b', 'distribution of child pornography'),
        (r'\bproduction of child pornography\b', 'production of child pornography'),
        (r'\btransmission of child pornography\b', 'transmission of child pornography'),
        (r'\bonline enticement\b', 'online enticement'),
        (r'\bsex trafficking\b', 'sex trafficking'),
        (r'\bsextortion\b', 'sextortion'),
        (r'\bpandering obscenity involving a minor\b', 'pandering obscenity involving a minor'),
        (r'\bpandering\b', 'pandering'),
        (r'\bobscenity involving a minor\b', 'obscenity involving a minor'),
        (r'\bobscene material\b', 'obscene material'),
        (r'\bsexual exploitation\b', 'sexual exploitation'),
        (r'\bchild molestation\b', 'child molestation'),
        (r'\bchild exploitation\b', 'child exploitation'),
    ]
)

# Sentence *duration* outcomes (distinct from pretrial jail location in ``jail``).
# Compound patterns run first (span-aware) so bare year/supervised fragments are not
# re-emitted from the same phrase (Fix B).
_SENTENCE_COMPOUND_RES: Tuple[re.Pattern, ...] = (
    re.compile(
        r'\b\d{1,3}\s*(?:years?|yrs?)\s+of\s+supervised\s+release\b',
        re.I,
    ),
    re.compile(r'\b\d{1,3}\s*(?:years?|yrs?)\s+probation\b', re.I),
)

_SENTENCE_DURATION_RES: Tuple[re.Pattern, ...] = (
    re.compile(r'\bsentenced\s+to\s+[^.\n]{0,80}?\blife\b', re.I),
    re.compile(r'\blife\s+(?:in\s+)?prison(?:ment)?\b', re.I),
    re.compile(r'\bmandatory\s+minimum(?:\s+sentence)?\b', re.I),
    re.compile(r'\b\d{1,3}\s+(?:years?|yrs?)\b', re.I),
    re.compile(r'\b\d{1,3}\s+months?\b', re.I),
    re.compile(r'\$\s*[\d,]+(?:\.\d{2})?', re.I),
    re.compile(r'\bprobation\b', re.I),
    re.compile(r'\bsupervised\s+release\b', re.I),
)

_SENTENCING_CLAUSE_RE = re.compile(
    r'\bsentenced\s+to\b|'
    r'\bsentenced\b|'
    r'\bin\s+prison\b|'
    r'\bfederal\s+prison\b|'
    r'\bimprisonment\b|'
    r'\bsupervised\s+release\b|'
    r'\bprobation\b|'
    r'\bordered\s+today\s+to\s+serve\b|'
    r'\bto\s+be\s+followed\s+by\b|'
    r'\bmandatory\s+minimum\b|'
    r'\bmonths?\s+in\s+(?:federal\s+)?prison\b',
    re.I,
)

_SENTENCE_URL_JUNK_RE = re.compile(r'[#%]|%20|://|crime#', re.I)
_SENTENCE_AGE_AFTER_RE = re.compile(r'^\s*old\b', re.I)


def _extract_prosecution_status(case_text: str) -> Optional[str]:
    """Return the highest-precedence prosecution stage mentioned in the text."""
    best_rank = 0
    best_status: Optional[str] = None
    for rank, pattern, status in _PROSECUTION_STATUS_PRECEDENCE:
        if re.search(pattern, case_text, re.IGNORECASE) and rank > best_rank:
            best_rank = rank
            best_status = status
    return best_status


def _extract_prosecution_charges(case_text: str) -> List[Dict[str, Any]]:
    charges: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(count: int, charge: str) -> None:
        charge = _normalize_prosecution_charge_text(charge)
        if _is_junk_prosecution_charge(charge):
            return
        key = (count, charge.lower())
        if key in seen:
            return
        seen.add(key)
        charges.append({'count': count, 'charge': charge})

    for match in _CHARGE_COUNT_RE.finditer(case_text):
        try:
            _add(int(match.group(1)), match.group(2))
        except (ValueError, IndexError):
            continue

    for pattern, label in _BARE_CHARGE_PHRASES:
        if pattern.search(case_text):
            _add(1, label)

    return charges


def _sentence_span_overlaps_covered(
    start: int, end: int, covered: List[Tuple[int, int]]
) -> bool:
    return any(start < ce and end > cs for cs, ce in covered)


def _sentence_match_in_sentencing_clause(
    case_text: str, start: int, end: int, *, window: int = 140
) -> bool:
    """True when the match sits near explicit sentencing / prison language."""
    window_start = max(0, start - window)
    window_end = min(len(case_text), end + window)
    return bool(_SENTENCING_CLAUSE_RE.search(case_text[window_start:window_end]))


def _sentence_duration_requires_anchor(phrase: str) -> bool:
    """Bare year/month/probation/supervised tokens need sentencing context."""
    lower = phrase.lower()
    if '$' in phrase or 'life' in lower or 'mandatory' in lower:
        return False
    if re.search(r'\d\s+years?\s+of\s+supervised\s+release', phrase, re.I):
        return False
    if re.search(r'\d\s+years?\s+probation', phrase, re.I):
        return False
    if re.search(r'\b\d{1,3}\s+(?:years?|yrs?|months?)\b', phrase, re.I):
        return True
    if lower in ('probation', 'supervised release'):
        return True
    return False


def _sentence_match_is_url_junk(case_text: str, start: int, end: int) -> bool:
    window_start = max(0, start - 40)
    window_end = min(len(case_text), end + 40)
    return bool(_SENTENCE_URL_JUNK_RE.search(case_text[window_start:window_end]))


def _parse_sentence_months(phrase: str) -> Optional[int]:
    m = re.search(r'(\d{1,3})\s*months?', phrase, re.I)
    return int(m.group(1)) if m else None


def _parse_sentence_years(phrase: str) -> Optional[int]:
    """Custodial year count only — not supervised-release or probation compounds."""
    lower = phrase.lower()
    if (
        'supervised' in lower
        or 'probation' in lower
        or '$' in phrase
        or 'life' in lower
        or 'mandatory' in lower
    ):
        return None
    m = re.search(r'(\d{1,3})\s*(?:years?|yrs?)', phrase, re.I)
    return int(m.group(1)) if m else None


def _dedupe_sentence_same_duration_units(
    entries: List[Tuple[str, int, int]],
    case_text: str,
) -> List[str]:
    """
    Fix A: drop redundant years when the same duration appears as months (|M − 12·Y| ≤ 1).
    Always keep the months figure (court-precise). When several year matches equate to
    the same months value, drop years that are not in a sentencing clause before others.
    """
    to_drop: set = set()
    months_entries = [
        (i, _parse_sentence_months(p))
        for i, (p, _s, _e) in enumerate(entries)
        if _parse_sentence_months(p) is not None
    ]
    years_entries = [
        (i, _parse_sentence_years(p), s, e)
        for i, (p, s, e) in enumerate(entries)
        if _parse_sentence_years(p) is not None
    ]

    for _mi, m_val in months_entries:
        if m_val is None:
            continue
        matching_year_idxs = [
            (yi, y_val, ys, ye)
            for yi, y_val, ys, ye in years_entries
            if y_val is not None and abs(m_val - y_val * 12) <= 1
        ]
        if not matching_year_idxs:
            continue
        # Prefer dropping headline-only years before years in sentencing clauses.
        matching_year_idxs.sort(
            key=lambda t: (
                0 if _sentence_match_in_sentencing_clause(case_text, t[2], t[3]) else 1,
                t[2],
            )
        )
        for yi, _y_val, _ys, _ye in matching_year_idxs:
            to_drop.add(yi)

    seen: set = set()
    result: List[str] = []
    for i, (phrase, _start, _end) in enumerate(entries):
        if i in to_drop:
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(phrase)
    return result


def _extract_sentence_durations(case_text: str) -> List[str]:
    """Extract sentence outcome phrases (years, life, probation, fines) — not jail names."""
    covered: List[Tuple[int, int]] = []
    entries: List[Tuple[str, int, int]] = []

    def _add_match(match: re.Match[str]) -> None:
        start, end = match.start(), match.end()
        if _sentence_span_overlaps_covered(start, end, covered):
            return
        raw = match.group(0)
        if _sentence_match_is_url_junk(case_text, start, end):
            return
        if re.search(r'\d\s+years?', raw, re.I) and _SENTENCE_AGE_AFTER_RE.match(
            case_text[end : end + 12]
        ):
            return
        phrase = _normalize_prosecution_charge_text(raw)
        if _sentence_duration_requires_anchor(phrase) and not _sentence_match_in_sentencing_clause(
            case_text, start, end
        ):
            return
        entries.append((phrase, start, end))
        covered.append((start, end))

    for pattern in _SENTENCE_COMPOUND_RES:
        for match in pattern.finditer(case_text):
            _add_match(match)

    for pattern in _SENTENCE_DURATION_RES:
        for match in pattern.finditer(case_text):
            _add_match(match)

    has_compound_supervised = any(
        re.search(r'\d\s+years?\s+of\s+supervised\s+release', phrase, re.I)
        for phrase, _start, _end in entries
    )
    if has_compound_supervised:
        entries = [
            item for item in entries if item[0].lower() != 'supervised release'
        ]

    entries.sort(key=lambda item: item[1])
    return _dedupe_sentence_same_duration_units(entries, case_text)


def extract_prosecution_outcome(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract prosecution outcome: charges, terminal booking status, pretrial jail, sentences.

    ``jail`` = detention facility (e.g. "Maricopa County Jail", non-bondable).
    ``sentences`` = list of duration/outcome phrases ("15 years", "life", "probation").
    """
    case_text = case.get('case_text', '')
    if not case_text:
        return None

    outcome: Dict[str, Any] = {
        'charges': _extract_prosecution_charges(case_text),
        'booking_status': _extract_prosecution_status(case_text),
        'jail': None,
        'sentences': _extract_sentence_durations(case_text),
    }

    jail_match = re.search(
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+County\s+Jail)',
        case_text,
    )
    if jail_match:
        outcome['jail'] = _normalize_prosecution_charge_text(jail_match.group(1))

    if re.search(r'non-bondable', case_text, re.IGNORECASE):
        outcome['jail'] = (outcome['jail'] or '') + ' (non-bondable)'

    if outcome['charges'] or outcome['booking_status'] or outcome['jail'] or outcome['sentences']:
        return outcome
    return None


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
    Topics: production, possession, international, multi_state, hands_on, online_only, family, stranger,
    csam, ai_csam (AI-generated / synthetic CSAM product), sextortion (regex only)

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
    
    if re.search(
        r'\b(rape|raped|raping|molest\w*|hands?\s+on|sexually\s+abused|sexually\s+assaulted)\b',
        case_text,
        re.IGNORECASE,
    ):
        topics.append('hands_on')
    elif re.search(r'\b(online|chat|trading\s+images?)\b', case_text, re.IGNORECASE) and 'hands_on' not in topics and not has_sexual_abuse:
        topics.append('online_only')
    
    # Family vs stranger
    if re.search(r'\b(father|mother|parent|brother|sister|uncle|aunt|cousin|biological)\b', case_text, re.IGNORECASE):
        topics.append('family')
    elif re.search(r'\bstranger\b', case_text, re.IGNORECASE):
        topics.append('stranger')
    
    # CSAM material indicators (internal topic key: csam)
    if _CSAM_TOPIC_RE.search(case_text):
        topics.append('csam')

    # AI-CSAM offense product (tool is Gen AI in platforms_used)
    if _AI_CSAM_TOPIC_RE.search(case_text):
        topics.append('ai_csam')

    if SEXTORTION_TOPIC_RE.search(case_text):
        topics.append('sextortion')

    return list(set(topics))  # Remove duplicates


def extract_severity_phrases(case: Dict[str, Any]) -> List[str]:
    """
    Extract key severity phrases from case text that indicate high severity.
    These are non-traditional indicators that show escalation, ongoing abuse, or dangerous behavior.
    
    Phrases: "dangerous", "stated", "told", "continue", "attacked", "out of control", "attracted"
    
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
        'attracted': r'\b(attracted|attracting|attracts)\b',  # e.g. sexual interest / grooming-adjacent language
    }
    
    for phrase_key, pattern in phrase_patterns.items():
        if re.search(pattern, case_text_lower, re.IGNORECASE):
            severity_phrases.append(phrase_key)
    
    return list(set(severity_phrases))  # Remove duplicates



