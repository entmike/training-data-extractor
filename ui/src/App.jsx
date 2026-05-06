import { useState, useEffect, useRef, useCallback } from 'react'
import { Routes, Route, Navigate, useParams, useNavigate, useLocation } from 'react-router-dom'
import { createPortal } from 'react-dom'
import { AppContext } from './context'
import Header from './components/Header'
import VideoPlayerModal from './components/VideoPlayerModal'
import ManageClipsModal from './components/ManageClipsModal'
import VideosPage from './components/VideosPage'
import TagsPage from './components/TagsPage'
import DiscoverPage from './components/DiscoverPage'
import ClusterDetailPage from './components/ClusterDetailPage'
import OutputsPage from './components/OutputsPage'
import ConfigPage from './components/ConfigPage'
import ComfyQueuePage from './components/ComfyQueuePage'
import Toast from './components/Toast'

function ScenePage() {
  const { sceneId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const initialState = location.state && location.state.sceneId ? location.state : null
  const [player, setPlayer] = useState(initialState)

  useEffect(() => {
    if (player) return
    let cancelled = false
    fetch(`/api/scene/${sceneId}`)
      .then(r => { if (!r.ok) throw new Error('Scene not found'); return r.json() })
      .then(data => {
        if (cancelled) return
        const startFrame = data.start_frame ?? Math.round(data.start_time * (data.fps || 24))
        const endFrame   = data.end_frame   ?? Math.round(data.end_time   * (data.fps || 24))
        setPlayer({
          sceneId: data.id,
          videoId: data.video_id,
          videoPath: data.video_path,
          startTime: data.start_time,
          endTime: data.end_time,
          fps: data.fps || 24,
          frameOffset: data.frame_offset || 0,
          startFrame,
          endFrame,
          videoTotalFrames: 0,
          blurhash: data.blurhash,
          videoWidth: data.video_width || 0,
          videoHeight: data.video_height || 0,
          caption: data.caption || '',
          tags: data.tags || [],
          rating: data.rating || 0,
          subtitles: data.subtitles || '',
        })
      })
      .catch(() => { if (!cancelled) navigate('/videos', { replace: true }) })
    return () => { cancelled = true }
  }, [sceneId, player, navigate])

  function handleClose() {
    if (location.key !== 'default') navigate(-1)
    else if (player?.videoId) navigate(`/videos/${player.videoId}`)
    else navigate('/videos')
  }

  return (
    <div className="scene-page-overlay">
      <Header isLoading={false} />
      {player ? (
        <VideoPlayerModal player={player} onClose={handleClose} pageMode />
      ) : (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#888' }}>
          Loading scene…
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [allTags, setAllTags] = useState([])
  const [isLoading] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [queueOpen, setQueueOpen] = useState(false)
  const [nsfwEnabled, setNsfwEnabled] = useState(false)

  // ComfyUI queue polling
  const [comfyQueue, setComfyQueue]       = useState(null)
  const [comfyHistory, setComfyHistory]   = useState(null)
  const [comfyProgress, setComfyProgress] = useState(null)
  const [comfyError, setComfyError]       = useState(null)
  const comfyTimerRef  = useRef(null)
  const comfyProgRef   = useRef(null)
  const prevRunningRef = useRef(null)   // track previous running set for completion detection

  // Toasts
  const [toasts, setToasts] = useState([])
  const toastIdRef = useRef(0)

  function addToast(msg, type = 'success') {
    const id = ++toastIdRef.current
    setToasts(ts => [...ts, { id, msg, type }])
    setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), 5000)
    // Also fire browser notification if permitted
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      new Notification('ComfyUI', { body: msg, icon: '/favicon.ico' })
    }
  }

  function dismissToast(id) {
    setToasts(ts => ts.filter(t => t.id !== id))
  }

  // Request browser notification permission once
  useEffect(() => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  const fetchComfyQueue = useCallback(async () => {
    try {
      const [qr, hr] = await Promise.all([
        fetch('/api/comfyui/queue'),
        fetch('/api/comfyui/history?limit=15'),
      ])
      const qd = await qr.json()
      const hd = await hr.json()
      if (qd.error) { setComfyError(qd.error); setComfyQueue(null); return }
      setComfyError(null)

      // Detect completed / failed jobs
      const prevRunning = prevRunningRef.current
      if (prevRunning !== null) {
        const nowIds = new Set([
          ...(qd.running ?? []).map(j => j.prompt_id),
          ...(qd.pending ?? []).map(j => j.prompt_id),
        ])
        const histMap = {}
        if (!hd.error) {
          for (const h of (hd.history ?? [])) histMap[h.prompt_id] = h
        }
        for (const job of prevRunning) {
          if (!nowIds.has(job.prompt_id)) {
            const hist = histMap[job.prompt_id]
            const short = job.prompt_id.slice(0, 8)
            const label = job.title && job.title !== short ? `"${job.title}"` : short
            if (hist) {
              const ok = hist.status_str === 'success'
              addToast(`Job ${label} ${ok ? 'completed' : 'failed'}`, ok ? 'success' : 'error')
            } else {
              addToast(`Job ${label} finished`, 'success')
            }
          }
        }
      }
      prevRunningRef.current = qd.running ?? []

      setComfyQueue(qd)
      if (!hd.error) setComfyHistory(hd)
    } catch (e) {
      setComfyError(String(e))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchComfyProgress = useCallback(async () => {
    try {
      const r = await fetch('/api/comfyui/progress')
      const d = await r.json()
      if (!d.error) setComfyProgress(d)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchComfyQueue()
    comfyTimerRef.current = setInterval(fetchComfyQueue, 3000)
    return () => clearInterval(comfyTimerRef.current)
  }, [fetchComfyQueue])

  const hasRunning = (comfyQueue?.running ?? []).length > 0
  useEffect(() => {
    if (hasRunning) {
      fetchComfyProgress()
      comfyProgRef.current = setInterval(fetchComfyProgress, 500)
    } else {
      setComfyProgress(null)
      clearInterval(comfyProgRef.current)
    }
    return () => clearInterval(comfyProgRef.current)
  }, [hasRunning, fetchComfyProgress])

  const deleteQueueItem = useCallback(async (prompt_id) => {
    await fetch('/api/comfyui/queue/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt_id }),
    })
    fetchComfyQueue()
  }, [fetchComfyQueue])

  const clearComfyQueue = useCallback(async () => {
    await fetch('/api/comfyui/queue/clear', { method: 'POST' })
    await fetchComfyQueue()
  }, [fetchComfyQueue])
  const navigate = useNavigate()
  const location = useLocation()
  const backgroundLocation = location.state?.backgroundLocation

  const tagMap = Object.fromEntries(allTags.map(t => [t.tag, t]))

  const fetchTags = useCallback(async () => {
    const r = await fetch('/api/tags/all')
    if (r.ok) { const d = await r.json(); setAllTags(d.tags || []) }
  }, [])

  useEffect(() => { fetchTags() }, [fetchTags])

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(d => setNsfwEnabled(!!(d.nsfw_password || '').trim()))
      .catch(() => {})
  }, [])

  // Close drawer on Escape
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') { setConfigOpen(false); setQueueOpen(false) } }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const openPlayer = useCallback(p => {
    // Strip callbacks — navigation state must be structured-cloneable (no functions).
    const state = { backgroundLocation: location }
    for (const k in p) if (typeof p[k] !== 'function') state[k] = p[k]
    navigate(`/scene/${p.sceneId}`, { state })
  }, [navigate, location])

  const pageLayout = child => (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Header isLoading={isLoading} />
      {child}
    </div>
  )

  return (
    <AppContext.Provider value={{
      tagMap, openPlayer, refreshTags: fetchTags, nsfwEnabled, setNsfwEnabled,
      configOpen, toggleConfig: () => setConfigOpen(o => !o),
      queueOpen, toggleQueue: () => setQueueOpen(o => !o),
      comfyQueue, comfyHistory, comfyProgress, comfyError,
      fetchComfyQueue, deleteQueueItem, clearComfyQueue,
    }}>
      <Routes location={backgroundLocation || location}>
        <Route path="/" element={<Navigate to="/videos" replace />} />
        <Route path="/scene/:sceneId" element={<ScenePage />} />
        <Route path="/videos" element={pageLayout(<VideosPage tagMap={tagMap} allTags={allTags} />)} />
        <Route path="/videos/:videoId" element={pageLayout(<VideosPage tagMap={tagMap} allTags={allTags} />)} />
        <Route path="/clips/:clipId?/:itemId?" element={<ClipsPage tagMap={tagMap} isLoading={isLoading} />} />
        <Route path="/tags" element={pageLayout(<TagsPage />)} />
        <Route path="/tags/:tag" element={pageLayout(<TagsPage />)} />
        <Route path="/discover" element={pageLayout(<DiscoverPage />)} />
        <Route path="/cluster/:clusterId" element={pageLayout(<ClusterDetailPage />)} />
        <Route path="/outputs" element={pageLayout(<OutputsPage />)} />
        <Route path="/config" element={<Navigate to="/videos" replace />} />
      </Routes>

      {backgroundLocation && (
        <Routes>
          <Route path="/scene/:sceneId" element={<ScenePage />} />
        </Routes>
      )}

      {createPortal(
        <>
          {configOpen && (
            <div className="config-drawer-overlay" onClick={() => setConfigOpen(false)} />
          )}
          <div className={`config-drawer${configOpen ? ' config-drawer--open' : ''}`}>
            <div className="config-drawer-header">
              <span className="config-drawer-title">Configuration</span>
              <button className="config-drawer-close" onClick={() => setConfigOpen(false)} aria-label="Close">✕</button>
            </div>
            <div className="config-drawer-body">
              <ConfigPage />
            </div>
          </div>
        </>,
        document.body
      )}

      {createPortal(
        <>
          {queueOpen && (
            <div className="config-drawer-overlay" onClick={() => setQueueOpen(false)} />
          )}
          <div className={`config-drawer queue-drawer${queueOpen ? ' config-drawer--open' : ''}`}>
            <div className="config-drawer-header">
              <span className="config-drawer-title">ComfyUI Queue</span>
              <button className="config-drawer-close" onClick={() => setQueueOpen(false)} aria-label="Close">✕</button>
            </div>
            <div className="config-drawer-body queue-drawer-body">
              <ComfyQueuePage />
            </div>
          </div>
        </>,
        document.body
      )}

      <Toast toasts={toasts} dismiss={dismissToast} />
    </AppContext.Provider>
  )
}

function ClipsPage({ tagMap, isLoading }) {
  const { clipId, itemId } = useParams()
  const navigate = useNavigate()
  const initialClipId = clipId ? Number(clipId) : null
  const initialItemId = itemId ? Number(itemId) : null

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Header isLoading={isLoading} />
      <ManageClipsModal
        tagMap={tagMap}
        initialClipId={initialClipId}
        initialItemId={initialItemId}
        onClose={() => navigate('/')}
        onClipSelect={id => navigate(id == null ? '/clips' : `/clips/${id}`)}
        onItemSelect={(cId, iId) => {
          if (iId == null) navigate(cId == null ? '/clips' : `/clips/${cId}`)
          else             navigate(`/clips/${cId}/${iId}`)
        }}
      />
    </div>
  )
}
