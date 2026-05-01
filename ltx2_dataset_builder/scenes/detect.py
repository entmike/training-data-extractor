"""
Scene detection using PySceneDetect.

Detects scene boundaries in videos and caches results.
"""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

from scenedetect import open_video, SceneManager, ContentDetector
from tqdm import tqdm

from ..config import PipelineConfig, SceneConfig
from ..utils.io import Database
from ..utils.preview import write_scene_thumbnail
from .blurhash import _compute_blurhash

logger = logging.getLogger(__name__)


def _downscale_if_needed(video_path: Path, max_height: int = 1080) -> Optional[Path]:
    """
    Downscale video to max_height if taller for ~4x speedup during detection.

    Uses MJPEG encoding (per-frame JPEG, no inter-frame GOP) with caching.
    MJPEG encodes at near decode speed (100+ fps) with ultrafast preset.
    The encoded file is cached in .cache/ and reused across runs.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return None
        line = result.stdout.strip().split("\n")[0]
        parts = line.split(",")
        if len(parts) < 2:
            return None
        height = int(parts[1])
        if height <= max_height:
            return None  # no downscale needed

        cache_dir = Path(".cache") / "downscaled"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = video_path.parent.name + "_" + video_path.stem + "_to_" + str(max_height)
        temp_path = cache_dir / f"{cache_key}.mkv"
        info_path = cache_dir / f"{cache_key}.info"

        # Reuse cached version if source hasn't changed
        try:
            if info_path.exists():
                cached_mtime = float(info_path.read_text().strip())
                if cached_mtime == video_path.stat().st_mtime:
                    logger.info(f"Using cached downscale: {temp_path.name}")
                    return temp_path
        except Exception:
            pass

        # H.264 with ultrafast preset — fast encode, scenedetect compatible
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path),
             "-vf", f"scale=-2:{max_height}:flags=bilinear",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
             "-pix_fmt", "yuv420p",
             "-an", "-sn",
             "-movflags", "+faststart",
             str(temp_path)],
            capture_output=True, check=True, timeout=3600
        )
        info_path.write_text(str(video_path.stat().st_mtime))
        file_size = temp_path.stat().st_size
        logger.info(f"Downscaled {video_path.name} to {max_height}p cached ({file_size / 1024 / 1024:.0f}MB)")
        return temp_path
    except Exception as e:
        logger.warning(f"Downscale failed for {video_path}: {e}")
        return None


def _scene_to_dict(scene, scene_config: SceneConfig) -> Optional[Dict[str, float]]:
    """Convert a pyscenedetect scene tuple to a dict."""
    start_time = scene[0].get_seconds()
    end_time = scene[1].get_seconds()
    duration = end_time - start_time
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

    # Downscale 4K content for ~4x speedup
    downscale_path = _downscale_if_needed(video_path)
    if downscale_path:
        logger.info(f"Using downscaled video: {downscale_path.name} ({downscale_path.stat().st_size / 1024 / 1024:.0f}MB)")
    else:
        logger.info(f"Using original video (not 4K, or downscale failed): {video_path.name}")
    try:
        vpath = str(downscale_path) if downscale_path else str(video_path)

        # Open video and get metadata
        video = open_video(vpath)
        total_frames = video.duration.get_frames()
        fps = video.frame_rate

        # Create scene manager with ContentDetector (fixed threshold, no blind spots)
        scene_manager = SceneManager()
        scene_manager.add_detector(
            ContentDetector(
                threshold=scene_config.threshold,
                min_scene_len=scene_config.min_scene_len,
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

        logger.info(f"Detected {len(scenes)} scenes")
        return scenes

    except Exception as e:
        logger.error(f"Scene detection failed for {video_path}: {e}")
        raise
    finally:
        # Clean up any leftover FIFOs from previous broken runs
        for leftover in video_path.parent.glob(f".fifo_{video_path.name}"):
            try:
                leftover.unlink()
            except Exception:
                pass


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


def detect_all_scenes(config: PipelineConfig, video_filter: Optional[str] = None) -> Dict[int, List[Dict[str, float]]]:
    """
    Detect scenes in all indexed videos.

    Args:
        config: Pipeline configuration
        video_filter: If set, only process this video

    Returns:
        Dictionary mapping video_id to list of scenes
    """
    from tqdm import tqdm
    
    db = Database(config.dsn)
    videos = db.get_all_videos()

    if video_filter:
        videos = [v for v in videos if Path(v["path"]).name == video_filter or v.get("name") == video_filter]
        if not videos:
            logger.error(f"Video not found: {video_filter}")
            return {}

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
