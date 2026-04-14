#!/usr/bin/env bash
# restart.sh — kill and restart backend + Vite dev server in tmux sessions
# Usage: ./restart.sh [config.yaml]

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv/bin"

CONFIG="${1:-config.yaml}"
# Resolve relative to script dir if not absolute
[[ "$CONFIG" != /* ]] && CONFIG="$DIR/$CONFIG"

if [[ ! -f "$CONFIG" ]]; then
    echo "Config file not found: $CONFIG" >&2
    exit 1
fi

# Read ports from config YAML
FLASK_PORT=$("$VENV/python" -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c.get('flask_port', 5000))")
VITE_PORT=$("$VENV/python"  -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c.get('vite_port', 5173))")

echo "Config:  $CONFIG"
echo "Flask:   port $FLASK_PORT"
echo "Vite:    port $VITE_PORT"

# ── Kill existing processes ────────────────────────────────────────────────────
echo "Stopping existing processes..."
tmux kill-session -t backend  2>/dev/null || true
tmux kill-session -t vite     2>/dev/null || true
fuser -k "${FLASK_PORT}/tcp"  2>/dev/null || true
fuser -k "${VITE_PORT}/tcp"   2>/dev/null || true
sleep 1

# ── Backend (Flask API) ────────────────────────────────────────────────────────
echo "Starting backend..."
tmux new-session -d -s backend \
    "LTX_CONFIG=$CONFIG $VENV/python $DIR/web_review.py --host 0.0.0.0 --port $FLASK_PORT 2>&1 | tee /tmp/web_review.log"

for i in $(seq 1 15); do
    if curl -sf "http://localhost:${FLASK_PORT}/api/stats" > /dev/null 2>&1; then
        echo "Backend up"
        break
    fi
    sleep 1
done

# ── Vite dev server ────────────────────────────────────────────────────────────
echo "Starting Vite dev server..."
tmux new-session -d -s vite \
    "cd $DIR/ui && FLASK_PORT=$FLASK_PORT node_modules/.bin/vite --port $VITE_PORT 2>&1 | tee /tmp/vite.log"

for i in $(seq 1 15); do
    if curl -sf "http://localhost:${VITE_PORT}/src/main.jsx" > /dev/null 2>&1; then
        echo "Vite up"
        break
    fi
    sleep 1
done

echo ""
echo "Done. Processes running in tmux sessions:"
echo "  tmux attach -t backend   — Flask API  (http://localhost:${FLASK_PORT})"
echo "  tmux attach -t vite      — Vite UI    (http://localhost:${VITE_PORT})"
echo "Logs: /tmp/web_review.log  /tmp/vite.log"
