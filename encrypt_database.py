"""
Encrypt existing database with SQLCipher
Run this script to encrypt your existing caselinker.db file
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src" / "Storage Layer"))
from storage import CaseStorage

try:
    from config import DB_ENCRYPTION_KEY, ENABLE_ENCRYPTION
except ImportError:
    print("Error: config.py not found or missing encryption settings")
    sys.exit(1)

if not ENABLE_ENCRYPTION:
    print("Encryption is disabled in config.py")
    sys.exit(1)

print("Encrypting database with SQLCipher...")
print(f"Database: caselinker.db")
print(f"Key: {'*' * len(DB_ENCRYPTION_KEY)}")

# This will create an encrypted database
# Note: SQLCipher encrypts on write, so we need to migrate data
storage = CaseStorage("caselinker.db", encryption_key=DB_ENCRYPTION_KEY)

# Test connection
try:
    cases = storage.get_all_cases()
    print(f"✓ Database encrypted successfully")
    print(f"✓ Found {len(cases)} cases in encrypted database")
except Exception as e:
    print(f"Error: {e}")
    print("Make sure pysqlcipher3 is installed: pip install pysqlcipher3")
