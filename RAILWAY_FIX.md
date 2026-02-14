# Railway Database Fix

## Problem
Railway doesn't have SQLCipher installed, so it can't read the encrypted `caselinker.db` file. This causes Railway to create a new empty database, showing 0 cases.

## Solution Options

### Option 1: Create Unencrypted Database (Recommended for Railway)

If you have SQLCipher installed locally:

```bash
# Run the export script
python3 export_unencrypted_db.py

# This creates caselinker_unencrypted.db
# Rename it and push:
mv caselinker_unencrypted.db caselinker.db
git add caselinker.db
git commit -m "Add unencrypted database for Railway"
git push
```

### Option 2: Disable Encryption on Railway

Update `config.py` to detect Railway and disable encryption:

```python
import os
ENABLE_ENCRYPTION = True if not os.environ.get("RAILWAY_ENVIRONMENT") else False
```

Then push the encrypted database - Railway will create a new unencrypted one automatically.

### Option 3: Install SQLCipher on Railway (Complex)

Add a `nixpacks.toml` or build script to install SQLCipher system libraries. This is more complex.

## Current Status
The code now detects when SQLCipher isn't available and will create a new unencrypted database automatically on Railway. However, this means Railway starts with 0 cases until you process PDFs there.
