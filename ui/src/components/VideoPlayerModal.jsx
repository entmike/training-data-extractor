import { useState, useEffect, useRef, useContext } from 'react'
import { createPortal } from 'react-dom'
import { AppContext } from '../context'
import TagDropdown from './TagDropdown'

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

  const { tagMap, refreshTags } = useContext(AppContext)
  const { sceneId, videoPath, startTime, endTime, fps = 24, frameOffset = 0, startFrame } = player

  const duration = endTime - startTime
  const title = `${videoPath?.split('/').pop()?.replace(/\.[^.]+$/, '') ?? ''} — ${formatTime(startTime)} (${duration.toFixed(1)}s)`

  // ── Bucket state ───────────────────────────────────────
  const [bucketData,              setBucketData]              = useState(null)
  const [bucketOffset,            setBucketOffset]            = useState(0)   // seconds into scene
  const [savedBucketOffsetFrames, setSavedBucketOffsetFrames] = useState(0)
  const [savingBucketOffset,      setSavingBucketOffset]      = useState(false)
  const [playEntireScene,         setPlayEntireScene]         = useState(false)
  const [detectingBucket,         setDetectingBucket]         = useState(false)
  const [detectBucketError,       setDetectBucketError]       = useState('')
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
  const [isDraggingBucket, setIsDraggingBucket] = useState(false)

  // ── Player state ───────────────────────────────────────
  const [playing,     setPlaying]     = useState(false)
  const [currentTime, setCurrentTime] = useState(0)   // always scene-relative
  const [videoDur,    setVideoDur]    = useState(0)
  const [volume,      setVolume]      = useState(1)
  const [muted,       setMuted]       = useState(false)
  const [waveformUrl, setWaveformUrl] = useState(null)

  // ── Caption / tag state ────────────────────────────────
  const rawCaption = (player.caption && !player.caption.startsWith('__')) ? player.caption : ''
  const [caption,      setCaption]      = useState(rawCaption)
  const [savedCaption, setSavedCaption] = useState(rawCaption)
  const [saveStatus,   setSaveStatus]   = useState('')
  const [tags,         setTags]         = useState(player.tags || [])
  const [rating,       setRatingState]  = useState(player.rating || 0)
  const [dropdownPos,  setDropdownPos]  = useState(null)
  const isDirty = caption !== savedCaption

  const bucketDuration = bucketData?.optimal_duration || 0

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

  // Sync bucket offset refs whenever bucketData changes
  useEffect(() => {
    if (bucketData) {
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
      const rect = seekWrapRef.current.getBoundingClientRect()
      const delta = ((e.clientX - dragStartX.current) / rect.width) * duration
      const maxOff = duration - bucketDurationRef.current
      const newOff = Math.max(0, Math.min(maxOff, dragStartOffset.current + delta))
      setBucketOffset(newOff)
      bucketOffsetRef.current = newOff
      if (videoRef.current && !playEntireSceneRef.current) {
        videoRef.current.currentTime = newOff
        setCurrentTime(newOff)
      }
    }
    function onUp() {
      if (!isDraggingBucketWindow.current) return
      isDraggingBucketWindow.current = false
      setIsDraggingBucket(false)
      // Auto-save if position changed
      const newFrames = Math.round(bucketOffsetRef.current * fps)
      if (newFrames !== savedBucketOffsetFramesRef.current) saveBucketOffsetNow(bucketOffsetRef.current)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
  }, [duration])

  function handleBucketWindowMouseDown(e) {
    e.preventDefault(); e.stopPropagation()
    isDraggingBucketWindow.current = true
    setIsDraggingBucket(true)
    dragStartX.current = e.clientX
    dragStartOffset.current = bucketOffsetRef.current
  }

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
  async function detectBucket() {
    setDetectingBucket(true); setDetectBucketError('')
    try {
      const r = await fetch(`/api/bucket/detect/${sceneId}`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Detection failed')
      setBucketData(d.bucket)
    } catch (e) { setDetectBucketError(e.message) }
    finally { setDetectingBucket(false) }
  }
  async function saveBucketOffsetNow(offsetSecs) {
    setSavingBucketOffset(true)
    const offsetFrames = Math.round(offsetSecs * fps)
    try {
      const r = await fetch(`/api/bucket/${sceneId}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ offset_frames: offsetFrames }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Save failed')
      setBucketData(d.bucket)
      setSavedBucketOffsetFrames(offsetFrames)
      savedBucketOffsetFramesRef.current = offsetFrames
    } catch (e) { console.error('Failed to save bucket offset:', e) }
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

  // ── Derived display values ─────────────────────────────
  const showBucketMode = !!bucketData && !playEntireScene
  const bucketRelTime  = showBucketMode ? Math.max(0, currentTime - bucketOffset) : 0
  const sceneStartF    = startFrame != null ? startFrame : Math.round(startTime * fps) - frameOffset - 1
  const tagSuggestions = Object.values(tagMap).filter(def => !tags.includes(def.tag))
  const offsetFramesCurrent = Math.round(bucketOffset * fps)
  const bucketOffsetDirty = bucketData && !isDraggingBucket && !savingBucketOffset && offsetFramesCurrent !== originalBucketOffsetFrames

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
          <button className="modal-close-btn" onClick={onClose}>&times;</button>
        </div>

        {/* Video */}
        <div className="modal-video-wrap">
          <video
            ref={videoRef}
            src={`/clip/${sceneId}`}
            loop
            muted={muted}
            onPlay={handlePlay}
            onPause={handlePause}
            onEnded={handleEnded}
            onLoadedMetadata={handleLoadedMeta}
            onClick={togglePlay}
            className="modal-video"
          />
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
            {showBucketMode
              ? `${fmtSecs(bucketRelTime)} / ${fmtSecs(bucketDuration)} (${Math.round(bucketRelTime * fps)}/${Math.round(bucketDuration * fps)}f)`
              : `${fmtSecs(currentTime)} / ${fmtSecs(videoDur)}`
            }
          </span>

          {/* Seek bar */}
          <div className="vc-seek-wrap" ref={seekWrapRef}>
            {waveformUrl && (
              <img src={waveformUrl} className="vc-waveform-img" alt="" aria-hidden="true"
                onError={() => setWaveformUrl(null)} />
            )}
            {/* Green bucket window — drag to reposition */}
            {bucketData && duration > 0 && bucketDuration > 0 && (
              <div
                className="vc-bucket-window"
                style={{
                  left:  `${(bucketOffset   / duration) * 100}%`,
                  width: `${(bucketDuration / duration) * 100}%`,
                }}
                onMouseDown={handleBucketWindowMouseDown}
                title="Drag to reposition bucket window"
              />
            )}
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

          {/* Play Entire Scene toggle (only when bucket exists) */}
          {bucketData && (
            <button
              className={`vc-btn vc-btn--text${playEntireScene ? ' vc-btn--active' : ''}`}
              onClick={togglePlayEntireScene}
              title={playEntireScene ? 'Return to bucket' : 'Play entire scene'}
            >
              {playEntireScene ? 'Bucket' : 'Full'}
            </button>
          )}

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

        {/* Meta */}
        <div className="video-modal-meta">

          {/* Bucket action row */}
          {(!bucketData || bucketOffsetDirty) && (
            <div className="detect-bucket-row">
              {!bucketData && (
                <>
                  <button className="detect-bucket-btn" onClick={detectBucket} disabled={detectingBucket}>
                    {detectingBucket ? 'Detecting…' : 'Detect bucket'}
                  </button>
                  {detectBucketError && <span className="detect-bucket-error">{detectBucketError}</span>}
                </>
              )}
              {bucketOffsetDirty && (
                <button className="detect-bucket-btn detect-bucket-btn--reset" onClick={resetBucketOffset}>
                  Reset position
                </button>
              )}
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
            <button className="tag-add-btn" ref={addBtnRef} onClick={openDropdown}>+ Tag</button>
          </div>

          {/* Caption */}
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
        </div>
      </div>

      {dropdownPos && createPortal(
        <TagDropdown position={dropdownPos} suggestions={tagSuggestions}
          onSelect={addTag} onClose={() => setDropdownPos(null)} />,
        document.body
      )}
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
