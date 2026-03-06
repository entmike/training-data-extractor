"""
Hashing utilities for deterministic processing.
"""

import hashlib
from pathlib import Path
from typing import BinaryIO


def compute_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
    """
    Compute hash of a file.
    
    Args:
        file_path: Path to the file
        algorithm: Hash algorithm (sha256, md5, etc.)
        
    Returns:
        Hex digest of the hash
    """
    hash_obj = hashlib.new(algorithm)
    
    with open(file_path, "rb") as f:
        # Read in chunks for large files
        for chunk in iter(lambda: f.read(8192 * 1024), b""):
            hash_obj.update(chunk)
    
    return hash_obj.hexdigest()


def compute_string_hash(text: str, algorithm: str = "sha256") -> str:
    """
    Compute hash of a string.
    
    Args:
        text: Input string
        algorithm: Hash algorithm
        
    Returns:
        Hex digest of the hash
    """
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(text.encode("utf-8"))
    return hash_obj.hexdigest()


def compute_clip_id(
    source_video_hash: str,
    start_time: float,
    end_time: float,
    crop_type: str
) -> str:
    """
    Compute a unique clip identifier.
    
    Args:
        source_video_hash: Hash of the source video
        start_time: Clip start time
        end_time: Clip end time
        crop_type: Type of crop (face, half_body, full)
        
    Returns:
        Unique clip ID
    """
    data = f"{source_video_hash}:{start_time:.3f}:{end_time:.3f}:{crop_type}"
    return compute_string_hash(data)[:16]
