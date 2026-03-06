# LTX-2 Character LoRA Training Data Automation

## Overview

This project automates end-to-end training data extraction for LTX-2 character LoRA training using owned movie sources stored on a NAS.

The goal is to transform:

Movie files (.mkv/.mp4 on NAS)

into:

High-quality, identity-focused, bucketed training samples  
(1024 resolution, 121-frame buckets)  
+ manifest.jsonl ready for LTX-2 training

Primary focus:
- Character identity fidelity
- Style consistency
- High-quality 1024 video buckets
- Minimal manual intervention
- Fully repeatable + scalable pipeline

Target hardware:
- RTX 6000 Pro Blackwell Workstation Edition (96GB VRAM)
- Linux environment (Ubuntu Server class system)
- Large NAS-backed dataset

---

# Objectives

1. Fully automate training sample generation from movies
2. Gate samples based on:
   - Scene segmentation
   - Face presence
3. Generate multi-crop variants (face / half-body / full)
4. Render consistent 1024 resolution 121-frame buckets
5. Generate clean manifest files for LTX-2 training
6. Maintain metadata for reproducibility
7. Enable easy reprocessing without recomputing expensive steps

---

# High-Level Pipeline

## 1. Video Ingestion

- Recursively scan folder (mounted to NAS or local) for supported video formats
- Extract metadata:
  - Duration
  - FPS
  - Resolution
  - Hash (SHA-256)
- Store index in local DB (MongoDB or SQLite)

---

## 2. Scene Detection

Input:
- Raw movie file

Output:
- List of scenes (start_time, end_time)

Requirements:
- Minimum scene duration threshold
- Optional splitting of long scenes into subclips
- Avoid black frames / fade-in/out where possible

Recommended:
- PySceneDetect
- FFmpeg-based threshold detection

---

## 3. Candidate Clip Generation

From detected scenes:

- Enforce duration constraints (e.g. 2s–8s)
- Split long scenes into fixed-length chunks
- Generate candidate clip list

Output:
[
  {
    source_video,
    scene_start,
    scene_end
  }
]

---

## 4. Face Detection & Identity Gating

Goal:
Ensure clip meaningfully contains the target character.

Process:
- Run face detection on sampled frames
- Keep clip if face appears in ≥ X% of frames
- Optionally:
  - Use embeddings (InsightFace) to cluster by character
  - Reject non-target identities

Output:
- Filtered candidate list

---

## 5. Crop Strategy Generation

For each accepted clip:

Generate multiple dataset views:

- Face crop (high priority)
- Half-body crop
- Full-frame (low frequency)

Requirements:
- Smooth bounding box across frames
- Expand bounding box slightly to avoid jitter
- Clamp within frame boundaries
- Store crop metadata for reproducibility

---

## 6. Bucket Rendering

Render final training shards:

- Resolution: 1024
- Frame count: 121
- Fixed FPS (e.g. 24)
- Pad or trim clips to exact frame count
- Deterministic processing

Directory structure example:

dataset/
  samples/
    austin_powers_person/
      clip_000123_face/
        000000.png
        ...
        000120.png

---

## 7. Caption Generation

Simple, consistent captions preferred.

Example:

austin_powers_person, cinematic, high quality

Avoid verbose natural-language scene descriptions.

Optional:
- Auto-captioning via VLM pass
- Template-based tag enrichment

---

## 8. Manifest Generation

Produce manifest.jsonl compatible with LTX-2 training.

Each entry should include:

{
  "token": "austin_powers_person",
  "source_video": "...",
  "scene_start": 123.45,
  "scene_end": 130.21,
  "fps": 24,
  "frames": 121,
  "crop_type": "face",
  "path": "dataset/samples/...",
  "caption": "austin_powers_person, cinematic, high quality"
}

---

# Design Requirements

## Determinism
- Given same input + config → identical output

## Reusability
- Cache scene detection
- Cache face detections
- Cache embeddings
- Avoid recomputation where possible

## Config-Driven
All thresholds configurable via YAML or CLI:

- Min/max scene duration
- Frame count
- FPS
- Face presence threshold
- Crop expansion ratio
- Resolution
- Output structure

---

# Non-Goals

- Manual clip curation
- GUI tooling
- General-purpose video editing
- Real-time processing

This is a batch pipeline for dataset generation.

---

# Proposed Project Structure

ltx2_dataset_builder/
  __init__.py
  cli.py
  config.py

  ingestion/
    index_videos.py

  scenes/
    detect.py

  candidates/
    generate.py

  faces/
    detect.py
    embed.py
    smooth.py

  crops/
    generate.py

  render/
    bucket.py

  manifest/
    writer.py

  utils/
    ffmpeg.py
    hashing.py
    io.py

---

# Hardware Context

- GPU: RTX 6000 Pro Blackwell (96GB)
- Large VRAM allows:
  - 1024 resolution
  - 121-frame buckets
  - High-capacity LoRAs
- CPU parallelism encouraged for preprocessing

---

# Success Criteria

The pipeline is successful when:

- Entire movie library can be processed automatically
- Character-specific dataset can be generated via:

  ltx2-build --token austin_powers_person --source /mnt/nas/movies

- Output is immediately usable for 1024 / 121f LTX-2 LoRA training
- No manual pruning required
- Identity quality improves measurably over raw frame sampling

---

# Future Enhancements

- Automatic character clustering
- Automatic negative sample generation
- Active learning loop (train → find weak spots → augment data)
- Quality scoring feedback from model outputs
- Web UI dashboard for dataset inspection