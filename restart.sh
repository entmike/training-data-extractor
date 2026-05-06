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

# Derive a per-config suffix so multiple configs can run side-by-side.
#   config.yaml      → ""           → backend / vite
#   config-ph.yaml   → "-ph"        → backend-ph / vite-ph
#   anything else    → "-<basename>"
CONFIG_BASENAME=$(basename "$CONFIG" .yaml)
if [[ "$CONFIG_BASENAME" == "config" ]]; then
    SUFFIX=""
else
    SUFFIX="-${CONFIG_BASENAME#config-}"
fi
BACKEND_SESSION="backend${SUFFIX}"
VITE_SESSION="vite${SUFFIX}"
WEB_LOG="/tmp/web_review${SUFFIX}.log"
VITE_LOG="/tmp/vite${SUFFIX}.log"

# Read ports from config YAML
FLASK_PORT=$("$VENV/python" -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c.get('flask_port', 5000))")
VITE_PORT=$("$VENV/python"  -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c.get('vite_port', 5173))")

echo "Config:  $CONFIG"
echo "Flask:   port $FLASK_PORT  (session: $BACKEND_SESSION)"
echo "Vite:    port $VITE_PORT  (session: $VITE_SESSION)"

# ── Kill existing processes for THIS config only ──────────────────────────────
echo "Stopping existing processes..."
tmux kill-session -t "$BACKEND_SESSION" 2>/dev/null || true
tmux kill-session -t "$VITE_SESSION"    2>/dev/null || true
fuser -k "${FLASK_PORT}/tcp"            2>/dev/null || true
fuser -k "${VITE_PORT}/tcp"             2>/dev/null || true
sleep 1

# ── Backend (Flask API) ────────────────────────────────────────────────────────
echo "Starting backend..."
tmux new-session -d -s "$BACKEND_SESSION" \
    "LTX_CONFIG=$CONFIG $VENV/python $DIR/web_review.py --host 0.0.0.0 --port $FLASK_PORT 2>&1 | tee $WEB_LOG"

for i in $(seq 1 15); do
    if curl -sf "http://localhost:${FLASK_PORT}/api/stats" > /dev/null 2>&1; then
        echo "Backend up"
        break
    fi
    sleep 1
done

# ── Vite dev server ────────────────────────────────────────────────────────────
echo "Starting Vite dev server..."
tmux new-session -d -s "$VITE_SESSION" \
    "cd $DIR/ui && FLASK_PORT=$FLASK_PORT node_modules/.bin/vite --port $VITE_PORT 2>&1 | tee $VITE_LOG"

for i in $(seq 1 15); do
    if curl -sf "http://localhost:${VITE_PORT}/src/main.jsx" > /dev/null 2>&1; then
        echo "Vite up"
        break
    fi
    sleep 1
done

echo ""
echo "Done. Processes running in tmux sessions:"
echo "  tmux attach -t $BACKEND_SESSION   — Flask API  (http://localhost:${FLASK_PORT})"
echo "  tmux attach -t $VITE_SESSION      — Vite UI    (http://localhost:${VITE_PORT})"
echo "Logs: $WEB_LOG  $VITE_LOG"
