"""
Ad-hoc demo script for SemanticSeverity on real case PDFs.

Usage (from repo root):
    python "src/Processing Layer/ML Processing Layer/test_semantic_extraction.py" \
        path/to/file1.pdf path/to/file2.pdf ... \
        [--min-score 0.35] [--top-k 10] [--max-cases 5] [-o results.json]

Will use AZICAC and Idaho ICAC PDFs; pass those 5 PDF paths
on the command line and this script will:
  1. Ingest PDFs via the Ingestion Layer
  2. Batch them using the same batching logic as the main pipeline
  3. Run SemanticConcepts on each case_text batch
  4. Print the semantic concept phrase scores for inspection, including
     which snippet of the case text drove each concept match
  5. Optionally write results to a JSON file (-o / --output)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Support running this file directly as a script (no package context)
try:
    from .semantic_concepts import SemanticConcepts, ConceptScore  # type: ignore[import]
except ImportError:
    from semantic_concepts import SemanticConcepts, ConceptScore  # type: ignore[import]

# Alias so existing references to SemanticSeverity still work in this file
SemanticSeverity = SemanticConcepts


# ------------------------------------------------------------------ #
# Dynamic module loaders (unchanged from original)
# ------------------------------------------------------------------ #

def _load_ingestion_module():
    """Dynamically load Ingestion Layer to avoid issues with spaces in paths."""
    import importlib.util

    src_dir = Path(__file__).resolve().parents[2]
    ingestion_path = src_dir / "Ingestion Layer" / "ingestion.py"

    if not ingestion_path.exists():
        raise FileNotFoundError(f"Ingestion module not found at {ingestion_path}")

    spec = importlib.util.spec_from_file_location("ingestion_layer", ingestion_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_batching_module():
    """Dynamically load shared batching module."""
    import importlib.util

    processing_layer_dir = Path(__file__).resolve().parents[1]
    batching_path = processing_layer_dir / "batching.py"

    if not batching_path.exists():
        raise FileNotFoundError(f"Batching module not found at {batching_path}")

    spec = importlib.util.spec_from_file_location("batching_module", batching_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ #
# Case construction
# ------------------------------------------------------------------ #

def _build_cases_from_df(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Mirror the batching behavior from processing.process_cases, but without
    running the full pattern/NER/merge stack.
    """
    batching_module = _load_batching_module()
    case_batching = getattr(batching_module, "case_batching")

    all_cases: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        extracted_text = row.get("extracted_text", "")
        source = row.get("source", "unknown")
        source_file = row.get("source_file", "unknown")

        org_name = source.lower() if source and source != "unknown" else "case"
        if org_name == "case" and source_file:
            org_match = re.search(r"([A-Z]+)", str(source_file))
            if org_match:
                org_name = org_match.group(1).lower()

        case_batches = case_batching(
            extracted_text,
            org_name=org_name,
            source=source,
            source_file=source_file,
        )

        for case_batch in case_batches:
            case_text = case_batch.get("case_text") or ""
            if not isinstance(case_text, str) or not case_text.strip():
                continue

            case: Dict[str, Any] = {
                "case_text": case_text,
                "month_year": case_batch.get("month_year"),
                "month": case_batch.get("month"),
                "year": case_batch.get("year"),
                "case_id": case_batch.get("case_id"),
                "source": source,
                "source_file": source_file,
            }
            if "state" in case_batch:
                case["state"] = case_batch["state"]

            all_cases.append(case)

    return all_cases


# ------------------------------------------------------------------ #
# Snippet matching — finds the case text sentence most aligned with
# each concept key, for ALL concepts (not just a hardcoded subset)
# ------------------------------------------------------------------ #

def _top_snippets_for_concept(
    detector: SemanticConcepts,
    text: str,
    concept_key: str,
    max_snippets: int = 1,
) -> List[Tuple[str, float]]:
    """
    Find the sentence(s) in `text` most semantically aligned with
    `concept_key` by comparing each sentence embedding to the
    precomputed concept embedding.

    Returns a list of (sentence, similarity_score) tuples.
    """
    if not text or not detector.is_available():
        return []

    concept_keys = getattr(detector, "_concept_keys", [])
    concept_embs = getattr(detector, "_concept_embeddings", None)
    if concept_embs is None or concept_key not in concept_keys:
        return []

    try:
        idx = concept_keys.index(concept_key)
    except ValueError:
        return []

    concept_vec = np.asarray(concept_embs[idx])

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return []

    sent_embs = detector.model.encode(  # type: ignore[attr-defined]
        sentences,
        normalize_embeddings=True,
    )
    sent_mat = np.asarray(sent_embs)
    sims = sent_mat @ concept_vec  # type: ignore[operator]

    pairs = sorted(zip(sentences, sims), key=lambda x: float(x[1]), reverse=True)
    return [(s, float(score)) for s, score in pairs[:max_snippets]]


