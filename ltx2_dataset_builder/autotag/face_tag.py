"""
Face-recognition-based automatic scene tagging.

Workflow:
  1. Register reference frames per tag:
       ltx2-build --add-tag-ref deadpool --video movie.mkv --time 330.5

  2. Run auto-tagging:
       ltx2-build --step auto-tag [--tag deadpool]
"""

from pathlib import Path
from typing import Optional
import logging
import numpy as np

from ..config import PipelineConfig
from ..utils.io import Database
from ..utils.ffmpeg import get_frame_at_time, sample_frames_from_clip
from ..faces.detect import get_face_analyzer, detect_faces_in_frame
from ..faces.embed import embedding_from_bytes

logger = logging.getLogger(__name__)


def _resolve_video(db: Database, video_name: str) -> dict:
    """Find a video by ID or path substring. Raises ValueError if not found."""
    videos = db.get_all_videos()
    try:
        vid_id = int(video_name)
        for v in videos:
            if v["id"] == vid_id:
                return v
    except ValueError:
        pass
    for v in videos:
        if video_name in v["path"]:
            return v
    raise ValueError(f"Video not found: {video_name!r}")


def _pick_best_face(frame_bgr: np.ndarray, config) -> Optional[bytes]:
    """
    Run InsightFace on a BGR frame and return the embedding bytes of the
    highest-confidence face, or None if no face was detected.
    """
    frame_rgb = frame_bgr[:, :, ::-1]
    analyzer = get_face_analyzer(config.face.embedding_model)
    faces = analyzer.get(frame_rgb)
    if not faces:
        return None
    best = max(faces, key=lambda f: float(f.det_score))
    if best.embedding is None:
        return None
    return best.embedding.tobytes()


# ── Public API ────────────────────────────────────────────────────────────────

def add_tag_reference(
    config: PipelineConfig,
    tag: str,
    video_name: str,
    frame_number: int,
) -> None:
    """
    Extract a face embedding from `video_name` at `frame_number` and store it
    as a reference embedding for `tag`.
    """
    db = Database(config.dsn)

    video = _resolve_video(db, video_name)
    video_path = Path(video["path"])
    fps = video.get("fps") or 24.0
    frame_time = frame_number / fps

    logger.info(
        f"Extracting reference frame from {video_path.name} "
        f"frame {frame_number} ({frame_time:.2f}s)"
    )

    frame = get_frame_at_time(video_path, frame_time)
    embedding_bytes = _pick_best_face(frame, config)

    if embedding_bytes is None:
        logger.error(
            f"No face detected in {video_path.name} at frame {frame_number}. "
            "Try a different frame."
        )
        return

    db.add_tag_reference(tag, video["id"], frame_number, frame_time, embedding_bytes)
    logger.info(
        f"Stored reference for tag '{tag}' "
        f"(video={video_path.name}, frame={frame_number}, t={frame_time:.2f}s)"
    )


def list_tag_references(config: PipelineConfig, tag: Optional[str] = None) -> None:
    """Print all stored tag references (optionally filtered by tag)."""
    db = Database(config.dsn)
    refs = db.get_tag_references(tag=tag)
    if not refs:
        print("No tag references stored.")
        return
    from collections import defaultdict
    by_tag: dict = defaultdict(list)
    for r in refs:
        by_tag[r["tag"]].append(r)
    for t, rows in sorted(by_tag.items()):
        print(f"\n[{t}]  ({len(rows)} reference{'s' if len(rows) != 1 else ''})")
        for r in rows:
            print(f"  id={r['id']}  video_id={r['video_id']}  frame={r.get('frame_number', '?')}  ({r['frame_time']:.2f}s)")


