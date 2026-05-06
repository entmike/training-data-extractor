import { useState, useEffect, useRef, useContext } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppContext } from '../context'

const PAGE_SIZE = 48

export default function DiscoverPage() {
  const [allClusters, setAllClusters]     = useState(null)
  const [running, setRunning]             = useState(false)
  const [showDismissed, setShowDismissed] = useState(false)
  const [showPromoted, setShowPromoted]   = useState(true)
  const [onlyUnclassified, setOnlyUnclassified] = useState(false)
  const [minSize, setMinSize]             = useState(5)
  const [page, setPage]                   = useState(1)
  const [promoteState, setPromoteState]   = useState({})

  function loadClusters(opts = {}) {
    const dismissed       = opts.dismissed        ?? showDismissed
    const promoted        = opts.promoted         ?? showPromoted
    const unclassified    = opts.onlyUnclassified ?? onlyUnclassified
    const size            = opts.minSize          ?? minSize
    const params = new URLSearchParams({
      include_dismissed:  dismissed    ? 1 : 0,
      include_promoted:   promoted     ? 1 : 0,
      only_unclassified:  unclassified ? 1 : 0,
      min_scenes:         size,
    })
    fetch(`/api/clusters?${params}`)
      .then(r => r.json())
      .then(d => { setAllClusters(d.clusters || []); setPage(1) })
      .catch(() => setAllClusters([]))
  }

  useEffect(() => { loadClusters() }, [])

  function applyFilter(key, val) {
    const next = { dismissed: showDismissed, promoted: showPromoted, onlyUnclassified, minSize }
    next[key] = val
    if (key === 'dismissed')       setShowDismissed(val)
    if (key === 'promoted')        setShowPromoted(val)
    if (key === 'onlyUnclassified') setOnlyUnclassified(val)
    if (key === 'minSize')         setMinSize(val)
    loadClusters(next)
  }

  async function runClustering() {
    setRunning(true)
    setAllClusters(null)
    try {
      const r = await fetch('/api/clusters/run', { method: 'POST' })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Unknown error')
      loadClusters()
    } catch (e) {
      alert(`Clustering failed: ${e.message}`)
      setAllClusters([])
    } finally {
      setRunning(false)
    }
  }

  async function dismiss(id) {
    await fetch(`/api/clusters/${id}/dismiss`, { method: 'POST' })
    setAllClusters(prev => prev.filter(c => c.id !== id))
  }

  async function promote(id) {
    const tag = (promoteState[id]?.input || '').trim().toLowerCase()
    if (!tag) return
    setPromoteState(s => ({ ...s, [id]: { ...s[id], status: 'saving' } }))
    try {
      const r = await fetch(`/api/clusters/${id}/promote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Failed')
      setPromoteState(s => ({ ...s, [id]: { input: '', status: 'done' } }))
      setAllClusters(prev => prev.map(c => c.id === id ? { ...c, promoted_tag: tag } : c))
      refreshTags()
    } catch {
      setPromoteState(s => ({ ...s, [id]: { ...s[id], status: 'error' } }))
    }
  }

  const clusters = allClusters ?? []
  const unknownCount = clusters.filter(c => !c.nearest_tag && !c.promoted_tag).length
  const totalPages = Math.ceil(clusters.length / PAGE_SIZE)
  const pageSlice = clusters.slice(0, page * PAGE_SIZE)
  const hasMore = page < totalPages

  return (
    <div className="discover-page">
      <div className="discover-toolbar">
        <button className="discover-run-btn" onClick={runClustering} disabled={running}>
          {running ? 'Clustering…' : 'Run clustering'}
        </button>

        <span className="discover-filter-label">
          Min scenes
          <span className="discover-filter-btns">
            {[1, 5, 10, 20, 50].map(n => (
              <button
                key={n}
                className={`filter-btn${minSize === n ? ' active' : ''}`}
                onClick={() => applyFilter('minSize', n)}
              >{n}</button>
            ))}
          </span>
        </span>

        {allClusters !== null && (
          <span className="discover-summary">
            {clusters.length} cluster{clusters.length !== 1 ? 's' : ''}
            {unknownCount > 0 && <> · <strong>{unknownCount} unknown</strong></>}
          </span>
        )}

        <div className="discover-toggles">
          <label className="discover-toggle">
            <input type="checkbox" checked={showPromoted}
              onChange={e => applyFilter('promoted', e.target.checked)} />
            Show promoted
          </label>
          <label className="discover-toggle">
            <input type="checkbox" checked={showDismissed}
              onChange={e => applyFilter('dismissed', e.target.checked)} />
            Show dismissed
          </label>
          <label className="discover-toggle">
            <input type="checkbox" checked={onlyUnclassified}
              onChange={e => applyFilter('onlyUnclassified', e.target.checked)} />
            Unclassified only
          </label>
        </div>
      </div>

      {allClusters === null && running ? (
        <div className="discover-loading">Running clustering — this may take a minute…</div>
      ) : allClusters === null ? (
        <div className="discover-scroll">
          <div className="discover-grid">
            {Array.from({ length: 24 }).map((_, i) => <ClusterSkeleton key={i} />)}
          </div>
        </div>
      ) : clusters.length === 0 ? (
        <div className="discover-empty">
          No clusters yet — click <strong>Run clustering</strong> to discover faces.
        </div>
      ) : (
        <div className="discover-scroll">
          <div className="discover-grid">
            {pageSlice.map(c => (
              <ClusterCard
                key={c.id}
                cluster={c}
                promoteInput={promoteState[c.id]?.input ?? ''}
                promoteStatus={promoteState[c.id]?.status}
                onPromoteInput={val => setPromoteState(s => ({ ...s, [c.id]: { ...s[c.id], input: val } }))}
                onPromote={() => promote(c.id)}
                onDismiss={() => dismiss(c.id)}
              />
            ))}
          </div>
          {hasMore && (
            <div className="discover-load-more">
              <button className="discover-load-more-btn" onClick={() => setPage(p => p + 1)}>
                Load more ({clusters.length - pageSlice.length} remaining)
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ClusterCard({ cluster, promoteInput, promoteStatus, onPromoteInput, onPromote, onDismiss }) {
  const { tagMap } = useContext(AppContext)
  const { refreshTags } = useContext(AppContext)
  const navigate = useNavigate()
  const sampleCount = Math.min(4, (cluster.sample_frame_numbers || []).length)
  const isPromoted  = !!cluster.promoted_tag
  const isDismissed = cluster.dismissed

  const inputRef = useRef(null)

  return (
    <div className={`discover-card${isDismissed ? ' discover-card--dismissed' : ''}${isPromoted ? ' discover-card--promoted' : ''}`}>
      <div className="discover-thumbs" onClick={() => navigate(`/cluster/${cluster.stable_key ?? cluster.id}`)} style={{ cursor: 'pointer' }}>
        {Array.from({ length: sampleCount }).map((_, i) => (
          <img
            key={i}
            className="discover-thumb"
            src={`/api/clusters/${cluster.id}/sample/${i}`}
            alt=""
            loading="lazy"
          />
        ))}
        {sampleCount === 0 && <div className="discover-thumb discover-thumb--empty" />}
      </div>

      <div className="discover-card-info">
        <span className="discover-card-badge discover-card-badge--faces">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
          {cluster.size}
        </span>
        <span className="discover-card-badge discover-card-badge--scenes">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 9l5 3-5 3V9z" fill="#000" opacity=".5"/></svg>
          {cluster.scene_count ?? 0}
        </span>
        <span className="discover-card-id">#{cluster.id}</span>
      </div>

      {isPromoted ? (
        <div className="discover-card-promoted">✓ <strong>{tagMap[cluster.promoted_tag]?.display_name || cluster.promoted_tag}</strong></div>
      ) : isDismissed ? (
        <div className="discover-card-dismissed-label">Dismissed</div>
      ) : (
        <div className="discover-card-actions">
          <div className="discover-promote-row">
            <input
              ref={inputRef}
              className="discover-promote-input"
              placeholder="tag name…"
              value={promoteInput}
              onChange={e => onPromoteInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') onPromote() }}
              disabled={promoteStatus === 'saving'}
            />
            <button
              className="discover-promote-btn"
              onClick={onPromote}
              disabled={!promoteInput.trim() || promoteStatus === 'saving'}
            >
              {promoteStatus === 'saving' ? '…' : promoteStatus === 'done' ? '✓' : 'Tag'}
            </button>
          </div>
          <button className="discover-dismiss-btn" onClick={onDismiss} title="Dismiss">✕</button>
        </div>
      )}
    </div>
  )
}

function ClusterSkeleton() {
  return (
    <div className="discover-card discover-card--skeleton">
      <div className="discover-thumbs">
        {[0,1,2,3].map(i => <div key={i} className="discover-thumb-skeleton skeleton" />)}
      </div>
      <div className="discover-card-info-skeleton">
        <div className="skel-badge skeleton" />
        <div className="skel-badge skeleton" />
      </div>
      <div className="skel-action skeleton" />
    </div>
  )
}
