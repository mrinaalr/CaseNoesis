"""
Test ML Processing - Semantic Severity Phrases

This script loads cases from the database, runs semantic severity phrase
extraction, and shows what phrases we would store in the DB.

Primary goal: sanity-check that we can get **semantic** severity phrases
for AZICAC cases (instead of relying only on regex).

Usage:
    python3 test_semantic_severity.py [--db caselinker.db] [--limit 47]
"""

import sys
import json
from pathlib import Path
from typing import Any, Dict, List

import argparse

# Add paths for imports (reuse pattern from test_ml.py)
src_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(src_path / "Storage Layer"))
sys.path.insert(0, str(src_path / "Processing Layer"))

from storage import CaseStorage  # type: ignore  # noqa: E402
from semantic_severity import SemanticSeverity  # type: ignore  # noqa: E402
from ml_models import get_global_ml_manager  # type: ignore  # noqa: E402


def get_case_text(case: Dict[str, Any]) -> str:
    """Get case text from common locations."""
    if case.get("case_text"):
        return str(case["case_text"])
    raw = case.get("raw_data")
    if isinstance(raw, dict) and raw.get("case_text"):
        return str(raw["case_text"])
    extracted = case.get("extracted_features")
    if isinstance(extracted, dict) and extracted.get("case_text"):
        return str(extracted["case_text"])
    return ""


def show_case_semantic_severity(case: Dict[str, Any], detector: SemanticSeverity) -> Dict[str, Any]:
    """Run semantic severity on a single case and print results."""
    case_id = case.get("id", "unknown")
    source = case.get("source", "unknown")

    print("\n" + "=" * 80)
    print(f"Case ID: {case_id}")
    print(f"Source: {source}")
    print("=" * 80)

    text = get_case_text(case)
    if not text:
        print("⚠️  No case text found; skipping semantic severity.")
        return case

    preview = text[:240] + "..." if len(text) > 240 else text
    print("\nCase Text Preview:")
    print(preview)

    enhanced = detector.enhance_case_with_semantic_severity(case)
    ml_features = enhanced.get("ml_features", {})
    semantic = ml_features.get("semantic_severity", {})
    phrases = semantic.get("phrases", [])
    scores = semantic.get("scores", {})

    print("\nSemantic Severity Phrases:")
    if not phrases:
        print("  (none above threshold)")
    else:
        for key in phrases:
            print(f"  - {key}: score={scores.get(key, 0.0):.3f}")

    print("\nWhat would be stored in extracted_features['ml_features']['semantic_severity']:")
    print(json.dumps(semantic, indent=2))

    return enhanced


def main() -> None:
    parser = argparse.ArgumentParser(description="Test semantic severity phrases on cases")
    parser.add_argument("--db", type=str, default="caselinker.db", help="Database path (default: caselinker.db)")
    parser.add_argument(
        "--limit",
        type=int,
        default=47,
        help="Max number of AZICAC cases to process (default: 47)",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="AZICAC",
        help="Source filter for cases (default: AZICAC)",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("ML Processing Test - Semantic Severity Phrases")
    print("=" * 80)

    # Initialize semantic model via global ML manager
    ml_manager = get_global_ml_manager(enable_ml=True)
    semantic_model = ml_manager.get_model("semantic")

    detector = SemanticSeverity(semantic_model=semantic_model)
    if not detector.is_available():
        print("\n❌ Semantic severity not available (missing sentence-transformers or numpy).")
        print("   Install dependencies with:")
        print("     pip install -r requirements-ml.txt")
        print("   or at minimum:")
        print("     pip install sentence-transformers numpy")
        sys.exit(1)

    # Load cases
    print(f"\nLoading cases from database: {args.db}")
    storage = CaseStorage(args.db)
    all_cases = storage.get_all_cases(include_raw_data=True)

    if not all_cases:
        print("❌ No cases found in database.")
        print("Run src/main.py to process PDFs and populate the database first.")
        sys.exit(1)

    # Filter AZICAC (or provided source) and cap at limit
    filtered = [c for c in all_cases if c.get("source") == args.source]
    if not filtered:
        print(f"⚠️  No cases found with source='{args.source}'.")
        print("    Available sources in DB may differ (e.g., 'AZICAC Cases').")
        print("    Adjust --source accordingly.")
        sys.exit(1)

    cases_to_process = filtered[: args.limit]
    print(f"✓ Loaded {len(all_cases)} total cases, {len(filtered)} from source='{args.source}'")
    print(f"✓ Will process {len(cases_to_process)} case(s) for semantic severity phrases\n")

    enhanced_cases: List[Dict[str, Any]] = []
    for idx, case in enumerate(cases_to_process, start=1):
        print(f"\n[{idx}/{len(cases_to_process)}]")
        enhanced = show_case_semantic_severity(case, detector)
        enhanced_cases.append(enhanced)

    # Simple summary
    total_phrases = 0
    phrase_counts: Dict[str, int] = {}
    for case in enhanced_cases:
        ml_features = case.get("ml_features", {})
        semantic = ml_features.get("semantic_severity", {})
        phrases = semantic.get("phrases", []) or []
        total_phrases += len(phrases)
        for p in phrases:
            phrase_counts[p] = phrase_counts.get(p, 0) + 1

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Processed {len(enhanced_cases)} case(s)")
    print(f"Total semantic severity phrase hits: {total_phrases}")
    if phrase_counts:
        print("\nPhrase frequencies across processed cases:")
        for key, count in sorted(phrase_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  - {key}: {count}")
    else:
        print("\nNo semantic severity phrases above threshold were found.")

    print("\n✅ Semantic severity test complete.")


if __name__ == "__main__":
    main()

