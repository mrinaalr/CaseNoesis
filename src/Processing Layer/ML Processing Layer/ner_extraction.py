"""
Named Entity Recognition (NER) Module

Purpose: Extract named entities from case text using spaCy NER.
Complements regex-based extraction by identifying entities that
may not match structured patterns.

Usage:
    from ml_models import MLModelManager
    from ner_extraction import NERExtractor
    
    ml_manager = MLModelManager(enable_ml=True)
    ner_model = ml_manager.get_model('ner')
    
    if ner_model:
        ner = NERExtractor(ner_model)
        entities = ner.extract_entities(case_text)
        enhanced_case = ner.enhance_case_with_entities(case)
"""

import warnings
from typing import Dict, List, Any, Optional, Set
import re


class NERExtractor:
    """
    Named Entity Recognition extractor using spaCy.
    
    Extracts entities like organizations, locations, persons, dates
    that complement regex-based extraction.
    """
    
    def __init__(self, nlp_model=None):
        """
        Initialize NER extractor.
        
        Args:
            nlp_model: spaCy NLP model instance. If None, NER won't work.
        """
        self.nlp = nlp_model
        if nlp_model is None:
            warnings.warn("No spaCy model provided. NER extraction will not work.")
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract named entities from text.
        
        Args:
            text: Case text to extract entities from
            
        Returns:
            Dictionary with entity types as keys and lists of entities as values:
            {
                'persons': [...],
                'organizations': [...],
                'locations': [...],
                'dates': [...],
                'ages': [...]
            }
        """
        if not self.nlp or not text:
            return {
                'persons': [],
                'organizations': [],
                'locations': [],
                'dates': [],
                'ages': []
            }
        
        try:
            doc = self.nlp(text)
            
            entities = {
                'persons': [],
                'organizations': [],
                'locations': [],
                'dates': [],
                'ages': []
            }
            
            # Extract entities by type
            for ent in doc.ents:
                if ent.label_ == 'PERSON':
                    # Filter out common false positives
                    if self._is_valid_person(ent.text):
                        entities['persons'].append(ent.text.strip())
                elif ent.label_ == 'ORG':
                    entities['organizations'].append(ent.text.strip())
                elif ent.label_ in ['GPE', 'LOC']:  # Geopolitical entity or location
                    entities['locations'].append(ent.text.strip())
                elif ent.label_ == 'DATE':
                    entities['dates'].append(ent.text.strip())
            
            # Extract ages using pattern + context
            ages = self._extract_ages_with_context(doc, text)
            entities['ages'].extend(ages)
            
            # Remove duplicates while preserving order
            for key in entities:
                entities[key] = list(dict.fromkeys(entities[key]))
            
            return entities
            
        except Exception as e:
            warnings.warn(f"Error in NER extraction: {e}")
            return {
                'persons': [],
                'organizations': [],
                'locations': [],
                'dates': [],
                'ages': []
            }
    
    def _is_valid_person(self, text: str) -> bool:
        """
        Filter out common false positives for person names.
        
        Args:
            text: Potential person name
            
        Returns:
            True if likely a valid person name
        """
        # Filter out common false positives
        false_positives = {
            'victim', 'victims', 'child', 'children', 'minor', 'minors',
            'perpetrator', 'offender', 'suspect', 'defendant', 'arrested',
            'booked', 'charged', 'jail', 'prison', 'police', 'officer'
        }
        
        text_lower = text.lower().strip()
        
        # Skip if it's a common word
        if text_lower in false_positives:
            return False
        
        # Skip if it's too short (likely not a name)
        if len(text_lower) < 3:
            return False
        
        # Skip if it's all uppercase acronyms
        if text.isupper() and len(text) <= 5:
            return False
        
        return True
    
    def _extract_ages_with_context(self, doc, text: str) -> List[int]:
        """
        Extract ages from text using pattern matching with context awareness.
        
        Args:
            doc: spaCy doc object
            text: Original text
            
        Returns:
            List of extracted ages
        """
        ages = []
        
        # Pattern: "X year old" or "age X" or "X years old"
        age_patterns = [
            r'(\d+)\s+year\s+old',
            r'age\s+(\d+)',
            r'(\d+)\s+years\s+old',
            r'aged\s+(\d+)',
        ]
        
        for pattern in age_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    age = int(match.group(1))
                    # Validate age range
                    if 1 <= age <= 100:
                        # Check context to avoid false positives
                        context_start = max(0, match.start() - 30)
                        context_end = min(len(text), match.end() + 30)
                        context = text[context_start:context_end].lower()
                        
                        # Skip if it's clearly not an age (e.g., "2014" in dates)
                        if 'year' in context or 'old' in context or 'age' in context:
                            ages.append(age)
                except (ValueError, IndexError):
                    continue
        
        return list(set(ages))  # Remove duplicates
    
    def merge_with_regex_results(
        self,
        regex_results: Dict[str, Any],
        ner_entities: Dict[str, List[str]]
    ) -> Dict[str, Any]:
        """
        Merge NER results with regex extraction results.
        
        Regex is authoritative for structured data (ages, platforms, etc.).
        NER supplements with contextual entities (organizations, locations).
        
        Args:
            regex_results: Results from regex-based extraction
            ner_entities: Results from NER extraction
            
        Returns:
            Merged results with confidence indicators
        """
        merged = regex_results.copy()
        
        # Merge organizations (NER can catch ones regex misses)
        regex_orgs = set(regex_results.get('agencies_involved', []))
        ner_orgs = set(ner_entities.get('organizations', []))
        
        # Combine and deduplicate
        all_orgs = list(regex_orgs | ner_orgs)
        merged['agencies_involved'] = all_orgs
        
        # Add NER entities to ml_features
        if 'ml_features' not in merged:
            merged['ml_features'] = {}
        merged['ml_features']['ner_entities'] = ner_entities
        
        # Add extraction confidence
        merged['ml_features']['extraction_confidence'] = {
            'regex_organizations': len(regex_orgs),
            'ner_organizations': len(ner_orgs),
            'merged_organizations': len(all_orgs),
            'ner_supplemented': len(ner_orgs - regex_orgs) > 0
        }
        
        return merged
    
    def enhance_case_with_entities(
        self,
        case: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enhance case dictionary with NER-extracted entities.
        
        Args:
            case: Case dictionary with case_text
            
        Returns:
            Enhanced case dictionary with NER entities in ml_features
        """
        if not self.nlp:
            return case
        
        enhanced_case = case.copy()
        
        # Get case text
        case_text = (
            case.get('case_text', '') or
            case.get('raw_data', {}).get('case_text', '') or
            ''
        )
        
        if case_text:
            # Extract entities
            entities = self.extract_entities(case_text)
            
            # Add to ml_features
            if 'ml_features' not in enhanced_case:
                enhanced_case['ml_features'] = {}
            enhanced_case['ml_features']['ner_entities'] = entities
            
            # Merge with existing agencies if present
            existing_agencies = enhanced_case.get('agencies_involved', [])
            if existing_agencies:
                # Merge NER organizations with existing
                all_agencies = list(set(existing_agencies + entities['organizations']))
                enhanced_case['agencies_involved'] = all_agencies
            else:
                # Use NER organizations if no regex results
                enhanced_case['agencies_involved'] = entities['organizations']
        
        return enhanced_case
    
    def get_entity_statistics(self, entities: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        Get statistics about extracted entities.
        
        Args:
            entities: Dictionary of extracted entities
            
        Returns:
            Statistics dictionary
        """
        return {
            'total_entities': sum(len(v) for v in entities.values()),
            'persons_count': len(entities.get('persons', [])),
            'organizations_count': len(entities.get('organizations', [])),
            'locations_count': len(entities.get('locations', [])),
            'dates_count': len(entities.get('dates', [])),
            'ages_count': len(entities.get('ages', []))
        }
    
    def is_available(self) -> bool:
        """Check if NER extraction is available."""
        return self.nlp is not None