def _truncate(text: str, max_len: int = 240) -> str:
    return text[:max_len - 3] + "..." if len(text) > max_len else text


# ------------------------------------------------------------------ #
# Concept API coverage tests
# These exercise every public promise of SemanticConcepts so that a
# single test run confirms the full contract is working end-to-end.
# ------------------------------------------------------------------ #

def _run_api_coverage_tests(detector: SemanticConcepts, sample_text: str) -> bool:
    """
    Exercise every public method of SemanticConcepts and print a
    pass/fail summary.  Returns True if all tests passed.
    """
    print("\n" + "=" * 60)
    print("SemanticConcepts API coverage tests")
    print("=" * 60)

    results: List[Tuple[str, bool, str]] = []  # (test_name, passed, detail)

    def check(name: str, condition: bool, detail: str = "") -> None:
        results.append((name, condition, detail))
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))

    # 1. is_available
    check("is_available()", detector.is_available(),
          "model and embeddings loaded")

    # 2. get_concept_scores — returns ConceptScore objects with .key and .score
    scores = detector.get_concept_scores(sample_text, min_score=0.0)
    check("get_concept_scores() returns list",
          isinstance(scores, list) and len(scores) > 0,
          f"{len(scores)} scores returned")
    check("get_concept_scores() items are ConceptScore",
          all(isinstance(s, ConceptScore) for s in scores),
          "")
    check("get_concept_scores() items have .key and .score",
          all(hasattr(s, "key") and hasattr(s, "score") for s in scores),
          "")
    check("get_concept_scores() sorted descending",
          all(scores[i].score >= scores[i + 1].score for i in range(len(scores) - 1)),
          "")
    check("get_concept_scores() min_score filter works",
          all(s.score >= 0.35 for s in detector.get_concept_scores(sample_text, min_score=0.35)),
          "")

    # 3. get_concepts — returns List[str]
    concepts = detector.get_concepts(sample_text, min_score=0.35)
    check("get_concepts() returns list of str",
          isinstance(concepts, list) and all(isinstance(k, str) for k in concepts),
          f"{len(concepts)} keys")
    concepts_topk = detector.get_concepts(sample_text, min_score=0.0, top_k=3)
    check("get_concepts() top_k respected",
          len(concepts_topk) <= 3,
          f"got {len(concepts_topk)}")

    # 4. enhance_case_with_concepts — writes ml_features.semantic_severity
    case: Dict[str, Any] = {"case_text": sample_text}
    detector.enhance_case_with_concepts(case, min_score=0.35)
    sem = case.get("ml_features", {}).get("semantic_severity", {})
    check("enhance_case_with_concepts() writes ml_features.semantic_severity",
          bool(sem),
          "")
    check("enhance_case_with_concepts() 'phrases' is list",
          isinstance(sem.get("phrases"), list),
          f"{len(sem.get('phrases', []))} phrases")
    check("enhance_case_with_concepts() 'scores' is dict",
          isinstance(sem.get("scores"), dict),
          "")
    check("enhance_case_with_concepts() 'concept_metadata' is dict",
          isinstance(sem.get("concept_metadata"), dict),
          "")
    check("enhance_case_with_concepts() no production_flag yet",
          "production_flag" not in sem,
          "production_flag should only appear after enhance_case_with_semantic_production")

    # concept_metadata only contains production-relevant keys
    for key, meta in sem.get("concept_metadata", {}).items():
        check(f"concept_metadata['{key}'] has 'is_production' bool",
              isinstance(meta.get("is_production"), bool),
              "")

    # 5. enhance_case_with_semantic_production — adds production_flag
    detector.enhance_case_with_semantic_production(case)
    sem2 = case.get("ml_features", {}).get("semantic_severity", {})
    check("enhance_case_with_semantic_production() adds 'production_flag'",
          "production_flag" in sem2,
          f"value={sem2.get('production_flag')}")
    check("enhance_case_with_semantic_production() adds 'production_flag_scores'",
          isinstance(sem2.get("production_flag_scores"), dict),
          f"{len(sem2.get('production_flag_scores', {}))} keys")
    pf = sem2.get("production_flag")
    check("production_flag is True, False, or None",
          pf is True or pf is False or pf is None,
          f"got {pf!r}")

    # 6. Empty / edge-case inputs
    check("get_concept_scores('') returns []",
          detector.get_concept_scores("") == [],
          "")
    check("enhance_case_with_concepts({}) returns {}",
          detector.enhance_case_with_concepts({}) == {},
          "")

    # 7. All configured concept keys are present in scores at min_score=0.0
    returned_keys = {s.key for s in detector.get_concept_scores(sample_text, min_score=0.0)}
    expected_keys = set(detector._concept_keys)
    check("all concept keys present in get_concept_scores(min_score=0.0)",
          expected_keys == returned_keys,
          f"missing={expected_keys - returned_keys}")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n  {passed}/{total} tests passed")
    print("=" * 60 + "\n")
    return passed == total


