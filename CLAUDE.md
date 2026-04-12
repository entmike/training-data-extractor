# LTX-2 Training Data Extractor

Extracts character LoRA training data from movie files for LTX-2 video diffusion model training.

## Git-specific Behavior

Do NOT mention co-authored by anything.

## Environment

```bash
source .venv/bin/activate
```

## Starting the dev environment

```bash
./restart.sh          # starts Flask backend (port 5000) + Vite dev server (port 5173) in tmux
```

Both processes run in persistent tmux sessions that survive SSH disconnects:
- `tmux attach -t backend` — Flask API logs
- `tmux attach -t vite` — Vite dev server logs

Access the UI at **http://localhost:5173** (Vite, with hot reload).
The API runs at **http://localhost:5000** — Vite proxies all `/api/*` requests there.

To run the captioner separately:
```bash
.venv/bin/ltx2-build --config config.yaml --step captions > /tmp/captions.log 2>&1 &
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

## Database

PostgreSQL via Docker. Start with:
```bash
docker compose up -d
```

Connection: `postgresql://ltx2:ltx2@localhost:5432/ltx2` (set in `config.yaml` as `pg_dsn` and in `.env` as `DATABASE_URL`).

To migrate from SQLite backup:
```bash
python migrate_sqlite_to_pg.py
```

## Pipeline steps (in order)

| Step | Command | Description |
|------|---------|-------------|
| index | `--step index` | Scan `./vids`, hash files, store metadata in DB |
| scenes | `--step scenes` | Detect scene cuts, write to DB incrementally per chunk |
| captions | `--step captions` | Caption scenes with Qwen3 VLM |
| buckets | `--step buckets` | Auto-detect optimal 24-frame-multiple crops prioritizing speech |
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

- `config.yaml` — active config (token, paths, thresholds, pg_dsn)
- `.env` — `DATABASE_URL` for PostgreSQL DSN
- `docker-compose.yml` — PostgreSQL container
- `./vids/` — source video files
- `./dataset/` — output (manifest + rendered frames)
- `ui/src/` — React frontend source
- `ui/dist/` — production build (served by Flask, rebuilt with `cd ui && npm run build`)

## Key source files

- `web_review.py` — Flask backend; serves API + built UI from `ui/dist/`
- `restart.sh` — starts backend + Vite dev server in tmux
- `ltx2_dataset_builder/cli.py` — pipeline entry point
- `ltx2_dataset_builder/config.py` — `PipelineConfig` dataclass (includes `pg_dsn` / `dsn` property)
- `ltx2_dataset_builder/utils/io.py` — `Database` class (PostgreSQL, all DB operations)
- `ltx2_dataset_builder/scenes/detect.py` — scene detection; writes to DB incrementally
- `ltx2_dataset_builder/captions/generate.py` — Qwen3 captioning
- `ltx2_dataset_builder/buckets/detect.py` — speech-based optimal bucket detection
- `ltx2_dataset_builder/faces/detect.py` — InsightFace filtering
- `ltx2_dataset_builder/render/bucket.py` — FFmpeg bucket rendering

## Notes

- Each step is idempotent — re-running skips already-processed items (`skip_existing: true` in config)
- Scene detection flushes confirmed scenes to DB after every ~10s chunk, so a kill won't lose all progress
- The `frame_offset` on a video compensates for codec timing drift (use `--list-videos` to inspect)
- Face embeddings use `buffalo_l`; downloaded automatically on first run to `~/.insightface/`
- **Buckets**: Auto-detected optimal crops prioritize speech content using audio energy and zero-crossing rate analysis. Buckets are always rounded down to multiples of 24 frames (at 24fps = 121 frames → 96 frames). The `speech_weight` config controls how much speech activity influences the optimal window selection.
- **HDR export**: Clip zip export auto-detects HDR sources (via `color_transfer` / 10-bit pixel format) and applies `zscale`→`tonemap=hable` tone-mapping to SDR. Falls back to plain encode if tone-mapping fails.
- **Sentinel captions**: `__skip__`, `__empty__`, `__error__: <msg>` — filter with `substr(caption, 1, 2) != '__'`
- All pipeline SQL uses `%s` placeholders (psycopg2 / PostgreSQL), not `?` (SQLite)
