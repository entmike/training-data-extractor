import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import TagDropdown from './TagDropdown'

export default function Header({
  stats, filter, setFilter, videoFilter, setVideoFilter,
  allVideos, allTags,
  activeIncludeTags, setActiveIncludeTags,
  activeExcludeTags, setActiveExcludeTags,
  includeMode, setIncludeMode,
  minFrames, setMinFrames,
  autoRefresh, setAutoRefresh,
  onManageTags, onManageVideos,
}) {
  const [dropdown, setDropdown] = useState(null) // { mode: 'include'|'exclude', pos }
  const includeAddRef = useRef(null)
  const excludeAddRef = useRef(null)

  const pct = stats.total > 0 ? Math.round((stats.captioned / stats.total) * 100) : 0
  const videoNames = allVideos.map(v => v.name ? v.name.replace(/\.[^.]+$/, '') : v)

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
          <div className="progress-bar-wrap">
            <div className="progress-bar" style={{ width: `${pct}%` }} />
          </div>
          <div className="stats-numbers">
            <span className="stats-total">{stats.total.toLocaleString()} scenes</span>
            <span className="stats-captioned">{stats.captioned.toLocaleString()} captioned ({pct}%)</span>
          </div>
        </div>

        {/* Filter buttons */}
        <div className="filter-buttons">
          {['all', 'captioned', 'uncaptioned'].map(f => (
            <button
              key={f}
              className={`filter-btn${filter === f ? ' active' : ''}`}
              onClick={() => setFilter(f)}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>

        {/* Video filter */}
        <select
          className="video-select"
          value={videoFilter}
          onChange={e => setVideoFilter(e.target.value)}
        >
          <option value="">All videos</option>
          {videoNames.map(name => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>

        <div className="header-spacer" />

        {/* Auto-refresh */}
        <label className="autorefresh-label">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={e => setAutoRefresh(e.target.checked)}
          />
          Auto-refresh
        </label>

        {/* Action buttons */}
        <button className="action-btn" onClick={onManageTags}>Manage Tags</button>
        <button className="action-btn" onClick={onManageVideos}>Videos</button>
      </div>

      {/* Tag filter bar */}
      <div className="tag-filter-bar">
        <div className="tag-filter-row">
          <span className="tag-filter-label">Show:</span>
          {activeIncludeTags.size > 1 && (
            <button
              className={`mode-toggle mode-toggle--${includeMode}`}
              onClick={() => setIncludeMode(m => m === 'and' ? 'or' : 'and')}
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
          <button ref={includeAddRef} className="tag-filter-add" onClick={() => openDropdown('include', includeAddRef)}>+ tag</button>
        </div>

        <div className="tag-filter-row">
          <span className="tag-filter-label">Hide:</span>
          {[...activeExcludeTags].map(tag => (
            <span key={tag} className="tag-filter-pill tag-filter-pill--exclude">
              {allTags.find(t => t.tag === tag)?.display_name || tag}
              <span className="remove-x" onClick={() => setActiveExcludeTags(prev => { const s = new Set(prev); s.delete(tag); return s })}>✕</span>
            </span>
          ))}
          <button ref={excludeAddRef} className="tag-filter-add" onClick={() => openDropdown('exclude', excludeAddRef)}>+ tag</button>

          <div className="header-spacer" />

          <div className="min-frames-wrap">
            <label>Min frames:</label>
            <input
              type="number"
              className="min-frames-input"
              min="0"
              value={minFrames}
              onChange={e => setMinFrames(Math.max(0, parseInt(e.target.value) || 0))}
            />
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
