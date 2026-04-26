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
import signal
import subprocess
import time
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


def scan_outputs(scan_dir: Path, db, stat_cache: Optional[Dict] = None) -> Dict[str, int]:
    """Walk *scan_dir* recursively and upsert image/video records into `outputs`.

    *stat_cache* maps path string → (mtime_ns, size) and is updated in-place.
    When provided, files whose mtime+size haven't changed are skipped without
    computing a sha256, making repeated daemon scans very cheap.

    Returns a dict with 'found', 'indexed', 'skipped' counts.
    """
    scan_dir = scan_dir.resolve()
    if not scan_dir.exists():
        logger.error("Output directory does not exist: %s", scan_dir)
        return {'found': 0, 'indexed': 0, 'skipped': 0}

    logger.info("Scanning %s for ComfyUI outputs …", scan_dir)
    found = indexed = skipped = 0

    all_files = []
    for root, _dirs, files in os.walk(scan_dir, followlinks=True):
        for name in files:
            all_files.append(Path(root) / name)

    for file_path in sorted(all_files):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue

        found += 1
        path_str = str(file_path)

        try:
            st = file_path.stat()
        except OSError:
            continue

        # Fast path: stat matches cache → file unchanged, no sha256 needed
        if stat_cache is not None:
            cached = stat_cache.get(path_str)
            if cached and cached == (st.st_mtime_ns, st.st_size):
                skipped += 1
                continue

        sha256 = _sha256(file_path)

        existing = db.get_output_by_path(path_str)
        if existing and existing['sha256'] == sha256:
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


def run_daemon(scan_dir: Path, db, interval: int = 30) -> None:
    """Run scan_outputs in a loop, re-scanning every *interval* seconds.

    Maintains an in-memory stat cache so unchanged files are skipped in O(1)
    without computing sha256 on every pass.  Exits cleanly on SIGINT/SIGTERM.
    """
    running = True

    def _stop(sig, frame):
        nonlocal running
        logger.info("Daemon received signal %d, stopping after current scan …", sig)
        running = False

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    stat_cache: Dict[str, tuple] = {}
    logger.info("Daemon started — watching %s every %ds (SIGINT/SIGTERM to stop)", scan_dir, interval)

    while running:
        try:
            scan_outputs(scan_dir, db, stat_cache=stat_cache)
        except Exception:
            logger.exception("Scan error — will retry next interval")

        if not running:
            break

        logger.debug("Next scan in %ds …", interval)
        # Sleep in 1s increments so SIGINT is handled promptly
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    logger.info("Daemon stopped.")
