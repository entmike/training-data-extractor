-- =============================================================================
-- LTX-2 Training Data Extractor — canonical PostgreSQL schema
--
-- Authoritative source of truth for all table definitions.
-- All ALTER TABLE migrations are folded in; this file produces a correct
-- fresh-install database when executed top-to-bottom.
--
-- Execution order respects FK dependencies.
-- io.py reads and executes this file, then applies ADD COLUMN IF NOT EXISTS
-- guards for columns that postdate the initial deployment of each table.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- videos
-- Root entity. One row per source video file.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS videos (
    id           SERIAL PRIMARY KEY,
    path         TEXT UNIQUE NOT NULL,
    hash         TEXT NOT NULL,
    duration     DOUBLE PRECISION,
    fps          DOUBLE PRECISION,
    width        INTEGER,
    height       INTEGER,
    codec        TEXT,
    frame_offset INTEGER          NOT NULL DEFAULT 0,  -- compensates for codec timing drift
    prompt       TEXT,
    name         TEXT,
    indexed_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- scenes
-- A detected scene cut within a video.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scenes (
    id                   SERIAL PRIMARY KEY,
    video_id             INTEGER          NOT NULL REFERENCES videos(id),
    start_time           DOUBLE PRECISION NOT NULL,
    end_time             DOUBLE PRECISION NOT NULL,
    duration             DOUBLE PRECISION NOT NULL,
    start_frame          INTEGER,
    end_frame            INTEGER,
    caption              TEXT,
    caption_started_at   TIMESTAMPTZ,
    caption_finished_at  TIMESTAMPTZ,
    caption_prompt       TEXT,
    blurhash             TEXT,
    rating               INTEGER          NOT NULL DEFAULT 2,
    bucket_ineligible    INTEGER          NOT NULL DEFAULT 0,
    subtitles            TEXT,                            -- extracted from MKV text tracks
    UNIQUE (video_id, start_time, end_time)
);


-- ---------------------------------------------------------------------------
-- scene_tags
-- Many-to-many: scenes ↔ character/content tags.
-- confirmed=TRUE  → manually assigned
-- confirmed=FALSE → auto-detected (shown as unconfirmed in UI)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scene_tags (
    scene_id   INTEGER     NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    tag        TEXT        NOT NULL,
    confirmed  BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scene_id, tag)
);


-- ---------------------------------------------------------------------------
-- tag_definitions
-- Display metadata for each tag slug.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tag_definitions (
    tag          TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT ''
);


