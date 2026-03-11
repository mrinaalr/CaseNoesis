"""
Test ML Processing - NER Extraction

This test script loads batched cases from the database, runs NER extraction,
and displays what information was extracted and what would be stored in the DB.

Usage:
    python3 test_ml.py [--limit N] [--case-id ID]
    
    --limit N: Process only first N cases (default: 5)
    --case-id ID: Process only specific case ID
"""

import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add paths for imports
src_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(src_path / "Storage Layer"))
sys.path.insert(0, str(src_path / "Processing Layer"))

# Try stanza first (Python 3.14 compatible, extracts dates/ages)
try:
    import stanza
    STANZA_AVAILABLE = True
    STANZA_ERROR = None
except ImportError as e:
    STANZA_AVAILABLE = False
    STANZA_ERROR = str(e)
except Exception as e:
    STANZA_AVAILABLE = False
    STANZA_ERROR = f"Stanza error: {e}"

# Try transformers (Python 3.14 compatible, but doesn't extract dates/ages)
try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
    TRANSFORMERS_ERROR = None
except ImportError as e:
    TRANSFORMERS_AVAILABLE = False
    TRANSFORMERS_ERROR = str(e)
except Exception as e:
    TRANSFORMERS_AVAILABLE = False
    TRANSFORMERS_ERROR = f"Transformers error: {e}"

# Try spaCy as fallback
try:
    import spacy
    SPACY_AVAILABLE = True
    SPACY_ERROR = None
except ImportError as e:
    SPACY_AVAILABLE = False
    SPACY_ERROR = str(e)
except Exception as e:
    # Handle compatibility issues (e.g., Python 3.14 with pydantic v1)
    SPACY_AVAILABLE = False
    SPACY_ERROR = f"spaCy compatibility issue: {e}"

from storage import CaseStorage
from ner_extraction import NERExtractor


def format_entities_for_display(entities: Dict[str, List[str]]) -> str:
    """Format entities dictionary for readable display."""
    lines = []
    if entities.get('organizations'):
        lines.append(f"  Organizations ({len(entities['organizations'])}): {', '.join(entities['organizations'][:10])}")
        if len(entities['organizations']) > 10:
            lines.append(f"    ... and {len(entities['organizations']) - 10} more")
    
    if entities.get('locations'):
        lines.append(f"  Locations ({len(entities['locations'])}): {', '.join(entities['locations'][:10])}")
        if len(entities['locations']) > 10:
            lines.append(f"    ... and {len(entities['locations']) - 10} more")
    
    if entities.get('dates'):
        lines.append(f"  Dates ({len(entities['dates'])}): {', '.join(entities['dates'][:10])}")
        if len(entities['dates']) > 10:
            lines.append(f"    ... and {len(entities['dates']) - 10} more")
    
    if entities.get('ages'):
        lines.append(f"  Ages ({len(entities['ages'])}): {', '.join(map(str, entities['ages']))}")
    
    return '\n'.join(lines) if lines else "  (none)"


def show_case_ner_results(case: Dict[str, Any], ner_extractor: NERExtractor) -> Dict[str, Any]:
    """
    Process a case with NER and show what would be stored in DB.
    
    Returns:
        Enhanced case dictionary with NER entities
    """
    print("\n" + "=" * 80)
    print(f"Case ID: {case.get('id', 'unknown')}")
    print(f"Source: {case.get('source', 'unknown')}")
    print("=" * 80)
    
    # Get case text (can be in multiple places)
    case_text = ''
    if case.get('case_text'):
        case_text = case.get('case_text')
    elif isinstance(case.get('raw_data'), dict):
        case_text = case.get('raw_data', {}).get('case_text', '')
    elif isinstance(case.get('extracted_features'), dict):
        # Sometimes case_text is in extracted_features
        case_text = case.get('extracted_features', {}).get('case_text', '')
    
    if not case_text:
        print("⚠️  No case text found in case")
        return case
    
    # Show text preview
    text_preview = case_text[:200] + "..." if len(case_text) > 200 else case_text
    print(f"\nCase Text Preview:\n  {text_preview}\n")
    
    # Extract entities
    entities = ner_extractor.extract_entities(case_text)
    
    print("NER Extracted Entities:")
    print(format_entities_for_display(entities))
    
    # Enhance case with NER
    enhanced_case = ner_extractor.enhance_case_with_entities(case)
    
    # Show what would be stored in DB
    print("\n" + "-" * 80)
    print("What would be stored in database:")
    print("-" * 80)
    
    # Show ml_features that would be in extracted_features JSON
    ml_features = enhanced_case.get('ml_features', {})
    if ml_features:
        print("\n📦 ml_features (stored in extracted_features JSON):")
        print(f"  {json.dumps(ml_features, indent=2)}")
    
    # Show updated agencies_involved
    agencies = enhanced_case.get('agencies_involved', [])
    original_agencies = case.get('agencies_involved', [])
    if agencies != original_agencies:
        print(f"\n📋 agencies_involved (updated):")
        print(f"  Original: {original_agencies}")
        print(f"  After NER: {agencies}")
        print(f"  Added by NER: {list(set(agencies) - set(original_agencies))}")
    elif agencies:
        print(f"\n📋 agencies_involved: {agencies}")
    
    # Show statistics
    stats = ner_extractor.get_entity_statistics(entities)
    print(f"\n📊 Entity Statistics:")
    print(f"  Total entities: {stats['total_entities']}")
    print(f"  Organizations: {stats['organizations_count']}")
    print(f"  Locations: {stats['locations_count']}")
    print(f"  Dates: {stats['dates_count']}")
    print(f"  Ages: {stats['ages_count']}")
    
    return enhanced_case


