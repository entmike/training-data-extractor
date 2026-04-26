# Database Schema

Canonical schema from `schema/schema.sql`. All tables are PostgreSQL.

---

## videos

Root entity. One row per source video file.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `path` | TEXT | UNIQUE, NOT NULL | Absolute file path |
| `hash` | TEXT | NOT NULL | File hash |
| `duration` | DOUBLE PRECISION | | |
| `fps` | DOUBLE PRECISION | | |
| `width` | INTEGER | | |
| `height` | INTEGER | | |
| `codec` | TEXT | | |
| `frame_offset` | INTEGER | NOT NULL, DEFAULT 0 | Compensates for codec timing drift |
| `prompt` | TEXT | | |
| `name` | TEXT | | |
| `indexed_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

---

## scenes

A detected scene cut within a video.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `video_id` | INTEGER | NOT NULL, FK→videos(id) | |
| `start_time` | DOUBLE PRECISION | NOT NULL | |
| `end_time` | DOUBLE PRECISION | NOT NULL | |
| `duration` | DOUBLE PRECISION | NOT NULL | |
| `start_frame` | INTEGER | | |
| `end_frame` | INTEGER | | |
| `caption` | TEXT | | |
| `caption_started_at` | TIMESTAMPTZ | | |
| `caption_finished_at` | TIMESTAMPTZ | | |
| `caption_prompt` | TEXT | | |
| `blurhash` | TEXT | | |
| `rating` | INTEGER | NOT NULL, DEFAULT 2 | |
| `bucket_ineligible` | INTEGER | NOT NULL, DEFAULT 0 | |
| `subtitles` | TEXT | | Extracted from MKV text tracks |
| **Unique** | `(video_id, start_time, end_time)` | | |

---

## scene_tags

Many-to-many: scenes ↔ character/content tags.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `scene_id` | INTEGER | NOT NULL, FK→scenes(id) ON DELETE CASCADE | |
| `tag` | TEXT | NOT NULL | |
| `confirmed` | BOOLEAN | NOT NULL, DEFAULT TRUE | TRUE=manual, FALSE=auto-detected |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| **Primary key** | `(scene_id, tag)` | | |

---

## tag_definitions

Display metadata for each tag slug.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `tag` | TEXT | PRIMARY KEY | |
| `display_name` | TEXT | NOT NULL, DEFAULT '' | |
| `description` | TEXT | NOT NULL, DEFAULT '' | |

---

## tag_references

Per-tag face embedding samples used by the auto-tagger.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `tag` | TEXT | NOT NULL | |
| `video_id` | INTEGER | FK→videos(id) ON DELETE CASCADE | |
| `frame_time` | DOUBLE PRECISION | NOT NULL | |
| `frame_number` | INTEGER | | |
| `embedding` | BYTEA | NOT NULL | |
| `embedding_type` | TEXT | NOT NULL, DEFAULT 'insightface' | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

---

## candidates

Fixed-length clip windows derived from scenes.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `video_id` | INTEGER | NOT NULL, FK→videos(id) | |
| `scene_id` | INTEGER | FK→scenes(id) | |
| `start_time` | DOUBLE PRECISION | NOT NULL | |
| `end_time` | DOUBLE PRECISION | NOT NULL | |
| `duration` | DOUBLE PRECISION | NOT NULL | |
| `quality_score` | DOUBLE PRECISION | | |
| `face_presence` | DOUBLE PRECISION | | |
| `status` | TEXT | DEFAULT 'pending' | |

---

## samples

Rendered output frames for a candidate / crop-type pair.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `candidate_id` | INTEGER | NOT NULL, FK→candidates(id) | |
| `crop_type` | TEXT | NOT NULL | |
| `output_path` | TEXT | NOT NULL | |
| `frame_count` | INTEGER | | |
| `caption` | TEXT | | |
| `rendered_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

---

## buckets

Optimal 24-frame-multiple crop windows within a scene.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `video_id` | INTEGER | NOT NULL, FK→videos(id) | |
| `scene_id` | INTEGER | FK→scenes(id) | |
| `start_time` | DOUBLE PRECISION | NOT NULL | |
| `end_time` | DOUBLE PRECISION | NOT NULL | |
| `duration` | DOUBLE PRECISION | NOT NULL | |
| `start_frame` | INTEGER | NOT NULL | |
| `end_frame` | INTEGER | NOT NULL | |
| `frame_count` | INTEGER | | |
| `speech_score` | DOUBLE PRECISION | | |
| `speech_start_frame` | INTEGER | | |
| `speech_end_frame` | INTEGER | | |
| `optimal_offset_frames` | INTEGER | | |
| `optimal_duration` | DOUBLE PRECISION | | |
| `bucket_timestamp` | TIMESTAMPTZ | DEFAULT NOW() | |
| **Unique** | `(video_id, start_frame, end_frame)` | | |

---

## face_detections

Per-frame InsightFace detections; embeddings cached to avoid re-inference.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `video_id` | INTEGER | NOT NULL, FK→videos(id) ON DELETE CASCADE | |
| `frame_number` | INTEGER | NOT NULL | |
| `bbox_area` | DOUBLE PRECISION | | |
| `pose_yaw` | DOUBLE PRECISION | | |
| `pose_pitch` | DOUBLE PRECISION | | |
| `pose_roll` | DOUBLE PRECISION | | |
| `det_score` | DOUBLE PRECISION | | |
| `age` | INTEGER | | |
| `sex` | TEXT | | |
| `embedding` | BYTEA | | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

