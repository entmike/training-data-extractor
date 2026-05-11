#!/usr/bin/env bash
# Daily PostgreSQL backup for ltx2, ltx2-ph, photo_album
set -euo pipefail

BACKUP_DIR="/mnt/data/code/training-data-extractor/backups"
CONTAINER="training-data-extractor-db-1"
DBS="ltx2 ltx2-ph photo_album"
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

for db in $DBS; do
    ts=$(date +%Y-%m-%d_%H%M%S)
    file="${BACKUP_DIR}/${db}_${ts}.sql.gz"
    echo "Backing up $db -> $file"
    docker exec $CONTAINER pg_dump -U ltx2 -d "$db" | gzip > "$file"
done

# Cleanup old backups
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "Backup complete."
