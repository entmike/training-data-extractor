"""
Face detection using InsightFace.

Detects faces in video frames and caches results.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import logging
import numpy as np
from tqdm import tqdm

from ..config import PipelineConfig, FaceConfig
from ..utils.ffmpeg import sample_frames_from_clip
from ..utils.io import Database

logger = logging.getLogger(__name__)

# Global face analyzer instance (lazy loaded)
_face_analyzer = None


def get_face_analyzer(model_name: str = "buffalo_l"):
    """
    Get or create the InsightFace analyzer.
    
    Args:
        model_name: Name of the InsightFace model
        
    Returns:
        InsightFace FaceAnalysis instance
    """
    global _face_analyzer
    
    if _face_analyzer is None:
        try:
            from insightface.app import FaceAnalysis
            
            _face_analyzer = FaceAnalysis(
                name=model_name,
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
            )
            _face_analyzer.prepare(ctx_id=0, det_size=(640, 640))
            logger.info(f"Initialized InsightFace with model: {model_name}")
        except ImportError:
            logger.error("InsightFace not installed. Install with: pip install insightface onnxruntime-gpu")
            raise
    
    return _face_analyzer


def detect_faces_in_frame(
    frame: np.ndarray,
    config: FaceConfig
) -> List[Dict[str, Any]]:
    """
    Detect faces in a single frame.
    
    Args:
        frame: BGR image as numpy array
        config: Face detection configuration
        
    Returns:
        List of detected faces with bboxes and embeddings
    """
    analyzer = get_face_analyzer(config.embedding_model)
    
    # InsightFace expects RGB
    frame_rgb = frame[:, :, ::-1]
    
    faces = analyzer.get(frame_rgb)
    
    results = []
    for face in faces:
        bbox = face.bbox.astype(int).tolist()
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        
        # Filter by size
        if width < config.min_face_size or height < config.min_face_size:
            continue
        
        # Filter by confidence
        if face.det_score < config.detection_threshold:
            continue
        
        results.append({
            "bbox": (x1, y1, width, height),
            "confidence": float(face.det_score),
            "embedding": face.embedding.tobytes() if face.embedding is not None else None,
            "landmark_2d": face.landmark_2d_106.tolist() if hasattr(face, 'landmark_2d_106') and face.landmark_2d_106 is not None else None
        })
    
    return results


def detect_faces_in_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    config: FaceConfig,
    num_samples: int = 5
) -> Dict[str, Any]:
    """
    Detect faces in a video clip.
    
    Args:
        video_path: Path to the video file
        start_time: Clip start time
        end_time: Clip end time
        config: Face detection configuration
        num_samples: Number of frames to sample
        
    Returns:
        Dictionary with face detection results
    """
    from ..utils.ffmpeg import sample_frames_from_clip
    
    # Sample frames
    frames = sample_frames_from_clip(
        video_path,
        start_time,
        end_time,
        num_samples
    )
    
    if not frames:
        return {
            "face_presence": 0.0,
            "frames_with_faces": 0,
            "total_frames": 0,
            "detections": []
        }
    
    # Detect faces in each frame
    frames_with_faces = 0
    all_detections = []
    
    for time, frame in frames:
        faces = detect_faces_in_frame(frame, config)
        
        if faces:
            frames_with_faces += 1
        
        all_detections.append({
            "time": time,
            "faces": faces
        })
    
    face_presence = frames_with_faces / len(frames)
    
    return {
        "face_presence": face_presence,
        "frames_with_faces": frames_with_faces,
        "total_frames": len(frames),
        "detections": all_detections
    }


def filter_candidates_by_face(
    config: PipelineConfig,
    candidates: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Filter candidates by face presence.
    
    Args:
        config: Pipeline configuration
        candidates: Optional list of candidates
        
    Returns:
        List of candidates that passed face filtering
    """
    db = Database(config.db_path)
    
    if candidates is None:
        # Get pending candidates
        candidates = db.get_candidates(status="pending")
    
    passed = []
    failed = 0
    
    pbar = tqdm(candidates, desc="Face filtering", unit="clip")
    for candidate in pbar:
        video = db.get_video_by_id(candidate["video_id"])
        if not video:
            continue
        
        video_path = Path(video["path"])
        video_name = video_path.stem[:20]
        fps = video.get("fps", 24.0)
        
        # Apply frame offset (convert frames to seconds)
        frame_offset = db.get_frame_offset(video["id"])
        time_offset = frame_offset / fps if fps > 0 else 0
        
        start_time = max(0, candidate["start_time"] + time_offset)
        end_time = candidate["end_time"] + time_offset
        
        # Update progress bar with current clip info
        pbar.set_postfix({
            "video": video_name,
            "clip": candidate["id"],
            "passed": len(passed),
            "failed": failed
        })
        
        try:
            result = detect_faces_in_clip(
                video_path,
                start_time,
                end_time,
                config.face,
                num_samples=config.face.sample_frames
            )
            
            # Cache face detections
            for detection in result["detections"]:
                for face in detection["faces"]:
                    db.add_face_detection(
                        video_id=candidate["video_id"],
                        frame_time=detection["time"],
                        bbox=face["bbox"],
                        confidence=face["confidence"],
                        embedding=face["embedding"]
                    )
            
            # Check face presence threshold
            passes = result["face_presence"] >= config.face.min_face_presence
            
            db.update_candidate(
                candidate["id"],
                face_presence=result["face_presence"],
                status="accepted" if passes else "face_failed"
            )
            
            if passes:
                candidate["face_presence"] = result["face_presence"]
                candidate["face_detections"] = result["detections"]
                passed.append(candidate)
            else:
                failed += 1
                
        except Exception as e:
            logger.error(f"Face detection failed for candidate {candidate['id']}: {e}")
            db.update_candidate(candidate["id"], status="error")
            failed += 1
    
    logger.info(f"Face filtering: {len(passed)} passed, {failed} failed")
    return passed
