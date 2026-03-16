"""
Authentication Middleware

Provides API key authentication for protected endpoints.
Can be disabled by not setting API_KEY environment variable.
"""

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from typing import Optional
import os

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)) -> bool:
    """
    Verify API key from header.
    
    Returns:
        True if valid, raises HTTPException if invalid
    
    Note: If API_KEY is not set, authentication is disabled (backward compatible)
    """
    expected_key = os.getenv("API_KEY")
    
    # If no API key configured, allow access (backward compatible for public demo)
    if not expected_key:
        return True
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Include X-API-Key header."
        )
    
    if api_key != expected_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key"
        )
    
    return True
