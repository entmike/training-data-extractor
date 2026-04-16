#!/usr/bin/env python3
"""Web frontend for reviewing scene captions."""

import io
import json
import os
import re
import subprocess
import threading
import zipfile
from pathlib import Path
from typing import Optional
import psycopg2
import psycopg2.extras
import psycopg2.pool
from flask import Flask, send_from_directory, request, jsonify, Response, send_file
import yaml
from PIL import Image, ImageDraw

from ltx2_dataset_builder.utils.preview import generate_scene_preview  # noqa: E402

app = Flask(__name__)

UI_DIST = Path(__file__).parent / 'ui' / 'dist'
_HERE = Path(__file__).parent

# Load .env if present (simple KEY=VALUE parser, no dependency needed)
_env_file = _HERE / '.env'
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())

# Load config — honour LTX_CONFIG env var, fall back to config.yaml
_cfg_env = os.environ.get("LTX_CONFIG")
CONFIG_PATH = Path(_cfg_env) if _cfg_env else _HERE / "config.yaml"
if not CONFIG_PATH.is_absolute():
    CONFIG_PATH = _HERE / CONFIG_PATH
if CONFIG_PATH.exists():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
else:
    config = {"output_dir": "./dataset"}

def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else _HERE / path

OUTPUT_DIR       = _resolve(config.get("output_dir", "./dataset"))
_CACHE_DIR       = _resolve(config.get("cache_dir", ".cache"))
DEBUG_SCENES_DIR = _CACHE_DIR / "previews"
WAVEFORMS_DIR    = _CACHE_DIR / "waveforms"
CLIPS_DIR        = _CACHE_DIR / "clips"

# ── PostgreSQL connection pool ────────────────────────────────────────────────

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

def _get_dsn() -> str:
    dsn = config.get('pg_dsn') or os.environ.get('DATABASE_URL')
    if not dsn:
        raise RuntimeError(
            "No pg_dsn in config.yaml and no DATABASE_URL env var. "
            "Set DATABASE_URL=postgresql://ltx2:ltx2@localhost:5432/ltx2 in .env"
        )
    return dsn

def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, _get_dsn())
    return _pool


class _DbConn:
    """Thin wrapper: exposes conn.execute(), conn.commit(), conn.close()
    so all route handlers work unchanged from the sqlite3 era."""

    def __init__(self):
        self._conn = _get_pool().getconn()

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params if params else None)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        _get_pool().putconn(self._conn)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def get_db_connection() -> _DbConn:
    return _DbConn()


def _init_schema():
    """Ensure all tables exist. Schema is defined in io.py; this call is a no-op
    if tables already exist, so startup is always safe."""
    try:
        from ltx2_dataset_builder.utils.io import Database as _Db
        _Db(_get_dsn())  # _init_tables() runs in __init__
        print("[startup] PostgreSQL schema ready")
    except Exception as e:
        print(f"[startup] Schema init failed: {e}")

_init_schema()

try:
    from ltx2_dataset_builder.utils.io import Database as _Db
    _n = _Db(_get_dsn()).backfill_default_buckets()
    if _n:
        print(f"[startup] Backfilled {_n} default bucket(s)")
except Exception as _e:
    print(f"[startup] Bucket backfill skipped: {_e}")


def find_preview_for_scene(video_name: str, scene_idx: int, start_frame: int = None) -> str | None:
    """Find preview image for a scene. Looks in video-partitioned subdirectory first."""
    if not DEBUG_SCENES_DIR.exists():
        return None

    subdir = DEBUG_SCENES_DIR / video_name
    search_dirs = [subdir, DEBUG_SCENES_DIR]  # prefer partitioned, fall back to flat
    for d in search_dirs:
        if not d.is_dir():
            continue
        pattern = f"{video_name}_scene_{scene_idx:04d}_*.png"
        matches = list(d.glob(pattern))
        if matches:
            rel = matches[0].relative_to(DEBUG_SCENES_DIR)
            return str(rel)
        for f in d.iterdir():
            if f.suffix == '.png' and video_name in f.stem:
                match = re.search(r'scene_(\d+)', f.stem)
                if match and int(match.group(1)) == scene_idx:
                    return str(f.relative_to(DEBUG_SCENES_DIR))
    
    return None


@app.route('/')
def index():
    """Serve React UI."""
    return send_from_directory(UI_DIST, 'index.html')


@app.errorhandler(404)
def spa_fallback(e):
    """Serve the SPA for client-side routes; let asset/API 404s through."""
    path = request.path
    if path.startswith('/api/') or path.startswith('/assets/') or '.' in path.rsplit('/', 1)[-1]:
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(UI_DIST, 'index.html')


@app.route('/assets/<path:filename>')
def serve_ui_assets(filename):
    """Serve Vite-built JS/CSS assets."""
    return send_from_directory(UI_DIST / 'assets', filename)


@app.route('/preview/<path:filename>')
def preview(filename):
    """Serve preview images."""
    return send_from_directory(DEBUG_SCENES_DIR, filename)


@app.route('/clip_item_preview/<int:item_id>')
def clip_item_preview(item_id: int):
    """Generate and serve a preview image for a clip item using its own frame range."""
    conn = get_db_connection()
    row = conn.execute("""
        SELECT ci.start_frame, ci.end_frame,
               v.path as video_path, v.fps, v.frame_offset
        FROM clip_items ci
        JOIN videos v ON ci.video_id = v.id
        WHERE ci.id = %s
    """, (item_id,)).fetchone()
    conn.close()

    if row is None:
        return jsonify({"error": "Clip item not found"}), 404

    cache_path = DEBUG_SCENES_DIR / f"clip_item_{item_id}.jpg"
    if cache_path.exists():
        return send_file(cache_path, mimetype='image/jpeg')

    preview_bytes = generate_scene_preview(
        video_path=Path(row["video_path"]),
        start_frame=row["start_frame"],
        end_frame=row["end_frame"],
        fps=row["fps"] or 24.0,
        frame_offset=row["frame_offset"] or 0,
    )

    if preview_bytes is None:
        return jsonify({"error": "Failed to generate preview"}), 500

    DEBUG_SCENES_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(preview_bytes)

    return Response(preview_bytes, mimetype='image/jpeg',
                    headers={'Cache-Control': 'max-age=3600'})


_PREVIEW_SIZES = {
    'thumb': 300,   # ~900px composite — compact grid thumbnails
    'card':  640,   # ~1920px composite — scene card previews
}

# Limit concurrent FFmpeg preview generation so we don't saturate all Flask
# threads and starve API requests when many uncached scenes are visible at once.
_preview_semaphore = threading.Semaphore(3)

def _serve_scene_preview(scene_id: int, size: Optional[str]) -> Response:
    """Shared logic for all scene_preview routes."""
    conn = get_db_connection()
    row = conn.execute("""
        SELECT s.*, v.path as video_path, v.fps, v.frame_offset
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        WHERE s.id = %s
    """, (scene_id,)).fetchone()
    conn.close()

    if row is None:
        return jsonify({"error": "Scene not found"}), 404

    video_path = Path(row["video_path"])
    fps = row["fps"] or 24.0
    frame_offset = row["frame_offset"] or 0

    start_frame = row["start_frame"]
    end_frame = row["end_frame"]
    if start_frame is None or end_frame is None:
        start_frame = int(row["start_time"] * fps)
        end_frame = int(row["end_time"] * fps)

    frame_width = _PREVIEW_SIZES.get(size) if size else None
    suffix = f"_{size}" if size else ""
    cache_path = DEBUG_SCENES_DIR / video_path.stem / f"scene_{scene_id}{suffix}.jpg"

    if cache_path.exists():
        return send_file(cache_path, mimetype='image/jpeg')

    with _preview_semaphore:
        # Re-check cache after acquiring semaphore — another thread may have
        # generated it while we were waiting.
        if cache_path.exists():
            return send_file(cache_path, mimetype='image/jpeg')

        preview_bytes = generate_scene_preview(
            video_path=video_path,
            start_frame=start_frame,
            end_frame=end_frame,
            fps=fps,
            frame_offset=frame_offset,
            frame_width=frame_width,
        )

    if preview_bytes is None:
        return jsonify({"error": "Failed to generate preview"}), 500

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(preview_bytes)

    return Response(preview_bytes, mimetype='image/jpeg',
                    headers={'Cache-Control': 'max-age=3600'})


@app.route('/scene_preview/<int:scene_id>')
def scene_preview(scene_id: int):
    return _serve_scene_preview(scene_id, None)

@app.route('/scene_preview/<int:scene_id>/thumb')
def scene_preview_thumb(scene_id: int):
    return _serve_scene_preview(scene_id, 'thumb')

@app.route('/scene_preview/<int:scene_id>/card')
def scene_preview_card(scene_id: int):
    return _serve_scene_preview(scene_id, 'card')


