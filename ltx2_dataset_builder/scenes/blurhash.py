"""Compute and store blurhash for the middle frame of each scene."""

import logging
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import blurhash
from PIL import Image

from ..config import PipelineConfig
from ..utils.io import Database

logger = logging.getLogger(__name__)


def _compute_blurhash(scene_id: int, video_path: Path, seek_time: float,
                      components_x: int = 9, components_y: int = 9) -> tuple[int, str | None]:
    """Extract one frame at seek_time and return (scene_id, blurhash_string)."""
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp_path = tmp.name

    cmd = [
        'ffmpeg',
        '-ss', f'{seek_time:.6f}',
        '-i', str(video_path),
        '-frames:v', '1',
        '-vf', 'scale=256:-1',
        '-pix_fmt', 'rgb24',
        '-y', tmp_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        return scene_id, None

    try:
        with Image.open(tmp_path) as img:
            return scene_id, blurhash.encode(img, components_x, components_y)
    except Exception:
        return scene_id, None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def compute_all_blurhashes(config: PipelineConfig) -> None:
    db = Database(config.dsn)
    workers = max(1, config.num_workers)

    with db._connection() as conn:
        rows = conn.execute("""
            SELECT s.id, s.start_frame, s.end_frame, s.start_time, s.end_time,
                   v.path, v.fps, v.frame_offset
            FROM scenes s
            JOIN videos v ON s.video_id = v.id
            WHERE s.blurhash IS NULL
            ORDER BY s.id
        """).fetchall()

    total = len(rows)
    logger.info(f"Computing blurhash for {total} scenes ({workers} workers)")

    tasks = []
    for row in rows:
        fps    = row['fps'] or 24.0
        offset = row['frame_offset'] or 0
        if row['start_frame'] is not None and row['end_frame'] is not None:
            start = (row['start_frame'] + offset + 1) / fps
            end   = (row['end_frame']   + offset)     / fps
        else:
            time_offset = offset / fps
            start = max(0.0, row['start_time'] + time_offset + 1.0 / fps)
            end   = row['end_time'] + time_offset
        tasks.append((row['id'], Path(row['path']), (start + end) / 2))

    done = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_compute_blurhash, sid, vp, mt): sid
                   for sid, vp, mt in tasks}
        for future in as_completed(futures):
            scene_id, bh = future.result()
            if bh is None:
                errors += 1
            else:
                with db._connection() as conn:
                    conn.execute("UPDATE scenes SET blurhash = ? WHERE id = ?", (bh, scene_id))
                    conn.commit()
            done += 1
            if done % 100 == 0 or done == total:
                logger.info(f"  {done}/{total} done ({errors} errors)")

    logger.info(f"Blurhash step complete: {done - errors}/{total} computed, {errors} errors")
