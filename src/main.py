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

from ingestion import ingest_pdf_from_user
from processing import process_cases
from storage import CaseStorage
import pandas as pd


def main():
    print("CaseLinker - Starting up...")
    print("\n✓ All layers loaded successfully!")
    
    print("\n" + "="*60)
    print("CaseLinker Pipeline: Ingest → Process → Store → Output")
    print("="*60)
    print("\nEnter PDF file path (or press Enter to use default test file)")
    print("Default: ../2014 Cases and Arrests – AZICAC.ORG.pdf")
    
    try:
        import sys
        if len(sys.argv) > 1:
            file_path = sys.argv[1]
            print(f"Using provided file: {file_path}")
        else:
            file_path = input("\nPDF file path: ").strip()
            
            if not file_path:
                file_path = "2014 Cases and Arrests – AZICAC.ORG.pdf"
                print(f"Using default: {file_path}")
        
        print("\n" + "="*60)
        print("Step 1: Ingesting PDF...")
        print("="*60)
        from ingestion import extract_pdf_text
        text = extract_pdf_text(file_path)
        print(f"✓ Extracted {len(text):,} characters")
        
        df = pd.DataFrame({
            'source_file': [file_path.split('/')[-1]],
            'extracted_text': [text],
            'source': ['AZICAC'],
        })
        
        print("\n" + "="*60)
        print("Step 2: Processing cases (splitting by month)...")
        print("="*60)
        cases = process_cases(df)
        print(f"✓ Found {len(cases)} cases")
        
        print("\n" + "="*60)
        print("Step 3: Storing cases in database...")
        print("="*60)
        try:
            from config import DATABASE_PATH, DB_ENCRYPTION_KEY, ENABLE_ENCRYPTION
            encryption_key = DB_ENCRYPTION_KEY if ENABLE_ENCRYPTION else None
        except ImportError:
            DATABASE_PATH = "caselinker.db"
            encryption_key = None
        storage = CaseStorage(DATABASE_PATH, encryption_key=encryption_key)
        stored_count = 0
        for case in cases:
            if storage.store_case(case):
                stored_count += 1
        print(f"✓ Stored {stored_count}/{len(cases)} cases in database")
        
        print("\n" + "="*60)
        print("Step 4: Cases in Database")
        print("="*60)
        all_stored_cases = storage.get_all_cases()
        print(f"✓ Total cases in database: {len(all_stored_cases)}")
        
        for i, case in enumerate(all_stored_cases, 1):
            print(f"\n--- Case {i} ---")
            print(f"ID: {case.get('id')}")
            print(f"Month/Year: {case.get('raw_data', {}).get('month_year', 'Unknown')}")
            print(f"Date Range: {case.get('date_range')}")
            case_text = case.get('raw_data', {}).get('case_text', '')
            if case_text:
                print(f"Text Preview: {case_text[:150]}...")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()    


if __name__ == "__main__":
    main()
