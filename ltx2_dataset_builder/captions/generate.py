"""
Scene captioning using Qwen3 Omni.

Generates natural language descriptions of scenes using a local VLM.
"""

import logging
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.io import Database

logger = logging.getLogger(__name__)

# Global model cache
_model = None
_processor = None


def load_qwen_model():
    """Load Qwen3 Omni model for video captioning."""
    global _model, _processor
    
    if _model is not None:
        return _model, _processor
    
    try:
        from transformers import Qwen3OmniMoeForConditionalGeneration, Qwen3OmniMoeProcessor
        import torch
        
        model_name = "Qwen/Qwen3-Omni-30B-A3B-Instruct"
        
        logger.info(f"Loading {model_name}...")
        
        _processor = Qwen3OmniMoeProcessor.from_pretrained(model_name)
        
        # Try flash_attention_2, fall back to sdpa
        try:
            _model = Qwen3OmniMoeForConditionalGeneration.from_pretrained(
                model_name,
                torch_dtype=torch.bfloat16,
                device_map="auto",
                attn_implementation="flash_attention_2"
            )
            logger.info("Using flash_attention_2")
        except Exception as e:
            logger.warning(f"Flash attention not available: {e}")
            _model = Qwen3OmniMoeForConditionalGeneration.from_pretrained(
                model_name,
                torch_dtype=torch.bfloat16,
                device_map="auto",
                attn_implementation="sdpa"
            )
            logger.info("Using sdpa attention")
        
        logger.info("Model loaded successfully")
        return _model, _processor
        
    except ImportError as e:
        logger.error(f"Missing dependencies: {e}")
        logger.error("Install with: pip install transformers==4.57.3 qwen-omni-utils accelerate flash-attn")
        raise
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        raise


