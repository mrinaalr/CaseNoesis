"""
Configuration file
Store settings and constants
"""

# Database
DATABASE_PATH = "caselinker.db"
GRAPH_DATABASE_PATH = "caselinker_graph.db"

# Database Encryption (deprecated - using plain SQLite for MVP)
# Encryption removed for MVP to ensure compatibility across all platforms
DB_ENCRYPTION_KEY = None
ENABLE_ENCRYPTION = False

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
