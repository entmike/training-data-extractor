import { useState, useEffect, useRef, useCallback } from 'react'

const POLL_MS = 3000

function fmtId(id) {
  return id ? id.slice(0, 8) : '—'
}

export default function ComfyQueuePage() {
  const [queue, setQueue]     = useState(null)   // { running, pending } | null
  const [history, setHistory] = useState(null)   // { history } | null
  const [error, setError]     = useState(null)
  const [clearing, setClearing] = useState(false)
  const timerRef = useRef(null)

  const fetchQueue = useCallback(async () => {
    try {
      const [qr, hr] = await Promise.all([
        fetch('/api/comfyui/queue'),
        fetch('/api/comfyui/history?limit=15'),
      ])
      const qd = await qr.json()
      const hd = await hr.json()
      if (qd.error) { setError(qd.error); setQueue(null); return }
      setError(null)
      setQueue(qd)
      if (!hd.error) setHistory(hd)
    } catch (e) {
      setError(String(e))
    }
  }, [])

  useEffect(() => {
    fetchQueue()
    timerRef.current = setInterval(fetchQueue, POLL_MS)
    return () => clearInterval(timerRef.current)
  }, [fetchQueue])

  async function deleteItem(prompt_id) {
    await fetch('/api/comfyui/queue/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt_id }),
    })
    fetchQueue()
  }

  async function clearQueue() {
    setClearing(true)
    await fetch('/api/comfyui/queue/clear', { method: 'POST' })
    await fetchQueue()
    setClearing(false)
  }

  if (error) return (
    <div className="cq-page">
      <div className="cq-error">
        {error.includes('not configured')
          ? <><strong>ComfyUI endpoint not configured.</strong><br />Set it in <a href="/config">Config</a> first.</>
          : <><strong>Could not reach ComfyUI:</strong> {error}</>}
      </div>
    </div>
  )

  const running = queue?.running ?? []
  const pending = queue?.pending ?? []
  const hist    = history?.history ?? []

  return (
    <div className="cq-page">
      <div className="cq-header">
        <h2 className="cq-title">ComfyUI Queue</h2>
        <div className="cq-header-actions">
          <span className="cq-poll-dot" title="Auto-refreshing every 3s" />
          {pending.length > 0 && (
            <button className="cq-clear-btn" onClick={clearQueue} disabled={clearing}>
              {clearing ? 'Clearing…' : `Clear queue (${pending.length})`}
            </button>
          )}
        </div>
      </div>

      {/* Running */}
      <section className="cq-section">
        <h3 className="cq-section-title">Running</h3>
        {queue === null ? (
          <div className="cq-empty">Loading…</div>
        ) : running.length === 0 ? (
          <div className="cq-empty">Idle</div>
        ) : running.map(item => (
          <div key={item.prompt_id} className="cq-item cq-item--running">
            <span className="cq-spinner" />
            <div className="cq-item-body">
              <span className="cq-item-title">{item.title}</span>
              <span className="cq-item-meta">{fmtId(item.prompt_id)} · {item.node_count} nodes</span>
            </div>
          </div>
        ))}
      </section>

      {/* Pending */}
      <section className="cq-section">
        <h3 className="cq-section-title">
          Pending{pending.length > 0 && <span className="cq-count">{pending.length}</span>}
        </h3>
        {pending.length === 0 ? (
          <div className="cq-empty">Queue empty</div>
        ) : pending.map(item => (
          <div key={item.prompt_id} className="cq-item">
            <span className="cq-item-number">#{item.number}</span>
            <div className="cq-item-body">
              <span className="cq-item-title">{item.title}</span>
              <span className="cq-item-meta">{fmtId(item.prompt_id)} · {item.node_count} nodes</span>
            </div>
            <button className="cq-delete-btn" onClick={() => deleteItem(item.prompt_id)} title="Remove from queue">
              ✕
            </button>
          </div>
        ))}
      </section>

      {/* Recent history */}
      <section className="cq-section">
        <h3 className="cq-section-title">Recent</h3>
        {hist.length === 0 ? (
          <div className="cq-empty">No history</div>
        ) : hist.map(item => (
          <div key={item.prompt_id} className="cq-item cq-item--history">
            <span className={`cq-status-dot cq-status-dot--${item.status_str === 'success' ? 'ok' : 'err'}`} />
            <div className="cq-item-body">
              <span className="cq-item-title">{fmtId(item.prompt_id)}</span>
              <span className="cq-item-meta">{item.status_str} · {item.outputs} output{item.outputs !== 1 ? 's' : ''}</span>
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}
