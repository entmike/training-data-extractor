import { useState, useEffect, useRef, useContext, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { AppContext } from '../context'
import TagDropdown from './TagDropdown'
import FrameCountStepper from './FrameCountStepper'
import { blurhashToDataURL } from './BlurhashCanvas'

export default function VideoPlayerModal({ player, onClose }) {
  const videoRef      = useRef(null)
  const canvasRef     = useRef(null)
  const audioCtxRef   = useRef(null)
  const analyserRef   = useRef(null)
  const rafRef        = useRef(null)
  const timeRafRef    = useRef(null)
  const seekingRef    = useRef(false)
  const addBtnRef     = useRef(null)
  const saveTimer     = useRef(null)
  const mouseDownOnOverlay = useRef(false)
  const [copied, setCopied] = useState(false)

  const { tagMap, refreshTags } = useContext(AppContext)
  const { sceneId, videoPath, startTime, endTime, fps = 24, frameOffset = 0, startFrame, endFrame: initialEndFrame, videoTotalFrames = 0, blurhash, videoWidth = 0, videoHeight = 0 } = player
  const blurhashDataUrl = useMemo(() => blurhashToDataURL(blurhash), [blurhash])

  const duration = endTime - startTime
  const title = `${videoPath?.split('/').pop()?.replace(/\.[^.]+$/, '') ?? ''} — ${formatTime(startTime)} (${duration.toFixed(1)}s)`

  // ── Clip picker state ────────────────────────────
  const [collPickerPos,   setCollPickerPos]   = useState(null) // null | { top, left }
  const [clips,     setClips]     = useState(null) // null = not fetched yet
  const [collAddStatus,   setCollAddStatus]   = useState({})   // { [clipId]: 'adding'|'done'|'error' }
  const [newCollName,     setNewCollName]     = useState('')
  const [creatingColl,    setCreatingColl]    = useState(false)
  const collBtnRef = useRef(null)

  // ── Bucket state ───────────────────────────────────────
  const [bucketData,              setBucketData]              = useState(null)
  const [bucketOffset,            setBucketOffset]            = useState(0)   // seconds into scene
  const [savedBucketOffsetFrames, setSavedBucketOffsetFrames] = useState(0)
  const [savingBucketOffset,      setSavingBucketOffset]      = useState(false)
  const [playEntireScene,         setPlayEntireScene]         = useState(false)
  const [originalBucketOffsetFrames, setOriginalBucketOffsetFrames] = useState(0)
  const bucketOffsetRef               = useRef(0)
  const bucketDurationRef             = useRef(0)
  const playEntireSceneRef            = useRef(false)
  const savedBucketOffsetFramesRef    = useRef(0)
  const originalBucketOffsetFramesRef = useRef(0)
  const bucketInitializedRef          = useRef(false)

  // Seek-bar drag refs for green overlay
  const seekWrapRef             = useRef(null)
  const isDraggingBucketWindow  = useRef(false)
  const dragStartX              = useRef(0)
  const dragStartOffset         = useRef(0)
  const dragStartDuration       = useRef(0)
  const dragMode                = useRef('body') // 'body' | 'start' | 'end'
  const [isDraggingBucket, setIsDraggingBucket] = useState(false)

  // ── Player state ───────────────────────────────────────
  const [playing,     setPlaying]     = useState(false)
  const [currentTime, setCurrentTime] = useState(0)   // always scene-relative
  const [videoDur,    setVideoDur]    = useState(0)
  const [volume,      setVolume]      = useState(1)
  const [muted,       setMuted]       = useState(false)
  const [waveformUrl, setWaveformUrl] = useState(null)
  const [clipLoading, setClipLoading] = useState(true)

  // ── Split state ────────────────────────────────────────
  const [splitting,    setSplitting]    = useState(false)
  const [splitResult,  setSplitResult]  = useState(null)  // { count } on success

  // ── Scene boundary state ───────────────────────────────
  const [localStartFrame, setLocalStartFrame] = useState(startFrame ?? 0)
  const [localEndFrame,   setLocalEndFrame]   = useState(initialEndFrame ?? 0)
  const [adjustingBound,  setAdjustingBound]  = useState(false)
  const [boundaryError,   setBoundaryError]   = useState('')

  // ── Face-ref state ─────────────────────────────────────
  const [refPickerPos,  setRefPickerPos]  = useState(null) // null | { top, left }
  const [refSaveStatus, setRefSaveStatus] = useState({})   // { [tag]: 'saving'|'done'|'error' }
  const refBtnRef = useRef(null)

  // ── CLIP-ref state ─────────────────────────────────────
  const [clipRefPickerPos,  setClipRefPickerPos]  = useState(null) // null | { top, left }
  const [clipRefSaveStatus, setClipRefSaveStatus] = useState({})   // { [tag]: 'saving'|'done'|'error' }
  const clipRefBtnRef = useRef(null)

  // ── Caption / tag state ────────────────────────────────
  const rawCaption = (player.caption && !player.caption.startsWith('__')) ? player.caption : ''
  const [caption,      setCaption]      = useState(rawCaption)
  const [savedCaption, setSavedCaption] = useState(rawCaption)
  const [saveStatus,   setSaveStatus]   = useState('')
  const [tags,         setTags]         = useState(player.tags || [])
  const [autoTags,     setAutoTags]     = useState(player.autoTags || [])
  const [rating,       setRatingState]  = useState(player.rating || 0)
  const [dropdownPos,  setDropdownPos]  = useState(null)
  const [modalTab,     setModalTab]     = useState('caption')
  const subtitles = player.subtitles || ''
  const isDirty = caption !== savedCaption

  const bucketDuration   = bucketData?.optimal_duration || 0
  const bucketFrameCount = bucketData?.frame_count || 0
  const sceneFrameCount  = bucketData?.scene_frame_count || Math.round(duration * fps)

  // ── Load bucket + waveform ─────────────────────────────
  useEffect(() => {
    if (sceneId) {
      fetch(`/api/bucket/${sceneId}`)
        .then(r => r.json())
        .then(d => { if (d.bucket) setBucketData(d.bucket) })
        .catch(() => {})
    }
    setWaveformUrl(`/waveform/${sceneId}`)
  }, [sceneId])

  // Sync bucket offset refs whenever bucketData changes (skip during drag — drag manages its own state)
  useEffect(() => {
    if (bucketData && !isDraggingBucketWindow.current) {
      const offset = bucketData.optimal_offset_frames / fps
      setBucketOffset(offset)
      setSavedBucketOffsetFrames(bucketData.optimal_offset_frames)
      savedBucketOffsetFramesRef.current = bucketData.optimal_offset_frames
      bucketOffsetRef.current = offset
      bucketDurationRef.current = bucketData.optimal_duration || 0
      playEntireSceneRef.current = false
      setPlayEntireScene(false)
      // Capture original offset only on first load
      if (!bucketInitializedRef.current) {
        bucketInitializedRef.current = true
        setOriginalBucketOffsetFrames(bucketData.optimal_offset_frames)
        originalBucketOffsetFramesRef.current = bucketData.optimal_offset_frames
      }
    }
  }, [bucketData, fps])

  // ── Keyboard ───────────────────────────────────────────
  useEffect(() => {
    function handleKey(e) { if (e.key === 'Escape' && !dropdownPos) onClose() }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose, dropdownPos])

  // ── Cleanup ────────────────────────────────────────────
  useEffect(() => {
    return () => {
      stopTimeRaf(); stopVuMeter()
      if (audioCtxRef.current) { audioCtxRef.current.close(); audioCtxRef.current = null }
    }
  }, [])

  // ── Green overlay drag ─────────────────────────────────
  useEffect(() => {
    function onMove(e) {
      if (!isDraggingBucketWindow.current || !seekWrapRef.current) return
      const rect  = seekWrapRef.current.getBoundingClientRect()
      const delta = ((e.clientX - dragStartX.current) / rect.width) * duration
      const s0    = dragStartOffset.current
      const d0    = dragStartDuration.current
      const minDur = 24 / fps

      if (dragMode.current === 'start') {
        // move start, keep end fixed → shrink/grow from left
        const fixedEnd = s0 + d0
        const newOff   = Math.max(0, Math.min(fixedEnd - minDur, s0 + delta))
        const newDur   = fixedEnd - newOff
        setBucketOffset(newOff); bucketOffsetRef.current = newOff
        bucketDurationRef.current = newDur
        setBucketData(prev => prev ? { ...prev, optimal_duration: newDur, frame_count: Math.round(newDur * fps) } : prev)
        if (videoRef.current && !playEntireSceneRef.current) {
          videoRef.current.currentTime = newOff; setCurrentTime(newOff)
        }
      } else if (dragMode.current === 'end') {
        // move end, keep start fixed → shrink/grow from right
        const newEnd = Math.max(s0 + minDur, Math.min(duration, s0 + d0 + delta))
        const newDur = newEnd - s0
        bucketDurationRef.current = newDur
        setBucketData(prev => prev ? { ...prev, optimal_duration: newDur, frame_count: Math.round(newDur * fps) } : prev)
        if (videoRef.current && !playEntireSceneRef.current) {
          videoRef.current.currentTime = newEnd; setCurrentTime(newEnd)
        }
      } else {
        // body — shift window, keep duration
        const maxOff = duration - d0
        const newOff = Math.max(0, Math.min(maxOff, s0 + delta))
        setBucketOffset(newOff); bucketOffsetRef.current = newOff
        if (videoRef.current && !playEntireSceneRef.current) {
          videoRef.current.currentTime = newOff; setCurrentTime(newOff)
        }
      }
    }
    function onUp() {
      if (!isDraggingBucketWindow.current) return
      isDraggingBucketWindow.current = false
      setIsDraggingBucket(false)
      // Auto-save offset + frame_count
      const newFrames   = Math.round(bucketOffsetRef.current * fps)
      const newDurFrames = Math.round(bucketDurationRef.current * fps)
      saveBucketOffsetNow(bucketOffsetRef.current, newDurFrames)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
  }, [duration, fps])

  function startBucketDrag(e, mode) {
    e.preventDefault(); e.stopPropagation()
    isDraggingBucketWindow.current = true
    dragMode.current = mode
    setIsDraggingBucket(true)
    dragStartX.current = e.clientX
    dragStartOffset.current = bucketOffsetRef.current
    dragStartDuration.current = bucketDurationRef.current
  }

  function handleBucketWindowMouseDown(e) { startBucketDrag(e, 'body') }

  // ── Web Audio ──────────────────────────────────────────
  function ensureAudioContext() {
    if (audioCtxRef.current) return
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 256; analyser.smoothingTimeConstant = 0.7
    const source = ctx.createMediaElementSource(videoRef.current)
    source.connect(analyser); analyser.connect(ctx.destination)
    audioCtxRef.current = ctx; analyserRef.current = analyser
  }

  function startVuMeter() {
    const analyser = analyserRef.current; const canvas = canvasRef.current
    if (!analyser || !canvas) return
    const ctx = canvas.getContext('2d'); const data = new Uint8Array(analyser.frequencyBinCount)
    function draw() {
      rafRef.current = requestAnimationFrame(draw)
      analyser.getByteFrequencyData(data)
      const level = data.slice(0, 32).reduce((s, v) => s + v, 0) / 32 / 255
      const W = canvas.width; const H = canvas.height
      ctx.clearRect(0, 0, W, H)
      const bars = 12; const gap = 2; const barW = (W - gap * (bars - 1)) / bars
      const lit = Math.round(level * bars)
      for (let i = 0; i < bars; i++) {
        ctx.fillStyle = i < lit ? '#58a6ff' : '#30363d'
        ctx.fillRect(i * (barW + gap), 0, barW, H)
      }
    }
    draw()
  }

  function stopVuMeter() {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    canvasRef.current?.getContext('2d').clearRect(0, 0, canvasRef.current.width, canvasRef.current.height)
  }

  // ── Time rAF — constrains to bucket window unless playEntireScene ──
  function startTimeRaf() {
    function tick() {
      const vid = videoRef.current
      if (vid && !seekingRef.current) {
        if (!playEntireSceneRef.current && bucketDurationRef.current > 0) {
          const end = bucketOffsetRef.current + bucketDurationRef.current
          if (vid.currentTime >= end) vid.currentTime = bucketOffsetRef.current
        }
        setCurrentTime(vid.currentTime)
      }
      timeRafRef.current = requestAnimationFrame(tick)
    }
    timeRafRef.current = requestAnimationFrame(tick)
  }

  function stopTimeRaf() {
    if (timeRafRef.current) { cancelAnimationFrame(timeRafRef.current); timeRafRef.current = null }
  }

  // ── Video events ───────────────────────────────────────
  function handlePlay()        { setPlaying(true);  startTimeRaf(); startVuMeter() }
  function handlePause()       { setPlaying(false); stopTimeRaf() }
  function handleEnded()       { setPlaying(false); stopTimeRaf() }
  function handleLoadedMeta()  {
    const vid = videoRef.current; if (!vid) return
    setVideoDur(vid.duration)
    if (!playEntireSceneRef.current && bucketOffsetRef.current > 0)
      vid.currentTime = bucketOffsetRef.current
    if (Math.round(duration * fps) <= 600)
      vid.play().catch(() => {})
  }

  async function togglePlay() {
    const vid = videoRef.current; if (!vid) return
    if (vid.paused) {
      ensureAudioContext()
      if (audioCtxRef.current.state === 'suspended') await audioCtxRef.current.resume()
      vid.play()
    } else { vid.pause() }
  }

  // ── Seek ───────────────────────────────────────────────
  function handleSeekStart() {
    seekingRef.current = true
    if (videoRef.current && !videoRef.current.paused) videoRef.current.pause()
  }
  function handleSeekInput(e) {
    const t = Number(e.target.value)
    setCurrentTime(t)
    if (videoRef.current) videoRef.current.currentTime = t
  }
  function handleSeekCommit(e) {
    seekingRef.current = false
    const t = Number(e.target.value)
    if (videoRef.current) videoRef.current.currentTime = t
    setCurrentTime(t)
  }

  // ── Volume ─────────────────────────────────────────────
  function handleVolumeChange(e) {
    const v = Number(e.target.value); setVolume(v)
    if (videoRef.current) videoRef.current.volume = v
  }
  function toggleMute() {
    const next = !muted; setMuted(next)
    if (videoRef.current) videoRef.current.muted = next
  }

  // ── Play Entire Scene toggle ───────────────────────────
  function togglePlayEntireScene() {
    const next = !playEntireScene
    setPlayEntireScene(next)
    playEntireSceneRef.current = next
    if (!next && videoRef.current) {
      // Return to bucket start
      videoRef.current.currentTime = bucketOffsetRef.current
      setCurrentTime(bucketOffsetRef.current)
    }
  }

  // ── Caption handlers ───────────────────────────────────
  function handleCaptionChange(val) {
    setCaption(val); setSaveStatus('')
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => doSaveCaption(val), 1200)
  }
  async function doSaveCaption(val) {
    setSaveStatus('saving')
    try {
      const r = await fetch(`/api/caption/${sceneId}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caption: val }),
      })
      if (!r.ok) throw new Error()
      setSavedCaption(val); setSaveStatus('saved')
      player.onCaptionChange?.(val)
      setTimeout(() => setSaveStatus(s => s === 'saved' ? '' : s), 2000)
    } catch { setSaveStatus('error') }
  }
  function handleBlur() {
    clearTimeout(saveTimer.current)
    if (caption !== savedCaption) doSaveCaption(caption)
  }
  async function deleteCaption() {
    await fetch(`/api/caption/${sceneId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ caption: '' }),
    })
    setCaption(''); setSavedCaption(''); setSaveStatus('')
    player.onCaptionChange?.('')
  }

  // ── Tag handlers ───────────────────────────────────────
  async function addTag(tag) {
    const isNew = !tagMap[tag]
    const r = await fetch(`/api/tags/${sceneId}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tag }),
    })
    if (r.ok) { const d = await r.json(); setTags(d.tags); player.onTagsChange?.(d.tags) }
    if (isNew) refreshTags()
    setDropdownPos(null)
  }
  async function removeTag(tag) {
    const r = await fetch(`/api/tags/${sceneId}/${encodeURIComponent(tag)}`, { method: 'DELETE' })
    if (r.ok) { const d = await r.json(); setTags(d.tags); player.onTagsChange?.(d.tags) }
  }
  async function confirmAutoTag(tag) {
    const r = await fetch(`/api/tags/${sceneId}/${encodeURIComponent(tag)}/confirm`, { method: 'PUT' })
    if (r.ok) {
      setAutoTags(prev => prev.filter(t => t !== tag))
      setTags(prev => [...prev, tag])
      player.onAutoTagsChange?.(autoTags.filter(t => t !== tag))
      player.onTagsChange?.([...tags, tag])
    }
  }
  async function rejectAutoTag(tag) {
    const r = await fetch(`/api/tags/${sceneId}/${encodeURIComponent(tag)}`, { method: 'DELETE' })
    if (r.ok) {
      setAutoTags(prev => prev.filter(t => t !== tag))
      player.onAutoTagsChange?.(autoTags.filter(t => t !== tag))
    }
  }
  async function setRating(n) {
    const next = n === rating ? 0 : n; setRatingState(next); player.onRatingChange?.(next)
    await fetch(`/api/rating/${sceneId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating: next || null }),
    })
  }
  function openDropdown() {
    const rect = addBtnRef.current.getBoundingClientRect()
    setDropdownPos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX })
  }

  // ── Bucket actions ─────────────────────────────────────
  async function saveBucketOffsetNow(offsetSecs, frameCount) {
    setSavingBucketOffset(true)
    const offsetFrames = Math.round(offsetSecs * fps)
    const body = { offset_frames: offsetFrames }
    if (frameCount != null) body.frame_count = frameCount
    try {
      const r = await fetch(`/api/bucket/${sceneId}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Save failed')
      setBucketData(d.bucket)
      setSavedBucketOffsetFrames(offsetFrames)
      savedBucketOffsetFramesRef.current = offsetFrames
    } catch (e) { console.error('Failed to save bucket offset:', e) }
    finally { setSavingBucketOffset(false) }
  }

  async function resizeBucket(deltaFrames) {
    const newCount = Math.max(24, Math.min(sceneFrameCount, bucketFrameCount + deltaFrames))
    if (newCount === bucketFrameCount) return
    setSavingBucketOffset(true)
    try {
      const r = await fetch(`/api/bucket/${sceneId}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ offset_frames: Math.round(bucketOffsetRef.current * fps), frame_count: newCount }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Resize failed')
      setBucketData(d.bucket)
      bucketDurationRef.current = d.bucket.optimal_duration || 0
    } catch (e) { console.error('Failed to resize bucket:', e) }
    finally { setSavingBucketOffset(false) }
  }

  function resetBucketOffset() {
    const origOffset = originalBucketOffsetFramesRef.current / fps
    setBucketOffset(origOffset)
    bucketOffsetRef.current = origOffset
    if (videoRef.current && !playEntireSceneRef.current) {
      videoRef.current.currentTime = origOffset
      setCurrentTime(origOffset)
    }
    saveBucketOffsetNow(origOffset)
  }

  // ── Clip picker ──────────────────────────────────
  async function openClipPicker() {
    if (collPickerPos) { setCollPickerPos(null); return }
    if (clips === null) {
      const r = await fetch('/api/clips')
      if (r.ok) { const d = await r.json(); setClips(d.clips || []) }
      else setClips([])
    }
    const rect = collBtnRef.current.getBoundingClientRect()
    setCollPickerPos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX })
  }

  async function addToClip(clipId) {
    setCollAddStatus(s => ({ ...s, [clipId]: 'adding' }))
    try {
      const r = await fetch(`/api/clips/${clipId}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene_id: sceneId }),
      })
      const d = await r.json()
      if (!r.ok && !d.already_exists) throw new Error(d.error || 'Failed')
      setCollAddStatus(s => ({ ...s, [clipId]: 'done' }))
      setClips(cols => cols.map(c => c.id === clipId
        ? { ...c, item_count: d.already_exists ? c.item_count : (c.item_count || 0) + 1 }
        : c))
      setTimeout(() => setCollAddStatus(s => { const n = { ...s }; delete n[clipId]; return n }), 2000)
    } catch {
      setCollAddStatus(s => ({ ...s, [clipId]: 'error' }))
      setTimeout(() => setCollAddStatus(s => { const n = { ...s }; delete n[clipId]; return n }), 2000)
    }
  }

  async function createAndAddClip() {
    const name = newCollName.trim()
    if (!name) return
    setCreatingColl(true)
    try {
      const r = await fetch('/api/clips', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (!r.ok) throw new Error()
      const d = await r.json()
      const newClip = { ...d.clip, item_count: 0 }
      setClips(cols => [newClip, ...(cols || [])])
      setNewCollName('')
      addToClip(newClip.id)
    } catch {
      setCreatingColl(false)
    }
    setCreatingColl(false)
  }

  // ── Split scene ────────────────────────────────────────
  async function splitScene() {
    setSplitting(true)
    try {
      const r = await fetch(`/api/scenes/${sceneId}/split`, { method: 'POST' })
      const data = await r.json()
      if (!r.ok) throw new Error(data.error || 'Split failed')
      setSplitResult({ count: data.segment_count })
      window.dispatchEvent(new CustomEvent('scene-split'))
    } catch (err) {
      console.error(err)
    } finally {
      setSplitting(false)
    }
  }

  // ── Scene boundary adjustment ──────────────────────────
  async function adjustBoundary(field, newValue) {
    setAdjustingBound(true)
    setBoundaryError('')
    try {
      const r = await fetch(`/api/scenes/${sceneId}/boundary`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field, value: newValue }),
      })
      const d = await r.json()
      if (!r.ok) { setBoundaryError(d.error || 'Failed'); return }
      if (field === 'start_frame') setLocalStartFrame(d.scene.start_frame)
      else                          setLocalEndFrame(d.scene.end_frame)
    } catch { setBoundaryError('Request failed') }
    finally { setAdjustingBound(false) }
  }

  // ── Derived display values ─────────────────────────────
  const showBucketMode = !!bucketData && !playEntireScene
  const bucketRelTime  = showBucketMode ? Math.max(0, currentTime - bucketOffset) : 0
  const sceneStartF    = startFrame != null ? startFrame : Math.round(startTime * fps) - frameOffset - 1
  const tagSuggestions = Object.values(tagMap).filter(def => !tags.includes(def.tag))
  const offsetFramesCurrent = Math.round(bucketOffset * fps)
  const bucketOffsetDirty = bucketData && !isDraggingBucket && !savingBucketOffset && offsetFramesCurrent !== originalBucketOffsetFrames
  // Absolute source-video frame at current playback position (matches CLI --frame convention)
  const currentAbsFrame = sceneStartF + frameOffset + 1 + Math.round(currentTime * fps)

  function openRefPicker() {
    if (refPickerPos) { setRefPickerPos(null); return }
    const rect = refBtnRef.current.getBoundingClientRect()
    setRefPickerPos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX })
  }

  async function saveRef(tag) {
    setRefSaveStatus(s => ({ ...s, [tag]: 'saving' }))
    try {
      const r = await fetch('/api/tag-refs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene_id: sceneId, tag, frame: currentAbsFrame }),
      })
      const d = await r.json()
      if (!r.ok) {
        setRefSaveStatus(s => ({ ...s, [tag]: 'error' }))
      } else {
        setRefSaveStatus(s => ({ ...s, [tag]: 'done' }))
      }
      setTimeout(() => setRefSaveStatus(s => { const n = { ...s }; delete n[tag]; return n }), 2000)
    } catch {
      setRefSaveStatus(s => ({ ...s, [tag]: 'error' }))
      setTimeout(() => setRefSaveStatus(s => { const n = { ...s }; delete n[tag]; return n }), 2000)
    }
  }

  function openClipRefPicker() {
    if (clipRefPickerPos) { setClipRefPickerPos(null); return }
    const rect = clipRefBtnRef.current.getBoundingClientRect()
    setClipRefPickerPos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX })
  }

  async function saveClipRef(tag) {
    setClipRefSaveStatus(s => ({ ...s, [tag]: 'saving' }))
    try {
      const r = await fetch('/api/tag-refs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene_id: sceneId, tag, frame: currentAbsFrame, embedding_type: 'clip' }),
      })
      if (!r.ok) {
        setClipRefSaveStatus(s => ({ ...s, [tag]: 'error' }))
      } else {
        setClipRefSaveStatus(s => ({ ...s, [tag]: 'done' }))
      }
      setTimeout(() => setClipRefSaveStatus(s => { const n = { ...s }; delete n[tag]; return n }), 2000)
    } catch {
      setClipRefSaveStatus(s => ({ ...s, [tag]: 'error' }))
      setTimeout(() => setClipRefSaveStatus(s => { const n = { ...s }; delete n[tag]; return n }), 2000)
    }
  }

  // ── Permalink ──────────────────────────────────────────
  async function handleShare() {
    const url = `${window.location.origin}/scene/${sceneId}`
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      // Fallback for non-secure contexts (e.g. HTTP localhost)
      const ta = document.createElement('textarea')
      ta.value = url
      ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch { /* ignore */ }
      ta.remove()
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // ── Render ─────────────────────────────────────────────
  return (
    <div
      className="video-modal-overlay"
      onMouseDown={e => { mouseDownOnOverlay.current = e.target === e.currentTarget }}
      onClick={e => { if (mouseDownOnOverlay.current && e.target === e.currentTarget) onClose() }}
    >
      <div className="video-modal-content">
        <div className="video-modal-header">
          <span className="video-modal-title">{title}</span>
          <div className="video-modal-actions">
            <button
              className="modal-share-btn"
              onClick={handleShare}
              title={copied ? 'Copied!' : 'Copy scene permalink'}
            >
              {copied ? '✓' : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/>
                  <polyline points="16 6 12 2 8 6"/>
                  <line x1="12" y1="2" x2="12" y2="15"/>
                </svg>
              )}
            </button>
            <button className="modal-close-btn" onClick={onClose}>&times;</button>
          </div>
        </div>

        {/* Video — hidden when scene exceeds 600 frames */}
        {sceneFrameCount > 600 ? (
          <div className="scene-split-prompt">
            {splitResult ? (
              <>
                <p className="scene-split-done">
                  Split into <strong>{splitResult.count}</strong> scenes of up to 600 frames each.
                </p>
                <button className="scene-split-btn scene-split-btn--close" onClick={onClose}>Close</button>
              </>
            ) : (
              <>
                <p>
                  This scene is <strong>{sceneFrameCount} frames</strong> ({duration.toFixed(1)}s) — over the 600-frame limit.
                </p>
                <p>
                  Split into <strong>{Math.ceil(sceneFrameCount / 600)}</strong> segments of up to 600 frames each?
                </p>
                <div className="scene-split-actions">
                  <button className="scene-split-btn scene-split-btn--confirm" onClick={splitScene} disabled={splitting}>
                    {splitting ? 'Splitting…' : 'Split Scene'}
                  </button>
                  <button className="scene-split-btn scene-split-btn--cancel" onClick={onClose} disabled={splitting}>
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        ) : (
          <>
            <div className="modal-video-wrap" style={(clipLoading && videoWidth && videoHeight) ? { aspectRatio: `${videoWidth}/${videoHeight}` } : undefined}>
              <video
                ref={videoRef}
                src={`/clip/${sceneId}`}
                loop
                muted={muted}
                onPlay={handlePlay}
                onPause={handlePause}
                onEnded={handleEnded}
                onLoadedMetadata={e => { setClipLoading(false); handleLoadedMeta(e) }}
                onWaiting={() => setClipLoading(true)}
                onCanPlay={() => setClipLoading(false)}
                onClick={togglePlay}
                className="modal-video"
              />
              {clipLoading && (
                <div
                  className="clip-loading-overlay"
                  style={blurhashDataUrl ? { backgroundImage: `url(${blurhashDataUrl})`, backgroundSize: '100% 100%' } : undefined}
                >
                  <div className="clip-loading-spinner" />
                  <span className="clip-loading-label">Generating clip…</span>
                </div>
              )}
            </div>

            {/* Controls */}
            <div className="video-controls">
              {/* Play/Pause */}
              <button className="vc-btn" onClick={togglePlay} title={playing ? 'Pause' : 'Play'}>
                {playing
                  ? <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>
                  : <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                }
              </button>

              {/* Time */}
              <span className="vc-time">
                {fmtSecs(currentTime)} / {fmtSecs(videoDur)}
              </span>

              {/* Seek bar */}
              <div className="vc-seek-wrap" ref={seekWrapRef}>
                {waveformUrl && (
                  <img src={waveformUrl} className="vc-waveform-img" alt="" aria-hidden="true"
                    onError={() => setWaveformUrl(null)} />
                )}
                {/* Green bucket window — drag body to reposition, handles to resize */}
                {bucketData && duration > 0 && bucketDuration > 0 && (() => {
                  const leftPct  = (bucketOffset   / duration) * 100
                  const widthPct = (bucketDuration / duration) * 100
                  return (
                    <>
                      <div
                        className="vc-bucket-window"
                        style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                        onMouseDown={handleBucketWindowMouseDown}
                        title="Drag to reposition bucket window"
                      />
                      <div
                        className="vc-bucket-handle vc-bucket-handle--start"
                        style={{ left: `${leftPct}%` }}
                        onMouseDown={e => startBucketDrag(e, 'start')}
                        title="Drag to resize start"
                      />
                      <div
                        className="vc-bucket-handle vc-bucket-handle--end"
                        style={{ left: `${leftPct + widthPct}%` }}
                        onMouseDown={e => startBucketDrag(e, 'end')}
                        title="Drag to resize end"
                      />
                    </>
                  )
                })()}
                <input
                  type="range"
                  className="vc-seek"
                  min={0}
                  max={duration || 1}
                  step={0.033}
                  value={currentTime}
                  onMouseDown={handleSeekStart}
                  onTouchStart={handleSeekStart}
                  onChange={handleSeekInput}
                  onMouseUp={handleSeekCommit}
                  onTouchEnd={handleSeekCommit}
                />
              </div>

              {/* VU meter */}
              <canvas ref={canvasRef} className="vc-vu" width={72} height={16} />

              {/* Mute */}
              <button className="vc-btn" onClick={toggleMute} title={muted ? 'Unmute' : 'Mute'}>
                {muted
                  ? <svg viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 12A4.5 4.5 0 0014 7.97v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.8 8.8 0 0021 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06A8.99 8.99 0 0017.73 18l1.28 1.27L20 18l-16-16-1.73 1.73zm9.73.73L9.13 8.6 12 11.47V4.73z"/></svg>
                  : <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0014 7.97v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77 0-4.28-2.99-7.86-7-8.77z"/></svg>
                }
              </button>

              {/* Volume */}
              <input
                type="range" className="vc-volume" min={0} max={1} step={0.05}
                value={muted ? 0 : volume} onChange={handleVolumeChange}
              />
            </div>

            {/* Frame info */}
            {showBucketMode ? (() => {
              const bucketFrame  = Math.round(bucketRelTime * fps)
              const bucketFrames = Math.round(bucketDuration * fps)
              const absFrame     = sceneStartF + frameOffset + 1 + offsetFramesCurrent + bucketFrame
              return (
                <div className="vc-frame-info">
                  bucket frame <strong>{bucketFrame}</strong> / {bucketFrames}
                  &nbsp;&nbsp;·&nbsp;&nbsp;
                  source frame <strong>{absFrame}</strong>
                  &nbsp;&nbsp;·&nbsp;&nbsp;
                  offset <strong>{offsetFramesCurrent}f</strong>
                  {bucketData.speech_start_frame && (
                    <>&nbsp;&nbsp;·&nbsp;&nbsp;speech {bucketData.speech_start_frame}–{bucketData.speech_end_frame}</>
                  )}
                </div>
              )
            })() : (() => {
              const clipFrame   = Math.round(currentTime * fps)
              const totalFrames = Math.round(videoDur * fps)
              const absFrame    = sceneStartF + frameOffset + 1 + clipFrame
              return (
                <div className="vc-frame-info">
                  frame <strong>{clipFrame}</strong> / {totalFrames}
                  &nbsp;&nbsp;·&nbsp;&nbsp;
                  source frame <strong>{absFrame}</strong>
                </div>
              )
            })()}

          </>
        )}

        {/* Meta */}
        <div className="video-modal-meta">

          {/* Bucket action row */}
          <div className="detect-bucket-row">
            {bucketData && (
              <button
                className={`detect-bucket-btn${playEntireScene ? ' detect-bucket-btn--active' : ''}`}
                onClick={togglePlayEntireScene}
                title={playEntireScene ? 'Return to bucket' : 'Play entire scene'}
              >
                {playEntireScene ? 'Bucket' : 'Full'}
              </button>
            )}
            {bucketData && (
              <FrameCountStepper
                frameCount={bucketFrameCount}
                min={24}
                max={sceneFrameCount}
                disabled={savingBucketOffset}
                onChange={newCount => resizeBucket(newCount - bucketFrameCount)}
              />
            )}
            {bucketOffsetDirty && (
              <button className="detect-bucket-btn detect-bucket-btn--reset" onClick={resetBucketOffset}>
                Reset position
              </button>
            )}
            {bucketData && (
              <button
                ref={collBtnRef}
                className={`detect-bucket-btn detect-bucket-btn--export${collPickerPos ? ' detect-bucket-btn--active' : ''}`}
                onClick={openClipPicker}
                title="Export bucket to a clip"
              >
                + Clip
              </button>
            )}
            <button
              ref={refBtnRef}
              className={`detect-bucket-btn detect-bucket-btn--ref${refPickerPos ? ' detect-bucket-btn--active' : ''}`}
              onClick={openRefPicker}
              title={`Set frame ${currentAbsFrame} as a face reference for a tag`}
            >
              + Face ref
            </button>
            <button
              ref={clipRefBtnRef}
              className={`detect-bucket-btn detect-bucket-btn--clipref${clipRefPickerPos ? ' detect-bucket-btn--active' : ''}`}
              onClick={openClipRefPicker}
              title={`Set frame ${currentAbsFrame} as a CLIP reference for a tag`}
            >
              + CLIP ref
            </button>
          </div>

          {/* Scene boundary adjusters */}
          {localStartFrame != null && localEndFrame != null && (
            <div className="scene-boundary-row">
              <div className="scene-boundary-item">
                <span className="scene-boundary-label">Start</span>
                <button
                  className="sba-btn"
                  disabled={adjustingBound || localStartFrame <= 0}
                  onClick={() => adjustBoundary('start_frame', localStartFrame - 1)}
                  title="Decrease start frame by 1"
                >−1f</button>
                <span className="scene-boundary-value">{localStartFrame}</span>
                <button
                  className="sba-btn"
                  disabled={adjustingBound || localStartFrame >= localEndFrame - 1}
                  onClick={() => adjustBoundary('start_frame', localStartFrame + 1)}
                  title="Increase start frame by 1"
                >+1f</button>
              </div>
              <div className="scene-boundary-sep" />
              <div className="scene-boundary-item">
                <span className="scene-boundary-label">End</span>
                <button
                  className="sba-btn"
                  disabled={adjustingBound || localEndFrame <= localStartFrame + 1}
                  onClick={() => adjustBoundary('end_frame', localEndFrame - 1)}
                  title="Decrease end frame by 1"
                >−1f</button>
                <span className="scene-boundary-value">{localEndFrame}</span>
                <button
                  className="sba-btn"
                  disabled={adjustingBound || (videoTotalFrames > 0 && localEndFrame >= videoTotalFrames)}
                  onClick={() => adjustBoundary('end_frame', localEndFrame + 1)}
                  title="Increase end frame by 1"
                >+1f</button>
              </div>
              {boundaryError && <span className="scene-boundary-error">{boundaryError}</span>}
            </div>
          )}

          {/* Rating */}
          <div className="star-rating">
            {[1, 2, 3].map(n => (
              <button key={n} className={`star-btn${rating >= n ? ' star-btn--active' : ''}`}
                onClick={() => setRating(n)} title={`${n} star${n > 1 ? 's' : ''}`}>★</button>
            ))}
          </div>

          {/* Tags */}
          <div className="tag-section">
            {tags.map(tag => (
              <span key={tag} className="tag-pill">
                {tagMap[tag]?.display_name || tag}
                <button className="tag-remove" onClick={() => removeTag(tag)}>✕</button>
              </span>
            ))}
            {autoTags.map(tag => (
              <span key={tag} className="tag-pill tag-pill--auto" title="Auto-detected — click to confirm" onClick={() => confirmAutoTag(tag)}>
                {tagMap[tag]?.display_name || tag}
                <button className="tag-remove" onClick={e => { e.stopPropagation(); rejectAutoTag(tag) }} title="Reject">✕</button>
              </span>
            ))}
            <button className="tag-add-btn" ref={addBtnRef} onClick={openDropdown}>+ Tag</button>
          </div>

          {/* Caption / Subtitles tabs */}
          <div className="card-tabs">
            <button
              className={`card-tab-btn${modalTab === 'caption' ? ' card-tab-btn--active' : ''}`}
              onClick={() => setModalTab('caption')}
            >Caption</button>
            {subtitles && (
              <button
                className={`card-tab-btn${modalTab === 'subtitles' ? ' card-tab-btn--active' : ''}`}
                onClick={() => setModalTab('subtitles')}
              >Subtitles</button>
            )}
          </div>

          {modalTab === 'caption' && (
            <div className={`caption-box${isDirty ? ' caption-box--dirty' : ''}`}>
              <textarea
                className="caption-textarea"
                value={caption}
                placeholder="Enter caption..."
                onChange={e => handleCaptionChange(e.target.value)}
                onBlur={handleBlur}
              />
              <div className="caption-footer">
                <span className="caption-length">{caption.length} chars</span>
                <div className="caption-actions">
                  {saveStatus === 'saving' && <span className="save-status save-status--saving">Saving…</span>}
                  {saveStatus === 'saved'  && <span className="save-status save-status--saved">✓ Saved</span>}
                  {saveStatus === 'error'  && <span className="save-status save-status--error">Error</span>}
                  {isDirty && (
                    <button className="revert-btn" onClick={() => { clearTimeout(saveTimer.current); setCaption(savedCaption); setSaveStatus('') }}>
                      Revert
                    </button>
                  )}
                  {caption && <button className="delete-caption-btn" onClick={deleteCaption}>Delete</button>}
                </div>
              </div>
            </div>
          )}

          {modalTab === 'subtitles' && (
            <div className="subtitle-box">
              {subtitles}
            </div>
          )}
        </div>
      </div>

      {dropdownPos && createPortal(
        <TagDropdown position={dropdownPos} suggestions={tagSuggestions}
          onSelect={addTag} onClose={() => setDropdownPos(null)} />,
        document.body
      )}

      {collPickerPos && createPortal(
        <ClipPicker
          position={collPickerPos}
          clips={clips || []}
          addStatus={collAddStatus}
          newName={newCollName}
          onNewNameChange={setNewCollName}
          onAdd={addToClip}
          onCreate={createAndAddClip}
          creating={creatingColl}
          onClose={() => setCollPickerPos(null)}
        />,
        document.body
      )}

      {refPickerPos && createPortal(
        <FaceRefPicker
          position={refPickerPos}
          tags={Object.keys(tagMap)}
          saveStatus={refSaveStatus}
          onSave={saveRef}
          onClose={() => setRefPickerPos(null)}
        />,
        document.body
      )}

      {clipRefPickerPos && createPortal(
        <FaceRefPicker
          position={clipRefPickerPos}
          tags={Object.keys(tagMap)}
          saveStatus={clipRefSaveStatus}
          onSave={saveClipRef}
          onClose={() => setClipRefPickerPos(null)}
          header="Save CLIP ref as"
          variant="clipref"
        />,
        document.body
      )}
    </div>
  )
}

function ClipPicker({ position, clips, addStatus, newName, onNewNameChange, onAdd, onCreate, creating, onClose }) {
  const wrapRef = useRef(null)

  useEffect(() => {
    function onMouseDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [onClose])

  return (
    <div
      ref={wrapRef}
      className="clip-picker"
      style={{ position: 'absolute', top: position.top, left: position.left, zIndex: 2000 }}
    >
      <div className="clip-picker-header">Add to clip</div>
      {clips.length === 0 && (
        <div className="clip-picker-empty">No clips yet — create one below.</div>
      )}
      <div className="clip-picker-list">
        {clips.map(c => {
          const status = addStatus[c.id]
          return (
            <button
              key={c.id}
              className={`clip-picker-item${status === 'done' ? ' clip-picker-item--done' : status === 'error' ? ' clip-picker-item--error' : ''}`}
              onMouseDown={() => onAdd(c.id)}
              disabled={status === 'adding'}
            >
              <span className="clip-picker-item-name">{c.name}</span>
              <span className="clip-picker-item-count">{c.item_count}</span>
              {status === 'adding' && <span className="clip-picker-status">…</span>}
              {status === 'done'   && <span className="clip-picker-status clip-picker-status--done">✓</span>}
              {status === 'error'  && <span className="clip-picker-status clip-picker-status--error">!</span>}
            </button>
          )
        })}
      </div>
      <div className="clip-picker-new">
        <input
          className="clip-picker-new-input"
          placeholder="New clip…"
          value={newName}
          onChange={e => onNewNameChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') onCreate(); if (e.key === 'Escape') onClose() }}
          disabled={creating}
        />
        <button
          className="clip-picker-new-btn"
          onMouseDown={onCreate}
          disabled={creating || !newName.trim()}
        >{creating ? '…' : '+'}</button>
      </div>
    </div>
  )
}

function FaceRefPicker({ position, tags, saveStatus, onSave, onClose, header = 'Save face ref as', variant = 'ref' }) {
  const wrapRef = useRef(null)

  useEffect(() => {
    function onMouseDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [onClose])

  return (
    <div
      ref={wrapRef}
      className={`clip-picker ${variant}-picker`}
      style={{ position: 'absolute', top: position.top, left: position.left, zIndex: 2000 }}
    >
      <div className="clip-picker-header">{header}</div>
      {tags.length === 0 && (
        <div className="clip-picker-empty">No tags yet — create one on the Tags page.</div>
      )}
      <div className="clip-picker-list">
        {tags.map(tag => {
          const status = saveStatus[tag]
          return (
            <button
              key={tag}
              className={`clip-picker-item${status === 'done' ? ' clip-picker-item--done' : status === 'error' ? ' clip-picker-item--error' : ''}`}
              onMouseDown={() => onSave(tag)}
              disabled={status === 'saving'}
            >
              <span className="clip-picker-item-name">{tag}</span>
              {status === 'saving' && <span className="clip-picker-status">…</span>}
              {status === 'done'   && <span className="clip-picker-status clip-picker-status--done">✓</span>}
              {status === 'error'  && <span className="clip-picker-status clip-picker-status--error">!</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function formatTime(secs) {
  const s = Math.floor(secs)
  return `${String(Math.floor(s / 3600)).padStart(2,'0')}:${String(Math.floor((s % 3600) / 60)).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`
}
function fmtSecs(s) {
  s = Math.floor(s || 0)
  return `${String(Math.floor(s / 60)).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`
}
