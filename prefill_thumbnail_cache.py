"""
Prefill the scene thumbnail cache (.cache/previews/scene_<id>.jpg) for all scenes
that don't already have a cached image.

Usage:
    source .venv/bin/activate
    python prefill_thumbnail_cache.py [--workers N]
"""

import argparse
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

# --- config -------------------------------------------------------------------

CONFIG_FILE = Path("config.yaml")
if CONFIG_FILE.exists():
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f)
else:
    config = {}

DB_PATH = Path(config.get("db_path", ".cache/index.db"))
DEBUG_SCENES_DIR = Path(".cache/previews")

# --- reuse preview logic from web_review -------------------------------------

sys.path.insert(0, str(Path(__file__).parent))
from web_review import generate_scene_preview  # noqa: E402


# --- helpers ------------------------------------------------------------------

def get_all_scenes():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT s.id, s.start_frame, s.end_frame, s.start_time, s.end_time,
               v.path AS video_path, v.fps, v.frame_offset
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        ORDER BY s.id
    """).fetchall()
    conn.close()
    return rows


def process_scene(row):
    scene_id = row["id"]
    cache_path = DEBUG_SCENES_DIR / f"scene_{scene_id}.jpg"
    if cache_path.exists():
        return scene_id, "skip"

    video_path = Path(row["video_path"])
    fps = row["fps"] or 24.0
    frame_offset = row["frame_offset"] or 0
    start_frame = row["start_frame"]
    end_frame = row["end_frame"]
    if start_frame is None or end_frame is None:
        start_frame = int(row["start_time"] * fps)
        end_frame = int(row["end_time"] * fps)

    img_bytes = generate_scene_preview(
        video_path=video_path,
        start_frame=start_frame,
        end_frame=end_frame,
        fps=fps,
        frame_offset=frame_offset,
    )

    if img_bytes is None:
        return scene_id, "fail"

    DEBUG_SCENES_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(img_bytes)
    return scene_id, "ok"


# --- main ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Prefill scene thumbnail cache")
    parser.add_argument("--workers", type=int, default=4,
                        help="Number of parallel worker threads (default: 4)")
    args = parser.parse_args()

    scenes = get_all_scenes()
    total = len(scenes)
    missing = [s for s in scenes
               if not (DEBUG_SCENES_DIR / f"scene_{s['id']}.jpg").exists()]

    print(f"Total scenes: {total}  |  Already cached: {total - len(missing)}  |  To generate: {len(missing)}")
    if not missing:
        print("Nothing to do.")
        return

    done = skipped = failed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_scene, row): row["id"] for row in missing}
        for i, fut in enumerate(as_completed(futures), 1):
            scene_id, status = fut.result()
            if status == "ok":
                done += 1
            elif status == "skip":
                skipped += 1
            else:
                failed += 1
            if i % 50 == 0 or i == len(missing):
                print(f"  [{i}/{len(missing)}]  generated={done}  skipped={skipped}  failed={failed}")

    print(f"\nDone.  generated={done}  failed={failed}")


if __name__ == "__main__":
    main()
