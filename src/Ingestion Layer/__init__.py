"""
Ingestion Layer
Handles data import, validation, and basic cleaning
"""

from .ingestion import ingest_file, extract_pdf_text, ingest_multiple_pdfs

__all__ = ['ingest_file', 'extract_pdf_text', 'ingest_multiple_pdfs']
