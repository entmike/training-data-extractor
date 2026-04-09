"""
Debug utilities for visual inspection of pipeline stages.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import logging
import subprocess
import numpy as np
from PIL import Image
from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.io import Database

logger = logging.getLogger(__name__)


def extract_frame_by_number(video_path: Path, frame_number: int, fps: float, max_width: int = 640) -> Optional[Image.Image]:
    """
    Extract a specific frame by its exact frame number.
    
    Args:
        video_path: Path to video file
        frame_number: The exact frame number to extract (0-indexed)
        fps: Video frame rate (used for fast seeking)
        max_width: Maximum width for resizing
        
    Returns:
        PIL Image or None on failure
    """
    try:
        # Use select filter with no seeking - accurate but scans from start
        # For preview generation this is acceptable
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", f"select=eq(n\\,{frame_number})",
            "-vsync", "vfr",
            "-vframes", "1",
            "-f", "image2pipe",
            "-vcodec", "png",
            "-"
        ]
        
        result = subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        
        from io import BytesIO
        img = Image.open(BytesIO(result.stdout))
        
        # Resize if too large
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        
        return img
        
    except Exception as e:
        logger.warning(f"Failed to extract frame {frame_number}: {e}")
        return None


def extract_multiple_frames(video_path: Path, frame_numbers: List[int], max_width: int = 640, fps: float = 24.0) -> List[Optional[Image.Image]]:
    """
    Extract multiple frames using fast seeking - much faster than select filter.
    
    Args:
        video_path: Path to video file
        frame_numbers: List of frame numbers to extract (0-indexed)
        max_width: Maximum width for resizing
        fps: Video frame rate for time calculation
        
    Returns:
        List of PIL Images (None for any that failed)
    """
    import tempfile
    import os
    
    if not frame_numbers:
        return []
    
    frames = []
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, frame_num in enumerate(frame_numbers):
                # Convert frame to time and use fast seek
                seek_time = frame_num / fps
                output_path = os.path.join(tmpdir, f"frame_{i}.png")
                
                cmd = [
                    "ffmpeg",
                    "-ss", str(seek_time),  # Fast seek before input
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-vf", f"scale={max_width}:-1",
                    "-y",
                    output_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                
                if result.returncode == 0 and os.path.exists(output_path):
                    img = Image.open(output_path)
                    frames.append(img.copy())
                else:
                    frames.append(None)
            
            return frames
            
    except Exception as e:
        logger.warning(f"Failed to extract frames {frame_numbers}: {e}")
        return [None] * len(frame_numbers)


def create_scene_preview(
    video_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float,
    frame_width: int = 426
) -> Optional[Image.Image]:
    """
    Create a 3-frame preview image (start, middle, end) for a scene.
    
    Args:
        video_path: Path to video file
        start_frame: First frame of scene (inclusive)
        end_frame: Last frame of scene (exclusive - first frame of next scene)
        fps: Video frame rate
        frame_width: Width of each frame in the composite
        
    Returns:
        Combined PIL Image or None on failure
    """
    # Calculate the three frames to extract
    # end_frame is exclusive (first frame of next scene), so last valid frame is end_frame - 1
    last_frame = end_frame - 1
    middle_frame = start_frame + (last_frame - start_frame) // 2
    
    frames_to_extract = [start_frame, middle_frame, last_frame]
    
    # Extract all 3 frames using fast seeking
    frames = extract_multiple_frames(video_path, frames_to_extract, max_width=frame_width, fps=fps)
    
    if None in frames or len(frames) != 3:
        return None
    
    # Resize all frames to same dimensions
    target_height = min(f.height for f in frames)
    resized_frames = []
    for f in frames:
        if f.height != target_height:
            ratio = target_height / f.height
            new_size = (int(f.width * ratio), target_height)
            f = f.resize(new_size, Image.LANCZOS)
        resized_frames.append(f)
    
    # Combine horizontally
    total_width = sum(f.width for f in resized_frames)
    combined = Image.new('RGB', (total_width, target_height))
    
    x_offset = 0
    for f in resized_frames:
        combined.paste(f, (x_offset, 0))
        x_offset += f.width
    
    return combined


def generate_scene_previews(
    config: PipelineConfig,
    output_dir: Optional[Path] = None,
    max_scenes: Optional[int] = None
) -> int:
    """
    Generate preview images for all detected scenes.
    
    Creates a single PNG per scene showing start/middle/end frames.
    
    Args:
        config: Pipeline configuration
        output_dir: Output directory (default: dataset/debug/scenes)
        max_scenes: Maximum number of scenes to preview (None for all)
        
    Returns:
        Number of previews generated
    """
    import tempfile
    import os
    
    db = Database(config.dsn)
    
    if output_dir is None:
        output_dir = config.output_dir / "debug" / "scenes"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    videos = db.get_all_videos()
    count = 0
    
    for video in videos:
        video_path = Path(video["path"])
        video_name = video_path.stem
        fps = video.get("fps", 24.0)
        frame_offset = db.get_frame_offset(video["id"])
        scenes = db.get_scenes(video["id"])
        
        if not scenes:
            logger.warning(f"No scenes found for {video_name}")
            continue
        
        scene_list = scenes[:max_scenes] if max_scenes else scenes
        
        logger.info(f"Generating {len(scene_list)} scene previews for {video_name} (frame_offset={frame_offset})")
        
        # Use OpenCV for frame-accurate extraction
        import cv2
        
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.error(f"Failed to open video: {video_path}")
            continue
        
        # Process scenes in order - extract and build preview immediately
        for i, scene in enumerate(tqdm(scene_list, desc=f"Previews: {video_name}")):
            start_frame = scene.get("start_frame")
            end_frame = scene.get("end_frame")
            
            if start_frame is None or end_frame is None:
                start_frame = int(scene["start_time"] * fps)
                end_frame = int(scene["end_time"] * fps)
            
            # Apply frame offset to both start and end (compensates for codec timing issues)
            start_frame = max(0, start_frame + frame_offset)  # Clamp to 0
            end_frame = end_frame + frame_offset
            
            scene_len = end_frame - start_frame
            
            # Simple: first frame, middle frame, last frame
            first_frame = start_frame + 1
            last_frame = end_frame - 1
            middle_frame = first_frame + (last_frame - first_frame) // 2
            
            frames_to_get = [first_frame, middle_frame, last_frame]
            extracted_frames = []
            
            for frame_num in frames_to_get:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                
                if ret:
                    # Resize to 426 width
                    h, w = frame.shape[:2]
                    new_w = 426
                    new_h = int(h * new_w / w)
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    extracted_frames.append(Image.fromarray(frame))
                else:
                    extracted_frames.append(None)
            
            if None in extracted_frames:
                continue
            
            # Combine horizontally
            target_height = min(f.height for f in extracted_frames)
            resized_frames = []
            for f in extracted_frames:
                if f.height != target_height:
                    ratio = target_height / f.height
                    new_size = (int(f.width * ratio), target_height)
                    f = f.resize(new_size, Image.LANCZOS)
                resized_frames.append(f)
            
            total_width = sum(f.width for f in resized_frames)
            combined = Image.new('RGB', (total_width, target_height))
            
            x_offset = 0
            for f in resized_frames:
                combined.paste(f, (x_offset, 0))
                x_offset += f.width
            
            # Save - filename shows frames
            filename = f"{video_name}_scene_{i:04d}_frames_{first_frame}_{middle_frame}_{last_frame}.png"
            combined.save(output_dir / filename)
            count += 1
    
    logger.info(f"Generated {count} scene previews in {output_dir}")
    return count


def generate_candidate_previews(
    config: PipelineConfig,
    output_dir: Optional[Path] = None,
    status_filter: Optional[str] = None,
    max_candidates: Optional[int] = None
) -> int:
    """
    Generate preview images for candidate clips.
    
    Args:
        config: Pipeline configuration
        output_dir: Output directory (default: dataset/debug/candidates)
        status_filter: Only show candidates with this status
        max_candidates: Maximum number of candidates to preview
        
    Returns:
        Number of previews generated
    """
    db = Database(config.dsn)
    
    if output_dir is None:
        output_dir = config.output_dir / "debug" / "candidates"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    candidates = db.get_candidates(status=status_filter)
    
    if max_candidates:
        candidates = candidates[:max_candidates]
    
    logger.info(f"Generating {len(candidates)} candidate previews")
    count = 0
    
    for candidate in tqdm(candidates, desc="Candidate previews"):
        video = db.get_video_by_id(candidate["video_id"])
        if not video:
            continue
        
        video_path = Path(video["path"])
        video_name = video_path.stem
        fps = video.get("fps", 24.0)
        
        # Apply frame offset
        frame_offset = db.get_frame_offset(video["id"])
        
        # Calculate frame numbers from timestamps
        start_frame = int(candidate["start_time"] * fps) + frame_offset
        end_frame = int(candidate["end_time"] * fps) + frame_offset
        start_frame = max(0, start_frame)  # Clamp to 0
        
        preview = create_scene_preview(
            video_path,
            start_frame,
            end_frame,
            fps
        )
        
        if preview:
            status = candidate.get("status", "unknown")
            
            filename = (
                f"{video_name}_clip_{candidate['id']:06d}_"
                f"{status}.png"
            )
            preview.save(output_dir / filename)
            count += 1
    
    logger.info(f"Generated {count} candidate previews in {output_dir}")
    return count
