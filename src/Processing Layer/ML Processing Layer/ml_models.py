"""
ML Model Management

Purpose: Centralized management of ML models for the ML Processing Layer.
Handles model initialization, loading, and lifecycle management.

Design:
- Lazy loading: Models loaded on first use
- Graceful degradation: System works without ML models
- Model caching: Models loaded once and reused
"""

import warnings
from typing import Dict, Optional, Any
from pathlib import Path


class MLModelManager:
    """
    Manages ML model lifecycle for CaseLinker ML Processing Layer.
    
    Provides centralized access to ML models with lazy loading and
    graceful degradation if models are unavailable.
    
    Usage:
        ml_manager = MLModelManager(enable_ml=True)
        semantic_model = ml_manager.get_model('semantic')
        if semantic_model:
            # Use model
            pass
    """
    
    def __init__(self, enable_ml: bool = True):
        """
        Initialize ML Model Manager.
        
        Args:
            enable_ml: Whether to enable ML models. If False, all models return None.
        """
        self.enable_ml = enable_ml
        self.models: Dict[str, Any] = {}
        self.model_status: Dict[str, bool] = {}
        
        if enable_ml:
            self._check_dependencies()
    
    def _check_dependencies(self):
        """Check if ML dependencies are available."""
        self.dependencies_available = {
            'sentence_transformers': False,
            'spacy': False,
            'transformers': False,
        }
        
        # Check sentence-transformers
        try:
            import sentence_transformers
            self.dependencies_available['sentence_transformers'] = True
        except ImportError:
            pass
        
        # Check spacy (with error handling for Python 3.14+ compatibility issues)
        try:
            # Suppress warnings during import
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore")
                import spacy
            # If import succeeded, mark as available
            # (we'll catch actual usage errors later)
            self.dependencies_available['spacy'] = True
        except (ImportError, Exception) as e:
            # Catch all errors including pydantic compatibility issues with Python 3.14
            self.dependencies_available['spacy'] = False
        
        # Check transformers
        try:
            import transformers
            self.dependencies_available['transformers'] = True
        except ImportError:
            pass
    
    def get_model(self, model_name: str) -> Optional[Any]:
        """
        Get ML model by name. Models are lazy-loaded on first access.
        
        Args:
            model_name: Name of model ('semantic', 'ner', 'summarization')
            
        Returns:
            Model object or None if unavailable
        """
        if not self.enable_ml:
            return None
        
        # Return cached model if already loaded
        if model_name in self.models:
            return self.models[model_name]
        
        # Load model
        if model_name == 'semantic':
            return self._load_semantic_model()
        elif model_name == 'ner':
            return self._load_ner_model()
        elif model_name == 'summarization':
            return self._load_summarization_model()
        else:
            warnings.warn(f"Unknown model name: {model_name}")
            return None
    
    def _load_semantic_model(self):
        """Load sentence transformer model for semantic similarity."""
        if not self.dependencies_available.get('sentence_transformers'):
            warnings.warn("sentence-transformers not available. Install with: pip install sentence-transformers")
            self.model_status['semantic'] = False
            return None
        
        try:
            from sentence_transformers import SentenceTransformer
            
            # Use lightweight, fast model
            model = SentenceTransformer('all-MiniLM-L6-v2')
            self.models['semantic'] = model
            self.model_status['semantic'] = True
            return model
        except Exception as e:
            warnings.warn(f"Failed to load semantic model: {e}")
            self.model_status['semantic'] = False
            return None
    
    def _load_ner_model(self):
        """Load spaCy NER model."""
        if not self.dependencies_available.get('spacy'):
            warnings.warn("spacy not available. Install with: pip install spacy && python -m spacy download en_core_web_sm")
            self.model_status['ner'] = False
            return None
        
        try:
            import spacy
            
            # Try to load English model
            try:
                nlp = spacy.load("en_core_web_sm")
            except OSError:
                warnings.warn("spaCy English model not found. Run: python -m spacy download en_core_web_sm")
                self.model_status['ner'] = False
                return None
            
            self.models['ner'] = nlp
            self.model_status['ner'] = True
            return nlp
        except Exception as e:
            warnings.warn(f"Failed to load NER model: {e}")
            self.model_status['ner'] = False
            return None
    
    def _load_summarization_model(self):
        """Load summarization model for content sanitization."""
        if not self.dependencies_available.get('transformers'):
            warnings.warn("transformers not available. Install with: pip install transformers torch")
            self.model_status['summarization'] = False
            return None
        
        try:
            from transformers import pipeline
            
            # Use BART for summarization (good balance of quality and speed)
            # For production, consider facebook/bart-large-cnn
            # For faster inference, use google/pegasus-xsum
            summarizer = pipeline(
                "summarization",
                model="facebook/bart-large-cnn",
                device=-1,  # Use CPU (-1) or GPU (0, 1, ...)
                return_full_text=False
            )
            
            self.models['summarization'] = summarizer
            self.model_status['summarization'] = True
            return summarizer
        except Exception as e:
            warnings.warn(f"Failed to load summarization model: {e}")
            warnings.warn("Falling back to extractive summarization")
            
            # Fallback: Try extractive summarization
            try:
                from transformers import pipeline
                summarizer = pipeline(
                    "summarization",
                    model="google/pegasus-xsum",
                    device=-1
                )
                self.models['summarization'] = summarizer
                self.model_status['summarization'] = True
                return summarizer
            except Exception as e2:
                warnings.warn(f"Failed to load fallback summarization model: {e2}")
                self.model_status['summarization'] = False
                return None
    
    def is_model_available(self, model_name: str) -> bool:
        """Check if a model is available and loaded."""
        return self.model_status.get(model_name, False)
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all models."""
        return {
            'ml_enabled': self.enable_ml,
            'dependencies': self.dependencies_available,
            'model_status': self.model_status,
            'loaded_models': list(self.models.keys())
        }
    
    def clear_cache(self):
        """Clear model cache (useful for memory management)."""
        self.models.clear()
        self.model_status.clear()


# Global instance (optional - can create new instances as needed)
_global_ml_manager: Optional[MLModelManager] = None


def get_global_ml_manager(enable_ml: bool = True) -> MLModelManager:
    """Get or create global ML model manager instance."""
    global _global_ml_manager
    if _global_ml_manager is None:
        _global_ml_manager = MLModelManager(enable_ml=enable_ml)
    return _global_ml_manager