# ------------------------------------------------------------------ #
# Main demo runner
# ------------------------------------------------------------------ #

def run_demo(
    pdf_paths: List[str],
    min_score: float = 0.35,
    top_k: int = 10,
    max_cases: Optional[int] = None,
    output_path: Optional[str] = None,
) -> None:
    """End-to-end demo: ingest PDFs → batch → semantic concepts."""
    if not pdf_paths:
        raise ValueError("No PDF paths provided.")

    ingestion_module = _load_ingestion_module()
    ingest_multiple_pdfs = getattr(ingestion_module, "ingest_multiple_pdfs")

    print(f"Ingesting {len(pdf_paths)} PDF(s) via Ingestion Layer...")
    df = ingest_multiple_pdfs(pdf_paths)
    print(f"Ingested {len(df)} row(s) from PDFs.")

    print("Batching cases using shared batching module...")
    cases = _build_cases_from_df(df)
    print(f"Constructed {len(cases)} case batch(es).")

    if max_cases and max_cases > 0:
        cases = cases[:max_cases]
        print(f"Limiting to first {max_cases} case(s) (--max-cases).")

    print("Initializing SemanticConcepts (sentence-transformer backend)...")
    detector = SemanticConcepts()
    if not detector.is_available():
        print(
            "SemanticConcepts is not available (missing sentence-transformers, numpy, "
            "or model load failure). Install ML deps and try again."
        )
        return

    # Run API coverage tests against the first non-empty case text we find,
    # so we validate the full contract before printing per-case results.
    sample_text = next(
        (c.get("case_text", "") for c in cases if c.get("case_text", "").strip()),
        "",
    )
    if sample_text:
        _run_api_coverage_tests(detector, sample_text)

    print("\n=== Semantic concept phrases per case (only cases with matches) ===\n")

    json_output: List[Dict[str, Any]] = []

    for idx, case in enumerate(cases, start=1):
        source_file = case.get("source_file", "unknown")
        case_id = case.get("case_id") or str(idx)
        case_text = case.get("case_text", "")

        # Use the correct, current method name
        scores = detector.get_concept_scores(case_text, min_score=min_score)
        if not scores:
            continue

        if top_k and top_k > 0:
            scores = scores[:top_k]

        header = f"Case {idx} (case_id={case_id}, file={source_file})"
        print("=" * len(header))
        print(header)
        print("=" * len(header))
        print(f"Top {len(scores)} concept(s) (min_score={min_score:.2f}):")

        case_json: Dict[str, Any] = {
            "case_index": idx,
            "case_id": case_id,
            "source_file": source_file,
            "month_year": case.get("month_year"),
            "concepts": [],
        }

        for s in scores:
            # For EVERY matched concept, find the best-matching sentence
            snippets = _top_snippets_for_concept(detector, case_text, s.key, max_snippets=1)
            snippet_text = ""
            snippet_score = 0.0
            if snippets:
                snippet_text, snippet_score = snippets[0]

            print(f"  - {s.key:<30s}  concept_score={s.score:.3f}", end="")
            if snippet_text:
                print(f"  snippet_sim={snippet_score:.3f}")
                print(f"      ↳ \"{_truncate(snippet_text)}\"")
            else:
                print()

            case_json["concepts"].append({
                "key": s.key,
                "score": round(s.score, 4),
                "best_snippet": snippet_text,
                "snippet_similarity": round(snippet_score, 4),
            })

        print()
        json_output.append(case_json)

    # Write JSON output if requested
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(json_output, f, indent=2, ensure_ascii=False)
        print(f"Results written to {out} ({len(json_output)} case(s)).")


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run SemanticConcepts on batched case_text derived from real PDFs "
            "via the CaseLinker ingestion + batching pipeline."
        )
    )
    parser.add_argument(
        "pdfs",
        nargs="+",
        help="Paths to PDF files.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.35,
        help="Minimum cosine similarity to include a concept (default: 0.35).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Maximum number of concepts to show per case (default: 10).",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Maximum number of cases to process (default: all).",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Optional path to write JSON results (e.g. semantic_results.json).",
    )

    args = parser.parse_args()
    pdf_paths = [str(Path(p)) for p in args.pdfs]
    run_demo(
        pdf_paths,
        min_score=args.min_score,
        top_k=args.top_k,
        max_cases=args.max_cases,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()