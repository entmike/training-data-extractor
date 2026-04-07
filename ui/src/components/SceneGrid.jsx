import { useState, useEffect, useRef, useCallback } from 'react'
import SceneCardGrid from './SceneCardGrid'

const BATCH_SIZE = 50

export default function SceneGrid({ videoFilter, activeIncludeTags, activeExcludeTags, includeMode, minFrames, ratingFilter, sort, tagMap, viewMode, onLoadingChange }) {
  const [scenes, setScenes] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [isEmpty, setIsEmpty] = useState(false)
  const sentinelRef = useRef(null)
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const pageRef = useRef(1)
  const fetchGenRef = useRef(0)

  // filterKey drives scene-list reset: any server-side filter param change resets the list
  const filterKey = [
    videoFilter,
    [...activeIncludeTags].sort().join(','),
    [...activeExcludeTags].sort().join(','),
    activeIncludeTags.size > 1 ? includeMode : '',
    minFrames,
    [...ratingFilter].map(String).sort().join(','),
    sort,
  ].join('|')

  useEffect(() => {
    fetchGenRef.current += 1
    setScenes([])
    hasMoreRef.current = true
    setIsEmpty(false)
    pageRef.current = 1
    loadingRef.current = false
  }, [filterKey]) // eslint-disable-line react-hooks/exhaustive-deps

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
      const r = await fetch('/api/scenes?' + params)
      if (!r.ok) throw new Error('fetch failed')
      const data = await r.json()
      if (fetchGenRef.current !== gen) return
      if (data.scenes.length === 0 && pageRef.current === 1) setIsEmpty(true)
      setScenes(prev => [...prev, ...data.scenes])
      hasMoreRef.current = data.has_more
      pageRef.current += 1
    } catch (e) {
      console.error('Failed to load scenes', e)
    } finally {
      if (fetchGenRef.current === gen) {
        loadingRef.current = false
        setIsLoading(false)
        onLoadingChange?.(false)
      }
    }
  }, [videoFilter, activeIncludeTags, activeExcludeTags, includeMode, minFrames, ratingFilter, sort])

  // Explicitly trigger initial load when loadNext changes (filter params changed).
  // The IntersectionObserver alone is unreliable here: if the sentinel is already
  // at the bottom (old scenes still in DOM when the new observer is created), the
  // observer fires with isIntersecting:false and may not re-fire once scenes reset.
  useEffect(() => {
    loadNext()
  }, [loadNext]) // eslint-disable-line react-hooks/exhaustive-deps

  // Observe bottom sentinel for infinite scroll (subsequent pages)
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const obs = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting) loadNext()
    }, { rootMargin: '400px' })
    obs.observe(el)
    return () => obs.disconnect()
  }, [loadNext])

  const isInitialLoad = isLoading && scenes.length === 0
  const skeletonCount = viewMode === 'thumb' ? 24 : 6

  return (
    <>
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
              <div key={i} className={viewMode === 'thumb' ? 'coll-skeleton-thumb' : 'coll-skeleton-card'}>
                <span className="skeleton skeleton--bar coll-skeleton-img" />
                {viewMode === 'card' && (
                  <div className="coll-skeleton-lines">
                    <span className="skeleton skeleton--text" style={{ width: '55%' }} />
                    <span className="skeleton skeleton--text" style={{ width: '80%' }} />
                    <span className="skeleton skeleton--text" style={{ width: '38%' }} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      <div ref={sentinelRef} style={{ height: 1 }} />
    </>
  )
}
