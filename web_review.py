#!/usr/bin/env python3
"""Web frontend for reviewing scene captions."""

import sqlite3
import re
import subprocess
import io
from pathlib import Path
from typing import Optional
from flask import Flask, send_from_directory, request, jsonify, Response, send_file
import yaml
from PIL import Image, ImageDraw

from ltx2_dataset_builder.utils.preview import generate_scene_preview  # noqa: E402

app = Flask(__name__)

UI_DIST = Path(__file__).parent / 'ui' / 'dist'
UI_SRC = Path(__file__).parent / 'ui' / 'src'  # For development without rebuild

# Load config
_HERE = Path(__file__).parent

CONFIG_PATH = _HERE / "config.yaml"
if CONFIG_PATH.exists():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
else:
    config = {
        "db_path": ".cache/index.db",
        "output_dir": "./dataset"
    }

def _resolve(p: str) -> Path:
    """Resolve a config path relative to the project root, not the cwd."""
    path = Path(p)
    return path if path.is_absolute() else _HERE / path

DB_PATH = _resolve(config.get("db_path", ".cache/index.db"))
OUTPUT_DIR = _resolve(config.get("output_dir", "./dataset"))
DEBUG_SCENES_DIR = _HERE / ".cache/previews"
WAVEFORMS_DIR = _HERE / ".cache/waveforms"
CLIPS_DIR     = Path(".cache/clips")


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tags_table():
    """Create scene_tags table if it doesn't exist."""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_tags (
            scene_id INTEGER NOT NULL,
            tag      TEXT    NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scene_id, tag),
            FOREIGN KEY (scene_id) REFERENCES scenes(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()


def ensure_tag_definitions_table():
    """Create tag_definitions table if it doesn't exist, and migrate schema."""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tag_definitions (
            tag          TEXT PRIMARY KEY,
            description  TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT ''
        )
    """)
    # Migrate: add display_name column if upgrading from older schema
    try:
        conn.execute("ALTER TABLE tag_definitions ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass  # column already exists
    conn.commit()
    conn.close()


try:
    ensure_tags_table()
    ensure_tag_definitions_table()
except Exception:
    pass


def ensure_videos_prompt_column():
    """Add prompt column to videos table if it doesn't exist."""
    conn = get_db_connection()
    try:
        conn.execute("ALTER TABLE videos ADD COLUMN prompt TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    finally:
        conn.close()


try:
    ensure_videos_prompt_column()
except Exception:
    pass


def ensure_rating_column():
    """Add rating column to scenes table if it doesn't exist."""
    conn = get_db_connection()
    try:
        conn.execute("ALTER TABLE scenes ADD COLUMN rating INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    finally:
        conn.close()


try:
    ensure_rating_column()
except Exception:
    pass


def ensure_collections_tables():
    """Create collections and collection_items tables if they don't exist."""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collection_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL,
            scene_id      INTEGER NOT NULL,
            video_id      INTEGER NOT NULL,
            start_frame   INTEGER NOT NULL,
            end_frame     INTEGER NOT NULL,
            caption       TEXT DEFAULT '',
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
            FOREIGN KEY (scene_id) REFERENCES scenes(id) ON DELETE CASCADE,
            UNIQUE (collection_id, scene_id)
        )
    """)
    # Migration: add caption column if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE collection_items ADD COLUMN caption TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass  # column already exists
    # Migration: add caption_prompt column to collections if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE collections ADD COLUMN caption_prompt TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists
    conn.commit()
    conn.close()


try:
    ensure_collections_tables()
except Exception:
    pass

try:
    from ltx2_dataset_builder.utils.io import Database as _Db
    _n = _Db(DB_PATH).backfill_default_buckets()
    if _n:
        print(f"[startup] Backfilled {_n} default bucket(s)")
except Exception as _e:
    print(f"[startup] Bucket backfill skipped: {_e}")


def find_preview_for_scene(video_name: str, scene_idx: int, start_frame: int = None) -> str | None:
    """Find preview image for a scene."""
    if not DEBUG_SCENES_DIR.exists():
        return None
    
    # Try to match by video name and scene index
    pattern = f"{video_name}_scene_{scene_idx:04d}_*.png"
    matches = list(DEBUG_SCENES_DIR.glob(pattern))
    if matches:
        return matches[0].name
    
    # Fallback: try looser matching
    for f in DEBUG_SCENES_DIR.iterdir():
        if f.suffix == '.png' and video_name in f.stem:
            # Extract scene number from filename
            match = re.search(r'scene_(\d+)', f.stem)
            if match and int(match.group(1)) == scene_idx:
                return f.name
    
    return None


@app.route('/')
def index():
    """Serve React UI."""
    return send_from_directory(UI_DIST, 'index.html')


@app.route('/assets/<path:filename>')
def serve_ui_assets(filename):
    """Serve Vite-built JS/CSS assets."""
    return send_from_directory(UI_DIST / 'assets', filename)


@app.route('/preview/<path:filename>')
def preview(filename):
    """Serve preview images."""
    return send_from_directory(DEBUG_SCENES_DIR, filename)


@app.route('/scene_preview/<int:scene_id>')
def scene_preview(scene_id: int):
    """
    Generate and serve a preview image for a scene on-the-fly.
    
    Falls back to static preview if it exists, otherwise generates dynamically.
    """
    conn = get_db_connection()
    
    # Get scene and video info
    row = conn.execute("""
        SELECT s.*, v.path as video_path, v.fps, v.frame_offset
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        WHERE s.id = ?
    """, (scene_id,)).fetchone()
    conn.close()
    
    if row is None:
        return jsonify({"error": "Scene not found"}), 404
    
    video_path = Path(row["video_path"])
    fps = row["fps"] or 24.0
    frame_offset = row["frame_offset"] or 0
    
    # Get frame numbers
    start_frame = row["start_frame"]
    end_frame = row["end_frame"]
    
    # Fall back to calculating from timestamps if frames not stored
    if start_frame is None or end_frame is None:
        start_frame = int(row["start_time"] * fps)
        end_frame = int(row["end_time"] * fps)
    
    # Serve from cache if available
    cache_path = DEBUG_SCENES_DIR / f"scene_{scene_id}.jpg"
    if cache_path.exists():
        return send_file(cache_path, mimetype='image/jpeg')

    # Generate preview
    preview_bytes = generate_scene_preview(
        video_path=video_path,
        start_frame=start_frame,
        end_frame=end_frame,
        fps=fps,
        frame_offset=frame_offset,
    )

    if preview_bytes is None:
        return jsonify({"error": "Failed to generate preview"}), 500

    # Cache to disk
    DEBUG_SCENES_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(preview_bytes)

    return Response(
        preview_bytes,
        mimetype='image/jpeg',
        headers={'Cache-Control': 'max-age=3600'}
    )


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
        WHERE s.id = ?
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
        WHERE s.id = ?
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
    filter_type = request.args.get('filter', 'captioned')
    video_filter = request.args.get('video', '')
    page = max(1, int(request.args.get('page', 1) or 1))
    limit = min(50, int(request.args.get('limit', 50) or 50))

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

    if filter_type in ('captioned', 'recent'):
        conditions.append("s.caption IS NOT NULL AND s.caption != '' AND substr(s.caption, 1, 2) != '__'")
    elif filter_type == 'uncaptioned':
        conditions.append("(s.caption IS NULL OR s.caption = '' OR substr(s.caption, 1, 2) = '__')")

    if video_filter:
        conditions.append("v.id = ?")
        params.append(int(video_filter))

    # Tag include filter
    if include_tags:
        if include_mode == 'or':
            ph = ','.join(['?'] * len(include_tags))
            conditions.append(f"EXISTS (SELECT 1 FROM scene_tags st2 WHERE st2.scene_id = s.id AND st2.tag IN ({ph}))")
            params.extend(include_tags)
        else:  # AND — each tag must be present
            for tag in include_tags:
                conditions.append("EXISTS (SELECT 1 FROM scene_tags st2 WHERE st2.scene_id = s.id AND st2.tag = ?)")
                params.append(tag)

    # Tag exclude filter
    for tag in exclude_tags:
        conditions.append("NOT EXISTS (SELECT 1 FROM scene_tags st2 WHERE st2.scene_id = s.id AND st2.tag = ?)")
        params.append(tag)

    # Min frames
    if min_frames > 0:
        conditions.append("(COALESCE(s.end_frame, 0) - COALESCE(s.start_frame, 0)) >= ?")
        params.append(min_frames)

    # Rating filter
    if rating_values:
        rating_parts = []
        numeric = [v for v in rating_values if v != 'unranked']
        if 'unranked' in rating_values:
            rating_parts.append("s.rating IS NULL")
        if numeric:
            ph = ','.join(['?'] * len(numeric))
            rating_parts.append(f"s.rating IN ({ph})")
            params.extend([int(v) for v in numeric])
        if rating_parts:
            conditions.append(f"({' OR '.join(rating_parts)})")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    scenes_from = "FROM scenes s JOIN videos v ON s.video_id = v.id"

    total = conn.execute(
        f"SELECT COUNT(*) {scenes_from} {where_clause}",
        params
    ).fetchone()[0]

    offset = (page - 1) * limit
    
    base_query = f"""
        SELECT s.*, v.path as video_path, v.fps, v.frame_offset,
            (SELECT COUNT(*) FROM scenes s2 WHERE s2.video_id = s.video_id AND s2.id < s.id) as scene_idx,
            (SELECT COUNT(*) FROM collection_items ci WHERE ci.scene_id = s.id) as collection_count,
            GROUP_CONCAT(st.tag, '|') as tags_concat
        {scenes_from}
        LEFT JOIN scene_tags st ON st.scene_id = s.id
        {where_clause}
        GROUP BY s.id
        ORDER BY {
            "s.caption_finished_at DESC NULLS LAST, s.id DESC" if filter_type == "recent"
            else "s.start_frame ASC, s.video_id, s.id" if sort == "frames_asc"
            else "s.start_frame DESC, s.video_id, s.id" if sort == "frames_desc"
            else "s.video_id, s.id"
        }
        LIMIT {limit} OFFSET {offset}
    """
    
    rows = conn.execute(base_query, params).fetchall()
    conn.close()

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
        preview_path = find_preview_for_scene(video_name, scene_idx, d.get('start_frame'))
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
            'start_time_hms': f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}",
            'duration': duration,
            'frame_count': (d.get('end_frame') or 0) - (d.get('start_frame') or 0),
            'preview_path': preview_path,
            'caption_finished_at': (d['caption_finished_at'].replace(' ', 'T') + 'Z') if d.get('caption_finished_at') else None,
            'rating': d.get('rating'),
            'blurhash': d.get('blurhash'),
            'collection_count': d.get('collection_count') or 0,
        })

    return jsonify({
        'scenes': scenes,
        'page': page,
        'has_more': offset + limit < total,
        'total': total,
    })


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
    row = conn.execute("SELECT id, caption FROM scenes WHERE id = ?", (scene_id,)).fetchone()
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
    row = conn.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404
    
    # Update caption
    conn.execute("UPDATE scenes SET caption = ? WHERE id = ?", (caption, scene_id))
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
               WHERE v.id = ?
               ORDER BY st.tag""",
            [int(video_filter)]
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT st.tag, COALESCE(td.description, '') as description, COALESCE(td.display_name, '') as display_name
               FROM (SELECT DISTINCT tag FROM scene_tags) st
               LEFT JOIN tag_definitions td ON td.tag = st.tag
               ORDER BY st.tag"""
        ).fetchall()
    conn.close()
    return jsonify({"tags": [{"tag": r["tag"], "description": r["description"], "display_name": r["display_name"]} for r in rows]})


@app.route('/api/tags/<int:scene_id>', methods=['GET'])
def get_tags(scene_id: int):
    """Get all tags for a scene."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = ? ORDER BY created_at, tag",
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
    if conn.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404

    conn.execute(
        "INSERT OR IGNORE INTO scene_tags (scene_id, tag) VALUES (?, ?)",
        (scene_id, tag)
    )
    conn.commit()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = ? ORDER BY created_at, tag",
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
        "SELECT COUNT(*) FROM scene_tags WHERE tag = ?", (old_tag,)
    ).fetchone()[0]
    # For scenes that already have new_tag, the INSERT is ignored (no duplicate)
    conn.execute(
        "INSERT OR IGNORE INTO scene_tags (scene_id, tag, created_at) "
        "SELECT scene_id, ?, created_at FROM scene_tags WHERE tag = ?",
        (new_tag, old_tag)
    )
    conn.execute("DELETE FROM scene_tags WHERE tag = ?", (old_tag,))
    # Migrate description to new tag name
    conn.execute(
        "INSERT INTO tag_definitions (tag, description, display_name) "
        "SELECT ?, description, display_name FROM tag_definitions WHERE tag = ? "
        "ON CONFLICT(tag) DO NOTHING",
        (new_tag, old_tag)
    )
    conn.execute("DELETE FROM tag_definitions WHERE tag = ?", (old_tag,))
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
        "INSERT INTO tag_definitions (tag, description, display_name) VALUES (?, ?, ?) "
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
        scene = conn.execute("SELECT video_id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
        if not scene:
            conn.close()
            return jsonify({"error": "Scene not found"}), 404
        
        video_id = scene["video_id"]
        tag_scores = {}
        
        existing_tags = [row["tag"] for row in conn.execute(
            "SELECT tag FROM scene_tags WHERE scene_id = ?", (scene_id,)
        ).fetchall()]
        
        scene_recent = conn.execute("""
            SELECT tag, created_at
            FROM scene_tags
            WHERE scene_id = ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (scene_id,)).fetchall()
        
        for row in scene_recent:
            tag = row["tag"]
            if tag not in tag_scores:
                tag_scores[tag] = {"score": 0.0, "sources": set()}
            tag_scores[tag]["score"] += 3.0
            tag_scores[tag]["sources"].add("scene_recent")
        
        video_co_occur = conn.execute("""
            SELECT st2.tag, COUNT(*) as co_occurrence
            FROM scene_tags st1
            JOIN scene_tags st2 ON st1.scene_id = st2.scene_id
            WHERE st1.scene_id = ?
              AND st2.tag != st1.tag
              AND st2.scene_id != ?
            GROUP BY st2.tag
            ORDER BY co_occurrence DESC
            LIMIT 20
        """, (scene_id, scene_id)).fetchall()
        
        for row in video_co_occur:
            tag = row["tag"]
            if tag not in tag_scores:
                tag_scores[tag] = {"score": 0.0, "sources": set()}
            tag_scores[tag]["score"] += 2.5 + (row["co_occurrence"] * 0.5)
            tag_scores[tag]["sources"].add("video_co_occur")
        
        global_popular = conn.execute("""
            SELECT tag, COUNT(*) as freq
            FROM scene_tags
            GROUP BY tag
            ORDER BY freq DESC
            LIMIT 50
        """).fetchall()
        
        for row in global_popular:
            tag = row["tag"]
            if tag not in tag_scores:
                tag_scores[tag] = {"score": 0.0, "sources": set()}
            tag_scores[tag]["score"] += 2.0 + (row["freq"] * 0.1)
            tag_scores[tag]["sources"].add("global_popular")
        
        global_recent = conn.execute("""
            SELECT tag, MAX(created_at) as last_used
            FROM scene_tags
            GROUP BY tag
            ORDER BY last_used DESC
            LIMIT 50
        """).fetchall()
        
        from datetime import datetime
        for row in global_recent:
            tag = row["tag"]
            if tag not in tag_scores:
                tag_scores[tag] = {"score": 0.0, "sources": set()}
            last_used_str = row["last_used"]
            if last_used_str:
                last_used = datetime.fromisoformat(last_used_str.replace('Z', '+00:00'))
                days_ago = (datetime.now() - last_used).total_seconds() / 86400
                weight = 1.5 - (days_ago * 0.01)
                tag_scores[tag]["score"] += max(0, weight)
            else:
                tag_scores[tag]["score"] += 1.5
            tag_scores[tag]["sources"].add("global_recent")
        
        tag_list = []
        for tag, data in tag_scores.items():
            desc_row = conn.execute(
                "SELECT description, display_name FROM tag_definitions WHERE tag = ?",
                (tag,)
            ).fetchone()
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
        "DELETE FROM scene_tags WHERE scene_id = ? AND tag = ?",
        (scene_id, tag)
    )
    conn.commit()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = ? ORDER BY created_at, tag",
        (scene_id,)
    ).fetchall()
    conn.close()
    return jsonify({"scene_id": scene_id, "tags": [r["tag"] for r in rows]})


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
    if conn.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404
    conn.execute("UPDATE scenes SET rating = ? WHERE id = ?", (rating, scene_id))
    conn.commit()
    conn.close()
    return jsonify({"scene_id": scene_id, "rating": rating})


@app.route('/api/videos', methods=['GET'])
def get_videos():
    """Return all videos with full metadata and scene/caption counts."""
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM videos ORDER BY path").fetchall()
    result = []
    for r in rows:
        v = dict(r)
        counts = conn.execute(
            """SELECT
                COUNT(*) as scene_count,
                SUM(CASE WHEN caption IS NOT NULL AND caption != '' AND substr(caption, 1, 2) != '__' THEN 1 ELSE 0 END) as captioned
               FROM scenes WHERE video_id = ?""",
            (v["id"],)
        ).fetchone()
        # Use custom name if set, otherwise fallback to filename
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
            "scene_count": counts["scene_count"] or 0,
            "captioned": counts["captioned"] or 0,
        })
    conn.close()
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
    conn.execute("UPDATE videos SET prompt = ? WHERE id = ?", (prompt, video_id))
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
    conn.execute("UPDATE videos SET name = ? WHERE id = ?", (name, video_id))
    conn.commit()
    conn.close()
    return jsonify({"video_id": video_id, "name": name or ""})



@app.route('/api/bucket/<int:scene_id>', methods=['PUT'])
def update_bucket(scene_id: int):
    """Update the bucket window offset and/or frame count."""
    data = request.get_json()
    if data is None or 'offset_frames' not in data:
        return jsonify({"error": "Missing offset_frames"}), 400

    offset_frames = int(data['offset_frames'])

    conn = get_db_connection()
    bucket = conn.execute("SELECT * FROM buckets WHERE scene_id = ?", (scene_id,)).fetchone()
    if not bucket:
        conn.close()
        return jsonify({"error": "Bucket not found"}), 404

    video = conn.execute("""
        SELECT v.fps, v.frame_offset FROM videos v
        JOIN scenes s ON s.video_id = v.id WHERE s.id = ?
    """, (scene_id,)).fetchone()
    scene = conn.execute("SELECT start_frame, end_frame, start_time, end_time FROM scenes WHERE id = ?", (scene_id,)).fetchone()
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
            frame_count = ?,
            optimal_offset_frames = ?,
            start_frame = ?,
            end_frame = ?,
            start_time = ?,
            end_time = ?,
            duration = ?,
            optimal_duration = ?,
            bucket_timestamp = CURRENT_TIMESTAMP
        WHERE scene_id = ?
    """, (frame_count, offset_frames, new_start_frame, new_end_frame,
          new_start_time, new_end_time, new_duration, new_duration, scene_id))
    conn.commit()
    saved = conn.execute("SELECT * FROM buckets WHERE scene_id = ?", (scene_id,)).fetchone()
    scene_fc = conn.execute("SELECT start_frame, end_frame FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    conn.close()

    result = dict(saved)
    result["scene_frame_count"] = scene_frame_count
    return jsonify({"bucket": result})


@app.route('/api/bucket/<int:scene_id>')
def get_bucket_data(scene_id: int):
    """Get bucket data for a scene."""
    conn = get_db_connection()

    bucket = conn.execute("SELECT * FROM buckets WHERE scene_id = ?", (scene_id,)).fetchone()
    if not bucket:
        conn.close()
        return jsonify({"bucket": None})

    result = dict(bucket)

    scene = conn.execute("SELECT start_frame, end_frame, start_time, end_time FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    fps = conn.execute("SELECT v.fps FROM videos v JOIN scenes s ON s.video_id = v.id WHERE s.id = ?", (scene_id,)).fetchone()
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
        SELECT * FROM buckets WHERE scene_id = ?
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
        WHERE b.scene_id = ?
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
        SELECT * FROM buckets WHERE scene_id = ?
    """, (scene_id,)).fetchone()
    
    if not bucket:
        conn.close()
        return jsonify({"error": "Bucket not found"}), 404
    
    # Get video info
    video_row = conn.execute("""
        SELECT v.path as video_path, v.fps, v.frame_offset
        FROM videos v
        JOIN buckets b ON b.video_id = v.id
        WHERE b.scene_id = ?
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


@app.route('/api/collections', methods=['GET'])
def get_collections():
    """List all collections with item count."""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT c.id, c.name, c.caption_prompt, c.created_at,
               COUNT(ci.id) as item_count
        FROM collections c
        LEFT JOIN collection_items ci ON ci.collection_id = c.id
        GROUP BY c.id
        ORDER BY c.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify({"collections": [dict(r) for r in rows]})


@app.route('/api/collections', methods=['POST'])
def create_collection():
    """Create a new collection."""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({"error": "Missing name"}), 400
    name = data['name'].strip()
    if not name:
        return jsonify({"error": "Empty name"}), 400
    conn = get_db_connection()
    cur = conn.execute("INSERT INTO collections (name) VALUES (?)", (name,))
    conn.commit()
    row = conn.execute("SELECT * FROM collections WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify({"collection": dict(row)}), 201


@app.route('/api/collections/<int:collection_id>', methods=['PUT'])
def update_collection(collection_id: int):
    """Update a collection's name and/or caption_prompt."""
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
    if conn.execute("SELECT id FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404
    if has_name:
        conn.execute("UPDATE collections SET name = ? WHERE id = ?", (name, collection_id))
    if has_prompt:
        prompt_val = data['caption_prompt'].strip() if data['caption_prompt'] else None
        conn.execute("UPDATE collections SET caption_prompt = ? WHERE id = ?", (prompt_val, collection_id))
    conn.commit()
    row = conn.execute("SELECT c.id, c.name, c.caption_prompt, c.created_at FROM collections c WHERE c.id = ?", (collection_id,)).fetchone()
    conn.close()
    return jsonify({"collection": dict(row)})


@app.route('/api/collections/<int:collection_id>', methods=['DELETE'])
def delete_collection(collection_id: int):
    """Delete a collection and all its items."""
    conn = get_db_connection()
    if conn.execute("SELECT id FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404
    conn.execute("DELETE FROM collection_items WHERE collection_id = ?", (collection_id,))
    conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/api/collections/<int:collection_id>/export', methods=['POST'])
def export_collection(collection_id: int):
    """Extract all collection items as MP4 clips + caption .txt files, return as a zip."""
    import zipfile
    import tempfile

    conn = get_db_connection()
    coll = conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
    if not coll:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404

    rows = conn.execute("""
        SELECT ci.id, ci.scene_id, ci.video_id, ci.start_frame, ci.end_frame,
               v.path as video_path, v.fps, v.frame_offset,
               s.caption
        FROM collection_items ci
        JOIN videos v ON ci.video_id = v.id
        JOIN scenes s ON ci.scene_id = s.id
        WHERE ci.collection_id = ?
        ORDER BY ci.created_at ASC
    """, (collection_id,)).fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "Collection is empty"}), 400

    collection_slug = re.sub(r'[^\w\-]', '_', coll['name']).strip('_')

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        zip_buf = io.BytesIO()

        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, row in enumerate(rows):
                item = dict(row)
                fps = item['fps'] or 24.0
                frame_offset = item['frame_offset'] or 0
                video_file = Path(item['video_path'])

                if not video_file.exists():
                    continue

                stem = f"{i + 1:04d}_scene{item['scene_id']}"
                mp4_name = f"{stem}.mp4"
                txt_name = f"{stem}.txt"
                mp4_path = tmpdir_path / mp4_name

                start_time = max(0.0, (item['start_frame'] + frame_offset + 1) / fps)
                duration   = (item['end_frame'] - item['start_frame']) / fps

                if duration <= 0:
                    continue

                cmd = [
                    'ffmpeg', '-y',
                    '-ss', f'{start_time:.6f}',
                    '-i', str(video_file),
                    '-t', f'{duration:.6f}',
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-crf', '18',
                    '-pix_fmt', 'yuv420p',
                    '-ac', '2',
                    '-c:a', 'aac',
                    '-movflags', '+faststart',
                    '-f', 'mp4',
                    str(mp4_path),
                ]
                result = subprocess.run(cmd, stderr=subprocess.DEVNULL)
                if result.returncode == 0 and mp4_path.exists():
                    zf.write(mp4_path, mp4_name)

                caption = (item.get('caption') or '').strip()
                if caption and not caption.startswith('__'):
                    zf.writestr(txt_name, caption)

        zip_data = zip_buf.getvalue()

    zip_io = io.BytesIO(zip_data)
    return send_file(
        zip_io,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{collection_slug}.zip',
    )


@app.route('/api/collections/<int:collection_id>/items', methods=['GET'])
def get_collection_items(collection_id: int):
    """Get all items in a collection with scene/video metadata."""
    conn = get_db_connection()
    if conn.execute("SELECT id FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404
    rows = conn.execute("""
        SELECT ci.id, ci.scene_id, ci.video_id, ci.start_frame, ci.end_frame, ci.created_at,
               ci.caption as item_caption,
               v.path as video_path, v.fps, v.frame_offset,
               COALESCE(v.name, '') as video_name_custom,
               s.caption as scene_caption, s.start_time, s.end_time, s.rating, s.blurhash,
               s.start_frame as scene_start_frame, s.end_frame as scene_end_frame,
               GROUP_CONCAT(st.tag, '|') as tags_concat
        FROM collection_items ci
        JOIN videos v ON ci.video_id = v.id
        JOIN scenes s ON ci.scene_id = s.id
        LEFT JOIN scene_tags st ON st.scene_id = s.id
        WHERE ci.collection_id = ?
        GROUP BY ci.id
        ORDER BY ci.created_at ASC
    """, (collection_id,)).fetchall()
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
            'caption': d.get('item_caption') or '',
            'tags': [tag for tag in tags_raw.split('|') if tag],
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


@app.route('/api/collections/<int:collection_id>/items', methods=['POST'])
def add_collection_item(collection_id: int):
    """Add a scene's bucket to a collection."""
    data = request.get_json()
    if not data or 'scene_id' not in data:
        return jsonify({"error": "Missing scene_id"}), 400
    scene_id = int(data['scene_id'])

    conn = get_db_connection()
    if conn.execute("SELECT id FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Collection not found"}), 404

    bucket = conn.execute("SELECT * FROM buckets WHERE scene_id = ?", (scene_id,)).fetchone()
    if not bucket:
        conn.close()
        return jsonify({"error": "No bucket found for this scene."}), 400

    scene = conn.execute("SELECT video_id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if not scene:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404

    video_id = scene['video_id']
    start_frame = bucket['start_frame']
    end_frame = bucket['end_frame']

    try:
        cur = conn.execute("""
            INSERT INTO collection_items (collection_id, scene_id, video_id, start_frame, end_frame)
            VALUES (?, ?, ?, ?, ?)
        """, (collection_id, scene_id, video_id, start_frame, end_frame))
        conn.commit()
        item_id = cur.lastrowid
        conn.close()
        return jsonify({
            "item_id": item_id, "collection_id": collection_id,
            "scene_id": scene_id, "video_id": video_id,
            "start_frame": start_frame, "end_frame": end_frame,
        }), 201
    except sqlite3.IntegrityError:
        existing = conn.execute(
            "SELECT id FROM collection_items WHERE collection_id = ? AND scene_id = ?",
            (collection_id, scene_id)
        ).fetchone()
        conn.close()
        return jsonify({"item_id": existing['id'] if existing else None, "already_exists": True}), 200


@app.route('/api/collections/<int:collection_id>/items/<int:item_id>', methods=['PUT'])
def update_collection_item(collection_id: int, item_id: int):
    """Update the start_frame and end_frame of a collection item."""
    data = request.get_json()
    if data is None or 'start_frame' not in data or 'end_frame' not in data:
        return jsonify({"error": "Missing start_frame or end_frame"}), 400
    start_frame = int(data['start_frame'])
    end_frame = int(data['end_frame'])
    if end_frame <= start_frame:
        return jsonify({"error": "end_frame must be greater than start_frame"}), 400
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id FROM collection_items WHERE id = ? AND collection_id = ?",
        (item_id, collection_id)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Item not found"}), 404
    conn.execute(
        "UPDATE collection_items SET start_frame = ?, end_frame = ? WHERE id = ?",
        (start_frame, end_frame, item_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"item_id": item_id, "start_frame": start_frame, "end_frame": end_frame,
                    "frame_count": end_frame - start_frame})


@app.route('/api/collections/<int:collection_id>/items/<int:item_id>/caption', methods=['PUT'])
def update_collection_item_caption(collection_id: int, item_id: int):
    """Update the caption of a collection item (independent of the scene caption)."""
    data = request.get_json()
    if data is None or 'caption' not in data:
        return jsonify({"error": "Missing caption"}), 400
    caption = data['caption']
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id FROM collection_items WHERE id = ? AND collection_id = ?",
        (item_id, collection_id)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Item not found"}), 404
    conn.execute("UPDATE collection_items SET caption = ? WHERE id = ?", (caption, item_id))
    conn.commit()
    conn.close()
    return jsonify({"item_id": item_id, "caption": caption})


@app.route('/api/collections/<int:collection_id>/items/<int:item_id>', methods=['DELETE'])
def remove_collection_item(collection_id: int, item_id: int):
    """Remove an item from a collection."""
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM collection_items WHERE id = ? AND collection_id = ?",
        (item_id, collection_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


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
    print(f"Database: {DB_PATH}")
    print(f"Previews: {DEBUG_SCENES_DIR}")
    print(f"URL: http://{args.host}:{args.port}")
    print(f"{'='*50}\n")
    
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
