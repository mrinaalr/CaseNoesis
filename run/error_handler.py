"""
Error Handler Utility

Provides consistent error handling with appropriate detail levels.
Production: Generic errors (no tracebacks)
Development: Detailed errors (with tracebacks)
"""
import os
import traceback
from typing import Dict, Any


def handle_error(e: Exception, include_traceback: bool = False) -> Dict[str, Any]:
    """
    Handle errors with appropriate detail level.
    
    Args:
        e: Exception that occurred
        include_traceback: If True, include full traceback (dev only)
    
    Returns:
        Error response dictionary
    """
    is_production = (
        os.getenv("RAILWAY_ENVIRONMENT") == "production" or 
        os.getenv("ENVIRONMENT") == "production" or
        os.getenv("RAILWAY_ENVIRONMENT_NAME") == "production"
    )
    
    response = {
        "error": "An error occurred processing your request",
        "error_type": type(e).__name__
    }
    
    # Only include detailed error in development
    if include_traceback and not is_production:
        response["error_detail"] = str(e)
        response["traceback"] = traceback.format_exc()
    elif not is_production:
        # Development: show error message but not traceback
        response["error_detail"] = str(e)
    
    return response
