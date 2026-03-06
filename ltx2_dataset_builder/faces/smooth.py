"""
Bounding box smoothing for stable crops.

Applies temporal smoothing to face bounding boxes to avoid jitter.
"""

from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from collections import deque

from ..config import CropConfig


def smooth_bounding_boxes(
    detections: List[Dict[str, Any]],
    window_size: int = 5
) -> List[Dict[str, Any]]:
    """
    Apply temporal smoothing to bounding boxes.
    
    Uses a moving average to smooth bounding box coordinates
    across frames, reducing jitter in crop boundaries.
    
    Args:
        detections: List of frame detections with face bboxes
        window_size: Size of the smoothing window
        
    Returns:
        Detections with smoothed bounding boxes
    """
    if not detections or len(detections) < 2:
        return detections
    
    # Extract bboxes for smoothing (use first/largest face per frame)
    bboxes = []
    for det in detections:
        faces = det.get("faces", [])
        if faces:
            # Use largest face
            largest = max(faces, key=lambda f: f["bbox"][2] * f["bbox"][3])
            bboxes.append(largest["bbox"])
        else:
            bboxes.append(None)
    
    # Interpolate missing bboxes
    bboxes = interpolate_missing_boxes(bboxes)
    
    if not any(bboxes):
        return detections
    
    # Apply moving average smoothing
    smoothed = apply_moving_average(bboxes, window_size)
    
    # Update detections with smoothed boxes
    result = []
    for det, smooth_bbox in zip(detections, smoothed):
        new_det = dict(det)
        if smooth_bbox and new_det.get("faces"):
            new_det["smoothed_bbox"] = smooth_bbox
        result.append(new_det)
    
    return result


def interpolate_missing_boxes(
    bboxes: List[Optional[Tuple[int, int, int, int]]]
) -> List[Optional[Tuple[int, int, int, int]]]:
    """
    Interpolate missing bounding boxes.
    
    Args:
        bboxes: List of bboxes (None for missing)
        
    Returns:
        List with interpolated bboxes
    """
    result = list(bboxes)
    n = len(result)
    
    # Find segments of missing boxes
    i = 0
    while i < n:
        if result[i] is None:
            # Find start and end of missing segment
            start = i
            while i < n and result[i] is None:
                i += 1
            end = i
            
            # Get surrounding boxes for interpolation
            prev_box = result[start - 1] if start > 0 else None
            next_box = result[end] if end < n else None
            
            if prev_box and next_box:
                # Linear interpolation
                for j in range(start, end):
                    t = (j - start + 1) / (end - start + 1)
                    result[j] = interpolate_box(prev_box, next_box, t)
            elif prev_box:
                # Extrapolate from previous
                for j in range(start, end):
                    result[j] = prev_box
            elif next_box:
                # Extrapolate from next
                for j in range(start, end):
                    result[j] = next_box
        else:
            i += 1
    
    return result


def interpolate_box(
    box1: Tuple[int, int, int, int],
    box2: Tuple[int, int, int, int],
    t: float
) -> Tuple[int, int, int, int]:
    """
    Linearly interpolate between two bounding boxes.
    
    Args:
        box1: First bbox (x, y, w, h)
        box2: Second bbox (x, y, w, h)
        t: Interpolation factor (0-1)
        
    Returns:
        Interpolated bbox
    """
    return tuple(
        int(box1[i] * (1 - t) + box2[i] * t)
        for i in range(4)
    )


def apply_moving_average(
    bboxes: List[Optional[Tuple[int, int, int, int]]],
    window_size: int
) -> List[Optional[Tuple[int, int, int, int]]]:
    """
    Apply moving average smoothing to bounding boxes.
    
    Args:
        bboxes: List of bboxes
        window_size: Window size for averaging
        
    Returns:
        Smoothed bboxes
    """
    if not bboxes:
        return bboxes
    
    n = len(bboxes)
    half_window = window_size // 2
    result = []
    
    for i in range(n):
        if bboxes[i] is None:
            result.append(None)
            continue
        
        # Collect boxes in window
        window_boxes = []
        for j in range(max(0, i - half_window), min(n, i + half_window + 1)):
            if bboxes[j] is not None:
                window_boxes.append(bboxes[j])
        
        if not window_boxes:
            result.append(bboxes[i])
            continue
        
        # Average coordinates
        avg_box = tuple(
            int(np.mean([box[k] for box in window_boxes]))
            for k in range(4)
        )
        result.append(avg_box)
    
    return result


def expand_bounding_box(
    bbox: Tuple[int, int, int, int],
    expansion_ratio: float,
    frame_width: int,
    frame_height: int
) -> Tuple[int, int, int, int]:
    """
    Expand a bounding box while keeping it within frame bounds.
    
    Args:
        bbox: Original bbox (x, y, w, h)
        expansion_ratio: Expansion ratio (e.g., 0.2 for 20%)
        frame_width: Frame width for clamping
        frame_height: Frame height for clamping
        
    Returns:
        Expanded bbox
    """
    x, y, w, h = bbox
    
    # Calculate expansion
    expand_w = int(w * expansion_ratio)
    expand_h = int(h * expansion_ratio)
    
    # Expand
    new_x = max(0, x - expand_w)
    new_y = max(0, y - expand_h)
    new_w = min(frame_width - new_x, w + 2 * expand_w)
    new_h = min(frame_height - new_y, h + 2 * expand_h)
    
    return (new_x, new_y, new_w, new_h)


def compute_stable_crop_region(
    detections: List[Dict[str, Any]],
    crop_type: str,
    config: "CropConfig",
    frame_width: int,
    frame_height: int
) -> Optional[Tuple[int, int, int, int]]:
    """
    Compute a stable crop region from face detections.
    
    Args:
        detections: List of face detections (already smoothed)
        crop_type: Type of crop (face, half_body, full)
        config: Crop configuration
        frame_width: Frame width
        frame_height: Frame height
        
    Returns:
        Stable crop region (x, y, w, h) or None
    """
    # Get all smoothed bboxes
    bboxes = []
    for det in detections:
        bbox = det.get("smoothed_bbox") or (
            det["faces"][0]["bbox"] if det.get("faces") else None
        )
        if bbox:
            bboxes.append(bbox)
    
    if not bboxes:
        return None
    
    # Compute union of all bboxes
    min_x = min(b[0] for b in bboxes)
    min_y = min(b[1] for b in bboxes)
    max_x = max(b[0] + b[2] for b in bboxes)
    max_y = max(b[1] + b[3] for b in bboxes)
    
    # Apply scale based on crop type
    if crop_type == "face":
        scale = config.face_crop_scale
    elif crop_type == "half_body":
        scale = config.half_body_scale
    else:  # full
        return (0, 0, frame_width, frame_height)
    
    # Expand region
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    width = (max_x - min_x) * scale
    height = (max_y - min_y) * scale
    
    # Make square (use larger dimension)
    size = max(width, height)
    
    # Compute final region
    x = int(center_x - size / 2)
    y = int(center_y - size / 2)
    w = int(size)
    h = int(size)
    
    # Clamp to frame bounds
    x = max(0, min(x, frame_width - w))
    y = max(0, min(y, frame_height - h))
    w = min(w, frame_width - x)
    h = min(h, frame_height - y)
    
    # Expand with config ratio
    return expand_bounding_box(
        (x, y, w, h),
        config.expansion_ratio,
        frame_width,
        frame_height
    )
