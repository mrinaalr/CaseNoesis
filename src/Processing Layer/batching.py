"""
Case Batching Module

Purpose: Split text corpus into individual cases based on source format.
Handles batching for NCMEC and AZICAC cases (and can be extended for other formats).

This module is shared by both Pattern Processing Layer and ML Processing Layer.
Both layers can ingest the batched cases and process them independently.
"""

import re
from typing import Dict, List, Any, Optional


def clean_artifacts_from_text(text: str, remove_urls: bool = True) -> str:
    """
    Remove artifacts from case text including URLs, page numbers, and other PDF extraction artifacts.
    
    Handles:
    - URLs (http://, https://, www.) - optional, controlled by remove_urls parameter
    - URLs split across lines
    - Page numbers at end of text
    - AZICAC-specific artifacts (azicac.org references, URL fragments)
    - Multiple consecutive spaces
    - Leading/trailing whitespace
    
    Args:
        text: Case text that may contain artifacts
        remove_urls: If True, remove URLs. If False, keep URLs in text (default: True)
        
    Returns:
        Cleaned text with artifacts removed
    """
    if not text:
        return text
    
    cleaned_text = text
    
    # Only remove URLs if requested (for NCMEC media cases, we want to keep URLs)
    if remove_urls:
        # Pattern 1: Match full URLs (http:// or https://) - handles URLs split across lines
        # Matches: "https://www.example.com/path" or "http://example.com"
        # Also handles URLs that may be broken across lines with newlines
        pattern1 = r'https?://[^\s\n]+(?:\s*\n\s*[^\s\n]+)*'
        cleaned_text = re.sub(pattern1, '', cleaned_text, flags=re.IGNORECASE)
        
        # Pattern 2: Match www. URLs (without http://)
        # Matches: "www.example.com/path" - handles split across lines
        pattern2 = r'www\.[^\s\n]+(?:\s*\n\s*[^\s\n]+)*'
        cleaned_text = re.sub(pattern2, '', cleaned_text, flags=re.IGNORECASE)
        
        # Pattern 3: Match URLs with fragments/anchors (e.g., #:~:text=...)
        # These often appear split across lines in PDFs
        pattern3 = r'[^\s]+\.(com|org|gov|net|edu|io|co)[^\s\n]*(?:#|/)[^\s\n]*(?:\s*\n\s*[^\s\n]+)*'
        cleaned_text = re.sub(pattern3, '', cleaned_text, flags=re.IGNORECASE)
    
    # Pattern 4: AZICAC-specific patterns
    # Match from http/https to AZICAC.ORG (case-insensitive)
    pattern4 = r'https?://.*?azicac\.org'
    cleaned_text = re.sub(pattern4, '', cleaned_text, flags=re.IGNORECASE)
    
    # Pattern 5: Match page numbers/date patterns that lead to AZICAC.ORG
    pattern5 = r'\d+/\d+\s+\d+/\d+/\d+.*?azicac\.org'
    cleaned_text = re.sub(pattern5, '', cleaned_text, flags=re.IGNORECASE)
    
    # Pattern 6: Match URL path fragments like "/2011-cases-and-arrests/"
    pattern6 = r'/\d{4}-cases-and-arrests/'
    cleaned_text = re.sub(pattern6, '', cleaned_text, flags=re.IGNORECASE)
    
    # Pattern 7: Match standalone "azicac.org" or "AZICAC.ORG" (without http://)
    pattern7 = r'\bazicac\.org\b'
    cleaned_text = re.sub(pattern7, '', cleaned_text, flags=re.IGNORECASE)
    
    # Pattern 8: Remove page numbers at end of text (standalone numbers on last line)
    # Matches: "42", "65", "74", "115", "165" etc. at end of text
    # Only remove if it's a standalone number (1-4 digits) at the very end
    cleaned_text = re.sub(r'\n\s*\d{1,4}\s*$', '', cleaned_text)
    cleaned_text = re.sub(r'^\s*\d{1,4}\s*$', '', cleaned_text, flags=re.MULTILINE)
    
    # Pattern 9: Remove trailing page numbers that appear after content
    # Matches patterns like "text.\n42" or "text\n65" where number is on separate line
    cleaned_text = re.sub(r'\n\s*(\d{1,4})\s*(?=\n|$)', '', cleaned_text)
    
    # Clean up whitespace artifacts
    # Replace multiple spaces with single space
    cleaned_text = re.sub(r' +', ' ', cleaned_text)
    # Replace multiple newlines with single newline (but preserve paragraph breaks)
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    # Remove trailing whitespace from each line
    cleaned_text = re.sub(r'[ \t]+$', '', cleaned_text, flags=re.MULTILINE)
    # Remove leading/trailing whitespace from entire text
    cleaned_text = cleaned_text.strip()
    
    return cleaned_text