---

## face_clusters

Unsupervised clusters of face_detections embeddings.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `video_id` | INTEGER | FK→videos(id) ON DELETE CASCADE | |
| `cluster_label` | INTEGER | NOT NULL | |
| `centroid` | BYTEA | NOT NULL | |
| `size` | INTEGER | NOT NULL | |
| `stable_key` | TEXT | | Content-addressed identity across re-clusters |
| `member_detection_ids` | INTEGER[] | NOT NULL, DEFAULT '{}' | |
| `sample_frame_numbers` | INTEGER[] | NOT NULL, DEFAULT '{}' | |
| `sample_video_ids` | INTEGER[] | NOT NULL, DEFAULT '{}' | |
| `nearest_tag` | TEXT | | |
| `nearest_sim` | DOUBLE PRECISION | | |
| `dismissed` | BOOLEAN | NOT NULL, DEFAULT FALSE | |
| `promoted_tag` | TEXT | | |
| `scene_count` | INTEGER | NOT NULL, DEFAULT 0 | |
| `scene_ids` | INTEGER[] | NOT NULL, DEFAULT '{}' | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

---

## clip_embeddings

CLIP visual embeddings per frame, used for similarity search / clustering.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `video_id` | INTEGER | NOT NULL, FK→videos(id) ON DELETE CASCADE | |
| `frame_number` | INTEGER | NOT NULL | |
| `model` | TEXT | NOT NULL, DEFAULT 'openai/clip-vit-large-patch14' | |
| `embedding` | BYTEA | NOT NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| **Unique** | `(video_id, frame_number, model)` | | |

---

## embeddings

Generic frame embeddings (used by clustering pipeline).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `video_id` | INTEGER | NOT NULL, FK→videos(id) | |
| `frame_time` | DOUBLE PRECISION | NOT NULL | |
| `embedding` | BYTEA | NOT NULL | |
| `cluster_id` | INTEGER | | |

---

## lora_files

Scanned LoRA model files from the training data directory.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `sha256` | TEXT | PRIMARY KEY | |
| `path` | TEXT | NOT NULL | |
| `rel_path` | TEXT | NOT NULL | |
| `filename` | TEXT | NOT NULL | |
| `size` | BIGINT | NOT NULL | |
| `modified` | TEXT | NOT NULL | |
| `model_name` | TEXT | | |
| `ss_output_name` | TEXT | | |
| `base_model` | TEXT | | |
| `step` | INTEGER | | |
| `epoch` | INTEGER | | |
| `software_name` | TEXT | | |
| `software_ver` | TEXT | | |
| `model_hash` | TEXT | | |
| `format` | TEXT | | |
| `indexed_at` | TIMESTAMPTZ | DEFAULT NOW() | |

---

## clips

A named collection of clip items for export.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `name` | TEXT | NOT NULL | |
| `caption_prompt` | TEXT | | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

---

## clip_items

An individual scene segment within a clip, with per-item export flags.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `clip_id` | INTEGER | NOT NULL, FK→clips(id) ON DELETE CASCADE | |
| `scene_id` | INTEGER | NOT NULL, FK→scenes(id) ON DELETE CASCADE | |
| `video_id` | INTEGER | NOT NULL | |
| `start_frame` | INTEGER | NOT NULL | |
| `end_frame` | INTEGER | NOT NULL | |
| `caption` | TEXT | DEFAULT '' | |
| `mute` | BOOLEAN | NOT NULL, DEFAULT FALSE | |
| `denoise` | BOOLEAN | NOT NULL, DEFAULT FALSE | |
| `denoise_mix` | FLOAT | NOT NULL, DEFAULT 1.0 | arnndn mix ratio 0.0–1.0 |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| **Unique** | `(clip_id, scene_id)` | | |

---

## outputs

ComfyUI (or other) generated files scanned from an output directory.
Stores file attributes and any embedded ComfyUI workflow/prompt JSON.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `path` | TEXT | UNIQUE, NOT NULL | |
| `sha256` | TEXT | NOT NULL | |
| `file_size` | BIGINT | | |
| `file_mtime` | TIMESTAMPTZ | | |
| `mime_type` | TEXT | | |
| `width` | INTEGER | | |
| `height` | INTEGER | | |
| `workflow` | JSONB | | ComfyUI workflow graph |
| `prompt` | JSONB | | ComfyUI prompt (API/queue format) |
| `indexed_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| `liked_at` | TIMESTAMPTZ | | Liked; liked items cannot be soft-deleted |
| `nsfw_at` | TIMESTAMPTZ | | NSFW-flagged; NSFW items cannot be soft-deleted |
| `deleted_at` | TIMESTAMPTZ | | Soft delete; NULL = active |

---

## config

Application key/value configuration store.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `key` | TEXT | PRIMARY KEY | |
| `value` | TEXT | NOT NULL, DEFAULT '' | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |

---

## prompt_favorites

Favorited ComfyUI prompt node inputs (by class_type + input_key).
Shown as an editable quick-access panel when viewing any prompt.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | SERIAL | PRIMARY KEY | |
| `node_id` | TEXT | NOT NULL | |
| `class_type` | TEXT | NOT NULL | |
| `input_key` | TEXT | NOT NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
| **Unique** | `(node_id, class_type, input_key)` | | |

---

## comfyui_cache

Cached responses from the ComfyUI API (object_info, models, etc.).
Refreshed on demand from the Config page.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `key` | TEXT | PRIMARY KEY | |
| `data` | JSONB | NOT NULL | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | |
