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
  const [detailCollapsed, setDetailCollapsed] = useState(true)
  const [detailTab, setDetailTab] = useState('info')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)  // null | { videoId, stats } | { error }
  const importFileRef = useRef(null)
  const [pendingImportFile, setPendingImportFile] = useState(null)  // File awaiting video selection
  const [videoPickModalOpen, setVideoPickModalOpen] = useState(false)
  const [videoPickId, setVideoPickId] = useState(null)
  const uploadVideoRef = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadResult, setUploadResult] = useState(null)  // null | { name } | { error }

  const [refreshing, setRefreshing] = useState(false)
  const [refreshResult, setRefreshResult] = useState(null)  // null | { indexed } | { error }

  const [mobilePickerOpen, setMobilePickerOpen] = useState(false)

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

  // Expanded folder state — persisted; root folder expanded by default
  const [expandedFolders, setExpandedFolders] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem('expandedFolders') || '[""]')) }
    catch { return new Set(['']) }
  })

  function toggleFolder(folder) {
    setExpandedFolders(prev => {
      const next = new Set(prev)
      next.has(folder) ? next.delete(folder) : next.add(folder)
      try { localStorage.setItem('expandedFolders', JSON.stringify([...next])) } catch {}
      return next
    })
  }

  // Group videos by parent directory
  const videosByFolder = useMemo(() => {
    const map = new Map()
    for (const v of videos) {
      const parts = (v.path || '').split('/')
      const folder = parts.length > 1 ? parts.slice(0, -1).join('/') : ''
      if (!map.has(folder)) map.set(folder, [])
      map.get(folder).push(v)
    }
    // Sort folders alphabetically; empty string (root) last
    return new Map([...map.entries()].sort(([a], [b]) => {
      if (a === '') return 1
      if (b === '') return -1
      return a.localeCompare(b)
    }))
  }, [videos])

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
      })
  }, [])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') navigate('/') }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navigate])

  const selected = videos.find(v => v.id === videoId) ?? null

  useEffect(() => { setDetailTab('info') }, [videoId])

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

  async function handleRefresh() {
    setRefreshing(true)
    setRefreshResult(null)
    try {
      const r = await fetch('/api/videos/refresh', { method: 'POST' })
      const d = await r.json()
      if (!r.ok) {
        setRefreshResult({ error: d.error || 'Refresh failed' })
        return
      }
      const listRes = await fetch('/api/videos')
      const listData = await listRes.json()
      const vids = (listData.videos || []).slice().sort((a, b) =>
        (a.name || a.path).localeCompare(b.name || b.path)
      )
      const prevCount = videos.length
      setVideos(vids)
      setRefreshResult({ indexed: d.indexed, added: Math.max(0, vids.length - prevCount) })
    } catch {
      setRefreshResult({ error: 'Request failed' })
    } finally {
      setRefreshing(false)
    }
  }

  function handleUploadVideo(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setUploadResult(null)
    setUploading(true)
    setUploadProgress(0)
    const fd = new FormData()
    fd.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.upload.onprogress = ev => {
      if (ev.lengthComputable) setUploadProgress(Math.round(ev.loaded / ev.total * 100))
    }
    xhr.onload = () => {
      setUploading(false)
      setUploadProgress(0)
      const d = JSON.parse(xhr.responseText)
      if (xhr.status === 200) {
        setUploadResult({ name: d.name })
      } else {
        setUploadResult({ error: d.error || 'Upload failed' })
      }
    }
    xhr.onerror = () => { setUploading(false); setUploadResult({ error: 'Upload failed' }) }
    xhr.open('POST', '/api/videos/upload')
    xhr.send(fd)
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
      {/* Mobile picker bar — only visible on phone-sized screens */}
      <button
        type="button"
        className="list-mobile-picker"
        onClick={() => setMobilePickerOpen(o => !o)}
        aria-expanded={mobilePickerOpen}
      >
        <span className="list-mobile-picker__label">
          {selected ? selected.name : (videos.length === 0 ? 'No videos' : 'Choose video…')}
        </span>
        <span className="list-mobile-picker__chev" aria-hidden="true">{mobilePickerOpen ? '▾' : '▸'}</span>
      </button>
      {mobilePickerOpen && (
        <div
          className="list-mobile-backdrop"
          onClick={() => setMobilePickerOpen(false)}
        />
      )}
      <div className="videos-layout">
        {/* Sidebar */}
        <div className={`videos-sidebar${mobilePickerOpen ? ' videos-sidebar--open' : ''}`}>
          {loading ? (
            [1,2,3].map(n => (
              <div key={n} className="video-sidebar-item video-sidebar-item--skeleton">
                <span className="skeleton skeleton--text" style={{ width: `${50 + n * 15}%` }} />
                <span className="skeleton skeleton--text" style={{ width: 24 }} />
                <span className="skeleton skeleton--text" style={{ width: 36 }} />
              </div>
            ))
          ) : [...videosByFolder.entries()].map(([folder, folderVideos]) => {
            const collapsed = !expandedFolders.has(folder)
            const folderLabel = folder ? folder.split('/').pop() : '/'
            const hasActive = folderVideos.some(v => v.id === videoId)
            return (
              <div key={folder || '__root__'} className="video-folder-group">
                <div
                  className={`video-folder-header${hasActive ? ' video-folder-header--active' : ''}`}
                  onClick={() => toggleFolder(folder)}
                  title={folder || '/'}
                >
                  <span className="video-folder-chevron">{collapsed ? '▸' : '▾'}</span>
                  <span className="video-folder-name">{folderLabel}</span>
                  <span className="video-folder-count">{folderVideos.length}</span>
                </div>
                {!collapsed && folderVideos.map(v => (
                  <div
                    key={v.id}
                    className={`video-sidebar-item video-sidebar-item--nested${v.id === videoId ? ' video-sidebar-item--active' : ''}`}
                    onClick={() => {
                      setImportResult(null)
                      setMobilePickerOpen(false)
                      navigate(v.id === videoId ? '/videos' : `/videos/${v.id}`)
                    }}
                  >
                    <span className="video-sidebar-name">{v.name}</span>
                    <span className="video-sidebar-count">{v.scene_count}</span>
                    <span className="video-sidebar-frames" title="Total frames">{v.total_frames > 0 ? `${v.total_frames.toLocaleString()}f` : ''}</span>
                  </div>
                ))}
              </div>
            )
          })}

          {/* Refresh — re-scan source directory for new files */}
          <div className="sidebar-import-zone">
            <button
              className="sidebar-import-btn"
              disabled={refreshing}
              onClick={handleRefresh}
              title="Scan the source directory for new video files"
            >{refreshing ? 'Scanning…' : '↻ Refresh'}</button>
            {refreshResult && (
              refreshResult.error
                ? <div className="import-result import-result--error">{refreshResult.error}</div>
                : <div className="import-result import-result--ok">
                    {refreshResult.added > 0
                      ? `+${refreshResult.added} new · ${refreshResult.indexed} total`
                      : `No new videos · ${refreshResult.indexed} total`}
                  </div>
            )}
          </div>

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

          {/* Upload raw video */}
          <div className="sidebar-import-zone">
            <input
              ref={uploadVideoRef}
              type="file"
              accept=".mp4,.mkv,.avi,.mov,.webm,.m4v,.wmv"
              style={{ display: 'none' }}
              onChange={handleUploadVideo}
            />
            {uploading ? (
              <div className="sidebar-upload-progress">
                <div className="sidebar-upload-progress-bar" style={{ width: `${uploadProgress}%` }} />
                <span>Uploading… {uploadProgress}%</span>
              </div>
            ) : (
              <button
                className="sidebar-import-btn"
                onClick={() => { setUploadResult(null); uploadVideoRef.current?.click() }}
              >+ Upload video</button>
            )}
            {uploadResult && (
              uploadResult.error
                ? <div className="import-result import-result--error">{uploadResult.error}</div>
                : <div className="import-result import-result--ok">Uploaded: {uploadResult.name}</div>
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
                  {!detailCollapsed && (
                    <div className="detail-panel-tabs" onClick={e => e.stopPropagation()}>
                      <button className={`detail-tab-btn${detailTab === 'info' ? ' active' : ''}`} onClick={() => setDetailTab('info')}>Info</button>
                      <button className={`detail-tab-btn${detailTab === 'settings' ? ' active' : ''}`} onClick={() => setDetailTab('settings')}>Settings</button>
                    </div>
                  )}
                </div>
                {!detailCollapsed && detailTab === 'info' && (
                  <>
                    <VideoDetail video={selected} onSaved={onVideoSaved} />
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
                {!detailCollapsed && detailTab === 'settings' && (
                  <VideoSettings video={selected} onSaved={onVideoSaved} onDeleted={onVideoDeleted} />
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

function VideoDetail({ video, onSaved }) {
  const [name, setName]     = useState(video.name || '')
  const [prompt, setPrompt] = useState(video.prompt || '')
  const [savedName,   setSavedName]   = useState(video.name || '')
  const [savedPrompt, setSavedPrompt] = useState(video.prompt || '')
  const [nameStatus,   setNameStatus]   = useState('')
  const [promptStatus, setPromptStatus] = useState('')

  const [scanOverride, setScanOverride] = useState(false)
  const [scanning,     setScanning]     = useState(false)
  const [scanResult,   setScanResult]   = useState(null)  // null | { scenes, cleared } | { error }

  useEffect(() => {
    setName(video.name || '')
    setPrompt(video.prompt || '')
    setSavedName(video.name || '')
    setSavedPrompt(video.prompt || '')
    setNameStatus('')
    setPromptStatus('')
    setScanOverride(false)
    setScanResult(null)
  }, [video.id])

  async function scanScenes() {
    if (scanOverride && !window.confirm(
      `Override existing scenes for "${video.name || video.path}"?\n\n` +
      `This will permanently delete existing scenes, candidates, samples, ` +
      `and buckets for this video, then re-run scene detection.`
    )) return
    setScanning(true)
    setScanResult(null)
    try {
      const r = await fetch(`/api/videos/${video.id}/scan-scenes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ override: scanOverride }),
      })
      const d = await r.json()
      if (!r.ok) { setScanResult({ error: d.error || 'Scan failed' }); return }
      onSaved?.({ id: video.id, scene_count: d.scenes })
      setScanResult({ scenes: d.scenes, cleared: d.cleared_scenes })
    } catch {
      setScanResult({ error: 'Request failed' })
    } finally {
      setScanning(false)
    }
  }

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
          <div className="progress-bar-wrap" style={{ height: 4, borderRadius: 2, marginTop: 4 }}>
            <div className="progress-bar" style={{ width: `${pct}%` }} />
          </div>
          {video.face_count > 0 && (
            <span className="video-detail-face-count">👤 {video.face_count.toLocaleString()} face embeddings</span>
          )}
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
          <label className="video-detail-label">Scene detection</label>
          <div className="video-detail-input-row">
            <button
              className="save-btn"
              disabled={scanning}
              onClick={scanScenes}
            >{scanning ? 'Scanning…' : 'Scan scenes'}</button>
            <label className="video-detail-checkbox">
              <input
                type="checkbox"
                checked={scanOverride}
                onChange={e => setScanOverride(e.target.checked)}
                disabled={scanning}
              />
              <span>Override existing scenes</span>
            </label>
            <span className="video-detail-status">
              {scanResult && (
                scanResult.error
                  ? <span className="video-detail-status--error">{scanResult.error}</span>
                  : <span>
                      ✓ {scanResult.scenes} scenes
                      {scanResult.cleared > 0 ? ` (cleared ${scanResult.cleared})` : ''}
                    </span>
              )}
            </span>
          </div>
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

function VideoSettings({ video, onSaved, onDeleted }) {
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteConfirm,   setDeleteConfirm]   = useState('')
  const [deleting,        setDeleting]        = useState(false)
  const [deleteError,     setDeleteError]     = useState('')
  const [deleteFile,      setDeleteFile]      = useState(false)

  const initialOverride = video.fps_override == null ? '' : String(video.fps_override)
  const [fpsDraft,  setFpsDraft]  = useState(initialOverride)
  const [fpsStatus, setFpsStatus] = useState('')

  const initialFilename = video.path ? video.path.split('/').pop() : ''
  const [filenameDraft, setFilenameDraft] = useState(initialFilename)
  const [renameStatus,  setRenameStatus]  = useState('')
  const [renaming,      setRenaming]      = useState(false)

  useEffect(() => {
    setShowDeleteModal(false)
    setDeleteConfirm('')
    setDeleteError('')
    setDeleteFile(false)
    setFpsDraft(video.fps_override == null ? '' : String(video.fps_override))
    setFpsStatus('')
    setFilenameDraft(video.path ? video.path.split('/').pop() : '')
    setRenameStatus('')
    setRenaming(false)
  }, [video.id, video.fps_override, video.path])

  async function renameFile() {
    const trimmed = filenameDraft.trim()
    if (!trimmed || trimmed === initialFilename) return
    setRenaming(true)
    setRenameStatus('Renaming…')
    try {
      const r = await fetch(`/api/videos/${video.id}/rename`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: trimmed }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Rename failed')
      // If the displayed name was the old basename (no custom display name set),
      // follow the rename. Otherwise keep the user's custom name.
      const nextName = video.name === initialFilename ? d.name : video.name
      onSaved?.({ id: video.id, path: d.path, name: nextName })
      setRenameStatus('✓ Renamed')
      setTimeout(() => setRenameStatus(''), 3000)
    } catch (err) {
      setRenameStatus(err.message || 'Error')
    } finally {
      setRenaming(false)
    }
  }

  async function saveFpsOverride(value) {
    setFpsStatus('Saving…')
    try {
      const r = await fetch(`/api/videos/${video.id}/fps-override`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fps_override: value === '' ? null : value }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Save failed')
      onSaved?.({ id: video.id, fps_override: d.fps_override })
      setFpsStatus(d.fps_override == null ? '✓ Cleared' : '✓ Saved')
      setTimeout(() => setFpsStatus(''), 3000)
    } catch (err) {
      setFpsStatus(err.message || 'Error')
    }
  }

  const confirmTitle = video.name || video.path.split('/').pop().replace(/\.[^.]+$/, '')
  const deleteReady  = deleteConfirm === confirmTitle

  async function doDelete() {
    if (!deleteReady) return
    setDeleting(true)
    setDeleteError('')
    try {
      const url = `/api/videos/${video.id}${deleteFile ? '?delete_file=1' : ''}`
      const r = await fetch(url, { method: 'DELETE' })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || 'Delete failed')
      onDeleted(video.id)
    } catch (err) {
      setDeleteError(err.message)
      setDeleting(false)
    }
  }

  const detectedFps = video.fps ? parseFloat(video.fps).toFixed(3) : '—'
  const fpsDirty = fpsDraft !== initialOverride

  const filenameDirty = filenameDraft.trim() !== initialFilename && filenameDraft.trim().length > 0

  return (
    <div className="video-detail">
      <div className="video-detail-fields">
        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">
            Filename
            <span className="video-detail-label-hint"> — rename the source file on disk; cached clips and waveforms move with it</span>
          </label>
          <div className="video-detail-input-row">
            <input
              className="video-detail-input"
              value={filenameDraft}
              placeholder={initialFilename}
              onChange={e => { setFilenameDraft(e.target.value); setRenameStatus('') }}
              onKeyDown={e => { if (e.key === 'Enter' && filenameDirty && !renaming) renameFile() }}
              disabled={renaming}
            />
            <span className="video-detail-status">{renameStatus}</span>
            <button
              className="save-btn"
              disabled={!filenameDirty || renaming}
              onClick={renameFile}
            >Rename</button>
          </div>
        </div>

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">
            FPS override
            <span className="video-detail-label-hint"> — used for scene/clip preview playback math and as the source rate before export re-encodes to 24 fps. Detected: <strong>{detectedFps}</strong></span>
          </label>
          <div className="video-detail-input-row">
            <input
              className="video-detail-input"
              value={fpsDraft}
              placeholder={`Use detected (${detectedFps})`}
              onChange={e => { setFpsDraft(e.target.value); setFpsStatus('') }}
              onKeyDown={e => { if (e.key === 'Enter' && fpsDirty) saveFpsOverride(fpsDraft) }}
              inputMode="decimal"
            />
            <span className="video-detail-status">{fpsStatus}</span>
            {video.fps_override != null && (
              <button
                className="save-btn"
                onClick={() => { setFpsDraft(''); saveFpsOverride('') }}
                title="Clear override and use detected FPS"
              >Clear</button>
            )}
            <button
              className="save-btn"
              disabled={!fpsDirty}
              onClick={() => saveFpsOverride(fpsDraft)}
            >Save</button>
          </div>
        </div>

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">Export</label>
          <div className="video-detail-input-row">
            <span className="video-detail-hint">Download scenes, tags, and clips for this video as a zip file.</span>
            <a className="save-btn" href={`/api/videos/${video.id}/export`} download>Export DB</a>
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
            </p>
            <label className="delete-video-file-label">
              <input
                type="checkbox"
                checked={deleteFile}
                onChange={e => setDeleteFile(e.target.checked)}
              />
              <span>Delete video file from disk</span>
              {deleteFile && <span className="delete-video-file-warn"> ⚠ This cannot be undone</span>}
            </label>
            <p className="delete-video-body">Type <strong>{confirmTitle}</strong> to confirm:</p>
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
              <button className="delete-video-cancel" onClick={() => { setShowDeleteModal(false); setDeleteConfirm(''); setDeleteFile(false) }} disabled={deleting}>Cancel</button>
              <button className="delete-video-confirm" onClick={doDelete} disabled={!deleteReady || deleting}>
                {deleting ? 'Deleting…' : deleteFile ? 'Delete DB + File' : 'Delete'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}