def case_batching(text: str, org_name: str = "case", source: str = None, source_file: str = None) -> List[Dict[str, Any]]:
    """
    Router function that splits text corpus into individual cases.
    Routes to appropriate batch function based on source format.
    
    Supported formats:
    - NCMEC: Split by state headers (ALABAMA, ARIZONA, etc.) or URL patterns
    - AZICAC: Split by month patterns ("In [Month]" or "[Month] [Year],")
    - Default: Falls back to AZICAC format
    
    To add new formats, create a _batch_[org]_cases() function and add detection logic here.
    
    Args:
        text: Large text block from PDF ingestion
        org_name: Organization name prefix for case IDs (e.g., "azicac", "ncmec")
        source: Source organization name ('NCMEC', 'AZICAC', 'FBI', etc.) - used to determine format
        source_file: Filename to extract report year from (e.g., "2022 NCMEC.pdf")
        
    Returns:
        List of case dictionaries, each with 'case_text', 'month_year', 'month', 'year', 'case_id'
    """
    # Normalize org name (lowercase, remove spaces/special chars)
    org_name = org_name.lower().replace(" ", "_").replace("-", "_")
    
    # Detect format: check source parameter first, then auto-detect from content
    is_ncmec = False
    if source and source.upper() == 'NCMEC':
        is_ncmec = True
    
    # Route to appropriate batch function
    if is_ncmec:
        return _batch_ncmec_cases(text, org_name, source_file)
    else:
        # Default to AZICAC format (can be extended for FBI, CA-ICAC, etc.)
        return _batch_azicac_cases(text, org_name)


def _batch_azicac_cases(text: str, org_name: str) -> List[Dict[str, Any]]:
    """
    Split AZICAC cases by month/year patterns.
    
    Primary pattern: "In [Month]" (e.g., "In January", "In February")
    Secondary pattern: "[Month] [Year]," (e.g., "July 2012,", "September 2012,")
    
    Args:
        text: Full text from AZICAC PDF
        org_name: Organization name prefix for case IDs (e.g., "azicac")
        
    Returns:
        List of case dictionaries with 'case_text', 'month_year', 'month', 'year', 'case_id'
    """
    cases = []
    
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
        return [{'case_text': text, 'month_year': None, 'case_id': f'{org_name}_{year}_001'}]
    
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
        
        # Clean artifacts from case text before processing
        case_text = clean_artifacts_from_text(case_text)
        
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
        
        case_id = f"{org_name}_{year}_{case_number:03d}"
        
        cases.append({
            'case_text': case_text,
            'month_year': f"{month} {year}",
            'month': month,
            'year': year,
            'case_id': case_id
        })
    
    return cases


def _batch_ncmec_cases(text: str, org_name: str, source_file: str = None) -> List[Dict[str, Any]]:
    """
    Router function for NCMEC case batching.
    Detects format from year in filename or first 10 lines and routes to appropriate handler.
    
    Args:
        text: Full text from NCMEC PDF
        org_name: Organization name prefix for case IDs (e.g., "ncmec")
        source_file: Filename to extract report year from (e.g., "2022 NCMEC.pdf")
        
    Returns:
        List of case dictionaries with 'case_text', 'month_year', 'month', 'year', 'case_id'
    """
    # Extract year from filename first (most reliable)
    report_year = None
    if source_file:
        year_match = re.search(r'(\d{4})', source_file)
        if year_match:
            report_year = year_match.group(1)
    
    if report_year == '2024':
        return _batch_ncmec_2024_cases(text, org_name, source_file)
    elif report_year in ['2022', '2023']:
        # 2022 or 2023 - use media format (numbered articles)
        return _batch_ncmec_media_cases(text, org_name, source_file)
    else:
        # Try to detect from text
        lines = text.split('\n')[:10]
        first_lines_text = ' '.join(lines)
        
        # Look for year pattern (2022, 2023, 2024)
        year_pattern = r'\b(202[234])\b'
        year_match = re.search(year_pattern, first_lines_text)
        
        if year_match:
            year = year_match.group(1)
            if year == '2024':
                return _batch_ncmec_2024_cases(text, org_name, source_file)
            else:
                return _batch_ncmec_media_cases(text, org_name, source_file)
        else:
            # No year found - default to media format
            return _batch_ncmec_media_cases(text, org_name, source_file)


