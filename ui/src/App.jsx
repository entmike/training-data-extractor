import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, Navigate, useParams, useNavigate } from 'react-router-dom'
import { AppContext } from './context'
import Header from './components/Header'
import VideoPlayerModal from './components/VideoPlayerModal'
import ManageTagsModal from './components/ManageTagsModal'
import ManageClipsModal from './components/ManageClipsModal'
import VideosPage from './components/VideosPage'

export default function App() {
  const navigate = useNavigate()
  const [allTags, setAllTags] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [player, setPlayer] = useState(null)
  const [showManageTags, setShowManageTags] = useState(false)

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

  const sharedProps = {
    isLoading,
    onManageTags: () => setShowManageTags(true),
    onManageVideos: () => navigate('/videos'),
  }

  const videoLayout = child => (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Header {...sharedProps} />
      {child}
    </div>
  )

  return (
    <AppContext.Provider value={{ tagMap, openPlayer, refreshTags: fetchTags }}>
      <Routes>
        <Route path="/" element={<Navigate to="/videos" replace />} />
        <Route path="/videos" element={videoLayout(<VideosPage tagMap={tagMap} allTags={allTags} />)} />
        <Route path="/videos/:videoId" element={videoLayout(<VideosPage tagMap={tagMap} allTags={allTags} />)} />
        <Route path="/clips/:clipName" element={<ClipsPage tagMap={tagMap} headerProps={sharedProps} />} />
        <Route path="/clips" element={<ClipsPage tagMap={tagMap} headerProps={sharedProps} />} />
      </Routes>

      {player && <VideoPlayerModal player={player} onClose={closePlayer} />}
      {showManageTags && (
        <ManageTagsModal onClose={() => { setShowManageTags(false); fetchTags() }} />
      )}
    </AppContext.Provider>
  )
}

function ClipsPage({ tagMap, headerProps }) {
  const { clipName } = useParams()
  const navigate = useNavigate()
  const decodedName = clipName ? decodeURIComponent(clipName) : null

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Header {...headerProps} videoId={null} />
      <ManageClipsModal
        tagMap={tagMap}
        initialClipName={decodedName}
        onClose={() => navigate('/')}
        onClipSelect={name => navigate(`/clips/${encodeURIComponent(name)}`)}
      />
    </div>
  )
}
