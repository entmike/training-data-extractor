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

app = Flask(__name__)

UI_DIST = Path(__file__).parent / 'ui' / 'dist'

# Load config
CONFIG_PATH = Path("config.yaml")
if CONFIG_PATH.exists():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
else:
    config = {
        "db_path": ".cache/index.db",
        "output_dir": "./dataset"
    }

DB_PATH = Path(config.get("db_path", ".cache/index.db"))
OUTPUT_DIR = Path(config.get("output_dir", "./dataset"))
DEBUG_SCENES_DIR = OUTPUT_DIR / "debug" / "scenes"
WAVEFORMS_DIR = Path(".cache/waveforms")


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


def generate_scene_preview(
    video_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float = 24.0,
    frame_offset: int = 0,
    frame_width: int = 426
) -> Optional[bytes]:
    """
    Generate a 3-frame preview image (start, middle, end) for a scene.
    
    This is reusable preview generation logic that can be called from:
    - Web server for on-the-fly preview generation
    - CLI for batch preview generation
    
    Args:
        video_path: Path to video file
        start_frame: First frame of scene (inclusive)
        end_frame: Last frame of scene (exclusive - first frame of next scene)
        fps: Video frame rate
        frame_offset: Frame offset compensation
        frame_width: Width of each frame in the composite
        
    Returns:
        PNG image bytes or None on failure
    """
    if not HAS_OPENCV or not HAS_PIL:
        return None
    
    if not video_path.exists():
        return None
    
    # Apply frame offset
    start_frame = max(0, start_frame + frame_offset)
    end_frame = end_frame + frame_offset
    
    # Calculate the three frames to extract
    first_frame = start_frame + 1
    last_frame = max(start_frame, end_frame - 1)
    middle_frame = first_frame + (last_frame - first_frame) // 2
    
    frames_to_get = [first_frame, middle_frame, last_frame]
    extracted_frames = []
    
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    
    try:
        for frame_num in frames_to_get:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            
            if ret:
                # Resize to target width
                h, w = frame.shape[:2]
                new_w = frame_width
                new_h = int(h * new_w / w)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                extracted_frames.append(Image.fromarray(frame))
            else:
                extracted_frames.append(None)
    finally:
        cap.release()
    
    if None in extracted_frames or len(extracted_frames) != 3:
        return None
    
    # Resize all frames to same height
    target_height = min(f.height for f in extracted_frames)
    resized_frames = []
    for f in extracted_frames:
        if f.height != target_height:
            ratio = target_height / f.height
            new_size = (int(f.width * ratio), target_height)
            f = f.resize(new_size, Image.LANCZOS)
        resized_frames.append(f)
    
    # Combine horizontally
    total_width = sum(f.width for f in resized_frames)
    combined = Image.new('RGB', (total_width, target_height))
    
    x_offset = 0
    for f in resized_frames:
        combined.paste(f, (x_offset, 0))
        x_offset += f.width
    
    # Convert to PNG bytes
    buffer = io.BytesIO()
    combined.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer.getvalue()


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
    
    # Generate preview
    preview_bytes = generate_scene_preview(
        video_path=video_path,
        start_frame=start_frame,
        end_frame=end_frame,
        fps=fps,
        frame_offset=frame_offset,
        frame_width=426
    )
    
    if preview_bytes is None:
        return jsonify({"error": "Failed to generate preview"}), 500
    
    return Response(
        preview_bytes,
        mimetype='image/png',
        headers={'Cache-Control': 'max-age=3600'}  # Cache for 1 hour
    )


@app.route('/clip/<int:scene_id>')
def serve_clip(scene_id: int):
    """Extract and serve a video clip using ffmpeg, with frame_offset applied as time_offset."""
    import subprocess

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

    # Single accurate seek: -ss before -i for speed, -to for precise end
    cmd = [
        'ffmpeg',
        '-ss', f'{start_time:.6f}',
        '-i', str(video_file),
        '-t', f'{duration:.6f}',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '23',
        '-c:a', 'aac',
        '-movflags', 'frag_keyframe+empty_moov+faststart',
        '-f', 'mp4',
        '-y',
        'pipe:1'
    ]
    
    def generate():
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=8192
        )
        try:
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                yield chunk
        finally:
            process.stdout.close()
            process.wait()
    
    return Response(
        generate(),
        mimetype='video/mp4',
        headers={
            'Content-Type': 'video/mp4',
            'Cache-Control': 'no-cache'
        }
    )


def _generate_rms_waveform_png(video_file: Path, start_time: float, duration: float,
                               width: int = 800, height: int = 80) -> Optional[bytes]:
    """
    Extract per-window RMS levels via FFmpeg astats, render as a bar chart PNG.
    Returns PNG bytes, or None on failure.
    """
    if not HAS_PIL:
        return None

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

    from PIL import ImageDraw
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
    cache_path = WAVEFORMS_DIR / f"{scene_id}.png"

    if cache_path.exists():
        return send_file(cache_path, mimetype='image/png', max_age=86400)

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
    limit = 50

    conn = get_db_connection()

    conditions = []
    params = []

    if filter_type in ('captioned', 'recent'):
        conditions.append("s.caption IS NOT NULL AND s.caption != '' AND substr(s.caption, 1, 2) != '__'")
    elif filter_type == 'uncaptioned':
        conditions.append("(s.caption IS NULL OR s.caption = '' OR substr(s.caption, 1, 2) = '__')")

    if video_filter:
        conditions.append("(v.path LIKE ? OR v.path LIKE ?)")
        params.extend([f'%/{video_filter}.%', f'{video_filter}.%'])

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM scenes s JOIN videos v ON s.video_id = v.id {where_clause}",
        params
    ).fetchone()[0]

    offset = (page - 1) * limit
    rows = conn.execute(f"""
        SELECT s.*, v.path as video_path, v.fps, v.frame_offset,
            (SELECT COUNT(*) FROM scenes s2 WHERE s2.video_id = s.video_id AND s2.id < s.id) as scene_idx,
            GROUP_CONCAT(st.tag, '|') as tags_concat
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        LEFT JOIN scene_tags st ON st.scene_id = s.id
        {where_clause}
        GROUP BY s.id
        ORDER BY {("s.caption_finished_at DESC NULLS LAST, s.id DESC" if filter_type == "recent" else "s.video_id, s.id")}
        LIMIT {limit} OFFSET {offset}
    """, params).fetchall()
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
               WHERE (v.path LIKE ? OR v.path LIKE ?)
               ORDER BY st.tag""",
            [f'%/{video_filter}.%', f'{video_filter}.%']
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
        result.append({
            "id": v["id"],
            "name": Path(v["path"]).name,
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
