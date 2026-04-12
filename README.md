# LTX-2 Character LoRA Training Data Builder

Automated end-to-end training data extraction for LTX-2 character LoRA training from movie sources. Includes a web-based review UI for browsing, tagging, captioning, and curating scenes.

## Features

- **Automated Pipeline**: Transform movie files into high-quality training samples
- **Scene Detection**: Automatic scene boundary detection using PySceneDetect
- **VLM Captioning**: Scene and clip captioning with Qwen3-Omni
- **Speech-Aware Bucketing**: Auto-detect optimal crop windows prioritising speech content
- **Face Detection**: InsightFace-based face detection and filtering
- **Multi-Crop Views**: Generate face, half-body, and full-frame crops
- **Bucket Rendering**: 1024px resolution, 121-frame training buckets
- **Web Review UI**: Browse scenes, manage tags, curate clips, export zip datasets
- **HDR Support**: Auto tone-maps HDR (PQ/HLG) sources to SDR on export

## Requirements

- Python 3.10+
- FFmpeg (must be in PATH)
- CUDA-capable GPU (required for Qwen3-Omni captioning)
- Docker (for PostgreSQL)
- Node.js 18+ (for the UI dev server)

## Installation

```bash
git clone <repo-url>
cd training-data-extractor

# Create virtualenv and install
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Install UI dependencies
cd ui && npm install && cd ..
```

### System Dependencies

```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg docker-compose
```

## Database Setup

PostgreSQL runs in Docker:

```bash
docker compose up -d
```

Connection string: `postgresql://ltx2:ltx2@localhost:5432/ltx2`

On first run the schema is created automatically. To migrate from a SQLite backup:

```bash
python migrate_sqlite_to_pg.py
```

## Starting the Dev Environment

```bash
./restart.sh
```

This starts two persistent tmux sessions:

| Session | Command | URL |
|---------|---------|-----|
| `backend` | Flask API | http://localhost:5000 |
| `vite` | Vite dev server (hot reload) | http://localhost:5173 |

Access the UI at **http://localhost:5173**.

```bash
# Attach to logs
tmux attach -t backend
tmux attach -t vite
```

## Running the Pipeline

### Using a config file (recommended)

```bash
# Generate a default config
ltx2-build --generate-config config.yaml

# Run the full pipeline
ltx2-build --config config.yaml
```

### Running individual steps

```bash
ltx2-build --config config.yaml --step <step>
```

### Pipeline steps (in order)

| Step | Description |
|------|-------------|
| `index` | Scan `./vids`, hash files, store metadata |
| `scenes` | Detect scene cuts, write to DB incrementally |
| `captions` | Caption scenes with Qwen3-Omni VLM |
| `buckets` | Auto-detect optimal speech-prioritised crop windows |
| `candidates` | Split scenes into fixed-length clips |
| `quality` | Filter clips by quality score |
| `faces` | Filter clips by InsightFace detection |
| `crops` | Generate face / half-body / full-frame crop specs |
| `render` | Render 1024px, 121-frame PNG buckets |
| `manifest` | Write `manifest.jsonl` and caption `.txt` files |
| `stats` | Print dataset statistics |

### Useful utilities

```bash
# List indexed videos with metadata
ltx2-build --config config.yaml --list-videos

# Set frame offset for codec timing compensation
ltx2-build --config config.yaml --set-frame-offset 2 --video my-movie.mkv

# Set display name for a video
ltx2-build --config config.yaml --set-name "My Movie" --video my-movie.mkv
```

## Configuration

```yaml
source_dir: vids
output_dir: dataset
cache_dir: .cache
pg_dsn: postgresql://ltx2:ltx2@localhost:5432/ltx2
token: character_person

scene:
  min_duration: 2.0
  max_duration: 8.0
  threshold: 3.0

face:
  min_face_presence: 0.5
  min_face_size: 64
  detection_threshold: 0.5
  embedding_model: buffalo_l

render:
  resolution: 1024
  frame_count: 121
  fps: 24
  output_format: png

bucket:
  speech_weight: 0.7
  visual_weight: 0.3
  min_frames: 24
  max_frames: 144
```

## Web Review UI

The UI runs at **http://localhost:5173** (dev) or **http://localhost:5000** (production build).

### Pages

- **Videos** — Browse scenes per video, filter by tag/rating/frames, play clips
- **Clips** — Curated clip collections; export as zip with captions (HDR→SDR auto tone-mapped)
- **Tags** — Manage tags: rename, set display names and captioner descriptions, browse tagged scenes

### Exporting clips

Select a clip collection and click **Export zip**. The export streams progress in real time. HDR source videos are automatically tone-mapped to SDR using `zscale` + `tonemap=hable`. Falls back to plain encode if tone-mapping fails.

## Output Structure

```
dataset/
├── manifest.jsonl
└── samples/
    └── character_person/
        ├── clip_000001_face/
        │   ├── 000000.png
        │   └── ... (121 frames)
        ├── clip_000001_face.txt   (caption)
        ├── clip_000001_half_body/
        └── ...
```

## Key Source Files

| File | Description |
|------|-------------|
| `web_review.py` | Flask backend — API + built UI |
| `restart.sh` | Start backend + Vite in tmux |
| `docker-compose.yml` | PostgreSQL container |
| `migrate_sqlite_to_pg.py` | One-time SQLite → PostgreSQL migration |
| `config.yaml` | Active pipeline config |
| `ltx2_dataset_builder/cli.py` | Pipeline entry point |
| `ltx2_dataset_builder/utils/io.py` | `Database` class (all DB operations) |
| `ltx2_dataset_builder/captions/generate.py` | Qwen3-Omni captioning |
| `ltx2_dataset_builder/buckets/detect.py` | Speech-aware bucket detection |

## Notes

- Each pipeline step is idempotent — re-running skips already-processed items
- Scene detection flushes to DB every ~10s, so killing mid-run won't lose progress
- Sentinel caption values: `__skip__`, `__empty__`, `__error__: <msg>`
- All SQL uses `%s` placeholders (psycopg2 / PostgreSQL)
- Face embeddings use `buffalo_l`, downloaded automatically to `~/.insightface/` on first run

## License

MIT License
