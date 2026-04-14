#!/usr/bin/env python3
"""
Convert a video file to 24fps.

Handles HDR sources by tone-mapping to SDR (yuv420p) automatically.
Audio is preserved and downmixed to stereo if needed.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_video_info(path: Path) -> dict:
    result = subprocess.run(
        [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', '-select_streams', 'v:0',
            str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f'ERROR: ffprobe failed: {result.stderr.strip()}', file=sys.stderr)
        sys.exit(1)
    data = json.loads(result.stdout)
    streams = data.get('streams', [])
    if not streams:
        print('ERROR: no video stream found', file=sys.stderr)
        sys.exit(1)
    s = streams[0]
    fps_str = s.get('r_frame_rate', '24/1')
    num, den = fps_str.split('/')
    fps = float(num) / float(den)
    return {
        'fps': fps,
        'pix_fmt': s.get('pix_fmt', ''),
        'color_transfer': s.get('color_transfer', ''),
        'width': s.get('width'),
        'height': s.get('height'),
        'codec': s.get('codec_name'),
    }


def is_hdr(info: dict) -> bool:
    hdr_transfers = {'smpte2084', 'arib-std-b67', 'smpte428', 'bt2020-10', 'bt2020-12'}
    if info['color_transfer'] in hdr_transfers:
        return True
    pix_fmt = info['pix_fmt']
    if '10le' in pix_fmt or '10be' in pix_fmt or '12le' in pix_fmt or '12be' in pix_fmt:
        return True
    return False


def build_cmd(src: Path, dst: Path, target_fps: int, hdr: bool, crf: int, preset: str) -> list:
    if hdr:
        vf = (
            f'fps={target_fps},'
            'zscale=transfer=linear:npl=100,format=gbrpf32le,'
            'zscale=primaries=bt709,tonemap=tonemap=hable:desat=0,'
            'zscale=transfer=bt709:matrix=bt709:range=tv,'
            'format=yuv420p'
        )
    else:
        vf = f'fps={target_fps},format=yuv420p'

    return [
        'ffmpeg', '-y',
        '-i', str(src),
        '-vf', vf,
        '-c:v', 'libx264',
        '-preset', preset,
        '-crf', str(crf),
        '-pix_fmt', 'yuv420p',
        '-ac', '2',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-movflags', '+faststart',
        str(dst),
    ]


def main():
    parser = argparse.ArgumentParser(
        description='Convert a video to 24fps (or another target fps).',
    )
    parser.add_argument('input', help='Input video file')
    parser.add_argument('output', nargs='?', help='Output file (default: <input>_24fps.<ext>)')
    parser.add_argument('--fps', type=int, default=24, metavar='N', help='Target fps (default: 24)')
    parser.add_argument('--crf', type=int, default=18, help='CRF quality (default: 18, lower=better)')
    parser.add_argument('--preset', default='fast', help='x264 preset (default: fast)')
    parser.add_argument('--force-tonemap', action='store_true', help='Force HDR tone-mapping even if not detected')
    parser.add_argument('--no-tonemap', action='store_true', help='Skip HDR tone-mapping even if detected')
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f'ERROR: {src} not found', file=sys.stderr)
        sys.exit(1)

    if args.output:
        dst = Path(args.output)
    else:
        dst = src.with_name(f'{src.stem}_{args.fps}fps{src.suffix}')

    info = get_video_info(src)
    current_fps = info['fps']

    print(f'Input:  {src}')
    print(f'        {info["width"]}x{info["height"]}  {current_fps:.3f}fps  {info["codec"]}  {info["pix_fmt"]}  transfer={info["color_transfer"] or "unset"}')

    if abs(current_fps - args.fps) < 0.01 and not args.force_tonemap:
        print(f'Already {args.fps}fps — nothing to do. Use --force-tonemap to re-encode anyway.')
        sys.exit(0)

    hdr = args.force_tonemap or (is_hdr(info) and not args.no_tonemap)
    if hdr:
        print(f'HDR detected — will tone-map to SDR (yuv420p)')

    cmd = build_cmd(src, dst, args.fps, hdr, args.crf, args.preset)
    print(f'Output: {dst}')
    print(f'Running: {" ".join(cmd)}\n')

    result = subprocess.run(cmd)
    if result.returncode != 0:
        if hdr:
            print('\nTone-mapping failed — retrying without tone-map...', file=sys.stderr)
            cmd2 = build_cmd(src, dst, args.fps, hdr=False, crf=args.crf, preset=args.preset)
            result2 = subprocess.run(cmd2)
            if result2.returncode != 0:
                print('ERROR: conversion failed', file=sys.stderr)
                sys.exit(1)
        else:
            print('ERROR: conversion failed', file=sys.stderr)
            sys.exit(1)

    print(f'\nDone: {dst}')


if __name__ == '__main__':
    main()
