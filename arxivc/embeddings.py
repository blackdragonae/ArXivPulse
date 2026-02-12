import logging
import numpy as np
from typing import List

# Global model instance
_model = None

def get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            # Load a small, fast model
            # all-MiniLM-L6-v2 is standard for efficiency
            print("Loading embedding model (all-MiniLM-L6-v2)...")
            _model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
        except ImportError:
            print("SentenceTransformers not installed. Semantic search disabled.")
            return None
    return _model

def generate_embedding(text: str) -> np.ndarray:
    """Generates a 384-d vector for the given text."""
    model = get_model()
    if model is None:
        return np.array([])
    
    # Encode with normalization for cosine similarity
    return model.encode(text, convert_to_numpy=True, normalize_embeddings=True)

def batch_generate_embeddings(texts: List[str]) -> np.ndarray:
    """Generates embeddings for a batch of texts."""
    model = get_model()
    if model is None:
        return np.array([])
    
    return model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
