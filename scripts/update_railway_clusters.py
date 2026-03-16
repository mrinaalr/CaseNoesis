#!/usr/bin/env python3
"""Quick script to update clusters on Railway PostgreSQL."""
import os
import sys
from pathlib import Path

# Set Railway DATABASE_URL
DATABASE_URL = "postgresql://postgres:scgdFtTSwwlLVsmOhAlNOlToHqMlNiwo@centerbeam.proxy.rlwy.net:58125/railway"
os.environ["DATABASE_URL"] = DATABASE_URL

# Add paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src" / "Storage Layer"))
sys.path.insert(0, str(project_root / "src" / "Clustering & Analysis Layer"))

from storage_postgres import CaseStorage
from analysis import run_automated_analysis

print("🔄 Updating clusters on Railway PostgreSQL...")

# Get storage
storage = CaseStorage()

# Load cases
print("📂 Loading cases...")
cases = storage.get_all_cases(include_raw_data=False)
print(f"✅ Loaded {len(cases)} cases")

if len(cases) == 0:
    print("❌ No cases found!")
    sys.exit(1)

# Clear old clusters
print("🗑️  Clearing old clusters...")
storage.clear_precomputed_clusters()

# Re-compute clusters
print("🔄 Re-computing clusters...")
cluster_data = run_automated_analysis(cases)

# Store clusters
print("💾 Storing clusters...")
storage.store_precomputed_clusters(cluster_data, len(cases))

print(f"✅ Successfully updated clusters for {len(cases)} cases")
