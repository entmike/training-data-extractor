#!/usr/bin/env bash
# restart.sh — kill and restart backend + Vite dev server + node timing daemon in tmux sessions
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
#   config.yaml      → ""           → backend / vite / comfy-timing
#   config-ph.yaml   → "-ph"        → backend-ph / vite-ph / comfy-timing-ph
#   anything else    → "-<basename>"
CONFIG_BASENAME=$(basename "$CONFIG" .yaml)
if [[ "$CONFIG_BASENAME" == "config" ]]; then
    SUFFIX=""
else
    SUFFIX="-${CONFIG_BASENAME#config-}"
fi
BACKEND_SESSION="backend${SUFFIX}"
VITE_SESSION="vite${SUFFIX}"
TIMING_SESSION="comfy-timing${SUFFIX}"
WEB_LOG="/tmp/web_review${SUFFIX}.log"
VITE_LOG="/tmp/vite${SUFFIX}.log"
TIMING_LOG="/tmp/comfy_timing${SUFFIX}.log"

# Read ports from config YAML
FLASK_PORT="$($VENV/python -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c.get('flask_port', 5000))" 2>/dev/null)"
VITE_PORT="$($VENV/python  -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c.get('vite_port', 5173))" 2>/dev/null)"

echo "Config:  $CONFIG"
echo "Flask:   port $FLASK_PORT  (session: $BACKEND_SESSION)"
echo "Vite:    port $VITE_PORT  (session: $VITE_SESSION)"
echo "ComfyUI: node-timing daemon (session: $TIMING_SESSION)"

# ── Kill existing processes for THIS config only ──────────────────────────────
echo "Stopping existing processes..."
tmux kill-session -t "$BACKEND_SESSION" 2>/dev/null || true
tmux kill-session -t "$VITE_SESSION"    2>/dev/null || true
tmux kill-session -t "$TIMING_SESSION"  2>/dev/null || true
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
NODE_BIN="/home/mike/.nvm/versions/node/v24.14.0/bin/node"
echo "Starting Vite dev server..."
tmux new-session -d -s "$VITE_SESSION" \
    "cd $DIR/ui && FLASK_PORT=$FLASK_PORT $NODE_BIN node_modules/.bin/vite --port $VITE_PORT 2>&1 | tee $VITE_LOG"

for i in $(seq 1 15); do
    if curl -sf "http://localhost:${VITE_PORT}/src/main.jsx" > /dev/null 2>&1; then
        echo "Vite up"
        break
    fi
    sleep 1
done

# ── ComfyUI Node Timing Daemon ────────────────────────────────────────────────
echo "Starting node timing daemon..."
tmux new-session -d -s "$TIMING_SESSION" \
    "LTX_CONFIG=$CONFIG $VENV/ltx2-build --step scan-comfy-node-timing 2>&1 | tee $TIMING_LOG"

echo ""
echo "Done. Processes running in tmux sessions:"
echo "  tmux attach -t $BACKEND_SESSION   — Flask API  (http://localhost:${FLASK_PORT})"
echo "  tmux attach -t $VITE_SESSION      — Vite UI    (http://localhost:${VITE_PORT})"
echo "  tmux attach -t $TIMING_SESSION    — Node timing daemon"
echo "Logs: $WEB_LOG  $VITE_LOG  $TIMING_LOG"
