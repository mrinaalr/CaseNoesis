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

from typing import Dict, Any, List, Optional, Tuple, Union
import importlib.util
import re
from pathlib import Path

_victim_gate_mod = None


def _victim_age_gate():
    global _victim_gate_mod
    if _victim_gate_mod is None:
        gate_path = Path(__file__).parent / "victim_age_gate.py"
        spec = importlib.util.spec_from_file_location("victim_age_gate", gate_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(mod)
        _victim_gate_mod = mod
    return _victim_gate_mod

# Promote case_topics ai_csam when semantic concept ai_and_internet_tools clears this bar.
AI_CSAM_SEMANTIC_THRESHOLD = 0.50


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
            - Locations: NER locations (states, countries, cities) normalized and stored in 'locations' field
            - NER entities kept in ml_features for reference
        """
        merged = pattern_features.copy()
        
        # Initialize ml_features if not present
        if 'ml_features' not in merged:
            merged['ml_features'] = {}
        
        # Store raw NER entities for reference/debugging
        if ner_entities:
            merged['ml_features']['ner_entities'] = ner_entities
            
            # Merge ages (always call to filter pattern ages, even if no NER ages)
            merged = self._merge_ages(merged, ner_entities)
            
            # Merge organizations (law enforcement only)
            merged = self._merge_organizations(merged, ner_entities)
            
            # Merge locations (geography: states, countries, cities)
            merged = self._merge_locations(merged, ner_entities)
        else:
            # Even without NER entities, we need to filter pattern ages (remove 18+)
            merged = self._merge_ages(merged, {'ages': []})

        # Merge semantic concepts (if present under ml_features.semantic_severity)
        merged = self._merge_semantic_concepts(merged)
        
        return merged

    # ------------------------------------------------------------------ #
    # Semantic concepts merge (possession hint + severity add‑ons)
    # ------------------------------------------------------------------ #
    def _merge_semantic_concepts(
        self,
        merged: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge semantic concepts from ML Processing Layer into pattern features.

        Behavior:
        - Production topic: pattern/regex only (no semantic override).
        - Possession: if possession_csam is strong, ensure 'possession' tag exists.
        - Severity: add 'grooming' when the semantic concept score is present.
        - Sextortion topic: pattern/regex only (see SEXTORTION_TOPIC_RE in processing).
        """
        ml_features = merged.get('ml_features') or {}
        semantic = ml_features.get('semantic_severity') or {}

        scores: Dict[str, float] = semantic.get('scores') or {}

        topics = merged.get('case_topics') or []
        if not isinstance(topics, list):
            topics = [topics] if topics else []

        # If semantic possession is strong, ensure 'possession' tag exists
        poss_score = float(scores.get('possession_csam', 0.0))
        if poss_score >= 0.5 and 'possession' not in topics:
            topics.append('possession')

        if topics:
            merged['case_topics'] = list(dict.fromkeys(topics))

        # --- Severity indicators from concepts (non‑regex ideas) ---
        severity = merged.get('severity_indicators') or []
        if not isinstance(severity, list):
            severity = [severity] if severity else []

        # Add grooming as a semantic severity indicator
        grooming_score = float(scores.get('grooming', 0.0))
        if grooming_score >= 0.35 and 'grooming' not in severity:
            severity.append('grooming')

        if severity:
            merged['severity_indicators'] = list(dict.fromkeys(severity))

        # AI-CSAM offense (semantic gate); Gen AI tool is regex in platforms_used
        ai_score = float(scores.get('ai_and_internet_tools', 0.0))
        if ai_score >= AI_CSAM_SEMANTIC_THRESHOLD:
            if 'ai_csam' not in topics:
                topics.append('ai_csam')

        if topics:
            merged['case_topics'] = list(dict.fromkeys(topics))

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
        
        # Convert NER ages to integers and validate (filter invalid ages: 0, >100)
        ner_age_ints = []
        if ner_ages:
            for age in ner_ages:
                try:
                    if isinstance(age, str):
                        age_int = int(age)
                    else:
                        age_int = age
                    # Filter invalid ages: must be between 1 and 99 (reasonable age range)
                    if 1 <= age_int <= 99:
                        ner_age_ints.append(age_int)
                except (ValueError, TypeError):
                    continue
        
        # Get existing pattern ages (ALWAYS filter, even if no NER ages)
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
        
        # Filter pattern victim ages: exclude ages >= 18 and invalid ages (0, >100)
        pattern_victim_ages_filtered = [age for age in pattern_victim_ages if 1 <= age <= 17]
        
        # Check if pattern had any ages >= 18 that should be perpetrator ages (also filter invalid ages)
        pattern_perp_candidates = [age for age in pattern_victim_ages if 18 <= age <= 99]
        
        # Filter existing perpetrator ages to valid range (1-99)
        pattern_perp_ages = [age for age in pattern_perp_ages if 1 <= age <= 99]
        
        # Combine all pattern perpetrator ages
        all_pattern_perp_ages = list(set(pattern_perp_ages + pattern_perp_candidates))
        
        # Separate NER ages into perpetrator (age >= 18) and victim (age <= 17)
        ner_perp_ages = [age for age in ner_age_ints if age >= 18]
        ner_victim_ages = [age for age in ner_age_ints if age <= 17]
        
        # Merge all perpetrator ages: combine pattern and NER, deduplicate
        all_perp_ages = list(set(all_pattern_perp_ages + ner_perp_ages))
        all_perp_ages.sort()
        
        if all_perp_ages:
            merged['perpetrator_age'] = all_perp_ages
        elif pattern_perp_candidates:
            # Even if no other perp ages, set empty list to clear any old data
            merged['perpetrator_age'] = []
        
        # Merge victim ages: combine filtered pattern and NER, deduplicate
        # Ensure victim ages are valid (1-17) and don't overlap with perpetrator ages
        candidate_victim_ages = list(
            set(pattern_victim_ages_filtered + ner_victim_ages)
        )
        candidate_victim_ages = [
            age
            for age in candidate_victim_ages
            if 1 <= age <= 17 and age not in all_perp_ages
        ]

        case_id = merged.get("case_id") or ""
        case_text = merged.get("case_text") or ""
        gate_mod = _victim_age_gate()
        all_victim_ages, gate_log = gate_mod.apply_victim_age_gate(
            case_id, case_text, candidate_victim_ages
        )

        if not isinstance(case_demo, dict):
            case_demo = {}
        case_demo["ages"] = all_victim_ages
        merged["case_demographics"] = case_demo

        if "ml_features" not in merged:
            merged["ml_features"] = {}
        merged["ml_features"]["victim_age_gate"] = {
            "candidates": sorted(candidate_victim_ages),
            "final": all_victim_ages,
            **gate_log,
        }

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
            all_orgs = self._dedupe_agency_fragments(
                list(dict.fromkeys(law_enforcement_orgs))
            )
            merged['organizations'] = all_orgs
            
            # Merge: combine pattern and NER law enforcement agencies for agencies_involved
            combined = list(pattern_agencies | set(law_enforcement_orgs))
            merged['agencies_involved'] = self._dedupe_agency_fragments(combined)
        elif pattern_agencies:
            # Even if no NER agencies, normalize pattern agencies
            merged['organizations'] = sorted(list(pattern_agencies))
            merged['agencies_involved'] = self._dedupe_agency_fragments(
                sorted(list(pattern_agencies))
            )
        
        return merged

    _BARE_STATE_AGENCY_NAMES = frozenset({
        'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado',
        'connecticut', 'delaware', 'florida', 'georgia', 'hawaii', 'idaho',
        'illinois', 'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana',
        'maine', 'maryland', 'massachusetts', 'michigan', 'minnesota',
        'mississippi', 'missouri', 'montana', 'nebraska', 'nevada',
        'new hampshire', 'new jersey', 'new mexico', 'new york',
        'north carolina', 'north dakota', 'ohio', 'oklahoma', 'oregon',
        'pennsylvania', 'rhode island', 'south carolina', 'south dakota',
        'tennessee', 'texas', 'utah', 'vermont', 'virginia', 'washington',
        'west virginia', 'wisconsin', 'wyoming', 'las vegas',
    })

    _AGENCY_FRAGMENT_DROP = frozenset({
        'investigation', 'tor task force', 'federal bureau', 'federal',
        'police department', 'department', 'bureau', 'justice department', 'doj',
    })

    def _dedupe_agency_fragments(self, agencies: List[str]) -> List[str]:
        """Drop NER split fragments and bare state-name agency labels."""
        cleaned: List[str] = []
        seen: set = set()
        upper_blob = ' | '.join(agencies).lower()

        for agency in agencies:
            if not agency or not str(agency).strip():
                continue
            label = str(agency).strip()
            low = label.lower()

            if low in self._BARE_STATE_AGENCY_NAMES:
                continue
            if low in self._AGENCY_FRAGMENT_DROP:
                continue
            # "tor Task Force" when a *Predator Task Force exists
            if low == 'tor task force' and 'predator task force' in upper_blob:
                continue
            # Standalone "Investigation" when FBI / full bureau name present
            if low == 'investigation' and (
                'fbi' in upper_blob
                or 'federal bureau of investigation' in upper_blob
                or 'homeland security investigations' in upper_blob
            ):
                continue
            # Generic "Police Department" without a city/county prefix
            if low == 'police department' and not re.match(
                r'.+\s+police\s+department$', label, re.I
            ):
                continue

            if low not in seen:
                seen.add(low)
                cleaned.append(label)

        cleaned.sort()
        return cleaned

    # Lightweight location residue filter (Stanza post-process; not transformers-era heavy filter)
    _LOCATION_FRAGMENT_DROP = frozenset({
        "an",
        "ab",
        "pi",
        "alas",
        "anch",
        "chor",
        "ag",
        ". s",
        ". s.",
        "u. s",
        "u. s.",
        "u. s. c",
        "states",
    })
    # Possessive stems that are real places — do not drop "Boise's" etc. if ever tagged
    _KNOWN_PLACE_POSSESSIVE_STEMS = frozenset({
        "alaska", "alabama", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
        "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan", "minnesota",
        "mississippi", "missouri", "montana", "nebraska", "nevada",
        "new hampshire", "new jersey", "new mexico", "new york",
        "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia", "washington",
        "west virginia", "wisconsin", "wyoming",
        "anchorage", "boise", "boston", "chicago", "dallas", "denver",
        "houston", "phoenix", "seattle", "portland", "honolulu", "juneau",
        "ely", "erie", "rome", "paris",
    })
    _POSSESSIVE_LOC_RE = re.compile(r"^(.+?)(?:['\u2019])s$", re.IGNORECASE)

    def _expand_newline_location_entities(self, loc: str) -> List[str]:
        """``ALASKA\\nWASHINGTON`` → two entities."""
        if not loc or "\n" not in loc:
            return [loc.strip()] if loc and loc.strip() else []
        return [p.strip() for p in loc.splitlines() if p.strip()]

    def _is_location_residue_fragment(self, loc: str) -> bool:
        """Rare transformers-era shards; explicit list only (not all ≤2-char places)."""
        low = loc.lower().strip()
        if low in self._LOCATION_FRAGMENT_DROP:
            return True
        if re.match(r"^\.\s*[a-z]\.?$", low):
            return True
        if re.match(r"^u\.\s*s\.?$", low):
            return True
        return False

    def _is_possessive_non_place(self, loc: str) -> bool:
        """Drop ``Moore's``-style PERSON possessives; keep known place stems."""
        m = self._POSSESSIVE_LOC_RE.match(loc.strip())
        if not m:
            return False
        stem = m.group(1).strip().lower()
        if stem in self._KNOWN_PLACE_POSSESSIVE_STEMS:
            return False
        if len(stem) >= 2 and stem in self._BARE_STATE_AGENCY_NAMES:
            return False
        return True

    def _pick_canonical_location_label(self, variants: List[str]) -> str:
        """Case-insensitive dedup: prefer title-case over ALL-CAPS dateline duplicates."""

        def _score(label: str) -> tuple:
            s = label.strip()
            if not s:
                return (0, 0, 0)
            letters = [c for c in s if c.isalpha()]
            all_caps = bool(letters) and all(c.isupper() for c in letters) and len(s) > 3
            titleish = bool(re.search(r"[a-z]", s)) and bool(re.search(r"[A-Z]", s))
            return (1 if titleish else 0, 0 if all_caps else 1, len(s))

        return max(variants, key=_score)

    def _drop_substring_location_fragments(self, locations: List[str]) -> List[str]:
        """Drop ``Chorage`` / ``An`` when a longer location on the case contains it."""
        if len(locations) < 2:
            return locations
        lowered = [loc.lower() for loc in locations]
        keep: List[str] = []
        for i, loc in enumerate(locations):
            low = lowered[i]
            if len(low) <= 4:
                if any(
                    j != i
                    and len(lowered[j]) > len(low) + 2
                    and low in lowered[j]
                    and low not in ("erie", "ely", "rome", "ohio", "utah", "iowa", "id")
                    for j in range(len(locations))
                ):
                    continue
            keep.append(loc)
        return keep

    def _filter_location_residue(
        self, locations: List[str], *, audit: bool = False
    ) -> List[str] | Tuple[List[str], List[Tuple[str, str]]]:
        """
        Stanza residue safety net (not a full transformers fragment rebuild).

        - Split newline-glued entities
        - Drop explicit fragment shards + possessive non-places
        - Case-insensitive dedup (prefer title-case)
        - Substring fragment dedup when parent place exists
        - Keeps jurisdiction phrases (District of Alaska, Western District of …)
        - Does NOT blocklist alias GPEs (e.g. China) — flagged for later

        With ``audit=True``, returns ``(cleaned, [(dropped_label, reason), ...])``.
        """
        dropped_audit: List[Tuple[str, str]] = []
        expanded: List[str] = []
        for raw in locations:
            if not raw or not str(raw).strip():
                continue
            parts = self._expand_newline_location_entities(str(raw).strip())
            if audit and len(parts) > 1:
                for p in parts[1:]:
                    dropped_audit.append((raw, "newline_split"))
            expanded.extend(parts)

        filtered: List[str] = []
        for loc in expanded:
            if self._is_location_residue_fragment(loc):
                if audit:
                    dropped_audit.append((loc, "fragment_reject_list"))
                continue
            if self._is_possessive_non_place(loc):
                if audit:
                    dropped_audit.append((loc, "possessive_non_place"))
                continue
            filtered.append(loc)

        before_sub = list(filtered)
        filtered = self._drop_substring_location_fragments(filtered)
        if audit:
            kept_low = {x.lower() for x in filtered}
            for loc in before_sub:
                if loc.lower() not in kept_low:
                    dropped_audit.append((loc, "substring_parent_dedup"))

        groups: Dict[str, List[str]] = {}
        for loc in filtered:
            key = re.sub(r"\s+", " ", loc.lower().strip())
            groups.setdefault(key, []).append(loc)

        deduped: List[str] = []
        seen: set = set()
        for key, variants in groups.items():
            canonical = self._pick_canonical_location_label(variants)
            if key not in seen:
                seen.add(key)
                deduped.append(canonical)
            elif audit:
                for v in variants:
                    if v != canonical:
                        dropped_audit.append((v, "case_insensitive_dedup"))

        deduped.sort(key=lambda s: s.lower())
        if audit:
            return deduped, dropped_audit
        return deduped
    
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
        - "The" prefix removal
        - HSI abbreviation normalization
        
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
            # Fix apostrophe issues: normalize all variations to "'s"
            # Handle patterns like: " ' 's", " 's", "' 's", " ' s", "' s", etc.
            # Match any sequence of spaces/quotes/apostrophes before 's' and replace with "'s"
            org_clean = re.sub(r"\s*['']+\s*['']*\s*s\b", "'s", org_clean)
            # Normalize multiple spaces to single space
            org_clean = re.sub(r'\s+', ' ', org_clean).strip()
            
            # Remove leading "the " (case-insensitive)
            if org_clean.lower().startswith('the '):
                org_clean = org_clean[4:].strip()
            # Remove leading "The " 
            if org_clean.startswith('The '):
                org_clean = org_clean[4:].strip()
            
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
            
            # HSI abbreviation normalization (must come after apostrophe fix and "the" removal)
            org_upper = org_clean.upper()
            if org_upper == 'HSI' or org_clean == 'Homeland Security Investigations':
                normalized.append('Homeland Security Investigations')
                continue
            
            # Keep original for other organizations
            normalized.append(org_clean)
        
        # Deduplicate while preserving order (case-insensitive)
        seen = set()
        unique_normalized = []
        for org in normalized:
            org_lower = org.lower()
            if org_lower not in seen:
                seen.add(org_lower)
                unique_normalized.append(org)
        
        return unique_normalized
    
    def _merge_locations(
        self,
        merged: Dict[str, Any],
        ner_entities: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        """
        Merge locations (geography) from NER into pattern features.
        
        Extracts states, countries, cities, and other geographic entities.
        Normalizes and deduplicates locations.
        
        Args:
            merged: Merged features dict
            ner_entities: NER entities dict
            
        Returns:
            Updated merged dict with locations added
        """
        ner_locations = ner_entities.get('locations', [])
        if not ner_locations:
            return merged
        
        # Normalize and clean locations
        normalized_locations = []
        seen = set()
        
        for loc in ner_locations:
            if not loc or len(loc.strip()) < 2:
                continue
            
            # Clean up location text
            loc_clean = loc.strip()
            loc_lower = loc_clean.lower()
            
            # Skip if already seen (case-insensitive)
            if loc_lower in seen:
                continue
            
            # Normalize common variations
            # US state abbreviations -> full names
            state_abbrev_map = {
                'az': 'Arizona', 'ca': 'California', 'co': 'Colorado', 'fl': 'Florida',
                'il': 'Illinois', 'ny': 'New York', 'tx': 'Texas', 'wa': 'Washington',
                'or': 'Oregon', 'nv': 'Nevada', 'nm': 'New Mexico', 'ut': 'Utah',
                'id': 'Idaho', 'mt': 'Montana', 'wy': 'Wyoming', 'nd': 'North Dakota',
                'sd': 'South Dakota', 'ne': 'Nebraska', 'ks': 'Kansas', 'ok': 'Oklahoma',
                'ar': 'Arkansas', 'mo': 'Missouri', 'ia': 'Iowa', 'mn': 'Minnesota',
                'wi': 'Wisconsin', 'mi': 'Michigan', 'in': 'Indiana', 'oh': 'Ohio',
                'ky': 'Kentucky', 'tn': 'Tennessee', 'al': 'Alabama', 'ms': 'Mississippi',
                'la': 'Louisiana', 'ga': 'Georgia', 'sc': 'South Carolina', 'nc': 'North Carolina',
                'va': 'Virginia', 'wv': 'West Virginia', 'md': 'Maryland', 'de': 'Delaware',
                'nj': 'New Jersey', 'pa': 'Pennsylvania', 'ct': 'Connecticut', 'ri': 'Rhode Island',
                'ma': 'Massachusetts', 'vt': 'Vermont', 'nh': 'New Hampshire', 'me': 'Maine',
                'ak': 'Alaska', 'hi': 'Hawaii', 'dc': 'Washington DC'
            }
            
            # Check if it's a state abbreviation
            if loc_lower in state_abbrev_map:
                loc_clean = state_abbrev_map[loc_lower]
                loc_lower = loc_clean.lower()
            
            # Normalize common location patterns
            # "City, State" -> keep both parts
            if ',' in loc_clean:
                parts = [p.strip() for p in loc_clean.split(',')]
                # If second part is a state abbreviation, expand it
                if len(parts) == 2 and parts[1].lower() in state_abbrev_map:
                    parts[1] = state_abbrev_map[parts[1].lower()]
                loc_clean = ', '.join(parts)
            
            # Capitalize properly (Title Case for locations)
            words = loc_clean.split()
            loc_normalized = ' '.join(word.capitalize() if word.lower() not in ['of', 'de', 'la', 'the'] else word.lower() 
                                     for word in words)
            # Handle special cases - normalize all US variations to "United States"
            loc_lower_clean = loc_normalized.lower().strip()
            if (loc_lower_clean in ['usa', 'u.s.a.', 'u.s.a', 'us'] or
                (loc_lower_clean == 'us' and len(words) == 1) or
                loc_lower_clean == 'america' or
                loc_lower_clean.startswith('the ') and loc_lower_clean.replace('the ', '').strip() == 'united states'):
                loc_normalized = 'United States'
            
            normalized_locations.append(loc_normalized)
            seen.add(loc_lower)
            seen.add(loc_normalized.lower())
        
        filtered = self._filter_location_residue(normalized_locations)
        normalized_locations = filtered if isinstance(filtered, list) else filtered[0]

        if normalized_locations:
            merged['locations'] = normalized_locations

        return merged


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