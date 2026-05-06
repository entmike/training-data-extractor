import { useState, useContext } from 'react'
import { AppContext } from '../context'

function fmtId(id) {
  return id ? id.slice(0, 8) : '—'
}

export default function ComfyQueuePage() {
  const {
    comfyQueue: queue,
    comfyHistory: history,
    comfyProgress: progress,
    comfyError: error,
    deleteQueueItem,
    clearComfyQueue,
  } = useContext(AppContext)

  const [clearing, setClearing] = useState(false)

  async function clearQueue() {
    setClearing(true)
    await clearComfyQueue()
    setClearing(false)
  }

  if (error) return (
    <div className="cq-page">
      <div className="cq-error">
        {error.includes('not configured')
          ? <><strong>ComfyUI endpoint not configured.</strong><br />Set it in Config first.</>
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
        ) : running.map(item => {
          const prog = progress?.prompt_id === item.prompt_id ? progress : null
          const pct  = (prog && prog.max > 0) ? Math.round((prog.value / prog.max) * 100) : null
          const nodeMeta = prog?.node ? (item.node_meta?.[prog.node] ?? null) : null
          const nodeLabel = nodeMeta?.title || nodeMeta?.class_type || (prog?.node ? `Node ${prog.node}` : null)
          const isSampling = prog && prog.max > 0

          return (
            <div key={item.prompt_id} className="cq-item cq-item--running">
              <span className="cq-spinner" />
              <div className="cq-item-body">
                <span className="cq-item-title">{item.title}</span>
                <span className="cq-item-meta">{fmtId(item.prompt_id)} · {item.node_count} nodes</span>

                {prog && item.node_count > 0 && prog.node && !isSampling && (
                  <div className="cq-progress">
                    <div className="cq-progress-bar cq-progress-bar--node">
                      <div className="cq-progress-fill cq-progress-fill--node"
                           style={{ width: `${Math.min(100, Math.round(((prog.node_value || 1) / item.node_count) * 100))}%` }} />
                    </div>
                    <div className="cq-progress-label">
                      {nodeLabel && <span className="cq-progress-node">{nodeLabel}</span>}
                      <span className="cq-progress-pct cq-progress-pct--node">
                        node {prog.node_value || '?'} / {item.node_count}
                        {prog.node_value > 0 && <>&nbsp;({Math.min(100, Math.round((prog.node_value / item.node_count) * 100))}%)</>}
                      </span>
                    </div>
                  </div>
                )}

                {isSampling && (
                  <div className="cq-progress">
                    <div className="cq-progress-bar">
                      <div className="cq-progress-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <div className="cq-progress-label">
                      {nodeLabel && <span className="cq-progress-node">{nodeLabel}</span>}
                      <span className="cq-progress-pct">
                        step {prog.value} / {prog.max} &nbsp;({pct}%)
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )
        })}
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
            <button className="cq-delete-btn" onClick={() => deleteQueueItem(item.prompt_id)} title="Remove from queue">
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
