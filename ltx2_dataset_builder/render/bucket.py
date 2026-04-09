"""
Bucket rendering for training samples.

Renders final training shards at target resolution and frame count.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import logging
import subprocess
from tqdm import tqdm

from ..config import PipelineConfig, RenderConfig
from ..utils.io import Database
from ..crops.generate import get_output_path

logger = logging.getLogger(__name__)


def render_bucket(
    video_path: Path,
    output_dir: Path,
    start_time: float,
    end_time: float,
    crop_region: Optional[Tuple[int, int, int, int]],
    config: RenderConfig
) -> int:
    """
    Render a single bucket (frame sequence).
    
    Args:
        video_path: Source video path
        output_dir: Output directory for frames
        start_time: Clip start time
        end_time: Clip end time
        crop_region: Crop region (x, y, w, h) or None
        config: Render configuration
        
    Returns:
        Number of frames rendered
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Calculate duration for exact frame count
    # 121 frames at 24 fps = ~5.04 seconds
    target_duration = config.frame_count / config.fps
    actual_duration = end_time - start_time
    
    # Adjust timing to hit exact frame count
    if actual_duration > target_duration:
        # Trim to target duration
        end_time = start_time + target_duration
    
    # Build filter chain
    filters = []
    
    # Apply crop if specified
    if crop_region:
        x, y, w, h = crop_region
        filters.append(f"crop={w}:{h}:{x}:{y}")
    
    # Scale to target resolution (maintain aspect, then pad)
    filters.append(
        f"scale={config.resolution}:{config.resolution}:"
        f"force_original_aspect_ratio=decrease"
    )
    filters.append(
        f"pad={config.resolution}:{config.resolution}:"
        f"(ow-iw)/2:(oh-ih)/2:black"
    )
    
    # Set exact FPS
    filters.append(f"fps={config.fps}")
    
    filter_str = ",".join(filters)
    
    # Output pattern
    output_pattern = str(output_dir / f"%06d.{config.output_format}")
    
    # Build FFmpeg command
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start_time),
        "-i", str(video_path),
        "-t", str(target_duration),
        "-vf", filter_str,
    ]
    
    # Quality settings based on format
    if config.output_format == "png":
        cmd.extend(["-compression_level", "6"])
    elif config.output_format in ["jpg", "jpeg"]:
        cmd.extend(["-q:v", str(100 - config.jpeg_quality)])
    
    # Frame limit to ensure exact count
    cmd.extend(["-frames:v", str(config.frame_count)])
    
    cmd.append(output_pattern)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg render failed: {e.stderr.decode()}")
        raise
    
    # Count rendered frames
    frames = list(output_dir.glob(f"*.{config.output_format}"))
    return len(frames)


def pad_or_trim_frames(
    output_dir: Path,
    target_count: int,
    output_format: str
) -> int:
    """
    Pad or trim frames to exact count.
    
    Args:
        output_dir: Directory containing frames
        target_count: Target frame count
        output_format: Frame file format
        
    Returns:
        Final frame count
    """
    import shutil
    
    frames = sorted(output_dir.glob(f"*.{output_format}"))
    current_count = len(frames)
    
    if current_count == target_count:
        return current_count
    
    if current_count > target_count:
        # Trim excess frames
        for frame in frames[target_count:]:
            frame.unlink()
        return target_count
    
    # Pad by duplicating last frame
    if frames:
        last_frame = frames[-1]
        for i in range(current_count, target_count):
            new_path = output_dir / f"{i:06d}.{output_format}"
            shutil.copy(last_frame, new_path)
    
    return target_count


def render_crop(
    crop: Dict[str, Any],
    config: PipelineConfig
) -> Optional[Dict[str, Any]]:
    """
    Render a single crop specification.
    
    Args:
        crop: Crop specification
        config: Pipeline configuration
        
    Returns:
        Rendered sample info or None
    """
    from ..utils.io import Database
    
    video_path = Path(crop["video_path"])
    video_name = video_path.stem
    
    # Get frame offset for this video
    db = Database(config.dsn)
    video = db.get_video_by_id(crop["video_id"])
    fps = video.get("fps", 24.0) if video else 24.0
    frame_offset = db.get_frame_offset(crop["video_id"])
    time_offset = frame_offset / fps if fps > 0 else 0
    
    # Apply offset to times
    start_time = max(0, crop["start_time"] + time_offset)
    end_time = crop["end_time"] + time_offset
    
    output_dir = get_output_path(
        config,
        video_name,
        crop["candidate_id"],
        crop["crop_type"]
    )
    
    # Skip if already rendered
    if config.skip_existing and output_dir.exists():
        existing_frames = list(output_dir.glob(f"*.{config.render.output_format}"))
        if len(existing_frames) == config.render.frame_count:
            logger.debug(f"Skipping already rendered: {output_dir}")
            return {
                "crop": crop,
                "output_path": str(output_dir),
                "frame_count": len(existing_frames),
                "skipped": True
            }
    
    try:
        # Render frames with offset-adjusted times
        frame_count = render_bucket(
            video_path=video_path,
            output_dir=output_dir,
            start_time=start_time,
            end_time=end_time,
            crop_region=crop["region"],
            config=config.render
        )
        
        # Ensure exact frame count
        frame_count = pad_or_trim_frames(
            output_dir,
            config.render.frame_count,
            config.render.output_format
        )
        
        return {
            "crop": crop,
            "output_path": str(output_dir),
            "frame_count": frame_count,
            "skipped": False
        }
        
    except Exception as e:
        logger.error(f"Failed to render crop {crop['candidate_id']}: {e}")
        return None


def render_all_crops(
    config: PipelineConfig,
    crops: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Render all crop specifications.
    
    Args:
        config: Pipeline configuration
        crops: Optional list of crops (generates if None)
        
    Returns:
        List of rendered sample info
    """
    from ..crops.generate import generate_all_crops
    
    if crops is None:
        crops = generate_all_crops(config)
    
    db = Database(config.dsn)
    rendered = []
    skipped = 0
    
    pbar = tqdm(crops, desc="Rendering buckets", unit="crop")
    for crop in pbar:
        video_name = Path(crop.get("video_path", "")).stem[:15] if crop.get("video_path") else "unknown"
        pbar.set_postfix({
            "video": video_name,
            "type": crop.get("crop_type", "?"),
            "done": len(rendered),
            "skip": skipped
        })
        
        result = render_crop(crop, config)
        
        if result:
            if result.get("skipped"):
                skipped += 1
            # Store in database
            db.add_sample(
                candidate_id=crop["candidate_id"],
                crop_type=crop["crop_type"],
                output_path=result["output_path"],
                frame_count=result["frame_count"],
                caption=""  # Will be set in caption generation
            )
            rendered.append(result)
    
    logger.info(
        f"Rendered {len(rendered)} samples ({skipped} skipped, "
        f"{len(rendered) - skipped} new)"
    )
    
    return rendered
