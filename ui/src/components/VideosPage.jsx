import { useState, useEffect, useRef, useContext } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useParams } from 'react-router-dom'
import { AppContext } from '../context'
import SceneGrid from './SceneGrid'
import TagDropdown from './TagDropdown'

function fmtDuration(secs) {
  if (!secs) return '—'
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = Math.floor(secs % 60)
  return h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`
}

const PRESET_FRAMES = [0, 24, 48, 72, 96, 120]

export default function VideosPage({ tagMap, allTags }) {
  const { videoId: videoIdParam } = useParams()
  const navigate = useNavigate()
  const { openPlayer, refreshTags } = useContext(AppContext)

  const [videos, setVideos] = useState([])
  const [loading, setLoading] = useState(true)
  const [isGridLoading, setIsGridLoading] = useState(false)
  const [viewMode, setViewMode] = useState('card')
  const [detailCollapsed, setDetailCollapsed] = useState(false)

  // Filters
  const [activeIncludeTags, setActiveIncludeTags] = useState(new Set())
  const [activeExcludeTags, setActiveExcludeTags] = useState(new Set())
  const [includeMode, setIncludeMode] = useState('and')
  const [minFrames, setMinFrames] = useState(0)
  const [ratingFilter, setRatingFilter] = useState(new Set())
  const [framesMode, setFramesMode] = useState('0')
  const [customDraft, setCustomDraft] = useState('')
  const [dropdown, setDropdown] = useState(null)
  const includeAddRef = useRef(null)
  const excludeAddRef = useRef(null)

  const videoId = videoIdParam ? Number(videoIdParam) : null

  useEffect(() => {
    fetch('/api/videos')
      .then(r => r.json())
      .then(d => {
        const vids = (d.videos || []).slice().sort((a, b) =>
          (a.name || a.path).localeCompare(b.name || b.path)
        )
        setVideos(vids)
        setLoading(false)
        if (!videoIdParam && vids.length > 0) {
          navigate(`/videos/${vids[0].id}`, { replace: true })
        }
      })
  }, [])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') navigate('/') }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navigate])

  const selected = videos.find(v => v.id === videoId) ?? null

  function onVideoSaved(updatedVideo) {
    setVideos(vs => vs.map(v => v.id === updatedVideo.id ? { ...v, ...updatedVideo } : v))
  }

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

  const usedTags = new Set([...activeIncludeTags, ...activeExcludeTags])
  const availableTags = allTags.filter(t => !usedTags.has(t.tag))

  return (
    <div className="videos-page">
      <div className="videos-layout">
        {/* Sidebar */}
        <div className="videos-sidebar">
          {loading ? (
            [1,2,3].map(n => (
              <div key={n} className="video-sidebar-item video-sidebar-item--skeleton">
                <span className="skeleton skeleton--text" style={{ width: `${50 + n * 15}%` }} />
                <span className="skeleton skeleton--text" style={{ width: 30 }} />
              </div>
            ))
          ) : videos.map(v => (
            <div
              key={v.id}
              className={`video-sidebar-item${v.id === videoId ? ' video-sidebar-item--active' : ''}`}
              onClick={() => navigate(`/videos/${v.id}`)}
            >
              <span className="video-sidebar-name">{v.name}</span>
              <span className="video-sidebar-count">{v.scene_count}</span>
            </div>
          ))}
        </div>

        {/* Right panel */}
        <div className="videos-right-panel">
          {selected ? (
            <>
              <div className="videos-detail-panel">
                <div className="detail-panel-header" onClick={() => setDetailCollapsed(c => !c)}>
                  <span className="collapse-toggle-btn">{detailCollapsed ? '▸' : '▾'}</span>
                  <span className="detail-panel-title">{selected.name || selected.path}</span>
                </div>
                {!detailCollapsed && <VideoDetail video={selected} onSaved={onVideoSaved} />}
              </div>
              <div className="videos-scenes-panel">
                {/* Toolbar: view toggle + count */}
                <div className="videos-scenes-toolbar">
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
                  <span className="videos-scenes-count">{selected.scene_count} scenes</span>
                </div>

                {/* Tag / frame / rating filters */}
                <div className="tag-filter-bar">
                  <div className="tag-filter-row">
                    <span className="tag-filter-label">Show:</span>
                    {activeIncludeTags.size > 1 && (
                      <button
                        className={`mode-toggle mode-toggle--${includeMode}`}
                        onClick={() => setIncludeMode(m => m === 'and' ? 'or' : 'and')}
                        disabled={isGridLoading}
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
                    <button ref={includeAddRef} className="tag-filter-add" onClick={() => openDropdown('include', includeAddRef)} disabled={isGridLoading}>+ tag</button>
                  </div>

                  <div className="tag-filter-row">
                    <span className="tag-filter-label">Hide:</span>
                    {[...activeExcludeTags].map(tag => (
                      <span key={tag} className="tag-filter-pill tag-filter-pill--exclude">
                        {allTags.find(t => t.tag === tag)?.display_name || tag}
                        <span className="remove-x" onClick={() => setActiveExcludeTags(prev => { const s = new Set(prev); s.delete(tag); return s })}>✕</span>
                      </span>
                    ))}
                    <button ref={excludeAddRef} className="tag-filter-add" onClick={() => openDropdown('exclude', excludeAddRef)} disabled={isGridLoading}>+ tag</button>

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
                        disabled={isGridLoading}
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
                          disabled={isGridLoading}
                          autoFocus
                        />
                      )}
                    </div>

                    <div className="rating-filter-wrap">
                      <span className="rating-filter-label">Rating:</span>
                      <button
                        className={`rating-filter-btn${ratingFilter.size === 0 ? ' active' : ''}`}
                        onClick={() => setRatingFilter(new Set())}
                        disabled={isGridLoading}
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
                          disabled={isGridLoading}
                        >{opt.label}</button>
                      ))}
                    </div>
                  </div>
                </div>

                <SceneGrid
                  videoFilter={String(selected.id)}
                  activeIncludeTags={activeIncludeTags}
                  activeExcludeTags={activeExcludeTags}
                  includeMode={includeMode}
                  minFrames={minFrames}
                  ratingFilter={ratingFilter}
                  viewMode={viewMode}
                  tagMap={tagMap}
                  onLoadingChange={setIsGridLoading}
                />
              </div>
            </>
          ) : !loading && (
            <div className="videos-empty">Select a video</div>
          )}
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
    </div>
  )
}

function VideoDetail({ video, onSaved }) {
  const [name, setName]     = useState(video.name || '')
  const [prompt, setPrompt] = useState(video.prompt || '')
  const [savedName,   setSavedName]   = useState(video.name || '')
  const [savedPrompt, setSavedPrompt] = useState(video.prompt || '')
  const [nameStatus,   setNameStatus]   = useState('')
  const [promptStatus, setPromptStatus] = useState('')

  useEffect(() => {
    setName(video.name || '')
    setPrompt(video.prompt || '')
    setSavedName(video.name || '')
    setSavedPrompt(video.prompt || '')
    setNameStatus('')
    setPromptStatus('')
  }, [video.id])

  const pct = video.scene_count > 0
    ? Math.round((video.captioned / video.scene_count) * 100) : 0

  async function saveName() {
    setNameStatus('Saving…')
    try {
      const r = await fetch(`/api/videos/${video.id}/name`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (!r.ok) throw new Error()
      setSavedName(name)
      onSaved({ id: video.id, name })
      setNameStatus('✓ Saved')
      setTimeout(() => setNameStatus(''), 3000)
    } catch { setNameStatus('Error') }
  }

  async function savePrompt() {
    setPromptStatus('Saving…')
    try {
      const r = await fetch(`/api/prompts/${video.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      if (!r.ok) throw new Error()
      setSavedPrompt(prompt)
      onSaved({ id: video.id, prompt })
      setPromptStatus('✓ Saved')
      setTimeout(() => setPromptStatus(''), 3000)
    } catch { setPromptStatus('Error') }
  }

  return (
    <div className="video-detail">
      {/* Stats bar */}
      <div className="video-detail-stats">
        <div className="video-detail-meta">
          {[
            video.width && video.height ? `${video.width}×${video.height}` : null,
            video.fps ? `${parseFloat(video.fps).toFixed(2)} fps` : null,
            fmtDuration(video.duration),
            video.codec || null,
          ].filter(Boolean).join(' · ')}
        </div>
        <div className="video-detail-counts">
          <span className="video-detail-captioned">{video.captioned} / {video.scene_count} captioned ({pct}%)</span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="video-detail-progress-wrap">
        <div className="progress-bar-wrap" style={{ height: 6, borderRadius: 3 }}>
          <div className="progress-bar" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Fields grid */}
      <div className="video-detail-fields">
        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">File path</label>
          <input className="video-detail-input" value={video.path} readOnly />
        </div>

        <div className="video-detail-field">
          <label className="video-detail-label">Frame offset</label>
          <input className="video-detail-input" value={video.frame_offset ?? 0} readOnly />
        </div>

        <div className="video-detail-field">
          <label className="video-detail-label">Hash</label>
          <input className="video-detail-input" value={(video.hash || '').slice(0, 16) + '…'} readOnly title={video.hash} />
        </div>

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">Display name</label>
          <div className="video-detail-input-row">
            <input
              className="video-detail-input"
              value={name}
              placeholder="User-friendly name…"
              onChange={e => setName(e.target.value)}
            />
            <span className="video-detail-status">{nameStatus}</span>
            <button
              className="save-btn"
              disabled={name === savedName}
              onClick={saveName}
            >Save</button>
          </div>
        </div>

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">
            Caption prompt
            <span className="video-detail-label-hint"> — per-video override; leave blank for system default</span>
          </label>
          <textarea
            className="video-detail-textarea"
            value={prompt}
            placeholder="Optional per-video captioning prompt…"
            rows={3}
            onChange={e => setPrompt(e.target.value)}
          />
          <div className="video-detail-input-row video-detail-input-row--right">
            <span className="video-detail-status">{promptStatus}</span>
            {prompt !== savedPrompt && (
              <button className="save-btn" onClick={savePrompt}>Save</button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
