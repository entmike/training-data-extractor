"""
Bucket detection module.

Auto-detects optimal crop buckets from scenes, prioritizing speech content.
"""

from .detect import (
    detect_speech_activity,
    find_optimal_bucket,
    detect_buckets_for_video,
    save_buckets_to_db,
    detect_all_buckets
)

__all__ = [
    "detect_speech_activity",
    "find_optimal_bucket",
    "detect_buckets_for_video",
    "save_buckets_to_db",
    "detect_all_buckets"
]
