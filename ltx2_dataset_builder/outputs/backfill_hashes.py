"""Backfill prompt_hash for outputs and comfy_queue rows that lack it."""

import json
import hashlib
import sys
import psycopg2
from psycopg2.extras import RealDictCursor


def backfill_output_hashes(dsn):
    """Update outputs rows with NULL prompt_hash where prompt is not NULL."""
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, prompt FROM outputs WHERE prompt IS NOT NULL AND prompt_hash IS NULL"
        )
        rows = cur.fetchall()
        updated = 0
        for row in rows:
            prompt_obj = row['prompt']
            prompt_hash = hashlib.sha256(
                json.dumps(prompt_obj, sort_keys=True).encode('utf-8')
            ).hexdigest()
            cur.execute(
                "UPDATE outputs SET prompt_hash = %s WHERE id = %s",
                (prompt_hash, row['id']),
            )
            updated += 1
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backfill_queue_hashes(dsn):
    """Update comfy_queue rows with NULL prompt_hash where prompt is not NULL."""
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT prompt_id, prompt FROM comfy_queue WHERE prompt IS NOT NULL AND prompt_hash IS NULL"
        )
        rows = cur.fetchall()
        updated = 0
        for row in rows:
            prompt_obj = row['prompt']
            prompt_hash = hashlib.sha256(
                json.dumps(prompt_obj, sort_keys=True).encode('utf-8')
            ).hexdigest()
            cur.execute(
                "UPDATE comfy_queue SET prompt_hash = %s WHERE prompt_id = %s",
                (prompt_hash, row['prompt_id']),
            )
            updated += 1
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: backfill_hashes.py <pg_dsn>", file=sys.stderr)
        sys.exit(1)

    dsn = sys.argv[1]
    dsn_preview = dsn[:dsn.rfind('@')]
    print(f"Backfilling prompt_hash using DSN: {dsn_preview}...")
    out_count = backfill_output_hashes(dsn)
    q_count = backfill_queue_hashes(dsn)
    print(f"Done: {out_count} outputs + {q_count} comfy_queue rows backfilled")


if __name__ == '__main__':
    main()