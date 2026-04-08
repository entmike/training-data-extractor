"""
Scene captioning using Qwen3 Omni.

Generates natural language descriptions of scenes using a local VLM.
"""

import logging
import subprocess
import tempfile
import os
import threading
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from tqdm import tqdm

from ..config import PipelineConfig
from ..utils.io import Database

logger = logging.getLogger(__name__)

# Global model cache
_model = None
_processor = None


def load_qwen_model(suppress_warnings: bool = True):
    """Load Qwen3 Omni model for video captioning."""
    global _model, _processor

    if _model is not None:
        return _model, _processor

    try:
        import transformers
        import torch
        from transformers import Qwen3OmniMoeForConditionalGeneration, Qwen3OmniMoeProcessor

        if suppress_warnings:
            warnings.filterwarnings("ignore")
            transformers.logging.set_verbosity_error()

        model_name = "Qwen/Qwen3-Omni-30B-A3B-Instruct"

        logger.info(f"Loading {model_name}...")
        
        _processor = Qwen3OmniMoeProcessor.from_pretrained(model_name)

        # Try flash_attention_2, fall back to sdpa
        try:
            _model = Qwen3OmniMoeForConditionalGeneration.from_pretrained(
                model_name,
                dtype=torch.bfloat16,
                device_map="auto",
                attn_implementation="flash_attention_2"
            )
            logger.info("Using flash_attention_2")
        except Exception as e:
            logger.warning(f"Flash attention not available: {e}")
            _model = Qwen3OmniMoeForConditionalGeneration.from_pretrained(
                model_name,
                dtype=torch.bfloat16,
                device_map="auto",
                attn_implementation="sdpa"
            )
            logger.info("Using sdpa attention")

        _model.tie_weights()
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


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _build_caption_prompt(
    video_prompt: Optional[str],
    tag_definitions: Optional[Dict[str, str]],
) -> str:
    """Build the full prompt string that will be (or was) sent to Qwen."""
    caption_prompt = (video_prompt.strip() if video_prompt else None) or (
        """
        # Instructions
        
        - Describe this video scene in 2 or 3 detailed sentences, including both the visuals and any audio (dialogue, music, sound effects). Focus on actions, subjects, setting, and what is being said or heard.
        - Do not provide subjective commentary, only what you see.  Also caption any spoken dialogue verbatim.  If no dialogue is present, then do not mention any lack of dialogue.
        - Identify any notable subjects by their name given in the details.  Do not include their identifying information or features when refering to them, only their name.  If no notable subjects are present, then do not mention any lack of notable subjects.
        - If the scene is silent, just describe the visuals.
        - If the scene is blurry or dark, do your best to describe what you can make out, but note the poor quality in your caption.
        - If the scene contains text (e.g. a sign, menu, or caption), include that text in your description if it's legible
        """
    )
    if tag_definitions:
        lines = "\n".join(
            f"- {name}: {desc}" if desc and desc.strip() else f"- {name}"
            for name, desc in tag_definitions.items()
        )
        caption_prompt += (
            "\n\nNotable Subjects:\n" + lines
        )
    return caption_prompt


def prepare_scene_inputs(
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
):
    """
    CPU-bound preparation: extract clip with FFmpeg, decode frames/audio,
    tokenize. Returns (inputs_dict, tmpdir, caption_prompt) where tmpdir must
    be kept alive until inference is done.

    Runs on CPU so it can overlap with GPU inference for the previous scene.
    """
    import json
    from qwen_omni_utils import process_mm_info

    _, processor = load_qwen_model()

    if start_frame is not None and end_frame is not None and fps > 0:
        adjusted_start = max(0.0, (start_frame + frame_offset + 1) / fps)
        adjusted_end = (end_frame + frame_offset) / fps
    else:
        time_offset = frame_offset / fps if fps > 0 else 0
        adjusted_start = max(0, start_time + time_offset)
        adjusted_end = end_time + time_offset

    caption_prompt = _build_caption_prompt(prompt, tag_definitions)

    tmpdir = tempfile.TemporaryDirectory()
    clip_path = Path(tmpdir.name) / "clip.mp4"

    if not extract_scene_clip(video_path, adjusted_start, adjusted_end, clip_path):
        tmpdir.cleanup()
        raise RuntimeError(f"Failed to extract clip from {video_path}")

    conversation = []
    if tags:
        conversation.append({
            "role": "system",
            "content": json.dumps({"tags": tags}),
        })
    conversation.append({
        "role": "user",
        "content": [
            {"type": "video", "video": str(clip_path)},
            {"type": "text", "text": caption_prompt},
        ],
    })

    text = processor.apply_chat_template(
        conversation, add_generation_prompt=True, tokenize=False
    )
    audios, images, videos = process_mm_info(conversation, use_audio_in_video=True)
    inputs = processor(
        text=text,
        audio=audios,
        images=images,
        videos=videos,
        return_tensors="pt",
        padding=True,
        use_audio_in_video=True,
    )

    return inputs, tmpdir, caption_prompt


