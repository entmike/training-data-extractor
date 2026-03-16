"""
Configuration management for the LTX-2 dataset builder.

All thresholds and settings are configurable via YAML or CLI.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List
import yaml


@dataclass
class SceneConfig:
    """Scene detection configuration."""
    min_duration: float = 2.0  # Minimum scene duration in seconds
    max_duration: float = 8.0  # Maximum scene duration in seconds
    threshold: float = 3.0  # Adaptive detection threshold for PySceneDetect (AdaptiveDetector)
    min_scene_len: int = 15  # Minimum scene length in frames


@dataclass
class FaceConfig:
    """Face detection and identity gating configuration."""
    min_face_presence: float = 0.5  # Minimum fraction of frames with face
    min_face_size: int = 64  # Minimum face size in pixels
    detection_threshold: float = 0.5  # Face detection confidence threshold
    embedding_model: str = "buffalo_l"  # InsightFace model for embeddings
    similarity_threshold: float = 0.4  # Cosine similarity threshold for identity
    sample_frames: int = 5  # Number of frames to sample per clip for face detection


@dataclass
class CropConfig:
    """Crop generation configuration."""
    expansion_ratio: float = 0.2  # Bounding box expansion ratio
    face_crop_scale: float = 1.5  # Scale factor for face crops
    half_body_scale: float = 2.5  # Scale factor for half-body crops
    smoothing_window: int = 5  # Window size for bounding box smoothing


@dataclass
class RenderConfig:
    """Bucket rendering configuration."""
    resolution: int = 1024  # Target resolution (square)
    frame_count: int = 121  # Target frame count per bucket
    fps: int = 24  # Target FPS
    output_format: str = "png"  # Output image format
    jpeg_quality: int = 95  # JPEG quality if using jpeg format


@dataclass
class CaptionConfig:
    """Caption generation configuration."""
    template: str = "{token}, cinematic, high quality"
    auto_caption: bool = False  # Use VLM for auto-captioning
    vlm_model: Optional[str] = None  # VLM model for auto-captioning


@dataclass
class BucketConfig:
    """Auto-detected bucket configuration.
    
    All duration/frame values are in FRAMES, not seconds.
    Values are converted from seconds to frames using base_fps if needed.
    """
    target_frame_count: int = 121  # Target frame count (multiple of 24)
    base_fps: int = 24  # Base FPS for frame count calculation
    min_speech_score: float = 0.3  # Minimum speech activity score
    speech_weight: float = 0.7  # Weight for speech in optimization
    visual_weight: float = 0.3  # Weight for visual quality in optimization
    min_frames: int = 24  # Minimum bucket frame count (24 frames = 1s at 24fps)
    max_frames: int = 144  # Maximum bucket frame count (144 frames = 6s at 24fps)
    speech_margin_frames: int = 12  # Frames to include before/after speech


@dataclass
class PipelineConfig:
    """Main pipeline configuration."""
    # Input/output paths
    source_dir: Path = field(default_factory=lambda: Path("/mnt/nas/movies"))
    output_dir: Path = field(default_factory=lambda: Path("./dataset"))
    cache_dir: Path = field(default_factory=lambda: Path("./.cache"))
    db_path: Path = field(default_factory=lambda: Path("./.cache/index.db"))

    # Token for character identification
    token: str = "character_person"

    # Video formats to process
    video_extensions: List[str] = field(
        default_factory=lambda: [".mkv", ".mp4", ".avi", ".mov", ".webm"]
    )

    # Sub-configurations
    scene: SceneConfig = field(default_factory=SceneConfig)
    face: FaceConfig = field(default_factory=FaceConfig)
    crop: CropConfig = field(default_factory=CropConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    caption: CaptionConfig = field(default_factory=CaptionConfig)
    bucket: BucketConfig = field(default_factory=BucketConfig)

    # Processing options
    num_workers: int = 4  # Number of parallel workers for CPU tasks
    gpu_batch_size: int = 8  # Batch size for GPU operations
    skip_existing: bool = True  # Skip already processed clips
    verbose: bool = False  # Verbose logging

    @classmethod
    def from_yaml(cls, path: Path) -> "PipelineConfig":
        """Load configuration from YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineConfig":
        """Create configuration from dictionary."""
        config = cls()

        # Update top-level fields
        for key in ['source_dir', 'output_dir', 'cache_dir', 'db_path']:
            if key in data:
                setattr(config, key, Path(data[key]))

        for key in ['token', 'num_workers', 'gpu_batch_size', 'skip_existing', 'verbose']:
            if key in data:
                setattr(config, key, data[key])

        if 'video_extensions' in data:
            config.video_extensions = data['video_extensions']

        # Update sub-configurations
        if 'scene' in data:
            for k, v in data['scene'].items():
                setattr(config.scene, k, v)

        if 'face' in data:
            for k, v in data['face'].items():
                setattr(config.face, k, v)

        if 'crop' in data:
            for k, v in data['crop'].items():
                setattr(config.crop, k, v)

        if 'render' in data:
            for k, v in data['render'].items():
                setattr(config.render, k, v)

        if 'caption' in data:
            for k, v in data['caption'].items():
                setattr(config.caption, k, v)

        if 'bucket' in data:
            # Convert seconds to frames if using old field names
            min_dur = data['bucket'].get('min_duration', data['bucket'].get('min_frames', 100))
            max_dur = data['bucket'].get('max_duration', data['bucket'].get('max_frames', 144))
            speech_marg = data['bucket'].get('speech_margin', data['bucket'].get('speech_margin_frames', 12))
            # If values are floats (seconds), convert to frames
            if isinstance(min_dur, float):
                min_dur = int(min_dur * data['bucket'].get('base_fps', 24))
            if isinstance(max_dur, float):
                max_dur = int(max_dur * data['bucket'].get('base_fps', 24))
            data['bucket']['min_frames'] = min_dur
            data['bucket']['max_frames'] = max_dur
            data['bucket']['speech_margin_frames'] = int(speech_marg * data['bucket'].get('base_fps', 24))
            for k, v in data['bucket'].items():
                setattr(config.bucket, k, v)

        return config

    def to_yaml(self, path: Path) -> None:
        """Save configuration to YAML file."""
        data = {
            'source_dir': str(self.source_dir),
            'output_dir': str(self.output_dir),
            'cache_dir': str(self.cache_dir),
            'db_path': str(self.db_path),
            'token': self.token,
            'video_extensions': self.video_extensions,
            'num_workers': self.num_workers,
            'gpu_batch_size': self.gpu_batch_size,
            'skip_existing': self.skip_existing,
            'verbose': self.verbose,
            'scene': {
                'min_duration': self.scene.min_duration,
                'max_duration': self.scene.max_duration,
                'threshold': self.scene.threshold,
                'min_scene_len': self.scene.min_scene_len,
            },
            'face': {
                'min_face_presence': self.face.min_face_presence,
                'min_face_size': self.face.min_face_size,
                'detection_threshold': self.face.detection_threshold,
                'embedding_model': self.face.embedding_model,
                'similarity_threshold': self.face.similarity_threshold,
                'sample_frames': self.face.sample_frames,
            },
            'crop': {
                'expansion_ratio': self.crop.expansion_ratio,
                'face_crop_scale': self.crop.face_crop_scale,
                'half_body_scale': self.crop.half_body_scale,
                'smoothing_window': self.crop.smoothing_window,
            },
            'render': {
                'resolution': self.render.resolution,
                'frame_count': self.render.frame_count,
                'fps': self.render.fps,
                'output_format': self.render.output_format,
                'jpeg_quality': self.render.jpeg_quality,
            },
            'caption': {
                'template': self.caption.template,
                'auto_caption': self.caption.auto_caption,
                'vlm_model': self.caption.vlm_model,
            },
            'bucket': {
                'target_frame_count': self.bucket.target_frame_count,
                'base_fps': self.bucket.base_fps,
                'min_speech_score': self.bucket.min_speech_score,
                'speech_weight': self.bucket.speech_weight,
                'visual_weight': self.bucket.visual_weight,
                'min_frames': self.bucket.min_frames,
                'max_frames': self.bucket.max_frames,
                'speech_margin_frames': self.bucket.speech_margin_frames,
            },
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def ensure_dirs(self) -> None:
        """Ensure all required directories exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "samples").mkdir(parents=True, exist_ok=True)
