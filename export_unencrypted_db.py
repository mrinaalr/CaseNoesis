"""
Export unencrypted database for Railway deployment
Railway doesn't have SQLCipher, so we need an unencrypted version
"""
import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent / "src" / "Storage Layer"))

try:
    from config import DATABASE_PATH, DB_ENCRYPTION_KEY, ENABLE_ENCRYPTION
    from storage import CaseStorage, SQLCIPHER_AVAILABLE
    
    if not SQLCIPHER_AVAILABLE:
        print("❌ SQLCipher not available. Cannot read encrypted database.")
        print("   Install SQLCipher to export database.")
        sys.exit(1)
    
    # Read encrypted database
    print("📖 Reading encrypted database...")
    encrypted_storage = CaseStorage(DATABASE_PATH, encryption_key=DB_ENCRYPTION_KEY)
    cases = encrypted_storage.get_all_cases()
    print(f"✓ Found {len(cases)} cases in encrypted database")
    
    # Write to unencrypted database
    unencrypted_path = "caselinker_unencrypted.db"
    print(f"\n💾 Writing to unencrypted database: {unencrypted_path}")
    unencrypted_storage = CaseStorage(unencrypted_path, encryption_key=None)
    
    stored = 0
    for case in cases:
        if unencrypted_storage.store_case(case):
            stored += 1
    
    print(f"✓ Stored {stored}/{len(cases)} cases in unencrypted database")
    print(f"\n✅ Unencrypted database created: {unencrypted_path}")
    print(f"   File size: {Path(unencrypted_path).stat().st_size:,} bytes")
    print(f"\n📝 For Railway: Rename this file to caselinker.db and push to GitHub")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
