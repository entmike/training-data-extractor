"""
Extract text-based subtitles from video files and store per-scene in the DB.

Supports: subrip (SRT), ass/ssa — ffmpeg converts both to SRT internally.
Image-based formats (hdmv_pgs_subtitle, dvd_subtitle) are skipped.
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import PipelineConfig
from ..utils.io import Database

logger = logging.getLogger(__name__)

TEXT_SUBTITLE_CODECS = {'subrip', 'ass', 'ssa', 'webvtt', 'mov_text'}

# Strip HTML-like tags ffmpeg leaves in SRT output (<i>, <b>, etc.)
_TAG_RE = re.compile(r'<[^>]+>')

# SRT timestamp: 00:00:01,000
_TS_RE = re.compile(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})')


def _ts_to_seconds(ts: str) -> float:
    m = _TS_RE.match(ts)
    if not m:
        return 0.0
    h, mn, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return h * 3600 + mn * 60 + s + ms / 1000.0


def _detect_subtitle_stream(video_path: Path) -> Optional[int]:
    """Return the stream index of the first English text subtitle track, or None."""
    import json
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json',
         '-show_streams', '-select_streams', 's', str(video_path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        return None
    streams = json.loads(result.stdout).get('streams', [])
    # Prefer English text track; fall back to first text track
    best = None
    for s in streams:
        if s.get('codec_name', '') not in TEXT_SUBTITLE_CODECS:
            continue
        lang = s.get('tags', {}).get('language', '')
        if lang == 'eng':
            return s['index']
        if best is None:
            best = s['index']
    return best


def _extract_srt(video_path: Path, stream_index: int) -> List[Tuple[float, float, str]]:
    """
    Extract subtitle track as SRT via ffmpeg and parse into
    (start_sec, end_sec, text) tuples.
    """
    result = subprocess.run(
        [
            'ffmpeg', '-i', str(video_path),
            '-map', f'0:{stream_index}',
            '-f', 'srt', '-',
        ],
        capture_output=True, text=True, timeout=120,
    )
    entries = []
    # Split on blank lines to get SRT blocks
    for block in re.split(r'\n\s*\n', result.stdout.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        # Find the timestamp line (contains -->)
        ts_line = next((l for l in lines if '-->' in l), None)
        if not ts_line:
            continue
        parts = ts_line.split('-->')
        if len(parts) != 2:
            continue
        start = _ts_to_seconds(parts[0].strip())
        end   = _ts_to_seconds(parts[1].strip())
        # Text is everything after the timestamp line
        ts_idx = lines.index(ts_line)
        raw_text = ' '.join(lines[ts_idx + 1:]).strip()
        text = _TAG_RE.sub('', raw_text).strip()
        if text:
            entries.append((start, end, text))
    return entries


def extract_subtitles_for_video(
    config: PipelineConfig,
    video: dict,
    db: Database,
    skip_existing: bool = True,
) -> int:
    """
    Extract subtitles for all scenes in one video.
    Returns the number of scenes updated.
    """
    video_path = Path(video['path'])
    video_id   = video['id']

    stream_idx = _detect_subtitle_stream(video_path)
    if stream_idx is None:
        logger.info(f"{video_path.name}: no text subtitle track — skipping")
        return 0

    logger.info(f"{video_path.name}: extracting subtitle stream {stream_idx}")
    entries = _extract_srt(video_path, stream_idx)
    if not entries:
        logger.warning(f"{video_path.name}: subtitle extraction returned no entries")
        return 0
    logger.info(f"{video_path.name}: {len(entries)} subtitle entries parsed")

    with db._connection() as conn:
        scenes = conn.execute(
            "SELECT id, start_time, end_time FROM scenes WHERE video_id = %s ORDER BY start_time",
            (video_id,)
        ).fetchall()

        updated = 0
        for scene in scenes:
            if skip_existing:
                existing = conn.execute(
                    "SELECT subtitles FROM scenes WHERE id = %s", (scene['id'],)
                ).fetchone()
                if existing and existing['subtitles']:
                    continue

            s_start = scene['start_time']
            s_end   = scene['end_time']

            # Collect subtitle lines whose time range overlaps the scene
            lines = []
            for (e_start, e_end, text) in entries:
                if e_end >= s_start and e_start <= s_end:
                    lines.append(text)

            subtitle_text = ' / '.join(lines) if lines else None

            conn.execute(
                "UPDATE scenes SET subtitles = %s WHERE id = %s",
                (subtitle_text, scene['id']),
            )
            updated += 1

        conn.commit()

    logger.info(f"{video_path.name}: subtitles written for {updated} scene(s)")
    return updated


def extract_all_subtitles(config: PipelineConfig) -> None:
    """Extract subtitles for all indexed videos that have text subtitle tracks."""
    db = Database(config.dsn)
    videos = db.get_all_videos()
    total = 0
    for video in videos:
        total += extract_subtitles_for_video(config, video, db,
                                             skip_existing=config.skip_existing)
    logger.info(f"Subtitle extraction complete — {total} scene(s) updated across {len(videos)} video(s)")
