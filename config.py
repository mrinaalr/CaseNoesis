"""
Configuration file
Store settings and constants
"""

# Database
DATABASE_PATH = "caselinker.db"
GRAPH_DATABASE_PATH = "caselinker_graph.db"

# SQLCipher Encryption
# Set a strong password for production - this is for demo/research purposes
# If SQLCipher is not available, encryption will be disabled automatically
import os
DB_ENCRYPTION_KEY = "caselinker_research_key_2024"  # Change this in production!
# On Railway, disable encryption since SQLCipher isn't available
ENABLE_ENCRYPTION = True if not os.environ.get("RAILWAY_ENVIRONMENT") else False

# Clustering
SIMILARITY_THRESHOLD = 0.5
CLUSTERING_THRESHOLD = 0.5

# File paths
CASES_DIRECTORY = "Cases"
DATA_DIRECTORY = "data"

# API Server
API_HOST = "0.0.0.0"
API_PORT = 8000
API_RELOAD = True
