"""
Face embedding clustering for automatic character discovery.

Clusters stored InsightFace embeddings from face_detections to surface
unknown characters that appear frequently across videos.

Usage:
    ltx2-build --config config.yaml --step cluster-faces
    ltx2-build --config config.yaml --step cluster-faces --video movie.mkv
"""

import logging
from collections import defaultdict
from typing import Optional

import numpy as np

from ..config import PipelineConfig
from ..faces.embed import cluster_embeddings, embedding_from_bytes
from ..utils.io import Database

logger = logging.getLogger(__name__)

# Minimum cosine similarity to consider a cluster "matched" to a known tag
KNOWN_TAG_SIM_THRESHOLD = 0.50


def cluster_all_faces(
    config: PipelineConfig,
    video_id: Optional[int] = None,
    eps: float = 0.4,
    min_samples: int = 5,
) -> int:
    """
    Load face embeddings from face_detections, cluster with DBSCAN, compare
    against existing tag_references centroids, and write results to face_clusters.

    Args:
        config: Pipeline configuration
        video_id: If set, restrict to a single video; otherwise cluster all videos
        eps: DBSCAN cosine distance threshold (0.4 ≈ similarity 0.6)
        min_samples: Minimum face detections to form a cluster

    Returns:
        Number of clusters found (excluding noise)
    """
    db = Database(config.dsn)

    # 1. Load all face embeddings (with video/frame context)
    logger.info(f"Loading face embeddings from face_detections{'for video_id=' + str(video_id) if video_id else ''}...")
    rows = db.get_face_detections_with_embeddings(video_id=video_id)
    if not rows:
        logger.warning("No face embeddings found — run auto-tag first to populate face_detections")
        return 0

    logger.info(f"Loaded {len(rows)} face embeddings")

    # 2. Decode embeddings
    embs = [embedding_from_bytes(bytes(r['embedding'])) for r in rows]

    # 3. Cluster
    logger.info(f"Clustering with DBSCAN (eps={eps}, min_samples={min_samples})...")
    labels = cluster_embeddings(embs, eps=eps, min_samples=min_samples)

    unique_labels = set(labels)
    noise_count = int(np.sum(labels == -1))
    cluster_count = len(unique_labels - {-1})
    logger.info(f"Found {cluster_count} clusters, {noise_count} noise points")

    if cluster_count == 0:
        logger.warning("No clusters found — try increasing eps or lowering min_samples")
        return 0

    # 4. Load known tag centroids for matching
    tag_centroids = db.get_tag_reference_centroids()
    logger.info(f"Loaded centroids for {len(tag_centroids)} known tag(s)")

    # 5. Build per-cluster summaries
    # Group row indices by cluster label
    by_label: dict = defaultdict(list)
    for i, label in enumerate(labels):
        if label >= 0:
            by_label[label].append(i)

    clusters = []
    for label, indices in sorted(by_label.items(), key=lambda x: -len(x[1])):
        member_embs = np.vstack([embs[i] for i in indices])

        # Normalize and compute centroid
        norms = np.linalg.norm(member_embs, axis=1, keepdims=True)
        normed = member_embs / np.where(norms > 0, norms, 1)
        centroid = np.mean(normed, axis=0)
        centroid_norm = np.linalg.norm(centroid)
        centroid = centroid / centroid_norm if centroid_norm > 0 else centroid

        # Pick up to 6 representative frames: one per unique scene, closest to centroid
        sims = normed @ centroid
        sorted_indices = np.argsort(-sims)  # best first
        seen_scenes: set = set()
        sample_rows = []
        for idx in sorted_indices:
            r = rows[indices[idx]]
            # One frame per scene; for frames outside any scene, bucket by ~500-frame windows
            dedup_key = (r['video_id'], r.get('scene_id') or f"nosec_{r['video_id']}_{r['frame_number'] // 500}")
            if dedup_key not in seen_scenes:
                seen_scenes.add(dedup_key)
                sample_rows.append(r)
            if len(sample_rows) >= 6:
                break
        sample_frame_numbers = [int(r['frame_number']) for r in sample_rows]
        sample_video_ids = [int(r['video_id']) for r in sample_rows]

        # Match against known tags
        nearest_tag = None
        nearest_sim = 0.0
        for tag, tag_centroid in tag_centroids.items():
            sim = float(np.dot(centroid, tag_centroid))
            if sim > nearest_sim:
                nearest_sim = sim
                nearest_tag = tag

        if nearest_sim < KNOWN_TAG_SIM_THRESHOLD:
            nearest_tag = None  # Not confidently matched

        member_detection_ids = [int(rows[i]['id']) for i in indices]

        clusters.append({
            'cluster_label': int(label),
            'centroid': centroid.astype(np.float32).tobytes(),
            'size': len(indices),
            'member_detection_ids': member_detection_ids,
            'sample_frame_numbers': sample_frame_numbers,
            'sample_video_ids': sample_video_ids,
            'nearest_tag': nearest_tag,
            'nearest_sim': float(nearest_sim),
        })
        logger.info(
            f"  Cluster {label}: {len(indices)} faces, "
            f"nearest={nearest_tag or 'unknown'} ({nearest_sim:.3f})"
        )

    # 6. Save to DB (replaces previous run for same scope)
    db.save_face_clusters(clusters, video_id=video_id)
    logger.info(f"Saved {len(clusters)} cluster(s) to face_clusters table")
    return len(clusters)