@app.route('/clip/<int:scene_id>')
def serve_clip(scene_id: int):
    """Extract and serve a video clip (cached to disk for range-request / seek support)."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    # Look up scene + video info from DB
    conn = get_db_connection()
    row = conn.execute("""
        SELECT s.start_time, s.end_time, s.start_frame, s.end_frame,
               v.path as video_path, v.fps, v.frame_offset
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        WHERE s.id = %s
    """, (scene_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Scene not found"}), 404

    video_file = Path(row["video_path"])
    if not video_file.exists():
        return jsonify({"error": "Video file not found"}), 404

    video_stem = video_file.stem
    cache_path = CLIPS_DIR / f"{video_stem}_{scene_id}.mp4"

    if cache_path.exists():
        return send_file(cache_path, mimetype='video/mp4', conditional=True)

    fps = row["fps"] or 24.0
    frame_offset = row["frame_offset"] or 0

    # Derive timestamps from frame numbers for precision; fall back to stored times
    # Add 1 to start_frame to compensate for ffmpeg fast-seek landing one frame early
    if row["start_frame"] is not None and row["end_frame"] is not None:
        start_time = (row["start_frame"] + frame_offset + 1) / fps
        end_time = (row["end_frame"] + frame_offset) / fps
    else:
        time_offset = frame_offset / fps
        start_time = max(0.0, row["start_time"] + time_offset + 1.0 / fps)
        end_time = row["end_time"] + time_offset

    start_time = max(0.0, start_time)
    duration = end_time - start_time

    if duration <= 0:
        return jsonify({"error": "Invalid time range"}), 400

    cmd = [
        'ffmpeg',
        '-ss', f'{start_time:.6f}',
        '-i', str(video_file),
        '-t', f'{duration:.6f}',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '23',
        '-c:a', 'aac',
        '-movflags', '+faststart',
        '-f', 'mp4',
        '-y',
        str(cache_path),
    ]

    result = subprocess.run(cmd, stderr=subprocess.DEVNULL)
    if result.returncode != 0 or not cache_path.exists():
        return jsonify({"error": "Clip generation failed"}), 500

    return send_file(cache_path, mimetype='video/mp4', conditional=True)


def _generate_rms_waveform_png(video_file: Path, start_time: float, duration: float,
                               width: int = 800, height: int = 80) -> Optional[bytes]:
    """
    Extract per-window RMS levels via FFmpeg astats, render as a bar chart PNG.
    Returns PNG bytes, or None on failure.
    """
    sample_rate = 44100
    n_bars = width // 4  # 4px per bar → 200 bars for 800px

    # Downmix to stereo; capture per-channel RMS via astats
    cmd = [
        'ffmpeg',
        '-ss', f'{start_time:.6f}',
        '-i', str(video_file),
        '-t', f'{duration:.6f}',
        '-filter_complex',
        f'aformat=channel_layouts=stereo:sample_rates={sample_rate},'
        f'astats=metadata=1:reset=1,'
        f'ametadata=print:key=lavfi.astats.1.RMS_level,'
        f'ametadata=print:key=lavfi.astats.2.RMS_level',
        '-vn', '-f', 'null', '-',
    ]

    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    output = result.stderr.decode('utf-8', errors='replace')

    def parse_channel(key):
        raw = []
        for m in re.finditer(rf'{re.escape(key)}=(.+)', output):
            val = m.group(1).strip()
            if val in ('-inf', 'inf'):
                raw.append(None)
            else:
                try:
                    raw.append(float(val))
                except ValueError:
                    raw.append(None)
        return raw

    raw_l = parse_channel('lavfi.astats.1.RMS_level')
    raw_r = parse_channel('lavfi.astats.2.RMS_level')

    if not raw_l and not raw_r:
        return None
    # Fall back to the available channel if one is missing
    if not raw_l:
        raw_l = raw_r
    if not raw_r:
        raw_r = raw_l

    def aggregate(raw):
        group_size = max(1, len(raw) // n_bars)
        grouped = []
        for i in range(0, len(raw), group_size):
            chunk = [v for v in raw[i:i + group_size] if v is not None]
            grouped.append(max(chunk) if chunk else None)
        return grouped[:n_bars]

    grouped_l = aggregate(raw_l)
    grouped_r = aggregate(raw_r)

    # Fixed reference range calibrated to home-video movie audio (RMS levels):
    #   -50 dB → 0   (silence / room tone floor)
    #   -35 dB → 50% (moderate speech / score)
    #   -20 dB → 100% (loud dialogue / action)
    DB_FLOOR = -50.0
    DB_CEIL  = -20.0
    DB_RANGE = DB_CEIL - DB_FLOOR  # 30 dB

    def to_level(v):
        if v is None:
            return 0.0
        return max(0.0, min(1.0, (v - DB_FLOOR) / DB_RANGE))

    levels_l = [to_level(v) for v in grouped_l]
    levels_r = [to_level(v) for v in grouped_r]

    if not levels_l:
        return None

    bg     = (28,  33,  40)   # #1c2128
    fg     = (88, 166, 255)   # #58a6ff
    center_color = (48, 54, 61)  # subtle center line
    img    = Image.new('RGB', (width, height), color=bg)
    draw   = ImageDraw.Draw(img)
    center = height // 2

    # Subtle center divider line
    draw.line([(0, center), (width, center)], fill=center_color)

    bar_w = width / max(len(levels_l), 1)
    for i, (lvl_l, lvl_r) in enumerate(zip(levels_l, levels_r)):
        x0 = int(i * bar_w)
        x1 = max(x0 + 1, int((i + 1) * bar_w) - 1)
        # Left channel: grows upward from center
        h_l = max(1, int(lvl_l * center))
        draw.rectangle([x0, center - h_l, x1, center], fill=fg)
        # Right channel: grows downward from center
        h_r = max(1, int(lvl_r * center))
        draw.rectangle([x0, center, x1, center + h_r], fill=fg)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.getvalue()


@app.route('/waveform/<int:scene_id>')
def serve_waveform(scene_id: int):
    """Generate and serve an RMS energy bar chart PNG for a scene clip (cached on disk)."""
    WAVEFORMS_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    row = conn.execute("""
        SELECT s.start_time, s.end_time, s.start_frame, s.end_frame,
               v.path as video_path, v.fps, v.frame_offset
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        WHERE s.id = %s
    """, (scene_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Scene not found"}), 404

    video_file = Path(row["video_path"])
    if not video_file.exists():
        return jsonify({"error": "Video file not found"}), 404

    video_stem = video_file.stem
    cache_path = WAVEFORMS_DIR / f"{video_stem}_{scene_id}.png"

    if cache_path.exists():
        return send_file(cache_path, mimetype='image/png', max_age=86400)

    fps = row["fps"] or 24.0
    frame_offset = row["frame_offset"] or 0

    if row["start_frame"] is not None and row["end_frame"] is not None:
        start_time = (row["start_frame"] + frame_offset + 1) / fps
        end_time   = (row["end_frame"]   + frame_offset)     / fps
    else:
        time_offset = frame_offset / fps
        start_time  = max(0.0, row["start_time"] + time_offset + 1.0 / fps)
        end_time    = row["end_time"] + time_offset

    start_time = max(0.0, start_time)
    duration   = end_time - start_time
    if duration <= 0:
        return jsonify({"error": "Invalid time range"}), 400

    png_bytes = _generate_rms_waveform_png(video_file, start_time, duration)
    if png_bytes is None:
        return jsonify({"error": "Waveform generation failed"}), 500

    cache_path.write_bytes(png_bytes)
    return send_file(cache_path, mimetype='image/png', max_age=86400)


@app.route('/api/scenes')
def get_scenes():
    """Return paginated scene data as JSON for infinite scroll."""
    video_filter = request.args.get('video', '')
    page = max(1, int(request.args.get('page', 1) or 1))
    limit = min(500, int(request.args.get('limit', 200) or 200))

    include_tags = [t for t in request.args.get('include_tags', '').split(',') if t]
    exclude_tags = [t for t in request.args.get('exclude_tags', '').split(',') if t]
    include_mode = request.args.get('include_mode', 'and')  # 'and' | 'or'
    try:
        min_frames = int(request.args.get('min_frames', 0) or 0)
    except (ValueError, TypeError):
        min_frames = 0
    rating_values = [v for v in request.args.get('rating', '').split(',') if v]
    sort = request.args.get('sort', '')  # 'frames_asc' | 'frames_desc' | ''

    conn = get_db_connection()

    conditions = []
    params = []

    if video_filter:
        conditions.append("v.id = %s")
        params.append(int(video_filter))

    # Tag include filter
    if include_tags:
        if include_mode == 'or':
            ph = ','.join(['%s'] * len(include_tags))
            conditions.append(f"EXISTS (SELECT 1 FROM scene_tags st2 WHERE st2.scene_id = s.id AND st2.tag IN ({ph}))")
            params.extend(include_tags)
        else:  # AND — each tag must be present
            for tag in include_tags:
                conditions.append("EXISTS (SELECT 1 FROM scene_tags st2 WHERE st2.scene_id = s.id AND st2.tag = %s)")
                params.append(tag)

    # Tag exclude filter
    for tag in exclude_tags:
        conditions.append("NOT EXISTS (SELECT 1 FROM scene_tags st2 WHERE st2.scene_id = s.id AND st2.tag = %s)")
        params.append(tag)

    # Min frames
    if min_frames > 0:
        conditions.append("(COALESCE(s.end_frame, 0) - COALESCE(s.start_frame, 0)) >= %s")
        params.append(min_frames)

    # Unconfirmed tag filter — scenes where a specific tag is auto-detected (confirmed=FALSE)
    unconfirmed_tag = request.args.get('unconfirmed_tag', '')
    if unconfirmed_tag:
        conditions.append("EXISTS (SELECT 1 FROM scene_tags st2 WHERE st2.scene_id = s.id AND st2.tag = %s AND st2.confirmed = FALSE)")
        params.append(unconfirmed_tag)

    # Rating filter
    if rating_values:
        rating_parts = []
        numeric = [v for v in rating_values if v != 'unranked']
        if 'unranked' in rating_values:
            rating_parts.append("s.rating IS NULL")
        if numeric:
            ph = ','.join(['%s'] * len(numeric))
            rating_parts.append(f"s.rating IN ({ph})")
            params.extend([int(v) for v in numeric])
        if rating_parts:
            conditions.append(f"({' OR '.join(rating_parts)})")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    scenes_from = "FROM scenes s JOIN videos v ON s.video_id = v.id"

    total = conn.execute(
        f"SELECT COUNT(*) AS total {scenes_from} {where_clause}",
        params
    ).fetchone()["total"]

    offset = (page - 1) * limit
    
    order_by = (
        "s.start_frame ASC, s.video_id, s.id" if sort == "frames_asc"
        else "s.start_frame DESC, s.video_id, s.id" if sort == "frames_desc"
        else "s.video_id, s.id"
    )
    base_query = f"""
        SELECT s.*, v.path as video_path, v.fps, v.frame_offset, v.duration as video_duration,
            (SELECT COUNT(*) FROM scenes s2 WHERE s2.video_id = s.video_id AND s2.id < s.id) as scene_idx,
            (SELECT COUNT(*) FROM clip_items ci WHERE ci.scene_id = s.id) as clip_count,
            (SELECT COUNT(*) FROM tag_references tr WHERE tr.video_id = s.video_id AND tr.frame_number >= s.start_frame AND tr.frame_number <= s.end_frame) as face_ref_count,
            (SELECT STRING_AGG(st.tag, '|') FROM scene_tags st WHERE st.scene_id = s.id AND st.confirmed = TRUE) as tags_concat,
            (SELECT STRING_AGG(st.tag, '|') FROM scene_tags st WHERE st.scene_id = s.id AND st.confirmed = FALSE) as auto_tags_concat
        {scenes_from}
        {where_clause}
        ORDER BY {order_by}
        LIMIT {limit} OFFSET {offset}
    """
    
    rows = conn.execute(base_query, params).fetchall()
    conn.close()

    # Build preview lookup once for all scenes in this batch (avoid per-scene glob).
    # Scans video-partitioned subdirectories; falls back to flat legacy files.
    preview_lookup: dict[tuple, str] = {}
    if DEBUG_SCENES_DIR.exists():
        for entry in DEBUG_SCENES_DIR.iterdir():
            if entry.is_dir():
                # Partitioned: .cache/previews/{video_name}/{video_name}_scene_N_*.png
                for f in entry.iterdir():
                    if f.suffix not in ('.png', '.jpg'):
                        continue
                    m = re.search(r'^(.+)_scene_(\d+)', f.stem)
                    if m:
                        preview_lookup[(m.group(1), int(m.group(2)))] = str(f.relative_to(DEBUG_SCENES_DIR))
            elif entry.suffix == '.png':
                # Legacy flat files
                m = re.search(r'^(.+)_scene_(\d+)', entry.stem)
                if m:
                    preview_lookup[(m.group(1), int(m.group(2)))] = entry.name

    scenes = []
    for row in rows:
        d = dict(row)
        video_path = Path(d['video_path'])
        video_name = video_path.stem
        scene_idx = d['scene_idx']
        duration = d['end_time'] - d['start_time']
        t = int(d['start_time'])
        caption = d.get('caption') or ''
        tags_raw = d.get('tags_concat') or ''
        auto_tags_raw = d.get('auto_tags_concat') or ''
        preview_path = preview_lookup.get((video_name, scene_idx))
        scenes.append({
            'id': d['id'],
            'video_name': video_name,
            'video_path': d['video_path'],
            'start_frame': d.get('start_frame') or 0,
            'end_frame': d.get('end_frame') or 0,
            'start_time': d['start_time'],
            'end_time': d['end_time'],
            'fps': d.get('fps') or 24.0,
            'frame_offset': d.get('frame_offset') or 0,
            'caption': caption,
            'tags': [t for t in tags_raw.split('|') if t],
            'auto_tags': [t for t in auto_tags_raw.split('|') if t],
            'start_time_hms': f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}",
            'duration': duration,
            'frame_count': (d.get('end_frame') or 0) - (d.get('start_frame') or 0),
            'preview_path': preview_path,
            'caption_finished_at': (d['caption_finished_at'].isoformat() if hasattr(d['caption_finished_at'], 'isoformat') else d['caption_finished_at'].replace(' ', 'T') + 'Z') if d.get('caption_finished_at') else None,
            'rating': d.get('rating'),
            'blurhash': d.get('blurhash'),
            'clip_count': d.get('clip_count') or 0,
            'face_ref_count': d.get('face_ref_count') or 0,
            'subtitles': d.get('subtitles') or '',
            'video_total_frames': round((d.get('video_duration') or 0) * (d.get('fps') or 24.0)),
        })

    return jsonify({
        'scenes': scenes,
        'page': page,
        'has_more': offset + limit < total,
        'total': total,
    })


@app.route('/api/cache/previews', methods=['GET'])
def cache_previews_size():
    """Return total size and file count of the preview cache (recursive)."""
    files = list(DEBUG_SCENES_DIR.rglob('*.jpg')) if DEBUG_SCENES_DIR.exists() else []
    total = sum(f.stat().st_size for f in files)
    return jsonify({'file_count': len(files), 'size_bytes': total})


@app.route('/api/cache/previews', methods=['DELETE'])
def cache_previews_clear():
    """Delete all cached preview images (recursive)."""
    import shutil
    files = list(DEBUG_SCENES_DIR.rglob('*.jpg')) if DEBUG_SCENES_DIR.exists() else []
    freed = sum(f.stat().st_size for f in files)
    for f in files:
        f.unlink(missing_ok=True)
    # Remove empty subdirectories
    for d in [e for e in DEBUG_SCENES_DIR.iterdir() if e.is_dir()]:
        shutil.rmtree(d, ignore_errors=True)
    return jsonify({'deleted': len(files), 'freed_bytes': freed})


@app.route('/api/stats')
def api_stats():
    """Get caption stats as JSON."""
    conn = get_db_connection()
    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN caption IS NOT NULL AND caption != '' AND substr(caption, 1, 2) != '__' THEN 1 ELSE 0 END) as captioned
        FROM scenes
    """).fetchone()
    conn.close()
    return jsonify(dict(stats))


