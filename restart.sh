#!/usr/bin/env bash
# restart.sh — kill and restart backend + Vite dev server in tmux sessions
# Usage: ./restart.sh

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv/bin"

# ── Kill existing processes ────────────────────────────────────────────────────
echo "Stopping existing processes..."
tmux kill-session -t backend  2>/dev/null || true
tmux kill-session -t vite     2>/dev/null || true
fuser -k 5000/tcp             2>/dev/null || true
fuser -k 5173/tcp             2>/dev/null || true
sleep 1

# ── Backend (Flask API) ────────────────────────────────────────────────────────
echo "Starting backend..."
tmux new-session -d -s backend \
    "$VENV/python $DIR/web_review.py --host 0.0.0.0 2>&1 | tee /tmp/web_review.log"

for i in $(seq 1 15); do
    if curl -sf http://localhost:5000/api/stats > /dev/null 2>&1; then
        echo "Backend up"
        break
    fi
    sleep 1
done

# ── Vite dev server ────────────────────────────────────────────────────────────
echo "Starting Vite dev server..."
tmux new-session -d -s vite \
    "cd $DIR/ui && node_modules/.bin/vite 2>&1 | tee /tmp/vite.log"

for i in $(seq 1 15); do
    if curl -sf http://localhost:5173/src/main.jsx > /dev/null 2>&1; then
        echo "Vite up"
        break
    fi
    sleep 1
done

echo ""
echo "Done. Processes running in tmux sessions:"
echo "  tmux attach -t backend   — Flask API  (http://localhost:5000)"
echo "  tmux attach -t vite      — Vite UI    (http://localhost:5173)"
echo "Logs: /tmp/web_review.log  /tmp/vite.log"
