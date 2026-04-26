"""
I/O utilities for the dataset builder — PostgreSQL backend.
"""

import json
import numpy as np
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
        # schema/schema.sql is the single source of truth for all table definitions.
        # Each statement is a complete CREATE TABLE IF NOT EXISTS with all current columns.
        schema_path = Path(__file__).parents[2] / 'schema' / 'schema.sql'
        schema_sql = schema_path.read_text()
        import re
        clean_sql = re.sub(r'--[^\n]*', '', schema_sql)   # strip line comments
        statements = [s.strip() for s in clean_sql.split(';') if s.strip()]

        # Incremental ADD COLUMN IF NOT EXISTS guards for columns added after each
        # table's initial deployment.  Safe to re-run; ignored on fresh installs
        # because the CREATE TABLE above already includes these columns.
        migrations = [
            "ALTER TABLE face_detections  ADD COLUMN IF NOT EXISTS embedding      BYTEA",
            "ALTER TABLE tag_references   ADD COLUMN IF NOT EXISTS embedding_type TEXT NOT NULL DEFAULT 'insightface'",
            "ALTER TABLE tag_references   ADD COLUMN IF NOT EXISTS frame_number   INTEGER",
            "ALTER TABLE scene_tags       ADD COLUMN IF NOT EXISTS confirmed      BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE scenes           ADD COLUMN IF NOT EXISTS subtitles      TEXT",
            "ALTER TABLE face_clusters    ADD COLUMN IF NOT EXISTS member_detection_ids INTEGER[] NOT NULL DEFAULT '{}'",
            "ALTER TABLE face_clusters    ADD COLUMN IF NOT EXISTS stable_key     TEXT",
            "ALTER TABLE clip_items       ADD COLUMN IF NOT EXISTS mute           BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE clip_items       ADD COLUMN IF NOT EXISTS denoise        BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE clip_items       ADD COLUMN IF NOT EXISTS denoise_mix    FLOAT   NOT NULL DEFAULT 1.0",
            "ALTER TABLE outputs          ADD COLUMN IF NOT EXISTS deleted_at     TIMESTAMPTZ",
            "ALTER TABLE outputs          ADD COLUMN IF NOT EXISTS liked_at       TIMESTAMPTZ",
            "ALTER TABLE outputs          ADD COLUMN IF NOT EXISTS nsfw_at        TIMESTAMPTZ",
            "CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
            "CREATE TABLE IF NOT EXISTS prompt_favorites (id SERIAL PRIMARY KEY, node_id TEXT NOT NULL, class_type TEXT NOT NULL, input_key TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (node_id, class_type, input_key))",
            "ALTER TABLE prompt_favorites ADD COLUMN IF NOT EXISTS node_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE prompt_favorites DROP CONSTRAINT IF EXISTS prompt_favorites_class_type_input_key_key",
            "CREATE UNIQUE INDEX IF NOT EXISTS prompt_favorites_node_class_input ON prompt_favorites (node_id, class_type, input_key)",
            "CREATE TABLE IF NOT EXISTS comfyui_cache (key TEXT PRIMARY KEY, data JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
        ]

        with self._connection() as conn:
            for stmt in statements:
                conn.execute(stmt)
            for stmt in migrations:
                conn.execute(stmt)
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
        frame_number: int,
        bbox_area: Optional[float] = None,
        pose_yaw: Optional[float] = None,
        pose_pitch: Optional[float] = None,
        pose_roll: Optional[float] = None,
        det_score: Optional[float] = None,
        age: Optional[int] = None,
        sex: Optional[str] = None,
        embedding: Optional[bytes] = None,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO face_detections
                    (video_id, frame_number, bbox_area, pose_yaw, pose_pitch, pose_roll,
                     det_score, age, sex, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (video_id, frame_number, bbox_area, pose_yaw, pose_pitch, pose_roll,
                  det_score, age, sex, embedding))
            conn.commit()

    def get_face_detections(
        self,
        video_id: int,
        frame_number_min: Optional[int] = None,
        frame_number_max: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM face_detections WHERE video_id = %s"
        params: list = [video_id]
        if frame_number_min is not None:
            query += " AND frame_number >= %s"
            params.append(frame_number_min)
        if frame_number_max is not None:
            query += " AND frame_number <= %s"
            params.append(frame_number_max)
        query += " ORDER BY frame_number"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def has_face_detections(self, video_id: int, frame_number_min: int, frame_number_max: int) -> bool:
        """Return True if any face detections with embeddings exist for this frame range."""
        with self._connection() as conn:
            row = conn.execute("""
                SELECT 1 FROM face_detections
                WHERE video_id = %s AND frame_number >= %s AND frame_number <= %s
                  AND embedding IS NOT NULL
                LIMIT 1
            """, (video_id, frame_number_min, frame_number_max)).fetchone()
            return row is not None

    # ── CLIP embedding cache ──────────────────────────────────────────────────

    def get_clip_embeddings(
        self,
        video_id: int,
        frame_number_min: int,
        frame_number_max: int,
        model: str = 'openai/clip-vit-large-patch14',
    ) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT frame_number, embedding FROM clip_embeddings
                WHERE video_id = %s AND frame_number >= %s AND frame_number <= %s AND model = %s
                ORDER BY frame_number
            """, (video_id, frame_number_min, frame_number_max, model)).fetchall()
            return [dict(r) for r in rows]

    def add_clip_embedding(
        self,
        video_id: int,
        frame_number: int,
        embedding: bytes,
        model: str = 'openai/clip-vit-large-patch14',
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO clip_embeddings (video_id, frame_number, model, embedding)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (video_id, frame_number, model) DO NOTHING
            """, (video_id, frame_number, model, embedding))
            conn.commit()

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

    # ── Tag reference operations ──────────────────────────────────────────────

    def add_tag_reference(
        self,
        tag: str,
        video_id: int,
        frame_number: int,
        frame_time: float,
        embedding: bytes,
        embedding_type: str = 'insightface',
    ) -> int:
        with self._connection() as conn:
            cur = conn.execute("""
                INSERT INTO tag_references (tag, video_id, frame_number, frame_time, embedding, embedding_type)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (tag, video_id, frame_number, frame_time, embedding, embedding_type))
            conn.commit()
            return cur.fetchone()["id"]

    def get_tag_references(self, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        if tag:
            query, params = (
                "SELECT * FROM tag_references WHERE tag = %s ORDER BY tag, id",
                [tag],
            )
        else:
            query, params = (
                "SELECT * FROM tag_references ORDER BY tag, id",
                [],
            )
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ── Face cluster operations ───────────────────────────────────────────────

    def get_face_detections_with_embeddings(
        self, video_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Return face_detections rows that have embeddings, optionally filtered by video.
        Includes scene_id (NULL if the frame falls outside all known scenes)."""
        query = """
            SELECT fd.id, fd.video_id, fd.frame_number, fd.embedding,
                   s.id AS scene_id
            FROM face_detections fd
            JOIN videos v ON v.id = fd.video_id
            LEFT JOIN scenes s ON s.video_id = fd.video_id
              AND (fd.frame_number - COALESCE(v.frame_offset, 0))::float / v.fps
                  BETWEEN s.start_time AND s.end_time
            WHERE fd.embedding IS NOT NULL
        """
        params: list = []
        if video_id is not None:
            query += " AND fd.video_id = %s"
            params.append(video_id)
        query += " ORDER BY fd.video_id, fd.frame_number"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_tag_reference_centroids(self) -> Dict[str, Any]:
        """Return {tag: normalized centroid np.ndarray} for all insightface tag references."""
        import numpy as np
        from ..faces.embed import embedding_from_bytes
        refs = self.get_tag_references()
        from collections import defaultdict
        by_tag: dict = defaultdict(list)
        for r in refs:
            if r.get('embedding') and (not r.get('embedding_type') or r['embedding_type'] == 'insightface'):
                emb = embedding_from_bytes(bytes(r['embedding']))
                by_tag[r['tag']].append(emb)
        centroids = {}
        for tag, embs in by_tag.items():
            stack = np.vstack(embs)
            c = np.mean(stack, axis=0)
            norm = np.linalg.norm(c)
            centroids[tag] = c / norm if norm > 0 else c
        return centroids

    def save_face_clusters(
        self, clusters: List[Dict[str, Any]], video_id: Optional[int] = None,
        preserve_threshold: float = 0.80,
    ) -> None:
        """Replace face_clusters for this scope with fresh results.

        Preserved promoted_tag and dismissed state are carried over to new clusters
        whose centroid is within preserve_threshold cosine similarity of an old one.
        """
        with self._connection() as conn:
            # Save promoted/dismissed clusters before wiping so we can restore them
            scope_filter = "video_id = %s" if video_id is not None else "video_id IS NULL"
            scope_params = (video_id,) if video_id is not None else ()
            old_rows = conn.execute(
                f"SELECT centroid, promoted_tag, dismissed, stable_key FROM face_clusters "
                f"WHERE {scope_filter} AND (promoted_tag IS NOT NULL OR dismissed = TRUE)",
                scope_params,
            ).fetchall()

            preserved = []
            for r in old_rows:
                c = np.frombuffer(bytes(r['centroid']), dtype=np.float32).copy()
                norm = np.linalg.norm(c)
                preserved.append({
                    'centroid': c / norm if norm > 0 else c,
                    'promoted_tag': r['promoted_tag'],
                    'dismissed': r['dismissed'],
                    'stable_key': r['stable_key'],
                })

            if video_id is not None:
                conn.execute("DELETE FROM face_clusters WHERE video_id = %s", (video_id,))
            else:
                conn.execute("DELETE FROM face_clusters WHERE video_id IS NULL")

            for c in clusters:
                promoted_tag = None
                dismissed = False
                stable_key = None

                if preserved:
                    new_c = np.frombuffer(bytes(c['centroid']), dtype=np.float32).copy()
                    norm = np.linalg.norm(new_c)
                    new_c = new_c / norm if norm > 0 else new_c
                    sims = [float(np.dot(new_c, p['centroid'])) for p in preserved]
                    best_idx = int(np.argmax(sims))
                    if sims[best_idx] >= preserve_threshold:
                        promoted_tag = preserved[best_idx]['promoted_tag']
                        dismissed = preserved[best_idx]['dismissed']
                        stable_key = preserved[best_idx]['stable_key']

                conn.execute("""
                    INSERT INTO face_clusters
                        (video_id, cluster_label, centroid, size, stable_key,
                         member_detection_ids, sample_frame_numbers, sample_video_ids,
                         nearest_tag, nearest_sim, promoted_tag, dismissed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    video_id,
                    c['cluster_label'],
                    c['centroid'],
                    c['size'],
                    stable_key,
                    c.get('member_detection_ids', []),
                    c['sample_frame_numbers'],
                    c['sample_video_ids'],
                    c.get('nearest_tag'),
                    c.get('nearest_sim'),
                    promoted_tag,
                    dismissed,
                ))
            conn.commit()

    def get_face_clusters(
        self,
        video_id: Optional[int] = None,
        include_dismissed: bool = False,
    ) -> List[Dict[str, Any]]:
        query = "SELECT id, video_id, cluster_label, size, sample_frame_numbers, sample_video_ids, nearest_tag, nearest_sim, dismissed, promoted_tag, created_at FROM face_clusters WHERE 1=1"
        params: list = []
        if video_id is not None:
            query += " AND video_id = %s"
            params.append(video_id)
        if not include_dismissed:
            query += " AND dismissed = FALSE"
        query += " ORDER BY size DESC"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def dismiss_cluster(self, cluster_id: int) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE face_clusters SET dismissed = TRUE WHERE id = %s", (cluster_id,)
            )
            conn.commit()

    def promote_cluster(self, cluster_id: int, tag: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE face_clusters SET promoted_tag = %s WHERE id = %s", (tag, cluster_id)
            )
            conn.commit()

    def get_cluster_centroid(self, cluster_id: int) -> Optional[bytes]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT centroid, sample_frame_numbers, sample_video_ids FROM face_clusters WHERE id = %s",
                (cluster_id,)
            ).fetchone()
            return dict(row) if row else None

    # ── Scene tag operations ──────────────────────────────────────────────────

    def add_scene_tag(self, scene_id: int, tag: str, confirmed: bool = True) -> None:
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO scene_tags (scene_id, tag, confirmed)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (scene_id, tag) DO UPDATE SET confirmed = EXCLUDED.confirmed""",
                (scene_id, tag, confirmed),
            )
            conn.commit()

    def get_tags_with_confirmed_scenes(self, video_id: Optional[int] = None) -> set:
        """Return the set of tags that have at least one confirmed scene_tag row.

        If video_id is given, restrict to scenes from that video only.
        """
        with self._connection() as conn:
            if video_id is not None:
                rows = conn.execute("""
                    SELECT DISTINCT st.tag
                    FROM scene_tags st
                    JOIN scenes s ON s.id = st.scene_id
                    WHERE st.confirmed = TRUE AND s.video_id = %s
                """, (video_id,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT DISTINCT tag FROM scene_tags WHERE confirmed = TRUE
                """).fetchall()
            return {r["tag"] for r in rows}

    # ── Output scan operations ────────────────────────────────────────────────

    def get_output_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, sha256 FROM outputs WHERE path = %s", (path,)
            ).fetchone()
            return dict(row) if row else None

    def upsert_output(
        self,
        path: str,
        sha256: str,
        file_size: Optional[int],
        file_mtime,
        mime_type: Optional[str],
        width: Optional[int],
        height: Optional[int],
        workflow: Optional[dict],
        prompt: Optional[dict],
    ) -> int:
        wf_json = json.dumps(workflow) if workflow is not None else None
        pr_json = json.dumps(prompt) if prompt is not None else None
        with self._connection() as conn:
            cur = conn.execute("""
                INSERT INTO outputs (path, sha256, file_size, file_mtime, mime_type, width, height, workflow, prompt)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (path) DO UPDATE SET
                    sha256     = EXCLUDED.sha256,
                    file_size  = EXCLUDED.file_size,
                    file_mtime = EXCLUDED.file_mtime,
                    mime_type  = EXCLUDED.mime_type,
                    width      = EXCLUDED.width,
                    height     = EXCLUDED.height,
                    workflow   = EXCLUDED.workflow,
                    prompt     = EXCLUDED.prompt,
                    indexed_at = NOW()
                RETURNING id
            """, (path, sha256, file_size, file_mtime, mime_type, width, height, wf_json, pr_json))
            conn.commit()
            return cur.fetchone()['id']

    def get_scenes_without_tag(self, tag: str, video_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return scenes that do not have the given tag, but only from videos that already
        have at least one confirmed scene with that tag (so we don't blindly scan unrelated videos).

        If video_id is given, only scenes from that video are returned (still subject to the
        confirmed-presence filter).
        """
        with self._connection() as conn:
            if video_id is not None:
                rows = conn.execute("""
                    SELECT s.id, s.video_id, s.start_time, s.end_time,
                           v.path AS video_path, v.fps
                    FROM scenes s
                    JOIN videos v ON v.id = s.video_id
                    WHERE v.id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM scene_tags st
                          WHERE st.scene_id = s.id AND st.tag = %s
                      )
                      AND EXISTS (
                          SELECT 1 FROM scene_tags st2
                          JOIN scenes s2 ON s2.id = st2.scene_id
                          WHERE s2.video_id = v.id AND st2.tag = %s AND st2.confirmed = TRUE
                      )
                    ORDER BY s.start_time
                """, (video_id, tag, tag)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT s.id, s.video_id, s.start_time, s.end_time,
                           v.path AS video_path, v.fps
                    FROM scenes s
                    JOIN videos v ON v.id = s.video_id
                    WHERE NOT EXISTS (
                        SELECT 1 FROM scene_tags st
                        WHERE st.scene_id = s.id AND st.tag = %s
                    )
                    AND EXISTS (
                        SELECT 1 FROM scene_tags st2
                        JOIN scenes s2 ON s2.id = st2.scene_id
                        WHERE s2.video_id = v.id AND st2.tag = %s AND st2.confirmed = TRUE
                    )
                    ORDER BY s.video_id, s.start_time
                """, (tag, tag)).fetchall()
            return [dict(r) for r in rows]


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