def run_scene_inference(inputs) -> str:
    """
    GPU-bound inference step. Takes pre-prepared inputs, returns caption string.
    """
    import torch

    model, processor = load_qwen_model()
    inputs_gpu = inputs.to(model.device).to(model.dtype)

    with torch.no_grad():
        text_ids, _ = model.generate(
            **inputs_gpu,
            use_audio_in_video=True,
            max_new_tokens=150,
            do_sample=False,
        )

    response = processor.batch_decode(
        text_ids.sequences[:, inputs_gpu["input_ids"].shape[1]:],
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()

    del inputs_gpu
    torch.cuda.empty_cache()

    logger.info(f"[RESPONSE]\n{response}")
    return response


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
) -> Tuple[str, str]:
    """
    Convenience wrapper: prepare inputs then run inference.
    Used when pipelining is not in effect.
    """
    inputs, tmpdir, caption_prompt = prepare_scene_inputs(
        video_path, start_time, end_time,
        frame_offset=frame_offset, fps=fps,
        start_frame=start_frame, end_frame=end_frame,
        prompt=prompt, tags=tags, tag_definitions=tag_definitions,
    )
    try:
        response = run_scene_inference(inputs)
    finally:
        tmpdir.cleanup()
    return response, caption_prompt


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


def _retrofit_caption_metadata(db: Database) -> None:
    """
    For scenes that have a real caption but no caption_started_at, backfill
    caption_prompt (reconstructed) and set both timestamps to now.
    """
    with db._connection() as conn:
        rows = conn.execute(
            """SELECT s.id, s.video_id, s.start_time, s.end_time,
                      s.start_frame, s.end_frame,
                      v.prompt as video_prompt, v.fps
               FROM scenes s
               JOIN videos v ON v.id = s.video_id
               WHERE s.caption IS NOT NULL
                 AND s.caption != ''
                 AND substr(s.caption, 1, 2) != '__'
                 AND s.caption_started_at IS NULL"""
        ).fetchall()

    if not rows:
        return

    logger.info(f"Retrofitting caption metadata for {len(rows)} existing scenes...")
    now = _now_utc()

    for row in rows:
        scene_id = row["id"]
        with db._connection() as conn:
            tag_rows = conn.execute(
                """SELECT st.tag,
                          COALESCE(td.description, '') as description,
                          COALESCE(td.display_name, '') as display_name
                   FROM scene_tags st
                   LEFT JOIN tag_definitions td ON td.tag = st.tag
                   WHERE st.scene_id = ?
                   ORDER BY st.created_at, st.tag""",
                (scene_id,)
            ).fetchall()

        tag_definitions = (
            {(r["display_name"] or r["tag"]): r["description"] for r in tag_rows if r["description"]}
            if tag_rows else None
        )
        prompt = _build_caption_prompt(row["video_prompt"] or None, tag_definitions)

        with db._connection() as conn:
            conn.execute(
                """UPDATE scenes
                   SET caption_started_at = ?,
                       caption_finished_at = ?,
                       caption_prompt = ?
                   WHERE id = ?""",
                (now, now, prompt, scene_id)
            )
            conn.commit()

    logger.info("Retrofit complete.")


def _get_scene_prep_args(db: Database, scene: Dict[str, Any]):
    """Gather everything needed to call prepare_scene_inputs for a scene."""
    video = db.get_video_by_id(scene["video_id"])
    if not video:
        return None
    video_path = Path(video["path"])
    fps = video.get("fps", 24.0)
    frame_offset = db.get_frame_offset(scene["video_id"])
    video_prompt = video.get("prompt") or None
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
    scene_tags = [r["display_name"] or r["tag"] for r in tag_rows] if tag_rows else None
    scene_tag_definitions = (
        {(r["display_name"] or r["tag"]): r["description"] for r in tag_rows if r["description"]}
        if tag_rows else None
    )
    return dict(
        video_path=video_path,
        start_time=scene["start_time"],
        end_time=scene["end_time"],
        frame_offset=frame_offset,
        fps=fps,
        start_frame=scene.get("start_frame"),
        end_frame=scene.get("end_frame"),
        prompt=video_prompt,
        tags=scene_tags,
        tag_definitions=scene_tag_definitions,
    )


