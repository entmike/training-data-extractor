"""
Face-recognition-based automatic scene tagging.

Supports two embedding strategies:
  - insightface (default): detect face region, embed with buffalo_l. Best for real faces.
  - clip: embed the whole frame with CLIP ViT. Works on any visual style (Pixar, anime, etc.)

Workflow:
  1. Register reference frames per tag:
       ltx2-build --add-tag-ref deadpool --video movie.mkv --frame 7932
       ltx2-build --add-tag-ref woody --video "Toy Story 4.mkv" --frame 1234 --embedding-type clip

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


def _clip_embed_frame(frame_bgr: np.ndarray, config) -> bytes:
    """Return CLIP embedding bytes for a BGR frame."""
    from ..embed.clip_embed import embed_frame
    emb = embed_frame(frame_bgr, model_name=config.face.clip_model)
    return emb.tobytes()


# ── Public API ────────────────────────────────────────────────────────────────

def add_tag_reference(
    config: PipelineConfig,
    tag: str,
    video_name: str,
    frame_number: int,
    embedding_type: str = 'auto',
) -> None:
    """
    Extract an embedding from `video_name` at `frame_number` and store it
    as a reference embedding for `tag`.

    embedding_type:
      'auto'        — try InsightFace first; fall back to CLIP if no face detected
      'insightface' — force InsightFace (logs error if no face found, stores nothing)
      'clip'        — force CLIP whole-frame embedding (skips face detection)
    """
    db = Database(config.dsn)

    video = _resolve_video(db, video_name)
    video_path = Path(video["path"])
    fps = video.get("fps") or 24.0
    frame_time = frame_number / fps

    logger.info(
        f"Extracting reference frame from {video_path.name} "
        f"frame {frame_number} ({frame_time:.2f}s) [embedding_type={embedding_type}]"
    )

    frame = get_frame_at_time(video_path, frame_time)

    if embedding_type == 'clip':
        embedding_bytes = _clip_embed_frame(frame, config)
        actual_type = 'clip'
    else:
        embedding_bytes = _pick_best_face(frame, config)
        if embedding_bytes is not None:
            actual_type = 'insightface'
        elif embedding_type == 'insightface':
            logger.error(
                f"No face detected in {video_path.name} at frame {frame_number}. "
                "Try a different frame or use --embedding-type clip."
            )
            return
        else:
            # auto fallback to CLIP
            logger.warning(
                f"No face detected at frame {frame_number} — falling back to CLIP embedding."
            )
            embedding_bytes = _clip_embed_frame(frame, config)
            actual_type = 'clip'

    db.add_tag_reference(tag, video["id"], frame_number, frame_time, embedding_bytes, actual_type)
    logger.info(
        f"Stored {actual_type} reference for tag '{tag}' "
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

    # Group and compute per-tag centroids, tracking embedding type per tag
    from collections import defaultdict
    raw: dict = defaultdict(list)
    tag_embedding_type: dict[str, str] = {}  # tag -> 'insightface' | 'clip'
    for r in refs:
        if r.get("embedding"):
            raw[r["tag"]].append(embedding_from_bytes(bytes(r["embedding"])))
            # All refs for a tag should share the same type; take the first seen
            if r["tag"] not in tag_embedding_type:
                tag_embedding_type[r["tag"]] = r.get("embedding_type") or "insightface"

    centroids: dict[str, np.ndarray] = {}
    for tag, embs in raw.items():
        stack = np.vstack(embs)
        centroid = np.mean(stack, axis=0)
        norm = np.linalg.norm(centroid)
        centroids[tag] = centroid / norm if norm > 0 else centroid

    insightface_tags = {t for t, et in tag_embedding_type.items() if et == "insightface"}
    clip_tags = {t for t, et in tag_embedding_type.items() if et == "clip"}
    logger.info(
        f"Loaded centroids for {len(centroids)} tag(s): "
        f"{len(insightface_tags)} InsightFace {sorted(insightface_tags)}, "
        f"{len(clip_tags)} CLIP {sorted(clip_tags)}"
    )

    # Pre-load models once
    analyzer = get_face_analyzer(config.face.embedding_model) if insightface_tags else None
    if clip_tags:
        from ..embed.clip_embed import get_clip_model, embed_frame as clip_embed_frame
        get_clip_model(config.face.clip_model)  # warm up

    clip_threshold = config.face.clip_auto_tag_threshold

    # Build a unified scene list: for each scene collect the set of tags it still needs.
    scenes_by_id: dict = {}
    scene_tags_needed: dict = defaultdict(set)  # scene_id -> set of tags to check

    for tag in centroids:
        for scene in db.get_scenes_without_tag(tag, video_id=video_id):
            sid = scene["id"]
            scenes_by_id[sid] = scene
            scene_tags_needed[sid].add(tag)

    logger.info(f"Scanning {len(scenes_by_id)} unique scene(s)")

    tagged_counts: dict = defaultdict(int)

    for scene_id, scene in tqdm(scenes_by_id.items(), desc="auto-tag", unit="scene"):
        tags_to_check = scene_tags_needed[scene_id]
        video_path = Path(scene["video_path"])
        fps = scene.get("fps") or 24.0

        insightface_tags_needed = tags_to_check & insightface_tags
        clip_tags_needed = tags_to_check & clip_tags

        # votes[tag] and best_sim[tag] accumulated across all frames in this scene
        votes: dict = defaultdict(int)
        best_sim: dict = defaultdict(float)

        # ── InsightFace path ──────────────────────────────────────────────────
        if insightface_tags_needed:
            pad_frames = 5
            start_frame = int(round(scene["start_time"] * fps)) + pad_frames
            end_frame   = int(round(scene["end_time"]   * fps)) - pad_frames
            # If padding collapses the window, fall back to unpadded bounds
            if start_frame >= end_frame:
                start_frame = int(round(scene["start_time"] * fps))
                end_frame   = int(round(scene["end_time"]   * fps))

            # Fast path: scene already processed by the embeddings step (cached rows
            # exist — possibly only sentinels indicating "scanned, no faces found").
            cached = db.get_face_detections(scene["video_id"], start_frame, end_frame)

            if cached:
                cached_with_emb = [r for r in cached if r.get("embedding")]
                logger.debug(
                    f"  Scene {scene_id}: using {len(cached_with_emb)} cached face detection(s) "
                    f"({len(cached) - len(cached_with_emb)} sentinel)"
                )
                for raw_emb in [embedding_from_bytes(bytes(r["embedding"])) for r in cached_with_emb]:
                    norm = np.linalg.norm(raw_emb)
                    if norm == 0:
                        continue
                    emb = raw_emb / norm
                    for tag in insightface_tags_needed:
                        sim = float(np.dot(centroids[tag], emb))
                        if sim > best_sim[tag]:
                            best_sim[tag] = sim
                        if sim >= threshold:
                            votes[tag] += 1
            else:
                # Slow path: extract frames, run InsightFace, store results
                try:
                    frames = sample_frames_from_clip(
                        video_path, scene["start_time"], scene["end_time"], frames_per_scene, fps=fps
                    )
                except Exception as e:
                    logger.warning(f"Scene {scene_id}: frame extraction failed — {e}")
                    frames = []

                for frame_t, frame_bgr in frames:
                    frame_rgb = frame_bgr[:, :, ::-1]
                    faces = analyzer.get(frame_rgb)
                    frame_num = int(round(frame_t * fps))

                    if not faces:
                        db.add_face_detection(video_id=scene["video_id"], frame_number=frame_num)
                        continue

                    for face in faces:
                        bbox = face.bbox
                        bbox_area = float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) if bbox is not None else None
                        pose = face.pose
                        db.add_face_detection(
                            video_id=scene["video_id"],
                            frame_number=frame_num,
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

                        for tag in insightface_tags_needed:
                            sim = float(np.dot(centroids[tag], emb))
                            if sim > best_sim[tag]:
                                best_sim[tag] = sim
                            if sim >= threshold:
                                votes[tag] += 1
                                logger.debug(
                                    f"  Scene {scene_id} t={frame_t:.1f}s — "
                                    f"'{tag}' match: similarity={sim:.3f}"
                                )

        # ── CLIP path ─────────────────────────────────────────────────────────
        if clip_tags_needed:
            pad_frames = 5
            clip_start_frame = int(round(scene["start_time"] * fps)) + pad_frames
            clip_end_frame   = int(round(scene["end_time"]   * fps)) - pad_frames
            if clip_start_frame >= clip_end_frame:
                clip_start_frame = int(round(scene["start_time"] * fps))
                clip_end_frame   = int(round(scene["end_time"]   * fps))
            clip_model_name = config.face.clip_model

            cached_clip = db.get_clip_embeddings(
                scene["video_id"], clip_start_frame, clip_end_frame, model=clip_model_name
            )

            if cached_clip:
                logger.debug(f"  Scene {scene_id}: using {len(cached_clip)} cached CLIP embedding(s)")
                clip_embs = [
                    embedding_from_bytes(bytes(r["embedding"])) for r in cached_clip
                ]
            else:
                try:
                    frames = sample_frames_from_clip(
                        video_path, scene["start_time"], scene["end_time"], frames_per_scene, fps=fps
                    )
                except Exception as e:
                    logger.warning(f"Scene {scene_id}: CLIP frame extraction failed — {e}")
                    frames = []

                clip_embs = []
                for frame_t, frame_bgr in frames:
                    emb = clip_embed_frame(frame_bgr, model_name=clip_model_name)
                    frame_num = int(round(frame_t * fps))
                    db.add_clip_embedding(scene["video_id"], frame_num, emb.tobytes(), model=clip_model_name)
                    clip_embs.append(emb)

            for emb in clip_embs:
                norm = np.linalg.norm(emb)
                emb = emb / norm if norm > 0 else emb
                for tag in clip_tags_needed:
                    sim = float(np.dot(centroids[tag], emb))
                    if sim > best_sim[tag]:
                        best_sim[tag] = sim
                    if sim >= clip_threshold:
                        votes[tag] += 1
                        logger.debug(
                            f"  Scene {scene_id} — "
                            f"'{tag}' CLIP match: similarity={sim:.3f}"
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
