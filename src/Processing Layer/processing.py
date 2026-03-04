"""
Processing Layer - Backward Compatibility Module

This module provides backward compatibility for imports like:
    from processing import process_cases

It re-exports all functions from the Pattern Processing Layer.
"""

# Re-export everything from Pattern Processing Layer
# Handle spaces in directory name using importlib
import importlib.util
from pathlib import Path

_pattern_processing_path = Path(__file__).parent / "Pattern Processing Layer" / "processing.py"
spec = importlib.util.spec_from_file_location("pattern_processing", _pattern_processing_path)
pattern_processing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pattern_processing)

# Import all functions directly from the loaded module
case_batching = pattern_processing.case_batching
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
clean_urls_from_text = pattern_processing.clean_artifacts_from_text  # Backward compatibility alias
clean_artifacts_from_text = pattern_processing.clean_artifacts_from_text

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
