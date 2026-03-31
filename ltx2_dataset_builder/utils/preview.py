"""
Scene thumbnail generation (3-frame composite: start, middle, end).

Used by both the web review server (on-demand) and the scene detection
pipeline (prefill on flush).
"""

import io
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def generate_scene_preview(
    video_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float = 24.0,
    frame_offset: int = 0,
    frame_width: int = None,
) -> Optional[bytes]:
    """
    Generate a 3-frame preview image (start, middle, end) for a scene.

    Args:
        video_path: Path to video file
        start_frame: First frame of scene (inclusive)
        end_frame: Last frame of scene (exclusive - first frame of next scene)
        fps: Video frame rate
        frame_offset: Frame offset compensation
        frame_width: Width of each frame in the composite

    Returns:
        JPEG image bytes or None on failure
    """
    if not HAS_OPENCV or not HAS_PIL:
        return None

    if not video_path.exists():
        return None

    start_frame = max(0, start_frame + frame_offset)
    end_frame = end_frame + frame_offset

    first_frame  = start_frame + 1
    last_frame   = max(start_frame, end_frame - 1)
    middle_frame = first_frame + (last_frame - first_frame) // 2

    extracted_frames = []
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    try:
        for frame_num in (first_frame, middle_frame, last_frame):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if ret:
                if frame_width is not None:
                    h, w = frame.shape[:2]
                    new_h = int(h * frame_width / w)
                    frame = cv2.resize(frame, (frame_width, new_h),
                                       interpolation=cv2.INTER_LANCZOS4)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                extracted_frames.append(Image.fromarray(frame))
            else:
                extracted_frames.append(None)
    finally:
        cap.release()

    if None in extracted_frames or len(extracted_frames) != 3:
        return None

    target_height = min(f.height for f in extracted_frames)
    resized = []
    for f in extracted_frames:
        if f.height != target_height:
            ratio = target_height / f.height
            f = f.resize((int(f.width * ratio), target_height), Image.LANCZOS)
        resized.append(f)

    total_width = sum(f.width for f in resized)
    combined = Image.new('RGB', (total_width, target_height))
    x = 0
    for f in resized:
        combined.paste(f, (x, 0))
        x += f.width

    buf = io.BytesIO()
    combined.save(buf, format='JPEG', quality=85)
    buf.seek(0)
    return buf.getvalue()


def write_scene_thumbnail(
    scene_id: int,
    video_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float,
    frame_offset: int,
    previews_dir: Path,
) -> bool:
    """
    Generate and write a scene thumbnail to disk if not already cached.

    Returns True if written, False if skipped or failed.
    """
    cache_path = previews_dir / f"scene_{scene_id}.jpg"
    if cache_path.exists():
        return False

    img_bytes = generate_scene_preview(
        video_path=video_path,
        start_frame=start_frame,
        end_frame=end_frame,
        fps=fps,
        frame_offset=frame_offset,
    )
    if img_bytes is None:
        return False

    previews_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(img_bytes)
    return True
