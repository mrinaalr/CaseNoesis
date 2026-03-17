"""
Ad-hoc demo script for SemanticSeverity on real case PDFs.

Usage (from repo root):
    python "src/Processing Layer/ML Processing Layer/test_semantic_extraction.py" \
        path/to/file1.pdf path/to/file2.pdf ...

Will use AZICAC and Idaho ICAC PDFs; pass those 5 PDF paths
on the command line and this script will:
  1. Ingest PDFs via the Ingestion Layer
  2. Batch them using the same batching logic as the main pipeline
  3. Run SemanticSeverity on each case_text batch
  4. Print the semantic severity phrase scores for inspection
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

# Support running this file directly as a script (no package context)
try:
    # When executed as part of a package
    from .semantic_severity import SemanticSeverity  # type: ignore[import]
except ImportError:
    # When executed directly: fall back to plain import from same directory
    from semantic_severity import SemanticSeverity


def _load_ingestion_module():
    """Dynamically load Ingestion Layer to avoid issues with spaces in paths."""
    import importlib.util

    # .../src/Processing Layer/ML Processing Layer/test_semantic_extraction.py
    # parents[2] -> src
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

    # parents[1] -> "Processing Layer"
    processing_layer_dir = Path(__file__).resolve().parents[1]
    batching_path = processing_layer_dir / "batching.py"

    if not batching_path.exists():
        raise FileNotFoundError(f"Batching module not found at {batching_path}")

    spec = importlib.util.spec_from_file_location("batching_module", batching_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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

        # Match org_name logic used in processing.process_cases
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


def _top_snippets_for_concept(
    severity: SemanticSeverity,
    text: str,
    concept_key: str,
    max_snippets: int = 2,
) -> List[Tuple[str, float]]:
    """
    Heuristic: find sentences most aligned with a given concept.

    We:
      - split case_text into sentences
      - encode each sentence
      - compute cosine similarity to the concept embedding
      - return the top N sentences and their scores
    """
    if not text or not severity.is_available():
        return []

    # Access internal embeddings; safe for this ad-hoc analysis script.
    concept_keys = getattr(severity, "_concept_keys", [])
    concept_embs = getattr(severity, "_concept_embeddings", None)
    if concept_embs is None or concept_key not in concept_keys:
        return []

    try:
        idx = concept_keys.index(concept_key)
    except ValueError:
        return []

    concept_vec = np.asarray(concept_embs[idx])

    # Very simple sentence splitter is enough for these reports
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return []

    sent_embs = severity.model.encode(  # type: ignore[attr-defined]
        sentences,
        normalize_embeddings=True,
    )
    sent_mat = np.asarray(sent_embs)
    sims = sent_mat @ concept_vec  # type: ignore[operator]

    pairs = list(zip(sentences, sims))
    pairs.sort(key=lambda x: float(x[1]), reverse=True)
    top = pairs[:max_snippets]
    return [(s, float(score)) for s, score in top]


def run_demo(pdf_paths: List[str], min_score: float = 0.35, top_k: int = 10) -> None:
    """End-to-end demo: ingest PDFs → batch → semantic severity."""
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

    print("Initializing SemanticSeverity (sentence-transformer backend)...")
    severity = SemanticSeverity()
    if not severity.is_available():
        print(
            "SemanticSeverity is not available (missing sentence-transformers, numpy, "
            "or model load failure). Install ML deps and try again."
        )
        return

    print("\n=== Semantic severity phrases per case (only cases with matches) ===\n")
    for idx, case in enumerate(cases, start=1):
        source_file = case.get("source_file", "unknown")
        case_id = case.get("case_id") or f"{idx}"
        case_text = case.get("case_text", "")
        scores = severity.get_severity_scores(case_text, min_score=min_score)
        if not scores:
            continue

        if top_k and top_k > 0:
            scores = scores[:top_k]

        header = f"Case {idx} (case_id={case_id}, file={source_file})"
        print("=" * len(header))
        print(header)
        print("=" * len(header))

        print(f"Top {len(scores)} phrases (min_score={min_score:.2f}):")
        for s in scores:
            print(f"  - {s.key:15s}  score={s.score:.3f}")

            # For key phrases of interest, also show example sentence(s)
            if s.key in {"depictions", "abuse", "stated"}:
                snippets = _top_snippets_for_concept(severity, case_text, s.key, max_snippets=1)
                for snippet, snippet_score in snippets:
                    # Truncate long sentences for readability
                    if len(snippet) > 240:
                        snippet_display = snippet[:237] + "..."
                    else:
                        snippet_display = snippet
                    print(f"      ↳ e.g. ({snippet_score:.3f}): {snippet_display}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run SemanticSeverity on batched case_text derived from real PDFs "
            "via the CaseLinker ingestion + batching pipeline."
        )
    )
    parser.add_argument(
        "pdfs",
        nargs="+",
        help="Paths to PDF files (e.g., AZICAC and Idaho ICAC cases).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.35,
        help="Minimum cosine similarity to include a phrase (default: 0.35).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Maximum number of phrases to show per case (default: 10).",
    )

    args = parser.parse_args()
    pdf_paths = [str(Path(p)) for p in args.pdfs]
    run_demo(pdf_paths, min_score=args.min_score, top_k=args.top_k)


if __name__ == "__main__":
    main()