@app.route('/api/caption/<int:scene_id>', methods=['GET'])
def get_caption(scene_id: int):
    """Get caption for a specific scene."""
    conn = get_db_connection()
    row = conn.execute("SELECT id, caption FROM scenes WHERE id = %s", (scene_id,)).fetchone()
    conn.close()
    
    if row is None:
        return jsonify({"error": "Scene not found"}), 404
    
    return jsonify({"id": row["id"], "caption": row["caption"]})


@app.route('/api/caption/<int:scene_id>', methods=['PUT'])
def update_caption(scene_id: int):
    """Update caption for a specific scene."""
    data = request.get_json()
    if data is None or "caption" not in data:
        return jsonify({"error": "Missing caption field"}), 400
    
    caption = data["caption"].strip() if data["caption"] else None
    
    conn = get_db_connection()
    
    # Check if scene exists
    row = conn.execute("SELECT id FROM scenes WHERE id = %s", (scene_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404
    
    # Update caption
    conn.execute("UPDATE scenes SET caption = %s WHERE id = %s", (caption, scene_id))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": scene_id, "caption": caption})


@app.route('/api/tags/all', methods=['GET'])
def get_all_tags():
    """Return all distinct tags in the DB with optional descriptions."""
    video_filter = request.args.get('video', '')
    conn = get_db_connection()
    if video_filter:
        rows = conn.execute(
            """SELECT DISTINCT st.tag, COALESCE(td.description, '') as description, COALESCE(td.display_name, '') as display_name
               FROM scene_tags st
               JOIN scenes s ON st.scene_id = s.id
               JOIN videos v ON s.video_id = v.id
               LEFT JOIN tag_definitions td ON td.tag = st.tag
               WHERE v.id = %s
               ORDER BY st.tag""",
            [int(video_filter)]
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT st.tag, COALESCE(td.description, '') as description, COALESCE(td.display_name, '') as display_name,
                      COUNT(st.scene_id) as scene_count,
                      COALESCE(SUM(s.end_frame - s.start_frame), 0) as total_frames,
                      (SELECT COUNT(*) FROM tag_references tr WHERE tr.tag = st.tag) as face_ref_count
               FROM scene_tags st
               LEFT JOIN tag_definitions td ON td.tag = st.tag
               LEFT JOIN scenes s ON s.id = st.scene_id
               GROUP BY st.tag, td.description, td.display_name
               ORDER BY st.tag"""
        ).fetchall()
    conn.close()
    return jsonify({"tags": [{"tag": r["tag"], "description": r["description"], "display_name": r["display_name"], "scene_count": r.get("scene_count"), "total_frames": r.get("total_frames") or 0, "face_ref_count": r.get("face_ref_count") or 0} for r in rows]})


@app.route('/api/tags/<int:scene_id>', methods=['GET'])
def get_tags(scene_id: int):
    """Get all tags for a scene."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = %s ORDER BY created_at, tag",
        (scene_id,)
    ).fetchall()
    conn.close()
    return jsonify({"scene_id": scene_id, "tags": [r["tag"] for r in rows]})


@app.route('/api/tags/<int:scene_id>', methods=['POST'])
def add_tag(scene_id: int):
    """Add a tag to a scene."""
    data = request.get_json()
    if not data or not data.get("tag"):
        return jsonify({"error": "Missing tag"}), 400
    tag = data["tag"].strip().lower()
    if not tag:
        return jsonify({"error": "Empty tag"}), 400

    conn = get_db_connection()
    if conn.execute("SELECT id FROM scenes WHERE id = %s", (scene_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404

    conn.execute(
        "INSERT INTO scene_tags (scene_id, tag, confirmed) VALUES (%s, %s, TRUE) "
        "ON CONFLICT (scene_id, tag) DO UPDATE SET confirmed = TRUE",
        (scene_id, tag)
    )
    conn.commit()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = %s ORDER BY created_at, tag",
        (scene_id,)
    ).fetchall()
    conn.close()
    return jsonify({"scene_id": scene_id, "tags": [r["tag"] for r in rows]})


@app.route('/api/tags/rename', methods=['PUT'])
def rename_tag():
    """Rename a tag globally across all scenes."""
    data = request.get_json()
    if not data or not data.get('old_tag') or not data.get('new_tag'):
        return jsonify({"error": "Missing old_tag or new_tag"}), 400
    old_tag = data['old_tag'].strip().lower()
    new_tag = data['new_tag'].strip().lower()
    if not old_tag or not new_tag:
        return jsonify({"error": "Empty tag"}), 400
    if old_tag == new_tag:
        return jsonify({"updated": 0}), 200

    conn = get_db_connection()
    count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM scene_tags WHERE tag = %s", (old_tag,)
    ).fetchone()["cnt"]
    # For scenes that already have new_tag, the INSERT is ignored (no duplicate)
    conn.execute(
        "INSERT INTO scene_tags (scene_id, tag, created_at) "
        "SELECT scene_id, %s, created_at FROM scene_tags WHERE tag = %s ON CONFLICT DO NOTHING",
        (new_tag, old_tag)
    )
    conn.execute("DELETE FROM scene_tags WHERE tag = %s", (old_tag,))
    # Migrate description to new tag name
    conn.execute(
        "INSERT INTO tag_definitions (tag, description, display_name) "
        "SELECT %s, description, display_name FROM tag_definitions WHERE tag = %s "
        "ON CONFLICT(tag) DO NOTHING",
        (new_tag, old_tag)
    )
    conn.execute("DELETE FROM tag_definitions WHERE tag = %s", (old_tag,))
    conn.commit()
    conn.close()
    return jsonify({"updated": count})


@app.route('/api/tags/description', methods=['PUT'])
def set_tag_description():
    """Set or update the description for a tag."""
    data = request.get_json()
    if not data or 'tag' not in data:
        return jsonify({"error": "Missing tag"}), 400
    tag = data['tag'].strip().lower()
    description = (data.get('description') or '').strip()
    display_name = (data.get('display_name') or '').strip()
    if not tag:
        return jsonify({"error": "Empty tag"}), 400

    conn = get_db_connection()
    conn.execute(
        "INSERT INTO tag_definitions (tag, description, display_name) VALUES (%s, %s, %s) "
        "ON CONFLICT(tag) DO UPDATE SET description = excluded.description, display_name = excluded.display_name",
        (tag, description, display_name)
    )
    conn.commit()
    conn.close()
    return jsonify({"tag": tag, "description": description, "display_name": display_name})


@app.route('/api/tags/suggestions/<int:scene_id>', methods=['GET'])
def get_tag_suggestions(scene_id: int):
    """Get auto-suggested tags for a scene based on various contexts."""
    conn = get_db_connection()
    
    try:
        scene = conn.execute("SELECT video_id FROM scenes WHERE id = %s", (scene_id,)).fetchone()
        if not scene:
            conn.close()
            return jsonify({"error": "Scene not found"}), 404
        
        video_id = scene["video_id"]
        tag_scores = {}
        
        existing_tags = set(row["tag"] for row in conn.execute(
            "SELECT tag FROM scene_tags WHERE scene_id = %s", (scene_id,)
        ).fetchall())

        def bump(tag, delta, source):
            if tag not in tag_scores:
                tag_scores[tag] = {"score": 0.0, "sources": set()}
            tag_scores[tag]["score"] += delta
            tag_scores[tag]["sources"].add(source)

        # Tags already on this scene (boost so they stay at top when re-opening dropdown)
        for tag in existing_tags:
            bump(tag, 5.0, "scene_existing")

        # Most popular tags within this video — primary signal
        video_popular = conn.execute("""
            SELECT st.tag, COUNT(*) AS freq
            FROM scene_tags st
            JOIN scenes s ON st.scene_id = s.id
            WHERE s.video_id = %s AND st.scene_id != %s
            GROUP BY st.tag
            ORDER BY freq DESC
            LIMIT 50
        """, (video_id, scene_id)).fetchall()

        for row in video_popular:
            bump(row["tag"], 3.0 + row["freq"] * 0.3, "video_popular")

        # Tags co-occurring with this scene's tags in the same video — secondary signal
        if existing_tags:
            placeholders = ",".join(["%s"] * len(existing_tags))
            video_co_occur = conn.execute(f"""
                SELECT st2.tag, COUNT(*) AS co_occurrence
                FROM scene_tags st1
                JOIN scene_tags st2 ON st1.scene_id = st2.scene_id
                JOIN scenes s ON st1.scene_id = s.id
                WHERE st1.tag IN ({placeholders})
                  AND st2.tag NOT IN ({placeholders})
                  AND s.video_id = %s
                  AND st1.scene_id != %s
                GROUP BY st2.tag
                ORDER BY co_occurrence DESC
                LIMIT 20
            """, list(existing_tags) + list(existing_tags) + [video_id, scene_id]).fetchall()

            for row in video_co_occur:
                bump(row["tag"], 2.0 + row["co_occurrence"] * 0.5, "video_co_occur")

        # Recency bonus within this video — most recently tagged scenes in the same video
        from datetime import datetime, timezone
        video_recent = conn.execute("""
            SELECT st.tag, MAX(st.created_at) AS last_used
            FROM scene_tags st
            JOIN scenes s ON st.scene_id = s.id
            WHERE s.video_id = %s AND st.scene_id != %s
            GROUP BY st.tag
            ORDER BY last_used DESC
            LIMIT 50
        """, (video_id, scene_id)).fetchall()

        for row in video_recent:
            last_used = row["last_used"]
            if last_used:
                if not hasattr(last_used, 'tzinfo'):
                    last_used = datetime.fromisoformat(str(last_used).replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                if last_used.tzinfo is None:
                    last_used = last_used.replace(tzinfo=timezone.utc)
                days_ago = (now - last_used).total_seconds() / 86400
                bump(row["tag"], max(0.0, 1.0 - days_ago * 0.02), "video_recent")
        
        # Load all tag definitions in one query to avoid N+1
        tag_defs = {
            r["tag"]: r for r in conn.execute(
                "SELECT tag, description, display_name FROM tag_definitions"
            ).fetchall()
        }
        tag_list = []
        for tag, data in tag_scores.items():
            desc_row = tag_defs.get(tag)
            tag_list.append({
                "tag": tag,
                "score": round(data["score"], 2),
                "display_name": desc_row["display_name"] if desc_row and desc_row["display_name"] else tag,
                "description": desc_row["description"] if desc_row else ""
            })
        
        tag_list.sort(key=lambda x: x["score"], reverse=True)
        
        conn.close()
        return jsonify({"suggestions": tag_list})
    
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/tags/<int:scene_id>/<path:tag>', methods=['DELETE'])
def remove_tag(scene_id: int, tag: str):
    """Remove a tag from a scene."""
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM scene_tags WHERE scene_id = %s AND tag = %s",
        (scene_id, tag)
    )
    conn.commit()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = %s ORDER BY created_at, tag",
        (scene_id,)
    ).fetchall()
    conn.close()
    return jsonify({"scene_id": scene_id, "tags": [r["tag"] for r in rows]})


@app.route('/api/tags/<int:scene_id>/<path:tag>/confirm', methods=['PUT'])
def confirm_tag(scene_id: int, tag: str):
    """Mark an auto-detected tag as confirmed."""
    conn = get_db_connection()
    conn.execute(
        "UPDATE scene_tags SET confirmed = TRUE WHERE scene_id = %s AND tag = %s",
        (scene_id, tag)
    )
    conn.commit()
    conn.close()
    return jsonify({"scene_id": scene_id, "tag": tag, "confirmed": True})


@app.route('/api/tag-refs', methods=['GET'])
def list_tag_refs():
    """List stored tag face references."""
    tag = request.args.get('tag', '')
    conn = get_db_connection()
    if tag:
        rows = conn.execute(
            "SELECT id, tag, video_id, frame_number, frame_time, created_at FROM tag_references WHERE tag = %s ORDER BY tag, id",
            (tag,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, tag, video_id, frame_number, frame_time, created_at FROM tag_references ORDER BY tag, id"
        ).fetchall()
    conn.close()
    return jsonify({"refs": [dict(r) for r in rows]})


@app.route('/api/tag-refs', methods=['POST'])
def add_tag_ref():
    """Extract a face embedding from a video frame and store as a tag reference."""
    data = request.get_json()
    scene_id = data.get('scene_id')
    tag = (data.get('tag') or '').strip().lower()
    frame = data.get('frame')

    if not scene_id or not tag or frame is None:
        return jsonify({'error': 'scene_id, tag, and frame are required'}), 400

    conn = get_db_connection()
    scene_row = conn.execute(
        "SELECT video_id FROM scenes WHERE id = %s", (scene_id,)
    ).fetchone()
    if not scene_row:
        conn.close()
        return jsonify({'error': 'Scene not found'}), 404
    video_row = conn.execute(
        "SELECT id, path, fps FROM videos WHERE id = %s", (scene_row['video_id'],)
    ).fetchone()
    conn.close()
    if not video_row:
        return jsonify({'error': 'Video not found'}), 404

    from pathlib import Path
    from ltx2_dataset_builder.utils.ffmpeg import get_frame_at_time
    from ltx2_dataset_builder.autotag.face_tag import _pick_best_face
    from ltx2_dataset_builder.faces.detect import get_face_analyzer

    video_path = Path(video_row['path'])
    fps = video_row['fps'] or 24.0
    frame_number = int(frame)
    frame_time = frame_number / fps

    # Ensure InsightFace is loaded (uses default buffalo_l)
    get_face_analyzer()

    # Dummy config shim — only embedding_model is needed by _pick_best_face
    class _FaceCfg:
        embedding_model = 'buffalo_l'
    class _Cfg:
        face = _FaceCfg()

    try:
        frame_bgr = get_frame_at_time(video_path, frame_time)
        embedding_bytes = _pick_best_face(frame_bgr, _Cfg())
    except Exception as e:
        return jsonify({'error': f'Frame extraction failed: {e}'}), 500

    if embedding_bytes is None:
        return jsonify({'error': 'No face detected at that frame — try a different position'}), 422

    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO tag_references (tag, video_id, frame_number, frame_time, embedding) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (tag, video_row['id'], frame_number, frame_time, embedding_bytes)
    )
    ref_id = cur.fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'ref_id': ref_id, 'tag': tag, 'frame': frame_number, 'frame_time': frame_time}), 201


