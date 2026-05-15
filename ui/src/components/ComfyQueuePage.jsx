import { useState, useContext } from 'react'
import { AppContext } from '../context'

function fmtDuration(seconds) {
  if (seconds == null || seconds == undefined) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds - mins * 60
  return `${mins}m ${secs.toFixed(0)}s`
}

function fmtTimeAgo(iso) {
  if (!iso) return ''
  const now = new Date()
  const dt = new Date(iso)
  const diffMs = now - dt
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHrs = Math.floor(diffMins / 60)
  const remainMins = diffMins % 60
  if (remainMins === 0) return `${diffHrs}h ago`
  return `${diffHrs}h ${remainMins}m ago`
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
  // { promptId: { expanded: boolean, nodeTiming: array | null, loading: boolean } }
  const [expandedJobs, setExpandedJobs] = useState({})

  async function clearQueue() {
    setClearing(true)
    await clearComfyQueue()
    setClearing(false)
  }

  async function handleToggle(promptId) {
    const prevState = expandedJobs[promptId]
    if (prevState && prevState.expanded) {
      // Collapse — no fetch needed
      setExpandedJobs(prev => {
        const next = { ...prev }
        delete next[promptId]
        return next
      })
      return
    }
    // Expand — set loading state, then fetch
    setExpandedJobs(prev => ({
      ...prev, [promptId]: { expanded: true, nodeTiming: null, loading: true }
    }))
    try {
      const r = await fetch(`/api/comfyui/node-timing/${promptId}`)
      const d = await r.json()
      const timing = d.node_timing ?? []
      setExpandedJobs(prev => ({
        ...prev, [promptId]: { expanded: true, nodeTiming: timing, loading: false }
      }))
    } catch {
      setExpandedJobs(prev => {
        const next = { ...prev, [promptId]: { expanded: true, nodeTiming: [], loading: false } }
        return next
      })
    }
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
                <span className="cq-item-title">{item.prompt_id}</span>
                <span className="cq-item-meta">{item.node_count} nodes</span>

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
              <span className="cq-item-title">{item.prompt_id}</span>
              <span className="cq-item-meta">{item.node_count} nodes</span>
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
        ) : (
          hist.map(item => {
            const durationStr = item.duration_seconds != null
              ? fmtDuration(item.duration_seconds)
              : null
            const timeAgo = fmtTimeAgo(item.completed_at)
            const jobState = expandedJobs[item.prompt_id]
            const isExpanded = !!(jobState && jobState.expanded)
            const isLoading = !!(jobState && jobState.loading)
            const nodeTiming = jobState?.nodeTiming ?? []

            return (
              <div key={item.prompt_id} className={`cq-item cq-item--history${isExpanded ? ' cq-item--expanded' : ''}`}>
                <div className="cq-item-header">
                  <span className={`cq-status-dot cq-status-dot--${item.status_str === 'success' ? 'ok' : 'err'}`} />
                  <span className="cq-chevron" onClick={() => handleToggle(item.prompt_id)} style={{ cursor: 'pointer' }}>
                    {isExpanded ? '▼' : '▶'}
                  </span>
                  <div className="cq-item-body" onClick={() => handleToggle(item.prompt_id)} style={{ cursor: 'pointer' }}>
                    <span className="cq-item-title">{item.prompt_id}</span>
                    <span className="cq-item-meta">
                      {item.status_str}
                      {durationStr && <span className="cq-duration"> · {durationStr}</span>}
                      {timeAgo && <span className="cq-time-ago"> · {timeAgo}</span>}
                    </span>
                  </div>
                </div>

                {isExpanded && (
                  <div className="cq-node-timing-detail">
                    {isLoading ? (
                      <div className="cq-empty">Loading node timing…</div>
                    ) : nodeTiming.length === 0 ? (
                      <div className="cq-empty">No node timing data</div>
                    ) : (
                      <table className="cq-node-table">
                        <thead>
                          <tr>
                            <th>Node</th>
                            <th>Class</th>
                            <th>Duration</th>
                            <th>Steps</th>
                            <th>Started</th>
                            <th>Completed</th>
                          </tr>
                        </thead>
                        <tbody>
                          {nodeTiming.map((nt, i) => (
                            <tr key={i} className={nt.completed_at ? '' : 'cq-node--active'}>
                              <td title={nt.prompt_id}>{nt.node_id}</td>
                              <td>{nt.class_type}</td>
                              <td>{nt.duration_sec != null ? fmtDuration(nt.duration_sec) : '—'}</td>
                              <td>{nt.step_value != null ? `${nt.step_value}/${nt.steps ?? '?'}` : '—'}</td>
                              <td>{nt.started_at ? new Date(nt.started_at).toLocaleTimeString() : '—'}</td>
                              <td>{nt.completed_at ? new Date(nt.completed_at).toLocaleTimeString() : '…'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>
            )
          })
        )}
      </section>
    </div>
  )
}