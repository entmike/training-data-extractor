#!/usr/bin/env python3
"""Web frontend for reviewing scene captions."""

import sqlite3
import re
import subprocess
import io
from pathlib import Path
from typing import Optional
from flask import Flask, render_template_string, send_from_directory, request, jsonify, Response, send_file
import yaml

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

app = Flask(__name__)

# Load config
CONFIG_PATH = Path("config.yaml")
if CONFIG_PATH.exists():
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
else:
    config = {
        "db_path": ".cache/index.db",
        "output_dir": "./dataset"
    }

DB_PATH = Path(config.get("db_path", ".cache/index.db"))
OUTPUT_DIR = Path(config.get("output_dir", "./dataset"))
DEBUG_SCENES_DIR = OUTPUT_DIR / "debug" / "scenes"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Caption Review - {{ stats.captioned }}/{{ stats.total }} scenes</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            line-height: 1.6;
        }
        
        .header {
            background: #161b22;
            border-bottom: 1px solid #30363d;
            padding: 16px 24px;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .header-content {
            max-width: 1600px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }
        
        .header h1 {
            font-size: 20px;
            font-weight: 600;
            color: #f0f6fc;
        }
        
        .stats {
            display: flex;
            gap: 24px;
            font-size: 14px;
        }
        
        .stat {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .stat-value {
            font-weight: 600;
            color: #58a6ff;
        }
        
        .filters {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .tag-filter-bar {
            max-width: 1600px;
            margin: 0 auto;
            padding: 8px 0 4px;
            display: flex;
            flex-direction: column;
            gap: 5px;
            border-top: 1px solid #21262d;
            margin-top: 10px;
        }

        .tag-filter-row {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 6px;
        }

        .tag-filter-label {
            font-size: 12px;
            color: #8b949e;
            margin-right: 4px;
            white-space: nowrap;
            min-width: 52px;
            text-align: right;
        }

        .tag-filter-pill {
            padding: 3px 11px;
            border: 1px solid #30363d;
            background: #21262d;
            color: #8b949e;
            border-radius: 12px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.15s;
            user-select: none;
        }

        .tag-filter-pill:hover {
            border-color: #388bfd;
            color: #58a6ff;
        }

        .tag-filter-pill.active {
            background: #1f3a6e;
            border-color: #388bfd;
            color: #58a6ff;
        }

        .tag-filter-pill.exclude-active {
            background: #3d1a1a;
            border-color: #f85149;
            color: #f85149;
        }

        .tag-filter-pill.exclude-active:hover {
            border-color: #f85149;
            color: #f85149;
        }

        .tag-filter-clear {
            padding: 3px 11px;
            border: 1px solid #30363d;
            background: transparent;
            color: #6e7681;
            border-radius: 12px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.15s;
        }

        .tag-filter-clear:hover {
            border-color: #f85149;
            color: #f85149;
        }

        .tag-filter-mode {
            padding: 3px 10px;
            border: 1px solid #30363d;
            background: #0d1117;
            color: #8b949e;
            border-radius: 12px;
            cursor: pointer;
            font-size: 11px;
            margin-left: 6px;
            transition: all 0.15s;
        }

        .tag-filter-mode:hover { border-color: #58a6ff; color: #58a6ff; }

        .scene-card.tag-hidden { display: none; }
        .scene-card.frame-hidden { display: none; }

        .filter-select {
            padding: 5px 10px;
            border: 1px solid #30363d;
            background: #21262d;
            color: #c9d1d9;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
            outline: none;
        }
        .filter-select:hover { background: #30363d; }

        .filter-count {
            font-size: 12px;
            color: #8b949e;
            margin-left: 4px;
        }

        .autorefresh-label {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: #8b949e;
            cursor: pointer;
            user-select: none;
            margin-left: 8px;
        }
        .autorefresh-label input[type="checkbox"] { cursor: pointer; accent-color: #58a6ff; }

        .filter-btn {
            padding: 6px 16px;
            border: 1px solid #30363d;
            background: #21262d;
            color: #c9d1d9;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }
        
        .filter-btn:hover {
            background: #30363d;
        }
        
        .filter-btn.active {
            background: #238636;
            border-color: #238636;
            color: #fff;
        }
        
        .container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 24px;
        }
        
        .scenes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(500px, 1fr));
            gap: 24px;
        }

        .scene-batch {
            display: contents;
        }

        .scene-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
            content-visibility: auto;
            contain-intrinsic-size: 0 420px;
        }
        
        .scene-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        }
        
        .scene-preview {
            width: 100%;
            aspect-ratio: 16/5;
            object-fit: cover;
            background: #0d1117;
            display: block;
        }
        
        .scene-info {
            padding: 16px;
        }
        
        .scene-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            font-size: 13px;
            color: #8b949e;
        }
        
        .scene-id {
            font-weight: 600;
            color: #58a6ff;
        }
        
        .scene-time {
            font-family: 'SF Mono', Monaco, monospace;
        }
        
        .scene-video {
            color: #7ee787;
            font-size: 12px;
            margin-top: 4px;
        }
        
        .caption-box {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 12px;
            min-height: 80px;
            position: relative;
        }
        
        .caption-box.modified {
            border-color: #d29922;
        }
        
        .caption-box.saving {
            border-color: #58a6ff;
        }
        
        .caption-box.saved {
            border-color: #238636;
        }
        
        .caption-box.error {
            border-color: #f85149;
        }
        
        .caption-textarea {
            width: 100%;
            min-height: 80px;
            background: transparent;
            border: none;
            color: #c9d1d9;
            font-size: 14px;
            line-height: 1.6;
            font-family: inherit;
            resize: vertical;
            outline: none;
        }
        
        .caption-textarea::placeholder {
            color: #6e7681;
            font-style: italic;
        }
        
        .caption-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 8px;
            gap: 8px;
        }
        
        .caption-length {
            font-size: 11px;
            color: #8b949e;
        }
        
        .caption-actions {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        
        .save-btn {
            padding: 4px 12px;
            border: 1px solid #238636;
            background: #238636;
            color: #fff;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            transition: all 0.2s;
            opacity: 0;
            pointer-events: none;
        }
        
        .save-btn.visible {
            opacity: 1;
            pointer-events: auto;
        }
        
        .save-btn:hover {
            background: #2ea043;
        }
        
        .save-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .revert-btn {
            padding: 4px 12px;
            border: 1px solid #d29922;
            background: transparent;
            color: #d29922;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .revert-btn:hover {
            background: #d29922;
            color: #0d1117;
        }
        
        .revert-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .delete-caption-btn {
            padding: 4px 12px;
            border: 1px solid #da3633;
            background: transparent;
            color: #da3633;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            transition: all 0.2s;
        }
        .delete-caption-btn:hover { background: #da3633; color: #fff; }
        
        .save-status {
            font-size: 11px;
            color: #8b949e;
        }
        
        .save-status.saving {
            color: #58a6ff;
        }
        
        .save-status.saved {
            color: #238636;
        }
        
        .save-status.error {
            color: #f85149;
        }
        
        .progress-bar {
            width: 200px;
            height: 8px;
            background: #21262d;
            border-radius: 4px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #238636, #2ea043);
            transition: width 0.3s;
        }
        
        .empty-state {
            text-align: center;
            padding: 80px 20px;
            color: #8b949e;
        }
        
        .empty-state h2 {
            font-size: 24px;
            margin-bottom: 8px;
            color: #c9d1d9;
        }
        
        /* Video player styles */
        .preview-container {
            position: relative;
            cursor: pointer;
        }
        
        .play-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(0, 0, 0, 0.3);
            opacity: 0;
            transition: opacity 0.2s;
        }
        
        .preview-container:hover .play-overlay {
            opacity: 1;
        }
        
        .play-icon {
            width: 64px;
            height: 64px;
            background: rgba(0, 0, 0, 0.7);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: transform 0.2s, background 0.2s;
        }
        
        .preview-container:hover .play-icon {
            transform: scale(1.1);
            background: rgba(35, 134, 54, 0.9);
        }
        
        .play-icon svg {
            width: 28px;
            height: 28px;
            fill: white;
            margin-left: 4px;
        }
        
        .video-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.9);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .video-modal.active {
            display: flex;
        }
        
        .video-modal-content {
            max-width: 1200px;
            width: 100%;
            position: relative;
            max-height: 95vh;
            overflow-y: auto;
            background: #161b22;
            border-radius: 12px;
            padding: 20px;
        }
        
        .video-modal video {
            width: 100%;
            max-height: 80vh;
            background: #000;
            border-radius: 8px;
        }
        
        .video-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            color: #c9d1d9;
        }
        
        .video-modal-title {
            font-size: 16px;
            font-weight: 500;
        }
        
        .video-modal-close {
            background: none;
            border: none;
            color: #8b949e;
            font-size: 32px;
            cursor: pointer;
            padding: 0;
            line-height: 1;
            transition: color 0.2s;
        }
        
        .video-modal-close:hover {
            color: #f0f6fc;
        }
        
        .video-loading {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #8b949e;
            font-size: 14px;
        }

        /* Tags */
        .tag-section {
            margin-top: 10px;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 6px;
        }

        .tag-pill {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            padding: 2px 8px;
            background: #1f3a6e;
            border: 1px solid #388bfd;
            border-radius: 12px;
            font-size: 12px;
            color: #58a6ff;
        }

        .tag-remove {
            background: none;
            border: none;
            color: #58a6ff;
            cursor: pointer;
            font-size: 14px;
            padding: 0;
            line-height: 1;
            opacity: 0.6;
            transition: opacity 0.15s;
        }

        .tag-remove:hover {
            opacity: 1;
        }

        .tag-add-btn {
            padding: 2px 9px;
            background: transparent;
            border: 1px dashed #30363d;
            color: #8b949e;
            border-radius: 12px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.2s;
        }

        .tag-add-btn:hover {
            border-color: #58a6ff;
            color: #58a6ff;
        }

        .tag-dropdown {
            position: fixed;
            background: #161b22;
            border: 1px solid #388bfd;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
            z-index: 2000;
            min-width: 160px;
            max-width: 260px;
            padding: 6px;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .tag-dropdown-item {
            padding: 5px 10px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 12px;
            color: #c9d1d9;
            transition: background 0.1s;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .tag-dropdown-item:hover { background: #21262d; color: #58a6ff; }

        .tag-dropdown-empty {
            font-size: 12px;
            color: #6e7681;
            padding: 5px 10px;
            font-style: italic;
        }

        .tag-dropdown-divider {
            border-top: 1px solid #21262d;
            margin: 4px 2px;
        }

        .tag-dropdown-new-label {
            font-size: 11px;
            color: #6e7681;
            padding: 2px 10px 0;
        }

        .tag-dropdown-input {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 5px;
            color: #c9d1d9;
            font-size: 12px;
            padding: 5px 8px;
            outline: none;
            width: 100%;
            box-sizing: border-box;
            margin-top: 2px;
        }

        .tag-dropdown-input:focus { border-color: #388bfd; }

        /* Manage Tags modal */
        .manage-tags-modal {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.8);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .manage-tags-modal.active { display: flex; }
        .manage-tags-content {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            width: 100%;
            max-width: 480px;
            max-height: 80vh;
            overflow-y: auto;
        }
        .manage-tags-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .manage-tags-header h2 { font-size: 16px; color: #f0f6fc; font-weight: 600; }
        .manage-tags-row {
            display: flex;
            gap: 8px;
            align-items: center;
            padding: 6px 0;
            border-bottom: 1px solid #21262d;
        }
        .manage-tags-row:last-child { border-bottom: none; }
        .manage-tags-input {
            flex: 1;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 5px;
            color: #c9d1d9;
            font-size: 13px;
            padding: 5px 8px;
            outline: none;
        }
        .manage-tags-input:focus { border-color: #388bfd; }
        .manage-tags-save {
            padding: 4px 12px;
            border: 1px solid #238636;
            background: transparent;
            color: #238636;
            border-radius: 5px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.15s;
            white-space: nowrap;
        }
        .manage-tags-save:hover { background: #238636; color: #fff; }
        .manage-tags-save:disabled { opacity: 0.4; cursor: default; }
        .manage-tags-status { font-size: 11px; min-width: 50px; text-align: right; }
        .manage-tags-empty { color: #6e7681; font-size: 14px; text-align: center; padding: 20px 0; }

        /* Manage Videos modal */
        .manage-videos-modal {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .manage-videos-modal.active { display: flex; }
        .manage-videos-content {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
            width: 100%;
            max-width: 900px;
            max-height: 85vh;
            overflow-y: auto;
        }
        .manage-videos-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .manage-videos-header h2 { font-size: 16px; color: #f0f6fc; font-weight: 600; }
        .manage-videos-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .manage-videos-table th {
            text-align: left;
            color: #8b949e;
            font-weight: 500;
            padding: 6px 10px;
            border-bottom: 1px solid #30363d;
            white-space: nowrap;
        }
        .manage-videos-table td {
            padding: 10px 10px;
            border-bottom: 1px solid #21262d;
            vertical-align: top;
            color: #c9d1d9;
        }
        .manage-videos-table tr:last-child td { border-bottom: none; }
        .manage-videos-table tr:hover td { background: #1c2128; }
        .manage-videos-name { font-weight: 500; color: #f0f6fc; }
        .manage-videos-meta { font-size: 11px; color: #6e7681; margin-top: 2px; word-break: break-all; }
        .manage-videos-bar-wrap { background: #21262d; border-radius: 4px; height: 6px; margin-top: 4px; width: 80px; }
        .manage-videos-bar { background: #238636; height: 6px; border-radius: 4px; }
        .manage-videos-empty { color: #6e7681; font-size: 14px; text-align: center; padding: 20px 0; }
        .manage-videos-prompt-label { font-size: 12px; color: #8b949e; margin: 10px 0 4px; }
        .manage-videos-textarea {
            width: 100%;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 4px;
            color: #c9d1d9;
            font-size: 13px;
            padding: 6px 8px;
            resize: vertical;
            min-height: 70px;
            font-family: inherit;
            outline: none;
        }
        .manage-videos-textarea:focus { border-color: #388bfd; }
        .manage-videos-prompt-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 6px;
        }
        .manage-videos-save {
            padding: 4px 12px;
            border: 1px solid #238636;
            border-radius: 4px;
            background: transparent;
            color: #238636;
            font-size: 12px;
            cursor: pointer;
            white-space: nowrap;
        }
        .manage-videos-save:hover { background: #238636; color: #fff; }
        .manage-videos-save:disabled { opacity: 0.4; cursor: default; }
        .manage-videos-save-status { font-size: 11px; color: #8b949e; }

        @media (max-width: 600px) {
            .scenes-grid {
                grid-template-columns: 1fr;
            }
            
            .header-content {
                flex-direction: column;
                align-items: flex-start;
            }
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="header-content">
            <h1>Scene Caption Review</h1>
            <div class="stats">
                <div class="stat">
                    <span>Progress:</span>
                    <span class="stat-value">{{ stats.captioned }} / {{ stats.total }}</span>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: {{ (stats.captioned / stats.total * 100) if stats.total > 0 else 0 }}%"></div>
                    </div>
                </div>
            </div>
            <div class="filters">
                <a href="?filter=captioned{% if video_filter %}&video={{ video_filter }}{% endif %}" class="filter-btn {{ 'active' if filter == 'captioned' else '' }}">Captioned</a>
                <a href="?filter=uncaptioned{% if video_filter %}&video={{ video_filter }}{% endif %}" class="filter-btn {{ 'active' if filter == 'uncaptioned' else '' }}">Uncaptioned</a>
                <a href="?filter=all{% if video_filter %}&video={{ video_filter }}{% endif %}" class="filter-btn {{ 'active' if filter == 'all' else '' }}">All</a>
                <button class="filter-btn" onclick="openManageTags()">Manage Tags</button>
                <button class="filter-btn" onclick="openManageVideos()">Videos</button>
                <select class="filter-select" id="min-frames-select" onchange="applyTagFilter()" title="Hide scenes shorter than N frames">
                    <option value="0">All lengths</option>
                    <option value="24">&ge; 24 frames</option>
                    <option value="48">&ge; 48 frames</option>
                    <option value="96">&ge; 96 frames</option>
                    <option value="121">&ge; 121 frames</option>
                </select>
                <select class="filter-select" id="movie-select" onchange="window.location.href='?filter={{ filter }}&video=' + encodeURIComponent(this.value)" title="Filter by movie">
                    <option value="">All movies</option>
                    {% for video in all_videos %}
                    <option value="{{ video }}" {{ 'selected' if video == video_filter else '' }}>{{ video }}</option>
                    {% endfor %}
                </select>
                <span class="filter-count" id="filter-count"></span>
                <label class="autorefresh-label" title="Reload page every 5 seconds">
                    <input type="checkbox" id="autorefresh-toggle" onchange="onAutoRefreshToggle(this.checked)">
                    Auto-refresh
                </label>
            </div>
        </div>
        {% if all_tags %}
        <div class="tag-filter-bar" id="tag-filter-bar">
            <div class="tag-filter-row">
                <span class="tag-filter-label">Include:</span>
                {% for tag in all_tags %}
                <span class="tag-filter-pill" data-tag="{{ tag }}" onclick="toggleIncludeFilter(this)">{{ tag }}</span>
                {% endfor %}
                <button class="tag-filter-clear" id="tag-include-clear" onclick="clearIncludeFilters()" style="display:none;">&#x2715; clear</button>
                <button class="tag-filter-mode" id="tag-filter-mode" onclick="toggleFilterMode()" title="Switch AND / OR for include">OR</button>
            </div>
            <div class="tag-filter-row">
                <span class="tag-filter-label">Exclude:</span>
                {% for tag in all_tags %}
                <span class="tag-filter-pill" data-tag="{{ tag }}" onclick="toggleExcludeFilter(this)">{{ tag }}</span>
                {% endfor %}
                <button class="tag-filter-clear" id="tag-exclude-clear" onclick="clearExcludeFilters()" style="display:none;">&#x2715; clear</button>
            </div>
        </div>
        {% endif %}
    </header>
    
    <main class="container">
        <div id="top-spacer" style="height:0;"></div>
        <div class="scenes-grid" id="scenes-grid"></div>
        <div id="bottom-sentinel" style="height:1px;margin-top:24px;"></div>
        <div class="loading-indicator" id="loading-indicator" style="display:none;text-align:center;padding:24px;color:#8b949e;font-size:14px;">Loading…</div>
        <div id="empty-state" class="empty-state" style="display:none;">
            <h2>No scenes found</h2>
            <p id="empty-state-msg"></p>
        </div>
    </main>

    <!-- Shared floating tag dropdown -->
    <div class="tag-dropdown" id="tag-dropdown" style="display:none;">
        <div id="tag-dropdown-list"></div>
        <div class="tag-dropdown-divider" id="tag-dropdown-divider" style="display:none;"></div>
        <div class="tag-dropdown-new-label">New tag:</div>
        <input class="tag-dropdown-input" id="tag-dropdown-input" type="text" placeholder="type &amp; press Enter…"
               onkeydown="onTagDropdownKeydown(event)"
               oninput="onTagDropdownInput(event)">
    </div>

    <!-- Video Modal -->
    <div class="video-modal" id="video-modal" onclick="closeVideoOnBackdrop(event)">
        <div class="video-modal-content">
            <div class="video-modal-header">
                <span class="video-modal-title" id="video-title"></span>
                <button class="video-modal-close" onclick="closeVideo()">&times;</button>
            </div>
            <div style="position:relative;">
                <video id="video-player" controls loop playsinline></video>
                <div class="video-loading" id="video-loading" style="display:none;"></div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:6px;font-family:'SF Mono',Monaco,monospace;font-size:12px;color:#8b949e;">
                <span>Frame <span id="video-frame-label" style="color:#c9d1d9;">—</span></span>
                <span id="video-ts-display"></span>
            </div>
            <div class="caption-box" id="modal-caption-box" style="margin-top:16px;">
                <textarea class="caption-textarea" id="modal-caption"
                    placeholder="No caption yet..."
                    oninput="onModalCaptionChange()"
                    onblur="onModalCaptionBlur(event)"
                    style="min-height:80px;"
                ></textarea>
                <div class="caption-footer">
                    <span class="caption-length" id="modal-caption-length">0 chars</span>
                    <div class="caption-actions">
                        <span class="save-status" id="modal-caption-status"></span>
                        <button class="revert-btn" id="modal-revert-btn" onclick="revertModalCaption()" style="display:none;">Revert</button>
                        <button class="delete-caption-btn" id="modal-delete-btn" onclick="deleteModalCaption()" style="display:none;">Delete</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Manage Tags Modal -->
    <div class="manage-tags-modal" id="manage-tags-modal" onclick="closeManageTagsBackdrop(event)">
        <div class="manage-tags-content">
            <div class="manage-tags-header">
                <h2>Manage Tags</h2>
                <button class="video-modal-close" onclick="closeManageTags()">&times;</button>
            </div>
            <div id="manage-tags-list"></div>
        </div>
    </div>

    <!-- Manage Videos Modal -->
    <div class="manage-videos-modal" id="manage-videos-modal" onclick="closeManageVideosBackdrop(event)">
        <div class="manage-videos-content">
            <div class="manage-videos-header">
                <h2>Videos</h2>
                <button class="video-modal-close" onclick="closeManageVideos()">&times;</button>
            </div>
            <div id="manage-videos-list"></div>
        </div>
    </div>

<script>
        // Track modified captions
        const modifiedCaptions = new Set();
        let isReverting = false;
        
        function onCaptionChange(sceneId) {
            const textarea = document.getElementById(`caption-${sceneId}`);
            const box = document.getElementById(`caption-box-${sceneId}`);
            const revertBtn = document.getElementById(`revert-btn-${sceneId}`);
            const lengthSpan = document.getElementById(`length-${sceneId}`);
            const statusSpan = document.getElementById(`status-${sceneId}`);
            const original = textarea.dataset.original;
            const current = textarea.value;
            lengthSpan.textContent = `${current.length} chars`;
            if (current !== original) {
                box.classList.add('modified');
                box.classList.remove('saved', 'error');
                revertBtn.classList.add('visible');
                revertBtn.style.display = 'inline-block';
                statusSpan.textContent = 'Modified';
                statusSpan.className = 'save-status';
                modifiedCaptions.add(sceneId);
            } else {
                box.classList.remove('modified');
                revertBtn.classList.remove('visible');
                revertBtn.style.display = 'none';
                statusSpan.textContent = '';
                modifiedCaptions.delete(sceneId);
            }
        }
        async function saveCaption(sceneId) {
            const textarea = document.getElementById(`caption-${sceneId}`);
            const box = document.getElementById(`caption-box-${sceneId}`);
            const revertBtn = document.getElementById(`revert-btn-${sceneId}`);
            const statusSpan = document.getElementById(`status-${sceneId}`);
            const caption = textarea.value;
            if (caption === textarea.dataset.original) return;
            box.classList.remove('modified', 'saved', 'error');
            box.classList.add('saving');
            statusSpan.textContent = 'Saving...';
            statusSpan.className = 'save-status saving';
            try {
                const response = await fetch(`/api/caption/${sceneId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ caption: caption })
                });
                if (response.ok) {
                    box.classList.remove('saving');
                    box.classList.add('saved');
                    revertBtn.classList.remove('visible');
                    revertBtn.style.display = 'none';
                    statusSpan.textContent = 'Saved!';
                    statusSpan.className = 'save-status saved';
                    textarea.dataset.original = caption;
                    modifiedCaptions.delete(sceneId);
                    setTimeout(() => {
                        if (!modifiedCaptions.has(sceneId)) {
                            box.classList.remove('saved');
                            statusSpan.textContent = '';
                        }
                    }, 2000);
                } else {
                    throw new Error('Save failed');
                }
            } catch (error) {
                box.classList.remove('saving');
                box.classList.add('error');
                statusSpan.textContent = 'Error saving';
                statusSpan.className = 'save-status error';
            }
        }
        function onCaptionBlur(event, sceneId) {
            if (isReverting) return;
            saveCaption(sceneId);
        }

        function revertCaption(sceneId) {
            isReverting = true;
            const textarea = document.getElementById(`caption-${sceneId}`);
            textarea.value = textarea.dataset.original;
            onCaptionChange(sceneId);
            setTimeout(() => { isReverting = false; }, 0);
        }
        
        // Keyboard shortcut: Ctrl+S to save current focused caption
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                const activeElement = document.activeElement;
                if (activeElement.classList.contains('caption-textarea')) {
                    const sceneId = activeElement.dataset.sceneId;
                    if (modifiedCaptions.has(parseInt(sceneId))) {
                        saveCaption(parseInt(sceneId));
                    }
                }
            }
        });
        
        // Warn before leaving if there are unsaved changes
        window.addEventListener('beforeunload', (e) => {
            if (modifiedCaptions.size > 0) {
                e.preventDefault();
                e.returnValue = '';
            }
        });
        
        // Video player functions
        let currentVideo = null;
        let modalSceneId = null;
        let modalCaptionOriginal = '';
        let modalFps = 24;
        let modalStartFrame = 0;
        let modalEndFrame = 0;
        let modalFrameOffset = 0;
        let frameRafId = null;

        function updateFrameCounter() {
            const video = document.getElementById('video-player');
            const frame = modalStartFrame + modalFrameOffset + 1 + Math.round(video.currentTime * modalFps);
            document.getElementById('video-frame-label').textContent = frame;
            const totalSecs = (modalStartFrame + modalFrameOffset + 1) / modalFps + video.currentTime;
            const h = Math.floor(totalSecs / 3600);
            const m = Math.floor((totalSecs % 3600) / 60);
            const s = Math.floor(totalSecs % 60);
            document.getElementById('video-ts-display').textContent = `· ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
            frameRafId = requestAnimationFrame(updateFrameCounter);
        }
        
        function playVideo(videoPath, startFrame, endFrame, sceneId, startTime, endTime, fps, frameOffset) {
            const modal = document.getElementById('video-modal');
            const video = document.getElementById('video-player');
            const title = document.getElementById('video-title');
            const loading = document.getElementById('video-loading');

            modalFps = fps || 24;
            modalStartFrame = startFrame || 0;
            modalEndFrame = endFrame || 0;
            modalFrameOffset = frameOffset || 0;

            // Build URL using scene_id for accurate server-side clip extraction
            const videoUrl = `/clip/${sceneId}`;

            title.textContent = `Scene #${sceneId} — frames ${startFrame}–${endFrame}`;
            document.getElementById('video-frame-label').textContent = '—';
            document.getElementById('video-ts-display').textContent = '';
            loading.style.display = 'block';
            loading.textContent = 'Loading clip...';
            
            video.src = videoUrl;
            currentVideo = video;
            
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
            
            video.onloadeddata = () => {
                loading.style.display = 'none';
                if (frameRafId) cancelAnimationFrame(frameRafId);
                frameRafId = requestAnimationFrame(updateFrameCounter);
                video.play();
            };
            
            video.onerror = () => {
                loading.textContent = 'Error loading clip';
            };
            modalSceneId = sceneId;
            // Load caption for this scene
            loadModalCaption(sceneId);
        }
        
        function loadModalCaption(sceneId) {
            const textarea = document.getElementById('modal-caption');
            const lengthSpan = document.getElementById('modal-caption-length');
            const statusSpan = document.getElementById('modal-caption-status');
            const revertBtn = document.getElementById('modal-revert-btn');
            const box = document.getElementById('modal-caption-box');
            
            textarea.value = '';
            textarea.dataset.original = '';
            lengthSpan.textContent = '0 chars';
            statusSpan.textContent = 'Loading...';
            statusSpan.className = 'save-status';
            revertBtn.classList.remove('visible');
            revertBtn.style.display = 'none';
            box.classList.remove('modified', 'saved', 'error', 'saving');
            
            fetch(`/api/caption/${sceneId}`)
                .then(r => r.json())
                .then(data => {
                    textarea.value = data.caption || '';
                    textarea.dataset.original = data.caption || '';
                    lengthSpan.textContent = `${(data.caption || '').length} chars`;
                    statusSpan.textContent = '';
                    statusSpan.className = 'save-status';
                    revertBtn.classList.remove('visible');
                    revertBtn.style.display = 'none';
                    box.classList.remove('modified', 'saved', 'error', 'saving');
                    modalCaptionOriginal = data.caption || '';
                    const modalDeleteBtn = document.getElementById('modal-delete-btn');
                    if (modalDeleteBtn) modalDeleteBtn.style.display = data.caption ? '' : 'none';
                });
        }
        
        function onModalCaptionChange() {
            const textarea = document.getElementById('modal-caption');
            const lengthSpan = document.getElementById('modal-caption-length');
            const statusSpan = document.getElementById('modal-caption-status');
            const revertBtn = document.getElementById('modal-revert-btn');
            const box = document.getElementById('modal-caption-box');
            const original = textarea.dataset.original || '';
            const current = textarea.value;
            lengthSpan.textContent = `${current.length} chars`;
            if (current !== original) {
                box.classList.add('modified');
                box.classList.remove('saved', 'error');
                revertBtn.style.display = 'inline-block';
                statusSpan.textContent = 'Modified';
                statusSpan.className = 'save-status';
            } else {
                box.classList.remove('modified');
                revertBtn.style.display = 'none';
                statusSpan.textContent = '';
            }
        }
        async function saveModalCaption() {
            const textarea = document.getElementById('modal-caption');
            const box = document.getElementById('modal-caption-box');
            const revertBtn = document.getElementById('modal-revert-btn');
            const statusSpan = document.getElementById('modal-caption-status');
            const caption = textarea.value;
            if (caption === textarea.dataset.original) return;
            box.classList.remove('modified', 'saved', 'error');
            box.classList.add('saving');
            revertBtn.disabled = true;
            statusSpan.textContent = 'Saving...';
            statusSpan.className = 'save-status saving';
            try {
                const response = await fetch(`/api/caption/${modalSceneId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ caption: caption })
                });
                if (response.ok) {
                    box.classList.remove('saving');
                    box.classList.add('saved');
                    revertBtn.classList.remove('visible');
                    revertBtn.disabled = false;
                    statusSpan.textContent = 'Saved!';
                    statusSpan.className = 'save-status saved';
                    textarea.dataset.original = caption;
                    modalCaptionOriginal = caption;
                    // Sync to the grid card
                    const gridTextarea = document.getElementById(`caption-${modalSceneId}`);
                    if (gridTextarea) {
                        gridTextarea.value = caption;
                        gridTextarea.dataset.original = caption;
                        onCaptionChange(modalSceneId);
                        const lengthSpan = document.getElementById(`length-${modalSceneId}`);
                        if (lengthSpan) lengthSpan.textContent = `${caption.length} chars`;
                    }
                    setTimeout(() => {
                        if (textarea.value === caption) {
                            box.classList.remove('saved');
                            statusSpan.textContent = '';
                        }
                    }, 2000);
                } else {
                    throw new Error('Save failed');
                }
            } catch (error) {
                box.classList.remove('saving');
                box.classList.add('error');
                revertBtn.disabled = false;
                statusSpan.textContent = 'Error saving';
                statusSpan.className = 'save-status error';
            }
        }
        function onModalCaptionBlur(event) {
            if (isReverting) return;
            saveModalCaption();
        }

        function revertModalCaption() {
            isReverting = true;
            const textarea = document.getElementById('modal-caption');
            textarea.value = textarea.dataset.original;
            onModalCaptionChange();
            // Sync revert to grid card too
            const gridTextarea = document.getElementById(`caption-${modalSceneId}`);
            if (gridTextarea) {
                gridTextarea.value = textarea.dataset.original;
                onCaptionChange(modalSceneId);
            }
            setTimeout(() => { isReverting = false; }, 0);
        }

        async function deleteCaption(sceneId) {

            const textarea = document.getElementById(`caption-${sceneId}`);
            const statusEl = document.getElementById(`status-${sceneId}`);
            const deleteBtn = document.getElementById(`delete-btn-${sceneId}`);
            const box = document.getElementById(`caption-box-${sceneId}`);
            try {
                const resp = await fetch(`/api/caption/${sceneId}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({caption: ''})
                });
                if (!resp.ok) throw new Error();
                textarea.value = '';
                textarea.dataset.original = '';
                onCaptionChange(sceneId);
                deleteBtn.style.display = 'none';
                document.getElementById(`length-${sceneId}`).textContent = '0 chars';
                box.classList.remove('modified', 'saving', 'error');
            } catch (e) {
                if (statusEl) { statusEl.textContent = 'Error'; statusEl.className = 'save-status error'; }
            }
        }

        async function deleteModalCaption() {

            const textarea = document.getElementById('modal-caption');
            const statusEl = document.getElementById('modal-caption-status');
            const deleteBtn = document.getElementById('modal-delete-btn');
            const box = document.getElementById('modal-caption-box');
            try {
                const resp = await fetch(`/api/caption/${modalSceneId}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({caption: ''})
                });
                if (!resp.ok) throw new Error();
                textarea.value = '';
                textarea.dataset.original = '';
                modalCaptionOriginal = '';
                onModalCaptionChange();
                deleteBtn.style.display = 'none';
                box.classList.remove('modified', 'saving', 'error');
                // Sync to grid card
                const gridTextarea = document.getElementById(`caption-${modalSceneId}`);
                if (gridTextarea) {
                    gridTextarea.value = '';
                    gridTextarea.dataset.original = '';
                    onCaptionChange(modalSceneId);
                    document.getElementById(`delete-btn-${modalSceneId}`).style.display = 'none';
                    document.getElementById(`length-${modalSceneId}`).textContent = '0 chars';
                }
            } catch (e) {
                if (statusEl) { statusEl.textContent = 'Error'; statusEl.className = 'save-status error'; }
            }
        }

        // ---- Tag functions ----
        let tagDropdownSceneId = null;
        let allKnownTags = [];

        function showTagDropdown(event, sceneId) {
            event.stopPropagation();
            tagDropdownSceneId = sceneId;
            const dropdown = document.getElementById('tag-dropdown');
            const input = document.getElementById('tag-dropdown-input');
            input.value = '';
            populateDropdownList('');
            // Position near button
            const btn = document.getElementById(`tag-add-btn-${sceneId}`);
            const rect = btn.getBoundingClientRect();
            dropdown.style.display = 'flex';
            dropdown.style.top = (rect.bottom + 4) + 'px';
            dropdown.style.left = rect.left + 'px';
            // Adjust if off right edge
            requestAnimationFrame(() => {
                const ddRect = dropdown.getBoundingClientRect();
                if (ddRect.right > window.innerWidth - 8)
                    dropdown.style.left = (window.innerWidth - ddRect.width - 8) + 'px';
                if (ddRect.bottom > window.innerHeight - 8)
                    dropdown.style.top = (rect.top - ddRect.height - 4) + 'px';
            });
            input.focus();
        }

        function hideTagDropdown() {
            const dropdown = document.getElementById('tag-dropdown');
            if (dropdown) dropdown.style.display = 'none';
            tagDropdownSceneId = null;
        }

        function populateDropdownList(filter) {
            const list = document.getElementById('tag-dropdown-list');
            const divider = document.getElementById('tag-dropdown-divider');
            const section = tagDropdownSceneId != null
                ? document.getElementById(`tag-section-${tagDropdownSceneId}`) : null;
            const existing = section
                ? new Set([...section.querySelectorAll('.tag-pill')].map(p => p.dataset.tag))
                : new Set();
            const available = allKnownTags.filter(t =>
                !existing.has(t) && (!filter || t.includes(filter))
            );
            if (available.length === 0) {
                list.innerHTML = filter ? '' : '<div class="tag-dropdown-empty">No existing tags</div>';
                divider.style.display = 'none';
            } else {
                list.innerHTML = available.map(t => {
                    const safe = t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
                    return `<div class="tag-dropdown-item" data-tag="${safe}">${safe}</div>`;
                }).join('');
                list.querySelectorAll('.tag-dropdown-item').forEach(el => {
                    el.addEventListener('mousedown', e => { e.preventDefault(); pickDropdownTag(el.dataset.tag); });
                });
                divider.style.display = '';
            }
        }

        function pickDropdownTag(tag) {
            const sceneId = tagDropdownSceneId;
            hideTagDropdown();
            if (sceneId != null) addTag(sceneId, tag);
        }

        function onTagDropdownKeydown(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                const tag = event.target.value.trim().toLowerCase();
                const sceneId = tagDropdownSceneId;
                hideTagDropdown();
                if (tag && sceneId != null) addTag(sceneId, tag);
            } else if (event.key === 'Escape') {
                hideTagDropdown();
            }
        }

        function onTagDropdownInput(event) {
            populateDropdownList(event.target.value.trim().toLowerCase());
        }

        document.addEventListener('click', (e) => {
            const dropdown = document.getElementById('tag-dropdown');
            if (dropdown && dropdown.style.display !== 'none') {
                if (!dropdown.contains(e.target) && !e.target.classList.contains('tag-add-btn')) {
                    hideTagDropdown();
                }
            }
        });

        // ---- Tag filter ----
        let activeIncludeFilters = new Set();
        let activeExcludeFilters = new Set();
        let tagFilterMode = 'OR'; // 'OR' or 'AND' — applies to include row only

        function toggleIncludeFilter(pill) {
            const tag = pill.dataset.tag;
            if (activeIncludeFilters.has(tag)) {
                activeIncludeFilters.delete(tag);
                pill.classList.remove('active');
            } else {
                // Can't be in both sets
                if (activeExcludeFilters.has(tag)) {
                    activeExcludeFilters.delete(tag);
                    document.querySelectorAll(`#tag-filter-bar .tag-filter-row:nth-child(2) .tag-filter-pill[data-tag="${tag}"]`)
                        .forEach(p => p.classList.remove('exclude-active'));
                }
                activeIncludeFilters.add(tag);
                pill.classList.add('active');
            }
            applyTagFilter();
        }

        function toggleExcludeFilter(pill) {
            const tag = pill.dataset.tag;
            if (activeExcludeFilters.has(tag)) {
                activeExcludeFilters.delete(tag);
                pill.classList.remove('exclude-active');
            } else {
                // Can't be in both sets
                if (activeIncludeFilters.has(tag)) {
                    activeIncludeFilters.delete(tag);
                    document.querySelectorAll(`#tag-filter-bar .tag-filter-row:nth-child(1) .tag-filter-pill[data-tag="${tag}"]`)
                        .forEach(p => p.classList.remove('active'));
                }
                activeExcludeFilters.add(tag);
                pill.classList.add('exclude-active');
            }
            applyTagFilter();
        }

        function clearIncludeFilters() {
            activeIncludeFilters.clear();
            document.querySelectorAll('#tag-filter-bar .tag-filter-row:nth-child(1) .tag-filter-pill.active')
                .forEach(p => p.classList.remove('active'));
            applyTagFilter();
        }

        function clearExcludeFilters() {
            activeExcludeFilters.clear();
            document.querySelectorAll('#tag-filter-bar .tag-filter-row:nth-child(2) .tag-filter-pill.exclude-active')
                .forEach(p => p.classList.remove('exclude-active'));
            applyTagFilter();
        }

        function toggleFilterMode() {
            tagFilterMode = tagFilterMode === 'OR' ? 'AND' : 'OR';
            document.getElementById('tag-filter-mode').textContent = tagFilterMode;
            applyTagFilter();
        }

        function applyTagFilter() {
            const incClear = document.getElementById('tag-include-clear');
            const exClear = document.getElementById('tag-exclude-clear');
            const countSpan = document.getElementById('filter-count');
            if (incClear) incClear.style.display = activeIncludeFilters.size ? 'inline-block' : 'none';
            if (exClear) exClear.style.display = activeExcludeFilters.size ? 'inline-block' : 'none';

            const minFrames = parseInt(document.getElementById('min-frames-select')?.value || '0');

            const cards = document.querySelectorAll('.scene-card');
            let visible = 0;
            cards.forEach(card => {
                const cardTags = new Set(
                    [...card.querySelectorAll('.tag-pill')].map(p => p.dataset.tag)
                );

                // Include check
                let includeMatch = true;
                if (activeIncludeFilters.size > 0) {
                    if (tagFilterMode === 'OR') {
                        includeMatch = [...activeIncludeFilters].some(t => cardTags.has(t));
                    } else {
                        includeMatch = [...activeIncludeFilters].every(t => cardTags.has(t));
                    }
                }

                // Exclude check: hide if card has ANY excluded tag
                let excludeMatch = activeExcludeFilters.size > 0 &&
                    [...activeExcludeFilters].some(t => cardTags.has(t));

                // Frame count check
                const frameCount = parseInt(card.dataset.frameCount || '0');
                const frameMatch = frameCount >= minFrames;

                const show = includeMatch && !excludeMatch && frameMatch;
                card.classList.toggle('tag-hidden', !show);
                if (show) visible++;
            });

            if (countSpan) {
                const anyActive = activeIncludeFilters.size || activeExcludeFilters.size || minFrames > 0;
                countSpan.textContent = anyActive ? `${visible} shown` : '';
            }
        }
        // ---- End tag filter ----

        // Load all distinct tags from DB for dropdown
        async function loadTagSuggestions() {
            try {
                const url = currentVideoFilter
                    ? '/api/tags/all?video=' + encodeURIComponent(currentVideoFilter)
                    : '/api/tags/all';
                const resp = await fetch(url);
                if (!resp.ok) return;
                const data = await resp.json();
                allKnownTags = data.tags || [];
                refreshFilterBar();
            } catch(e) { /* best-effort */ }
        }

        function refreshFilterBar() {
            const bar = document.getElementById('tag-filter-bar');
            if (!bar) return;
            const rows = bar.querySelectorAll('.tag-filter-row');
            if (rows.length < 2) return;
            const incRow = rows[0];
            const exRow = rows[1];

            // Prune deleted tags from active sets
            for (const t of [...activeIncludeFilters]) if (!allKnownTags.includes(t)) activeIncludeFilters.delete(t);
            for (const t of [...activeExcludeFilters]) if (!allKnownTags.includes(t)) activeExcludeFilters.delete(t);

            function rebuildRow(row, activeSet, activeClass, clickFn) {
                // Save anchors (label first child, buttons at end)
                const label = row.querySelector('.tag-filter-label');
                const clearBtn = row.querySelector('.tag-filter-clear');
                const modeBtn = row.querySelector('.tag-filter-mode');

                // Remove existing pills
                row.querySelectorAll('.tag-filter-pill').forEach(p => p.remove());

                // Re-insert pills after label
                let insertBefore = clearBtn || modeBtn || null;
                for (const tag of allKnownTags) {
                    const pill = document.createElement('span');
                    pill.className = 'tag-filter-pill' + (activeSet.has(tag) ? ' ' + activeClass : '');
                    pill.dataset.tag = tag;
                    pill.textContent = tag;
                    pill.addEventListener('click', () => clickFn(pill));
                    if (insertBefore) row.insertBefore(pill, insertBefore);
                    else row.appendChild(pill);
                }

                if (clearBtn) clearBtn.style.display = activeSet.size ? 'inline-block' : 'none';
            }

            rebuildRow(incRow, activeIncludeFilters, 'active', toggleIncludeFilter);
            rebuildRow(exRow, activeExcludeFilters, 'exclude-active', toggleExcludeFilter);

            // Show/hide the whole bar
            bar.style.display = allKnownTags.length ? '' : 'none';
            applyTagFilter();
        }

        async function addTag(sceneId, tag) {
            try {
                const resp = await fetch(`/api/tags/${sceneId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({tag})
                });
                if (resp.ok) {
                    const data = await resp.json();
                    renderTags(sceneId, data.tags);
                    loadTagSuggestions();
                }
            } catch(e) { console.error('Failed to add tag', e); }
        }

        function removeTagFromPill(btn) {
            const pill = btn.parentElement;
            const sceneId = parseInt(pill.dataset.scene);
            const tag = pill.dataset.tag;
            fetch(`/api/tags/${sceneId}/${encodeURIComponent(tag)}`, {method: 'DELETE'})
                .then(r => r.ok ? r.json() : null)
                .then(data => { if (data) { renderTags(sceneId, data.tags); loadTagSuggestions(); } })
                .catch(e => console.error('Failed to remove tag', e));
        }

        function renderTags(sceneId, tags) {
            const section = document.getElementById(`tag-section-${sceneId}`);
            if (!section) return;
            section.querySelectorAll('.tag-pill').forEach(p => p.remove());
            const input = document.getElementById(`tag-input-${sceneId}`);
            for (const tag of tags) {
                const pill = document.createElement('span');
                pill.className = 'tag-pill';
                pill.dataset.scene = sceneId;
                pill.dataset.tag = tag;
                pill.innerHTML = `${tag}<button class="tag-remove" onclick="removeTagFromPill(this)">&#x2715;</button>`;
                section.insertBefore(pill, input);
            }
            applyTagFilter();
        }
        // ---- End tag functions ----

        // ---- Manage Tags ----
        async function openManageTags() {
            const modal = document.getElementById('manage-tags-modal');
            const list = document.getElementById('manage-tags-list');
            list.innerHTML = '<div class="manage-tags-empty">Loading...</div>';
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';

            const resp = await fetch('/api/tags/all');
            const data = await resp.json();
            const tags = data.tags || [];

            if (tags.length === 0) {
                list.innerHTML = '<div class="manage-tags-empty">No tags in database</div>';
                return;
            }

            list.innerHTML = tags.map(tag => {
                const safe = tag.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
                return `<div class="manage-tags-row" id="manage-row-${safe}">
                    <input class="manage-tags-input" type="text" value="${safe}" data-original="${safe}"
                           oninput="onManageTagInput(this)" onkeydown="onManageTagKeydown(event, this)">
                    <button class="manage-tags-save" disabled onclick="doRenameTag(this)">Rename</button>
                    <span class="manage-tags-status" id="manage-status-${safe}"></span>
                </div>`;
            }).join('');
        }

        function closeManageTags() {
            document.getElementById('manage-tags-modal').classList.remove('active');
            document.body.style.overflow = '';
        }

        function closeManageTagsBackdrop(event) {
            if (event.target === document.getElementById('manage-tags-modal')) closeManageTags();
        }

        function onManageTagInput(input) {
            const btn = input.parentElement.querySelector('.manage-tags-save');
            btn.disabled = input.value.trim() === '' || input.value.trim() === input.dataset.original;
        }

        function onManageTagKeydown(event, input) {
            if (event.key === 'Enter') {
                const btn = input.parentElement.querySelector('.manage-tags-save');
                if (!btn.disabled) doRenameTag(btn);
            } else if (event.key === 'Escape') {
                closeManageTags();
            }
        }

        async function doRenameTag(btn) {
            const row = btn.parentElement;
            const input = row.querySelector('.manage-tags-input');
            const oldTag = input.dataset.original;
            const newTag = input.value.trim().toLowerCase();
            const statusEl = row.querySelector('.manage-tags-status');

            if (!newTag || newTag === oldTag) return;

            btn.disabled = true;
            statusEl.textContent = 'Saving...';
            statusEl.style.color = '#58a6ff';

            try {
                const resp = await fetch('/api/tags/rename', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({old_tag: oldTag, new_tag: newTag})
                });
                if (!resp.ok) throw new Error('Failed');
                const data = await resp.json();

                input.dataset.original = newTag;
                input.value = newTag;

                statusEl.textContent = `\u2713 ${data.updated} updated`;
                statusEl.style.color = '#238636';

                // Update allKnownTags
                const idx = allKnownTags.indexOf(oldTag);
                if (idx !== -1) allKnownTags[idx] = newTag;

                // Update tag pills in the scene grid
                document.querySelectorAll(`.tag-pill[data-tag="${CSS.escape(oldTag)}"]`).forEach(pill => {
                    pill.dataset.tag = newTag;
                    pill.childNodes[0].textContent = newTag;
                });

                refreshFilterBar();
                setTimeout(() => { statusEl.textContent = ''; }, 3000);
            } catch(e) {
                statusEl.textContent = 'Error';
                statusEl.style.color = '#f85149';
                btn.disabled = false;
            }
        }
        // ---- End Manage Tags ----

        // ---- Manage Videos ----
        async function openManageVideos() {
            const modal = document.getElementById('manage-videos-modal');
            const list = document.getElementById('manage-videos-list');
            list.innerHTML = '<div class="manage-videos-empty">Loading...</div>';
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';

            const resp = await fetch('/api/videos');
            const data = await resp.json();
            const videos = data.videos || [];

            if (videos.length === 0) {
                list.innerHTML = '<div class="manage-videos-empty">No videos in database</div>';
                return;
            }

            const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
            const fmtDur = s => {
                if (!s) return '?';
                const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
                return h > 0 ? `${h}h ${m}m` : `${m}m ${sec}s`;
            };

            list.innerHTML = videos.map(v => {
                const pct = v.scene_count > 0 ? Math.round(v.captioned / v.scene_count * 100) : 0;
                const bar = `<div class="manage-videos-bar-wrap"><div class="manage-videos-bar" style="width:${pct}%"></div></div>`;
                const indexed = v.indexed_at ? v.indexed_at.replace('T',' ').slice(0,16) : '?';
                const prompt = esc(v.prompt || '');
                return `<div class="manage-videos-row" id="manage-videos-row-${v.id}">
                    <table class="manage-videos-table" style="margin-bottom:0">
                        <tbody><tr>
                            <td style="padding:0 10px 0 0; white-space:nowrap">
                                <div class="manage-videos-name">${esc(v.name)}</div>
                                <div class="manage-videos-meta">${esc(v.path)}</div>
                            </td>
                            <td style="white-space:nowrap; color:#8b949e; font-size:12px; padding:0 10px 0 0">
                                ${v.width && v.height ? v.width+'×'+v.height : '?'}<br>
                                ${fmtDur(v.duration)}<br>
                                ${v.fps ? v.fps.toFixed(3)+' fps' : '?'}
                            </td>
                            <td style="white-space:nowrap; color:#8b949e; font-size:12px; padding:0 10px 0 0">
                                ${esc(v.codec || '?')}<br>
                                offset: ${v.frame_offset ?? 0}<br>
                                ${indexed}
                            </td>
                            <td style="vertical-align:middle; white-space:nowrap; font-size:12px">
                                ${v.captioned}/${v.scene_count} captioned${bar}
                            </td>
                        </tr></tbody>
                    </table>
                    <div class="manage-videos-prompt-label">Captioning prompt</div>
                    <textarea class="manage-videos-textarea" data-video-id="${v.id}" data-original="${prompt}"
                              oninput="onVideosPromptInput(this)"
                              placeholder="Leave blank to use global default...">${prompt}</textarea>
                    <div class="manage-videos-prompt-footer">
                        <span class="manage-videos-save-status" id="manage-videos-status-${v.id}"></span>
                        <button class="manage-videos-save" disabled data-video-id="${v.id}" onclick="saveVideosPrompt(this)">Save</button>
                    </div>
                </div>`;
            }).join('<hr style="border:none;border-top:1px solid #21262d;margin:0">');
        }

        function closeManageVideos() {
            document.getElementById('manage-videos-modal').classList.remove('active');
            document.body.style.overflow = '';
        }

        function closeManageVideosBackdrop(event) {
            if (event.target === document.getElementById('manage-videos-modal')) closeManageVideos();
        }

        function onVideosPromptInput(textarea) {
            const videoId = textarea.dataset.videoId;
            const btn = document.querySelector(`#manage-videos-row-${videoId} .manage-videos-save`);
            btn.disabled = textarea.value.trim() === textarea.dataset.original;
        }

        async function saveVideosPrompt(btn) {
            const videoId = btn.dataset.videoId;
            const row = document.getElementById(`manage-videos-row-${videoId}`);
            const textarea = row.querySelector('.manage-videos-textarea');
            const statusEl = document.getElementById(`manage-videos-status-${videoId}`);
            const prompt = textarea.value.trim();
            btn.disabled = true;
            statusEl.textContent = 'Saving...';
            try {
                const resp = await fetch(`/api/prompts/${videoId}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({prompt})
                });
                if (!resp.ok) throw new Error(await resp.text());
                textarea.dataset.original = prompt;
                statusEl.textContent = 'Saved!';
                setTimeout(() => { statusEl.textContent = ''; }, 2000);
            } catch (e) {
                statusEl.textContent = 'Error';
                btn.disabled = false;
            }
        }
        // ---- End Manage Videos ----

        // ---- Infinite scroll + DOM recycling ----
        const BATCH_SIZE = 50;
        const MAX_BATCHES = 4; // max ~200 cards in DOM at once

        const urlParams = new URLSearchParams(window.location.search);
        const currentFilter = urlParams.get('filter') || 'captioned';
        const currentVideoFilter = {{ video_filter|tojson }};

        let nextPage = 1;
        let isLoading = false;
        let hasMore = true;
        let loadedBatches = []; // {el, height}
        let recycledTop = [];   // {html, height}
        let topSpacerHeight = 0;

        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function renderSceneCard(scene) {
            const caption = (scene.caption && !scene.caption.startsWith('__')) ? scene.caption : '';
            const imgSrc = scene.preview_path
                ? `/preview/${esc(scene.preview_path)}`
                : `/scene_preview/${scene.id}`;
            const tags = (scene.tags || []).map(tag =>
                `<span class="tag-pill" data-scene="${scene.id}" data-tag="${esc(tag)}">${esc(tag)}<button class="tag-remove" onclick="removeTagFromPill(this)">&#x2715;</button></span>`
            ).join('');
            return `<div class="scene-card" data-frame-count="${scene.frame_count}" data-video="${esc(scene.video_name)}">
                <div class="preview-container" onclick="playVideo('${esc(scene.video_path)}',${scene.start_frame},${scene.end_frame},${scene.id},${scene.start_time},${scene.end_time},${scene.fps},${scene.frame_offset})">
                    <img class="scene-preview" src="${imgSrc}" alt="Scene ${scene.id} preview" loading="lazy">
                    <div class="play-overlay"><div class="play-icon"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></div></div>
                </div>
                <div class="scene-info">
                    <div class="scene-meta">
                        <div>
                            <span class="scene-id">Scene #${scene.id}</span>
                            <div class="scene-video">${esc(scene.video_name)}</div>
                        </div>
                        <span class="scene-time">${esc(scene.start_time_hms)} (${scene.duration.toFixed(1)}s)</span>
                    </div>
                    <div class="caption-box" id="caption-box-${scene.id}" data-scene-id="${scene.id}">
                        <textarea class="caption-textarea"
                            id="caption-${scene.id}"
                            data-scene-id="${scene.id}"
                            data-original="${esc(caption)}"
                            placeholder="Enter caption..."
                            oninput="onCaptionChange(${scene.id})"
                            onblur="onCaptionBlur(event,${scene.id})"
                        >${esc(caption)}</textarea>
                        <div class="caption-footer">
                            <span class="caption-length" id="length-${scene.id}">${caption.length} chars</span>
                            <div class="caption-actions">
                                <span class="save-status" id="status-${scene.id}"></span>
                                <button class="revert-btn" id="revert-btn-${scene.id}" onclick="revertCaption(${scene.id})" style="display:none;">Revert</button>
                                <button class="delete-caption-btn" onclick="deleteCaption(${scene.id})" ${!caption ? 'style="display:none;"' : ''} id="delete-btn-${scene.id}">Delete</button>
                            </div>
                        </div>
                    </div>
                    <div class="tag-section" id="tag-section-${scene.id}">
                        ${tags}
                        <button class="tag-add-btn" id="tag-add-btn-${scene.id}" onclick="showTagDropdown(event,${scene.id})">+ Tag</button>
                    </div>
                </div>
            </div>`;
        }

        function recycleTopBatch() {
            const batch = loadedBatches.shift();
            const height = batch.el.getBoundingClientRect().height || batch.el.offsetHeight;
            recycledTop.push({ html: batch.el.outerHTML, height });
            batch.el.remove();
            topSpacerHeight += height;
            document.getElementById('top-spacer').style.height = topSpacerHeight + 'px';
        }

        function restoreTopBatch() {
            if (!recycledTop.length) return;
            const { html, height } = recycledTop.pop();
            topSpacerHeight -= height;
            document.getElementById('top-spacer').style.height = topSpacerHeight + 'px';
            const grid = document.getElementById('scenes-grid');
            const tmp = document.createElement('div');
            tmp.innerHTML = html;
            const el = tmp.firstElementChild;
            grid.insertBefore(el, grid.firstChild);
            loadedBatches.unshift({ el, height });
            applyTagFilter();
        }

        async function loadNextBatch() {
            if (isLoading || !hasMore) return;
            isLoading = true;
            document.getElementById('loading-indicator').style.display = 'block';

            try {
                const params = new URLSearchParams({ filter: currentFilter, page: nextPage, limit: BATCH_SIZE });
                if (currentVideoFilter) params.set('video', currentVideoFilter);
                const resp = await fetch('/api/scenes?' + params);
                if (!resp.ok) throw new Error('fetch failed');
                const data = await resp.json();

                if (data.scenes.length === 0 && nextPage === 1) {
                    const emptyEl = document.getElementById('empty-state');
                    const msg = document.getElementById('empty-state-msg');
                    emptyEl.style.display = '';
                    msg.textContent = currentFilter === 'captioned' ? 'No captioned scenes yet'
                        : currentFilter === 'uncaptioned' ? 'All scenes are captioned!'
                        : 'No scenes in database';
                }

                const grid = document.getElementById('scenes-grid');
                const batchEl = document.createElement('div');
                batchEl.className = 'scene-batch';
                batchEl.innerHTML = data.scenes.map(renderSceneCard).join('');
                grid.appendChild(batchEl);
                loadedBatches.push({ el: batchEl });

                applyTagFilter();

                if (loadedBatches.length > MAX_BATCHES) recycleTopBatch();

                hasMore = data.has_more;
                nextPage++;
            } catch(e) {
                console.error('Failed to load scenes', e);
            }

            isLoading = false;
            document.getElementById('loading-indicator').style.display = 'none';
        }

        // Bottom sentinel — load more when visible
        const bottomObserver = new IntersectionObserver(entries => {
            if (entries[0].isIntersecting) loadNextBatch();
        }, { rootMargin: '400px' });
        bottomObserver.observe(document.getElementById('bottom-sentinel'));

        // Top spacer — restore a recycled batch when user scrolls back up
        const topObserver = new IntersectionObserver(entries => {
            if (entries[0].isIntersecting && recycledTop.length) restoreTopBatch();
        }, { rootMargin: '400px' });
        topObserver.observe(document.getElementById('top-spacer'));

        // Initial load
        loadNextBatch();
        // ---- End infinite scroll ----

        // Load suggestions on page load
        loadTagSuggestions();

        // ---- Auto-refresh ----
        let autoRefreshTimer = null;
        const AR_KEY = 'autorefresh_enabled';

        async function doSoftRefresh() {
            // Skip if user has unsaved edits or tag dropdown is open
            if (modifiedCaptions.size > 0) return;
            if (tagDropdownSceneId != null) return;
            if (document.getElementById('video-modal')?.classList.contains('active')) return;
            try {
                const resp = await fetch('/api/stats', {cache: 'no-store'});
                if (!resp.ok) return;
                const data = await resp.json();

                // Update page title
                document.title = `Caption Review - ${data.captioned}/${data.total} scenes`;

                // Update stats bar
                const statVal = document.querySelector('.stat-value');
                if (statVal) statVal.textContent = `${data.captioned} / ${data.total}`;
                const fill = document.querySelector('.progress-fill');
                if (fill) fill.style.width = data.total > 0 ? `${(data.captioned / data.total * 100)}%` : '0%';
            } catch(e) { /* best-effort */ }
        }

        function startAutoRefresh() {
            if (autoRefreshTimer) return;
            autoRefreshTimer = setInterval(doSoftRefresh, 5000);
        }

        function stopAutoRefresh() {
            if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null; }
        }

        function onAutoRefreshToggle(enabled) {
            localStorage.setItem(AR_KEY, enabled ? '1' : '0');
            enabled ? startAutoRefresh() : stopAutoRefresh();
        }

        // Restore checkbox state from localStorage
        (function() {
            const cb = document.getElementById('autorefresh-toggle');
            const saved = localStorage.getItem(AR_KEY);
            if (saved === '1') { cb.checked = true; startAutoRefresh(); }
        })();
        // ---- End auto-refresh ----

        function closeVideo() {
            const modal = document.getElementById('video-modal');
            const video = document.getElementById('video-player');
            if (typeof frameRafId !== 'undefined' && frameRafId) { cancelAnimationFrame(frameRafId); frameRafId = null; }
            if (typeof frameInputFocused !== 'undefined') frameInputFocused = false;
            const frameInput = document.getElementById('video-frame-input');
            if (frameInput) frameInput.value = '';
            const tsDisplay = document.getElementById('video-ts-display');
            if (tsDisplay) tsDisplay.textContent = '';
            modal.classList.remove('active');
            document.body.style.overflow = '';
            video.pause();
            video.src = '';
            currentVideo = null;
        }

        function closeVideoOnBackdrop(event) {
            if (event.target === document.getElementById('video-modal')) {
                closeVideo();
            }
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const modal = document.getElementById('video-modal');
                if (modal.classList.contains('active')) closeVideo();
            }
        });
        </script>
    </body>
</html>
"""


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tags_table():
    """Create scene_tags table if it doesn't exist."""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scene_tags (
            scene_id INTEGER NOT NULL,
            tag      TEXT    NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scene_id, tag),
            FOREIGN KEY (scene_id) REFERENCES scenes(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()


try:
    ensure_tags_table()
except Exception:
    pass


def ensure_videos_prompt_column():
    """Add prompt column to videos table if it doesn't exist."""
    conn = get_db_connection()
    try:
        conn.execute("ALTER TABLE videos ADD COLUMN prompt TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    finally:
        conn.close()


try:
    ensure_videos_prompt_column()
except Exception:
    pass


def generate_scene_preview(
    video_path: Path,
    start_frame: int,
    end_frame: int,
    fps: float = 24.0,
    frame_offset: int = 0,
    frame_width: int = 426
) -> Optional[bytes]:
    """
    Generate a 3-frame preview image (start, middle, end) for a scene.
    
    This is reusable preview generation logic that can be called from:
    - Web server for on-the-fly preview generation
    - CLI for batch preview generation
    
    Args:
        video_path: Path to video file
        start_frame: First frame of scene (inclusive)
        end_frame: Last frame of scene (exclusive - first frame of next scene)
        fps: Video frame rate
        frame_offset: Frame offset compensation
        frame_width: Width of each frame in the composite
        
    Returns:
        PNG image bytes or None on failure
    """
    if not HAS_OPENCV or not HAS_PIL:
        return None
    
    if not video_path.exists():
        return None
    
    # Apply frame offset
    start_frame = max(0, start_frame + frame_offset)
    end_frame = end_frame + frame_offset
    
    # Calculate the three frames to extract
    first_frame = start_frame + 1
    last_frame = max(start_frame, end_frame - 1)
    middle_frame = first_frame + (last_frame - first_frame) // 2
    
    frames_to_get = [first_frame, middle_frame, last_frame]
    extracted_frames = []
    
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    
    try:
        for frame_num in frames_to_get:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            
            if ret:
                # Resize to target width
                h, w = frame.shape[:2]
                new_w = frame_width
                new_h = int(h * new_w / w)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                extracted_frames.append(Image.fromarray(frame))
            else:
                extracted_frames.append(None)
    finally:
        cap.release()
    
    if None in extracted_frames or len(extracted_frames) != 3:
        return None
    
    # Resize all frames to same height
    target_height = min(f.height for f in extracted_frames)
    resized_frames = []
    for f in extracted_frames:
        if f.height != target_height:
            ratio = target_height / f.height
            new_size = (int(f.width * ratio), target_height)
            f = f.resize(new_size, Image.LANCZOS)
        resized_frames.append(f)
    
    # Combine horizontally
    total_width = sum(f.width for f in resized_frames)
    combined = Image.new('RGB', (total_width, target_height))
    
    x_offset = 0
    for f in resized_frames:
        combined.paste(f, (x_offset, 0))
        x_offset += f.width
    
    # Convert to PNG bytes
    buffer = io.BytesIO()
    combined.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer.getvalue()


def find_preview_for_scene(video_name: str, scene_idx: int, start_frame: int = None) -> str | None:
    """Find preview image for a scene."""
    if not DEBUG_SCENES_DIR.exists():
        return None
    
    # Try to match by video name and scene index
    pattern = f"{video_name}_scene_{scene_idx:04d}_*.png"
    matches = list(DEBUG_SCENES_DIR.glob(pattern))
    if matches:
        return matches[0].name
    
    # Fallback: try looser matching
    for f in DEBUG_SCENES_DIR.iterdir():
        if f.suffix == '.png' and video_name in f.stem:
            # Extract scene number from filename
            match = re.search(r'scene_(\d+)', f.stem)
            if match and int(match.group(1)) == scene_idx:
                return f.name
    
    return None


@app.route('/')
def index():
    """Main page shell — scenes loaded via /api/scenes."""
    filter_type = request.args.get('filter', 'captioned')
    video_filter = request.args.get('video', '')

    conn = get_db_connection()

    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN caption IS NOT NULL AND caption != '' THEN 1 ELSE 0 END) as captioned
        FROM scenes
    """).fetchone()
    stats = dict(stats)

    if video_filter:
        all_tags = [r["tag"] for r in conn.execute(
            """SELECT DISTINCT st.tag FROM scene_tags st
               JOIN scenes s ON st.scene_id = s.id
               JOIN videos v ON s.video_id = v.id
               WHERE (v.path LIKE ? OR v.path LIKE ?)
               ORDER BY st.tag""",
            [f'%/{video_filter}.%', f'{video_filter}.%']
        ).fetchall()]
    else:
        all_tags = [r["tag"] for r in conn.execute(
            "SELECT DISTINCT tag FROM scene_tags ORDER BY tag"
        ).fetchall()]

    all_videos = [
        Path(r["path"]).stem for r in conn.execute(
            "SELECT DISTINCT path FROM videos ORDER BY path"
        ).fetchall()
    ]
    conn.close()

    return render_template_string(
        HTML_TEMPLATE,
        stats=stats,
        filter=filter_type,
        video_filter=video_filter,
        all_tags=all_tags,
        all_videos=all_videos,
    )


@app.route('/preview/<path:filename>')
def preview(filename):
    """Serve preview images."""
    return send_from_directory(DEBUG_SCENES_DIR, filename)


@app.route('/scene_preview/<int:scene_id>')
def scene_preview(scene_id: int):
    """
    Generate and serve a preview image for a scene on-the-fly.
    
    Falls back to static preview if it exists, otherwise generates dynamically.
    """
    conn = get_db_connection()
    
    # Get scene and video info
    row = conn.execute("""
        SELECT s.*, v.path as video_path, v.fps, v.frame_offset
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        WHERE s.id = ?
    """, (scene_id,)).fetchone()
    conn.close()
    
    if row is None:
        return jsonify({"error": "Scene not found"}), 404
    
    video_path = Path(row["video_path"])
    fps = row["fps"] or 24.0
    frame_offset = row["frame_offset"] or 0
    
    # Get frame numbers
    start_frame = row["start_frame"]
    end_frame = row["end_frame"]
    
    # Fall back to calculating from timestamps if frames not stored
    if start_frame is None or end_frame is None:
        start_frame = int(row["start_time"] * fps)
        end_frame = int(row["end_time"] * fps)
    
    # Generate preview
    preview_bytes = generate_scene_preview(
        video_path=video_path,
        start_frame=start_frame,
        end_frame=end_frame,
        fps=fps,
        frame_offset=frame_offset,
        frame_width=426
    )
    
    if preview_bytes is None:
        return jsonify({"error": "Failed to generate preview"}), 500
    
    return Response(
        preview_bytes,
        mimetype='image/png',
        headers={'Cache-Control': 'max-age=3600'}  # Cache for 1 hour
    )


@app.route('/clip/<int:scene_id>')
def serve_clip(scene_id: int):
    """Extract and serve a video clip using ffmpeg, with frame_offset applied as time_offset."""
    import subprocess

    # Look up scene + video info from DB
    conn = get_db_connection()
    row = conn.execute("""
        SELECT s.start_time, s.end_time, s.start_frame, s.end_frame,
               v.path as video_path, v.fps, v.frame_offset
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        WHERE s.id = ?
    """, (scene_id,)).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Scene not found"}), 404

    video_file = Path(row["video_path"])
    if not video_file.exists():
        return jsonify({"error": "Video file not found"}), 404

    fps = row["fps"] or 24.0
    frame_offset = row["frame_offset"] or 0

    # Derive timestamps from frame numbers for precision; fall back to stored times
    # Add 1 to start_frame to compensate for ffmpeg fast-seek landing one frame early
    if row["start_frame"] is not None and row["end_frame"] is not None:
        start_time = (row["start_frame"] + frame_offset + 1) / fps
        end_time = (row["end_frame"] + frame_offset) / fps
    else:
        time_offset = frame_offset / fps
        start_time = max(0.0, row["start_time"] + time_offset + 1.0 / fps)
        end_time = row["end_time"] + time_offset

    start_time = max(0.0, start_time)
    duration = end_time - start_time

    if duration <= 0:
        return jsonify({"error": "Invalid time range"}), 400

    # Single accurate seek: -ss before -i for speed, -to for precise end
    cmd = [
        'ffmpeg',
        '-ss', f'{start_time:.6f}',
        '-i', str(video_file),
        '-t', f'{duration:.6f}',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '23',
        '-c:a', 'aac',
        '-movflags', 'frag_keyframe+empty_moov+faststart',
        '-f', 'mp4',
        '-y',
        'pipe:1'
    ]
    
    def generate():
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=8192
        )
        try:
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                yield chunk
        finally:
            process.stdout.close()
            process.wait()
    
    return Response(
        generate(),
        mimetype='video/mp4',
        headers={
            'Content-Type': 'video/mp4',
            'Cache-Control': 'no-cache'
        }
    )


@app.route('/api/scenes')
def get_scenes():
    """Return paginated scene data as JSON for infinite scroll."""
    filter_type = request.args.get('filter', 'captioned')
    video_filter = request.args.get('video', '')
    page = max(1, int(request.args.get('page', 1) or 1))
    limit = 50

    conn = get_db_connection()

    conditions = []
    params = []

    if filter_type == 'captioned':
        conditions.append("s.caption IS NOT NULL AND s.caption != ''")
    elif filter_type == 'uncaptioned':
        conditions.append("(s.caption IS NULL OR s.caption = '')")

    if video_filter:
        conditions.append("(v.path LIKE ? OR v.path LIKE ?)")
        params.extend([f'%/{video_filter}.%', f'{video_filter}.%'])

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM scenes s JOIN videos v ON s.video_id = v.id {where_clause}",
        params
    ).fetchone()[0]

    offset = (page - 1) * limit
    rows = conn.execute(f"""
        SELECT s.*, v.path as video_path, v.fps, v.frame_offset,
            (SELECT COUNT(*) FROM scenes s2 WHERE s2.video_id = s.video_id AND s2.id < s.id) as scene_idx,
            GROUP_CONCAT(st.tag, '|') as tags_concat
        FROM scenes s
        JOIN videos v ON s.video_id = v.id
        LEFT JOIN scene_tags st ON st.scene_id = s.id
        {where_clause}
        GROUP BY s.id
        ORDER BY s.video_id, s.id
        LIMIT {limit} OFFSET {offset}
    """, params).fetchall()
    conn.close()

    scenes = []
    for row in rows:
        d = dict(row)
        video_path = Path(d['video_path'])
        video_name = video_path.stem
        scene_idx = d['scene_idx']
        duration = d['end_time'] - d['start_time']
        t = int(d['start_time'])
        caption = d.get('caption') or ''
        tags_raw = d.get('tags_concat') or ''
        preview_path = find_preview_for_scene(video_name, scene_idx, d.get('start_frame'))
        scenes.append({
            'id': d['id'],
            'video_name': video_name,
            'video_path': d['video_path'],
            'start_frame': d.get('start_frame') or 0,
            'end_frame': d.get('end_frame') or 0,
            'start_time': d['start_time'],
            'end_time': d['end_time'],
            'fps': d.get('fps') or 24.0,
            'frame_offset': d.get('frame_offset') or 0,
            'caption': caption,
            'tags': [t for t in tags_raw.split('|') if t],
            'start_time_hms': f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}",
            'duration': duration,
            'frame_count': (d.get('end_frame') or 0) - (d.get('start_frame') or 0),
            'preview_path': preview_path,
        })

    return jsonify({
        'scenes': scenes,
        'page': page,
        'has_more': offset + limit < total,
        'total': total,
    })


@app.route('/api/stats')
def api_stats():
    """Get caption stats as JSON."""
    conn = get_db_connection()
    stats = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN caption IS NOT NULL AND caption != '' THEN 1 ELSE 0 END) as captioned
        FROM scenes
    """).fetchone()
    conn.close()
    return jsonify(dict(stats))


@app.route('/api/caption/<int:scene_id>', methods=['GET'])
def get_caption(scene_id: int):
    """Get caption for a specific scene."""
    conn = get_db_connection()
    row = conn.execute("SELECT id, caption FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    conn.close()
    
    if row is None:
        return jsonify({"error": "Scene not found"}), 404
    
    return jsonify({"id": row["id"], "caption": row["caption"]})


@app.route('/api/caption/<int:scene_id>', methods=['PUT'])
def update_caption(scene_id: int):
    """Update caption for a specific scene."""
    data = request.get_json()
    if data is None or "caption" not in data:
        return jsonify({"error": "Missing caption field"}), 400
    
    caption = data["caption"].strip() if data["caption"] else None
    
    conn = get_db_connection()
    
    # Check if scene exists
    row = conn.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404
    
    # Update caption
    conn.execute("UPDATE scenes SET caption = ? WHERE id = ?", (caption, scene_id))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "id": scene_id, "caption": caption})


@app.route('/api/tags/all', methods=['GET'])
def get_all_tags():
    """Return all distinct tags in the DB for autocomplete."""
    video_filter = request.args.get('video', '')
    conn = get_db_connection()
    if video_filter:
        rows = conn.execute(
            """SELECT DISTINCT st.tag FROM scene_tags st
               JOIN scenes s ON st.scene_id = s.id
               JOIN videos v ON s.video_id = v.id
               WHERE (v.path LIKE ? OR v.path LIKE ?)
               ORDER BY st.tag""",
            [f'%/{video_filter}.%', f'{video_filter}.%']
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT tag FROM scene_tags ORDER BY tag"
        ).fetchall()
    conn.close()
    return jsonify({"tags": [r["tag"] for r in rows]})


@app.route('/api/tags/<int:scene_id>', methods=['GET'])
def get_tags(scene_id: int):
    """Get all tags for a scene."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = ? ORDER BY created_at, tag",
        (scene_id,)
    ).fetchall()
    conn.close()
    return jsonify({"scene_id": scene_id, "tags": [r["tag"] for r in rows]})


@app.route('/api/tags/<int:scene_id>', methods=['POST'])
def add_tag(scene_id: int):
    """Add a tag to a scene."""
    data = request.get_json()
    if not data or not data.get("tag"):
        return jsonify({"error": "Missing tag"}), 400
    tag = data["tag"].strip().lower()
    if not tag:
        return jsonify({"error": "Empty tag"}), 400

    conn = get_db_connection()
    if conn.execute("SELECT id FROM scenes WHERE id = ?", (scene_id,)).fetchone() is None:
        conn.close()
        return jsonify({"error": "Scene not found"}), 404

    conn.execute(
        "INSERT OR IGNORE INTO scene_tags (scene_id, tag) VALUES (?, ?)",
        (scene_id, tag)
    )
    conn.commit()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = ? ORDER BY created_at, tag",
        (scene_id,)
    ).fetchall()
    conn.close()
    return jsonify({"scene_id": scene_id, "tags": [r["tag"] for r in rows]})


@app.route('/api/tags/rename', methods=['PUT'])
def rename_tag():
    """Rename a tag globally across all scenes."""
    data = request.get_json()
    if not data or not data.get('old_tag') or not data.get('new_tag'):
        return jsonify({"error": "Missing old_tag or new_tag"}), 400
    old_tag = data['old_tag'].strip().lower()
    new_tag = data['new_tag'].strip().lower()
    if not old_tag or not new_tag:
        return jsonify({"error": "Empty tag"}), 400
    if old_tag == new_tag:
        return jsonify({"updated": 0}), 200

    conn = get_db_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM scene_tags WHERE tag = ?", (old_tag,)
    ).fetchone()[0]
    # For scenes that already have new_tag, the INSERT is ignored (no duplicate)
    conn.execute(
        "INSERT OR IGNORE INTO scene_tags (scene_id, tag, created_at) "
        "SELECT scene_id, ?, created_at FROM scene_tags WHERE tag = ?",
        (new_tag, old_tag)
    )
    conn.execute("DELETE FROM scene_tags WHERE tag = ?", (old_tag,))
    conn.commit()
    conn.close()
    return jsonify({"updated": count})


@app.route('/api/tags/<int:scene_id>/<path:tag>', methods=['DELETE'])
def remove_tag(scene_id: int, tag: str):
    """Remove a tag from a scene."""
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM scene_tags WHERE scene_id = ? AND tag = ?",
        (scene_id, tag)
    )
    conn.commit()
    rows = conn.execute(
        "SELECT tag FROM scene_tags WHERE scene_id = ? ORDER BY created_at, tag",
        (scene_id,)
    ).fetchall()
    conn.close()
    return jsonify({"scene_id": scene_id, "tags": [r["tag"] for r in rows]})


@app.route('/api/videos', methods=['GET'])
def get_videos():
    """Return all videos with full metadata and scene/caption counts."""
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM videos ORDER BY path").fetchall()
    result = []
    for r in rows:
        v = dict(r)
        counts = conn.execute(
            """SELECT
                COUNT(*) as scene_count,
                SUM(CASE WHEN caption IS NOT NULL AND caption != '' AND substr(caption, 1, 2) != '__' THEN 1 ELSE 0 END) as captioned
               FROM scenes WHERE video_id = ?""",
            (v["id"],)
        ).fetchone()
        result.append({
            "id": v["id"],
            "name": Path(v["path"]).name,
            "path": v["path"],
            "hash": v["hash"],
            "duration": v.get("duration"),
            "fps": v.get("fps"),
            "width": v.get("width"),
            "height": v.get("height"),
            "codec": v.get("codec"),
            "frame_offset": v.get("frame_offset") or 0,
            "prompt": v.get("prompt") or "",
            "indexed_at": v.get("indexed_at"),
            "scene_count": counts["scene_count"] or 0,
            "captioned": counts["captioned"] or 0,
        })
    conn.close()
    return jsonify({"videos": result})


@app.route('/api/prompts', methods=['GET'])
def get_prompts():
    """Return all videos with their captioning prompts."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, path, prompt FROM videos ORDER BY path"
    ).fetchall()
    conn.close()
    return jsonify({
        "videos": [
            {"id": r["id"], "name": Path(r["path"]).name, "prompt": r["prompt"] or ""}
            for r in rows
        ]
    })


@app.route('/api/prompts/<int:video_id>', methods=['PUT'])
def set_prompt(video_id: int):
    """Set the captioning prompt for a video."""
    data = request.get_json()
    prompt = (data.get("prompt") or "").strip() or None
    conn = get_db_connection()
    conn.execute("UPDATE videos SET prompt = ? WHERE id = ?", (prompt, video_id))
    conn.commit()
    conn.close()
    return jsonify({"video_id": video_id, "prompt": prompt or ""})


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description="Web frontend for caption review")
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print(f"Caption Review Server")
    print(f"{'='*50}")
    print(f"Database: {DB_PATH}")
    print(f"Previews: {DEBUG_SCENES_DIR}")
    print(f"URL: http://{args.host}:{args.port}")
    print(f"{'='*50}\n")
    
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
