"""
Bucket detection module for auto-detecting optimal crop buckets.

Detects speech activity in scenes and finds optimal 24-frame multiples
that prioritize speech content.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import logging
import numpy as np
from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.io import Database
from ..utils.ffmpeg import get_video_metadata

logger = logging.getLogger(__name__)


def detect_speech_activity(
    video_path: Path,
    start_frame: int,
    end_frame: int,
    video_fps: float,
    target_fps: int = 24
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect speech activity in a video segment.
    
    Uses audio energy and zero-crossing rate to estimate speech probability.
    Returns per-frame speech scores and frame numbers.
    
    Args:
        video_path: Path to the video file
        start_frame: Start frame number
        end_frame: End frame number
        video_fps: Video's native FPS
        target_fps: Target FPS for analysis
        
    Returns:
        Tuple of (frame_numbers, speech_scores) arrays
    """
    import tempfile
    import subprocess
    
    # Calculate duration from frames
    duration = (end_frame - start_frame) / video_fps
    
    # Extract audio segment
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        audio_path = Path(tmp.name)
    
    try:
        # Extract audio segment using ffmpeg
        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_path),
            '-ss', str(start_frame / video_fps),
            '-t', str(duration),
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            str(audio_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            logger.warning(f"FFmpeg failed: {result.stderr}")
            return np.array([]), np.array([])
        
        # Read audio and compute speech features
        import struct
        
        with open(audio_path, 'rb') as f:
            # Skip WAV header
            f.read(44)
            
            # Read audio data
            audio_data = []
            while True:
                chunk = f.read(2)
                if len(chunk) < 2:
                    break
                audio_data.append(struct.unpack('<h', chunk)[0])
        
        if len(audio_data) == 0:
            return np.array([]), np.array([])
        
        audio_data = np.array(audio_data, dtype=np.float32)
        
        # Normalize
        audio_data = audio_data / np.max(np.abs(audio_data)) if np.max(np.abs(audio_data)) > 0 else audio_data
        
        # Compute frame-level features
        frame_size = int(16000 / target_fps)  # 16kHz / 24fps = ~667 samples per frame
        num_frames = len(audio_data) // frame_size
        
        if num_frames == 0:
            return np.array([]), np.array([])
        
        frame_numbers = np.arange(start_frame, start_frame + num_frames)
        speech_scores = np.zeros(num_frames)
        
        for i in range(num_frames):
            start_idx = i * frame_size
            end_idx = start_idx + frame_size
            frame = audio_data[start_idx:end_idx]
            
            # Compute speech features
            # 1. Energy (RMS)
            energy = np.sqrt(np.mean(frame ** 2))
            
            # 2. Zero-crossing rate
            zero_crossings = np.sum(np.abs(np.diff(np.sign(frame)))) / len(frame)
            
            # 3. Spectral features (simplified)
            # Use short-term energy and zero-crossing as speech proxy
            # Speech typically has: moderate energy, moderate zero-crossing
            
            # Normalize features
            energy_score = np.clip(energy / 0.1, 0, 1)  # Typical speech energy range
            zcr_score = np.clip(1.0 - abs(zero_crossings - 0.1) / 0.1, 0, 1)  # Speech ZCR ~0.1
            
            # Combine features (simple heuristic)
            speech_scores[i] = 0.6 * energy_score + 0.4 * zcr_score
        
        return frame_numbers, speech_scores
        
    except Exception as e:
        logger.warning(f"Speech detection failed: {e}")
        return np.array([]), np.array([])
    finally:
        # Clean up temp file
        if audio_path.exists():
            audio_path.unlink()


def find_optimal_bucket(
    scene: Dict[str, float],
    frame_numbers: np.ndarray,
    speech_scores: np.ndarray,
    config: PipelineConfig,
    video_fps: float
) -> Optional[Dict[str, Any]]:
    """
    Find optimal bucket within a scene that maximizes speech content.
    
    Args:
        scene: Scene dict with start_time, end_time, start_frame, end_frame
        frame_numbers: Array of frame numbers
        speech_scores: Array of speech scores per frame
        config: Pipeline configuration
        video_fps: Video's native FPS
        
    Returns:
        Optimal bucket dict or None if no valid bucket found
    """
    scene_duration = scene["duration"]
    scene_start_frame = scene.get("start_frame", 0)
    scene_end_frame = scene.get("end_frame", 0)
    
    # Calculate target frame count (multiple of 24, rounded down)
    target_frames = config.bucket.target_frame_count
    base_fps = config.bucket.base_fps
    
    # Ensure we're using a multiple of 24
    if target_frames % 24 != 0:
        target_frames = (target_frames // 24) * 24
    
    # Check if scene is long enough (in frames)
    scene_frame_count = scene_end_frame - scene_start_frame
    min_frames = config.bucket.min_frames
    min_frames = (min_frames // 24) * 24
    
    if scene_frame_count < min_frames:
        return None
    
    # If scene is shorter than target, use entire scene (rounded down to largest multiple of 24)
    if scene_frame_count <= target_frames:
        # Round down to largest multiple of 24 that fits in scene
        bucket_frame_count = (scene_frame_count // 24) * 24
        
        # Skip if scene is too short (less than 24 frames)
        if bucket_frame_count < 24:
            return None
            
        bucket_duration = bucket_frame_count / video_fps
        
        return {
            "start_time": scene["start_time"],
            "end_time": scene["start_time"] + bucket_duration,
            "duration": bucket_duration,
            "start_frame": scene_start_frame,
            "end_frame": scene_start_frame + bucket_frame_count,
            "frame_count": bucket_frame_count,
            "speech_score": float(np.mean(speech_scores[:bucket_frame_count])) if bucket_frame_count > 0 and len(speech_scores) > 0 else 0.0,
            "speech_start_frame": None,
            "speech_end_frame": None,
            "optimal_offset_frames": 0,
            "optimal_duration": bucket_duration
        }
    
    # Find optimal window using sliding window approach (in frames)
    best_score = -1
    best_bucket = None
    best_speech_start_frame = None
    best_speech_end_frame = None
    
    # Calculate max offset to ensure we can fit max_frames
    max_frames = config.bucket.max_frames
    max_frames = (max_frames // 24) * 24
    
    # Slide window across scene (step by base_fps frames = 1 second steps)
    step_size = base_fps
    current_offset = 0
    
    while current_offset + max_frames <= scene_frame_count:
        window_start_frame = scene_start_frame + current_offset
        window_end_frame = window_start_frame + max_frames
        
        # Get speech scores for this window
        mask = (frame_numbers >= window_start_frame) & (frame_numbers < window_end_frame)
        window_scores = speech_scores[mask]
        
        if len(window_scores) == 0:
            current_offset += step_size
            continue
            continue
        
        # Calculate weighted score (prioritize speech)
        mean_speech = np.mean(window_scores)
        window_score = (
            config.bucket.speech_weight * mean_speech +
            config.bucket.visual_weight * 0.5  # Placeholder for visual quality
        )
        
        if window_score > best_score:
            best_score = window_score
            
            # Find speech boundaries within window
            speech_mask = window_scores >= config.bucket.min_speech_score
            if np.any(speech_mask):
                speech_indices = np.where(speech_mask)[0]
                best_speech_start_frame = frame_numbers[mask][speech_indices[0]]
                best_speech_end_frame = frame_numbers[mask][speech_indices[-1]]
        
        current_offset += step_size
    
    # Calculate max_frames to use for the final bucket
    max_frames_final = config.bucket.max_frames
    max_frames_final = (max_frames_final // 24) * 24
    
    if best_bucket is None and best_score > 0:
        # Calculate final bucket using max_frames
        bucket_start_frame = scene_start_frame + (current_offset - step_size)
        bucket_end_frame = min(bucket_start_frame + max_frames_final, scene_end_frame)
        bucket_frame_count = bucket_end_frame - bucket_start_frame
        
        # Round down to largest multiple of 24 that fits
        bucket_frame_count = (bucket_frame_count // 24) * 24
        
        # Skip if less than 24 frames
        if bucket_frame_count < 24:
            return None
            
        bucket_end_frame = bucket_start_frame + bucket_frame_count
        
        bucket_duration = bucket_frame_count / video_fps
        
        best_bucket = {
            "start_time": bucket_start_frame / video_fps,
            "end_time": bucket_end_frame / video_fps,
            "duration": bucket_duration,
            "start_frame": int(bucket_start_frame),
            "end_frame": int(bucket_end_frame),
            "frame_count": bucket_frame_count,
            "speech_score": float(best_score),
            "speech_start_frame": int(best_speech_start_frame) if best_speech_start_frame else None,
            "speech_end_frame": int(best_speech_end_frame) if best_speech_end_frame else None,
            "optimal_offset_frames": int(current_offset - step_size),
            "optimal_duration": bucket_duration
        }
    
    return best_bucket


def detect_buckets_for_video(
    video_id: int,
    scenes: List[Dict[str, float]],
    config: PipelineConfig,
    show_progress: bool = True,
    flush_interval: int = 10
) -> List[Dict[str, Any]]:
    """
    Detect optimal buckets for all scenes in a video.
    
    Args:
        video_id: Video ID in database
        scenes: List of scene dicts
        config: Pipeline configuration
        show_progress: Whether to show progress bar
        flush_interval: Number of buckets to process before flushing to DB
        
    Returns:
        List of bucket dicts
    """
    db = Database(config.db_path)
    video = db.get_video_by_id(video_id)
    
    if not video:
        logger.error(f"Video {video_id} not found")
        return []
    
    video_path = Path(video["path"])
    video_fps = video.get("fps", 24) or 24
    
    buckets = []
    flushed_count = 0
    
    iterator = tqdm(scenes, desc=f"Detecting buckets", disable=not show_progress)
    
    for scene in iterator:
        try:
            start_frame = int(scene.get("start_frame") or 0)
            end_frame = int(scene.get("end_frame") or 0)
            
            if start_frame == 0 and end_frame == 0:
                logger.warning(f"Scene {scene.get('id')} has zero frame numbers, skipping")
                continue
            
            # Detect speech activity in scene (using frames)
            frame_numbers, speech_scores = detect_speech_activity(
                video_path,
                start_frame,
                end_frame,
                video_fps=video_fps,
                target_fps=config.bucket.base_fps
            )
            
            if len(frame_numbers) == 0:
                # No speech detected, use entire scene
                bucket = {
                    "start_time": scene["start_time"],
                    "end_time": scene["end_time"],
                    "duration": scene["duration"],
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "frame_count": end_frame - start_frame,
                    "speech_score": 0.0,
                    "speech_start_frame": None,
                    "speech_end_frame": None,
                    "optimal_offset_frames": 0,
                    "optimal_duration": scene["duration"]
                }
            else:
                # Find optimal bucket
                bucket = find_optimal_bucket(
                    scene, frame_numbers, speech_scores, config, video_fps
                )
            
            if bucket:
                bucket["video_id"] = video_id
                bucket["scene_id"] = scene.get("id")
                buckets.append(bucket)

                # Flush to database periodically
                if len(buckets) - flushed_count >= flush_interval:
                    save_buckets_to_db(video_id, buckets[flushed_count:], config)
                    flushed_count = len(buckets)
                    iterator.set_postfix(buckets=len(buckets), flushed=flushed_count)
            else:
                scene_id_raw = scene.get("id")
                scene_id = int(scene_id_raw) if scene_id_raw is not None else 0
                if scene_id:
                    db.mark_scene_bucket_ineligible(scene_id)
                    logger.debug(f"Scene {scene_id} marked bucket_ineligible (too short or no valid window)")

        except Exception as e:
            logger.warning(f"Failed to detect buckets for scene {scene.get('id')}: {e}")
            continue
    
    # Flush remaining buckets
    if len(buckets) > flushed_count:
        save_buckets_to_db(video_id, buckets[flushed_count:], config)
    
    return buckets


def save_buckets_to_db(
    video_id: int,
    buckets: List[Dict[str, Any]],
    config: PipelineConfig
) -> List[int]:
    """
    Save detected buckets to database.
    
    Args:
        video_id: Video ID
        buckets: List of bucket dicts
        config: Pipeline configuration
        
    Returns:
        List of bucket IDs
    """
    db = Database(config.db_path)
    ids = []
    
    with db._connection() as conn:
        for bucket in buckets:
            try:
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO buckets
                    (video_id, scene_id, start_time, end_time, duration, 
                     start_frame, end_frame, frame_count, speech_score,
                     speech_start_frame, speech_end_frame, optimal_offset_frames, optimal_duration)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    video_id,
                    bucket.get("scene_id"),
                    bucket["start_time"],
                    bucket["end_time"],
                    bucket["duration"],
                    bucket["start_frame"],
                    bucket["end_frame"],
                    bucket.get("frame_count"),
                    bucket.get("speech_score"),
                    bucket.get("speech_start_frame"),
                    bucket.get("speech_end_frame"),
                    bucket.get("optimal_offset_frames"),
                    bucket.get("optimal_duration"),
                ))
                conn.commit()
                
                # Get the ID (inserted or existing)
                row = conn.execute(
                    "SELECT id FROM buckets WHERE video_id = ? AND start_frame = ? AND end_frame = ?",
                    (video_id, bucket["start_frame"], bucket["end_frame"])
                ).fetchone()
                
                if row:
                    ids.append(row["id"])
                    
            except Exception as e:
                logger.error(f"Failed to save bucket: {e}")
                continue
    
    return ids


def detect_all_buckets(config: PipelineConfig) -> int:
    """
    Detect optimal buckets for all videos.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        Total number of buckets detected
    """
    db = Database(config.db_path)
    videos = db.get_all_videos()
    
    total_buckets = 0
    
    for video in tqdm(videos, desc="Processing videos"):
        video_id = video["id"]
        scenes = db.get_scenes_for_buckets(video_id)

        if not scenes:
            logger.info(f"No scenes need bucket detection for video {video_id} (all done or ineligible)")
            continue
        
        # Detect buckets for this video (with incremental flushing)
        buckets = detect_buckets_for_video(video_id, scenes, config, flush_interval=10)
        
        total_buckets += len(buckets)
        logger.info(f"Detected {len(buckets)} buckets for {video['path']} (total: {total_buckets})")
    
    logger.info(f"Total buckets detected: {total_buckets}")
    return total_buckets
