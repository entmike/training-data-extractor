"""
Manifest generation for LTX-2 training.

Produces manifest.jsonl files compatible with LTX-2 training.
"""

from pathlib import Path
from typing import List, Dict, Any, Iterator, Optional
import logging
import json

from ..config import PipelineConfig
from ..utils.io import Database, write_jsonl

logger = logging.getLogger(__name__)


def generate_caption(
    token: str,
    template: str,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generate a caption from template.
    
    Args:
        token: Character token
        template: Caption template with {token} placeholder
        metadata: Optional additional metadata for captioning
        
    Returns:
        Generated caption
    """
    caption = template.format(token=token)
    return caption


def build_manifest_entry(
    sample: Dict[str, Any],
    candidate: Dict[str, Any],
    video: Dict[str, Any],
    config: PipelineConfig
) -> Dict[str, Any]:
    """
    Build a single manifest entry.
    
    Args:
        sample: Rendered sample info
        candidate: Candidate clip info
        video: Source video info
        config: Pipeline configuration
        
    Returns:
        Manifest entry dictionary
    """
    # Generate caption
    caption = generate_caption(
        config.token,
        config.caption.template
    )
    
    # Build entry
    entry = {
        "token": config.token,
        "source_video": video["path"],
        "source_video_hash": video["hash"],
        "scene_start": candidate["start_time"],
        "scene_end": candidate["end_time"],
        "fps": config.render.fps,
        "frames": sample["frame_count"],
        "resolution": config.render.resolution,
        "crop_type": sample["crop_type"],
        "path": sample["output_path"],
        "caption": caption
    }
    
    return entry


def generate_manifest_entries(
    config: PipelineConfig
) -> Iterator[Dict[str, Any]]:
    """
    Generate manifest entries for all rendered samples.
    
    Args:
        config: Pipeline configuration
        
    Yields:
        Manifest entry dictionaries
    """
    db = Database(config.dsn)
    samples = db.get_samples()
    
    for sample in samples:
        # Get candidate info
        candidate = None
        for c in db.get_candidates():
            if c["id"] == sample["candidate_id"]:
                candidate = c
                break
        
        if not candidate:
            logger.warning(f"Candidate not found for sample {sample['id']}")
            continue
        
        # Get video info
        video = db.get_video_by_id(candidate["video_id"])
        if not video:
            logger.warning(f"Video not found for candidate {candidate['id']}")
            continue
        
        # Check output exists
        output_path = Path(sample["output_path"])
        if not output_path.exists():
            logger.warning(f"Output not found: {output_path}")
            continue
        
        entry = build_manifest_entry(sample, candidate, video, config)
        yield entry


def write_manifest(
    config: PipelineConfig,
    output_path: Optional[Path] = None
) -> int:
    """
    Write the manifest.jsonl file.
    
    Args:
        config: Pipeline configuration
        output_path: Optional custom output path
        
    Returns:
        Number of entries written
    """
    if output_path is None:
        output_path = config.output_dir / "manifest.jsonl"
    
    entries = generate_manifest_entries(config)
    count = write_jsonl(output_path, entries)
    
    logger.info(f"Wrote manifest with {count} entries to {output_path}")
    return count


def write_captions(
    config: PipelineConfig,
    output_dir: Optional[Path] = None
) -> int:
    """
    Write individual caption files alongside frame directories.
    
    Args:
        config: Pipeline configuration
        output_dir: Optional custom output directory
        
    Returns:
        Number of caption files written
    """
    db = Database(config.dsn)
    samples = db.get_samples()
    
    count = 0
    for sample in samples:
        sample_path = Path(sample["output_path"])
        caption_path = sample_path.parent / f"{sample_path.name}.txt"
        
        # Generate caption
        caption = generate_caption(
            config.token,
            config.caption.template
        )
        
        # Write caption file
        caption_path.write_text(caption)
        count += 1
    
    logger.info(f"Wrote {count} caption files")
    return count


def generate_statistics(config: PipelineConfig) -> Dict[str, Any]:
    """
    Generate statistics about the dataset.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        Statistics dictionary
    """
    db = Database(config.dsn)
    
    videos = db.get_all_videos()
    candidates = db.get_candidates()
    samples = db.get_samples()
    
    # Count by status
    status_counts = {}
    for c in candidates:
        status = c.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Count by crop type
    crop_counts = {}
    for s in samples:
        crop_type = s.get("crop_type", "unknown")
        crop_counts[crop_type] = crop_counts.get(crop_type, 0) + 1
    
    # Total duration
    total_video_duration = sum(v.get("duration", 0) for v in videos)
    
    # Calculate sample duration
    sample_duration = config.render.frame_count / config.render.fps
    total_sample_duration = len(samples) * sample_duration
    
    stats = {
        "videos": {
            "total": len(videos),
            "total_duration_hours": total_video_duration / 3600
        },
        "candidates": {
            "total": len(candidates),
            "by_status": status_counts
        },
        "samples": {
            "total": len(samples),
            "by_crop_type": crop_counts,
            "total_duration_minutes": total_sample_duration / 60,
            "total_frames": len(samples) * config.render.frame_count
        },
        "config": {
            "token": config.token,
            "resolution": config.render.resolution,
            "frame_count": config.render.frame_count,
            "fps": config.render.fps
        }
    }
    
    return stats


def print_statistics(config: PipelineConfig) -> None:
    """
    Print dataset statistics.
    
    Args:
        config: Pipeline configuration
    """
    stats = generate_statistics(config)
    
    print("\n" + "=" * 50)
    print("Dataset Statistics")
    print("=" * 50)
    
    print(f"\nVideos:")
    print(f"  Total indexed: {stats['videos']['total']}")
    print(f"  Total duration: {stats['videos']['total_duration_hours']:.1f} hours")
    
    print(f"\nCandidates:")
    print(f"  Total generated: {stats['candidates']['total']}")
    for status, count in stats['candidates']['by_status'].items():
        print(f"    {status}: {count}")
    
    print(f"\nSamples:")
    print(f"  Total rendered: {stats['samples']['total']}")
    for crop_type, count in stats['samples']['by_crop_type'].items():
        print(f"    {crop_type}: {count}")
    print(f"  Total duration: {stats['samples']['total_duration_minutes']:.1f} minutes")
    print(f"  Total frames: {stats['samples']['total_frames']}")
    
    print(f"\nConfiguration:")
    print(f"  Token: {stats['config']['token']}")
    print(f"  Resolution: {stats['config']['resolution']}")
    print(f"  Frame count: {stats['config']['frame_count']}")
    print(f"  FPS: {stats['config']['fps']}")
    
    print("=" * 50 + "\n")
