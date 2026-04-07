"""
CaseLinker - main code
Simple pipeline: ingest -> process -> analyze -> store -> visualize
"""

import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

src_path = Path(__file__).parent
sys.path.insert(0, str(src_path / "Ingestion Layer"))
sys.path.insert(0, str(src_path / "Processing Layer"))
sys.path.insert(0, str(src_path / "Storage Layer"))
sys.path.insert(0, str(src_path / "Clustering & Analysis Layer"))
sys.path.insert(0, str(src_path / "Visualization Layer"))

from processing import process_cases
import os
import re

# Use PostgreSQL if DATABASE_URL is set, otherwise use SQLite
if os.getenv("DATABASE_URL"):
    try:
        from storage_postgres import CaseStorage
        print("✅ Using PostgreSQL database for storage")
    except ImportError:
        print("⚠️  PostgreSQL storage not available, falling back to SQLite")
        from storage import CaseStorage
else:
    from storage import CaseStorage
    print("✅ Using SQLite database for storage")


def main():
    print("CaseLinker - Starting up...")
    print("\n✓ All layers loaded successfully!")
    
    print("\n" + "="*60)
    print("CaseLinker Pipeline: Ingest → Process → Store → Output")
    print("="*60)
    print("\nEnter PDF file path(s) - separate multiple files with spaces")
    print("Or press Enter to use default test file")
    print("Default: 2014 Cases and Arrests – AZICAC.ORG.pdf")
    
    try:
        if len(sys.argv) > 1:
            # Multiple files provided as command line arguments
            file_paths = sys.argv[1:]
            print(f"\nUsing {len(file_paths)} provided file(s):")
            for fp in file_paths:
                print(f"  - {fp}")
        else:
            user_input = input("\nPDF file path(s): ").strip()
            
            if not user_input:
                file_paths = ["2014 Cases and Arrests – AZICAC.ORG.pdf"]
                print(f"Using default: {file_paths[0]}")
            else:
                # Split by spaces to handle multiple files
                file_paths = user_input.split()
                print(f"\nProcessing {len(file_paths)} file(s)...")
        
        print("\n" + "="*60)
        print("Step 1: Ingesting PDF(s)...")
        print("="*60)
        from ingestion import ingest_multiple_pdfs
        
        if len(file_paths) == 1:
            # Single file - route through ingestion helper so source_url fallback is applied.
            from ingestion import ingest_file
            df = ingest_file(file_paths[0], file_type='pdf')
            text = str(df.iloc[0].get('extracted_text', '') or '')
            source = str(df.iloc[0].get('source', 'unknown') or 'unknown')
            source_url = df.iloc[0].get('source_url')
            print(f"✓ Extracted {len(text):,} characters from {file_paths[0]}")
            print(f"✓ Detected source: {source}")
            if source_url:
                print(f"✓ Source URL: {source_url}")
        else:
            # Multiple files
            df = ingest_multiple_pdfs(file_paths)
            print(f"\n✓ Successfully ingested {len(df)} PDF file(s)")
        
        print("\n" + "="*60)
        print("Step 2: Processing cases (batch, extract features, merge ml and pattern approaches)...")
        print("="*60)
        cases = process_cases(df)
        print(f"✓ Found {len(cases)} cases across all PDFs")
        
        print("\n" + "="*60)
        print("Step 3: Storing cases in database...")
        print("="*60)
        db_path = get_database_path()
        stored_count = store_cases(cases, db_path)
        print(f"✓ Stored {stored_count}/{len(cases)} cases in database")
        
        print("\n" + "="*60)
        print("Step 4: Summary")
        print("="*60)
        all_stored_cases = get_all_stored_cases(db_path)
        print(f"✓ Total cases in database: {len(all_stored_cases)}")
        
        # Show breakdown by source
        sources = {}
        for case in all_stored_cases:
            source = case.get('source', 'Unknown')
            sources[source] = sources.get(source, 0) + 1
        
        print("\nCases by source:")
        for source, count in sorted(sources.items()):
            print(f"  - {source}: {count} cases")
        
        # Pre-compute clusters after storing cases
        print("\n" + "="*60)
        print("Step 5: Pre-computing clusters...")
        print("="*60)
        try:
            from analysis import run_automated_analysis
            cluster_data = run_automated_analysis(all_stored_cases)
            if db_path:
                storage = CaseStorage(db_path)  # SQLite
            else:
                storage = CaseStorage()  # PostgreSQL
            storage.store_precomputed_clusters(cluster_data, len(all_stored_cases))
            print(f"✓ Pre-computed clusters stored ({len(all_stored_cases)} cases)")
        except Exception as e:
            print(f"⚠️  Warning: Could not pre-compute clusters: {e}")
            import traceback
            traceback.print_exc()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()    



