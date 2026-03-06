# LTX-2 Training Data Extractor

Extracts character LoRA training data from movie files for LTX-2 video diffusion model training.

## Environment

```bash
source .venv/bin/activate
```

## Common commands

```bash
# Run a single pipeline step
ltx2-build --config config.yaml --step <step>

# Full pipeline (requires --token if not in config)
ltx2-build --config config.yaml

# List indexed videos
ltx2-build --config config.yaml --list-videos

# Set frame offset for a video (codec timing compensation)
ltx2-build --config config.yaml --set-frame-offset 2 --video deadpool-and-wolverine.mkv
```

## Pipeline steps (in order)

| Step | Command | Description |
|------|---------|-------------|
| index | `--step index` | Scan `./vids`, hash files, store metadata in DB |
| scenes | `--step scenes` | Detect scene cuts, write to DB incrementally per chunk |
| captions | `--step captions` | Caption scenes with Qwen3 VLM |
| candidates | `--step candidates` | Split scenes into fixed-length clips |
| quality | `--step quality` | Filter clips by quality score |
| faces | `--step faces` | Filter clips by InsightFace detection |
| crops | `--step crops` | Generate face / half-body / full-frame crop specs |
| render | `--step render` | Render 1024px, 121-frame PNG buckets |
| manifest | `--step manifest` | Write `manifest.jsonl` and caption `.txt` files |
| stats | `--step stats` | Print dataset statistics |
| debug-scenes | `--step debug-scenes` | Generate scene preview images |
| debug-candidates | `--step debug-candidates` | Generate candidate preview images |

## Key paths

- `config.yaml` — active config (token, paths, thresholds)
- `.cache/index.db` — SQLite cache (videos, scenes, candidates, face detections, samples)
- `./vids/` — source video files
- `./dataset/` — output (manifest + rendered frames)

## Key source files

- `ltx2_dataset_builder/cli.py` — entry point, `run_pipeline` / `run_step`
- `ltx2_dataset_builder/config.py` — `PipelineConfig` dataclass
- `ltx2_dataset_builder/utils/io.py` — `Database` class (all DB operations)
- `ltx2_dataset_builder/scenes/detect.py` — scene detection; writes to DB incrementally
- `ltx2_dataset_builder/captions/generate.py` — Qwen3 captioning
- `ltx2_dataset_builder/faces/detect.py` — InsightFace filtering
- `ltx2_dataset_builder/render/bucket.py` — FFmpeg bucket rendering

## Notes

- Each step is idempotent — re-running skips already-processed items (`skip_existing: true` in config)
- Scene detection flushes confirmed scenes to DB after every ~10s chunk, so a kill won't lose all progress
- The `frame_offset` on a video compensates for codec timing drift (use `--list-videos` to inspect)
- Face embeddings use `buffalo_l`; downloaded automatically on first run to `~/.insightface/`