@app.route('/api/tag-refs/<int:ref_id>', methods=['DELETE'])
def delete_tag_ref(ref_id: int):
    """Delete a tag face reference."""
    conn = get_db_connection()
    conn.execute("DELETE FROM tag_references WHERE id = %s", (ref_id,))
    conn.commit()
    conn.close()
    return jsonify({'deleted': ref_id})


@app.route('/api/tag-refs/<int:ref_id>/image')
def tag_ref_image(ref_id: int):
    """Return a tone-mapped JPEG still of the face reference frame."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT tr.frame_time, v.path, v.width, v.height FROM tag_references tr JOIN videos v ON v.id = tr.video_id WHERE tr.id = %s",
        (ref_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404

    video_path = Path(row['path'])
    frame_time = row['frame_time']
    is_hdr = _is_hdr_video(video_path)

    tonemap_filter = (
        'zscale=transfer=linear:npl=100,format=gbrpf32le,'
        'zscale=primaries=bt709,tonemap=tonemap=hable:desat=0,'
        'zscale=transfer=bt709:matrix=bt709:range=tv,'
        'format=bgr24'
    )

    vf_args = ['-vf', tonemap_filter] if is_hdr else ['-pix_fmt', 'bgr24']

    cmd = [
        'ffmpeg', '-ss', str(frame_time), '-i', str(video_path),
        '-vframes', '1',
        *vf_args,
        '-f', 'image2pipe', '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24', '-',
    ]

    try:
        import numpy as np
        import cv2
        result = subprocess.run(cmd, capture_output=True, check=True)
        w, h = row['width'], row['height']
        frame = np.frombuffer(result.stdout, dtype=np.uint8).reshape((h, w, 3))
        ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError('imencode failed')
        return send_file(io.BytesIO(buf.tobytes()), mimetype='image/jpeg')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scenes/<int:scene_id>/split', methods=['POST'])
def split_scene(scene_id: int):
    """Split a long scene into segments of up to 600 frames each."""
    conn = get_db_connection()
    row = conn.execute("""
        SELECT s.video_id, s.start_frame, s.end_frame, s.rating, v.fps
        FROM scenes s JOIN videos v ON s.video_id = v.id
        WHERE s.id = %s
    """, (scene_id,)).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404

    start_frame = row['start_frame']
    end_frame   = row['end_frame']
    video_id    = row['video_id']
    fps         = row['fps'] or 24.0
    rating      = row['rating']
    total_frames = end_frame - start_frame

    if total_frames <= 600:
        conn.close()
        return jsonify({"error": "Scene is not longer than 600 frames"}), 400

    # Build segment boundaries
    segments = []
    f = start_frame
    while f < end_frame:
        seg_end = min(f + 600, end_frame)
        segments.append((f, seg_end))
        f = seg_end

    # Update original row to be the first segment
    seg0_s, seg0_e = segments[0]
    seg0_start_t, seg0_end_t = seg0_s / fps, seg0_e / fps
    seg0_dur = seg0_end_t - seg0_start_t
    conn.execute("""
        UPDATE scenes SET start_frame = %s, end_frame = %s, start_time = %s, end_time = %s, duration = %s
        WHERE id = %s
    """, (seg0_s, seg0_e, seg0_start_t, seg0_end_t, seg0_dur, scene_id))

    # Update existing bucket for first segment (if any)
    conn.execute("""
        UPDATE buckets SET start_frame = %s, end_frame = %s, frame_count = %s,
                           start_time = %s, end_time = %s, duration = %s,
                           optimal_offset_frames = 0, optimal_duration = %s
        WHERE scene_id = %s
    """, (seg0_s, seg0_e, seg0_e - seg0_s, seg0_start_t, seg0_end_t, seg0_dur, seg0_dur, scene_id))

    # Insert remaining segments + their default buckets
    new_ids = [scene_id]
    for seg_s, seg_e in segments[1:]:
        seg_start_t = seg_s / fps
        seg_end_t   = seg_e / fps
        seg_dur     = seg_end_t - seg_start_t
        seg_frames  = seg_e - seg_s
        cur = conn.execute("""
            INSERT INTO scenes (video_id, start_time, end_time, duration, start_frame, end_frame, rating)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (video_id, seg_start_t, seg_end_t, seg_dur, seg_s, seg_e, rating))
        inserted = cur.fetchone()
        if inserted:
            new_scene_id = inserted['id']
            new_ids.append(new_scene_id)
            conn.execute("""
                INSERT INTO buckets
                    (video_id, scene_id, start_time, end_time, duration,
                     start_frame, end_frame, frame_count,
                     optimal_offset_frames, optimal_duration)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
                ON CONFLICT (video_id, start_frame, end_frame) DO NOTHING
            """, (video_id, new_scene_id, seg_start_t, seg_end_t, seg_dur,
                  seg_s, seg_e, seg_frames, seg_dur))

    conn.commit()
    conn.close()
    return jsonify({"success": True, "scene_ids": new_ids, "segment_count": len(segments)})


