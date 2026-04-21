import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, Navigate, useParams, useNavigate } from 'react-router-dom'
import { AppContext } from './context'
import Header from './components/Header'
import VideoPlayerModal from './components/VideoPlayerModal'
import ManageClipsModal from './components/ManageClipsModal'
import VideosPage from './components/VideosPage'
import TagsPage from './components/TagsPage'
import DiscoverPage from './components/DiscoverPage'
import ClusterDetailPage from './components/ClusterDetailPage'

export default function App() {
  const navigate = useNavigate()
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

  const sharedProps = {
    isLoading,
    onManageTags: () => navigate('/tags'),
    onManageVideos: () => navigate('/videos'),
  }

  const pageLayout = child => (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Header {...sharedProps} />
      {child}
    </div>
  )

  return (
    <AppContext.Provider value={{ tagMap, openPlayer, refreshTags: fetchTags }}>
      <Routes>
        <Route path="/" element={<Navigate to="/videos" replace />} />
        <Route path="/videos" element={pageLayout(<VideosPage tagMap={tagMap} allTags={allTags} />)} />
        <Route path="/videos/:videoId" element={pageLayout(<VideosPage tagMap={tagMap} allTags={allTags} />)} />
        <Route path="/clips" element={<ClipsPage tagMap={tagMap} headerProps={sharedProps} />} />
        <Route path="/clips/:clipId" element={<ClipsPage tagMap={tagMap} headerProps={sharedProps} />} />
        <Route path="/tags" element={pageLayout(<TagsPage />)} />
        <Route path="/tags/:tag" element={pageLayout(<TagsPage />)} />
        <Route path="/discover" element={pageLayout(<DiscoverPage />)} />
        <Route path="/cluster/:clusterId" element={pageLayout(<ClusterDetailPage />)} />
      </Routes>

      {player && <VideoPlayerModal player={player} onClose={closePlayer} />}
    </AppContext.Provider>
  )
}

function ClipsPage({ tagMap, headerProps }) {
  const { clipId } = useParams()
  const navigate = useNavigate()
  const initialClipId = clipId ? Number(clipId) : null

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <Header {...headerProps} videoId={null} />
      <ManageClipsModal
        tagMap={tagMap}
        initialClipId={initialClipId}
        onClose={() => navigate('/')}
        onClipSelect={id => navigate(`/clips/${id}`)}
      />
    </div>
  )
}
