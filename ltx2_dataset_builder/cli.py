"""
Command-line interface for LTX-2 Dataset Builder.

Usage:
    ltx2-build --token <character_token> --source <path>
    ltx2-build --config <config.yaml>
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import PipelineConfig
from .ingestion.index_videos import index_videos, get_indexed_videos
from .scenes.detect import detect_all_scenes
from .captions.generate import caption_all_scenes
from .candidates.generate import generate_all_candidates
from .faces.detect import filter_candidates_by_face
from .crops.generate import generate_all_crops
from .render.bucket import render_all_crops
from .manifest.writer import write_manifest, write_captions, print_statistics


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Reduce noise from other libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


def run_pipeline(config: PipelineConfig) -> None:
    """
    Run the full dataset generation pipeline.
    
    Args:
        config: Pipeline configuration
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Starting LTX-2 Dataset Builder")
    logger.info(f"Token: {config.token}")
    logger.info(f"Source: {config.source_dir}")
    logger.info(f"Output: {config.output_dir}")
    
    # Ensure directories exist
    config.ensure_dirs()
    
    # Step 1: Index videos
    logger.info("=" * 50)
    logger.info("Step 1: Indexing videos")
    logger.info("=" * 50)
    videos = index_videos(config)
    
    if not videos:
        logger.error("No videos found. Exiting.")
        return
    
    # Step 2: Detect scenes
    logger.info("=" * 50)
    logger.info("Step 2: Detecting scenes")
    logger.info("=" * 50)
    scenes = detect_all_scenes(config)
    
    # Step 3: Caption scenes
    logger.info("=" * 50)
    logger.info("Step 3: Captioning scenes with Qwen3")
    logger.info("=" * 50)
    caption_all_scenes(config)
    
    # Step 4: Generate candidates
    logger.info("=" * 50)
    logger.info("Step 4: Generating candidate clips")
    logger.info("=" * 50)
    candidates = generate_all_candidates(config)
    
    if not candidates:
        logger.error("No candidate clips generated. Exiting.")
        return

    # Step 5: Quality filtering
    logger.info("=" * 50)
    logger.info("Step 5: Quality filtering")
    logger.info("=" * 50)
    from .quality.score import filter_candidates_by_quality
    candidates = filter_candidates_by_quality(config)

    if not candidates:
        logger.error("No clips passed quality filtering. Exiting.")
        return

    # Step 6: Face filtering
    logger.info("=" * 50)
    logger.info("Step 6: Face detection and filtering")
    logger.info("=" * 50)
    accepted = filter_candidates_by_face(config)
    
    if not accepted:
        logger.error("No clips passed face filtering. Exiting.")
        return
    
    # Step 6: Generate crops
    logger.info("=" * 50)
    logger.info("Step 6: Generating crop specifications")
    logger.info("=" * 50)
    crops = generate_all_crops(config, accepted)

    # Step 7: Render buckets
    logger.info("=" * 50)
    logger.info("Step 7: Rendering buckets")
    logger.info("=" * 50)
    rendered = render_all_crops(config, crops)

    # Step 8: Generate manifest
    logger.info("=" * 50)
    logger.info("Step 8: Generating manifest")
    logger.info("=" * 50)
    write_manifest(config)
    write_captions(config)
    
    # Print statistics
    print_statistics(config)
    
    logger.info("Pipeline completed successfully!")


