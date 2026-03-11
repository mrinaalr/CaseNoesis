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

# Import batching functions directly from batching module
_batching_path = Path(__file__).parent / "batching.py"
_batching_spec = importlib.util.spec_from_file_location("batching", _batching_path)
batching = importlib.util.module_from_spec(_batching_spec)
_batching_spec.loader.exec_module(batching)

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
process_cases = pattern_processing.process_cases
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
]
