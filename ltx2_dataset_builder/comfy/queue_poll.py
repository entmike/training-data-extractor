"""
Poll the ComfyUI /queue endpoint and persist active jobs to the `comfy_queue`
table.

The endpoint URL is read from the `config` DB table (key `comfyui_endpoint`),
the same place the web UI / Config page writes it to.

Each /queue response contains:
    queue_running: list of running jobs
    queue_pending: list of pending jobs
A job is a 5-tuple: (number, prompt_id, nodes, extra_data, _)
  - nodes      → the API-format prompt (id → {class_type, inputs, _meta})
  - extra_data → may contain client_id, extra_pnginfo.workflow (GUI graph)

We upsert each observed job and, after each poll, mark any previously-active
job that has fallen out of the queue as `completed`.
"""

import json
import logging
import signal
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _fetch_queue(endpoint: str, timeout: int = 10) -> Dict[str, Any]:
    url = endpoint.rstrip('/') + '/queue'
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _split_extra_data(extra_data: Any) -> Tuple[Optional[dict], Optional[str], Optional[dict]]:
    """Return (workflow_graph, client_id, extra_data_minus_pnginfo)."""
    if not isinstance(extra_data, dict):
        return None, None, None
    workflow = None
    pnginfo = extra_data.get('extra_pnginfo')
    if isinstance(pnginfo, dict):
        wf = pnginfo.get('workflow')
        if isinstance(wf, (dict, list)):
            workflow = wf
    client_id = extra_data.get('client_id')
    if client_id is not None and not isinstance(client_id, str):
        client_id = str(client_id)
    rest = {k: v for k, v in extra_data.items() if k != 'extra_pnginfo'}
    return workflow, client_id, (rest or None)


def _extract_title(nodes: Any, extra_data: Any) -> Optional[str]:
    """Mirror web_review._fmt_queue_item title resolution."""
    try:
        wf = (extra_data or {}).get('extra_pnginfo', {}).get('workflow', {})
        name = wf.get('name') if isinstance(wf, dict) else None
        if name:
            return name
    except Exception:
        pass
    if isinstance(nodes, dict):
        for n in nodes.values():
            if isinstance(n, dict) and n.get('class_type') in ('CheckpointLoaderSimple', 'CheckpointLoader'):
                ckpt = (n.get('inputs') or {}).get('ckpt_name', '')
                if isinstance(ckpt, str) and ckpt:
                    return ckpt.split('/')[-1]
    return None


def _process_job(db, item: Any, status: str) -> Optional[str]:
    """Upsert a single queue tuple. Returns the prompt_id, or None if malformed."""
    if not isinstance(item, (list, tuple)) or len(item) < 4:
        return None
    number, prompt_id, nodes, extra_data = item[0], item[1], item[2], item[3]
    if not isinstance(prompt_id, str) or not prompt_id:
        return None

    workflow, client_id, extra_rest = _split_extra_data(extra_data)
    title = _extract_title(nodes, extra_data)
    node_count = len(nodes) if isinstance(nodes, dict) else None
    api_prompt = nodes if isinstance(nodes, dict) else None
    try:
        num_int = int(number) if number is not None else None
    except (TypeError, ValueError):
        num_int = None

    inserted = db.upsert_comfy_queue_job(
        prompt_id=prompt_id,
        number=num_int,
        status=status,
        title=title,
        node_count=node_count,
        client_id=client_id,
        workflow=workflow,
        prompt=api_prompt,
        extra_data=extra_rest,
    )
    if inserted:
        logger.info("  [new %s] %s — %s", status, prompt_id, title or f'#{num_int}')
    else:
        logger.debug("  [seen %s] %s", status, prompt_id)
    return prompt_id


def poll_once(db, endpoint: str) -> Dict[str, int]:
    """One pass: fetch /queue, upsert active jobs, mark missing ones completed."""
    try:
        data = _fetch_queue(endpoint)
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("ComfyUI /queue unreachable at %s: %s", endpoint, exc)
        return {'running': 0, 'pending': 0, 'completed': 0}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("ComfyUI /queue returned malformed JSON: %s", exc)
        return {'running': 0, 'pending': 0, 'completed': 0}

    active: List[str] = []
    running = pending = 0
    for item in data.get('queue_running', []) or []:
        pid = _process_job(db, item, 'running')
        if pid:
            active.append(pid)
            running += 1
    for item in data.get('queue_pending', []) or []:
        pid = _process_job(db, item, 'pending')
        if pid:
            active.append(pid)
            pending += 1

    completed = db.mark_comfy_queue_completed(active)
    if completed:
        logger.info("  [completed] %d job(s) left the queue", completed)

    logger.debug("Poll: %d running, %d pending, %d marked completed",
                 running, pending, completed)
    return {'running': running, 'pending': pending, 'completed': completed}


def _resolve_endpoint(db, override: Optional[str]) -> Optional[str]:
    if override:
        return override.rstrip('/')
    val = db.get_config_value('comfyui_endpoint')
    return val.rstrip('/') if val else None


def run_daemon(db, interval: int = 5, endpoint_override: Optional[str] = None) -> None:
    """Poll /queue every *interval* seconds until SIGINT/SIGTERM.

    Re-reads the configured endpoint from the `config` table on every tick so
    UI changes take effect without a daemon restart.
    """
    running = True

    def _stop(sig, _frame):
        nonlocal running
        logger.info("Daemon received signal %d, stopping after current poll …", sig)
        running = False

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info("Comfy queue daemon started — polling every %ds (SIGINT/SIGTERM to stop)", interval)
    warned_no_endpoint = False

    while running:
        endpoint = _resolve_endpoint(db, endpoint_override)
        if not endpoint:
            if not warned_no_endpoint:
                logger.warning("ComfyUI endpoint not configured (config.comfyui_endpoint) — idling")
                warned_no_endpoint = True
        else:
            warned_no_endpoint = False
            try:
                poll_once(db, endpoint)
            except Exception:
                logger.exception("Poll error — will retry next interval")

        if not running:
            break
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    logger.info("Comfy queue daemon stopped.")