@app.route('/api/scenes/<int:scene_id>/boundary', methods=['PUT'])
def update_scene_boundary(scene_id: int):
    """Adjust start_frame or end_frame by 1 frame; mirror change to the adjacent scene."""
    data = request.get_json()
    field = data.get('field')   # 'start_frame' | 'end_frame'
    new_value = data.get('value')

    if field not in ('start_frame', 'end_frame') or not isinstance(new_value, int):
        return jsonify({'error': 'Invalid field or value'}), 400

    conn = get_db_connection()

    row = conn.execute("""
        SELECT s.id, s.video_id, s.start_frame, s.end_frame,
               v.fps, v.duration AS video_duration
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        WHERE s.id = %s
    """, (scene_id,)).fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Scene not found'}), 404

    scene = dict(row)
    fps = scene['fps'] or 24.0
    video_total_frames = round((scene['video_duration'] or 0) * fps)
    cur_start = scene['start_frame'] or 0
    cur_end   = scene['end_frame']   or 0

    if field == 'start_frame':
        if new_value < 0:
            conn.close()
            return jsonify({'error': 'start_frame cannot be below 0'}), 400
        if new_value >= cur_end:
            conn.close()
            return jsonify({'error': 'start_frame must be less than end_frame'}), 400
    else:
        if new_value <= cur_start:
            conn.close()
            return jsonify({'error': 'end_frame must be greater than start_frame'}), 400
        if video_total_frames > 0 and new_value > video_total_frames:
            conn.close()
            return jsonify({'error': 'end_frame exceeds video length'}), 400

    # Find the scene that shares the boundary being moved
    adjacent = None
    if field == 'start_frame':
        # Previous scene ends where this one starts
        adj_row = conn.execute("""
            SELECT id, start_frame, end_frame FROM scenes
            WHERE video_id = %s AND end_frame = %s AND id != %s
        """, (scene['video_id'], cur_start, scene_id)).fetchone()
        if adj_row:
            adjacent = dict(adj_row)
            if new_value <= adjacent['start_frame']:
                conn.close()
                return jsonify({'error': 'Adjacent scene would have no frames'}), 400
    else:
        # Next scene starts where this one ends
        adj_row = conn.execute("""
            SELECT id, start_frame, end_frame FROM scenes
            WHERE video_id = %s AND start_frame = %s AND id != %s
        """, (scene['video_id'], cur_end, scene_id)).fetchone()
        if adj_row:
            adjacent = dict(adj_row)
            if new_value >= adjacent['end_frame']:
                conn.close()
                return jsonify({'error': 'Adjacent scene would have no frames'}), 400

    new_start = new_value if field == 'start_frame' else cur_start
    new_end   = new_value if field == 'end_frame'   else cur_end

    conn.execute("""
        UPDATE scenes
        SET start_frame = %s, end_frame = %s,
            start_time = %s, end_time = %s, duration = %s
        WHERE id = %s
    """, (new_start, new_end, new_start / fps, new_end / fps,
          (new_end - new_start) / fps, scene_id))

    adj_result = None
    if adjacent:
        if field == 'start_frame':
            adj_new_start = adjacent['start_frame']
            adj_new_end   = new_value
        else:
            adj_new_start = new_value
            adj_new_end   = adjacent['end_frame']
        conn.execute("""
            UPDATE scenes
            SET start_frame = %s, end_frame = %s,
                start_time = %s, end_time = %s, duration = %s
            WHERE id = %s
        """, (adj_new_start, adj_new_end,
              adj_new_start / fps, adj_new_end / fps,
              (adj_new_end - adj_new_start) / fps, adjacent['id']))
        adj_result = {'id': adjacent['id'], 'start_frame': adj_new_start, 'end_frame': adj_new_end}

    conn.commit()
    conn.close()

    return jsonify({
        'scene': {'id': scene_id, 'start_frame': new_start, 'end_frame': new_end},
        'adjacent': adj_result,
    })


