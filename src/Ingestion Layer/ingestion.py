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

_EXTERNAL_PDF_NAME = "external.pdf"
from typing import Dict, List, Any, Optional
import warnings
import logging
import re

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
    logging.getLogger("pdfplumber").setLevel(logging.ERROR)
    # pdfplumber → pdfminer: suppress FontBBox / font descriptor noise on malformed PDFs
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
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
        Source organization name ('NCMEC', 'AZICAC', 'Idaho ICAC', 'Michigan ICAC', 'GBI', 'Texas AG', 'SVICAC',
        'TBI ICAC', 'SCAG ICAC', 'WCSO', 'LAPD', 'SOUTH FLORIDA ICAC', 'NJ AG', 'PA AG', 'VT AG', 'OHIO AG', 'UT AG', 'MS AG', 'NC SBI', 'LA AG', 'WY DCI', 'SD AG', 'KY SP', 'FBI', 'Other', or defaults to Other).
    """
    text_sample = text[:5000]  # Check first 5000 chars for efficiency
    filename_lower = filename.lower()
    
    # Default mixed-scrape PDF: canonical name → source Other (Case 1 : … batching)
    if Path(filename).name.lower() == _EXTERNAL_PDF_NAME:
        return "Other"

    # Check filename first
    if 'ncmec' in filename_lower or 'cybertipline' in filename_lower or 'cyber-tipline' in filename_lower:
        return 'NCMEC'
    elif 'gbi' in filename_lower:
        return 'GBI'
    elif 'texas' in filename_lower:
        return 'Texas AG'
    elif 'azicac' in filename_lower:
        return 'AZICAC'
    elif 'idaho' in filename_lower and 'icac' in filename_lower:
        return 'Idaho ICAC'
    elif 'michigan' in filename_lower and 'icac' in filename_lower:
        return 'Michigan ICAC'
    elif 'svicac' in filename_lower:
        return 'SVICAC'
    elif 'tbi' in filename_lower and 'icac' in filename_lower:
        return 'TBI ICAC'
    elif 'scag' in filename_lower and 'icac' in filename_lower:
        return 'SCAG ICAC'
    elif 'nysp' in filename_lower and 'icac' in filename_lower:
        return 'NEWYORK SP'
    elif ('illinois' in filename_lower or 'illnois' in filename_lower) and 'icac' in filename_lower:
        return 'ILLINOIS AG'
    elif 'wcso' in filename_lower:
        return 'WCSO'
    elif 'washoe' in filename_lower and 'icac' in filename_lower:
        return 'WCSO'
    elif 'lapd' in filename_lower:
        return 'LAPD'
    elif 'southflorida' in filename_lower and 'icac' in filename_lower:
        return 'SOUTH FLORIDA ICAC'
    elif ('njoag' in filename_lower or 'njag' in filename_lower) and 'icac' in filename_lower:
        return 'NJ AG'
    elif (
        ('paag' in filename_lower or 'pa_ag' in filename_lower or 'paoag' in filename_lower)
        and 'icac' in filename_lower
    ):
        return 'PA AG'
    elif 'pennsylvania' in filename_lower and 'icac' in filename_lower:
        return 'PA AG'
    elif (
        ('vtag' in filename_lower or 'vt_ag' in filename_lower or 'vtoag' in filename_lower or 'vermont' in filename_lower)
        and 'icac' in filename_lower
    ):
        return 'VT AG'
    elif ('ohioag' in filename_lower or 'ohio_ag' in filename_lower) and 'icac' in filename_lower:
        return 'OHIO AG'
    elif ('utag' in filename_lower or 'ut_ag' in filename_lower or 'utoag' in filename_lower) and 'icac' in filename_lower:
        return 'UT AG'
    elif ('msag' in filename_lower or 'ms_ag' in filename_lower or 'mississippi' in filename_lower) and 'icac' in filename_lower:
        return 'MS AG'
    elif ('ncsbi' in filename_lower or 'nc_sbi' in filename_lower) and 'icac' in filename_lower:
        return 'NC SBI'
    elif ('laag' in filename_lower or 'la_ag' in filename_lower or 'louisiana_ag' in filename_lower) and 'icac' in filename_lower:
        return 'LA AG'
    elif ('wydci' in filename_lower or 'wy_dci' in filename_lower or 'wyoming_dci' in filename_lower) and 'icac' in filename_lower:
        return 'WY DCI'
    elif ('sdag' in filename_lower or 'sd_ag' in filename_lower or 'south_dakota' in filename_lower) and 'icac' in filename_lower:
        return 'SD AG'
    elif ('kysp' in filename_lower or 'ksp_icac' in filename_lower or 'kentucky_sp' in filename_lower) and 'icac' in filename_lower:
        return 'KY SP'
    elif 'fbi' in filename_lower:
        return 'FBI'

    # Washoe County Sheriff site / newsroom ICAC scrape (merged PDF)
    if re.search(r'washoesheriff\.com', text_sample, re.I) and re.search(
        r'\bICAC\b|Internet Crimes Against Children', text_sample, re.I
    ):
        return 'WCSO'

    # LAPD Online site search (merged ICAC news PDF)
    if re.search(r'lapdonline\.org', text_sample, re.I) and re.search(
        r'\bICAC\b|Internet Crimes Against Children', text_sample, re.I
    ):
        return 'LAPD'

    # South Florida ICAC news index (merged external-article PDF)
    if re.search(r'southfloridaicac\.org', text_sample, re.I) and re.search(
        r'\bICAC\b|Internet Crimes Against Children', text_sample, re.I
    ):
        return 'SOUTH FLORIDA ICAC'

    # New Jersey Office of Attorney General site search / press (merged ICAC news PDF)
    if re.search(r'njoag\.gov', text_sample, re.I) and re.search(
        r'\bICAC\b|Internet Crimes Against Children', text_sample, re.I
    ):
        return 'NJ AG'

    # Vermont Attorney General (ago.vermont.gov — site search / press; merged ICAC news PDF)
    if re.search(r'ago\.vermont\.gov', text_sample, re.I) and re.search(
        r'\bICAC\b|Internet Crimes Against Children|Child Predator|child exploitation',
        text_sample,
        re.I,
    ):
        return 'VT AG'

    # Ohio Attorney General (ohioattorneygeneral.gov — news releases; merged ICAC news PDF)
    if re.search(r'ohioattorneygeneral\.gov', text_sample, re.I) and re.search(
        r'Attorney General|Internet Crimes|\bICAC\b|Human Trafficking|child pornography|Child Predator|exploitation',
        text_sample,
        re.I,
    ):
        return 'OHIO AG'

    # Utah Attorney General (attorneygeneral.utah.gov — WordPress search / press; merged ICAC news PDF)
    if re.search(r'attorneygeneral\.utah\.gov', text_sample, re.I) and re.search(
        r'\bICAC\b|Internet Crimes Against Children|Attorney General|child exploitation|Child Predator',
        text_sample,
        re.I,
    ):
        return 'UT AG'

    # Mississippi Attorney General (attorneygenerallynnfitch.com — press; merged ICAC news PDF)
    if re.search(r'attorneygenerallynnfitch\.com', text_sample, re.I) and re.search(
        r'Attorney General|Lynn Fitch|child exploitation|Child Exploitation|Internet Crimes|\bICAC\b',
        text_sample,
        re.I,
    ):
        return 'MS AG'

    # North Carolina State Bureau of Investigation (ncsbi.gov — news releases; merged ICAC news PDF)
    if re.search(r'ncsbi\.gov', text_sample, re.I) and re.search(
        r'State Bureau of Investigation|\bSBI\b|Internet Crimes Against Children|\bICAC\b|child exploitation|Child Exploitation',
        text_sample,
        re.I,
    ):
        return 'NC SBI'

    # Louisiana Office of the Attorney General (ag.state.la.us — news; merged ICAC news PDF)
    if re.search(r'ag\.state\.la\.us', text_sample, re.I) and re.search(
        r'Louisiana Bureau of Investigation|\bLBI\b|Attorney General|Murrill|child|Child Sexual|exploitation|ICAC|Cyber Crimes',
        text_sample,
        re.I,
    ):
        return 'LA AG'

    # Wyoming Division of Criminal Investigation (wyomingdci.wyo.gov — news; merged ICAC news PDF)
    if re.search(r'wyomingdci\.wyo\.gov', text_sample, re.I) and re.search(
        r'Division of Criminal Investigation|\bDCI\b|Wyoming|Computer Crime|\bICAC\b|Internet Crimes Against Children|'
        r'child exploitation|Child Porn|CSAM',
        text_sample,
        re.I,
    ):
        return 'WY DCI'

    # South Dakota Office of the Attorney General (atg.sd.gov — press releases; merged ICAC news PDF)
    if re.search(r'atg\.sd\.gov', text_sample, re.I) and re.search(
        r'South Dakota Attorney General|Attorney General Jackley|\bICAC\b|Internet Crimes Against Children|'
        r'Division of Criminal Investigation|\bDCI\b|Child Porn|child pornography|Child Exploitation',
        text_sample,
        re.I,
    ):
        return 'SD AG'

    # Kentucky State Police (kentuckystatepolice.ky.gov — WordPress news; merged ICAC news PDF)
    if re.search(r'kentuckystatepolice\.ky\.gov', text_sample, re.I) and re.search(
        r'Kentucky State Police|\bKSP\b|Electronic Crime Branch|\bICAC\b|Internet Crimes Against Children',
        text_sample,
        re.I,
    ):
        return 'KY SP'

    # Pennsylvania Office of Attorney General (attorneygeneral.gov — exclude other state AG domains)
    if re.search(r'attorneygeneral\.gov', text_sample, re.I) and not re.search(
        r'illinoisattorneygeneral|texasattorneygeneral|njoag\.gov|ohioattorneygeneral|attorneygeneral\.utah\.gov',
        text_sample,
        re.I,
    ) and re.search(
        r'Child Predator|Internet Crimes Against Children|\bICAC\b|Taking Action',
        text_sample,
        re.I,
    ):
        return 'PA AG'

    # Delimited "Case 1 : ... Case 2 : ..." scrapes (news, LinkedIn PDFs, etc.)
    if re.search(r'(?m)(?:^|\n)\s*Case\s+1\s*:', text_sample, re.IGNORECASE):
        return 'Other'

    # Default fallback
    return 'Other'  # Default to Other


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



