"""
Pre-generate and cache scene preview images at all served sizes.

Sizes mirror the constants in web_review.py (_PREVIEW_SIZES).
Update both places if sizes change.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.io import Database
from .preview import generate_scene_preview

logger = logging.getLogger(__name__)

# Must match web_review.py _PREVIEW_SIZES
PREVIEW_SIZES = {
    'thumb': 300,   # ~900px composite — compact grid thumbnails
    'card':  640,   # ~1920px composite — scene card previews
}
# None = full native resolution (legacy unsized cache)
ALL_SIZES = [None, *PREVIEW_SIZES.keys()]


def _cache_filename(scene_id: int, size: str | None) -> str:
    suffix = f"_{size}" if size else ""
    return f"scene_{scene_id}{suffix}.jpg"


def _generate_one(
    scene_id: int,
    video_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float,
    frame_offset: int,
    previews_dir: Path,
    size: str | None,
) -> tuple[int, str | None, bool]:
    """
    Generate and cache one preview image.
    Returns (scene_id, size, was_generated).
    """
    cache_path = previews_dir / video_path.stem / _cache_filename(scene_id, size)
    if cache_path.exists():
        return scene_id, size, False

    frame_width = PREVIEW_SIZES.get(size) if size else None
    data = generate_scene_preview(
        video_path=video_path,
        start_frame=start_frame,
        end_frame=end_frame,
        fps=fps,
        frame_offset=frame_offset,
        frame_width=frame_width,
    )
    if data is None:
        return scene_id, size, False

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)
    return scene_id, size, True


def precache_previews(config: PipelineConfig) -> None:
    """Generate all missing preview cache files for every scene."""
    db = Database(config.dsn)
    previews_dir = Path(config.cache_dir) / "previews"

    videos = db.get_all_videos()
    if not videos:
        logger.info("No videos found.")
        return

    # Collect all (scene, video_info) pairs
    work_items: list[dict] = []
    for video in videos:
        scenes = db.get_scenes(video["id"])
        if not scenes:
            continue
        fps = video.get("fps") or 24.0
        frame_offset = video.get("frame_offset") or 0
        video_path = Path(video["path"])
        for scene in scenes:
            start_frame = scene.get("start_frame")
            end_frame = scene.get("end_frame")
            if start_frame is None or end_frame is None:
                start_frame = int(scene["start_time"] * fps)
                end_frame = int(scene["end_time"] * fps)
            for size in ALL_SIZES:
                work_items.append({
                    "scene_id": scene["id"],
                    "video_path": video_path,
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "fps": fps,
                    "frame_offset": frame_offset,
                    "size": size,
                })

    total = len(work_items)
    sizes_str = ", ".join(
        f"{s}={PREVIEW_SIZES[s]}px" if s else "full" for s in ALL_SIZES
    )
    logger.info(f"Precaching {total} images ({total // len(ALL_SIZES)} scenes × {len(ALL_SIZES)} sizes: {sizes_str})")

    workers = max(1, config.num_workers)
    generated = skipped = errors = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _generate_one,
                item["scene_id"], item["video_path"],
                item["start_frame"], item["end_frame"],
                item["fps"], item["frame_offset"],
                previews_dir, item["size"],
            ): item
            for item in work_items
        }

        with tqdm(total=total, desc="Precaching previews", unit="img") as bar:
            for fut in as_completed(futures):
                bar.update(1)
                try:
                    _, _, was_generated = fut.result()
                    if was_generated:
                        generated += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    errors += 1
                    logger.debug(f"Preview error: {exc}")

    logger.info(
        f"Precache complete — generated: {generated}, skipped (cached): {skipped}, errors: {errors}"
    )
