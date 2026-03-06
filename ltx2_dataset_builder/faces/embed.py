"""
Face embedding extraction and clustering.

Uses InsightFace embeddings for identity clustering and matching.
"""

from typing import List, Dict, Any, Optional
import numpy as np
import logging
from pathlib import Path
from sklearn.cluster import DBSCAN
from sklearn.metrics.pairwise import cosine_similarity

from ..config import PipelineConfig
from ..utils.io import Database

logger = logging.getLogger(__name__)


def embedding_from_bytes(data: bytes) -> np.ndarray:
    """Convert embedding bytes back to numpy array."""
    return np.frombuffer(data, dtype=np.float32)


def cluster_embeddings(
    embeddings: List[np.ndarray],
    eps: float = 0.5,
    min_samples: int = 3
) -> np.ndarray:
    """
    Cluster face embeddings using DBSCAN.
    
    Args:
        embeddings: List of face embeddings
        eps: DBSCAN epsilon (max distance between points)
        min_samples: Minimum samples per cluster
        
    Returns:
        Array of cluster labels (-1 for noise)
    """
    if len(embeddings) < min_samples:
        return np.zeros(len(embeddings), dtype=int)
    
    # Stack embeddings
    X = np.vstack(embeddings)
    
    # Normalize embeddings
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    
    # Cluster using DBSCAN with cosine distance
    clustering = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        metric='cosine'
    )
    
    labels = clustering.fit_predict(X)
    
    return labels


def find_target_identity(
    reference_embeddings: List[np.ndarray],
    candidate_embeddings: List[np.ndarray],
    threshold: float = 0.4
) -> List[bool]:
    """
    Match candidate embeddings against reference identity.
    
    Args:
        reference_embeddings: List of reference face embeddings
        candidate_embeddings: List of candidate face embeddings
        threshold: Minimum cosine similarity threshold
        
    Returns:
        List of booleans indicating if each candidate matches reference
    """
    if not reference_embeddings or not candidate_embeddings:
        return [False] * len(candidate_embeddings)
    
    # Compute reference centroid
    ref_stack = np.vstack(reference_embeddings)
    ref_centroid = np.mean(ref_stack, axis=0)
    ref_centroid = ref_centroid / np.linalg.norm(ref_centroid)
    
    matches = []
    for emb in candidate_embeddings:
        emb_norm = emb / np.linalg.norm(emb)
        similarity = float(np.dot(ref_centroid, emb_norm))
        matches.append(similarity >= threshold)
    
    return matches


def compute_identity_similarity(
    embedding1: np.ndarray,
    embedding2: np.ndarray
) -> float:
    """
    Compute cosine similarity between two face embeddings.
    
    Args:
        embedding1: First face embedding
        embedding2: Second face embedding
        
    Returns:
        Cosine similarity (-1 to 1)
    """
    e1 = embedding1 / np.linalg.norm(embedding1)
    e2 = embedding2 / np.linalg.norm(embedding2)
    return float(np.dot(e1, e2))


def get_dominant_identity(
    detections: List[Dict[str, Any]],
    config: PipelineConfig
) -> Optional[np.ndarray]:
    """
    Get the dominant identity embedding from a set of face detections.
    
    Args:
        detections: List of face detection results
        config: Pipeline configuration
        
    Returns:
        Centroid embedding of the dominant identity, or None
    """
    # Collect all embeddings
    embeddings = []
    for det in detections:
        for face in det.get("faces", []):
            if face.get("embedding"):
                emb = embedding_from_bytes(face["embedding"])
                embeddings.append(emb)
    
    if not embeddings:
        return None
    
    if len(embeddings) == 1:
        return embeddings[0]
    
    # Cluster embeddings
    labels = cluster_embeddings(
        embeddings,
        eps=1 - config.face.similarity_threshold,
        min_samples=2
    )
    
    # Find largest cluster (excluding noise label -1)
    unique_labels, counts = np.unique(labels, return_counts=True)
    valid_mask = unique_labels >= 0
    
    if not np.any(valid_mask):
        # No clusters found, use all embeddings
        centroid = np.mean(np.vstack(embeddings), axis=0)
        return centroid / np.linalg.norm(centroid)
    
    # Get dominant cluster
    valid_labels = unique_labels[valid_mask]
    valid_counts = counts[valid_mask]
    dominant_label = valid_labels[np.argmax(valid_counts)]
    
    # Compute centroid of dominant cluster
    dominant_embeddings = [
        emb for emb, label in zip(embeddings, labels)
        if label == dominant_label
    ]
    
    centroid = np.mean(np.vstack(dominant_embeddings), axis=0)
    return centroid / np.linalg.norm(centroid)
