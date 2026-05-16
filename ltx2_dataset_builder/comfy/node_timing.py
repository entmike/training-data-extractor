"""
Background WebSocket daemon for per-node ComfyUI timing.

Connects to ComfyUI's WebSocket and captures per-node start/end times,
progress steps, and durations — all persisted to `comfy_node_timing`
table. Runs independently of any browser session.

Events handled:
  execution_start  → reset state for new prompt
  executing          → mark previous node complete, start new node
  progress           → update step progress for current node
  execution_success  → mark last node complete
  execution_error    → mark last node complete with error

Usage:
    ltx2-build --step scan-comfy-node-timing [--daemon]
"""

import json
import logging
import signal
import time
import urllib.request
import websocket
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Per-prompt state tracking
_active_prompt: Optional[str] = None
_ws_client_id = __name__ + "-ws-client"


def _resolve_endpoint(db) -> Optional[str]:
    val = db.get_config_value('comfyui_endpoint')
    return val.rstrip('/') if val else None


def run_daemon(db, endpoint_override: Optional[str] = None, outputs_dir: Optional[Path] = None) -> None:
    """Connect to ComfyUI WebSocket and persist node timing data."""
    endpoint = endpoint_override or _resolve_endpoint(db)
    if not endpoint:
        logger.warning("ComfyUI endpoint not configured — cannot start node timing daemon")
        return

    ws_url = endpoint.replace('http://', 'ws://').replace('https://', 'wss://')
    ws_url = f"{ws_url}/ws?clientId={_ws_client_id}"

    running = True

    def _stop(sig, _frame):
        nonlocal running
        logger.info("Node timing daemon received signal %d, stopping…", sig)
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    def on_message(ws, raw):
        global _active_prompt
        try:
            msg = json.loads(raw)
            mtype = msg.get('type')
            data = msg.get('data', {})

            if mtype == 'execution_start':
                pid = data.get('prompt_id')
                if pid:
                    # Complete any leftover nodes from previous prompt
                    if _active_prompt and _active_prompt != pid:
                        db.complete_last_node(_active_prompt)
                    _active_prompt = pid
                    logger.debug("  execution_start: %s", pid)

            elif mtype == 'executing':
                node = data.get('node')
                if node is not None:
                    # Bootstrap _active_prompt from /queue if not yet set
                    if not _active_prompt:
                        try:
                            qdata = json.loads(
                                urllib.request.urlopen(
                                    endpoint.rstrip('/') + '/queue', timeout=5
                                ).read()
                            )
                            running = qdata.get('queue_running', [])
                            if running:
                                # Structure: [number, prompt_id, nodes, extra_data, node_list]
                                pid = running[0][1]
                                _active_prompt = pid
                                logger.debug("  bootstrapped _active_prompt=%s from /queue", pid)
                        except Exception:
                            logger.warning("  /queue bootstrap failed", exc_info=True)
                            return None
                    if not _active_prompt:
                        return None
                    # Get node meta from comfy_queue
                    try:
                        queue_row = db.get_comfy_queue_job(_active_prompt)
                        class_type = None
                        title = None
                        if queue_row and queue_row.get('prompt'):
                            nodes = queue_row['prompt']
                            if isinstance(nodes, dict) and str(node) in nodes:
                                n = nodes[str(node)]
                                class_type = n.get('class_type')
                                title = (n.get('_meta') or {}).get('title')
                    except Exception:
                        pass
                    db.upsert_node_timing(_active_prompt, str(node), class_type, title)
                    logger.debug("  executing: node %s", node)

            elif mtype == 'progress':
                node = data.get('node')
                pid = data.get('prompt_id')
                if node is not None and pid:
                    # Bootstrap _active_prompt from progress event
                    if not _active_prompt:
                        _active_prompt = pid
                        logger.debug("  bootstrapped _active_prompt=%s from progress event", pid)
                    step_val = data.get('value', 0)
                    step_max = data.get('max', 0)
                    db.update_node_progress(pid, str(node), step_val, step_max)

            elif mtype in ('execution_success', 'execution_error', 'execution_interrupted'):
                pid = data.get('prompt_id') or _active_prompt
                if pid:
                    completed = db.complete_last_node(pid)
                    logger.info(
                        "  %s: prompt %s — %d node(s) completed",
                        mtype, pid, completed
                    )
                    _active_prompt = None

                    # Trigger output scan on job completion
                    try:
                        from ..outputs.scan import scan_outputs
                        out_dir = outputs_dir or (Path.cwd() / "output")
                        scan_outputs(out_dir, db, incremental=True)
                    except Exception:
                        logger.exception("Output scan after job completion failed")

        except Exception:
            logger.exception("Error processing WebSocket message")

    def on_error(ws, err):
        logger.debug("WS error: %s", err)

    def on_close(ws, *_):
        logger.info("WebSocket closed")

    def on_open(ws):
        logger.info("Node timing daemon connected to ComfyUI")
        # Scan outputs after reconnect to catch files produced during disconnect
        try:
            from ..outputs.scan import scan_outputs
            out_dir = outputs_dir or (Path.cwd() / "output")
            scan_outputs(out_dir, db)
        except Exception:
            logger.exception("Output scan on reconnect failed")
        # Sync state on connect: check if a job is already running and
        # create a timing row for the currently-active node so subsequent
        # events attach correctly.
        try:
            qdata = json.loads(
                urllib.request.urlopen(
                    endpoint.rstrip('/') + '/queue', timeout=5
                ).read()
            )
            for item in qdata.get('queue_running', []):
                # Structure: [number, prompt_id, nodes, extra_data, node_list]
                number = item[0]
                pid = item[1]
                nodes = item[2]
                extra_data = item[3]
                node_list = item[4]
                # The last item in node_list is the currently-active node
                current_node = node_list[-1] if node_list else None
                if current_node:
                    global _active_prompt
                    _active_prompt = pid
                    try:
                        class_type = nodes.get(str(current_node), {}).get('class_type')
                        title = nodes.get(str(current_node), {}).get('_meta', {}).get('title')
                        db.upsert_node_timing(pid, str(current_node), class_type, title)
                        logger.info("  Synced mid-job state for node %s (prompt %s)", current_node, pid)
                    except Exception:
                        logger.warning("  Mid-job sync failed for node %s", current_node, exc_info=True)
        except Exception:
            logger.warning("  /queue sync failed", exc_info=True)

    logger.info("Connecting to ComfyUI WebSocket: %s", ws_url)
    wsc = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    wsc.run_forever(reconnect=5)
    logger.info("Node timing daemon stopped")


def poll_once(db, endpoint: str) -> Dict[str, int]:
    """One-shot poll (no-op for WS daemon — used only if WS is unavailable)."""
    return {'nodes': 0}
