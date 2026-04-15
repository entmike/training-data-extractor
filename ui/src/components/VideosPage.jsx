import { useState, useEffect, useRef, useContext, useMemo } from 'react'
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
  const [detailCollapsed, setDetailCollapsed] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)  // null | { videoId, stats } | { error }
  const importFileRef = useRef(null)
  const [pendingImportFile, setPendingImportFile] = useState(null)  // File awaiting video selection
  const [videoPickModalOpen, setVideoPickModalOpen] = useState(false)
  const [videoPickId, setVideoPickId] = useState(null)

  // Filters
  const [activeIncludeTags, setActiveIncludeTags] = useState(new Set())
  const [activeExcludeTags, setActiveExcludeTags] = useState(new Set())
  const [includeMode, setIncludeMode] = useState('and')
  const [minFrames, setMinFrames] = useState(0)
  const [ratingFilter, setRatingFilter] = useState(new Set())
  const [framesMode, setFramesMode] = useState('0')
  const [customDraft, setCustomDraft] = useState('')
  const [dropdown, setDropdown] = useState(null)
  const [videoTags, setVideoTags] = useState([])
  const includeAddRef = useRef(null)
  const excludeAddRef = useRef(null)

  const videoId = videoIdParam ? Number(videoIdParam) : null

  useEffect(() => {
    if (videoId == null) { setVideoTags([]); return }
    fetch(`/api/tags/all?video=${videoId}`)
      .then(r => r.json())
      .then(d => setVideoTags(d.tags || []))
      .catch(() => setVideoTags([]))
  }, [videoId])

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

  function onVideoDeleted(deletedId) {
    const remaining = videos.filter(v => v.id !== deletedId)
    setVideos(remaining)
    if (remaining.length > 0) navigate(`/videos/${remaining[0].id}`, { replace: true })
    else navigate('/videos', { replace: true })
  }

  async function doImport(file, videoId = null) {
    setImporting(true)
    setImportResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (videoId != null) fd.append('video_id', videoId)
      const r = await fetch('/api/videos/import', { method: 'POST', body: fd })
      const d = await r.json()
      if (r.status === 422 && d.needs_video_selection) {
        // Zip has no video.json — ask user to pick a video
        setPendingImportFile(file)
        setVideoPickId(videos[0]?.id ?? null)
        setVideoPickModalOpen(true)
        return
      }
      if (!r.ok) { setImportResult({ error: d.error || 'Import failed' }); return }
      const listRes = await fetch('/api/videos')
      const listData = await listRes.json()
      const vids = (listData.videos || []).slice().sort((a, b) =>
        (a.name || a.path).localeCompare(b.name || b.path)
      )
      setVideos(vids)
      setImportResult({ videoId: d.video_id, stats: d.stats })
      navigate(`/videos/${d.video_id}`, { replace: true })
    } catch { setImportResult({ error: 'Request failed' }) }
    finally { setImporting(false) }
  }

  async function handleImport(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    await doImport(file)
  }

  async function handleVideoPickConfirm() {
    const file = pendingImportFile
    const vid = videoPickId
    setVideoPickModalOpen(false)
    setPendingImportFile(null)
    if (!file || !vid) return
    await doImport(file, vid)
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

  // When a video is selected use video-scoped tags for scene-card suggestions;
  // fall back to global tagMap only while videoTags hasn't loaded yet.
  const effectiveTagMap = useMemo(() => {
    if (!videoId || videoTags.length === 0) return tagMap
    return Object.fromEntries(videoTags.map(t => [t.tag, t]))
  }, [videoId, videoTags, tagMap])

  const usedTags = new Set([...activeIncludeTags, ...activeExcludeTags])
  const availableTags = videoTags.filter(t => !usedTags.has(t.tag))

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
              onClick={() => { setImportResult(null); navigate(`/videos/${v.id}`) }}
            >
              <span className="video-sidebar-name">{v.name}</span>
              <span className="video-sidebar-count">{v.scene_count}</span>
            </div>
          ))}

          {/* Import from zip */}
          <div className="sidebar-import-zone">
            <input
              ref={importFileRef}
              type="file"
              accept=".zip"
              style={{ display: 'none' }}
              onChange={handleImport}
            />
            <button
              className="sidebar-import-btn"
              disabled={importing}
              onClick={() => { setImportResult(null); importFileRef.current?.click() }}
            >{importing ? 'Importing…' : '+ Import from zip'}</button>
            {importResult && (
              importResult.error
                ? <div className="import-result import-result--error">{importResult.error}</div>
                : <div className="import-result import-result--ok">
                    {importResult.stats.scenes_created} scenes
                    &nbsp;·&nbsp;{importResult.stats.tags_added} tags
                    &nbsp;·&nbsp;{importResult.stats.clip_items_added} clips
                  </div>
            )}
          </div>
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
                {!detailCollapsed && (
                  <>
                    <VideoDetail video={selected} onSaved={onVideoSaved} onDeleted={onVideoDeleted} />
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
                  </>
                )}
              </div>
              <div className="videos-scenes-panel">
                <SceneGrid
                  videoFilter={String(selected.id)}
                  activeIncludeTags={activeIncludeTags}
                  activeExcludeTags={activeExcludeTags}
                  includeMode={includeMode}
                  minFrames={minFrames}
                  ratingFilter={ratingFilter}
                  tagMap={effectiveTagMap}
                  onLoadingChange={setIsGridLoading}
                  totalCount={selected.scene_count}
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

      {videoPickModalOpen && createPortal(
        <div className="modal-overlay" onClick={() => setVideoPickModalOpen(false)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <div className="modal-title">Select video for import</div>
            <p className="modal-body-text">
              This zip has no <code>video.json</code>. Which video do these scenes belong to?
            </p>
            <select
              className="modal-video-select"
              value={videoPickId ?? ''}
              onChange={e => setVideoPickId(Number(e.target.value))}
            >
              {videos.map(v => (
                <option key={v.id} value={v.id}>{v.name || v.path}</option>
              ))}
            </select>
            <div className="modal-actions">
              <button className="modal-btn modal-btn--cancel" onClick={() => setVideoPickModalOpen(false)}>Cancel</button>
              <button className="modal-btn modal-btn--confirm" disabled={!videoPickId} onClick={handleVideoPickConfirm}>Import</button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}

function VideoDetail({ video, onSaved, onDeleted }) {
  const [name, setName]     = useState(video.name || '')
  const [prompt, setPrompt] = useState(video.prompt || '')
  const [savedName,   setSavedName]   = useState(video.name || '')
  const [savedPrompt, setSavedPrompt] = useState(video.prompt || '')
  const [nameStatus,   setNameStatus]   = useState('')
  const [promptStatus, setPromptStatus] = useState('')
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteConfirm,   setDeleteConfirm]   = useState('')
  const [deleting,        setDeleting]        = useState(false)
  const [deleteError,     setDeleteError]     = useState('')

  useEffect(() => {
    setName(video.name || '')
    setPrompt(video.prompt || '')
    setSavedName(video.name || '')
    setSavedPrompt(video.prompt || '')
    setNameStatus('')
    setPromptStatus('')
    setShowDeleteModal(false)
    setDeleteConfirm('')
    setDeleteError('')
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

  const confirmTitle = video.name || video.path.split('/').pop().replace(/\.[^.]+$/, '')
  const deleteReady  = deleteConfirm === confirmTitle

  async function doDelete() {
    if (!deleteReady) return
    setDeleting(true)
    setDeleteError('')
    try {
      const r = await fetch(`/api/videos/${video.id}`, { method: 'DELETE' })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || 'Delete failed')
      onDeleted(video.id)
    } catch (err) {
      setDeleteError(err.message)
      setDeleting(false)
    }
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

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">Export</label>
          <div className="video-detail-input-row">
            <span className="video-detail-hint">Download scenes, tags, and clips for this video as a zip file.</span>
            <a
              className="save-btn"
              href={`/api/videos/${video.id}/export`}
              download
            >Export DB</a>
          </div>
        </div>

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label video-detail-label--danger">Danger zone</label>
          <div className="video-detail-input-row">
            <span className="video-detail-hint">Remove this video and all its scenes, tags, and clips from the database. The source file is not deleted.</span>
            <button className="delete-video-btn" onClick={() => setShowDeleteModal(true)}>Delete Video</button>
          </div>
        </div>
      </div>

      {showDeleteModal && createPortal(
        <div className="delete-video-overlay" onClick={e => { if (e.target === e.currentTarget) setShowDeleteModal(false) }}>
          <div className="delete-video-modal">
            <h3 className="delete-video-title">Delete video from database?</h3>
            <p className="delete-video-body">
              This will permanently remove <strong>{confirmTitle}</strong> and all its scenes, tags, buckets, and clip memberships from the database.
              The source video file will not be touched.
            </p>
            <p className="delete-video-body">
              Type <strong>{confirmTitle}</strong> to confirm:
            </p>
            <input
              className="delete-video-input"
              value={deleteConfirm}
              onChange={e => { setDeleteConfirm(e.target.value); setDeleteError('') }}
              placeholder={confirmTitle}
              autoFocus
              onKeyDown={e => e.key === 'Enter' && deleteReady && doDelete()}
            />
            {deleteError && <p className="delete-video-error">{deleteError}</p>}
            <div className="delete-video-actions">
              <button className="delete-video-cancel" onClick={() => { setShowDeleteModal(false); setDeleteConfirm('') }} disabled={deleting}>Cancel</button>
              <button className="delete-video-confirm" onClick={doDelete} disabled={!deleteReady || deleting}>
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}
