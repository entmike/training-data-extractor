"""
Face embedding extraction and clustering.

Uses InsightFace embeddings for identity clustering and matching.
"""

from typing import List, Dict, Any, Optional
import numpy as np
import logging
from pathlib import Path
import faiss
from collections import defaultdict

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
    Cluster face embeddings using FAISS HNSW + DBSCAN-like connected components.
    
    Uses an HNSW index for memory-efficient approximate nearest-neighbor search
    (O(N) memory vs O(N²) for sklearn DBSCAN's pairwise distance matrix).
    
    Args:
        embeddings: List of face embeddings
        eps: Maximum cosine distance threshold for eps-neighborhood
        min_samples: Minimum faces per cluster (noise points get label -1)
        
    Returns:
        Array of cluster labels (-1 for noise)
    """
    n = len(embeddings)
    if n == 0:
        return np.array([], dtype=int)
    if n < min_samples:
        return np.full(n, -1, dtype=int)
    
    # Stack and L2-normalize (cosine distance ≈ L2 on normalized vectors)
    X = np.array([e.flatten() for e in embeddings], dtype=np.float32)
    faiss.normalize_L2(X)
    dim = X.shape[1]
    
    # Build HNSW index
    index = faiss.IndexHNSWFlat(dim, 64, faiss.METRIC_L2)
    index.add(X)
    
    # k-NN search with large k to find all eps-neighbors
    k = max(min_samples * 4, 100)
    distances, indices = index.search(X, k)
    
    # Build undirected neighborhood graph
    neighbors = defaultdict(set)
    for i in range(n):
        for j_idx in range(k):
            if distances[i][j_idx] > eps:
                break
            ni = indices[i][j_idx]
            neighbors[i].add(ni)
            neighbors[ni].add(i)
    
    # Connected-components clustering (BFS)
    labels = np.full(n, -1, dtype=int)
    visited = set()
    cluster_id = 0
    
    for i in range(n):
        if i in visited:
            continue
        if len(neighbors[i]) < min_samples - 1:
            continue  # noise point
        # BFS to find connected component
        component = []
        queue = [i]
        visited.add(i)
        while queue:
            node = queue.pop(0)
            component.append(node)
            for nb in neighbors[node]:
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        if len(component) >= min_samples:
            for idx in component:
                labels[idx] = cluster_id
            cluster_id += 1
    
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
