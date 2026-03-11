"""
Merge Processing - Intersection class for Pattern and ML outputs

This class is the "intersection" layer that will eventually combine:
- Pattern Processing Layer: regex-based extraction (crimes, volume, phrases, prosecution)
- ML Processing Layer: NER / semantic extraction (ages, dates, orgs, locations, etc.)

For now (as requested), it **ignores all ML / NER input** and defaults
to the pattern-processing outputs only, so behavior is identical to the
current system. The ML results can optionally be attached under
`ml_features.ner_entities` for debugging/inspection.
"""

from typing import Dict, Any, List, Optional


class MergeProcessing:
    """
    Intersection class between Pattern Processing and ML (NER).

    Current behavior:
    - Returns pattern-processing results unchanged for all core fields
    - Optionally attaches raw NER entities under `ml_features.ner_entities`
    - Does **not** let NER override or change dates, agencies, ages, etc.
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
            Dict identical to pattern_features, with optional `ml_features`
            attached for debugging.
        """
        merged = pattern_features.copy()

        if ner_entities:
            # Attach raw NER output for inspection, but don't change any
            # of the existing pattern-based fields.
            ml_features = merged.get("ml_features", {}) or {}
            ml_features["ner_entities"] = ner_entities
            merged["ml_features"] = ml_features

        return merged


def merge_processing(
    pattern_features: Dict[str, Any],
    ner_entities: Optional[Dict[str, List[Any]]] = None,
) -> Dict[str, Any]:
    """
    Convenience function to merge pattern and NER features.

    Currently behaves as a no-op on core fields:
    - Returns a copy of pattern_features
    - Optionally attaches ner_entities under `ml_features.ner_entities`
    """
    merger = MergeProcessing()
    return merger.merge_features(pattern_features, ner_entities)

