import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import SceneCard from './SceneCard'

const BATCH_SIZE = 50

export default function SceneGrid({ filter, videoFilter, activeIncludeTags, activeExcludeTags, includeMode, minFrames, ratingFilter, tagMap, onLoadingChange }) {
  const [scenes, setScenes] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [isEmpty, setIsEmpty] = useState(false)
  const sentinelRef = useRef(null)
  const loadingRef = useRef(false)
  const hasMoreRef = useRef(true)
  const pageRef = useRef(1)
  const filterKey = `${filter}|${videoFilter}`

  // Reset when filter/video changes
  useEffect(() => {
    setScenes([])
    hasMoreRef.current = true
    setIsEmpty(false)
    pageRef.current = 1
    loadingRef.current = false
  }, [filterKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadNext = useCallback(async () => {
    if (loadingRef.current || !hasMoreRef.current) return
    loadingRef.current = true
    setIsLoading(true)
    onLoadingChange?.(true)
    try {
      const params = new URLSearchParams({ filter, page: pageRef.current, limit: BATCH_SIZE })
      if (videoFilter) params.set('video', videoFilter)
      const r = await fetch('/api/scenes?' + params)
      if (!r.ok) throw new Error('fetch failed')
      const data = await r.json()
      if (data.scenes.length === 0 && pageRef.current === 1) setIsEmpty(true)
      setScenes(prev => [...prev, ...data.scenes])
      hasMoreRef.current = data.has_more
      pageRef.current += 1
    } catch (e) {
      console.error('Failed to load scenes', e)
    } finally {
      loadingRef.current = false
      setIsLoading(false)
      onLoadingChange?.(false)
    }
  }, [filter, videoFilter])

  // Observe bottom sentinel
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const obs = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting) loadNext()
    }, { rootMargin: '400px' })
    obs.observe(el)
    return () => obs.disconnect()
  }, [loadNext])

  // Client-side visibility filter
  const isVisible = useCallback((scene) => {
    const tags = new Set(scene.tags || [])
    if (activeIncludeTags.size > 0) {
      const match = includeMode === 'or'
        ? [...activeIncludeTags].some(t => tags.has(t))
        : [...activeIncludeTags].every(t => tags.has(t))
      if (!match) return false
    }
    if (activeExcludeTags.size > 0 && [...activeExcludeTags].some(t => tags.has(t))) return false
    if (minFrames > 0 && (scene.frame_count || 0) < minFrames) return false
    if (ratingFilter.size > 0) {
      const r = scene.rating || 0
      const match = (ratingFilter.has('unranked') && !r) || ratingFilter.has(r)
      if (!match) return false
    }
    return true
  }, [activeIncludeTags, activeExcludeTags, includeMode, minFrames, ratingFilter])

  const visibilityMap = useMemo(() => {
    const m = {}
    for (const s of scenes) m[s.id] = isVisible(s)
    return m
  }, [scenes, isVisible])

  return (
    <>
      {isEmpty && (
        <div className="empty-state">
          <h2>No scenes found</h2>
        </div>
      )}
      <div className="scenes-grid">
        {scenes.map(scene => (
          <SceneCard
            key={scene.id}
            scene={scene}
            tagMap={tagMap}
            visible={visibilityMap[scene.id]}
          />
        ))}
      </div>
      {isLoading && <div className="loading-indicator">Loading…</div>}
      <div ref={sentinelRef} style={{ height: 1 }} />
    </>
  )
}
