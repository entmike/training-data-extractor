import { useState, useEffect, useCallback } from 'react'
import { AppContext } from './context'
import Header from './components/Header'
import SceneGrid from './components/SceneGrid'
import VideoPlayerModal from './components/VideoPlayerModal'
import ManageTagsModal from './components/ManageTagsModal'
import ManageVideosModal from './components/ManageVideosModal'
import ManageCollectionsModal from './components/ManageCollectionsModal'

function getUrlParam(key, fallback = '') {
  return new URLSearchParams(window.location.search).get(key) ?? fallback
}

export default function App() {
  const [videoFilter, setVideoFilter] = useState(() => getUrlParam('video', ''))
  const [stats, setStats] = useState(null)
  const [allTags, setAllTags] = useState([])
  const [allVideos, setAllVideos] = useState([])
  const [activeIncludeTags, setActiveIncludeTags] = useState(new Set())
  const [activeExcludeTags, setActiveExcludeTags] = useState(new Set())
  const [includeMode, setIncludeMode] = useState('and') // 'and' | 'or'
  const [minFrames, setMinFrames] = useState(0)
  const [ratingFilter, setRatingFilter] = useState(new Set())
  const [sort, setSort] = useState('') // empty = any; values: 1|2|3|'unranked'
  const [viewMode, setViewMode] = useState('card') // 'card' | 'thumb'
  const [isLoading, setIsLoading] = useState(false)
  const [player, setPlayer] = useState(null)
  const [showManageTags, setShowManageTags] = useState(false)
  const [showManageVideos, setShowManageVideos] = useState(false)
  const [showManageCollections, setShowManageCollections] = useState(false)

  const tagMap = Object.fromEntries(allTags.map(t => [t.tag, t]))

  // Sync URL params
  useEffect(() => {
    const url = new URL(window.location)
    videoFilter
      ? url.searchParams.set('video', videoFilter)
      : url.searchParams.delete('video')
    window.history.replaceState({}, '', url)
  }, [videoFilter])

  const fetchStats = useCallback(async () => {
    const r = await fetch('/api/stats')
    if (r.ok) setStats(await r.json())
  }, [])

  const fetchTags = useCallback(async () => {
    const url = videoFilter
      ? `/api/tags/all?video=${encodeURIComponent(videoFilter)}`
      : '/api/tags/all'
    const r = await fetch(url)
    if (r.ok) {
      const d = await r.json()
      setAllTags(d.tags || [])
    }
  }, [videoFilter])

  const fetchVideos = useCallback(async () => {
    const r = await fetch('/api/videos')
    if (r.ok) {
      const d = await r.json()
      setAllVideos(d.videos || [])
    }
  }, [])

  useEffect(() => {
    fetchStats()
    fetchTags()
    fetchVideos()
  }, [fetchStats, fetchTags, fetchVideos])

  const openPlayer = useCallback(p => setPlayer(p), [])
  const closePlayer = useCallback(() => setPlayer(null), [])

  return (
    <AppContext.Provider value={{ tagMap, openPlayer, refreshTags: fetchTags }}>
      <Header
        stats={stats}
        videoFilter={videoFilter} setVideoFilter={setVideoFilter}
        allVideos={allVideos}
        allTags={allTags}
        activeIncludeTags={activeIncludeTags} setActiveIncludeTags={setActiveIncludeTags}
        activeExcludeTags={activeExcludeTags} setActiveExcludeTags={setActiveExcludeTags}
        includeMode={includeMode} setIncludeMode={setIncludeMode}
        minFrames={minFrames} setMinFrames={setMinFrames}
        ratingFilter={ratingFilter} setRatingFilter={setRatingFilter}
        isLoading={isLoading}
        onManageTags={() => setShowManageTags(true)}
        onManageVideos={() => setShowManageVideos(true)}
        sort={sort} setSort={setSort}
        viewMode={viewMode} setViewMode={setViewMode}
        onManageCollections={() => setShowManageCollections(true)}
      />
      <main className="container">
        <SceneGrid
          videoFilter={videoFilter}
          activeIncludeTags={activeIncludeTags}
          activeExcludeTags={activeExcludeTags}
          includeMode={includeMode}
          minFrames={minFrames}
          ratingFilter={ratingFilter}
          sort={sort}
          viewMode={viewMode}
          tagMap={tagMap}
          onLoadingChange={setIsLoading}
        />
      </main>

      {player && <VideoPlayerModal player={player} onClose={closePlayer} />}
      {showManageTags && (
        <ManageTagsModal onClose={() => { setShowManageTags(false); fetchTags() }} />
      )}
      {showManageVideos && (
        <ManageVideosModal allVideos={allVideos} onClose={() => setShowManageVideos(false)} />
      )}
      {showManageCollections && (
        <ManageCollectionsModal
          tagMap={tagMap}
          onClose={() => setShowManageCollections(false)}
        />
      )}
    </AppContext.Provider>
  )
}
