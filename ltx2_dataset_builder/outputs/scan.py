"""
Scan an output directory for ComfyUI-generated image and video files.

Extracts embedded ComfyUI workflow/prompt JSON from PNG tEXt chunks (and
other PIL-readable metadata) and stores file attributes + workflow in the
`outputs` DB table.
"""

import hashlib
import json
import logging
import mimetypes
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.tiff', '.bmp'}
VIDEO_EXTS = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _image_meta(path: Path) -> Dict[str, Any]:
    """Return width, height, workflow, prompt extracted via PIL."""
    result: Dict[str, Any] = {'width': None, 'height': None, 'workflow': None, 'prompt': None}
    try:
        from PIL import Image
        with Image.open(path) as img:
            result['width'] = img.width
            result['height'] = img.height
            info = img.info or {}
            for key in ('workflow', 'prompt'):
                raw = info.get(key)
                if raw:
                    try:
                        result[key] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        pass
    except Exception as exc:
        logger.debug("PIL failed on %s: %s", path.name, exc)
    return result


def _video_meta(path: Path) -> Dict[str, Any]:
    """Return width, height, workflow, prompt from ffprobe streams + format tags."""
    result: Dict[str, Any] = {'width': None, 'height': None, 'workflow': None, 'prompt': None}
    try:
        proc = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_streams', '-show_format', str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(proc.stdout)
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                result['width']  = stream.get('width')
                result['height'] = stream.get('height')
                break
        tags = data.get('format', {}).get('tags', {})
        # SaveVideo node: top-level 'workflow' and 'prompt' tags (JSON strings)
        for key in ('workflow', 'prompt'):
            raw = tags.get(key)
            if raw:
                try:
                    result[key] = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    pass
        # VHS VideoCombine node: both packed into a single 'comment' tag
        if not result['workflow'] and not result['prompt']:
            comment = tags.get('comment', '')
            if comment:
                try:
                    outer = json.loads(comment)
                    for key in ('workflow', 'prompt'):
                        raw = outer.get(key)
                        if raw:
                            result[key] = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass
    except Exception as exc:
        logger.debug("ffprobe failed on %s: %s", path.name, exc)
    return result


def scan_outputs(
    scan_dir: Path,
    db,
    stat_cache: Optional[Dict] = None,
    incremental: bool = True,
) -> Dict[str, int]:
    """Walk *scan_dir* recursively and upsert image/video records into `outputs`.

    *stat_cache* maps path string → (mtime_ns, size) and is updated in-place.
    When provided, files whose mtime+size haven't changed are skipped without
    computing a sha256, making repeated daemon scans very cheap.

    When *incremental* is True (default), files already in the DB are skipped
    entirely — no sha256, no stat, no DB lookup per file.  Only truly new files
    get processed.  Set to False for a full rescan that re-verifies every file.

    Returns a dict with 'found', 'indexed', 'skipped' counts.
    """
    scan_dir = scan_dir.resolve()
    if not scan_dir.exists():
        logger.error("Output directory does not exist: %s", scan_dir)
        return {'found': 0, 'indexed': 0, 'skipped': 0}

    logger.info("Scanning %s for ComfyUI outputs … (%s)",
                 scan_dir, "incremental" if incremental else "full")
    found = indexed = skipped = 0

    all_files = []
    for root, _dirs, files in os.walk(scan_dir, followlinks=True):
        for name in files:
            all_files.append(Path(root) / name)

    # Pre-fetch all existing paths from DB for fast lookup
    existing_paths: Optional[set] = None
    if incremental:
        try:
            with db._connection() as conn:
                rows = conn.execute("SELECT path FROM outputs").fetchall()
                existing_paths = {r['path'] for r in rows}
        except Exception:
            logger.warning("Failed to load existing paths, falling back to per-file lookup")
            existing_paths = None

    for file_path in sorted(all_files):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue

        found += 1
        path_str = str(file_path)

        # Incremental fast-path: skip all files already in DB — no DB query, no sha256
        if incremental and existing_paths and path_str in existing_paths:
            skipped += 1
            continue

        # New file: full processing
        try:
            st = file_path.stat()
        except OSError:
            continue

        # Use stat_cache to avoid sha256 for unchanged files (repeated daemon runs)
        existing = None
        stat_unchanged = False
        if stat_cache is not None:
            cached = stat_cache.get(path_str)
            if cached and cached == (st.st_mtime_ns, st.st_size):
                stat_unchanged = True

        # For cache hits, we still need the existing row to reuse sha256
        if not stat_unchanged:
            existing = db.get_output_by_path(path_str)

        if stat_unchanged:
            if existing:
                sha256 = existing['sha256']
            else:
                # New file — must compute
                sha256 = _sha256(file_path)
        else:
            sha256 = _sha256(file_path)
            existing = db.get_output_by_path(path_str)

        # If file is unchanged (same sha256) and record is complete, skip
        if existing and existing['sha256'] == sha256:
            if existing.get('prompt_id') is not None and existing.get('prompt_hash') is not None:
                if stat_cache is not None:
                    stat_cache[path_str] = (st.st_mtime_ns, st.st_size)
                skipped += 1
                continue

        file_size = st.st_size
        file_mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        mime_type, _ = mimetypes.guess_type(path_str)

        workflow = prompt = width = height = None

        if ext in IMAGE_EXTS:
            meta = _image_meta(file_path)
            workflow = meta['workflow']
            prompt = meta['prompt']
            width = meta['width']
            height = meta['height']
        else:
            meta = _video_meta(file_path)
            workflow = meta['workflow']
            prompt   = meta['prompt']
            width    = meta['width']
            height   = meta['height']

        db.upsert_output(
            path=path_str,
            sha256=sha256,
            file_size=file_size,
            file_mtime=file_mtime,
            mime_type=mime_type,
            width=width,
            height=height,
            workflow=workflow,
            prompt=prompt,
        )
        if stat_cache is not None:
            stat_cache[path_str] = (st.st_mtime_ns, st.st_size)
        indexed += 1
        wf_tag = 'workflow' if workflow else ('prompt' if prompt else 'no workflow')
        logger.info("  [%s] %s", wf_tag, file_path.relative_to(scan_dir))

    logger.info(
        "Scan complete: %d files found, %d indexed, %d skipped (unchanged)",
        found, indexed, skipped,
    )
    return {'found': found, 'indexed': indexed, 'skipped': skipped}