-- ---------------------------------------------------------------------------
-- tag_references
-- Per-tag face embedding samples used by the auto-tagger.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tag_references (
    id             SERIAL PRIMARY KEY,
    tag            TEXT             NOT NULL,
    video_id       INTEGER          REFERENCES videos(id) ON DELETE CASCADE,
    frame_number   INTEGER          NOT NULL,
    frame_time     DOUBLE PRECISION NOT NULL,
    embedding      BYTEA            NOT NULL,
    embedding_type TEXT             NOT NULL DEFAULT 'insightface',
    created_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- candidates
-- Fixed-length clip windows derived from scenes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS candidates (
    id             SERIAL PRIMARY KEY,
    video_id       INTEGER          NOT NULL REFERENCES videos(id),
    scene_id       INTEGER          REFERENCES scenes(id),
    start_time     DOUBLE PRECISION NOT NULL,
    end_time       DOUBLE PRECISION NOT NULL,
    duration       DOUBLE PRECISION NOT NULL,
    quality_score  DOUBLE PRECISION,
    face_presence  DOUBLE PRECISION,
    status         TEXT             NOT NULL DEFAULT 'pending'
);


-- ---------------------------------------------------------------------------
-- samples
-- Rendered output frames for a candidate / crop-type pair.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS samples (
    id           SERIAL PRIMARY KEY,
    candidate_id INTEGER     NOT NULL REFERENCES candidates(id),
    crop_type    TEXT        NOT NULL,
    output_path  TEXT        NOT NULL,
    frame_count  INTEGER,
    caption      TEXT,
    rendered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- buckets
-- Optimal 24-frame-multiple crop windows within a scene.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS buckets (
    id                    SERIAL PRIMARY KEY,
    video_id              INTEGER          NOT NULL REFERENCES videos(id),
    scene_id              INTEGER          REFERENCES scenes(id),
    start_time            DOUBLE PRECISION NOT NULL,
    end_time              DOUBLE PRECISION NOT NULL,
    duration              DOUBLE PRECISION NOT NULL,
    start_frame           INTEGER          NOT NULL,
    end_frame             INTEGER          NOT NULL,
    frame_count           INTEGER,
    speech_score          DOUBLE PRECISION,
    speech_start_frame    INTEGER,
    speech_end_frame      INTEGER,
    optimal_offset_frames INTEGER,
    optimal_duration      DOUBLE PRECISION,
    bucket_timestamp      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    UNIQUE (video_id, start_frame, end_frame)
);


-- ---------------------------------------------------------------------------
-- face_detections
-- Per-frame InsightFace detections; embeddings cached to avoid re-inference.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS face_detections (
    id           SERIAL PRIMARY KEY,
    video_id     INTEGER          NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_number INTEGER          NOT NULL,
    bbox_area    DOUBLE PRECISION,
    pose_yaw     DOUBLE PRECISION,
    pose_pitch   DOUBLE PRECISION,
    pose_roll    DOUBLE PRECISION,
    det_score    DOUBLE PRECISION,
    age          INTEGER,
    sex          TEXT,
    embedding    BYTEA,
    created_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- face_clusters
-- Unsupervised clusters of face_detections embeddings.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS face_clusters (
    id                   SERIAL PRIMARY KEY,
    video_id             INTEGER     REFERENCES videos(id),
    cluster_label        INTEGER     NOT NULL,
    centroid             BYTEA       NOT NULL,
    size                 INTEGER     NOT NULL,
    stable_key           TEXT,                           -- content-addressed identity across re-clusters
    member_detection_ids INTEGER[]   NOT NULL DEFAULT '{}',
    sample_frame_numbers INTEGER[]   NOT NULL DEFAULT '{}',
    sample_video_ids     INTEGER[]   NOT NULL DEFAULT '{}',
    nearest_tag          TEXT,
    nearest_sim          DOUBLE PRECISION,
    dismissed            BOOLEAN     NOT NULL DEFAULT FALSE,
    promoted_tag         TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- clip_embeddings
-- CLIP visual embeddings per frame, used for similarity search / clustering.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clip_embeddings (
    id           SERIAL PRIMARY KEY,
    video_id     INTEGER     NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_number INTEGER     NOT NULL,
    model        TEXT        NOT NULL DEFAULT 'openai/clip-vit-large-patch14',
    embedding    BYTEA       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (video_id, frame_number, model)
);


-- ---------------------------------------------------------------------------
-- embeddings
-- Generic frame embeddings (used by clustering pipeline).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embeddings (
    id         SERIAL PRIMARY KEY,
    video_id   INTEGER          NOT NULL REFERENCES videos(id),
    frame_time DOUBLE PRECISION NOT NULL,
    embedding  BYTEA            NOT NULL,
    cluster_id INTEGER
);


-- ---------------------------------------------------------------------------
-- clips
-- A named collection of clip items for export.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clips (
    id             SERIAL PRIMARY KEY,
    name           TEXT        NOT NULL,
    caption_prompt TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ---------------------------------------------------------------------------
-- clip_items
-- An individual scene segment within a clip, with per-item export flags.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clip_items (
    id          SERIAL PRIMARY KEY,
    clip_id     INTEGER     NOT NULL REFERENCES clips(id)  ON DELETE CASCADE,
    scene_id    INTEGER     NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    video_id    INTEGER     NOT NULL,
    start_frame INTEGER     NOT NULL,
    end_frame   INTEGER     NOT NULL,
    caption     TEXT                 DEFAULT '',
    mute        BOOLEAN     NOT NULL DEFAULT FALSE,
    denoise     BOOLEAN     NOT NULL DEFAULT FALSE,
    denoise_mix FLOAT       NOT NULL DEFAULT 1.0,   -- arnndn mix ratio 0.0–1.0
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (clip_id, scene_id)
);