def run_auto_tag(
    config: PipelineConfig,
    tag_filter: Optional[str] = None,
    video_filter: Optional[str] = None,
) -> None:
    """
    For every tag that has stored references (or just `tag_filter` if given),
    sample frames from each untagged scene and apply the tag where the dominant
    face matches the reference centroid.

    If video_filter is given (video ID or path substring), only scenes from that
    video are evaluated.
    """
    from tqdm import tqdm

    db = Database(config.dsn)
    threshold = config.face.auto_tag_threshold
    frames_per_scene = config.face.auto_tag_frames_per_scene
    min_votes = config.face.auto_tag_min_votes

    # Resolve optional video filter to a video_id
    video_id: Optional[int] = None
    if video_filter:
        video = _resolve_video(db, video_filter)
        video_id = video["id"]
        logger.info(f"Constraining to video: {video['path']} (id={video_id})")

    # Build {tag: centroid_embedding} from stored references, restricted to tags
    # that already have at least one confirmed scene in the target video(s).
    relevant_tags = db.get_tags_with_confirmed_scenes(video_id=video_id)
    if tag_filter:
        relevant_tags = {tag_filter} & relevant_tags

    refs = db.get_tag_references(tag=tag_filter)
    refs = [r for r in refs if r["tag"] in relevant_tags]

    if not refs:
        msg = f"No references for tag '{tag_filter}'" if tag_filter else "No tag references stored"
        logger.error(f"{msg} with confirmed scenes in the target video(s). Nothing to scan.")
        return

    # Group and compute per-tag centroids
    from collections import defaultdict
    raw: dict = defaultdict(list)
    for r in refs:
        if r.get("embedding"):
            raw[r["tag"]].append(embedding_from_bytes(bytes(r["embedding"])))

    centroids: dict[str, np.ndarray] = {}
    for tag, embs in raw.items():
        stack = np.vstack(embs)
        centroid = np.mean(stack, axis=0)
        norm = np.linalg.norm(centroid)
        centroids[tag] = centroid / norm if norm > 0 else centroid
    logger.info(f"Loaded centroids for {len(centroids)} tag(s): {list(centroids)}")

    # Pre-load InsightFace once
    analyzer = get_face_analyzer(config.face.embedding_model)

    # Build a unified scene list: for each scene collect the set of tags it still needs.
    # This lets us sample frames once per scene and check all centroids in one pass.
    scenes_by_id: dict = {}
    scene_tags_needed: dict = defaultdict(set)  # scene_id -> set of tags to check

    for tag in centroids:
        for scene in db.get_scenes_without_tag(tag, video_id=video_id):
            sid = scene["id"]
            scenes_by_id[sid] = scene
            scene_tags_needed[sid].add(tag)

    logger.info(
        f"Scanning {len(scenes_by_id)} unique scene(s) for "
        f"{len(centroids)} tag(s): {list(centroids)}"
    )

    tagged_counts: dict = defaultdict(int)

    for scene_id, scene in tqdm(scenes_by_id.items(), desc="auto-tag", unit="scene"):
        tags_to_check = scene_tags_needed[scene_id]
        video_path = Path(scene["video_path"])
        fps = scene.get("fps") or 24.0

        # votes[tag] and best_sim[tag] accumulated across all frames in this scene
        votes: dict = defaultdict(int)
        best_sim: dict = defaultdict(float)

        start_frame = int(round(scene["start_time"] * fps))
        end_frame   = int(round(scene["end_time"]   * fps))

        # Fast path: embeddings already stored for this scene's frame range
        cached = db.get_face_detections(scene["video_id"], start_frame, end_frame)
        cached_with_emb = [r for r in cached if r.get("embedding")]

        if cached_with_emb:
            logger.debug(f"  Scene {scene_id}: using {len(cached_with_emb)} cached face detection(s)")
            face_embeddings = [
                embedding_from_bytes(bytes(r["embedding"])) for r in cached_with_emb
            ]
            for raw_emb in face_embeddings:
                norm = np.linalg.norm(raw_emb)
                if norm == 0:
                    continue
                emb = raw_emb / norm
                for tag in tags_to_check:
                    sim = float(np.dot(centroids[tag], emb))
                    if sim > best_sim[tag]:
                        best_sim[tag] = sim
                    if sim >= threshold:
                        votes[tag] += 1
        else:
            # Slow path: extract frames, run InsightFace, store results
            try:
                frames = sample_frames_from_clip(
                    video_path, scene["start_time"], scene["end_time"], frames_per_scene
                )
            except Exception as e:
                logger.warning(f"Scene {scene_id}: frame extraction failed — {e}")
                continue

            for frame_t, frame_bgr in frames:
                frame_rgb = frame_bgr[:, :, ::-1]
                faces = analyzer.get(frame_rgb)

                for face in faces:
                    # Record detection metadata + embedding for future rescans
                    bbox = face.bbox
                    bbox_area = float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) if bbox is not None else None
                    pose = face.pose
                    db.add_face_detection(
                        video_id=scene["video_id"],
                        frame_number=int(round(frame_t * fps)),
                        bbox_area=bbox_area,
                        pose_yaw=float(pose[0]) if pose is not None else None,
                        pose_pitch=float(pose[1]) if pose is not None else None,
                        pose_roll=float(pose[2]) if pose is not None else None,
                        det_score=float(face.det_score) if face.det_score is not None else None,
                        age=int(face.age) if face.age is not None else None,
                        sex=str(face.sex) if face.sex is not None else None,
                        embedding=face.embedding.tobytes() if face.embedding is not None else None,
                    )

                    if face.embedding is None:
                        continue
                    emb = face.embedding / np.linalg.norm(face.embedding)

                    # Check this face against every tag centroid in one shot
                    for tag in tags_to_check:
                        sim = float(np.dot(centroids[tag], emb))
                        if sim > best_sim[tag]:
                            best_sim[tag] = sim
                        if sim >= threshold:
                            votes[tag] += 1
                            logger.debug(
                                f"  Scene {scene_id} t={frame_t:.1f}s — "
                                f"'{tag}' match: similarity={sim:.3f}"
                            )

        for tag in tags_to_check:
            if votes[tag] >= min_votes:
                db.add_scene_tag(scene_id, tag, confirmed=False)
                tagged_counts[tag] += 1
                logger.info(
                    f"  ✓ Tagged scene {scene_id} as '{tag}' "
                    f"({votes[tag]}/{frames_per_scene} votes, best sim={best_sim[tag]:.3f})"
                )

    total_tagged = sum(tagged_counts.values())
    for tag, count in sorted(tagged_counts.items()):
        logger.info(f"Tag '{tag}': applied to {count} scene(s)")
    logger.info(f"Auto-tagging complete — {total_tagged} scene-tag(s) applied in total")
