"""
FFmpeg utilities for video processing.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)


def get_video_metadata(video_path: Path) -> Dict[str, Any]:
    """
    Extract metadata from a video file using ffprobe.
    
    Args:
        video_path: Path to the video file
        
    Returns:
        Dictionary containing video metadata
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # Find video stream
        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break
        
        if not video_stream:
            raise ValueError(f"No video stream found in {video_path}")
        
        # Parse FPS
        fps_str = video_stream.get("r_frame_rate", "24/1")
        fps_parts = fps_str.split("/")
        fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])
        
        # Get duration
        duration = float(data.get("format", {}).get("duration", 0))
        if duration == 0 and "duration" in video_stream:
            duration = float(video_stream["duration"])

        width  = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        # Honor HEVC/AVC bitstream Frame Cropping — ffmpeg applies it during decode,
        # so reported width/height must match the cropped output, not the coded macroblock size.
        for sd in video_stream.get("side_data_list", []) or []:
            if sd.get("side_data_type") == "Frame Cropping":
                width  -= int(sd.get("crop_left", 0)) + int(sd.get("crop_right", 0))
                height -= int(sd.get("crop_top",  0)) + int(sd.get("crop_bottom", 0))
                break

        return {
            "duration": duration,
            "fps": fps,
            "width": width,
            "height": height,
            "codec": video_stream.get("codec_name", "unknown"),
            "bit_rate": int(data.get("format", {}).get("bit_rate", 0)),
            "frame_count": int(video_stream.get("nb_frames", int(duration * fps))),
        }
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe failed for {video_path}: {e.stderr}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ffprobe output for {video_path}: {e}")
        raise


def extract_frames(
    video_path: Path,
    output_dir: Path,
    start_time: float,
    duration: float,
    fps: int = 24,
    resolution: Optional[int] = None,
    crop: Optional[Tuple[int, int, int, int]] = None,
    output_format: str = "png"
) -> List[Path]:
    """
    Extract frames from a video clip.
    
    Args:
        video_path: Path to the video file
        output_dir: Directory to save extracted frames
        start_time: Start time in seconds
        duration: Duration in seconds
        fps: Target FPS for extraction
        resolution: Target resolution (square, optional)
        crop: Crop region as (x, y, width, height), optional
        output_format: Output image format (png, jpg)
        
    Returns:
        List of paths to extracted frames
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Build filter chain
    filters = []
    
    if crop:
        x, y, w, h = crop
        filters.append(f"crop={w}:{h}:{x}:{y}")
    
    if resolution:
        filters.append(f"scale={resolution}:{resolution}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={resolution}:{resolution}:(ow-iw)/2:(oh-ih)/2")
    
    filters.append(f"fps={fps}")
    
    filter_str = ",".join(filters)
    
    output_pattern = str(output_dir / f"%06d.{output_format}")
    
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start_time),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", filter_str,
        "-q:v", "2",  # High quality
        output_pattern
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg frame extraction failed: {e.stderr.decode()}")
        raise
    
    # Return list of extracted frames
    frames = sorted(output_dir.glob(f"*.{output_format}"))
    return frames


def extract_clip(
    video_path: Path,
    output_path: Path,
    start_time: float,
    duration: float,
    fps: int = 24,
    resolution: Optional[int] = None,
    crop: Optional[Tuple[int, int, int, int]] = None
) -> Path:
    """
    Extract a video clip from source.
    
    Args:
        video_path: Path to the video file
        output_path: Output path for the clip
        start_time: Start time in seconds
        duration: Duration in seconds
        fps: Target FPS
        resolution: Target resolution (square, optional)
        crop: Crop region as (x, y, width, height), optional
        
    Returns:
        Path to the extracted clip
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Build filter chain
    filters = []
    
    if crop:
        x, y, w, h = crop
        filters.append(f"crop={w}:{h}:{x}:{y}")
    
    if resolution:
        filters.append(f"scale={resolution}:{resolution}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={resolution}:{resolution}:(ow-iw)/2:(oh-ih)/2")
    
    filters.append(f"fps={fps}")
    
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start_time),
        "-i", str(video_path),
        "-t", str(duration),
    ]
    
    if filters:
        cmd.extend(["-vf", ",".join(filters)])
    
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-an",  # No audio
        str(output_path)
    ])
    
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg clip extraction failed: {e.stderr.decode()}")
        raise
    
    return output_path


def get_frame_at_time(video_path: Path, time: float) -> "np.ndarray":
    """
    Extract a single frame at a specific time.
    
    Args:
        video_path: Path to the video file
        time: Time in seconds
        
    Returns:
        Frame as numpy array (BGR format)
    """
    import numpy as np
    
    cmd = [
        "ffmpeg",
        "-ss", str(time),
        "-i", str(video_path),
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-"
    ]
    
    # Get video dimensions first
    metadata = get_video_metadata(video_path)
    width = metadata["width"]
    height = metadata["height"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        frame = np.frombuffer(result.stdout, dtype=np.uint8)
        frame = frame.reshape((height, width, 3))
        return frame
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg frame extraction failed: {e.stderr.decode()}")
        raise


def sample_frames_from_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    num_frames: int,
    pad_frames: int = 5,
    fps: float = 24.0,
) -> List[Tuple[float, "np.ndarray"]]:
    """
    Sample evenly spaced frames from a clip, padded inward by pad_frames on each
    end to avoid bleed from adjacent scenes.

    Args:
        video_path: Path to the video file
        start_time: Start time in seconds
        end_time: End time in seconds
        num_frames: Number of frames to sample
        pad_frames: Frames to skip at the start and end of the scene
        fps: Frame rate used to convert pad_frames to seconds

    Returns:
        List of (time, frame) tuples
    """
    import numpy as np

    pad_secs = pad_frames / fps
    sample_start = start_time + pad_secs
    sample_end   = end_time   - pad_secs

    # If padding collapses the window, fall back to the original bounds
    if sample_start >= sample_end:
        sample_start = start_time
        sample_end   = end_time

    times = np.linspace(sample_start, sample_end, num_frames, endpoint=False)

    frames = []
    for t in times:
        try:
            frame = get_frame_at_time(video_path, t)
            frames.append((t, frame))
        except Exception as e:
            logger.warning(f"Failed to extract frame at {t}s: {e}")
    
    return frames
