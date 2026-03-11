"""
Ingestion Layer

Purpose: Handle diverse, messy data sources and normalize them into a consistent format for processing.

Design Ideas from Architecture:
- Keep it very simple: parse file (start with text-based), simple pre-processing
- Nothing too fancy - just take the info from the source to the data processing layer
- Data validation & sanitization
- Basic cleaning, pandas-based
- Modular so can upload website/pdf
"""

import pandas as pd
from pathlib import Path
from typing import Dict, List, Any, Optional
import warnings
import logging
import re

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
    logging.getLogger("pdfplumber").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", category=UserWarning)
except ImportError:
    PDFPLUMBER_AVAILABLE = False


def detect_source_from_content(text: str, filename: str) -> str:
    """
    Detect source organization from file content and filename.
    Checks for NCMEC patterns (CT numbers, state headers) and AZICAC patterns.
    
    Args:
        text: Extracted text content
        filename: Name of the file
        
    Returns:
        Source organization name ('NCMEC', 'AZICAC', 'FBI', or 'unknown')
    """
    text_sample = text[:5000]  # Check first 5000 chars for efficiency
    filename_lower = filename.lower()
    
    # Check filename first
    if 'ncmec' in filename_lower:
        return 'NCMEC'
    elif 'azicac' in filename_lower:
        return 'AZICAC'
    elif 'fbi' in filename_lower:
        return 'FBI'
    
    
    # Default fallback
    return 'AZICAC'  # Default to AZICAC for backward compatibility


def extract_pdf_text(pdf_path: str) -> str:
    """
    Extract all text from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Extracted text as a string
    """
    if not PDFPLUMBER_AVAILABLE:
        raise ImportError("pdfplumber is required for PDF extraction. Install with: pip install pdfplumber")
    
    text_content = []
    
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_content.append(page_text)
        
        return "\n".join(text_content)
    except Exception as e:
        raise Exception(f"Error extracting text from PDF: {str(e)}")


def ingest_file(file_path: str, file_type: Optional[str] = None) -> pd.DataFrame:
    """
    Ingest a file and return a DataFrame.
    Supports PDF files (extracts text) and other formats as needed.
    
    Args:
        file_path: Path to the file to ingest
        file_type: Optional file type hint (e.g., 'pdf', 'csv', 'txt')
                   If None, will be inferred from file extension
        
    Returns:
        DataFrame with ingested data
    """
    path = Path(file_path)
    
    if file_type is None:
        file_type = path.suffix.lower().lstrip('.')
    
    if file_type == 'pdf':
        text = extract_pdf_text(str(path))
        source = detect_source_from_content(text, path.name)
        
        df = pd.DataFrame({
            'source_file': [path.name],
            'extracted_text': [text],
            'source': [source],
        })
        
        return df
    
    elif file_type == 'csv':
        return pd.read_csv(file_path)
    
    elif file_type == 'txt':
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        df = pd.DataFrame({
            'source_file': [path.name],
            'extracted_text': [text],
            'source': ['unknown'],
        })
        
        return df
    
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def ingest_multiple_pdfs(pdf_paths: List[str]) -> pd.DataFrame:
    """
    Ingest multiple PDF files and return a combined DataFrame.
    Each PDF is processed separately and combined into a single DataFrame.
    
    Args:
        pdf_paths: List of paths to PDF files
        
    Returns:
        DataFrame with ingested data from all PDFs
    """
    if not pdf_paths:
        raise ValueError("No PDF paths provided")
    
    all_data = []
    
    for pdf_path in pdf_paths:
        path = Path(pdf_path)
        
        if not path.exists():
            print(f"⚠️  Warning: File not found, skipping: {pdf_path}")
            continue
        
        if not path.suffix.lower() == '.pdf':
            print(f"⚠️  Warning: Not a PDF file, skipping: {pdf_path}")
            continue
        
        try:
            text = extract_pdf_text(str(path))
            
            # Detect source from content and filename
            org_name = detect_source_from_content(text, path.name)
            
            all_data.append({
                'source_file': path.name,
                'extracted_text': text,
                'source': org_name,
            })
            print(f"✓ Ingested: {path.name} ({len(text):,} characters) - Detected source: {org_name}")
            
        except Exception as e:
            print(f"❌ Error processing {path.name}: {e}")
            continue
    
    if not all_data:
        raise ValueError("No PDFs were successfully ingested")
    
    df = pd.DataFrame(all_data)
    return df



