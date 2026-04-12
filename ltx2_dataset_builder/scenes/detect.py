"""
Scene detection using PySceneDetect.

Detects scene boundaries in videos and caches results.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

from scenedetect import open_video, SceneManager, ContentDetector, AdaptiveDetector
from tqdm import tqdm

from ..config import PipelineConfig, SceneConfig
from ..utils.io import Database
from ..utils.preview import write_scene_thumbnail
from .blurhash import _compute_blurhash

logger = logging.getLogger(__name__)


def _scene_to_dict(scene, scene_config: SceneConfig) -> Optional[Dict[str, float]]:
    """Convert a pyscenedetect scene tuple to a dict, returning None if below min_duration."""
    start_time = scene[0].get_seconds()
    end_time = scene[1].get_seconds()
    duration = end_time - start_time
    if duration < scene_config.min_duration:
        return None
    return {
        "start_time": start_time,
        "end_time": end_time,
        "duration": duration,
        "start_frame": scene[0].get_frames(),
        "end_frame": scene[1].get_frames(),
    }


def detect_scenes_in_video(
    video_path: Path,
    scene_config: SceneConfig,
    show_progress: bool = True,
    flush_callback=None,
) -> List[Dict[str, float]]:
    """
    Detect scenes in a video file with progress bar.

    Args:
        video_path: Path to the video file
        scene_config: Scene detection configuration
        show_progress: Whether to show progress bar
        flush_callback: Optional callable(scenes) invoked after each chunk with
                        newly confirmed scenes so callers can persist incrementally.

    Returns:
        List of scene dicts with start_time and end_time
    """
    logger.info(f"Detecting scenes in: {video_path}")

    try:
        # Open video and get metadata
        video = open_video(str(video_path))
        total_frames = video.duration.get_frames()
        fps = video.frame_rate

        # Create scene manager with AdaptiveDetector (more accurate than ContentDetector)
        scene_manager = SceneManager()
        scene_manager.add_detector(
            AdaptiveDetector(
                adaptive_threshold=scene_config.threshold,
                min_scene_len=scene_config.min_scene_len
            )
        )

        # Process with progress bar
        if show_progress:
            with tqdm(
                total=total_frames,
                desc=f"Scanning {video_path.name}",
                unit="frames",
                leave=False
            ) as pbar:
                # Process in chunks for progress updates
                chunk_size = int(fps * 10)  # ~10 seconds per update
                frames_processed = 0
                last_flushed = 0  # index into scene_list up to which we've flushed

                while frames_processed < total_frames:
                    frames_to_process = min(chunk_size, total_frames - frames_processed)
                    is_last_chunk = (frames_processed + frames_to_process >= total_frames)
                    scene_manager.detect_scenes(video, duration=frames_to_process)
                    frames_processed += frames_to_process

                    current_scenes = scene_manager.get_scene_list()
                    pbar.update(frames_to_process)
                    pbar.set_postfix(scenes=len(current_scenes))

                    if flush_callback and len(current_scenes) > last_flushed:
                        # All scenes except the last have a finalised end_time because
                        # end = start of next cut.  The last scene's end is provisional
                        # (current last frame) until either a new cut or video end.
                        flush_end = len(current_scenes) if is_last_chunk else len(current_scenes) - 1
                        new_scenes = [
                            d for d in (
                                _scene_to_dict(s, scene_config)
                                for s in current_scenes[last_flushed:flush_end]
                            )
                            if d is not None
                        ]
                        if new_scenes:
                            flush_callback(new_scenes)
                        last_flushed = flush_end
        else:
            scene_manager.detect_scenes(video)

        # Build final filtered list from complete scene list
        scene_list = scene_manager.get_scene_list()
        scenes = [
            d for d in (_scene_to_dict(s, scene_config) for s in scene_list)
            if d is not None
        ]

        logger.info(f"Detected {len(scenes)} scenes (min duration: {scene_config.min_duration}s)")
        return scenes

    except Exception as e:
        logger.error(f"Scene detection failed for {video_path}: {e}")
        raise


def detect_and_cache_scenes(
    video_id: int,
    video_path: Path,
    config: PipelineConfig,
    show_progress: bool = True
) -> List[Dict[str, float]]:
    """
    Detect scenes and cache results in database.

    Args:
        video_id: Video ID in database
        video_path: Path to the video file
        config: Pipeline configuration
        show_progress: Whether to show progress bar

    Returns:
        List of scene dicts
    """
    db = Database(config.dsn)

    # Check cache
    existing_scenes = db.get_scenes(video_id)
    if existing_scenes:
        logger.debug(f"Using cached scenes for video {video_id}")
        return existing_scenes

    video_info = db.get_video_by_id(video_id)
    fps          = (video_info.get('fps') or 24.0) if video_info else 24.0
    frame_offset = (video_info.get('frame_offset') or 0) if video_info else 0
    workers = max(1, config.num_workers)
    previews_dir = config.db_path.parent / "previews"

    def _mid_time(scene: Dict) -> float:
        if scene.get('start_frame') is not None and scene.get('end_frame') is not None:
            start = (scene['start_frame'] + frame_offset + 1) / fps
            end   = (scene['end_frame']   + frame_offset)     / fps
        else:
            t_off = frame_offset / fps
            start = max(0.0, scene['start_time'] + t_off + 1.0 / fps)
            end   = scene['end_time'] + t_off
        return (start + end) / 2

    def _save_blurhash(fut):
        scene_id, bh = fut.result()
        if bh:
            with db._connection() as conn:
                conn.execute("UPDATE scenes SET blurhash = %s WHERE id = %s", (bh, scene_id))
                conn.commit()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        def _flush(scenes):
            scene_ids = db.add_scenes(video_id, scenes)
            for scene_id, scene in zip(scene_ids, scenes):
                fut = pool.submit(_compute_blurhash, scene_id, video_path, _mid_time(scene))
                fut.add_done_callback(_save_blurhash)
                pool.submit(
                    write_scene_thumbnail,
                    scene_id, video_path,
                    scene.get('start_frame', int(scene['start_time'] * fps)),
                    scene.get('end_frame',   int(scene['end_time']   * fps)),
                    fps, frame_offset, previews_dir,
                )

        detect_scenes_in_video(
            video_path, config.scene,
            show_progress=show_progress,
            flush_callback=_flush,
        )
        # pool.__exit__ waits for all submitted futures to complete

    return db.get_scenes(video_id)


def detect_all_scenes(config: PipelineConfig) -> Dict[int, List[Dict[str, float]]]:
    """
    Detect scenes in all indexed videos.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        Dictionary mapping video_id to list of scenes
    """
    from tqdm import tqdm
    
    db = Database(config.dsn)
    videos = db.get_all_videos()
    
    all_scenes = {}
    
    for video in tqdm(videos, desc="Detecting scenes"):
        video_id = video["id"]
        video_path = Path(video["path"])
        
        try:
            scenes = detect_and_cache_scenes(video_id, video_path, config)
            all_scenes[video_id] = scenes
        except Exception as e:
            logger.error(f"Failed to detect scenes for {video_path}: {e}")
            all_scenes[video_id] = []
    
    total_scenes = sum(len(s) for s in all_scenes.values())
    logger.info(f"Detected {total_scenes} scenes across {len(videos)} videos")
    
    return all_scenes
