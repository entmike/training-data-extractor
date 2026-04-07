import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import TagDropdown from './TagDropdown'

export default function Header({
  stats, videoFilter, setVideoFilter,
  allVideos, allTags,
  activeIncludeTags, setActiveIncludeTags,
  activeExcludeTags, setActiveExcludeTags,
  includeMode, setIncludeMode,
  minFrames, setMinFrames,
  ratingFilter, setRatingFilter,
  sort, setSort,
  viewMode, setViewMode,
  isLoading,
  onManageTags, onManageVideos, onManageCollections,
}) {
  const [dropdown, setDropdown] = useState(null) // { mode: 'include'|'exclude', pos }

  const PRESET_FRAMES = [0, 24, 48, 72, 96, 120]
  const isPreset = PRESET_FRAMES.includes(minFrames)
  const [framesMode, setFramesMode] = useState(isPreset ? String(minFrames) : 'custom')
  const [customDraft, setCustomDraft] = useState(isPreset ? '' : String(minFrames))

  useEffect(() => {
    if (PRESET_FRAMES.includes(minFrames)) {
      setFramesMode(String(minFrames))
    }
  }, [minFrames])
  const includeAddRef = useRef(null)
  const excludeAddRef = useRef(null)

  const statsReady = stats !== null
  const pct = statsReady && stats.total > 0 ? Math.round((stats.captioned / stats.total) * 100) : 0
  const videoLabel = v => (v.name || v.path).replace(/\.[^.]+$/, '').replace(/.*\//, '')

  function openDropdown(mode, ref) {
    const rect = ref.current.getBoundingClientRect()
    setDropdown({ mode, pos: { top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX } })
  }

  function handleTagSelect(tag) {
    if (!dropdown) return
    if (dropdown.mode === 'include') {
      setActiveIncludeTags(prev => new Set([...prev, tag]))
      setActiveExcludeTags(prev => { const s = new Set(prev); s.delete(tag); return s })
    } else {
      setActiveExcludeTags(prev => new Set([...prev, tag]))
      setActiveIncludeTags(prev => { const s = new Set(prev); s.delete(tag); return s })
    }
    setDropdown(null)
  }

  const allTagNames = allTags.map(t => t.tag)
  const usedTags = new Set([...activeIncludeTags, ...activeExcludeTags])
  const availableTags = allTags.filter(t => !usedTags.has(t.tag))

  return (
    <header className="app-header">
      <div className="header-main">
        {/* Stats */}
        <div className="stats-group">
          <div className="stats-bars">
            <div className="progress-bar-wrap">
              {statsReady
                ? <div className="progress-bar" style={{ width: `${pct}%` }} />
                : <div className="skeleton skeleton--bar" />}
            </div>
          </div>
          <div className="stats-numbers">
            {statsReady ? <>
              <span className="stats-total">{stats.total.toLocaleString()} scenes</span>
              <span className="stats-captioned">{stats.captioned.toLocaleString()} captioned ({pct}%)</span>
            </> : <>
              <span className="skeleton skeleton--text" style={{ width: 80 }} />
              <span className="skeleton skeleton--text" style={{ width: 120 }} />
            </>}
          </div>
        </div>

        {/* Video filter */}
        <select
          className="video-select"
          value={videoFilter}
          onChange={e => setVideoFilter(e.target.value)}
          disabled={isLoading}
        >
          <option value="">All videos</option>
          {allVideos.map(v => (
            <option key={v.id} value={v.id}>{videoLabel(v)}</option>
          ))}
        </select>

        {/* Sort buttons */}
        <div className="filter-buttons">
          {[['', 'Default'], ['frames_asc', 'Start ↑'], ['frames_desc', 'Start ↓']].map(([val, label]) => (
            <button
              key={val}
              className={`filter-btn${sort === val ? ' active' : ''}`}
              onClick={() => setSort(val)}
              disabled={isLoading}
            >{label}</button>
          ))}
        </div>

        <div className="header-spacer" />

        {/* Action buttons */}
        <div className="view-toggle">
          <button
            className={`view-toggle-btn${viewMode === 'card' ? ' active' : ''}`}
            onClick={() => setViewMode('card')}
            title="Card view"
          >⊟</button>
          <button
            className={`view-toggle-btn${viewMode === 'thumb' ? ' active' : ''}`}
            onClick={() => setViewMode('thumb')}
            title="Thumbnail view"
          >⊞</button>
        </div>
        <button className="action-btn" onClick={onManageTags} disabled={isLoading}>Manage Tags</button>
        <button className="action-btn" onClick={onManageVideos} disabled={isLoading}>Videos</button>
        <button className="action-btn" onClick={onManageCollections} disabled={isLoading}>Collections</button>
      </div>

      {/* Tag filter bar */}
      <div className="tag-filter-bar">
        <div className="tag-filter-row">
          <span className="tag-filter-label">Show:</span>
          {activeIncludeTags.size > 1 && (
            <button
              className={`mode-toggle mode-toggle--${includeMode}`}
              onClick={() => setIncludeMode(m => m === 'and' ? 'or' : 'and')}
              disabled={isLoading}
            >
              {includeMode.toUpperCase()}
            </button>
          )}
          {[...activeIncludeTags].map(tag => (
            <span key={tag} className="tag-filter-pill tag-filter-pill--include">
              {allTags.find(t => t.tag === tag)?.display_name || tag}
              <span className="remove-x" onClick={() => setActiveIncludeTags(prev => { const s = new Set(prev); s.delete(tag); return s })}>✕</span>
            </span>
          ))}
          <button ref={includeAddRef} className="tag-filter-add" onClick={() => openDropdown('include', includeAddRef)} disabled={isLoading}>+ tag</button>
        </div>

        <div className="tag-filter-row">
          <span className="tag-filter-label">Hide:</span>
          {[...activeExcludeTags].map(tag => (
            <span key={tag} className="tag-filter-pill tag-filter-pill--exclude">
              {allTags.find(t => t.tag === tag)?.display_name || tag}
              <span className="remove-x" onClick={() => setActiveExcludeTags(prev => { const s = new Set(prev); s.delete(tag); return s })}>✕</span>
            </span>
          ))}
          <button ref={excludeAddRef} className="tag-filter-add" onClick={() => openDropdown('exclude', excludeAddRef)} disabled={isLoading}>+ tag</button>

          <div className="header-spacer" />

          <div className="min-frames-wrap">
            <label>Min frames:</label>
            <select
              className="min-frames-input"
              value={framesMode}
              onChange={e => {
                const val = e.target.value
                setFramesMode(val)
                if (val !== 'custom') setMinFrames(Number(val))
                else setCustomDraft('')
              }}
              disabled={isLoading}
            >
              {PRESET_FRAMES.map(n => (
                <option key={n} value={String(n)}>{n === 0 ? 'Any' : `${n}f`}</option>
              ))}
              <option value="custom">Custom…</option>
            </select>
            {framesMode === 'custom' && (
              <input
                type="number"
                className="min-frames-input"
                min="0"
                placeholder="frames"
                value={customDraft}
                onChange={e => setCustomDraft(e.target.value)}
                onBlur={e => {
                  const v = Math.max(0, parseInt(e.target.value) || 0)
                  setCustomDraft(String(v))
                  setMinFrames(v)
                }}
                onKeyDown={e => e.key === 'Enter' && e.target.blur()}
                disabled={isLoading}
                autoFocus
              />
            )}
          </div>

          <div className="rating-filter-wrap">
            <span className="rating-filter-label">Rating:</span>
            <button
              className={`rating-filter-btn${ratingFilter.size === 0 ? ' active' : ''}`}
              onClick={() => setRatingFilter(new Set())}
              disabled={isLoading}
            >Any</button>
            {[
              { value: 1,          label: '★' },
              { value: 2,          label: '★★' },
              { value: 3,          label: '★★★' },
              { value: 'unranked', label: 'Unranked' },
            ].map(opt => (
              <button
                key={String(opt.value)}
                className={`rating-filter-btn${ratingFilter.has(opt.value) ? ' active' : ''}`}
                onClick={() => setRatingFilter(prev => {
                  const next = new Set(prev)
                  next.has(opt.value) ? next.delete(opt.value) : next.add(opt.value)
                  return next
                })}
                disabled={isLoading}
              >{opt.label}</button>
            ))}
          </div>
        </div>
      </div>

      {dropdown && createPortal(
        <TagDropdown
          position={dropdown.pos}
          suggestions={availableTags}
          onSelect={handleTagSelect}
          onClose={() => setDropdown(null)}
        />,
        document.body
      )}
    </header>
  )
}
