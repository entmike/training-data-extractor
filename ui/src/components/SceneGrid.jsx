import { useState, useEffect, useRef, useCallback } from 'react'
import SceneCardGrid from './SceneCardGrid'
import SceneCardSkeleton from './SceneCardSkeleton'
import ViewToggle from './ViewToggle'

const BATCH_SIZE = 200

export default function SceneGrid({ videoFilter, activeIncludeTags, activeExcludeTags, includeMode, minFrames, ratingFilter, tagMap, onLoadingChange, totalCount, unconfirmedTag }) {
  const [scenes, setScenes] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [isEmpty, setIsEmpty] = useState(false)
  const [sort, setSort] = useState('')
  const [viewMode, setViewMode] = useState('card')
  const sentinelRef = useRef(null)
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const pageRef = useRef(1)
  const fetchGenRef = useRef(0)
  const sentinelVisibleRef = useRef(false)

  // filterKey drives scene-list reset: any server-side filter param change resets the list
  const filterKey = [
    videoFilter,
    [...activeIncludeTags].sort().join(','),
    [...activeExcludeTags].sort().join(','),
    activeIncludeTags.size > 1 ? includeMode : '',
    minFrames,
    [...ratingFilter].map(String).sort().join(','),
    sort,
    unconfirmedTag || '',
  ].join('|')

  useEffect(() => {
    fetchGenRef.current += 1
    setScenes([])
    hasMoreRef.current = true
    setIsEmpty(false)
    pageRef.current = 1
    loadingRef.current = false
  }, [filterKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // Reload when a scene is split via the modal
  useEffect(() => {
    function onSceneSplit() {
      fetchGenRef.current += 1
      setScenes([])
      hasMoreRef.current = true
      setIsEmpty(false)
      pageRef.current = 1
      loadingRef.current = false
    }
    window.addEventListener('scene-split', onSceneSplit)
    return () => window.removeEventListener('scene-split', onSceneSplit)
  }, [])

  // Callback so SceneCard can report tag changes back (keeps card state in sync; no longer
  // used for filtering since filtering is server-side, but still needed for SceneCard display)
  const handleTagsChange = useCallback((id, tags) => {
    setScenes(prev => prev.map(s => s.id === id ? { ...s, tags } : s))
  }, [])

  const loadNext = useCallback(async () => {
    if (loadingRef.current || !hasMoreRef.current) return
    loadingRef.current = true
    const gen = fetchGenRef.current
    setIsLoading(true)
    onLoadingChange?.(true)
    try {
      const params = new URLSearchParams({ page: pageRef.current, limit: BATCH_SIZE })
      if (videoFilter) params.set('video', videoFilter)
      if (activeIncludeTags.size > 0) params.set('include_tags', [...activeIncludeTags].join(','))
      if (activeExcludeTags.size > 0) params.set('exclude_tags', [...activeExcludeTags].join(','))
      if (activeIncludeTags.size > 1) params.set('include_mode', includeMode)
      if (minFrames > 0) params.set('min_frames', minFrames)
      if (ratingFilter.size > 0) params.set('rating', [...ratingFilter].join(','))
      if (sort) params.set('sort', sort)
      if (unconfirmedTag) params.set('unconfirmed_tag', unconfirmedTag)
      const r = await fetch('/api/scenes?' + params)
      if (!r.ok) throw new Error('fetch failed')
      const data = await r.json()
      if (fetchGenRef.current !== gen) return
      if (data.scenes.length === 0 && pageRef.current === 1) setIsEmpty(true)
      hasMoreRef.current = data.has_more
      pageRef.current += 1

      // Append in chunks of 50 across animation frames to avoid a large
      // synchronous render that blocks the main thread.
      const CHUNK = 50
      const chunks = []
      for (let i = 0; i < data.scenes.length; i += CHUNK) chunks.push(data.scenes.slice(i, i + CHUNK))
      for (let ci = 0; ci < chunks.length; ci++) {
        if (fetchGenRef.current !== gen) break
        if (ci > 0) await new Promise(r => requestAnimationFrame(r))
        if (fetchGenRef.current !== gen) break
        setScenes(prev => [...prev, ...chunks[ci]])
      }
    } catch (e) {
      console.error('Failed to load scenes', e)
    } finally {
      if (fetchGenRef.current === gen) {
        loadingRef.current = false
        setIsLoading(false)
        onLoadingChange?.(false)
        // Re-trigger if sentinel is still in view — the observer won't re-fire
        // because intersection state didn't change during chunked rendering.
        if (sentinelVisibleRef.current && hasMoreRef.current) loadNext()
      }
    }
  }, [videoFilter, activeIncludeTags, activeExcludeTags, includeMode, minFrames, ratingFilter, sort, unconfirmedTag])

  // Explicitly trigger initial load when loadNext changes (filter params changed).
  // The IntersectionObserver alone is unreliable here: if the sentinel is already
  // at the bottom (old scenes still in DOM when the new observer is created), the
  // observer fires with isIntersecting:false and may not re-fire once scenes reset.
  useEffect(() => {
    loadNext()
  }, [loadNext]) // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll-based trigger for infinite scroll — more reliable than
  // IntersectionObserver with rootMargin on a non-viewport scroll container.
  useEffect(() => {
    const container = sentinelRef.current?.closest('.videos-scenes-panel')
    if (!container) return
    function onScroll() {
      const { scrollTop, scrollHeight, clientHeight } = container
      sentinelVisibleRef.current = scrollHeight - scrollTop - clientHeight < 1200
      if (sentinelVisibleRef.current) loadNext()
    }
    container.addEventListener('scroll', onScroll, { passive: true })
    // Run once immediately in case content already fills less than one page
    onScroll()
    return () => container.removeEventListener('scroll', onScroll)
  }, [loadNext])

  const isInitialLoad = isLoading && scenes.length === 0
  const skeletonCount = viewMode === 'thumb' ? 24 : 6

  return (
    <div className="scene-grid-wrap">
      <div className="scene-grid-toolbar">
        <ViewToggle value={viewMode} onChange={setViewMode} />
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
        {totalCount != null && <span className="toolbar-count">{totalCount.toLocaleString()} scenes</span>}
      </div>
      {isEmpty && (
        <div className="empty-state">
          <h2>No scenes found</h2>
        </div>
      )}
      <SceneCardGrid
        scenes={scenes}
        tagMap={tagMap}
        viewMode={viewMode}
        onTagsChange={handleTagsChange}
      />
      {isLoading && (
        <div className={isInitialLoad ? undefined : 'skeleton-pagination-wrap'}>
          <div className={viewMode === 'thumb' ? 'scenes-thumbgrid' : 'scenes-grid'}>
            {Array.from({ length: isInitialLoad ? skeletonCount : (viewMode === 'thumb' ? 8 : 2) }).map((_, i) => (
              <SceneCardSkeleton key={i} viewMode={viewMode} />
            ))}
          </div>
        </div>
      )}
      <div ref={sentinelRef} style={{ height: 1 }} />
    </div>
  )
}
