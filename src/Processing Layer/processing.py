"""
Processing Layer - Backward Compatibility Module

This module provides backward compatibility for imports like:
    from processing import process_cases

It re-exports all functions from the Pattern Processing Layer and Batching module.
"""

# Re-export everything from Pattern Processing Layer and Batching
# Handle spaces in directory name using importlib
import importlib.util
from pathlib import Path
import pandas as pd
import re
from typing import Dict, Any, List
from datetime import datetime

# Try to import tqdm for progress bars, fallback gracefully if not available
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    # Create a dummy tqdm that just returns the iterable unchanged
    def tqdm(iterable, *args, **kwargs):
        return iterable

# Import batching functions directly from batching module
_batching_path = Path(__file__).parent / "batching.py"
_batching_spec = importlib.util.spec_from_file_location("batching", _batching_path)
batching = importlib.util.module_from_spec(_batching_spec)
_batching_spec.loader.exec_module(batching)
try_append_source_url_continuation = batching.try_append_source_url_continuation
consume_same_line_slug_after_url = batching.consume_same_line_slug_after_url

# Import from Pattern Processing Layer
_pattern_processing_path = Path(__file__).parent / "Pattern Processing Layer" / "processing.py"
_pattern_spec = importlib.util.spec_from_file_location("pattern_processing", _pattern_processing_path)
pattern_processing = importlib.util.module_from_spec(_pattern_spec)
_pattern_spec.loader.exec_module(pattern_processing)

# Import batching functions directly from batching module (shared by both layers)
case_batching = batching.case_batching
clean_artifacts_from_text = batching.clean_artifacts_from_text
clean_urls_from_text = batching.clean_artifacts_from_text  # Backward compatibility alias

# Import pattern processing functions
_pattern_process_cases = pattern_processing.process_cases
extract_features = pattern_processing.extract_features
assign_comparison_values = pattern_processing.assign_comparison_values
extract_date_range = pattern_processing.extract_date_range
extract_victim_count = pattern_processing.extract_victim_count
extract_case_demographics = pattern_processing.extract_case_demographics
extract_perpetrator_demographics = pattern_processing.extract_perpetrator_demographics
extract_relationship = pattern_processing.extract_relationship
extract_previous_conviction = pattern_processing.extract_previous_conviction
extract_platforms = pattern_processing.extract_platforms
extract_evidence_volume = pattern_processing.extract_evidence_volume
extract_investigation_info = pattern_processing.extract_investigation_info
extract_prosecution_outcome = pattern_processing.extract_prosecution_outcome
extract_severity = pattern_processing.extract_severity
extract_topics = pattern_processing.extract_topics
extract_severity_phrases = pattern_processing.extract_severity_phrases

# Import merge_processing intersection class
_merge_path = Path(__file__).parent / "merge_processing.py"
_merge_spec = importlib.util.spec_from_file_location("merge_processing_module", _merge_path)
merge_module = importlib.util.module_from_spec(_merge_spec)
_merge_spec.loader.exec_module(merge_module)

MergeProcessing = merge_module.MergeProcessing
merge_processing = merge_module.merge_processing

# Import NER extractor from ML Processing Layer
_ml_layer_path = Path(__file__).parent / "ML Processing Layer" / "ner_extraction.py"
_ner_spec = importlib.util.spec_from_file_location("ner_extraction", _ml_layer_path)
ner_module = importlib.util.module_from_spec(_ner_spec)
_ner_spec.loader.exec_module(ner_module)

NERExtractor = ner_module.NERExtractor

# Import semantic concept detector from ML Processing Layer
_semantic_path = Path(__file__).parent / "ML Processing Layer" / "semantic_concepts.py"
_semantic_spec = importlib.util.spec_from_file_location("semantic_concepts", _semantic_path)
semantic_module = importlib.util.module_from_spec(_semantic_spec)
_semantic_spec.loader.exec_module(semantic_module)

SemanticConcepts = semantic_module.SemanticConcepts


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


