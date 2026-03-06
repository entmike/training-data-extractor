"""
Candidate clip generation from detected scenes.

Generates candidate clips by splitting scenes into fixed-length chunks
that meet duration constraints.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.io import Database

logger = logging.getLogger(__name__)


def split_scene_into_clips(
    scene: Dict[str, float],
    min_duration: float,
    max_duration: float,
    target_duration: float,
    overlap: float = 0.5
) -> List[Dict[str, float]]:
    """
    Split a scene into candidate clips.
    
    Args:
        scene: Scene dict with start_time, end_time
        min_duration: Minimum clip duration
        max_duration: Maximum clip duration
        target_duration: Target clip duration for splitting
        overlap: Overlap ratio between consecutive clips (0-1)
        
    Returns:
        List of clip dicts with start_time and end_time
    """
    scene_start = scene["start_time"]
    scene_end = scene["end_time"]
    scene_duration = scene_end - scene_start
    
    clips = []
    
    # If scene is shorter than min_duration, skip it
    if scene_duration < min_duration:
        return clips
    
    # If scene fits within max_duration, use it as a single clip
    if scene_duration <= max_duration:
        clips.append({
            "start_time": scene_start,
            "end_time": scene_end,
            "duration": scene_duration
        })
        return clips
    
    # Split long scene into overlapping chunks
    step = target_duration * (1 - overlap)
    current_start = scene_start
    
    while current_start < scene_end - min_duration:
        clip_end = min(current_start + target_duration, scene_end)
        clip_duration = clip_end - current_start
        
        if clip_duration >= min_duration:
            clips.append({
                "start_time": current_start,
                "end_time": clip_end,
                "duration": clip_duration
            })
        
        current_start += step
        
        # Prevent infinite loop
        if step <= 0:
            break
    
    return clips


def generate_candidates_for_video(
    video_id: int,
    scenes: List[Dict[str, float]],
    config: PipelineConfig
) -> List[Dict[str, Any]]:
    """
    Generate candidate clips for a video from its scenes.
    
    Args:
        video_id: Video ID in database
        scenes: List of scene dicts
        config: Pipeline configuration
        
    Returns:
        List of candidate clip dicts
    """
    db = Database(config.db_path)
    
    # Calculate target duration based on frame count and FPS
    # 121 frames at 24 fps ≈ 5.04 seconds
    target_duration = config.render.frame_count / config.render.fps
    
    candidates = []
    
    for scene in scenes:
        scene_id = scene.get("id")
        
        clips = split_scene_into_clips(
            scene,
            min_duration=config.scene.min_duration,
            max_duration=config.scene.max_duration,
            target_duration=target_duration,
            overlap=0.25  # 25% overlap between clips
        )
        
        for clip in clips:
            candidate_id = db.add_candidate(
                video_id=video_id,
                scene_id=scene_id,
                start_time=clip["start_time"],
                end_time=clip["end_time"]
            )
            
            candidates.append({
                "id": candidate_id,
                "video_id": video_id,
                "scene_id": scene_id,
                **clip
            })
    
    return candidates


def generate_all_candidates(config: PipelineConfig) -> List[Dict[str, Any]]:
    """
    Generate candidate clips for all indexed videos.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        List of all candidate clips
    """
    db = Database(config.db_path)
    videos = db.get_all_videos()
    
    all_candidates = []
    
    for video in tqdm(videos, desc="Generating candidates"):
        video_id = video["id"]
        scenes = db.get_scenes(video_id)
        
        if not scenes:
            logger.warning(f"No scenes found for video {video_id}, skipping")
            continue
        
        candidates = generate_candidates_for_video(video_id, scenes, config)
        all_candidates.extend(candidates)
        
        logger.debug(f"Generated {len(candidates)} candidates for video {video_id}")
    
    logger.info(f"Generated {len(all_candidates)} total candidate clips")
    return all_candidates


def get_pending_candidates(config: PipelineConfig) -> List[Dict[str, Any]]:
    """
    Get all pending candidate clips.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        List of pending candidates
    """
    db = Database(config.db_path)
    return db.get_candidates(status="pending")


def get_accepted_candidates(config: PipelineConfig) -> List[Dict[str, Any]]:
    """
    Get all accepted candidate clips (passed quality and face filtering).
    
    Args:
        config: Pipeline configuration
        
    Returns:
        List of accepted candidates
    """
    db = Database(config.db_path)
    return db.get_candidates(status="accepted")
