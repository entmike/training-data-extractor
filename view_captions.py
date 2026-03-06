#!/usr/bin/env python3
"""View scene captions from the database."""

import sqlite3
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="View scene captions from database")
    parser.add_argument("--db", type=str, default=".cache/index.db", help="Database path")
    parser.add_argument("--limit", type=int, default=20, help="Number of captions to show")
    parser.add_argument("--all", action="store_true", help="Show all captions")
    parser.add_argument("--empty", action="store_true", help="Show scenes without captions")
    args = parser.parse_args()
    
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get stats
    stats = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN caption IS NOT NULL AND caption != '' THEN 1 ELSE 0 END) as captioned
        FROM scenes
    """).fetchone()
    
    print(f"\n{'='*60}")
    print(f"Scene Captions: {stats['captioned']} / {stats['total']}")
    print(f"{'='*60}\n")
    
    # Query based on args
    if args.empty:
        query = "SELECT s.*, v.path as video_path FROM scenes s JOIN videos v ON s.video_id = v.id WHERE s.caption IS NULL OR s.caption = '' ORDER BY s.id"
    else:
        query = "SELECT s.*, v.path as video_path FROM scenes s JOIN videos v ON s.video_id = v.id WHERE s.caption IS NOT NULL AND s.caption != '' ORDER BY s.id"
    
    if not args.all:
        query += f" LIMIT {args.limit}"
    
    rows = conn.execute(query).fetchall()
    
    for row in rows:
        video_name = Path(row['video_path']).stem[:30]
        start = row['start_time']
        end = row['end_time']
        duration = end - start
        caption = row['caption'] or "(no caption)"
        
        print(f"Scene {row['id']:04d} | {video_name}")
        print(f"  Time: {start:.2f}s - {end:.2f}s ({duration:.2f}s)")
        print(f"  Caption: {caption}")
        print()
    
    conn.close()
    return 0


if __name__ == "__main__":
    exit(main())
