"""
Semantic Similarity Module

Purpose: Generate semantic embeddings and calculate similarity between cases
using transformer-based sentence embeddings.

This complements the existing regex-based similarity by understanding
semantic meaning, not just keyword matching.

Usage:
    from ml_models import MLModelManager
    from semantic_similarity import SemanticSimilarity
    
    ml_manager = MLModelManager(enable_ml=True)
    semantic_model = ml_manager.get_model('semantic')
    
    if semantic_model:
        similarity = SemanticSimilarity(semantic_model)
        embedding = similarity.get_case_embedding(case_text)
        similarity_score = similarity.calculate_similarity(case1_text, case2_text)
"""

import warnings
from typing import Dict, List, Any, Optional, Tuple
import numpy as np


class SemanticSimilarity:
    """
    Semantic similarity calculator using sentence transformers.
    
    Generates embeddings for case text and calculates cosine similarity
    between cases for better semantic understanding.
    """
    
    def __init__(self, model=None):
        """
        Initialize semantic similarity calculator.
        
        Args:
            model: SentenceTransformer model instance. If None, will try to load.
        """
        self.model = model
        if model is None:
            warnings.warn("No model provided. Semantic similarity will not work.")
    
    def get_case_embedding(self, case_text: str) -> Optional[List[float]]:
        """
        Generate semantic embedding for case text.
        
        Args:
            case_text: Raw case text
            
        Returns:
            Embedding vector (list of floats) or None if model unavailable
        """
        if not self.model or not case_text:
            return None
        
        try:
            # Generate embedding
            embedding = self.model.encode(case_text, convert_to_numpy=True)
            # Convert to list for JSON serialization
            return embedding.tolist()
        except Exception as e:
            warnings.warn(f"Error generating embedding: {e}")
            return None
    
    def get_case_embeddings_batch(self, case_texts: List[str]) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple cases (batch processing).
        
        Args:
            case_texts: List of case text strings
            
        Returns:
            List of embedding vectors (or None for failed cases)
        """
        if not self.model or not case_texts:
            return [None] * len(case_texts)
        
        try:
            # Batch encode for efficiency
            embeddings = self.model.encode(
                case_texts,
                convert_to_numpy=True,
                show_progress_bar=False
            )
            # Convert to list of lists
            return [emb.tolist() for emb in embeddings]
        except Exception as e:
            warnings.warn(f"Error in batch embedding generation: {e}")
            return [None] * len(case_texts)
    
    def calculate_similarity(self, text1: str, text2: str) -> Optional[float]:
        """
        Calculate cosine similarity between two texts.
        
        Args:
            text1: First case text
            text2: Second case text
            
        Returns:
            Similarity score between 0.0 and 1.0, or None if unavailable
        """
        if not self.model or not text1 or not text2:
            return None
        
        try:
            # Generate embeddings
            embeddings = self.model.encode([text1, text2], convert_to_numpy=True)
            
            # Calculate cosine similarity
            from sklearn.metrics.pairwise import cosine_similarity
            similarity = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
            
            return float(similarity)
        except Exception as e:
            warnings.warn(f"Error calculating similarity: {e}")
            return None
    
    def calculate_similarity_from_embeddings(
        self,
        embedding1: List[float],
        embedding2: List[float]
    ) -> Optional[float]:
        """
        Calculate cosine similarity from pre-computed embeddings.
        
        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector
            
        Returns:
            Similarity score between 0.0 and 1.0, or None if invalid
        """
        if not embedding1 or not embedding2:
            return None
        
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            similarity = cosine_similarity([embedding1], [embedding2])[0][0]
            return float(similarity)
        except Exception as e:
            warnings.warn(f"Error calculating similarity from embeddings: {e}")
            return None
    
    def find_similar_cases(
        self,
        target_case: Dict[str, Any],
        all_cases: List[Dict[str, Any]],
        top_k: int = 5,
        similarity_threshold: float = 0.5
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Find most similar cases to target case using semantic similarity.
        
        Args:
            target_case: Target case dictionary
            all_cases: List of all cases to search
            top_k: Number of similar cases to return
            similarity_threshold: Minimum similarity score (0.0-1.0)
            
        Returns:
            List of tuples: (case_dict, similarity_score), sorted by similarity
        """
        if not self.model:
            return []
        
        # Get target case text
        target_text = (
            target_case.get('case_text', '') or
            target_case.get('raw_data', {}).get('case_text', '') or
            ''
        )
        
        if not target_text:
            return []
        
        # Generate target embedding
        target_embedding = self.get_case_embedding(target_text)
        if not target_embedding:
            return []
        
        # Calculate similarities
        similarities = []
        for case in all_cases:
            # Skip self
            if case.get('id') == target_case.get('id'):
                continue
            
            # Get case text
            case_text = (
                case.get('case_text', '') or
                case.get('raw_data', {}).get('case_text', '') or
                ''
            )
            
            if not case_text:
                continue
            
            # Generate embedding and calculate similarity
            case_embedding = self.get_case_embedding(case_text)
            if case_embedding:
                similarity = self.calculate_similarity_from_embeddings(
                    target_embedding,
                    case_embedding
                )
                
                if similarity and similarity >= similarity_threshold:
                    similarities.append((case, similarity))
        
        # Sort by similarity (highest first) and return top K
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]
    
    def enhance_case_with_semantic_features(
        self,
        case: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enhance case dictionary with semantic features.
        
        Adds:
        - semantic_embedding: Embedding vector
        - semantic_summary: Brief semantic summary (optional)
        
        Args:
            case: Case dictionary
            
        Returns:
            Enhanced case dictionary (original + semantic features)
        """
        if not self.model:
            return case
        
        enhanced_case = case.copy()
        
        # Get case text
        case_text = (
            case.get('case_text', '') or
            case.get('raw_data', {}).get('case_text', '') or
            ''
        )
        
        if case_text:
            # Generate embedding
            embedding = self.get_case_embedding(case_text)
            if embedding:
                # Add to ml_features if it exists, otherwise create it
                if 'ml_features' not in enhanced_case:
                    enhanced_case['ml_features'] = {}
                enhanced_case['ml_features']['semantic_embedding'] = embedding
        
        return enhanced_case
    
    def is_available(self) -> bool:
        """Check if semantic similarity is available."""
        return self.model is not None