def extract_scene_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    output_path: Path,
    max_width: int = 1920,
    max_height: int = 1080,
) -> bool:
    """
    Extract a video clip from a scene for captioning.

    Args:
        video_path: Path to source video file
        start_time: Scene start time
        end_time: Scene end time
        output_path: Path for output clip
        max_width: Maximum output width (default 1920 for 1080p)
        max_height: Maximum output height (default 1080 for 1080p)

    Returns:
        True if extraction succeeded
    """
    duration = end_time - start_time

    # Scale down to fit within max_width x max_height, preserving aspect ratio.
    # The \, escapes the comma so FFmpeg doesn't treat it as a filter separator.
    scale_filter = (
        f"scale=w='min(iw\\,{max_width})':h='min(ih\\,{max_height})':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )

    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",  # Force 8-bit; 10-bit HDR source segfaults torchvision
        "-c:a", "aac",
        "-ac", "2",  # Downmix to stereo; torchvision 0.25 segfaults on 7.1 (8-ch) audio
        "-y",
        str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    return result.returncode == 0 and output_path.exists()


def caption_scene_with_qwen(
    video_path: Path,
    start_time: float,
    end_time: float,
    frame_offset: int = 0,
    fps: float = 24.0,
    start_frame: Optional[int] = None,
    end_frame: Optional[int] = None,
    prompt: Optional[str] = None,
    tags: Optional[List[str]] = None,
    tag_definitions: Optional[Dict[str, str]] = None,
) -> str:
    """
    Generate a caption for a scene using Qwen3 Omni.

    Args:
        video_path: Path to video file
        start_time: Scene start time in seconds
        end_time: Scene end time in seconds
        frame_offset: Frame offset for codec timing compensation
        fps: Video frame rate
        start_frame: Scene start frame (preferred over start_time for precision)
        end_frame: Scene end frame (preferred over end_time for precision)
        tags: Optional list of scene tags to include as context
        tag_definitions: Optional mapping of tag name -> description; tags with
            descriptions are appended to the prompt so the VLM knows to identify
            those subjects by name.

    Returns:
        Generated caption string
    """
    import torch
    
    model, processor = load_qwen_model()
    
    # Derive timestamps from frame numbers if available (matches web preview logic)
    # +1 on start_frame compensates for ffmpeg fast-seek landing one frame early
    if start_frame is not None and end_frame is not None and fps > 0:
        adjusted_start = max(0.0, (start_frame + frame_offset + 1) / fps)
        adjusted_end = (end_frame + frame_offset) / fps
    else:
        time_offset = frame_offset / fps if fps > 0 else 0
        adjusted_start = max(0, start_time + time_offset)
        adjusted_end = end_time + time_offset
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Extract clip for captioning
        clip_path = Path(tmpdir) / "clip.mp4"
        
        if not extract_scene_clip(video_path, adjusted_start, adjusted_end, clip_path):
            logger.warning(f"Failed to extract clip from {video_path}")
            return ""
        
        # Build conversation for Qwen3-Omni
        caption_prompt = prompt if prompt else (
            "Describe this video scene in one detailed sentence, including both the visuals "
            "and any audio (dialogue, music, sound effects). Focus on actions, subjects, "
            "setting, and what is being said or heard."
        )

        # Append tag description suffix for tags that have defined descriptions
        described_tags = {
            tag: desc
            for tag, desc in (tag_definitions or {}).items()
            if desc and desc.strip()
        }
        if described_tags:
            lines = "\n".join(
                f"- {tag}: {desc}" for tag, desc in described_tags.items()
            )
            caption_prompt += (
                "\n\nIf any of the following subjects are identifiable in this scene, "
                "refer to them by name in your description:\n" + lines
            )

        logger.info(f"[PROMPT]\n{caption_prompt}")

        conversation = []
        if tags:
            import json
            conversation.append({
                "role": "system",
                "content": json.dumps({"tags": tags}),
            })
        conversation.append({
            "role": "user",
            "content": [
                {"type": "video", "video": str(clip_path)},
                {"type": "text", "text": caption_prompt}
            ],
        })
        
        try:
            from qwen_omni_utils import process_mm_info
            
            # Process the conversation
            text = processor.apply_chat_template(
                conversation, 
                add_generation_prompt=True, 
                tokenize=False
            )
            
            # Process multimodal info (include audio from video)
            audios, images, videos = process_mm_info(conversation, use_audio_in_video=True)
            
            inputs = processor(
                text=text,
                audio=audios,
                images=images,
                videos=videos,
                return_tensors="pt",
                padding=True,
                use_audio_in_video=True
            )
            inputs = inputs.to(model.device).to(model.dtype)
            
            # Generate caption (text only output, but use audio input)
            with torch.no_grad():
                text_ids, _ = model.generate(
                    **inputs,
                    use_audio_in_video=True,
                    max_new_tokens=150,
                    do_sample=False,
                )
            
            # Decode response
            response = processor.batch_decode(
                text_ids.sequences[:, inputs["input_ids"].shape[1]:],
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )[0].strip()

            logger.info(f"[RESPONSE]\n{response}")

            return response
            
        except Exception as e:
            logger.error(f"Captioning error: {e}")
            raise


def _pick_next_scene(db: Database, video_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    Pick the single highest-priority uncaptioned scene.

    Priority: scenes with tags first (most tags wins), then untagged scenes.
    """
    with db._connection() as conn:
        if video_id:
            row = conn.execute(
                """
                SELECT s.*,
                       COUNT(st.tag) AS tag_count
                FROM scenes s
                LEFT JOIN scene_tags st ON st.scene_id = s.id
                WHERE s.video_id = ?
                  AND (s.caption IS NULL OR s.caption = '' OR s.caption = '__empty__' OR substr(s.caption, 1, 9) = '__error__')
                GROUP BY s.id
                ORDER BY tag_count DESC, s.start_time
                LIMIT 1
                """,
                (video_id,)
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT s.*,
                       COUNT(st.tag) AS tag_count
                FROM scenes s
                LEFT JOIN scene_tags st ON st.scene_id = s.id
                WHERE s.caption IS NULL OR s.caption = '' OR s.caption = '__empty__' OR substr(s.caption, 1, 9) = '__error__'
                GROUP BY s.id
                ORDER BY tag_count DESC, s.video_id, s.start_time
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None


def caption_all_scenes(
    config: PipelineConfig,
    video_id: Optional[int] = None
) -> int:
    """
    Caption all scenes that don't have captions yet.

    Scenes are processed one at a time, re-querying the DB each iteration so
    that newly-tagged scenes are always picked up with the correct priority.
    Tagged scenes (ordered by tag count descending) are captioned before
    untagged ones.

    Args:
        config: Pipeline configuration
        video_id: Optional video ID to filter by

    Returns:
        Number of scenes captioned
    """
    db = Database(config.db_path)
    count = 0

    while True:
        scene = _pick_next_scene(db, video_id)
        if scene is None:
            break

        video = db.get_video_by_id(scene["video_id"])
        if not video:
            # Shouldn't happen, but skip to avoid infinite loop
            logger.warning(f"No video found for scene {scene['id']}, skipping")
            break

        video_path = Path(video["path"])
        fps = video.get("fps", 24.0)
        frame_offset = db.get_frame_offset(scene["video_id"])
        video_prompt = video.get("prompt") or None

        tag_count = scene.get("tag_count", 0)
        duration = scene["end_time"] - scene["start_time"]
        logger.info(
            f"Captioning scene {scene['id']} ({scene['start_time']:.1f}s-{scene['end_time']:.1f}s,"
            f" tags={tag_count}) from {video_path.stem}"
        )

        if duration > 60:
            logger.warning(f"Scene {scene['id']} is {duration:.1f}s (>60s), skipping")
            db.update_scene_caption(scene["id"], "__skip__")
            continue

        # Fetch scene tags and their descriptions/display names to pass as context
        with db._connection() as conn:
            tag_rows = conn.execute(
                """SELECT st.tag, COALESCE(td.description, '') as description,
                          COALESCE(td.display_name, '') as display_name
                   FROM scene_tags st
                   LEFT JOIN tag_definitions td ON td.tag = st.tag
                   WHERE st.scene_id = ?
                   ORDER BY st.created_at, st.tag""",
                (scene["id"],)
            ).fetchall()
        scene_tags = [r["tag"] for r in tag_rows] if tag_rows else None
        # Use display_name as the prompt key if set, otherwise fall back to tag name
        scene_tag_definitions = (
            {(r["display_name"] or r["tag"]): r["description"] for r in tag_rows if r["description"]}
            if tag_rows else None
        )

        try:
            caption = caption_scene_with_qwen(
                video_path,
                scene["start_time"],
                scene["end_time"],
                frame_offset=frame_offset,
                fps=fps,
                start_frame=scene.get("start_frame"),
                end_frame=scene.get("end_frame"),
                prompt=video_prompt,
                tags=scene_tags,
                tag_definitions=scene_tag_definitions,
            )

            if caption:
                db.update_scene_caption(scene["id"], caption)
                count += 1
                print(f"\n[Scene {scene['id']}] {scene['start_time']:.1f}s-{scene['end_time']:.1f}s")
                print(f"  {caption}")
            else:
                logger.warning(f"Empty caption for scene {scene['id']}, skipping")
                db.update_scene_caption(scene["id"], "__empty__")

        except Exception as e:
            logger.error(f"Failed to caption scene {scene['id']}: {e}")
            db.update_scene_caption(scene["id"], f"__error__: {e}")
            break

    logger.info(f"Captioned {count} scenes")
    return count
