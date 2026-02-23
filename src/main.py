"""
CaseLinker - main code
Simple pipeline: ingest -> process -> analyze -> store -> visualize
"""

import sys
from pathlib import Path

src_path = Path(__file__).parent
sys.path.insert(0, str(src_path / "Ingestion Layer"))
sys.path.insert(0, str(src_path / "Processing Layer"))
sys.path.insert(0, str(src_path / "Storage Layer"))
sys.path.insert(0, str(src_path / "Clustering & Analysis Layer"))
sys.path.insert(0, str(src_path / "Visualization Layer"))

from processing import process_cases
from storage import CaseStorage
import pandas as pd


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
            # Single file - use simpler approach
            from ingestion import extract_pdf_text
            text = extract_pdf_text(file_paths[0])
            print(f"✓ Extracted {len(text):,} characters from {file_paths[0]}")
            
            df = pd.DataFrame({
                'source_file': [file_paths[0].split('/')[-1]],
                'extracted_text': [text],
                'source': ['AZICAC'],
            })
        else:
            # Multiple files
            df = ingest_multiple_pdfs(file_paths)
            print(f"\n✓ Successfully ingested {len(df)} PDF file(s)")
        
        print("\n" + "="*60)
        print("Step 2: Processing cases (splitting by month)...")
        print("="*60)
        cases = process_cases(df)
        print(f"✓ Found {len(cases)} cases across all PDFs")
        
        print("\n" + "="*60)
        print("Step 3: Storing cases in database...")
        print("="*60)
        try:
            from config import DATABASE_PATH
        except ImportError:
            DATABASE_PATH = "caselinker.db"
        storage = CaseStorage(DATABASE_PATH)
        stored_count = 0
        for case in cases:
            if storage.store_case(case):
                stored_count += 1
        print(f"✓ Stored {stored_count}/{len(cases)} cases in database")
        
        print("\n" + "="*60)
        print("Step 4: Summary")
        print("="*60)
        all_stored_cases = storage.get_all_cases()
        print(f"✓ Total cases in database: {len(all_stored_cases)}")
        
        # Show breakdown by source
        sources = {}
        for case in all_stored_cases:
            source = case.get('source', 'Unknown')
            sources[source] = sources.get(source, 0) + 1
        
        print("\nCases by source:")
        for source, count in sorted(sources.items()):
            print(f"  - {source}: {count} cases")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()    


if __name__ == "__main__":
    main()
