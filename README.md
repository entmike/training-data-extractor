# LTX-2 Character LoRA Training Data Builder

Automated end-to-end training data extraction for LTX-2 character LoRA training using movie sources.

## Features

- **Automated Pipeline**: Transform movie files into high-quality training samples
- **Scene Detection**: Automatic scene boundary detection using PySceneDetect
- **Face Detection**: InsightFace-based face detection and identity clustering
- **Multi-Crop Views**: Generate face, half-body, and full-frame crops
- **Bucket Rendering**: Output 1024 resolution, 121-frame training buckets
- **Deterministic**: Same input + config = identical output
- **Caching**: Avoid recomputation of expensive operations

## Installation

### Prerequisites

- Python 3.9+
- FFmpeg (must be in PATH)
- CUDA-capable GPU (recommended)

### Install from source

```bash
# Clone the repository
git clone <repo-url>
cd ltx2-dataset-builder

# Install the package
pip install -e .

# Or install with development dependencies
pip install -e ".[dev]"

# For CPU-only (no GPU):
pip install -e ".[cpu]"
```

### System Dependencies

Install FFmpeg if not already present:

```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Or download from https://ffmpeg.org/download.html
```

## Quick Start

### Basic Usage

```bash
# Run full pipeline
ltx2-build --token austin_powers_person --source /mnt/nas/movies

# Specify output directory
ltx2-build --token austin_powers_person --source /mnt/nas/movies --output ./dataset
```

### Using Configuration File

```bash
# Generate default config
ltx2-build --generate-config config.yaml

# Edit config.yaml as needed, then run
ltx2-build --config config.yaml
```

### Running Individual Steps

```bash
# Index videos only
ltx2-build --config config.yaml --step index

# Detect scenes
ltx2-build --config config.yaml --step scenes

# Show statistics
ltx2-build --config config.yaml --step stats
```

## Pipeline Steps

1. **Video Ingestion** (`index`)
   - Recursively scan folder for video files
   - Extract metadata (duration, FPS, resolution)
   - Compute file hashes for reproducibility

2. **Scene Detection** (`scenes`)
   - Detect scene boundaries using PySceneDetect
   - Filter by minimum duration threshold
   - Cache results for reuse

3. **Candidate Generation** (`candidates`)
   - Split scenes into fixed-length clips
   - Apply duration constraints (2-8 seconds)
   - Generate overlapping clips for coverage

4. **Face Filtering** (`faces`)
   - Run InsightFace detection on sampled frames
   - Filter clips by face presence threshold
   - Cache embeddings for identity clustering

5. **Crop Generation** (`crops`)
   - Generate face, half-body, and full-frame crops
   - Smooth bounding boxes across frames
   - Apply stable crop regions

6. **Bucket Rendering** (`render`)
   - Render frames at target resolution (1024)
   - Output exact frame count (121)
   - Pad or trim to match exactly

7. **Manifest Generation** (`manifest`)
   - Generate `manifest.jsonl` for LTX-2
   - Write caption files
   - Output statistics

## Output Structure

```
dataset/
├── manifest.jsonl
├── samples/
│   └── austin_powers_person/
│       ├── clip_000001_face/
│       │   ├── 000000.png
│       │   ├── 000001.png
│       │   └── ... (121 frames)
│       ├── clip_000001_face.txt  (caption)
│       ├── clip_000001_half_body/
│       │   └── ...
│       └── clip_000002_face/
│           └── ...
└── .cache/
    └── index.db  (SQLite database)
```

## Configuration

### Key Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `token` | - | Character identifier |
| `render.resolution` | 1024 | Output resolution |
| `render.frame_count` | 121 | Frames per bucket |
| `render.fps` | 24 | Output FPS |
| `scene.min_duration` | 2.0 | Minimum scene duration (seconds) |
| `scene.max_duration` | 8.0 | Maximum scene duration (seconds) |
| `face.min_face_presence` | 0.5 | Required face detection ratio |

### Example Config

```yaml
token: austin_powers_person
source_dir: /mnt/nas/movies
output_dir: ./dataset
cache_dir: ./.cache

scene:
  min_duration: 2.0
  max_duration: 8.0
  threshold: 27.0

face:
  min_face_presence: 0.5
  min_face_size: 64
  detection_threshold: 0.5

render:
  resolution: 1024
  frame_count: 121
  fps: 24
  output_format: png
```

## Hardware Requirements

- **Recommended GPU**: RTX 6000 Pro Blackwell (96GB VRAM) or similar
- **Minimum GPU**: Any CUDA-capable GPU with 8GB+ VRAM
- **CPU**: Multi-core processor for parallel preprocessing
- **Storage**: Fast NVMe SSD for output, NAS acceptable for source

## Troubleshooting

### FFmpeg not found

Ensure FFmpeg is installed and in your PATH:

```bash
ffmpeg -version
```

### InsightFace model download

InsightFace models are downloaded automatically on first run. If you have network issues, download manually:

```python
from insightface.app import FaceAnalysis
app = FaceAnalysis(name="buffalo_l")
app.prepare(ctx_id=0)
```

### Out of memory

Reduce batch size or use CPU for face detection:

```bash
pip install onnxruntime  # CPU-only
```

## License

MIT License
