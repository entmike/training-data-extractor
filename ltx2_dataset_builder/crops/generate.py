"""
Crop strategy generation for training samples.

Generates multiple crop views (face, half-body, full) for each accepted clip.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import logging
from tqdm import tqdm

from ..config import PipelineConfig, CropConfig
from ..utils.io import Database
from ..faces.smooth import (
    smooth_bounding_boxes,
    compute_stable_crop_region
)

logger = logging.getLogger(__name__)


# Crop types and their relative frequencies
CROP_TYPES = {
    "face": 1.0,       # High priority
    "half_body": 0.5,  # Medium priority
    "full": 0.2        # Low frequency
}


def generate_crop_for_candidate(
    candidate: Dict[str, Any],
    crop_type: str,
    config: CropConfig,
    frame_width: int,
    frame_height: int
) -> Optional[Dict[str, Any]]:
    """
    Generate a specific crop for a candidate.
    
    Args:
        candidate: Candidate clip data
        crop_type: Type of crop (face, half_body, full)
        config: Crop configuration
        frame_width: Source frame width
        frame_height: Source frame height
        
    Returns:
        Crop specification dict or None
    """
    detections = candidate.get("face_detections", [])
    
    # Full frame crop doesn't need face detection
    if crop_type == "full":
        return {
            "crop_type": crop_type,
            "region": (0, 0, frame_width, frame_height),
            "candidate_id": candidate["id"]
        }
    
    # For face/half_body, we need face detections
    if not detections:
        return None
    
    # Smooth bounding boxes
    smoothed = smooth_bounding_boxes(detections, config.smoothing_window)
    
    # Compute stable crop region
    region = compute_stable_crop_region(
        smoothed,
        crop_type,
        config,
        frame_width,
        frame_height
    )
    
    if not region:
        return None
    
    return {
        "crop_type": crop_type,
        "region": region,
        "candidate_id": candidate["id"]
    }


def generate_crops_for_candidate(
    candidate: Dict[str, Any],
    config: PipelineConfig,
    frame_width: int,
    frame_height: int
) -> List[Dict[str, Any]]:
    """
    Generate all crop variants for a candidate.
    
    Args:
        candidate: Candidate clip data
        config: Pipeline configuration
        frame_width: Source frame width
        frame_height: Source frame height
        
    Returns:
        List of crop specifications
    """
    crops = []
    
    for crop_type in CROP_TYPES.keys():
        crop = generate_crop_for_candidate(
            candidate,
            crop_type,
            config.crop,
            frame_width,
            frame_height
        )
        
        if crop:
            crops.append(crop)
    
    return crops


def generate_all_crops(
    config: PipelineConfig,
    candidates: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Generate crops for all accepted candidates.
    
    Args:
        config: Pipeline configuration
        candidates: Optional list of candidates
        
    Returns:
        List of all crop specifications
    """
    db = Database(config.db_path)
    
    if candidates is None:
        candidates = db.get_candidates(status="accepted")
    
    all_crops = []
    
    pbar = tqdm(candidates, desc="Generating crops", unit="clip")
    for candidate in pbar:
        video = db.get_video_by_id(candidate["video_id"])
        if not video:
            continue
        
        video_name = Path(video["path"]).stem[:20]
        pbar.set_postfix({
            "video": video_name,
            "clip": candidate["id"],
            "crops": len(all_crops)
        })
        
        # Get face detections if not in candidate
        if "face_detections" not in candidate:
            face_dets = db.get_face_detections(
                video_id=candidate["video_id"],
                start_time=candidate["start_time"],
                end_time=candidate["end_time"]
            )
            candidate["face_detections"] = [
                {
                    "time": det["frame_time"],
                    "faces": [{
                        "bbox": (
                            det["bbox_x"],
                            det["bbox_y"],
                            det["bbox_w"],
                            det["bbox_h"]
                        ),
                        "confidence": det["confidence"]
                    }] if det["bbox_x"] is not None else []
                }
                for det in face_dets
            ]
        
        crops = generate_crops_for_candidate(
            candidate,
            config,
            video["width"],
            video["height"]
        )
        
        # Add video info to each crop
        for crop in crops:
            crop["video_id"] = candidate["video_id"]
            crop["video_path"] = video["path"]
            crop["start_time"] = candidate["start_time"]
            crop["end_time"] = candidate["end_time"]
        
        all_crops.extend(crops)
    
    logger.info(f"Generated {len(all_crops)} crop specifications")
    return all_crops


def get_output_path(
    config: PipelineConfig,
    video_name: str,
    candidate_id: int,
    crop_type: str
) -> Path:
    """
    Generate output path for a crop.
    
    Args:
        config: Pipeline configuration
        video_name: Source video name (without extension)
        candidate_id: Candidate ID
        crop_type: Type of crop
        
    Returns:
        Output directory path
    """
    return (
        config.output_dir / 
        "samples" / 
        config.token /
        f"clip_{candidate_id:06d}_{crop_type}"
    )