def run_step(config: PipelineConfig, step: str) -> None:
    """
    Run a single pipeline step.
    
    Args:
        config: Pipeline configuration
        step: Step name to run
    """
    logger = logging.getLogger(__name__)
    config.ensure_dirs()
    
    if step == "index":
        logger.info("Running: Index videos")
        index_videos(config)
        
    elif step == "scenes":
        logger.info("Running: Detect scenes")
        detect_all_scenes(config)
        
    elif step == "captions":
        logger.info("Running: Caption scenes with Qwen3")
        caption_all_scenes(config)
        
    elif step == "candidates":
        logger.info("Running: Generate candidates")
        generate_all_candidates(config)

    elif step == "quality":
        from .quality.score import filter_candidates_by_quality
        logger.info("Running: Quality filtering")
        filter_candidates_by_quality(config)

    elif step == "faces":
        logger.info("Running: Face filtering")
        filter_candidates_by_face(config)
        
    elif step == "crops":
        logger.info("Running: Generate crops")
        generate_all_crops(config)
        
    elif step == "render":
        logger.info("Running: Render buckets")
        render_all_crops(config)
        
    elif step == "manifest":
        logger.info("Running: Generate manifest")
        write_manifest(config)
        write_captions(config)
        
    elif step == "stats":
        print_statistics(config)
    
    elif step == "blurhash":
        from .scenes.blurhash import compute_all_blurhashes
        logger.info("Running: Compute scene blurhashes")
        compute_all_blurhashes(config)

    elif step == "debug-scenes":
        from .utils.debug import generate_scene_previews
        logger.info("Running: Generate scene preview images")
        generate_scene_previews(config)
    
    elif step == "debug-candidates":
        from .utils.debug import generate_candidate_previews
        logger.info("Running: Generate candidate preview images")
        generate_candidate_previews(config)
        
    else:
        logger.error(f"Unknown step: {step}")
        logger.info("Available steps: index, scenes, captions, blurhash, candidates, quality, faces, crops, render, manifest, stats, debug-scenes, debug-candidates")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LTX-2 Character LoRA Training Data Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline
  ltx2-build --token austin_powers_person --source /mnt/nas/movies

  # Use config file
  ltx2-build --config config.yaml

  # Run single step
  ltx2-build --config config.yaml --step render

  # Generate default config
  ltx2-build --generate-config config.yaml
        """
    )
    
    # Basic options
    parser.add_argument(
        "--token",
        type=str,
        help="Character token for training (e.g., austin_powers_person)"
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Source directory containing video files"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./dataset",
        help="Output directory for dataset (default: ./dataset)"
    )
    
    # Config file
    parser.add_argument(
        "--config",
        type=str,
        help="Path to YAML configuration file"
    )
    parser.add_argument(
        "--generate-config",
        type=str,
        metavar="PATH",
        help="Generate a default configuration file"
    )
    
    # Pipeline control
    parser.add_argument(
        "--step",
        type=str,
        choices=["index", "scenes", "captions", "blurhash", "candidates", "quality", "faces", "crops", "render", "manifest", "stats", "debug-scenes", "debug-candidates"],
        help="Run a specific pipeline step"
    )
    
    # Processing options
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)"
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Don't skip already processed clips"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    # Render options
    parser.add_argument(
        "--resolution",
        type=int,
        default=1024,
        help="Output resolution (default: 1024)"
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=121,
        help="Frame count per bucket (default: 121)"
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=24,
        help="Output FPS (default: 24)"
    )
    
    # Frame offset utility
    parser.add_argument(
        "--set-frame-offset",
        type=int,
        metavar="OFFSET",
        help="Set frame offset for a video (use with --video)"
    )
    parser.add_argument(
        "--video",
        type=str,
        help="Video filename or ID (for use with --set-frame-offset)"
    )
    parser.add_argument(
        "--list-videos",
        action="store_true",
        help="List all indexed videos with their frame offsets"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # Generate config mode
    if args.generate_config:
        config = PipelineConfig()
        config.to_yaml(Path(args.generate_config))
        logger.info(f"Generated default config: {args.generate_config}")
        return 0
    
    # List videos mode
    if args.list_videos:
        from .utils.io import Database
        db_path = Path(".cache/index.db")
        if not db_path.exists():
            logger.error("No database found. Run --step index first.")
            return 1
        db = Database(db_path)
        videos = db.get_all_videos()
        if not videos:
            logger.info("No videos indexed.")
            return 0
        with db._connection() as conn:
            for v in videos:
                scene_count = conn.execute(
                    "SELECT COUNT(*) as n FROM scenes WHERE video_id = ?", (v["id"],)
                ).fetchone()["n"]
                captioned = conn.execute(
                    "SELECT COUNT(*) as n FROM scenes WHERE video_id = ? AND caption IS NOT NULL AND caption != '' AND substr(caption, 1, 2) != '__'",
                    (v["id"],)
                ).fetchone()["n"]
                duration_str = f"{int(v['duration'] // 60)}m{int(v['duration'] % 60)}s" if v.get("duration") else "?"
                res_str = f"{v['width']}x{v['height']}" if v.get("width") else "?"
                fps_str = f"{v['fps']:.3f}" if v.get("fps") else "?"
                offset = v.get("frame_offset") or 0
                prompt_str = (v["prompt"][:60] + "…") if v.get("prompt") and len(v["prompt"]) > 60 else (v.get("prompt") or "")
                print(f"\n[{v['id']}] {Path(v['path']).name}")
                print(f"  path:     {v['path']}")
                print(f"  hash:     {v['hash']}")
                print(f"  duration: {duration_str}  fps: {fps_str}  res: {res_str}  codec: {v.get('codec', '?')}")
                print(f"  offset:   {offset}")
                print(f"  scenes:   {scene_count} total, {captioned} captioned")
                print(f"  indexed:  {v.get('indexed_at', '?')}")
                if prompt_str:
                    print(f"  prompt:   {prompt_str}")
        print()
        return 0
    
    # Set frame offset mode
    if args.set_frame_offset is not None:
        from .utils.io import Database
        if not args.video:
            parser.error("--set-frame-offset requires --video")
        db_path = Path(".cache/index.db")
        if not db_path.exists():
            logger.error("No database found. Run --step index first.")
            return 1
        db = Database(db_path)
        
        # Find video by ID or name
        videos = db.get_all_videos()
        video_id = None
        try:
            video_id = int(args.video)
        except ValueError:
            for v in videos:
                if args.video in v["path"]:
                    video_id = v["id"]
                    break
        
        if video_id is None:
            logger.error(f"Video not found: {args.video}")
            return 1
        
        db.set_frame_offset(video_id, args.set_frame_offset)
        logger.info(f"Set frame_offset={args.set_frame_offset} for video ID {video_id}")
        return 0
    
    # Load or create config
    if args.config:
        config = PipelineConfig.from_yaml(Path(args.config))
    else:
        config = PipelineConfig()
    
    # Override with CLI arguments
    if args.token:
        config.token = args.token
    if args.source:
        config.source_dir = Path(args.source)
    if args.output:
        config.output_dir = Path(args.output)
    if args.workers:
        config.num_workers = args.workers
    if args.no_skip_existing:
        config.skip_existing = False
    if args.verbose:
        config.verbose = True
    if args.resolution:
        config.render.resolution = args.resolution
    if args.frames:
        config.render.frame_count = args.frames
    if args.fps:
        config.render.fps = args.fps
    
    # Validate required options for full pipeline
    if not args.step and not args.token:
        parser.error("--token is required for full pipeline run")
    
    if not args.step and not config.source_dir.exists():
        parser.error(f"Source directory does not exist: {config.source_dir}")
    
    try:
        if args.step:
            run_step(config, args.step)
        else:
            run_pipeline(config)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 1
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