def process_cases(df):
    """
    Process cases: batch → pattern extract → NER extract → merge → comparison values.
    
    Expects ingestion DataFrame rows with ``extracted_text`` (or the column name your
    ingestion step uses), ``source`` (e.g. NCMEC, AZICAC, ALEA, VT AG), ``source_file``,
    and optional ``source_url``.
    
    Pipeline:
    1. Batch cases using batching.py
    2. Extract pattern features using Pattern Processing Layer
    3. Extract NER features using ML Processing Layer (if available)
    4. Merge features using MergeProcessing (for now, pattern-only)
    5. Assign comparison values
    6. Return cases ready for storage
    
    Args:
        df: DataFrame from ingestion layer (parsed PDF data with 'extracted_text')
        
    Returns:
        List of structured case dictionaries ready for storage
    """
    # Initialize NER extractor (gracefully handles if models not available)
    ner_extractor = None
    try:
        # NERExtractor handles its own initialization and model loading
        ner_extractor = NERExtractor(backend='stanza')  # Try Stanza first
        if not ner_extractor.is_available():
            # Fallback to transformers if Stanza not available
            ner_extractor = NERExtractor(backend='transformers')
            if not ner_extractor.is_available():
                ner_extractor = None
    except Exception:
        # NER not available - continue without it
        ner_extractor = None

    # Initialize semantic concepts detector (optional; ML deps may be missing)
    semantic_detector = None
    try:
        semantic_detector = SemanticConcepts()
        if not semantic_detector.is_available():
            semantic_detector = None
    except Exception:
        semantic_detector = None
    
    processed_cases = []
    merger = MergeProcessing()
    
    # First pass: Collect all case batches to get total count for progress bar
    all_case_batches = []
    for idx, row in df.iterrows():
        extracted_text = row.get('extracted_text', '')
        source = row.get('source', 'unknown')
        source_file = row.get('source_file', 'unknown')
        
        # Step 1: Batch cases (batching.py handles its own logic)
        org_name = source.lower() if source and source != 'unknown' else 'case'
        if org_name == 'case' and source_file:
            org_match = re.search(r'([A-Z]+)', source_file)
            if org_match:
                org_name = org_match.group(1).lower()
        
        case_batches = case_batching(extracted_text, org_name=org_name, source=source, source_file=source_file)
        
        # Store batches with metadata for processing
        for case_batch in case_batches:
            all_case_batches.append({
                'case_batch': case_batch,
                'source': source,
                'source_file': source_file,
                'source_url': row.get('source_url'),
            })
    
    # Second pass: Process all cases with progress bar
    total_cases = len(all_case_batches)
    if total_cases == 0:
        return processed_cases
    
    # Use tqdm for progress bar if available
    if HAS_TQDM:
        case_iterator = tqdm(
            all_case_batches,
            desc="Processing cases",
            unit="case",
            total=total_cases
        )
    else:
        case_iterator = all_case_batches
    
    for batch_info in case_iterator:
        case_batch = batch_info['case_batch']
        source = batch_info['source']
        source_file = batch_info['source_file']
        
        raw_case = {
            'case_text': case_batch.get('case_text'),
            'month_year': case_batch.get('month_year'),
            'month': case_batch.get('month'),
            'year': case_batch.get('year'),
            'case_id': case_batch.get('case_id'),
            'source': source,
            'source_file': source_file,
        }
        row_source_url = batch_info.get('source_url')
        if isinstance(row_source_url, str) and row_source_url.strip():
            raw_case['source_url'] = row_source_url.strip()
        if 'state' in case_batch:
            raw_case['state'] = case_batch['state']
        if 'source_url' in case_batch:
            raw_case['source_url'] = case_batch['source_url']
        if not raw_case.get('source_url'):
            inferred_url = _extract_source_url(raw_case.get('case_text', ''))
            if inferred_url:
                raw_case['source_url'] = inferred_url
        
        # Step 2: Extract pattern features (Pattern Processing Layer handles its own logic)
        pattern_features = extract_features(raw_case)

        # Step 2b: Enrich with semantic concepts (if available)
        if semantic_detector and semantic_detector.is_available():
            try:
                semantic_detector.enhance_case_with_concepts(pattern_features)
            except Exception:
                # If semantic enrichment fails, continue with pattern-only features
                pass
        
        # Step 3: Extract NER features (ML Processing Layer handles its own logic)
        ner_entities = None
        if ner_extractor and ner_extractor.is_available():
            case_text = raw_case.get('case_text', '')
            if case_text:
                try:
                    ner_entities = ner_extractor.extract_entities(case_text)
                except Exception:
                    # NER extraction failed - continue without NER
                    ner_entities = None
        
        # Step 4: Merge pattern + NER features (MergeProcessing handles its own logic)
        merged_features = merger.merge_features(pattern_features, ner_entities)
        
        # Step 5: Assign comparison values (Pattern Processing Layer handles its own logic)
        case_with_values = assign_comparison_values(merged_features)
        
        # Step 6: Add timestamps
        timestamp = datetime.now().isoformat()
        case_with_values['created_at'] = timestamp
        case_with_values['updated_at'] = timestamp
        
        processed_cases.append(case_with_values)
    
    return processed_cases

__all__ = [
    'case_batching',
    'process_cases',
    'extract_features',
    'assign_comparison_values',
    'extract_date_range',
    'extract_victim_count',
    'extract_case_demographics',
    'extract_perpetrator_demographics',
    'extract_relationship',
    'extract_previous_conviction',
    'extract_platforms',
    'extract_evidence_volume',
    'extract_investigation_info',
    'extract_prosecution_outcome',
    'extract_severity',
    'extract_topics',
    'extract_severity_phrases',
    'clean_urls_from_text',  # Backward compatibility
    'clean_artifacts_from_text',
    'MergeProcessing',      # Intersection class
    'merge_processing',     # Convenience function
    'NERExtractor',         # ML Processing Layer NER extractor
]
