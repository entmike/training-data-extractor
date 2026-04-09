"""
Frame quality scoring for candidate clips.

Scores clips based on:
  - Sharpness: Laplacian variance of grayscale frames
  - Brightness: mean pixel value sanity check
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

import numpy as np
from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.ffmpeg import sample_frames_from_clip
from ..utils.io import Database

logger = logging.getLogger(__name__)

# Defaults — can be overridden via config.face attributes if present
_DEFAULT_MIN_SHARPNESS = 50.0
_DEFAULT_MIN_BRIGHTNESS = 20.0
_DEFAULT_MAX_BRIGHTNESS = 235.0


def score_frame_sharpness(frame: np.ndarray) -> float:
    """
    Compute sharpness of a single frame using Laplacian variance.

    Higher values indicate sharper images. Blurry or out-of-focus frames
    produce low variance; sharp frames produce high variance.

    Args:
        frame: BGR image as numpy array

    Returns:
        Laplacian variance (sharpness score)
    """
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def score_frame_brightness(frame: np.ndarray) -> float:
    """
    Compute mean brightness of a single frame.

    Args:
        frame: BGR image as numpy array

    Returns:
        Mean pixel value in [0, 255]
    """
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())


def score_clip_quality(
    video_path: Path,
    start_time: float,
    end_time: float,
    num_samples: int = 5,
    min_sharpness: float = _DEFAULT_MIN_SHARPNESS,
    min_brightness: float = _DEFAULT_MIN_BRIGHTNESS,
    max_brightness: float = _DEFAULT_MAX_BRIGHTNESS,
) -> Dict[str, Any]:
    """
    Score the visual quality of a candidate clip.

    Samples ``num_samples`` evenly-spaced frames from the clip and computes
    per-frame sharpness (Laplacian variance) and brightness.  The mean
    sharpness across sampled frames is used as the primary ``quality_score``
    stored in the database.

    Args:
        video_path: Path to the video file
        start_time: Clip start time in seconds
        end_time: Clip end time in seconds
        num_samples: Number of frames to sample
        min_sharpness: Minimum acceptable Laplacian variance
        min_brightness: Minimum acceptable mean pixel brightness
        max_brightness: Maximum acceptable mean pixel brightness

    Returns:
        Dictionary with keys:
            quality_score   – mean Laplacian variance across sampled frames
            mean_brightness – mean pixel brightness across sampled frames
            passes          – True if the clip meets all quality thresholds
            frames_scored   – number of frames successfully scored
    """
    frames = sample_frames_from_clip(
        video_path, start_time, end_time, num_samples
    )

    if not frames:
        return {
            "quality_score": 0.0,
            "mean_brightness": 0.0,
            "passes": False,
            "frames_scored": 0,
        }

    sharpness_scores: List[float] = []
    brightness_scores: List[float] = []

    for _time, frame in frames:
        sharpness_scores.append(score_frame_sharpness(frame))
        brightness_scores.append(score_frame_brightness(frame))

    quality_score = float(np.mean(sharpness_scores))
    mean_brightness = float(np.mean(brightness_scores))

    passes = (
        quality_score >= min_sharpness
        and min_brightness <= mean_brightness <= max_brightness
    )

    return {
        "quality_score": quality_score,
        "mean_brightness": mean_brightness,
        "passes": passes,
        "frames_scored": len(frames),
    }


def filter_candidates_by_quality(
    config: PipelineConfig,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Filter pending candidates by visual quality.

    For each candidate the clip is sampled, scored, and the result is written
    back to the database (``quality_score`` column, status set to
    ``"quality_failed"`` or left as ``"pending"`` to proceed to face
    filtering).

    Args:
        config: Pipeline configuration
        candidates: Optional pre-fetched candidate list; if None the database
            is queried for all ``"pending"`` candidates.

    Returns:
        List of candidates that passed quality filtering.
    """
    db = Database(config.dsn)

    if candidates is None:
        candidates = db.get_candidates(status="pending")

    # Pull thresholds from config.face if present, otherwise use defaults.
    face_cfg = config.face
    num_samples = getattr(face_cfg, "sample_frames", 5)
    min_sharpness = getattr(face_cfg, "min_sharpness", _DEFAULT_MIN_SHARPNESS)
    min_brightness = getattr(face_cfg, "min_brightness", _DEFAULT_MIN_BRIGHTNESS)
    max_brightness = getattr(face_cfg, "max_brightness", _DEFAULT_MAX_BRIGHTNESS)

    passed: List[Dict[str, Any]] = []
    failed = 0

    pbar = tqdm(candidates, desc="Quality filtering", unit="clip")
    for candidate in pbar:
        video = db.get_video_by_id(candidate["video_id"])
        if not video:
            continue

        video_path = Path(video["path"])
        video_name = video_path.stem[:20]
        fps = video.get("fps", 24.0)

        # Apply frame offset (convert frames to seconds)
        frame_offset = db.get_frame_offset(video["id"])
        time_offset = frame_offset / fps if fps > 0 else 0.0

        start_time = max(0.0, candidate["start_time"] + time_offset)
        end_time = candidate["end_time"] + time_offset

        pbar.set_postfix({
            "video": video_name,
            "clip": candidate["id"],
            "passed": len(passed),
            "failed": failed,
        })

        try:
            result = score_clip_quality(
                video_path,
                start_time,
                end_time,
                num_samples=num_samples,
                min_sharpness=min_sharpness,
                min_brightness=min_brightness,
                max_brightness=max_brightness,
            )

            db.update_candidate(
                candidate["id"],
                quality_score=result["quality_score"],
                status="pending" if result["passes"] else "quality_failed",
            )

            if result["passes"]:
                candidate["quality_score"] = result["quality_score"]
                passed.append(candidate)
            else:
                logger.debug(
                    "Clip %d rejected: sharpness=%.1f brightness=%.1f",
                    candidate["id"],
                    result["quality_score"],
                    result["mean_brightness"],
                )
                failed += 1

        except Exception as e:
            logger.error("Quality scoring failed for candidate %d: %s", candidate["id"], e)
            db.update_candidate(candidate["id"], status="error")
            failed += 1

    logger.info("Quality filtering: %d passed, %d failed", len(passed), failed)
    return passed