def main():
    """Main test function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test NER extraction on batched cases')
    parser.add_argument('--limit', type=int, default=5, help='Number of cases to process (default: 5)')
    parser.add_argument('--case-id', type=str, help='Process specific case ID')
    parser.add_argument('--db', type=str, default='caselinker.db', help='Database path (default: caselinker.db)')
    parser.add_argument('--demo', action='store_true', help='Demo mode: show structure without running spaCy (for Python 3.14 compatibility)')
    args = parser.parse_args()
    
    print("=" * 80)
    print("ML Processing Test - NER Extraction")
    if args.demo:
        print("(DEMO MODE - Showing structure without spaCy)")
    print("=" * 80)
    
    # Demo mode: skip spaCy and show structure
    if args.demo:
        print("\n📋 DEMO MODE: Showing test structure and what would be extracted")
        print("=" * 80)
        
        # Load cases from database
        print(f"\nLoading cases from database: {args.db}")
        storage = CaseStorage(args.db)
        all_cases = storage.get_all_cases(include_raw_data=True)
        
        if not all_cases:
            print("❌ No cases found in database.")
            print("Run src/main.py to process PDFs and populate the database first.")
            sys.exit(1)
        
        print(f"✓ Loaded {len(all_cases)} cases from database")
        
        # Filter cases
        if args.case_id:
            cases_to_process = [c for c in all_cases if c.get('id') == args.case_id]
            if not cases_to_process:
                print(f"❌ Case ID '{args.case_id}' not found in database.")
                sys.exit(1)
        else:
            cases_to_process = all_cases[:args.limit]
        
        print(f"\nWould process {len(cases_to_process)} case(s) with NER extraction")
        print("\n" + "=" * 80)
        print("EXAMPLE OUTPUT STRUCTURE:")
        print("=" * 80)
        
        # Show example for first case
        if cases_to_process:
            case = cases_to_process[0]
            print(f"\nCase ID: {case.get('id', 'unknown')}")
            print(f"Source: {case.get('source', 'unknown')}")
            
            case_text = ''
            if case.get('case_text'):
                case_text = case.get('case_text')
            elif isinstance(case.get('raw_data'), dict):
                case_text = case.get('raw_data', {}).get('case_text', '')
            elif isinstance(case.get('extracted_features'), dict):
                case_text = case.get('extracted_features', {}).get('case_text', '')
            
            if case_text:
                text_preview = case_text[:200] + "..." if len(case_text) > 200 else case_text
                print(f"\nCase Text Preview:\n  {text_preview}\n")
            
            print("\nNER would extract entities like:")
            print("  Organizations: [FBI, NCMEC, AZICAC, Phoenix Police, ...]")
            print("  Locations: [Arizona, Phoenix, Maricopa County, ...]")
            print("  Dates: [January 2014, February 2014, ...]")
            print("  Ages: [12, 15, 35, ...]")
            
            print("\n" + "-" * 80)
            print("What would be stored in database:")
            print("-" * 80)
            print("\n📦 ml_features (stored in extracted_features JSON):")
            print("""  {
    "ner_entities": {
      "organizations": ["FBI", "NCMEC", ...],
      "locations": ["Arizona", "Phoenix", ...],
      "dates": ["January 2014", ...],
      "ages": [12, 15, ...]
    }
  }""")
            
            agencies = case.get('agencies_involved', [])
            if agencies:
                print(f"\n📋 agencies_involved (would be merged with NER organizations):")
                print(f"  Current: {agencies}")
                print(f"  After NER: {agencies + ['FBI', 'NCMEC']}  (example)")
            
            print("\n📊 Entity Statistics (example):")
            print("  Total entities: 15")
            print("  Organizations: 5")
            print("  Locations: 4")
            print("  Dates: 3")
            print("  Ages: 3")
        
        print("\n" + "=" * 80)
        print("✅ Demo complete!")
        print("=" * 80)
        print("\nTo run actual NER extraction:")
        print("  1. Use Python 3.11 or 3.12 (spaCy has Python 3.14 compatibility issues)")
        print("  2. Or wait for spaCy to update for Python 3.14 support")
        print("  3. Run without --demo flag when spaCy is available")
        return
    
    # Try stanza first (Python 3.14 compatible, extracts dates/ages!)
    stanza_works = False
    if STANZA_AVAILABLE:
        print("\nUsing Stanza backend (Python 3.14 compatible, extracts dates/ages)...")
        try:
            ner_extractor = NERExtractor(backend='stanza')
            if ner_extractor.is_available():
                print("✓ Stanza NER model loaded (extracts DATE, ORG, LOC, PER, MISC)")
                stanza_works = True
            else:
                raise Exception("Stanza pipeline failed to initialize")
        except Exception as e:
            print(f"⚠️  Stanza failed: {e}")
            print("Falling back to transformers...")
            stanza_works = False
    
    # Fallback to transformers if stanza not available
    transformers_works = False
    if not stanza_works and TRANSFORMERS_AVAILABLE:
        print("\nUsing Transformers backend (Python 3.14 compatible, no dates/ages)...")
        try:
            ner_extractor = NERExtractor(backend='transformers')
            if ner_extractor.is_available():
                print("✓ Transformers NER model loaded (extracts ORG, LOC, PER, MISC)")
                transformers_works = True
            else:
                raise Exception("Transformers pipeline failed to initialize")
        except Exception as e:
            print(f"⚠️  Transformers failed: {e}")
            transformers_works = False
    
    # Fallback to spaCy if neither available
    if not stanza_works and not transformers_works:
        if not SPACY_AVAILABLE:
            print("\n❌ Error: Neither Transformers nor spaCy is available.")
            if TRANSFORMERS_ERROR:
                print(f"Transformers error: {TRANSFORMERS_ERROR}")
            if SPACY_ERROR:
                print(f"spaCy error: {SPACY_ERROR}")
            print("\nPossible solutions:")
            print("  1. Install transformers: pip install transformers torch")
            print("  2. Or install spaCy: pip install spacy && python -m spacy download en_core_web_sm")
            print("  3. If using Python 3.14+, transformers is recommended")
            print("  4. Use --demo flag to see structure without NER")
            sys.exit(1)
        
        # Load spaCy model
        print("\nLoading spaCy model...")
        try:
            nlp = spacy.load("en_core_web_sm")
            print("✓ spaCy model loaded")
        except OSError:
            print("❌ Error: spaCy model 'en_core_web_sm' not found.")
            print("Download with: python -m spacy download en_core_web_sm")
            sys.exit(1)
        
        # Initialize NER extractor with spaCy
        ner_extractor = NERExtractor(nlp_model=nlp, backend='spacy')
        print("✓ NER Extractor initialized (spaCy)")
    
    # Load cases from database
    print(f"\nLoading cases from database: {args.db}")
    storage = CaseStorage(args.db)
    all_cases = storage.get_all_cases(include_raw_data=True)
    
    if not all_cases:
        print("❌ No cases found in database.")
        print("Run src/main.py to process PDFs and populate the database first.")
        sys.exit(1)
    
    print(f"✓ Loaded {len(all_cases)} cases from database")
    
    # Filter cases
    if args.case_id:
        cases_to_process = [c for c in all_cases if c.get('id') == args.case_id]
        if not cases_to_process:
            print(f"❌ Case ID '{args.case_id}' not found in database.")
            sys.exit(1)
    else:
        cases_to_process = all_cases[:args.limit]
    
    print(f"\nProcessing {len(cases_to_process)} case(s)...")
    print("=" * 80)
    
    # Process each case
    enhanced_cases = []
    for i, case in enumerate(cases_to_process, 1):
        print(f"\n[{i}/{len(cases_to_process)}]")
        enhanced_case = show_case_ner_results(case, ner_extractor)
        enhanced_cases.append(enhanced_case)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total_entities = 0
    total_orgs = 0
    total_locs = 0
    total_dates = 0
    total_ages = 0
    
    for case in enhanced_cases:
        ml_features = case.get('ml_features', {})
        ner_entities = ml_features.get('ner_entities', {})
        total_entities += sum(len(v) for v in ner_entities.values())
        total_orgs += len(ner_entities.get('organizations', []))
        total_locs += len(ner_entities.get('locations', []))
        total_dates += len(ner_entities.get('dates', []))
        total_ages += len(ner_entities.get('ages', []))
    
    print(f"\nProcessed {len(enhanced_cases)} case(s)")
    print(f"Total entities extracted: {total_entities}")
    print(f"  - Organizations: {total_orgs}")
    print(f"  - Locations: {total_locs}")
    print(f"  - Dates: {total_dates}")
    print(f"  - Ages: {total_ages}")
    
    print("\n" + "=" * 80)
    print("✅ Test complete!")
    print("=" * 80)
    print("\nNote: These enhanced cases with NER entities would be stored in the")
    print("database's 'extracted_features' JSON field under 'ml_features' -> 'ner_entities'")
    print("and merged into 'agencies_involved' if organizations were found.")


if __name__ == "__main__":
    main()
