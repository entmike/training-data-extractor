"""
Face embedding scan.

Iterates over all scenes and runs InsightFace to populate face_detections.
Decoupled from auto-tag so embeddings can be cached upfront and reused by
tagging, clustering, and downstream filters.
"""

from pathlib import Path
from typing import Optional
import logging

from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.ffmpeg import sample_frames_from_clip
from ..utils.io import Database
from .detect import get_face_analyzer

logger = logging.getLogger(__name__)


def scan_face_embeddings(config: PipelineConfig, video_filter: Optional[str] = None) -> int:
    """
    Scan all scenes for face embeddings, storing results in face_detections.

    Args:
        config: Pipeline configuration
        video_filter: If set, only process this video (path basename or display name)

    Returns:
        Total number of face_detection rows added
    """
    db = Database(config.dsn)
    videos = db.get_all_videos()

    if video_filter:
        videos = [
            v for v in videos
            if Path(v["path"]).name == video_filter or v.get("name") == video_filter
        ]
        if not videos:
            logger.error(f"Video not found: {video_filter}")
            return 0

    analyzer = get_face_analyzer(config.face.embedding_model)
    frames_per_scene = config.face.auto_tag_frames_per_scene

    total_added = 0

    for video in videos:
        video_id = video["id"]
        video_path = Path(video["path"])
        fps = video.get("fps") or 24.0
        scenes = db.get_scenes(video_id)

        if not scenes:
            continue

        added_for_video = 0
        for scene in tqdm(scenes, desc=video_path.name, unit="scene"):
            start_frame = int(round(scene["start_time"] * fps))
            end_frame = int(round(scene["end_time"] * fps))

            if config.skip_existing and db.has_scanned_frames(video_id, start_frame, end_frame):
                continue

            try:
                frames = sample_frames_from_clip(
                    video_path, scene["start_time"], scene["end_time"], frames_per_scene, fps=fps
                )
            except Exception as e:
                logger.warning(f"Scene {scene['id']}: frame extraction failed — {e}")
                continue

            for frame_t, frame_bgr in frames:
                frame_rgb = frame_bgr[:, :, ::-1]
                faces = analyzer.get(frame_rgb)
                frame_num = int(round(frame_t * fps))
                if not faces:
                    db.add_face_detection(video_id=video_id, frame_number=frame_num)
                    continue
                for face in faces:
                    bbox = face.bbox
                    bbox_area = float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) if bbox is not None else None
                    pose = face.pose
                    db.add_face_detection(
                        video_id=video_id,
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
                    added_for_video += 1

        logger.info(f"{video_path.name}: added {added_for_video} face detection(s)")
        total_added += added_for_video

    logger.info(f"scan-faces: added {total_added} face detection(s) across {len(videos)} video(s)")
    return total_added
