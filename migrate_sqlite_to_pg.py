#!/usr/bin/env python3
"""Migrate data from SQLite (.cache/index.db) to PostgreSQL.

Usage:
    python migrate_sqlite_to_pg.py
    python migrate_sqlite_to_pg.py --sqlite .cache/index.db --pg postgresql://ltx2:ltx2@localhost:5432/ltx2
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

# ── Config ────────────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent

def _load_dsn_from_env():
    env_file = _HERE / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                os.environ.setdefault(k.strip(), v.strip())

def _load_dsn_from_config():
    import yaml
    config_path = _HERE / 'config.yaml'
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return data.get('pg_dsn')
    return None

# ── Migration ─────────────────────────────────────────────────────────────────

# Tables migrated in FK-safe order. Each entry: (table, [column_names])
# We read all rows from SQLite and insert into PG preserving original IDs.
# Sequences are reset at the end so future INSERTs don't collide.

TABLES = [
    "videos",
    "scenes",
    "scene_tags",
    "tag_definitions",
    "buckets",
    "candidates",
    "face_detections",
    "embeddings",
    "samples",
    "clips",
    "clip_items",
]

# Tables with SERIAL primary keys that need sequence reset after import
SERIAL_TABLES = {
    "videos":          "videos_id_seq",
    "scenes":          "scenes_id_seq",
    "buckets":         "buckets_id_seq",
    "candidates":      "candidates_id_seq",
    "face_detections": "face_detections_id_seq",
    "embeddings":      "embeddings_id_seq",
    "samples":         "samples_id_seq",
    "clips":           "clips_id_seq",
    "clip_items":      "clip_items_id_seq",
}


def get_sqlite_columns(sqlite_cur, table: str) -> list[str]:
    sqlite_cur.execute(f"PRAGMA table_info({table})")
    rows = sqlite_cur.fetchall()
    return [r[1] for r in rows]  # column name is index 1


def get_pg_columns(pg_cur, table: str) -> list[str]:
    pg_cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
        ORDER BY ordinal_position
    """, (table,))
    return [r['column_name'] for r in pg_cur.fetchall()]


def migrate_table(sqlite_conn, pg_conn, table: str, verbose: bool = True):
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get columns from both sides; use intersection (pg schema is authoritative)
    sqlite_cols = get_sqlite_columns(sqlite_cur, table)
    pg_cols = get_pg_columns(pg_cur, table)

    if not sqlite_cols:
        print(f"  {table}: not found in SQLite, skipping")
        return 0
    if not pg_cols:
        print(f"  {table}: not found in PostgreSQL — run the server once to init schema")
        return 0

    # Use columns present in both, preserving PG column order
    shared_cols = [c for c in pg_cols if c in sqlite_cols]
    if not shared_cols:
        print(f"  {table}: no shared columns, skipping")
        return 0

    sqlite_cur.execute(f"SELECT {', '.join(shared_cols)} FROM {table}")
    rows = sqlite_cur.fetchall()

    if not rows:
        print(f"  {table}: 0 rows, nothing to migrate")
        return 0

    col_list = ', '.join(shared_cols)
    placeholders = ', '.join(['%s'] * len(shared_cols))

    # Truncate target table first (respecting FK order via TRUNCATE ... CASCADE or per-table)
    pg_cur.execute(f"DELETE FROM {table}")

    inserted = 0
    for row in rows:
        values = []
        for val in row:
            # Convert memoryview/bytes for BYTEA columns
            if isinstance(val, memoryview):
                val = bytes(val)
            values.append(val)
        try:
            pg_cur.execute(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                values
            )
            inserted += 1
        except Exception as e:
            print(f"  WARNING: row insert failed in {table}: {e}")
            pg_conn.rollback()
            # Re-start transaction
            pg_cur = pg_conn.cursor()

    pg_conn.commit()
    print(f"  {table}: {inserted}/{len(rows)} rows migrated")
    return inserted


def reset_sequences(pg_conn):
    """Reset SERIAL sequences so next INSERT gets the right ID."""
    cur = pg_conn.cursor()
    for table, seq in SERIAL_TABLES.items():
        cur.execute(f"""
            SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 1))
        """)
    pg_conn.commit()
    print("Sequences reset.")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite → PostgreSQL")
    parser.add_argument('--sqlite', default='.cache/index.db', help='SQLite DB path')
    parser.add_argument('--pg', default=None, help='PostgreSQL DSN (overrides config/env)')
    args = parser.parse_args()

    _load_dsn_from_env()
    pg_dsn = args.pg or _load_dsn_from_config() or os.environ.get('DATABASE_URL')
    if not pg_dsn:
        print("ERROR: No PostgreSQL DSN found. Pass --pg or set DATABASE_URL in .env")
        sys.exit(1)

    sqlite_path = _HERE / args.sqlite
    if not sqlite_path.exists():
        print(f"ERROR: SQLite DB not found: {sqlite_path}")
        sys.exit(1)

    print(f"Source:      {sqlite_path}")
    print(f"Destination: {pg_dsn}")
    print()

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = None  # return plain tuples for migration

    try:
        pg_conn = psycopg2.connect(pg_dsn)
    except Exception as e:
        print(f"ERROR: Cannot connect to PostgreSQL: {e}")
        sys.exit(1)

    print("Migrating tables (in FK-safe order):")
    for table in TABLES:
        migrate_table(sqlite_conn, pg_conn, table)

    print()
    reset_sequences(pg_conn)

    sqlite_conn.close()
    pg_conn.close()
    print("\nMigration complete.")


if __name__ == '__main__':
    main()
