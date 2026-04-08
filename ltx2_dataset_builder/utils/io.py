"""
I/O utilities for the dataset builder.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional, Iterator
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class Database:
    """
    SQLite database for caching and indexing.
    """
    
    def __init__(self, db_path: Path):
        """Initialize database connection."""
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()
    
    def _init_tables(self) -> None:
        """Initialize database tables."""
        with self._connection() as conn:
            # Videos table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    hash TEXT NOT NULL,
                    duration REAL,
                    fps REAL,
                    width INTEGER,
                    height INTEGER,
                    codec TEXT,
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Scenes table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scenes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    duration REAL NOT NULL,
                    start_frame INTEGER,
                    end_frame INTEGER,
                    FOREIGN KEY (video_id) REFERENCES videos(id),
                    UNIQUE(video_id, start_time, end_time)
                )
            """)
            
            # Add frame columns if they don't exist (for existing databases)
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN start_frame INTEGER")
            except:
                pass
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN end_frame INTEGER")
            except:
                pass
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN caption TEXT")
            except:
                pass
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN caption_started_at TIMESTAMP")
            except:
                pass
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN caption_finished_at TIMESTAMP")
            except:
                pass
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN caption_prompt TEXT")
            except:
                pass
            
            # Add blurhash of the first frame for each scene
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN blurhash TEXT")
            except:
                pass

            # Add rating column for scene quality prioritization
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN rating INTEGER DEFAULT 2")
            except:
                pass

            # Mark scenes ineligible for bucket detection (too short, no valid window)
            try:
                conn.execute("ALTER TABLE scenes ADD COLUMN bucket_ineligible INTEGER DEFAULT 0")
            except:
                pass

            # Add frame_offset column to videos (codec timing compensation, default 0)
            try:
                conn.execute("ALTER TABLE videos ADD COLUMN frame_offset INTEGER DEFAULT 0")
            except:
                pass

            # Add per-video captioning prompt
            try:
                conn.execute("ALTER TABLE videos ADD COLUMN prompt TEXT")
            except:
                pass

            # Add user-friendly name column for videos
            try:
                conn.execute("ALTER TABLE videos ADD COLUMN name TEXT")
            except:
                pass
            
            # Buckets table for auto-detected optimal crops
            conn.execute("""
                CREATE TABLE IF NOT EXISTS buckets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    scene_id INTEGER,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    duration REAL NOT NULL,
                    start_frame INTEGER NOT NULL,
                    end_frame INTEGER NOT NULL,
                    frame_count INTEGER,
                    speech_score REAL,
                    speech_start_frame INTEGER,
                    speech_end_frame INTEGER,
                    optimal_offset_frames INTEGER,
                    optimal_duration REAL,
                    bucket_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_id) REFERENCES videos(id),
                    FOREIGN KEY (scene_id) REFERENCES scenes(id),
                    UNIQUE(video_id, start_frame, end_frame)
                )
            """)
            
            # Add speech detection columns to buckets if they don't exist
            try:
                conn.execute("ALTER TABLE buckets ADD COLUMN speech_score REAL")
            except:
                pass
            try:
                conn.execute("ALTER TABLE buckets ADD COLUMN speech_start_frame INTEGER")
            except:
                pass
            try:
                conn.execute("ALTER TABLE buckets ADD COLUMN speech_end_frame INTEGER")
            except:
                pass
            try:
                conn.execute("ALTER TABLE buckets ADD COLUMN optimal_offset_frames INTEGER")
            except:
                pass
            try:
                conn.execute("ALTER TABLE buckets ADD COLUMN optimal_duration REAL")
            except:
                pass
            try:
                conn.execute("ALTER TABLE buckets ADD COLUMN bucket_timestamp DATETIME")
            except:
                pass
            
            # Candidates table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    scene_id INTEGER,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    duration REAL NOT NULL,
                    quality_score REAL,
                    face_presence REAL,
                    status TEXT DEFAULT 'pending',
                    FOREIGN KEY (video_id) REFERENCES videos(id),
                    FOREIGN KEY (scene_id) REFERENCES scenes(id)
                )
            """)
            
            # Face detections cache
            conn.execute("""
                CREATE TABLE IF NOT EXISTS face_detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    frame_time REAL NOT NULL,
                    bbox_x REAL,
                    bbox_y REAL,
                    bbox_w REAL,
                    bbox_h REAL,
                    confidence REAL,
                    embedding BLOB,
                    FOREIGN KEY (video_id) REFERENCES videos(id),
                    UNIQUE(video_id, frame_time)
                )
            """)
            
            # Embeddings cache
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    frame_time REAL NOT NULL,
                    embedding BLOB NOT NULL,
                    cluster_id INTEGER,
                    FOREIGN KEY (video_id) REFERENCES videos(id)
                )
            """)
            
            # Rendered samples
            conn.execute("""
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL,
                    crop_type TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    frame_count INTEGER,
                    caption TEXT,
                    rendered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
                )
            """)
            
            conn.commit()
    
    @contextmanager
    def _connection(self):
        """Context manager for database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    # Video operations
    def add_video(self, path: str, hash: str, metadata: Dict[str, Any]) -> int:
        """Add or update a video in the database."""
        with self._connection() as conn:
            cursor = conn.execute("""
                INSERT OR REPLACE INTO videos (path, hash, duration, fps, width, height, codec, frame_offset, prompt, name)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
            """, (
                path,
                hash,
                metadata.get("duration"),
                metadata.get("fps"),
                metadata.get("width"),
                metadata.get("height"),
                metadata.get("codec"),
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_video(self, path: str) -> Optional[Dict[str, Any]]:
        """Get video by path."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE path = ?", (path,)
            ).fetchone()
            return dict(row) if row else None
    
    def get_video_by_id(self, video_id: int) -> Optional[Dict[str, Any]]:
        """Get video by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE id = ?", (video_id,)
            ).fetchone()
            return dict(row) if row else None
    
    def get_all_videos(self) -> List[Dict[str, Any]]:
        """Get all indexed videos."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM videos").fetchall()
            return [dict(row) for row in rows]
    
    def get_frame_offset(self, video_id: int) -> int:
        """Get frame offset for a video (codec timing compensation)."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT frame_offset FROM videos WHERE id = ?", (video_id,)
            ).fetchone()
            return row["frame_offset"] if row and row["frame_offset"] else 0
    
    def set_frame_offset(self, video_id: int, offset: int) -> None:
        """Set frame offset for a video (codec timing compensation)."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE videos SET frame_offset = ? WHERE id = ?",
                (offset, video_id)
            )
            conn.commit()

    # Video name operations
    def get_video_name(self, video_id: int) -> Optional[str]:
        """Get the user-friendly name for a video."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT name FROM videos WHERE id = ?", (video_id,)
            ).fetchone()
            return row["name"] if row and row["name"] else None

    def set_video_name(self, video_id: int, name: str) -> None:
        """Set the user-friendly name for a video."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE videos SET name = ? WHERE id = ?",
                (name, video_id)
            )
            conn.commit()
    
    # Scene operations
    def add_scenes(self, video_id: int, scenes: List[Dict[str, Any]]) -> List[int]:
        """Add scenes for a video. Returns list of scene IDs (inserted or existing)."""
        ids = []
        with self._connection() as conn:
            for scene in scenes:
                try:
                    start_frame = scene.get("start_frame")
                    end_frame = scene.get("end_frame")
                    frame_count = (end_frame - start_frame) if (start_frame is not None and end_frame is not None) else None
                    default_rating = 1 if (frame_count is not None and frame_count < 24) else 2
                    conn.execute("""
                        INSERT OR IGNORE INTO scenes
                        (video_id, start_time, end_time, duration, start_frame, end_frame, rating)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        video_id,
                        scene["start_time"],
                        scene["end_time"],
                        scene["duration"],
                        start_frame,
                        end_frame,
                        default_rating,
                    ))
                except sqlite3.IntegrityError:
                    pass  # Scene already exists
                row = conn.execute(
                    "SELECT id FROM scenes WHERE video_id = ? AND start_time = ? AND end_time = ?",
                    (video_id, scene["start_time"], scene["end_time"]),
                ).fetchone()
                if row:
                    scene_id = row["id"]
                    ids.append(scene_id)
                    # Insert default full-scene bucket if none exists yet
                    if start_frame is not None and end_frame is not None:
                        conn.execute("""
                            INSERT OR IGNORE INTO buckets
                              (video_id, scene_id, start_time, end_time, duration,
                               start_frame, end_frame, frame_count,
                               optimal_offset_frames, optimal_duration)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                        """, (
                            video_id, scene_id,
                            scene["start_time"], scene["end_time"], scene["duration"],
                            start_frame, end_frame, frame_count,
                            scene["duration"],
                        ))
            conn.commit()
        return ids

    def backfill_default_buckets(self) -> int:
        """Insert default full-scene buckets for any scene that has no bucket row yet."""
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
                    INSERT OR IGNORE INTO buckets
                      (video_id, scene_id, start_time, end_time, duration,
                       start_frame, end_frame, frame_count,
                       optimal_offset_frames, optimal_duration)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """, (
                    s["video_id"], s["id"],
                    s["start_time"], s["end_time"], s["duration"],
                    s["start_frame"], s["end_frame"], frame_count,
                    s["duration"],
                ))
                count += 1
            conn.commit()
            logger.info(f"Backfilled {count} default bucket(s)")
            return count
    
    def get_scenes(self, video_id: int) -> List[Dict[str, Any]]:
        """Get all scenes for a video."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM scenes WHERE video_id = ? ORDER BY start_time",
                (video_id,)
            ).fetchall()
            return [dict(row) for row in rows]
    
    def get_scenes_for_buckets(self, video_id: int) -> List[Dict[str, Any]]:
        """Get scenes that need bucket detection: not ineligible and no bucket yet."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT s.* FROM scenes s
                   LEFT JOIN buckets b ON b.scene_id = s.id
                   WHERE s.video_id = ?
                     AND (s.bucket_ineligible IS NULL OR s.bucket_ineligible = 0)
                     AND b.id IS NULL
                   ORDER BY s.start_time""",
                (video_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_scene_bucket_ineligible(self, scene_id: int) -> None:
        """Mark a scene as ineligible for bucket detection."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE scenes SET bucket_ineligible = 1 WHERE id = ?",
                (scene_id,)
            )
            conn.commit()

    def get_scenes_without_caption(self, video_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get scenes that don't have captions yet."""
        with self._connection() as conn:
            if video_id:
                rows = conn.execute(
                    "SELECT * FROM scenes WHERE video_id = ? AND (caption IS NULL OR caption = '') ORDER BY start_time",
                    (video_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scenes WHERE caption IS NULL OR caption = '' ORDER BY video_id, start_time"
                ).fetchall()
            return [dict(row) for row in rows]
    
    def update_scene_caption(
        self,
        scene_id: int,
        caption: str,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> None:
        """Update the caption for a scene, optionally recording timing and prompt."""
        with self._connection() as conn:
            conn.execute(
                """UPDATE scenes
                   SET caption = ?,
                       caption_started_at = COALESCE(?, caption_started_at),
                       caption_finished_at = COALESCE(?, caption_finished_at),
                       caption_prompt = COALESCE(?, caption_prompt)
                   WHERE id = ?""",
                (caption, started_at, finished_at, prompt, scene_id)
            )
            conn.commit()
    
    def update_clip_item_caption(self, item_id: int, caption: str) -> None:
        """Update the caption for a clip item."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE clip_items SET caption = ? WHERE id = ?",
                (caption, item_id)
            )
            conn.commit()

    # Candidate operations
    def add_candidate(
        self,
        video_id: int,
        scene_id: Optional[int],
        start_time: float,
        end_time: float
    ) -> int:
        """Add a candidate clip."""
        with self._connection() as conn:
            cursor = conn.execute("""
                INSERT INTO candidates (video_id, scene_id, start_time, end_time, duration)
                VALUES (?, ?, ?, ?, ?)
            """, (
                video_id,
                scene_id,
                start_time,
                end_time,
                end_time - start_time,
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update_candidate(
        self,
        candidate_id: int,
        quality_score: Optional[float] = None,
        face_presence: Optional[float] = None,
        status: Optional[str] = None
    ) -> None:
        """Update candidate with scores."""
        updates = []
        params = []
        
        if quality_score is not None:
            updates.append("quality_score = ?")
            params.append(quality_score)
        if face_presence is not None:
            updates.append("face_presence = ?")
            params.append(face_presence)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        
        if updates:
            params.append(candidate_id)
            with self._connection() as conn:
                conn.execute(
                    f"UPDATE candidates SET {', '.join(updates)} WHERE id = ?",
                    params
                )
                conn.commit()
    
    def get_candidates(
        self,
        video_id: Optional[int] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get candidates with optional filters."""
        query = "SELECT * FROM candidates WHERE 1=1"
        params = []
        
        if video_id is not None:
            query += " AND video_id = ?"
            params.append(video_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY video_id, start_time"
        
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    # Face detection cache
    def add_face_detection(
        self,
        video_id: int,
        frame_time: float,
        bbox: Optional[tuple] = None,
        confidence: Optional[float] = None,
        embedding: Optional[bytes] = None
    ) -> None:
        """Cache face detection result."""
        with self._connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO face_detections 
                (video_id, frame_time, bbox_x, bbox_y, bbox_w, bbox_h, confidence, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                video_id,
                frame_time,
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
        end_time: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Get cached face detections."""
        query = "SELECT * FROM face_detections WHERE video_id = ?"
        params = [video_id]
        
        if start_time is not None:
            query += " AND frame_time >= ?"
            params.append(start_time)
        if end_time is not None:
            query += " AND frame_time <= ?"
            params.append(end_time)
        
        query += " ORDER BY frame_time"
        
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    # Sample operations
    def add_sample(
        self,
        candidate_id: int,
        crop_type: str,
        output_path: str,
        frame_count: int,
        caption: str
    ) -> int:
        """Add a rendered sample."""
        with self._connection() as conn:
            cursor = conn.execute("""
                INSERT INTO samples (candidate_id, crop_type, output_path, frame_count, caption)
                VALUES (?, ?, ?, ?, ?)
            """, (candidate_id, crop_type, output_path, frame_count, caption))
            conn.commit()
            return cursor.lastrowid
    
    def get_samples(self, candidate_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get rendered samples."""
        if candidate_id:
            query = "SELECT * FROM samples WHERE candidate_id = ?"
            params = [candidate_id]
        else:
            query = "SELECT * FROM samples"
            params = []
        
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    # Bucket operations
    def add_buckets(
        self,
        video_id: int,
        buckets: List[Dict[str, Any]]
    ) -> List[int]:
        """Add buckets for a video. Returns list of bucket IDs."""
        ids = []
        with self._connection() as conn:
            for bucket in buckets:
                try:
                    cursor = conn.execute("""
                        INSERT OR IGNORE INTO buckets
                        (video_id, scene_id, start_time, end_time, duration,
                         start_frame, end_frame, frame_count, speech_score,
                         speech_start_frame, speech_end_frame, optimal_offset_frames, optimal_duration)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        video_id,
                        bucket.get("scene_id"),
                        bucket["start_time"],
                        bucket["end_time"],
                        bucket["duration"],
                        bucket["start_frame"],
                        bucket["end_frame"],
                        bucket.get("frame_count"),
                        bucket.get("speech_score"),
                        bucket.get("speech_start_frame"),
                        bucket.get("speech_end_frame"),
                        bucket.get("optimal_offset_frames"),
                        bucket.get("optimal_duration"),
                    ))
                    conn.commit()
                    
                    # Get the ID (inserted or existing)
                    row = conn.execute(
                        "SELECT id FROM buckets WHERE video_id = ? AND start_frame = ? AND end_frame = ?",
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
        scene_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get buckets with optional filters."""
        query = "SELECT * FROM buckets WHERE 1=1"
        params = []
        
        if video_id is not None:
            query += " AND video_id = ?"
            params.append(video_id)
        if scene_id is not None:
            query += " AND scene_id = ?"
            params.append(scene_id)
        
        query += " ORDER BY video_id, start_time"
        
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    def get_buckets_without_rendering(
        self,
        video_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get buckets that haven't been rendered yet."""
        # For now, return all buckets - we can add a rendered flag later
        return self.get_buckets(video_id=video_id)


def write_jsonl(path: Path, entries: Iterator[Dict[str, Any]]) -> int:
    """
    Write entries to a JSONL file.
    
    Args:
        path: Output file path
        entries: Iterator of dictionaries to write
        
    Returns:
        Number of entries written
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    
    with open(path, 'w') as f:
        for entry in entries:
            f.write(json.dumps(entry) + '\n')
            count += 1
    
    logger.info(f"Wrote {count} entries to {path}")
    return count


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    """
    Read entries from a JSONL file.
    
    Args:
        path: Input file path
        
    Yields:
        Dictionaries from the file
    """
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