def _batch_ncmec_2024_cases(text: str, org_name: str, source_file: str = None) -> List[Dict[str, Any]]:
    """
    Split NCMEC 2024 cases by state headers.
    Each case starts with a state name (ALABAMA, ARIZONA, etc.) in all caps.
    
    Args:
        text: Full text from NCMEC PDF
        org_name: Organization name prefix for case IDs (e.g., "ncmec")
        source_file: Filename to extract report year from (e.g., "2024 - NCMEC Cases.pdf")
        
    Returns:
        List of case dictionaries with 'case_text', 'month_year', 'month', 'year', 'case_id'
    """
    # Extract report year from filename if available
    report_year = None
    if source_file:
        year_match = re.search(r'(\d{4})', source_file)
        if year_match:
            report_year = year_match.group(1)
    cases = []
    
    # List of all US states (all caps for NCMEC format)
    states = [
        'ALABAMA', 'ALASKA', 'ARIZONA', 'ARKANSAS', 'CALIFORNIA', 'COLORADO',
        'CONNECTICUT', 'DELAWARE', 'FLORIDA', 'GEORGIA', 'HAWAII', 'IDAHO',
        'ILLINOIS', 'INDIANA', 'IOWA', 'KANSAS', 'KENTUCKY', 'LOUISIANA',
        'MAINE', 'MARYLAND', 'MASSACHUSETTS', 'MICHIGAN', 'MINNESOTA',
        'MISSISSIPPI', 'MISSOURI', 'MONTANA', 'NEBRASKA', 'NEVADA',
        'NEW HAMPSHIRE', 'NEW JERSEY', 'NEW MEXICO', 'NEW YORK',
        'NORTH CAROLINA', 'NORTH DAKOTA', 'OHIO', 'OKLAHOMA', 'OREGON',
        'PENNSYLVANIA', 'RHODE ISLAND', 'SOUTH CAROLINA', 'SOUTH DAKOTA',
        'TENNESSEE', 'TEXAS', 'UTAH', 'VERMONT', 'VIRGINIA', 'WASHINGTON',
        'WEST VIRGINIA', 'WISCONSIN', 'WYOMING'
    ]
    
    # Build regex pattern to match state headers (must be at start of line)
    # Sort by length (longest first) to match "NEW YORK" before "NEW"
    states_sorted = sorted(states, key=len, reverse=True)
    state_pattern = '|'.join(re.escape(state) for state in states_sorted)
    pattern = rf'^({state_pattern})$'
    
    # Find all state header positions
    matches = []
    for match in re.finditer(pattern, text, re.MULTILINE):
        matches.append({
            'pos': match.start(),
            'state': match.group(1)
        })
    
    if not matches:
        # No state headers found - return entire text as one case
        from datetime import datetime
        id_year = report_year if report_year else str(datetime.now().year)
        case_date_year = report_year if report_year else str(datetime.now().year)
        return [{
            'case_text': text,
            'month_year': None,
            'month': None,
            'year': case_date_year,
            'case_id': f'{org_name}_{id_year}_001'
        }]
    
    # Track case numbers per report year (for ID generation)
    year_case_counts = {}
    
    for i, match_info in enumerate(matches):
        start_pos = match_info['pos']
        state = match_info['state']
        
        # Determine end position (next state header or end of text)
        if i + 1 < len(matches):
            end_pos = matches[i + 1]['pos']
        else:
            end_pos = len(text)
        
        case_text = text[start_pos:end_pos].strip()
        
        # Clean artifacts from case text before processing
        case_text = clean_artifacts_from_text(case_text)
        
        # Extract date from case text (e.g., "July 10, 2024" or "May 29, 2024")
        # Look for month name followed by day and year
        months = r'(January|February|March|April|May|June|July|August|September|October|November|December)'
        date_pattern = rf'{months}\s+(\d{{1,2}}),?\s+(\d{{4}})'
        date_match = re.search(date_pattern, case_text, re.IGNORECASE)
        
        if date_match:
            month = date_match.group(1)
            day = date_match.group(2)
            case_date_year = date_match.group(3)
            month_year = f"{month} {case_date_year}"
        else:
            # Try to extract just year from case text
            year_match = re.search(r'\b(19|20)\d{2}\b', case_text)
            if year_match:
                case_date_year = year_match.group(0)
                month = None
                month_year = case_date_year
            else:
                # Fallback: use report year if available, otherwise current year
                from datetime import datetime
                case_date_year = report_year if report_year else str(datetime.now().year)
                month = None
                month_year = case_date_year
        
        # Use report year for ID generation to ensure uniqueness across different report files
        # This prevents conflicts when cases from different report years have the same case date year
        id_year = report_year if report_year else case_date_year
        
        # Track case number per report year (for ID generation)
        if id_year not in year_case_counts:
            year_case_counts[id_year] = 0
        year_case_counts[id_year] += 1
        case_number = year_case_counts[id_year]
        
        # Generate case ID using report year: ncmec_2024_001
        case_id = f"{org_name}_{id_year}_{case_number:03d}"
        
        # Use case_date_year for case metadata (not ID)
        year = case_date_year
        
        cases.append({
            'case_text': case_text,
            'month_year': month_year,
            'month': month,
            'year': year,
            'case_id': case_id,
            'state': state  # Store state for reference
        })
    
    return cases


