"""
Merge Processing - Intersection class for Pattern and ML outputs

This class is the "intersection" layer that combines:
- Pattern Processing Layer: regex-based extraction (crimes, volume, phrases, prosecution)
- ML Processing Layer: NER / semantic extraction (ages, dates, orgs, locations, etc.)

Merge logic:
    - Ages: NER ages merged (age >= 18 → perpetrator_age, age <= 17 → case_demographics.ages)
- Pattern processing takes precedence when both sources have data
- NER supplements missing data from pattern processing
- Raw NER entities stored in ml_features.ner_entities for reference/debugging
"""

from typing import Dict, Any, List, Optional
import re


class MergeProcessing:
    """
    Intersection class between Pattern Processing and ML (NER).

    Merge behavior:
    - Ages: Merges NER ages (age >= 18 → perpetrator_age list, age <= 17 → victim ages)
    - Pattern processing takes precedence when both sources have data
    - NER supplements missing data from pattern processing
    - Raw NER entities stored in ml_features.ner_entities for reference
    """

    def __init__(self) -> None:
        """Initialize the MergeProcessing class."""
        # No state needed yet; kept for future extensions
        return None

    def merge_features(
        self,
        pattern_features: Dict[str, Any],
        ner_entities: Optional[Dict[str, List[Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Merge pattern-processing features with optional NER entities.

        For now:
        - Core behavior is pattern-only (pattern_features are authoritative)
        - NER entities are **ignored** for decision-making and only stored
          under `ml_features.ner_entities` if provided.

        Args:
            pattern_features: Feature dict from Pattern Processing Layer
            ner_entities: Optional dict from ML Processing Layer (NER)

        Returns:
            Dict with pattern_features merged with NER entities:
            - Ages: NER ages merged (age >= 18 → perpetrator_age list, age <= 17 → case_demographics.ages)
            - Organizations: ALL NER organizations stored in 'organizations' field
            - Agencies: Law enforcement agencies filtered and merged into 'agencies_involved'
            - Dates: NER dates stored as additional_event_dates
            - Locations: NER locations stored at top level
            - NER entities kept in ml_features for reference
        """
        merged = pattern_features.copy()
        
        # Initialize ml_features if not present
        if 'ml_features' not in merged:
            merged['ml_features'] = {}
        
        # Store raw NER entities for reference/debugging
        if ner_entities:
            merged['ml_features']['ner_entities'] = ner_entities
            
            # Merge ages
            merged = self._merge_ages(merged, ner_entities)
            
            # Merge organizations (law enforcement only)
            merged = self._merge_organizations(merged, ner_entities)
        
        return merged
    
    def _merge_ages(
        self,
        merged: Dict[str, Any],
        ner_entities: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        """
        Merge ages from NER into pattern features.
        
        Logic:
        - Age >= 18 → perpetrator_age (if not already set by pattern)
        - Age <= 17 → case_demographics.ages (victim ages)
        - Pattern ages take precedence if they exist
        
        Args:
            merged: Merged features dict
            ner_entities: NER entities dict
            
        Returns:
            Updated merged dict with ages merged
        """
        ner_ages = ner_entities.get('ages', [])
        if not ner_ages:
            return merged
        
        # Convert NER ages to integers and validate
        ner_age_ints = []
        for age in ner_ages:
            try:
                if isinstance(age, str):
                    age_int = int(age)
                else:
                    age_int = age
                if 1 <= age_int <= 100:
                    ner_age_ints.append(age_int)
            except (ValueError, TypeError):
                continue
        
        if not ner_age_ints:
            return merged
        
        # Get existing pattern ages
        pattern_victim_ages = []
        pattern_perp_ages = merged.get('perpetrator_age')
        
        # Handle backward compatibility: convert single integer to list
        if isinstance(pattern_perp_ages, int):
            pattern_perp_ages = [pattern_perp_ages]
        elif not isinstance(pattern_perp_ages, list):
            pattern_perp_ages = []
        
        case_demo = merged.get('case_demographics', {})
        if isinstance(case_demo, dict):
            pattern_victim_ages = case_demo.get('ages', [])
        
        # Filter pattern victim ages to exclude ages >= 18 (they should be perpetrator ages)
        pattern_victim_ages_filtered = [age for age in pattern_victim_ages if age <= 17]
        
        # Check if pattern had any ages >= 18 that should be perpetrator ages
        pattern_perp_candidates = [age for age in pattern_victim_ages if age >= 18]
        
        # Combine all pattern perpetrator ages
        all_pattern_perp_ages = list(set(pattern_perp_ages + pattern_perp_candidates))
        
        # Separate NER ages into perpetrator (age >= 18) and victim (age <= 17)
        ner_perp_ages = [age for age in ner_age_ints if age >= 18]
        ner_victim_ages = [age for age in ner_age_ints if age <= 17]
        
        # Merge all perpetrator ages: combine pattern and NER, deduplicate
        all_perp_ages = list(set(all_pattern_perp_ages + ner_perp_ages))
        all_perp_ages.sort()  # Sort for consistency
        
        if all_perp_ages:
            merged['perpetrator_age'] = all_perp_ages
        
        # Merge victim ages: combine filtered pattern and NER, deduplicate
        all_victim_ages = list(set(pattern_victim_ages_filtered + ner_victim_ages))
        
        # Final safety check: remove any ages that match perpetrator ages AND ensure all are <= 17
        if all_perp_ages:
            all_victim_ages = [age for age in all_victim_ages if age not in all_perp_ages]
        
        # Double-check: remove any ages >= 18 (shouldn't happen but safety net)
        all_victim_ages = [age for age in all_victim_ages if age <= 17]
        all_victim_ages.sort()
        
        # Update case_demographics - ensure no ages >= 18 and no duplicates with perpetrator_age
        if not isinstance(case_demo, dict):
            case_demo = {}
        
        # Final assignment - always overwrite with filtered victim ages
        # One more check: ensure no ages >= 18 and no duplicates with perpetrator ages
        final_victim_ages = [age for age in all_victim_ages if age <= 17]
        if all_perp_ages:
            final_victim_ages = [age for age in final_victim_ages if age not in all_perp_ages]
        
        # Always set victim ages (even if empty list) to ensure we overwrite any incorrect pattern values
        case_demo['ages'] = final_victim_ages if final_victim_ages else []
        
        merged['case_demographics'] = case_demo
        
        return merged
    
    def _merge_organizations(
        self,
        merged: Dict[str, Any],
        ner_entities: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        """
        Merge organizations from NER.
        
        Logic:
        - Store ALL NER organizations in 'organizations' field (tech platforms, news, agencies, etc.)
        - Filter to law enforcement agencies and merge into 'agencies_involved'
        - Pattern agencies take precedence if duplicates exist
        
        Args:
            merged: Merged features dict
            ner_entities: NER entities dict
            
        Returns:
            Updated merged dict with organizations merged
        """
        ner_orgs = ner_entities.get('organizations', [])
        if not ner_orgs:
            return merged
        
        # Normalize organizations first
        normalized_orgs = self._normalize_organizations(ner_orgs)
        
        # Filter to ONLY law enforcement agencies (we only care about LE orgs)
        law_enforcement_orgs = self._filter_law_enforcement_agencies(normalized_orgs)
        
        # Normalize pattern agencies too
        pattern_agencies_raw = merged.get('agencies_involved', [])
        pattern_agencies_normalized = self._normalize_organizations(pattern_agencies_raw)
        pattern_agencies = set(pattern_agencies_normalized)
        
        # Only save law enforcement organizations (not tech platforms, news orgs, etc.)
        if law_enforcement_orgs:
            # Deduplicate and sort
            all_orgs = list(dict.fromkeys(law_enforcement_orgs))  # Preserve order, remove duplicates
            all_orgs.sort()
            merged['organizations'] = all_orgs
            
            # Merge: combine pattern and NER law enforcement agencies for agencies_involved
            all_agencies = list(pattern_agencies | set(law_enforcement_orgs))
            all_agencies.sort()  # Sort for consistency
            merged['agencies_involved'] = all_agencies
        elif pattern_agencies:
            # Even if no NER agencies, normalize pattern agencies
            merged['organizations'] = sorted(list(pattern_agencies))
            merged['agencies_involved'] = sorted(list(pattern_agencies))
        
        return merged
    
    def _filter_law_enforcement_agencies(self, organizations: List[str]) -> List[str]:
        """
        Filter organizations to only include law enforcement agencies.
        
        Excludes:
        - Tech platforms (Facebook, Instagram, Dropbox, etc.)
        - News organizations (KAKE News, Herald, etc.)
        - Generic organizations without law enforcement context
        
        Includes:
        - Police departments
        - Sheriff departments
        - Federal agencies (FBI, ICE, HSI, etc.)
        - ICAC task forces
        - County/State/Federal law enforcement
        - Attorney/Prosecutor offices (law enforcement context)
        
        Args:
            organizations: List of organization strings from NER
            
        Returns:
            Filtered list of law enforcement agencies
        """
        law_enforcement = []
        
        # Common law enforcement keywords
        le_keywords = [
            'police', 'sheriff', 'department', 'agency', 'bureau',
            'fbi', 'ice', 'hsi', 'dea', 'atf', 'marshals', 'us marshals',
            'icac', 'ncmec', 'task force', 'taskforce',
            'attorney', 'prosecutor', 'district attorney', 'county attorney',
            'state police', 'county sheriff', 'federal',
            'investigation', 'detective', 'detectives',
            'homeland security', 'dhs', 'secret service',
            'department of justice', 'doj', 'justice department'
        ]
        
        # Common tech platforms to exclude
        tech_platforms = [
            'facebook', 'instagram', 'snapchat', 'discord', 'whatsapp',
            'dropbox', 'google', 'apple', 'microsoft', 'twitter', 'x',
            'tiktok', 'youtube', 'telegram', 'signal', 'kik'
        ]
        
        # Common news/media keywords to exclude
        news_keywords = [
            'news', 'herald', 'times', 'tribune', 'journal', 'post',
            'reporter', 'media', 'press', 'publication', 'focus'
        ]
        
        for org in organizations:
            if not org or len(org.strip()) < 3:
                continue
            
            org_lower = org.lower().strip()
            org_words = set(org_lower.split())  # Use set for whole-word matching
            
            # Skip if it's clearly a tech platform (whole word match to avoid false positives)
            # Check both substring (for multi-word platforms) and whole word matches
            is_tech = False
            for platform in tech_platforms:
                platform_words = platform.split()
                # If platform is multi-word, check substring; if single word, check whole word
                if len(platform_words) > 1:
                    if platform in org_lower:
                        is_tech = True
                        break
                else:
                    if platform_words[0] in org_words:
                        is_tech = True
                        break
            if is_tech:
                continue
            
            # Skip if it's clearly a news organization (whole word match)
            is_news = False
            for news in news_keywords:
                news_words = news.split()
                if len(news_words) > 1:
                    if news in org_lower:
                        is_news = True
                        break
                else:
                    if news_words[0] in org_words:
                        is_news = True
                        break
            if is_news:
                continue
            
            # Check if it contains law enforcement keywords
            # Use whole-word matching for single-word keywords to avoid false positives
            has_le_keyword = False
            for keyword in le_keywords:
                keyword_words = keyword.split()
                if len(keyword_words) == 1:
                    # Single word: use whole-word matching
                    if keyword in org_words:
                        has_le_keyword = True
                        break
                else:
                    # Multi-word: substring match is OK
                    if keyword in org_lower:
                        has_le_keyword = True
                        break
            
            if has_le_keyword:
                # Additional validation: make sure it's not just a generic word
                # Skip single words that are too generic
                words = org_lower.split()
                if len(words) == 1 and words[0] in ['department', 'agency', 'bureau', 'attorney', 'police', 'sheriff']:
                    continue
                
                # Skip if it's just "County" or "County Attorney" without a location
                if org_lower == 'county' or org_lower == 'county attorney':
                    continue
                
                law_enforcement.append(org.strip())
        
        # Deduplicate while preserving order
        seen = set()
        unique_agencies = []
        for agency in law_enforcement:
            agency_lower = agency.lower()
            if agency_lower not in seen:
                seen.add(agency_lower)
                unique_agencies.append(agency)
        
        return unique_agencies
    
    def _normalize_organizations(self, organizations: List[str]) -> List[str]:
        """
        Normalize organization names to merge common variations.
        
        Handles:
        - "ZICAC" → "AZICAC" (tokenization artifact)
        - NCMEC variations → "NCMEC"
        - ICAC variations → "ICAC" or "ICAC Task Force"
        - AZICAC variations → "AZICAC" or "AZICAC Task Force"
        - FBI variations → "FBI"
        - Police department variations
        - Apostrophe/spacing variations (Attorney's Office, Sheriff's Office, etc.)
        - Case variations and common abbreviations
        
        Args:
            organizations: List of organization strings
            
        Returns:
            List of normalized organization strings
        """
        normalized = []
        
        for org in organizations:
            if not org or len(org.strip()) < 2:
                continue
            
            # First pass: normalize apostrophes, quotes, and spacing issues
            org_clean = org.strip()
            # Fix multiple apostrophes/quotes: "Attorney''s" -> "Attorney's", "Attorney 's" -> "Attorney's"
            org_clean = org_clean.replace("''", "'").replace(" ' '", " '").replace(" ' ", "'")
            # Fix spacing around apostrophes: " ' s" -> "'s", " 's" -> "'s"
            org_clean = org_clean.replace(" ' s", "'s").replace(" 's", "'s").replace("' s", "'s")
            # Normalize multiple spaces to single space
            org_clean = re.sub(r'\s+', ' ', org_clean).strip()
            
            org_lower = org_clean.lower()
            
            # Filter out generic standalone terms
            generic_terms = ['task force', 'force', 'county', 'internet', 'department', 'office', 'police', 'attorney']
            if org_lower in generic_terms or org_lower == generic_terms[0] + 's':
                continue  # Skip generic terms
            
            # NCMEC variations → "NCMEC"
            if org_lower == 'ncmec' or 'national center for missing and exploited children' in org_lower:
                normalized.append('NCMEC')
                continue
            
                    # ICAC variations → "ICAC" (merge all ICAC Task Force into ICAC)
            # Handle both "ICAC" and "ICAC Task Force" and variations like "North Texas ICAC Task Force"
            if ('icac' in org_lower and 'azicac' not in org_lower) or ('internet crimes against children' in org_lower and 'arizona' not in org_lower):
                # Normalize all ICAC variations (including "ICAC Task Force", "North Texas ICAC Task Force", etc.) to just "ICAC"
                normalized.append('ICAC')
                continue
            
            # AZICAC variations → "AZICAC" or "AZICAC Task Force"
            if org_lower == 'azicac' or org_lower == 'zicac' or 'arizona internet crimes against children' in org_lower:
                # Handle "ZICAC Task Force" → "AZICAC Task Force"
                if 'task force' in org_lower:
                    normalized.append('AZICAC Task Force')
                # Handle "AZICAC Phoenix Police" → split or normalize
                elif 'phoenix police' in org_lower or 'police' in org_lower:
                    # Keep as is for now, but could normalize to "AZICAC" + separate police org
                    normalized.append('AZICAC')
                else:
                    normalized.append('AZICAC')
                continue
            
            # FBI variations → "FBI"
            if org_lower == 'fbi' or 'federal bureau of investigation' in org_lower:
                # Keep unit-specific names like "FBI Child Sexual Exploitation Unit"
                if 'child sexual exploitation' in org_lower:
                    normalized.append('FBI Child Sexual Exploitation Unit')
                else:
                    normalized.append('FBI')
                continue
            
            # Normalize "Police Department" to consistent format
            if 'police' in org_lower:
                # Extract city/region name before "police"
                police_match = re.match(r'^(.+?)\s+police', org_clean, re.IGNORECASE)
                if police_match:
                    city_name = police_match.group(1).strip()
                    # Check if it includes "Department" or "Department of Public Safety"
                    if 'department of public safety' in org_lower:
                        normalized.append(city_name + ' Department of Public Safety')
                    elif 'department' in org_lower:
                        normalized.append(city_name + ' Police Department')
                    else:
                        # If truncated (like "Phoenix Police"), assume Department
                        normalized.append(city_name + ' Police Department')
                    continue
                elif 'department' in org_lower:
                    normalized.append(org_clean.replace(' Dept.', ' Department').replace('Dept.', ' Department'))
                    continue
            
            # Normalize "Attorney's Office" variations - already fixed apostrophes above
            if 'attorney' in org_lower and 'office' in org_lower:
                # Ensure consistent "'s Office" format
                normalized_attorney = re.sub(r"\s*'?s?\s*Office\s*$", "'s Office", org_clean, flags=re.IGNORECASE)
                normalized.append(normalized_attorney)
                continue
            
            # Normalize "Sheriff's Office" variations
            if 'sheriff' in org_lower:
                # Extract county/region name before "sheriff"
                sheriff_match = re.match(r'^(.+?)\s+sheriff', org_clean, re.IGNORECASE)
                if sheriff_match:
                    county_name = sheriff_match.group(1).strip()
                    # Check if it ends with "Office", "Department", or nothing
                    if 'office' in org_lower:
                        normalized.append(county_name + " Sheriff's Office")
                    elif 'department' in org_lower:
                        normalized.append(county_name + " Sheriff's Department")
                    else:
                        # If truncated (like "Boulder County Sheriff's"), assume Office
                        normalized.append(county_name + " Sheriff's Office")
                    continue
                else:
                    # Just "Sheriff's Office" or similar - normalize apostrophe
                    normalized_sheriff = re.sub(r"sheriff'?s?\s*", "Sheriff's ", org_clean, flags=re.IGNORECASE)
                    normalized.append(normalized_sheriff)
                    continue
            
            # Normalize "Homeland Security" variations
            if 'homeland security' in org_lower:
                if 'investigation' in org_lower:
                    normalized.append('Homeland Security Investigations')
                else:
                    normalized.append('Department of Homeland Security')
                continue
            
            # Keep original for other organizations
            normalized.append(org_clean)
        
        return normalized


def merge_processing(
    pattern_features: Dict[str, Any],
    ner_entities: Optional[Dict[str, List[Any]]] = None,
) -> Dict[str, Any]:
    """
    Convenience function to merge pattern and NER features.
    
    Args:
        pattern_features: Features from Pattern Processing Layer
        ner_entities: Entities from ML Processing Layer (optional)
    
    Returns:
        Merged features dictionary
    """
    merger = MergeProcessing()
    return merger.merge_features(pattern_features, ner_entities)