def get_database_path() -> Optional[str]:
    """
    Get database path from config or use default.
    Returns None if using PostgreSQL (DATABASE_URL set).
    
    Returns:
        Path to database file (SQLite) or None (PostgreSQL)
    """
    if os.getenv("DATABASE_URL"):
        return None  # PostgreSQL doesn't use file path
    try:
        from config import DATABASE_PATH
        return DATABASE_PATH
    except ImportError:
        return "caselinker.db"


def store_cases(cases: List[Dict[str, Any]], db_path: Optional[str]) -> int:
    """
    Store cases in the database.
    
    This abstracts storage operations to maintain layer boundaries.
    The main orchestration layer doesn't need to know about storage
    implementation details.
    
    Args:
        cases: List of case dictionaries to store
        db_path: Path to database file (SQLite) or None (PostgreSQL)
        
    Returns:
        Number of successfully stored cases
    """
    if db_path:
        storage = CaseStorage(db_path)  # SQLite
    else:
        storage = CaseStorage()  # PostgreSQL (uses DATABASE_URL)
    
    cases_to_store = _filter_doj_cases_by_novelty(cases, storage)

    stored_count = 0
    for case in cases_to_store:
        if storage.store_case(case):
            stored_count += 1
    return stored_count


def _normalize_text_for_exact_match(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _filter_doj_cases_by_novelty(
    incoming_cases: List[Dict[str, Any]],
    storage: "CaseStorage",
    similarity_threshold: float = 0.98,
) -> List[Dict[str, Any]]:
    """
    DOJ-only guardrail:
      a) skip exact narrative matches already in DB
      b) skip if similarity to any existing case is >= threshold

    Non-DOJ cases pass through unchanged.
    """
    if not incoming_cases:
        return incoming_cases

    # Separate DOJ from all other sources; only DOJ gets novelty gating.
    doj_sources = {"DOJ CEOS"}
    doj_cases = [c for c in incoming_cases if str(c.get("source", "")).upper() in doj_sources]
    non_doj_cases = [c for c in incoming_cases if str(c.get("source", "")).upper() not in doj_sources]
    if not doj_cases:
        return incoming_cases

    try:
        from analysis import calculate_case_similarity
    except Exception:
        # If similarity module unavailable, keep only exact-match guard.
        calculate_case_similarity = None

    existing_cases = storage.get_all_cases(include_raw_data=True)
    existing_norm_texts = set()
    for ex in existing_cases:
        t = ex.get("case_text")
        if not t and isinstance(ex.get("raw_data"), dict):
            t = ex.get("raw_data", {}).get("case_text")
        nt = _normalize_text_for_exact_match(t)
        if nt:
            existing_norm_texts.add(nt)

    kept_doj: List[Dict[str, Any]] = []
    dropped_exact = 0
    dropped_similar = 0

    # Include already-kept DOJ cases in similarity pool to prevent duplicates within same run.
    similarity_pool = list(existing_cases)
    seen_new_norm = set()

    for c in doj_cases:
        c_text = c.get("case_text")
        if not c_text and isinstance(c.get("raw_data"), dict):
            c_text = c.get("raw_data", {}).get("case_text")
        ntext = _normalize_text_for_exact_match(c_text)
        if not ntext:
            # If no text, treat as low-confidence and skip.
            dropped_exact += 1
            continue
        if ntext in existing_norm_texts or ntext in seen_new_norm:
            dropped_exact += 1
            continue

        if calculate_case_similarity is not None:
            max_sim = 0.0
            for ex in similarity_pool:
                try:
                    sim = float(calculate_case_similarity(c, ex))
                except Exception:
                    sim = 0.0
                if sim > max_sim:
                    max_sim = sim
                if max_sim >= similarity_threshold:
                    break
            if max_sim >= similarity_threshold:
                dropped_similar += 1
                continue

        kept_doj.append(c)
        similarity_pool.append(c)
        seen_new_norm.add(ntext)

    if dropped_exact or dropped_similar:
        print(
            f"✓ DOJ novelty filter: kept {len(kept_doj)}/{len(doj_cases)} "
            f"(dropped exact={dropped_exact}, similar={dropped_similar}, threshold={similarity_threshold:.2f})"
        )

    return non_doj_cases + kept_doj


def get_all_stored_cases(db_path: Optional[str]) -> List[Dict[str, Any]]:
    """
    Retrieve all cases from the database.
    
    Args:
        db_path: Path to database file (SQLite) or None (PostgreSQL)
        
    Returns:
        List of all case dictionaries
    """
    if db_path:
        storage = CaseStorage(db_path)  # SQLite
    else:
        storage = CaseStorage()  # PostgreSQL (uses DATABASE_URL)
    return storage.get_all_cases()



if __name__ == "__main__":
    main()