def _pick_next_clip_item(db: Database) -> Optional[Dict[str, Any]]:
    """
    Pick the next clip item whose caption is empty.
    Items that already have a real caption, or that are marked __skip__/__error__,
    are skipped.
    """
    with db._connection() as conn:
        row = conn.execute(
            """
            SELECT ci.id, ci.scene_id, ci.video_id, ci.start_frame, ci.end_frame,
                   s.start_time, s.end_time,
                   COUNT(st.tag) AS tag_count,
                   c.caption_prompt AS clip_caption_prompt
            FROM clip_items ci
            JOIN scenes s ON s.id = ci.scene_id
            JOIN clips c ON c.id = ci.clip_id
            LEFT JOIN scene_tags st ON st.scene_id = ci.scene_id
            WHERE ci.caption IS NULL OR ci.caption = ''
            GROUP BY ci.id
            ORDER BY tag_count DESC, ci.created_at
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None


def _pick_next_work_item(db: Database, video_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    Pick the next item to caption, prioritising clip items over scenes.
    Returns a dict with an added 'work_type' key: 'clip_item' or 'scene'.
    """
    item = _pick_next_clip_item(db)
    if item:
        return {**item, "work_type": "clip_item"}
    scene = _pick_next_scene(db, video_id)
    if scene:
        return {**scene, "work_type": "scene"}
    return None


def _get_clip_item_prep_args(db: Database, item: Dict[str, Any]):
    """
    Gather everything needed to call prepare_scene_inputs for a clip item.
    Uses the item's own start_frame/end_frame (not the full scene range) so the
    clip sent to Qwen matches the specific clip range.
    """
    video = db.get_video_by_id(item["video_id"])
    if not video:
        return None
    video_path = Path(video["path"])
    fps = video.get("fps", 24.0)
    frame_offset = db.get_frame_offset(item["video_id"])
    # Prompt resolution: clip override → video prompt → system default (None)
    raw_prompt = (
        item.get("clip_caption_prompt") or
        video.get("prompt") or
        None
    )
    video_prompt = raw_prompt
    scene_id = item["scene_id"]
    with db._connection() as conn:
        tag_rows = conn.execute(
            """SELECT st.tag, COALESCE(td.description, '') as description,
                      COALESCE(td.display_name, '') as display_name
               FROM scene_tags st
               LEFT JOIN tag_definitions td ON td.tag = st.tag
               WHERE st.scene_id = ?
               ORDER BY st.created_at, st.tag""",
            (scene_id,)
        ).fetchall()
    scene_tags = [r["display_name"] or r["tag"] for r in tag_rows] if tag_rows else None
    scene_tag_definitions = (
        {(r["display_name"] or r["tag"]): r["description"] for r in tag_rows if r["description"]}
        if tag_rows else None
    )
    return dict(
        video_path=video_path,
        start_time=item["start_time"],
        end_time=item["end_time"],
        frame_offset=frame_offset,
        fps=fps,
        start_frame=item["start_frame"],   # clip item's specific clip range
        end_frame=item["end_frame"],
        prompt=video_prompt,
        tags=scene_tags,
        tag_definitions=scene_tag_definitions,
    )


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

    Preprocessing (FFmpeg extraction, frame/audio decoding, tokenisation) runs
    in a background thread overlapping with GPU inference for the previous scene,
    eliminating the CPU idle gap between scenes.

    Args:
        config: Pipeline configuration
        video_id: Optional video ID to filter by

    Returns:
        Number of scenes captioned
    """
    db = Database(config.db_path)
    _retrofit_caption_metadata(db)
    count = 0

    # Prefetch state: background thread preparing next item's inputs
    prefetch_result: Dict[str, Any] = {}
    prefetch_thread = None

    def _item_duration(work_item: Dict[str, Any]) -> float:
        if work_item["work_type"] == "clip_item":
            fps_val = (db.get_video_by_id(work_item["video_id"]) or {}).get("fps", 24.0) or 24.0
            return (work_item["end_frame"] - work_item["start_frame"]) / fps_val
        return work_item["end_time"] - work_item["start_time"]

    def _get_prep_args(work_item: Dict[str, Any]):
        if work_item["work_type"] == "clip_item":
            return _get_clip_item_prep_args(db, work_item)
        return _get_scene_prep_args(db, work_item)

    def _save_caption(work_item: Dict[str, Any], caption: str,
                      started_at: Optional[str] = None, finished_at: Optional[str] = None,
                      prompt: Optional[str] = None) -> None:
        if work_item["work_type"] == "clip_item":
            db.update_clip_item_caption(work_item["id"], caption)
        else:
            db.update_scene_caption(
                work_item["id"], caption,
                started_at=started_at, finished_at=finished_at, prompt=prompt
            )

    def _log_label(work_item: Dict[str, Any]) -> str:
        if work_item["work_type"] == "clip_item":
            return (f"clip item {work_item['id']} "
                    f"(scene {work_item['scene_id']}, "
                    f"frames {work_item['start_frame']}-{work_item['end_frame']})")
        video = db.get_video_by_id(work_item["video_id"]) or {}
        stem = Path(video.get("path", "?")).stem
        return (f"scene {work_item['id']} "
                f"({work_item['start_time']:.1f}s-{work_item['end_time']:.1f}s, "
                f"tags={work_item.get('tag_count', 0)}) from {stem}")

    def _launch_prefetch(work_item: Dict[str, Any]):
        """Start background prep for work_item; result lands in prefetch_result."""
        prefetch_result.clear()
        args = _get_prep_args(work_item)
        if args is None:
            prefetch_result["error"] = RuntimeError(f"No video for {_log_label(work_item)}")
            return
        if _item_duration(work_item) > 60:
            prefetch_result["skip"] = True
            return

        def _run():
            try:
                inputs, tmpdir, prompt = prepare_scene_inputs(**args)
                prefetch_result["inputs"] = inputs
                prefetch_result["tmpdir"] = tmpdir
                prefetch_result["prompt"] = prompt
            except Exception as exc:
                prefetch_result["error"] = exc

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    # Bootstrap: clip items have priority over scenes
    work_item = _pick_next_work_item(db, video_id)
    if work_item is None:
        logger.info("Nothing to caption")
        return 0

    prefetch_thread = _launch_prefetch(work_item)

    while True:
        duration = _item_duration(work_item)
        logger.info(f"Captioning {_log_label(work_item)}")

        if duration > 60:
            logger.warning(f"{_log_label(work_item)} is {duration:.1f}s (>60s), skipping")
            _save_caption(work_item, "__skip__")
            work_item = _pick_next_work_item(db, video_id)
            if work_item is None:
                break
            prefetch_thread = _launch_prefetch(work_item)
            continue

        if prefetch_thread is not None:
            prefetch_thread.join()

        if "error" in prefetch_result:
            logger.error(f"Prefetch failed for {_log_label(work_item)}: {prefetch_result['error']}")
            _save_caption(work_item, f"__error__: {prefetch_result['error']}",
                          started_at=_now_utc(), finished_at=_now_utc())
            break

        inputs      = prefetch_result["inputs"]
        tmpdir      = prefetch_result["tmpdir"]
        prompt_used = prefetch_result["prompt"]
        started_at  = _now_utc()

        try:
            caption = run_scene_inference(inputs)
            finished_at = _now_utc()
        except Exception as e:
            logger.error(f"Failed to caption {_log_label(work_item)}: {e}")
            _save_caption(work_item, f"__error__: {e}",
                          started_at=started_at, finished_at=_now_utc())
            tmpdir.cleanup()
            break
        finally:
            tmpdir.cleanup()

        if caption:
            _save_caption(work_item, caption,
                          started_at=started_at, finished_at=finished_at, prompt=prompt_used)
            count += 1
            wt = work_item["work_type"]
            if wt == "clip_item":
                print(f"\n[Collection item {work_item['id']} / scene {work_item['scene_id']}]"
                      f" frames {work_item['start_frame']}-{work_item['end_frame']}")
            else:
                print(f"\n[Scene {work_item['id']}]"
                      f" {work_item['start_time']:.1f}s-{work_item['end_time']:.1f}s")
            print(f"  {caption}")
        else:
            logger.warning(f"Empty caption for {_log_label(work_item)}")
            _save_caption(work_item, "__empty__",
                          started_at=started_at, finished_at=_now_utc(), prompt=prompt_used)

        work_item = _pick_next_work_item(db, video_id)
        if work_item is None:
            break
        prefetch_thread = _launch_prefetch(work_item)

    logger.info(f"Captioned {count} items")
    return count