def _batch_ncmec_media_cases(text: str, org_name: str, source_file: str = None) -> List[Dict[str, Any]]:
    """
    Split NCMEC media cases (2022/2023 format) by title → text → link pattern.
    Each case starts with a title and ends with a URL link.
    Pattern: title → text → text → link
    
    Args:
        text: Full text from NCMEC PDF
        org_name: Organization name prefix for case IDs (e.g., "ncmec")
        source_file: Filename to extract report year from (e.g., "2022 NCMEC.pdf")
        
    Returns:
        List of case dictionaries with 'case_text', 'month_year', 'month', 'year', 'case_id'
    """
    # Extract report year from filename if available
    report_year = None
    if source_file:
        year_match = re.search(r'(\d{4})', source_file)
        if year_match:
            report_year = year_match.group(1)
    
    cases = []
    
    # Find all URLs (these mark the end of each case)
    # URLs can span multiple lines (if ending with dash, continue on next line)
    # URLs end when we hit: newline → number → newline (the case marker)
    # Pattern: http://... until we hit \n\d+\n (newline, number, newline)
    url_pattern = r'https?://[^\n]+(?:\n(?!\s*\d+\s*\n)[^\n]+)*'
    url_matches = []
    for match in re.finditer(url_pattern, text):
        url_text = match.group(0)
        url_end_pos = match.end()
        
        # The URL ends, then we have newline → number → newline → next case
        # So the case ends at the URL's end position
        url_matches.append({
            'pos': url_end_pos,  # End position of URL (start of next case)
            'url': url_text
        })
    
    if not url_matches:
        # No URLs found - return entire text as one case
        from datetime import datetime
        year = report_year if report_year else str(datetime.now().year)
        return [{
            'case_text': clean_artifacts_from_text(text),
            'month_year': None,
            'month': None,
            'year': year,
            'case_id': f'{org_name}_{year}_001'
        }]
    
    # Track case numbers per year
    year_case_counts = {}
    
    # Process cases: each case is from previous URL end to current URL end
    # But skip the number marker between cases (newline → number → newline)
    for i, url_info in enumerate(url_matches):
        # Start of case: end of previous URL (or start of text for first case)
        if i == 0:
            start_pos = 0
        else:
            # Skip the number marker between URLs
            # Pattern: newline → number → newline → next case title
            prev_url_end = url_matches[i - 1]['pos']
            # Find the number marker and skip past it
            # Look for: newline, optional whitespace, number, optional whitespace, newline
            number_pattern = r'\n\s*(\d+)\s*\n'
            number_match = re.search(number_pattern, text[prev_url_end:prev_url_end+20])  # Only check first 20 chars
            if number_match:
                # Start after the number marker (which includes the trailing newline)
                start_pos = prev_url_end + number_match.end()
            else:
                # No number marker found - might be at end of file or malformed
                # Start right after previous URL (skip the newline)
                start_pos = prev_url_end + 1 if prev_url_end < len(text) and text[prev_url_end] == '\n' else prev_url_end
        
        # End of case: end of current URL
        end_pos = url_info['pos']
        
        case_text = text[start_pos:end_pos].strip()
        
        # Clean artifacts from case text before processing
        # Keep URLs for NCMEC media cases (they mark the end of each case)
        case_text = clean_artifacts_from_text(case_text, remove_urls=False)
        
        # Skip empty cases
        if not case_text or len(case_text) < 50:
            continue
        
        # Extract date from case text (for case metadata)
        months = r'(January|February|March|April|May|June|July|August|September|October|November|December)'
        date_pattern = rf'{months}\s+(\d{{1,2}}),?\s+(\d{{4}})'
        date_match = re.search(date_pattern, case_text, re.IGNORECASE)
        
        if date_match:
            month = date_match.group(1)
            day = date_match.group(2)
            case_date_year = date_match.group(3)
            month_year = f"{month} {case_date_year}"
        else:
            # Use report year from filename if available, otherwise try to extract from case text
            if report_year:
                case_date_year = report_year
                month = None
                month_year = case_date_year
            else:
                # Try to extract just year from case text (prefer 2022-2024 range)
                year_match = re.search(r'\b(202[234])\b', case_text)
                if year_match:
                    case_date_year = year_match.group(1)
                    month = None
                    month_year = case_date_year
                else:
                    # Fallback: use current year
                    from datetime import datetime
                    case_date_year = str(datetime.now().year)
                    month = None
                    month_year = case_date_year
        
        # Use report year for ID generation to ensure uniqueness across different report files
        # This prevents conflicts when cases from different report years have the same case date year
        id_year = report_year if report_year else case_date_year
        
        # Track case number per report year (for ID generation)
        if id_year not in year_case_counts:
            year_case_counts[id_year] = 0
        year_case_counts[id_year] += 1
        case_number = year_case_counts[id_year]
        
        # Generate case ID using report year: org_reportyear_number
        case_id = f"{org_name}_{id_year}_{case_number:03d}"
        
        # Use case_date_year for case metadata (not ID)
        year = case_date_year
        
        cases.append({
            'case_text': case_text,
            'month_year': month_year,
            'month': month,
            'year': year,
            'case_id': case_id
        })
    
    # Handle last case: text after the last URL (if any)
    if url_matches:
        last_url_end = url_matches[-1]['pos']
        text_after_last_url = text[last_url_end:].strip()
        
        if text_after_last_url and len(text_after_last_url) >= 50:
            # This is a final case without a URL at the end
            case_text = clean_artifacts_from_text(text_after_last_url, remove_urls=False)
            
            # Extract date from case text
            months = r'(January|February|March|April|May|June|July|August|September|October|November|December)'
            date_pattern = rf'{months}\s+(\d{{1,2}}),?\s+(\d{{4}})'
            date_match = re.search(date_pattern, case_text, re.IGNORECASE)
            
            if date_match:
                month = date_match.group(1)
                day = date_match.group(2)
                year = date_match.group(3)
                month_year = f"{month} {year}"
            else:
                # Use report year from filename if available
                if report_year:
                    year = report_year
                    month = None
                    month_year = year
                else:
                    # Try to extract just year from case text (prefer 2022-2024 range)
                    year_match = re.search(r'\b(202[234])\b', case_text)
                    if year_match:
                        year = year_match.group(1)
                        month = None
                        month_year = year
                    else:
                        # Fallback: use current year
                        from datetime import datetime
                        year = str(datetime.now().year)
                        month = None
                        month_year = year
            
            # Track case number per year
            if year not in year_case_counts:
                year_case_counts[year] = 0
            year_case_counts[year] += 1
            case_number = year_case_counts[year]
            
            # Generate case ID
            month_str = month.lower() if month else 'unknown'
            case_id = f"{org_name}_{year}_{month_str}_{case_number:03d}"
            
            cases.append({
                'case_text': case_text,
                'month_year': month_year,
                'month': month,
                'year': year,
                'case_id': case_id
            })
    
    return cases