@app.route('/api/rating/<int:scene_id>', methods=['PUT'])
def set_rating(scene_id: int):
    """Set or clear the star rating (1-3) for a scene."""
    data = request.get_json()
    if data is None or 'rating' not in data:
        return jsonify({"error": "Missing rating field"}), 400
    rating = data['rating']
    if rating is not None and rating not in (1, 2, 3):
        return jsonify({"error": "Rating must be 1, 2, 3, or null"}), 400
    conn = get_db_connection()
    if conn.execute("SELECT id FROM scenes WHERE id = %s", (scene_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404
    conn.execute("UPDATE scenes SET rating = %s WHERE id = %s", (rating, scene_id))
    conn.commit()
    conn.close()
    return jsonify({"scene_id": scene_id, "rating": rating})


@app.route('/api/videos', methods=['GET'])
def get_videos():
    """Return all videos with full metadata and scene/caption counts."""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT v.*,
               COUNT(s.id) as scene_count,
               SUM(CASE WHEN s.caption IS NOT NULL AND s.caption != ''
                        AND substr(s.caption, 1, 2) != '__' THEN 1 ELSE 0 END) as captioned,
               COALESCE(SUM(s.end_frame - s.start_frame), 0) as total_frames
        FROM videos v
        LEFT JOIN scenes s ON s.video_id = v.id
        GROUP BY v.id
        ORDER BY v.path
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        v = dict(r)
        display_name = v.get("name") or Path(v["path"]).name
        result.append({
            "id": v["id"],
            "name": display_name,
            "path": v["path"],
            "hash": v["hash"],
            "duration": v.get("duration"),
            "fps": v.get("fps"),
            "width": v.get("width"),
            "height": v.get("height"),
            "codec": v.get("codec"),
            "frame_offset": v.get("frame_offset") or 0,
            "prompt": v.get("prompt") or "",
            "indexed_at": v.get("indexed_at"),
            "scene_count": v.get("scene_count") or 0,
            "captioned": v.get("captioned") or 0,
            "total_frames": v.get("total_frames") or 0,
        })
    return jsonify({"videos": result})


@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    """Return all videos with their captioning prompts."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, path, prompt FROM videos ORDER BY path"
    ).fetchall()
    conn.close()
    return jsonify({
        "videos": [
            {"id": r["id"], "name": Path(r["path"]).name, "prompt": r["prompt"] or ""}
            for r in rows
        ]
    })


@app.route('/api/prompts/<int:video_id>', methods=['PUT'])
def set_prompt(video_id: int):
    """Set the captioning prompt for a video."""
    data = request.get_json()
    prompt = (data.get("prompt") or "").strip() or None
    conn = get_db_connection()
    conn.execute("UPDATE videos SET prompt = %s WHERE id = %s", (prompt, video_id))
    conn.commit()
    conn.close()
    return jsonify({"video_id": video_id, "prompt": prompt or ""})


@app.route('/api/videos/<int:video_id>/name', methods=['PUT'])
def set_video_name(video_id: int):
    """Set the user-friendly name for a video."""
    data = request.get_json()
    if data is None or 'name' not in data:
        return jsonify({"error": "Missing name field"}), 400
    name = data["name"].strip() or None
    conn = get_db_connection()
    conn.execute("UPDATE videos SET name = %s WHERE id = %s", (name, video_id))
    conn.commit()
    conn.close()
    return jsonify({"video_id": video_id, "name": name or ""})



@app.route('/api/videos/<int:video_id>', methods=['DELETE'])
def delete_video(video_id: int):
    """Delete a video and all associated DB rows and cache files (not the source file)."""
    conn = get_db_connection()

    video = conn.execute(
        "SELECT id, path FROM videos WHERE id = %s", (video_id,)
    ).fetchone()
    if not video:
        conn.close()
        return jsonify({"error": "Video not found"}), 404

    video_stem = Path(video["path"]).stem

    # Collect IDs needed for cache deletion before removing rows
    scene_rows = conn.execute(
        "SELECT id FROM scenes WHERE video_id = %s", (video_id,)
    ).fetchall()
    scene_ids = [r["id"] for r in scene_rows]

    item_ids = []
    if scene_ids:
        ph = ",".join(["%s"] * len(scene_ids))
        item_rows = conn.execute(
            f"SELECT id FROM clip_items WHERE scene_id IN ({ph})", scene_ids
        ).fetchall()
        item_ids = [r["id"] for r in item_rows]

    # ── DB deletion (order matters for FK constraints) ────────
    if scene_ids:
        ph = ",".join(["%s"] * len(scene_ids))
        candidate_rows = conn.execute(
            f"SELECT id FROM candidates WHERE video_id = %s", (video_id,)
        ).fetchall()
        candidate_ids = [r["id"] for r in candidate_rows]
        if candidate_ids:
            cph = ",".join(["%s"] * len(candidate_ids))
            conn.execute(f"DELETE FROM samples WHERE candidate_id IN ({cph})", candidate_ids)
    conn.execute("DELETE FROM candidates     WHERE video_id = %s", (video_id,))
    conn.execute("DELETE FROM buckets        WHERE video_id = %s", (video_id,))
    conn.execute("DELETE FROM face_detections WHERE video_id = %s", (video_id,))
    conn.execute("DELETE FROM embeddings     WHERE video_id = %s", (video_id,))
    conn.execute("DELETE FROM scenes         WHERE video_id = %s", (video_id,))
    # Delete clips that now have no items
    conn.execute("""
        DELETE FROM clips WHERE id NOT IN (SELECT DISTINCT clip_id FROM clip_items)
    """)
    conn.execute("DELETE FROM videos WHERE id = %s", (video_id,))
    conn.commit()
    conn.close()

    # ── Cache file deletion ───────────────────────────────────
    deleted_files = 0
    for scene_id in scene_ids:
        for path in [
            DEBUG_SCENES_DIR / f"scene_{scene_id}.jpg",
            WAVEFORMS_DIR    / f"{video_stem}_{scene_id}.png",
            CLIPS_DIR        / f"{video_stem}_{scene_id}.mp4",
            CLIPS_DIR        / f"{video_stem}_bucket_{scene_id}.mp4",
        ]:
            if path.exists():
                path.unlink()
                deleted_files += 1
    for item_id in item_ids:
        path = DEBUG_SCENES_DIR / f"clip_item_{item_id}.jpg"
        if path.exists():
            path.unlink()
            deleted_files += 1

    return jsonify({
        "success": True,
        "video_id": video_id,
        "scenes_deleted": len(scene_ids),
        "cache_files_deleted": deleted_files,
    })


@app.route('/api/videos/<int:video_id>/export', methods=['GET'])
def export_video_db(video_id: int):
    """Export video metadata, scenes, tags, and clips as a downloadable zip."""
    conn = get_db_connection()

    video = conn.execute("""
        SELECT id, path, name, hash, duration, fps, width, height, codec,
               frame_offset, prompt
        FROM videos WHERE id = %s
    """, (video_id,)).fetchone()
    if not video:
        conn.close()
        return jsonify({"error": "Video not found"}), 404

    video_meta = dict(video)
    video_stem = Path(video["path"]).stem

    # ── Scenes ───────────────────────────────────────────────
    scene_rows = conn.execute("""
        SELECT id, video_id, start_time, end_time, duration,
               start_frame, end_frame, caption, rating, blurhash
        FROM scenes
        WHERE video_id = %s
        ORDER BY start_frame
    """, (video_id,)).fetchall()
    scenes = [dict(r) for r in scene_rows]
    scene_ids = [s["id"] for s in scenes]

    # ── Scene tags ────────────────────────────────────────────
    scene_tags = []
    if scene_ids:
        ph = ",".join(["%s"] * len(scene_ids))
        tag_rows = conn.execute(
            f"SELECT scene_id, tag FROM scene_tags WHERE scene_id IN ({ph}) ORDER BY scene_id, tag",
            scene_ids
        ).fetchall()
        scene_tags = [dict(r) for r in tag_rows]

    # ── Clip items (with clip name) ───────────────────────────
    clips_data = []
    if scene_ids:
        ph = ",".join(["%s"] * len(scene_ids))
        item_rows = conn.execute(f"""
            SELECT c.id as clip_id, c.name as clip_name,
                   ci.id as item_id, ci.scene_id, ci.start_frame, ci.end_frame,
                   ci.caption
            FROM clip_items ci
            JOIN clips c ON ci.clip_id = c.id
            WHERE ci.scene_id IN ({ph})
            ORDER BY c.name, ci.start_frame
        """, scene_ids).fetchall()
        clips_data = [dict(r) for r in item_rows]

    conn.close()

    # ── Build zip in memory ───────────────────────────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("video.json",      json.dumps(video_meta,  indent=2, default=str))
        zf.writestr("scenes.json",     json.dumps(scenes,      indent=2, default=str))
        zf.writestr("scene_tags.json", json.dumps(scene_tags,  indent=2, default=str))
        zf.writestr("clips.json",      json.dumps(clips_data,  indent=2, default=str))
    buf.seek(0)

    return Response(
        buf.read(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{video_stem}_db_export.zip"'},
    )


@app.route('/api/videos/import', methods=['POST'])
def import_video_db():
    """Import a zip export as a brand-new video entry (creates video + scenes)."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    f = request.files['file']
    if not f.filename.lower().endswith('.zip'):
        return jsonify({'error': 'File must be a .zip'}), 400

    try:
        raw = f.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            has_video_json = 'video.json' in names
            video_meta  = json.loads(zf.read('video.json')) if has_video_json else None
            scenes_data = json.loads(zf.read('scenes.json'))      if 'scenes.json'     in names else []
            tags_data   = json.loads(zf.read('scene_tags.json'))  if 'scene_tags.json' in names else []
            clips_data  = json.loads(zf.read('clips.json'))       if 'clips.json'      in names else []
    except Exception as e:
        return jsonify({'error': f'Failed to read zip: {e}'}), 400

    conn = get_db_connection()

    if not has_video_json:
        # No video metadata — ask the client to pick an existing video
        video_id_param = request.form.get('video_id')
        if not video_id_param:
            conn.close()
            return jsonify({'needs_video_selection': True}), 422
        try:
            video_id = int(video_id_param)
        except ValueError:
            conn.close()
            return jsonify({'error': 'Invalid video_id'}), 400
        if not conn.execute("SELECT 1 FROM videos WHERE id = %s", (video_id,)).fetchone():
            conn.close()
            return jsonify({'error': 'Video not found'}), 404
    else:
        # Resolve path — append suffix if already taken by a different hash
        orig_path = video_meta['path']
        orig_hash = video_meta['hash']

        existing_by_hash = conn.execute(
            "SELECT id FROM videos WHERE hash = %s", (orig_hash,)
        ).fetchone()
        if existing_by_hash:
            conn.close()
            return jsonify({'error': 'A video with this file hash already exists in the database'}), 409

        path = orig_path
        if conn.execute("SELECT 1 FROM videos WHERE path = %s", (path,)).fetchone():
            stem, ext = (path.rsplit('.', 1) + [''])[:2]
            suffix = 1
            while conn.execute("SELECT 1 FROM videos WHERE path = %s",
                               (f"{stem}_import{suffix}.{ext}" if ext else f"{stem}_import{suffix}",)).fetchone():
                suffix += 1
            path = f"{stem}_import{suffix}.{ext}" if ext else f"{stem}_import{suffix}"

        cur = conn.execute("""
            INSERT INTO videos (path, hash, duration, fps, width, height, codec, frame_offset, name, prompt)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            path, orig_hash,
            video_meta.get('duration'), video_meta.get('fps'),
            video_meta.get('width'),    video_meta.get('height'),
            video_meta.get('codec'),    video_meta.get('frame_offset', 0),
            video_meta.get('name'),     video_meta.get('prompt'),
        ))
        video_id = cur.fetchone()['id']

    stats = {'scenes_created': 0, 'tags_added': 0, 'clip_items_added': 0}
    id_map = {}  # exported scene id → new scene id

    for scene in scenes_data:
        try:
            ins = conn.execute("""
                INSERT INTO scenes
                    (video_id, start_time, end_time, duration,
                     start_frame, end_frame, caption, rating, blurhash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (video_id, start_time, end_time) DO UPDATE
                    SET caption  = EXCLUDED.caption,
                        rating   = EXCLUDED.rating,
                        blurhash = EXCLUDED.blurhash
                RETURNING id
            """, (
                video_id,
                scene['start_time'], scene['end_time'], scene['duration'],
                scene.get('start_frame'), scene.get('end_frame'),
                scene.get('caption'), scene.get('rating'), scene.get('blurhash'),
            ))
            new_id = ins.fetchone()['id']
            id_map[scene['id']] = new_id
            stats['scenes_created'] += 1
        except Exception:
            pass

    for entry in tags_data:
        old_id = entry.get('scene_id')
        tag = (entry.get('tag') or '').strip()
        if not tag or old_id not in id_map:
            continue
        cur_id = id_map[old_id]
        if not conn.execute("SELECT 1 FROM scene_tags WHERE scene_id = %s AND tag = %s",
                            (cur_id, tag)).fetchone():
            conn.execute("INSERT INTO scene_tags (scene_id, tag) VALUES (%s, %s)", (cur_id, tag))
            stats['tags_added'] += 1

    for item in clips_data:
        old_id    = item.get('scene_id')
        clip_name = (item.get('clip_name') or '').strip()
        if not clip_name or old_id not in id_map:
            continue
        cur_scene_id = id_map[old_id]

        clip_row = conn.execute("SELECT id FROM clips WHERE name = %s", (clip_name,)).fetchone()
        clip_id  = clip_row['id'] if clip_row else conn.execute(
            "INSERT INTO clips (name) VALUES (%s) RETURNING id", (clip_name,)
        ).fetchone()['id']

        if not conn.execute("SELECT 1 FROM clip_items WHERE clip_id = %s AND scene_id = %s",
                            (clip_id, cur_scene_id)).fetchone():
            conn.execute(
                "INSERT INTO clip_items (clip_id, scene_id, video_id, start_frame, end_frame, caption)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (clip_id, cur_scene_id, video_id,
                 item.get('start_frame', 0), item.get('end_frame', 0),
                 item.get('caption', '')),
            )
            stats['clip_items_added'] += 1

    conn.commit()
    conn.close()
    return jsonify({'success': True, 'video_id': video_id, 'stats': stats})


@app.route('/api/bucket/<int:scene_id>', methods=['PUT'])
def update_bucket(scene_id: int):
    """Update the bucket window offset and/or frame count."""
    data = request.get_json()
    if data is None or 'offset_frames' not in data:
        return jsonify({"error": "Missing offset_frames"}), 400

    offset_frames = int(data['offset_frames'])

    conn = get_db_connection()
    bucket = conn.execute("SELECT * FROM buckets WHERE scene_id = %s", (scene_id,)).fetchone()
    if not bucket:
        conn.close()
        return jsonify({"error": "Bucket not found"}), 404

    video = conn.execute("""
        SELECT v.fps, v.frame_offset FROM videos v
        JOIN scenes s ON s.video_id = v.id WHERE s.id = %s
    """, (scene_id,)).fetchone()
    scene = conn.execute("SELECT start_frame, end_frame, start_time, end_time FROM scenes WHERE id = %s", (scene_id,)).fetchone()
    conn.close()

    if not video or not scene:
        return jsonify({"error": "Scene/video not found"}), 404

    fps = video["fps"] or 24.0
    scene_start_frame = scene["start_frame"] or 0
    if scene["end_frame"] is not None and scene["start_frame"] is not None:
        scene_frame_count = scene["end_frame"] - scene["start_frame"]
    else:
        scene_frame_count = round((scene["end_time"] - scene["start_time"]) * fps)

    # Use provided frame_count or fall back to current
    if 'frame_count' in data:
        frame_count = max(1, min(scene_frame_count, int(data['frame_count'])))
    else:
        frame_count = bucket["frame_count"]

    # Clamp offset so bucket doesn't exceed scene
    offset_frames = max(0, min(scene_frame_count - frame_count, offset_frames))

    new_start_frame = scene_start_frame + offset_frames
    new_end_frame = new_start_frame + frame_count
    new_start_time = new_start_frame / fps
    new_end_time = new_end_frame / fps
    new_duration = frame_count / fps

    conn = get_db_connection()
    conn.execute("""
        UPDATE buckets SET
            frame_count = %s,
            optimal_offset_frames = %s,
            start_frame = %s,
            end_frame = %s,
            start_time = %s,
            end_time = %s,
            duration = %s,
            optimal_duration = %s,
            bucket_timestamp = CURRENT_TIMESTAMP
        WHERE scene_id = %s
    """, (frame_count, offset_frames, new_start_frame, new_end_frame,
          new_start_time, new_end_time, new_duration, new_duration, scene_id))
    conn.commit()
    saved = conn.execute("SELECT * FROM buckets WHERE scene_id = %s", (scene_id,)).fetchone()
    scene_fc = conn.execute("SELECT start_frame, end_frame FROM scenes WHERE id = %s", (scene_id,)).fetchone()
    conn.close()

    result = dict(saved)
    result["scene_frame_count"] = scene_frame_count
    return jsonify({"bucket": result})


@app.route('/api/bucket/<int:scene_id>')
def get_bucket_data(scene_id: int):
    """Get bucket data for a scene."""
    conn = get_db_connection()

    bucket = conn.execute("SELECT * FROM buckets WHERE scene_id = %s", (scene_id,)).fetchone()
    if not bucket:
        conn.close()
        return jsonify({"bucket": None})

    result = dict(bucket)

    scene = conn.execute("SELECT start_frame, end_frame, start_time, end_time FROM scenes WHERE id = %s", (scene_id,)).fetchone()
    fps = conn.execute("SELECT v.fps FROM videos v JOIN scenes s ON s.video_id = v.id WHERE s.id = %s", (scene_id,)).fetchone()
    if scene:
        if scene["start_frame"] is not None and scene["end_frame"] is not None:
            result["scene_frame_count"] = scene["end_frame"] - scene["start_frame"]
        elif scene["start_time"] is not None and scene["end_time"] is not None and fps:
            result["scene_frame_count"] = round((scene["end_time"] - scene["start_time"]) * (fps["fps"] or 24.0))
    conn.close()

    return jsonify({"bucket": result})


@app.route('/bucket_clip/<int:scene_id>')
def serve_bucket_clip(scene_id: int):
    """Extract and serve an optimal bucket clip."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    # Look up bucket + video info from DB
    conn = get_db_connection()
    bucket_row = conn.execute("""
        SELECT * FROM buckets WHERE scene_id = %s
    """, (scene_id,)).fetchone()
    
    if not bucket_row:
        conn.close()
        return jsonify({"error": "Bucket not found"}), 404
    
    bucket = dict(bucket_row)
    
    # Get video info
    video_row = conn.execute("""
        SELECT v.path as video_path, v.fps, v.frame_offset
        FROM videos v
        JOIN buckets b ON b.video_id = v.id
        WHERE b.scene_id = %s
    """, (scene_id,)).fetchone()
    
    if not video_row:
        conn.close()
        return jsonify({"error": "Video not found"}), 404
    
    conn.close()

    video_file = Path(video_row["video_path"])
    if not video_file.exists():
        return jsonify({"error": "Video file not found"}), 404

    video_stem = video_file.stem
    cache_path = CLIPS_DIR / f"{video_stem}_bucket_{scene_id}.mp4"

    if cache_path.exists():
        return send_file(cache_path, mimetype='video/mp4', conditional=True)

    fps = video_row["fps"] or 24.0
    frame_offset = video_row["frame_offset"] or 0

    # Use bucket frame numbers directly
    start_frame = bucket["start_frame"]
    end_frame = bucket["end_frame"]
    
    # Calculate timestamps from frames
    start_time = (start_frame + frame_offset + 1) / fps
    duration = (end_frame - start_frame) / fps

    start_time = max(0.0, start_time)
    
    if duration <= 0:
        return jsonify({"error": "Invalid bucket duration"}), 400

    cmd = [
        'ffmpeg',
        '-ss', f'{start_time:.6f}',
        '-i', str(video_file),
        '-t', f'{duration:.6f}',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '23',
        '-c:a', 'aac',
        '-movflags', '+faststart',
        '-f', 'mp4',
        '-y',
        str(cache_path),
    ]

    result = subprocess.run(cmd, stderr=subprocess.DEVNULL)
    if result.returncode != 0 or not cache_path.exists():
        return jsonify({"error": "Bucket clip generation failed"}), 500

    return send_file(cache_path, mimetype='video/mp4', conditional=True)


@app.route('/bucket_waveform/<int:scene_id>')
def serve_bucket_waveform(scene_id: int):
    """Serve waveform for bucket segment."""
    # Get bucket data
    conn = get_db_connection()
    bucket = conn.execute("""
        SELECT * FROM buckets WHERE scene_id = %s
    """, (scene_id,)).fetchone()
    
    if not bucket:
        conn.close()
        return jsonify({"error": "Bucket not found"}), 404
    
    # Get video info
    video_row = conn.execute("""
        SELECT v.path as video_path, v.fps, v.frame_offset
        FROM videos v
        JOIN buckets b ON b.video_id = v.id
        WHERE b.scene_id = %s
    """, (scene_id,)).fetchone()
    
    if not video_row:
        conn.close()
        return jsonify({"error": "Video not found"}), 404
    
    conn.close()
    
    video_file = Path(video_row["video_path"])
    fps = video_row["fps"] or 24.0
    frame_offset = video_row["frame_offset"] or 0
    
    # Calculate bucket start time
    start_time = (bucket["start_frame"] + frame_offset + 1) / fps
    duration = bucket["frame_count"] / fps
    
    # Generate waveform
    waveform_bytes = _generate_rms_waveform_png(video_file, start_time, duration)
    if waveform_bytes:
        return Response(waveform_bytes, mimetype='image/png')
    
    return jsonify({"error": "Waveform generation failed"}), 500


@app.route('/api/clips', methods=['GET'])
def get_clips():
    """List all clips with item count."""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT c.id, c.name, c.caption_prompt, c.created_at,
               COUNT(ci.id) as item_count,
               COALESCE(SUM(ci.end_frame - ci.start_frame), 0) as total_frames
        FROM clips c
        LEFT JOIN clip_items ci ON ci.clip_id = c.id
        GROUP BY c.id, c.name, c.caption_prompt, c.created_at
        ORDER BY c.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify({"clips": [dict(r) for r in rows]})


@app.route('/api/clips', methods=['POST'])
def create_clip():
    """Create a new clip."""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({"error": "Missing name"}), 400
    name = data['name'].strip()
    if not name:
        return jsonify({"error": "Empty name"}), 400
    conn = get_db_connection()
    cur = conn.execute("INSERT INTO clips (name) VALUES (%s) RETURNING *", (name,))
    conn.commit()
    row = cur.fetchone()
    conn.close()
    return jsonify({"clip": dict(row)}), 201


@app.route('/api/clips/<int:clip_id>', methods=['PUT'])
def update_clip(clip_id: int):
    """Update a clip's name and/or caption_prompt."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing data"}), 400
    has_name = 'name' in data
    has_prompt = 'caption_prompt' in data
    if not has_name and not has_prompt:
        return jsonify({"error": "Nothing to update"}), 400
    name = data['name'].strip() if has_name else None
    if has_name and not name:
        return jsonify({"error": "Empty name"}), 400
    conn = get_db_connection()
    if conn.execute("SELECT id FROM clips WHERE id = %s", (clip_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404
    if has_name:
        conn.execute("UPDATE clips SET name = %s WHERE id = %s", (name, clip_id))
    if has_prompt:
        prompt_val = data['caption_prompt'].strip() if data['caption_prompt'] else None
        conn.execute("UPDATE clips SET caption_prompt = %s WHERE id = %s", (prompt_val, clip_id))
    conn.commit()
    row = conn.execute("SELECT c.id, c.name, c.caption_prompt, c.created_at FROM clips c WHERE c.id = %s", (clip_id,)).fetchone()
    conn.close()
    return jsonify({"clip": dict(row)})


@app.route('/api/clips/<int:clip_id>', methods=['DELETE'])
def delete_clip(clip_id: int):
    """Delete a clip and all its items."""
    conn = get_db_connection()
    if conn.execute("SELECT id FROM clips WHERE id = %s", (clip_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404
    conn.execute("DELETE FROM clip_items WHERE clip_id = %s", (clip_id,))
    conn.execute("DELETE FROM clips WHERE id = %s", (clip_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


def _is_hdr_video(video_path: Path) -> bool:
    """Return True if the video stream uses an HDR transfer characteristic or 10-bit pixel format."""
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_streams', '-select_streams', 'v:0', str(video_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return False
        import json as _json
        streams = _json.loads(result.stdout).get('streams', [])
        if not streams:
            return False
        s = streams[0]
        transfer = s.get('color_transfer', '')
        pix_fmt  = s.get('pix_fmt', '')
        # HDR transfers: smpte2084 (PQ/HDR10), arib-std-b67 (HLG)
        hdr_transfers = {'smpte2084', 'arib-std-b67', 'smpte428', 'bt2020-10', 'bt2020-12'}
        if transfer in hdr_transfers:
            return True
        # 10-bit pixel formats are a strong indicator even without explicit transfer metadata
        if '10le' in pix_fmt or '10be' in pix_fmt or '12le' in pix_fmt or '12be' in pix_fmt:
            return True
        return False
    except Exception:
        return False


def _build_export_cmd(video_file: Path, start_time: float, duration: float,
                      out_path: Path, tonemap: bool) -> list:
    vf = (
        'zscale=transfer=linear:npl=100,format=gbrpf32le,'
        'zscale=primaries=bt709,tonemap=tonemap=hable:desat=0,'
        'zscale=transfer=bt709:matrix=bt709:range=tv,'
        'format=yuv420p'
        if tonemap else 'format=yuv420p'
    )
    return [
        'ffmpeg', '-y',
        '-ss', f'{start_time:.6f}',
        '-i', str(video_file),
        '-t', f'{duration:.6f}',
        '-vf', vf,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '18',
        '-pix_fmt', 'yuv420p',
        '-ac', '2',
        '-c:a', 'aac',
        '-movflags', '+faststart',
        '-f', 'mp4',
        str(out_path),
    ]


# token → (zip_bytes, filename) for pending downloads
_export_store: dict = {}


@app.route('/api/clips/<int:clip_id>/export/stream')
def export_clip_stream(clip_id: int):
    """SSE stream: encodes items one-by-one, emits progress, stores zip, sends download token."""
    import zipfile, tempfile, secrets, json as _json

    conn = get_db_connection()
    coll = conn.execute("SELECT * FROM clips WHERE id = %s", (clip_id,)).fetchone()
    if not coll:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404

    rows = conn.execute("""
        SELECT ci.id, ci.scene_id, ci.video_id, ci.start_frame, ci.end_frame,
               v.path as video_path, v.fps, v.frame_offset,
               COALESCE(NULLIF(ci.caption, ''), s.caption) AS caption
        FROM clip_items ci
        JOIN videos v ON ci.video_id = v.id
        JOIN scenes s ON ci.scene_id = s.id
        WHERE ci.clip_id = %s
        ORDER BY ci.created_at ASC
    """, (clip_id,)).fetchall()
    conn.close()

    if not rows:
        def _err():
            yield "data: " + _json.dumps({"error": "Collection is empty"}) + "\n\n"
        return Response(_err(), mimetype='text/event-stream')

    clip_slug = re.sub(r'[^\w\-]', '_', coll['name']).strip('_')
    total = len(rows)

    def generate():
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            zip_buf = io.BytesIO()
            hdr_cache: dict = {}

            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for i, row in enumerate(rows):
                    item = dict(row)
                    fps = item['fps'] or 24.0
                    frame_offset = item['frame_offset'] or 0
                    video_file = Path(item['video_path'])

                    stem = f"{i + 1:04d}_scene{item['scene_id']}"
                    mp4_name = f"{stem}.mp4"
                    txt_name = f"{stem}.txt"
                    mp4_path = tmpdir_path / mp4_name

                    if video_file.exists():
                        start_time = max(0.0, (item['start_frame'] + frame_offset + 1) / fps)
                        duration   = (item['end_frame'] - item['start_frame']) / fps

                        if duration > 0:
                            vf_key = str(video_file)
                            if vf_key not in hdr_cache:
                                hdr_cache[vf_key] = _is_hdr_video(video_file)
                            is_hdr = hdr_cache[vf_key]
                            ok = False
                            if is_hdr:
                                cmd = _build_export_cmd(video_file, start_time, duration, mp4_path, tonemap=True)
                                result = subprocess.run(cmd, stderr=subprocess.DEVNULL)
                                ok = result.returncode == 0 and mp4_path.exists()
                            if not ok:
                                cmd = _build_export_cmd(video_file, start_time, duration, mp4_path, tonemap=False)
                                result = subprocess.run(cmd, stderr=subprocess.DEVNULL)
                                ok = result.returncode == 0 and mp4_path.exists()
                            if ok:
                                zf.write(mp4_path, mp4_name)

                    caption = (item.get('caption') or '').strip()
                    if caption and not caption.startswith('__'):
                        zf.writestr(txt_name, caption)

                    yield "data: " + _json.dumps({"done": i + 1, "total": total}) + "\n\n"

            token = secrets.token_hex(16)
            _export_store[token] = (zip_buf.getvalue(), f'{clip_slug}.zip')
            yield "data: " + _json.dumps({"token": token}) + "\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})


@app.route('/api/clips/export/download/<token>')
def export_clip_download(token: str):
    """Serve the pre-built zip for a given export token (one-time)."""
    entry = _export_store.pop(token, None)
    if not entry:
        return jsonify({"error": "Invalid or expired token"}), 404
    zip_bytes, filename = entry
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename,
    )


@app.route('/api/clips/<int:clip_id>/items', methods=['GET'])
def get_clip_items(clip_id: int):
    """Get all items in a clip with scene/video metadata."""
    sort = request.args.get('sort', '')
    order_by = (
        "ci.start_frame ASC" if sort == "frames_asc"
        else "ci.start_frame DESC" if sort == "frames_desc"
        else "ci.created_at ASC"
    )
    conn = get_db_connection()
    if conn.execute("SELECT id FROM clips WHERE id = %s", (clip_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404
    rows = conn.execute(f"""
        SELECT ci.id, ci.scene_id, ci.video_id, ci.start_frame, ci.end_frame, ci.created_at,
               ci.caption as item_caption,
               v.path as video_path, v.fps, v.frame_offset,
               COALESCE(v.name, '') as video_name_custom,
               s.caption as scene_caption, s.start_time, s.end_time, s.rating, s.blurhash,
               s.start_frame as scene_start_frame, s.end_frame as scene_end_frame,
               (SELECT STRING_AGG(st.tag, '|') FROM scene_tags st WHERE st.scene_id = s.id) as tags_concat
        FROM clip_items ci
        JOIN videos v ON ci.video_id = v.id
        JOIN scenes s ON ci.scene_id = s.id
        WHERE ci.clip_id = %s
        ORDER BY {order_by}
    """, (clip_id,)).fetchall()
    conn.close()
    items = []
    for r in rows:
        d = dict(r)
        video_display = d['video_name_custom'] or Path(d['video_path']).stem
        tags_raw = d.get('tags_concat') or ''
        t = int(d.get('start_time') or 0)
        items.append({
            'id': d['id'],
            'scene_id': d['scene_id'],
            'video_id': d['video_id'],
            'start_frame': d['start_frame'],
            'end_frame': d['end_frame'],
            'frame_count': d['end_frame'] - d['start_frame'],
            'created_at': d['created_at'],
            'video_name': video_display,
            'video_path': d['video_path'],
            'fps': d['fps'] or 24.0,
            'frame_offset': d['frame_offset'] or 0,
            'caption': d['item_caption'] or '',
            'scene_caption': d['scene_caption'] or '',
            'tags': [tag for tag in tags_raw.split('|') if tag],
            'start_time': d.get('start_time'),
            'end_time': d.get('end_time'),
            'start_time_hms': f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}",
            'duration': (d['end_frame'] - d['start_frame']) / (d['fps'] or 24.0),
            'rating': d.get('rating'),
            'blurhash': d.get('blurhash'),
            'scene_start_frame': d.get('scene_start_frame') or 0,
            'scene_end_frame': d.get('scene_end_frame') or 0,
        })
    return jsonify({"items": items})


@app.route('/api/clips/<int:clip_id>/items', methods=['POST'])
def add_clip_item(clip_id: int):
    """Add a scene's bucket to a clip."""
    data = request.get_json()
    if not data or 'scene_id' not in data:
        return jsonify({"error": "Missing scene_id"}), 400
    scene_id = int(data['scene_id'])

    conn = get_db_connection()
    if conn.execute("SELECT id FROM clips WHERE id = %s", (clip_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404

    bucket = conn.execute("SELECT * FROM buckets WHERE scene_id = %s", (scene_id,)).fetchone()
    if not bucket:
        conn.close()
        return jsonify({"error": "No bucket found for this scene."}), 400

    scene = conn.execute("SELECT video_id FROM scenes WHERE id = %s", (scene_id,)).fetchone()
    if not scene:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404

    video_id = scene['video_id']
    start_frame = bucket['start_frame']
    end_frame = bucket['end_frame']

    try:
        cur = conn.execute("""
            INSERT INTO clip_items (clip_id, scene_id, video_id, start_frame, end_frame)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (clip_id, scene_id, video_id, start_frame, end_frame))
        conn.commit()
        item_id = cur.fetchone()["id"]
        conn.close()
        return jsonify({
            "item_id": item_id, "clip_id": clip_id,
            "scene_id": scene_id, "video_id": video_id,
            "start_frame": start_frame, "end_frame": end_frame,
        }), 201
    except psycopg2.errors.UniqueViolation:
        existing = conn.execute(
            "SELECT id FROM clip_items WHERE clip_id = %s AND scene_id = %s",
            (clip_id, scene_id)
        ).fetchone()
        conn.close()
        return jsonify({"item_id": existing['id'] if existing else None, "already_exists": True}), 200


@app.route('/api/clips/<int:clip_id>/items/<int:item_id>', methods=['PUT'])
def update_clip_item(clip_id: int, item_id: int):
    """Update the start_frame and end_frame of a clip item."""
    data = request.get_json()
    if data is None or 'start_frame' not in data or 'end_frame' not in data:
        return jsonify({"error": "Missing start_frame or end_frame"}), 400
    start_frame = int(data['start_frame'])
    end_frame = int(data['end_frame'])
    if end_frame <= start_frame:
        return jsonify({"error": "end_frame must be greater than start_frame"}), 400
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id FROM clip_items WHERE id = %s AND clip_id = %s",
        (item_id, clip_id)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Item not found"}), 404
    conn.execute(
        "UPDATE clip_items SET start_frame = %s, end_frame = %s WHERE id = %s",
        (start_frame, end_frame, item_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"item_id": item_id, "start_frame": start_frame, "end_frame": end_frame,
                    "frame_count": end_frame - start_frame})


@app.route('/api/clips/<int:clip_id>/items/<int:item_id>/caption', methods=['PUT'])
def update_clip_item_caption(clip_id: int, item_id: int):
    """Update the caption of a clip item (independent of the scene caption)."""
    data = request.get_json()
    if data is None or 'caption' not in data:
        return jsonify({"error": "Missing caption"}), 400
    caption = data['caption']
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id FROM clip_items WHERE id = %s AND clip_id = %s",
        (item_id, clip_id)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Item not found"}), 404
    conn.execute("UPDATE clip_items SET caption = %s WHERE id = %s", (caption, item_id))
    conn.commit()
    conn.close()
    return jsonify({"item_id": item_id, "caption": caption})


@app.route('/api/clips/<int:clip_id>/items/<int:item_id>', methods=['DELETE'])
def remove_clip_item(clip_id: int, item_id: int):
    """Remove an item from a clip."""
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM clip_items WHERE id = %s AND clip_id = %s",
        (item_id, clip_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/api/scenes/<int:scene_id>/clip_items', methods=['GET'])
def get_scene_clip_items(scene_id: int):
    """Get all clip items for a given scene, with clip metadata."""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT ci.id, ci.scene_id, ci.video_id, ci.clip_id,
               ci.start_frame, ci.end_frame, ci.created_at,
               ci.caption as item_caption,
               c.name as clip_name,
               v.path as video_path, v.fps, v.frame_offset,
               COALESCE(v.name, '') as video_name_custom,
               s.caption as scene_caption, s.start_time, s.end_time, s.rating, s.blurhash,
               s.start_frame as scene_start_frame, s.end_frame as scene_end_frame
        FROM clip_items ci
        JOIN clips c ON ci.clip_id = c.id
        JOIN videos v ON ci.video_id = v.id
        JOIN scenes s ON ci.scene_id = s.id
        WHERE ci.scene_id = %s
        ORDER BY c.name ASC, ci.created_at ASC
    """, (scene_id,)).fetchall()
    conn.close()
    items = []
    for r in rows:
        d = dict(r)
        video_display = d['video_name_custom'] or Path(d['video_path']).stem
        t = int(d.get('start_time') or 0)
        items.append({
            'id': d['id'],
            'scene_id': d['scene_id'],
            'video_id': d['video_id'],
            'clip_id': d['clip_id'],
            'clip_name': d['clip_name'],
            'start_frame': d['start_frame'],
            'end_frame': d['end_frame'],
            'frame_count': d['end_frame'] - d['start_frame'],
            'created_at': d['created_at'],
            'video_name': video_display,
            'video_path': d['video_path'],
            'fps': d['fps'] or 24.0,
            'frame_offset': d['frame_offset'] or 0,
            'caption': d.get('item_caption') or '',
            'start_time': d.get('start_time'),
            'end_time': d.get('end_time'),
            'start_time_hms': f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}",
            'duration': (d.get('end_time') or 0) - (d.get('start_time') or 0),
            'rating': d.get('rating'),
            'blurhash': d.get('blurhash'),
            'scene_start_frame': d.get('scene_start_frame') or 0,
            'scene_end_frame': d.get('scene_end_frame') or 0,
        })
    return jsonify({"items": items})


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description="Web frontend for caption review")
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"Caption Review Server")
    print(f"{'='*50}")
    print(f"Database: {_get_dsn()}")
    print(f"Previews: {DEBUG_SCENES_DIR}")
    print(f"URL: http://{args.host}:{args.port}")
    print(f"{'='*50}\n")

    # Pre-load InsightFace model so the first /api/tag-refs POST doesn't block
    try:
        from ltx2_dataset_builder.faces.detect import get_face_analyzer
        get_face_analyzer('buffalo_l')
        print("InsightFace buffalo_l model ready.")
    except Exception as _e:
        print(f"Warning: could not pre-load InsightFace model: {_e}")

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
