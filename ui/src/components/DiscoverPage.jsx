import { useState, useEffect, useRef, useContext, useLayoutEffect } from 'react'
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
  const [allTags, setAllTags]             = useState([])
  const [tagsLoaded, setTagsLoaded]       = useState(false)

  // Merge state
  const [selectedClusters, setSelectedClusters] = useState([])
  const [showMergeModal, setShowMergeModal] = useState(false)

  const { refreshTags } = useContext(AppContext)

  // Fetch tags once when the page loads
  useEffect(() => {
    if (!tagsLoaded) {
      fetch('/api/tags/all')
        .then(r => r.json())
        .then(d => { setAllTags(d.tags || []); setTagsLoaded(true) })
        .catch(() => setTagsLoaded(true))
    }
  }, [tagsLoaded])

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

  // Selection toggle
  function toggleSelection(id) {
    setSelectedClusters(sel =>
      sel.includes(id) ? sel.filter(s => s !== id) : [...sel, id]
    )
  }

  // Merge handler
  async function mergeClusters() {
    if (selectedClusters.length < 2) {
      alert('Select at least 2 clusters to merge.')
      return
    }
    const survivorId = selectedClusters[0]
    const sourceIds = selectedClusters.slice(1)
    try {
      const r = await fetch('/api/clusters/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ survivor_id: survivorId, source_ids: sourceIds }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Merge failed')
      setAllClusters(prev => prev.filter(c => !sourceIds.includes(c.id)))
      setSelectedClusters([])
      setShowMergeModal(false)
      loadClusters()
      refreshTags()
    } catch (e) {
      alert(`Merge failed: ${e.message}`)
    }
  }

  async function promote(id, explicitTag) {
    const tag = (explicitTag || (promoteState[id]?.input || '')).trim().toLowerCase()
    if (!tag) return
    setPromoteState(s => {
      const existing = s[id] || {}
      existing.status = 'saving'
      const next = { ...s }
      next[id] = existing
      return next
    });
    try {
      const r = await fetch(`/api/clusters/${id}/promote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Failed')
      setPromoteState(s => {
        const existing = s[id] || {}
        existing.status = 'done'
        existing.input = ''
        const next = { ...s }
        next[id] = existing
        return next
      });
      setAllClusters(prev => prev.map(c => c.id === id ? { ...c, promoted_tag: tag } : c))
      refreshTags()
    } catch (err) {
      setPromoteState(s => {
        const existing = s[id] || {}
        existing.status = 'error'
        const next = { ...s }
        next[id] = existing
        return next
      });
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
        <button className="discover-merge-btn" onClick={() => setShowMergeModal(true)} disabled={selectedClusters.length < 2}>
          Merge ({selectedClusters.length} selected)
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
        <div className="discover-loading">Running clustering - this may take a minute…</div>
      ) : allClusters === null ? (
        <div className="discover-scroll">
          <div className="discover-grid">
            {Array.from({ length: 24 }).map((_, i) => <ClusterSkeleton key={i} />)}
          </div>
        </div>
      ) : clusters.length === 0 ? (
        <div className="discover-empty">
          No clusters yet - click <strong>Run clustering</strong> to discover faces.
        </div>
      ) : (
        <div className="discover-scroll">
          <div className="discover-grid">
            {pageSlice.map(c => (
              <ClusterCard
                key={c.id}
                cluster={c}
                allTags={allTags}
                promoteInput={promoteState[c.id]?.input ?? ''}
                promoteStatus={promoteState[c.id]?.status}
                selected={selectedClusters.includes(c.id)}
                onToggleSelection={() => toggleSelection(c.id)}
                onPromoteInput={val => {
                  const next = { ...promoteState }
                  const existing = next[c.id] || {}
                  existing.input = val
                  next[c.id] = existing
                  setPromoteState(next)
                }}
                onPromote={(tag) => promote(c.id, tag)}
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

      {/* Merge Modal */}
      {showMergeModal && (
        <div className="discover-modal-overlay" onClick={() => setShowMergeModal(false)}>
          <div className="discover-modal" onClick={e => e.stopPropagation()}>
            <div className="discover-modal-title">Merge Clusters</div>
            <div className="discover-modal-body">
              <p>Survivor: <strong>#{selectedClusters[0]}</strong></p>
              <p>Absorbing {selectedClusters.length - 1} cluster(s): <strong>{selectedClusters.slice(1).join(', ')}</strong></p>
              <p className="discover-modal-warning">The survivor will absorb all detections, samples, and scenes from the other clusters. Absorbed clusters will be deleted.</p>
            </div>
            <div className="discover-modal-actions">
              <button className="discover-modal-cancel" onClick={() => setShowMergeModal(false)}>Cancel</button>
              <button className="discover-modal-confirm" onClick={mergeClusters}>Confirm Merge</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ClusterCard({ cluster, allTags, promoteInput, promoteStatus, onPromoteInput, onPromote, onDismiss, selected, onToggleSelection }) {
  const { tagMap } = useContext(AppContext)
  const navigate = useNavigate()
  const sampleCount = Math.min(4, (cluster.sample_frame_numbers || []).length)
  const isPromoted  = !!cluster.promoted_tag
  const isDismissed = cluster.dismissed

  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [cursor, setCursor] = useState(0)
  const [adjustedTop, setAdjustedTop] = useState(0)
  const [adjustedLeft, setAdjustedLeft] = useState(0)
  const inputRef = useRef(null)
  const wrapRef = useRef(null)

  useLayoutEffect(() => {
    if (!dropdownOpen) return
    if (!wrapRef.current) {
      const retry = () => {
        if (wrapRef.current) {
          const rect = wrapRef.current.getBoundingClientRect()
          const ddHeight = 240
          const top = rect.bottom + 4
          if (top + ddHeight > window.innerHeight) {
            setAdjustedTop(rect.top - ddHeight - 4)
          } else {
            setAdjustedTop(top)
          }
          setAdjustedLeft(rect.left)
        }
      }
      requestAnimationFrame(retry)
      return
    }
    const rect = wrapRef.current.getBoundingClientRect()
    const ddHeight = 240
    const top = rect.bottom + 4
    if (top + ddHeight > window.innerHeight) {
      setAdjustedTop(rect.top - ddHeight - 4)
    } else {
      setAdjustedTop(top)
    }
    setAdjustedLeft(rect.left)
  }, [dropdownOpen])

  const existingTags = [...allTags].sort((a, b) => (a.tag || '').localeCompare(b.tag || ''))
  const q = (promoteInput || '').toLowerCase()
  const filteredExisting = existingTags.filter(
    t => (t.tag || '').includes(q) || (t.display_name || '').toLowerCase().includes(q)
  )

  const isNewTag = q && !existingTags.some(t => (t.tag || '') === q)
  const options = isNewTag
    ? [{ tag: q, display_name: q, isNew: true }, ...filteredExisting]
    : filteredExisting

  useEffect(() => { setCursor(0) }, [promoteInput])

  useEffect(() => {
    function onClickOutside(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setDropdownOpen(false)
      }
    }
    if (dropdownOpen) {
      document.addEventListener('mousedown', onClickOutside)
    }
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [dropdownOpen])

  function handleKey(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor(c => Math.min(c + 1, options.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor(c => Math.max(c - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (options[cursor]) selectTag(options[cursor].tag)
    } else if (e.key === 'Escape') {
      setDropdownOpen(false)
    }
  }

  function selectTag(tag) {
    onPromoteInput(tag)
    setDropdownOpen(false)
    onPromote(tag)
  }

  function toggleDropdown(e) {
    e.preventDefault()
    setDropdownOpen(prev => !prev)
  }

  return (
    <div className={`discover-card${isDismissed ? ' discover-card--dismissed' : ''}${isPromoted ? ' discover-card--promoted' : ''}${selected ? ' discover-card--selected' : ''}`}>
      <div className="discover-card-selection" onClick={(e) => { e.stopPropagation(); onToggleSelection(cluster.id) }} style={{ cursor: 'pointer' }}>
        <span className={`discover-card-checkbox${selected ? ' discover-card-checkbox--checked' : ''}`}>
          {selected ? '✓' : ''}
        </span>
      </div>
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
            <div ref={wrapRef} className="discover-autocomplete-wrap">
              <div className="discover-autocomplete-input-row">
                <input
                  ref={inputRef}
                  className="discover-autocomplete-input"
                  placeholder="tag name…"
                  value={promoteInput}
                  onChange={e => { onPromoteInput(e.target.value); setDropdownOpen(true) }}
                  onFocus={() => setDropdownOpen(true)}
                  onKeyDown={handleKey}
                  disabled={promoteStatus === 'saving'}
                />
                <button
                  className="discover-autocomplete-toggle"
                  onClick={toggleDropdown}
                  disabled={promoteStatus === 'saving'}
                  title="Toggle tag list"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg>
                </button>
              </div>
              {dropdownOpen && (
                <div
                  className="discover-autocomplete-list"
                  style={{ top: adjustedTop, left: adjustedLeft }}
                >
                  {options.length === 0 && q && (
                    <div
                      className="discover-autocomplete-item discover-autocomplete-item--new"
                      onMouseDown={() => selectTag(q)}
                      style={{ cursor: 'pointer' }}
                    >
                      <span className="discover-autocomplete-item-main">New: {q}</span>
                      <span className="discover-autocomplete-badge">NEW</span>
                    </div>
                  )}
                  {options.map((t, i) => (
                    <div
                      key={t.tag + (t.isNew ? '-new' : '')}
                      className={`discover-autocomplete-item${i === cursor ? ' discover-autocomplete-item--active' : ''}${t.isNew ? ' discover-autocomplete-item--new' : ''}`}
                      onMouseDown={() => selectTag(t.tag)}
                      onMouseEnter={() => setCursor(i)}
                      style={{ cursor: 'pointer' }}
                    >
                      <span className="discover-autocomplete-item-main">
                        {t.display_name || t.tag}
                        {t.isNew ? ' (new)' : ''}
                      </span>
                      {t.isNew && <span className="discover-autocomplete-badge">NEW</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <button
              className="discover-promote-btn"
              onClick={() => onPromote(promoteInput)}
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
