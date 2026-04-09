"""
I/O utilities for the dataset builder — PostgreSQL backend.
"""

import json
import psycopg2
import psycopg2.extras
import psycopg2.errors
from pathlib import Path
from typing import Dict, Any, List, Optional, Iterator, Union
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class _PgConn:
    """Thin wrapper that gives psycopg2 connections the same interface as sqlite3:
    conn.execute(sql, params), conn.commit(), conn.close().
    All cursors use RealDictCursor so rows are dict-like."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params if params else None)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


class Database:
    """PostgreSQL database for caching and indexing."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._init_tables()

    def _init_tables(self) -> None:
        with self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id SERIAL PRIMARY KEY,
                    path TEXT UNIQUE NOT NULL,
                    hash TEXT NOT NULL,
                    duration DOUBLE PRECISION,
                    fps DOUBLE PRECISION,
                    width INTEGER,
                    height INTEGER,
                    codec TEXT,
                    frame_offset INTEGER DEFAULT 0,
                    prompt TEXT,
                    name TEXT,
                    indexed_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scenes (
                    id SERIAL PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    start_time DOUBLE PRECISION NOT NULL,
                    end_time DOUBLE PRECISION NOT NULL,
                    duration DOUBLE PRECISION NOT NULL,
                    start_frame INTEGER,
                    end_frame INTEGER,
                    caption TEXT,
                    caption_started_at TIMESTAMPTZ,
                    caption_finished_at TIMESTAMPTZ,
                    caption_prompt TEXT,
                    blurhash TEXT,
                    rating INTEGER DEFAULT 2,
                    bucket_ineligible INTEGER DEFAULT 0,
                    UNIQUE(video_id, start_time, end_time)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS buckets (
                    id SERIAL PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    scene_id INTEGER REFERENCES scenes(id),
                    start_time DOUBLE PRECISION NOT NULL,
                    end_time DOUBLE PRECISION NOT NULL,
                    duration DOUBLE PRECISION NOT NULL,
                    start_frame INTEGER NOT NULL,
                    end_frame INTEGER NOT NULL,
                    frame_count INTEGER,
                    speech_score DOUBLE PRECISION,
                    speech_start_frame INTEGER,
                    speech_end_frame INTEGER,
                    optimal_offset_frames INTEGER,
                    optimal_duration DOUBLE PRECISION,
                    bucket_timestamp TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(video_id, start_frame, end_frame)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candidates (
                    id SERIAL PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    scene_id INTEGER REFERENCES scenes(id),
                    start_time DOUBLE PRECISION NOT NULL,
                    end_time DOUBLE PRECISION NOT NULL,
                    duration DOUBLE PRECISION NOT NULL,
                    quality_score DOUBLE PRECISION,
                    face_presence DOUBLE PRECISION,
                    status TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS face_detections (
                    id SERIAL PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    frame_time DOUBLE PRECISION NOT NULL,
                    bbox_x DOUBLE PRECISION,
                    bbox_y DOUBLE PRECISION,
                    bbox_w DOUBLE PRECISION,
                    bbox_h DOUBLE PRECISION,
                    confidence DOUBLE PRECISION,
                    embedding BYTEA,
                    UNIQUE(video_id, frame_time)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id SERIAL PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id),
                    frame_time DOUBLE PRECISION NOT NULL,
                    embedding BYTEA NOT NULL,
                    cluster_id INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS samples (
                    id SERIAL PRIMARY KEY,
                    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                    crop_type TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    frame_count INTEGER,
                    caption TEXT,
                    rendered_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scene_tags (
                    scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
                    tag TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (scene_id, tag)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tag_definitions (
                    tag TEXT PRIMARY KEY,
                    description TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    caption_prompt TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clip_items (
                    id SERIAL PRIMARY KEY,
                    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                    scene_id INTEGER NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
                    video_id INTEGER NOT NULL,
                    start_frame INTEGER NOT NULL,
                    end_frame INTEGER NOT NULL,
                    caption TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(clip_id, scene_id)
                )
            """)
            conn.commit()

    @contextmanager
    def _connection(self):
        conn = psycopg2.connect(self._dsn)
        wrapper = _PgConn(conn)
        try:
            yield wrapper
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Video operations ──────────────────────────────────────────────────────

    def add_video(self, path: str, hash: str, metadata: Dict[str, Any]) -> int:
        with self._connection() as conn:
            cur = conn.execute("""
                INSERT INTO videos (path, hash, duration, fps, width, height, codec)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (path) DO UPDATE SET hash = EXCLUDED.hash
                RETURNING id
            """, (
                path, hash,
                metadata.get("duration"),
                metadata.get("fps"),
                metadata.get("width"),
                metadata.get("height"),
                metadata.get("codec"),
            ))
            conn.commit()
            return cur.fetchone()['id']

    def get_video(self, path: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE path = %s", (path,)
            ).fetchone()
            return dict(row) if row else None

    def get_video_by_id(self, video_id: int) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE id = %s", (video_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_videos(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM videos").fetchall()
            return [dict(r) for r in rows]

    def get_frame_offset(self, video_id: int) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT frame_offset FROM videos WHERE id = %s", (video_id,)
            ).fetchone()
            return row["frame_offset"] if row and row["frame_offset"] else 0

    def set_frame_offset(self, video_id: int, offset: int) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE videos SET frame_offset = %s WHERE id = %s", (offset, video_id)
            )
            conn.commit()

    def get_video_name(self, video_id: int) -> Optional[str]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name FROM videos WHERE id = %s", (video_id,)
            ).fetchone()
            return row["name"] if row and row["name"] else None

    def set_video_name(self, video_id: int, name: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE videos SET name = %s WHERE id = %s", (name, video_id)
            )
            conn.commit()

    # ── Scene operations ──────────────────────────────────────────────────────

    def add_scenes(self, video_id: int, scenes: List[Dict[str, Any]]) -> List[int]:
        ids = []
        with self._connection() as conn:
            for scene in scenes:
                start_frame = scene.get("start_frame")
                end_frame = scene.get("end_frame")
                frame_count = (
                    (end_frame - start_frame)
                    if (start_frame is not None and end_frame is not None)
                    else None
                )
                default_rating = 1 if (frame_count is not None and frame_count < 24) else 2
                conn.execute("""
                    INSERT INTO scenes
                        (video_id, start_time, end_time, duration, start_frame, end_frame, rating)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (video_id, start_time, end_time) DO NOTHING
                """, (
                    video_id, scene["start_time"], scene["end_time"], scene["duration"],
                    start_frame, end_frame, default_rating,
                ))
                row = conn.execute(
                    "SELECT id FROM scenes WHERE video_id = %s AND start_time = %s AND end_time = %s",
                    (video_id, scene["start_time"], scene["end_time"]),
                ).fetchone()
                if row:
                    scene_id = row["id"]
                    ids.append(scene_id)
                    if start_frame is not None and end_frame is not None:
                        conn.execute("""
                            INSERT INTO buckets
                                (video_id, scene_id, start_time, end_time, duration,
                                 start_frame, end_frame, frame_count,
                                 optimal_offset_frames, optimal_duration)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
                            ON CONFLICT (video_id, start_frame, end_frame) DO NOTHING
                        """, (
                            video_id, scene_id,
                            scene["start_time"], scene["end_time"], scene["duration"],
                            start_frame, end_frame, frame_count, scene["duration"],
                        ))
            conn.commit()
        return ids

    def backfill_default_buckets(self) -> int:
        with self._connection() as conn:
            scenes = conn.execute("""
                SELECT s.id, s.video_id, s.start_time, s.end_time, s.duration,
                       s.start_frame, s.end_frame
                FROM scenes s
                LEFT JOIN buckets b ON b.scene_id = s.id
                WHERE b.id IS NULL
                  AND s.start_frame IS NOT NULL
                  AND s.end_frame IS NOT NULL
            """).fetchall()
            count = 0
            for s in scenes:
                frame_count = s["end_frame"] - s["start_frame"]
                conn.execute("""
                    INSERT INTO buckets
                        (video_id, scene_id, start_time, end_time, duration,
                         start_frame, end_frame, frame_count,
                         optimal_offset_frames, optimal_duration)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
                    ON CONFLICT (video_id, start_frame, end_frame) DO NOTHING
                """, (
                    s["video_id"], s["id"],
                    s["start_time"], s["end_time"], s["duration"],
                    s["start_frame"], s["end_frame"], frame_count, s["duration"],
                ))
                count += 1
            conn.commit()
            logger.info(f"Backfilled {count} default bucket(s)")
            return count

    def get_scenes(self, video_id: int) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM scenes WHERE video_id = %s ORDER BY start_time",
                (video_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_scenes_for_buckets(self, video_id: int) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT s.* FROM scenes s
                LEFT JOIN buckets b ON b.scene_id = s.id
                WHERE s.video_id = %s
                  AND (s.bucket_ineligible IS NULL OR s.bucket_ineligible = 0)
                  AND b.id IS NULL
                ORDER BY s.start_time
            """, (video_id,)).fetchall()
            return [dict(r) for r in rows]

    def mark_scene_bucket_ineligible(self, scene_id: int) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE scenes SET bucket_ineligible = 1 WHERE id = %s", (scene_id,)
            )
            conn.commit()

    def get_scenes_without_caption(self, video_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            if video_id:
                rows = conn.execute(
                    "SELECT * FROM scenes WHERE video_id = %s AND (caption IS NULL OR caption = '') ORDER BY start_time",
                    (video_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scenes WHERE caption IS NULL OR caption = '' ORDER BY video_id, start_time"
                ).fetchall()
            return [dict(r) for r in rows]

    def update_scene_caption(
        self,
        scene_id: int,
        caption: str,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                UPDATE scenes
                SET caption = %s,
                    caption_started_at = COALESCE(%s, caption_started_at),
                    caption_finished_at = COALESCE(%s, caption_finished_at),
                    caption_prompt = COALESCE(%s, caption_prompt)
                WHERE id = %s
            """, (caption, started_at, finished_at, prompt, scene_id))
            conn.commit()

    def update_clip_item_caption(self, item_id: int, caption: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE clip_items SET caption = %s WHERE id = %s", (caption, item_id)
            )
            conn.commit()

    # ── Candidate operations ──────────────────────────────────────────────────

    def add_candidate(
        self,
        video_id: int,
        scene_id: Optional[int],
        start_time: float,
        end_time: float,
    ) -> int:
        with self._connection() as conn:
            cur = conn.execute("""
                INSERT INTO candidates (video_id, scene_id, start_time, end_time, duration)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (video_id, scene_id, start_time, end_time, end_time - start_time))
            conn.commit()
            return cur.fetchone()['id']

    def update_candidate(
        self,
        candidate_id: int,
        quality_score: Optional[float] = None,
        face_presence: Optional[float] = None,
        status: Optional[str] = None,
    ) -> None:
        updates = []
        params: list = []
        if quality_score is not None:
            updates.append("quality_score = %s")
            params.append(quality_score)
        if face_presence is not None:
            updates.append("face_presence = %s")
            params.append(face_presence)
        if status is not None:
            updates.append("status = %s")
            params.append(status)
        if updates:
            params.append(candidate_id)
            with self._connection() as conn:
                conn.execute(
                    f"UPDATE candidates SET {', '.join(updates)} WHERE id = %s", params
                )
                conn.commit()

    def get_candidates(
        self,
        video_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM candidates WHERE 1=1"
        params: list = []
        if video_id is not None:
            query += " AND video_id = %s"
            params.append(video_id)
        if status is not None:
            query += " AND status = %s"
            params.append(status)
        query += " ORDER BY video_id, start_time"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ── Face detection cache ──────────────────────────────────────────────────

    def add_face_detection(
        self,
        video_id: int,
        frame_time: float,
        bbox: Optional[tuple] = None,
        confidence: Optional[float] = None,
        embedding: Optional[bytes] = None,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO face_detections
                    (video_id, frame_time, bbox_x, bbox_y, bbox_w, bbox_h, confidence, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (video_id, frame_time) DO UPDATE SET
                    bbox_x = EXCLUDED.bbox_x, bbox_y = EXCLUDED.bbox_y,
                    bbox_w = EXCLUDED.bbox_w, bbox_h = EXCLUDED.bbox_h,
                    confidence = EXCLUDED.confidence, embedding = EXCLUDED.embedding
            """, (
                video_id, frame_time,
                bbox[0] if bbox else None,
                bbox[1] if bbox else None,
                bbox[2] if bbox else None,
                bbox[3] if bbox else None,
                confidence,
                embedding,
            ))
            conn.commit()

    def get_face_detections(
        self,
        video_id: int,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM face_detections WHERE video_id = %s"
        params: list = [video_id]
        if start_time is not None:
            query += " AND frame_time >= %s"
            params.append(start_time)
        if end_time is not None:
            query += " AND frame_time <= %s"
            params.append(end_time)
        query += " ORDER BY frame_time"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ── Sample operations ─────────────────────────────────────────────────────

    def add_sample(
        self,
        candidate_id: int,
        crop_type: str,
        output_path: str,
        frame_count: int,
        caption: str,
    ) -> int:
        with self._connection() as conn:
            cur = conn.execute("""
                INSERT INTO samples (candidate_id, crop_type, output_path, frame_count, caption)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (candidate_id, crop_type, output_path, frame_count, caption))
            conn.commit()
            return cur.fetchone()['id']

    def get_samples(self, candidate_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if candidate_id:
            query, params = "SELECT * FROM samples WHERE candidate_id = %s", [candidate_id]
        else:
            query, params = "SELECT * FROM samples", []
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ── Bucket operations ─────────────────────────────────────────────────────

    def add_buckets(self, video_id: int, buckets: List[Dict[str, Any]]) -> List[int]:
        ids = []
        with self._connection() as conn:
            for bucket in buckets:
                try:
                    conn.execute("""
                        INSERT INTO buckets
                            (video_id, scene_id, start_time, end_time, duration,
                             start_frame, end_frame, frame_count, speech_score,
                             speech_start_frame, speech_end_frame,
                             optimal_offset_frames, optimal_duration)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (video_id, start_frame, end_frame) DO NOTHING
                    """, (
                        video_id,
                        bucket.get("scene_id"),
                        bucket["start_time"], bucket["end_time"], bucket["duration"],
                        bucket["start_frame"], bucket["end_frame"],
                        bucket.get("frame_count"),
                        bucket.get("speech_score"),
                        bucket.get("speech_start_frame"),
                        bucket.get("speech_end_frame"),
                        bucket.get("optimal_offset_frames"),
                        bucket.get("optimal_duration"),
                    ))
                    conn.commit()
                    row = conn.execute(
                        "SELECT id FROM buckets WHERE video_id = %s AND start_frame = %s AND end_frame = %s",
                        (video_id, bucket["start_frame"], bucket["end_frame"])
                    ).fetchone()
                    if row:
                        ids.append(row["id"])
                except Exception as e:
                    logger.error(f"Failed to add bucket: {e}")
                    continue
        return ids

    def get_buckets(
        self,
        video_id: Optional[int] = None,
        scene_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM buckets WHERE 1=1"
        params: list = []
        if video_id is not None:
            query += " AND video_id = %s"
            params.append(video_id)
        if scene_id is not None:
            query += " AND scene_id = %s"
            params.append(scene_id)
        query += " ORDER BY video_id, start_time"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_buckets_without_rendering(
        self, video_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return self.get_buckets(video_id=video_id)


def write_jsonl(path: Path, entries: Iterator[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, 'w') as f:
        for entry in entries:
            f.write(json.dumps(entry) + '\n')
            count += 1
    logger.info(f"Wrote {count} entries to {path}")
    return count


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
