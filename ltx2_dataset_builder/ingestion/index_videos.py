"""
Video indexing and metadata extraction.

Recursively scans folders for video files and extracts metadata.
"""

from pathlib import Path
from typing import List, Optional, Generator
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.ffmpeg import get_video_metadata
from ..utils.hashing import compute_file_hash
from ..utils.io import Database

logger = logging.getLogger(__name__)


def find_videos(
    source_dir: Path,
    extensions: List[str]
) -> Generator[Path, None, None]:
    """
    Recursively find video files in a directory.
    
    Args:
        source_dir: Root directory to scan
        extensions: List of video file extensions (e.g., ['.mkv', '.mp4'])
        
    Yields:
        Paths to video files
    """
    for ext in extensions:
        for video_path in source_dir.rglob(f"*{ext}"):
            yield video_path


def index_single_video(
    video_path: Path,
    db: Database
) -> Optional[dict]:
    """
    Index a single video file.
    
    Args:
        video_path: Path to the video file
        db: Database instance
        
    Returns:
        Video metadata dict or None if failed
    """
    try:
        # Check if already indexed
        existing = db.get_video(str(video_path))
        if existing:
            logger.debug(f"Video already indexed: {video_path}")
            return existing
        
        # Extract metadata
        logger.info(f"Indexing: {video_path}")
        metadata = get_video_metadata(video_path)
        
        # Compute hash
        logger.debug(f"Computing hash for: {video_path}")
        file_hash = compute_file_hash(video_path)
        
        # Store in database
        video_id = db.add_video(str(video_path), file_hash, metadata)
        
        result = {
            "id": video_id,
            "path": str(video_path),
            "hash": file_hash,
            **metadata
        }
        
        logger.info(f"Indexed: {video_path.name} ({metadata['duration']:.1f}s, {metadata['width']}x{metadata['height']})")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to index {video_path}: {e}")
        return None


def index_videos(config: PipelineConfig) -> List[dict]:
    """
    Index all videos in the source directory.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        List of indexed video metadata
    """
    config.ensure_dirs()
    db = Database(config.dsn)
    
    # Find all video files
    video_paths = list(find_videos(config.source_dir, config.video_extensions))
    logger.info(f"Found {len(video_paths)} video files in {config.source_dir}")
    
    if not video_paths:
        logger.warning(f"No video files found in {config.source_dir}")
        return []
    
    # Index videos (with parallel hashing)
    results = []
    
    with ThreadPoolExecutor(max_workers=config.num_workers) as executor:
        futures = {
            executor.submit(index_single_video, path, db): path 
            for path in video_paths
        }
        
        with tqdm(total=len(video_paths), desc="Indexing videos") as pbar:
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)
                pbar.update(1)
    
    logger.info(f"Successfully indexed {len(results)}/{len(video_paths)} videos")
    return results


def get_indexed_videos(config: PipelineConfig) -> List[dict]:
    """
    Get all indexed videos from the database.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        List of video metadata
    """
    db = Database(config.dsn)
    return db.get_all_videos()
