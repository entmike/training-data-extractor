import { useState, useEffect, useCallback, useRef, useContext } from 'react'
import { Routes, Route, Navigate, useParams, useNavigate } from 'react-router-dom'
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

function ScenePage() {
  const { sceneId } = useParams()
  const navigate = useNavigate()
  const { openPlayer, player } = useContext(AppContext)
  const sceneRef = useRef(null)
  const prevPlayerRef = useRef(null)
  const videoIdRef = useRef(null)

  useEffect(() => {
    if (sceneRef.current) return
    sceneRef.current = true

    fetch(`/api/scene/${sceneId}`)
      .then(r => {
        if (!r.ok) throw new Error('Scene not found')
        return r.json()
      })
      .then(data => {
        videoIdRef.current = data.video_id
        const startFrame = data.start_frame ?? Math.round(data.start_time * (data.fps || 24))
        const endFrame = data.end_frame ?? Math.round(data.end_time * (data.fps || 24))
        openPlayer({
          sceneId: data.id,
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
        })
      })
      .catch(() => {
        navigate('/videos')
      })
  }, [sceneId, navigate, openPlayer])

  // Detect when modal closes (player went from truthy → falsy) and navigate back to the scene's video
  useEffect(() => {
    const prev = prevPlayerRef.current
    prevPlayerRef.current = player
    if (prev && !player) {
      const id = videoIdRef.current
      navigate(id ? `/videos/${id}` : '/videos')
    }
  }, [player, navigate])

  return (
    <div style={{
      height: '100vh', display: 'flex', flexDirection: 'column',
      overflow: 'hidden', backgroundColor: '#0a0a0a',
    }}>
      <Header isLoading={false} />
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#888' }}>
        Loading scene…
      </div>
    </div>
  )
}

export default function App() {
  const [allTags, setAllTags] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [player, setPlayer] = useState(null)

  const tagMap = Object.fromEntries(allTags.map(t => [t.tag, t]))

  const fetchTags = useCallback(async () => {
    const r = await fetch('/api/tags/all')
    if (r.ok) { const d = await r.json(); setAllTags(d.tags || []) }
  }, [])

  useEffect(() => {
    fetchTags()
  }, [fetchTags])

  const openPlayer = useCallback(p => setPlayer(p), [])
  const closePlayer = useCallback(() => setPlayer(null), [])

  const pageLayout = child => (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Header isLoading={isLoading} />
      {child}
    </div>
  )

  return (
    <AppContext.Provider value={{ tagMap, openPlayer, closePlayer, player, refreshTags: fetchTags }}>
      <Routes>
        <Route path="/" element={<Navigate to="/videos" replace />} />
        <Route path="/scene/:sceneId" element={<ScenePage />} />
        <Route path="/videos" element={pageLayout(<VideosPage tagMap={tagMap} allTags={allTags} />)} />
        <Route path="/videos/:videoId" element={pageLayout(<VideosPage tagMap={tagMap} allTags={allTags} />)} />
        <Route path="/clips" element={<ClipsPage tagMap={tagMap} isLoading={isLoading} />} />
        <Route path="/clips/:clipId" element={<ClipsPage tagMap={tagMap} isLoading={isLoading} />} />
        <Route path="/tags" element={pageLayout(<TagsPage />)} />
        <Route path="/tags/:tag" element={pageLayout(<TagsPage />)} />
        <Route path="/discover" element={pageLayout(<DiscoverPage />)} />
        <Route path="/cluster/:clusterId" element={pageLayout(<ClusterDetailPage />)} />
        <Route path="/outputs" element={pageLayout(<OutputsPage />)} />
        <Route path="/config" element={pageLayout(<ConfigPage />)} />
      </Routes>

      {player && <VideoPlayerModal player={player} onClose={closePlayer} />}
    </AppContext.Provider>
  )
}

function ClipsPage({ tagMap, isLoading }) {
  const { clipId } = useParams()
  const navigate = useNavigate()
  const initialClipId = clipId ? Number(clipId) : null

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Header isLoading={isLoading} />
      <ManageClipsModal
        tagMap={tagMap}
        initialClipId={initialClipId}
        onClose={() => navigate('/')}
        onClipSelect={id => navigate(id == null ? '/clips' : `/clips/${id}`)}
      />
    </div>
  )
}
