import { useState, useEffect, useRef, useContext } from 'react'
import { createPortal } from 'react-dom'
import { AppContext } from '../context'
import TagDropdown from './TagDropdown'

export default function VideoPlayerModal({ player, onClose }) {
  const videoRef = useRef(null)
  const addBtnRef = useRef(null)
  const saveTimer = useRef(null)

  // Custom player refs
  const canvasRef   = useRef(null)
  const audioCtxRef = useRef(null)
  const analyserRef = useRef(null)
  const sourceRef   = useRef(null)
  const rafRef      = useRef(null)
  const timeRafRef  = useRef(null)
  const seekingRef  = useRef(false)

  const { tagMap, refreshTags } = useContext(AppContext)
  const { sceneId, videoPath, startTime, endTime, fps = 24, frameOffset = 0, startFrame } = player

  // Fetch bucket data for this scene
  const [bucketData, setBucketData] = useState(null)
  const [activeTab, setActiveTab] = useState('scene') // 'scene' | 'bucket'

  useEffect(() => {
    if (sceneId) {
      fetch(`/api/bucket/${sceneId}`)
        .then(r => r.json())
        .then(d => {
          if (d.bucket) setBucketData(d.bucket)
        })
        .catch(() => {})
    }
  }, [sceneId])

  const rawCaption = (player.caption && !player.caption.startsWith('__')) ? player.caption : ''
  const [caption, setCaption] = useState(rawCaption)
  const [savedCaption, setSavedCaption] = useState(rawCaption)
  const [saveStatus, setSaveStatus] = useState('')
  const [tags, setTags] = useState(player.tags || [])
  const [rating, setRatingState] = useState(player.rating || 0)
  const [dropdownPos, setDropdownPos] = useState(null)

  // Custom player state
  const [playing,     setPlaying]     = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [videoDur,    setVideoDur]    = useState(0)
  const [volume,      setVolume]      = useState(1)
  const [muted,       setMuted]       = useState(false)
  const [waveformUrl, setWaveformUrl] = useState(null)
  
  // Bucket video refs
  const bucketVideoRef = useRef(null)
  const [bucketPlaying, setBucketPlaying] = useState(false)
  const [bucketCurrentTime, setBucketCurrentTime] = useState(0)
  const [bucketDur, setBucketDur] = useState(0)
  const [bucketWaveformUrl, setBucketWaveformUrl] = useState(null)
  const bucketRafRef = useRef(null)
  const bucketTimeRafRef = useRef(null)
  const bucketSeekingRef = useRef(false)
  const bucketAudioInitialized = useRef(false)

  const isDirty = caption !== savedCaption
  const duration = endTime - startTime
  const title = `${videoPath?.split('/').pop()?.replace(/\.[^.]+$/, '') ?? ''} — ${formatTime(startTime)} (${duration.toFixed(1)}s)`
  
  // Bucket duration
  const bucketDuration = bucketData?.optimal_duration || 0
  const bucketStartTime = bucketData ? (startTime + bucketData.optimal_offset_frames / fps) : 0

  // Load waveform for this scene
  useEffect(() => {
    setWaveformUrl(`/waveform/${sceneId}`)
    if (bucketData) {
      setBucketWaveformUrl(`/bucket_waveform/${sceneId}`)
    }
  }, [sceneId, bucketData])

  // Reset bucket video state when switching tabs
  useEffect(() => {
    console.log('Tab changed to:', activeTab, 'bucketVideoRef:', bucketVideoRef.current ? 'mounted' : 'null')
    if (activeTab === 'bucket' && bucketVideoRef.current) {
      bucketVideoRef.current.load()
    }
  }, [activeTab])

  // Keyboard handler
  useEffect(() => {
    function handleKey(e) {
      if (e.key === 'Escape' && !dropdownPos) onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose, dropdownPos])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopTimeRaf()
      stopBucketTimeRaf()
      stopVuMeter()
      if (audioCtxRef.current) {
        audioCtxRef.current.close()
        audioCtxRef.current = null
      }
    }
  }, [])

  // ── Web Audio ──────────────────────────────────────────

  function ensureAudioContext(videoElement = videoRef.current) {
    if (audioCtxRef.current) return
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    analyser.smoothingTimeConstant = 0.7
    const source = ctx.createMediaElementSource(videoElement)
    source.connect(analyser)
    analyser.connect(ctx.destination)
    audioCtxRef.current = ctx
    analyserRef.current = analyser
    sourceRef.current   = source
  }

  function startVuMeter() {
    const analyser = analyserRef.current
    const canvas   = canvasRef.current
    if (!analyser || !canvas) return
    const ctx  = canvas.getContext('2d')
    const data = new Uint8Array(analyser.frequencyBinCount)

    function draw() {
      rafRef.current = requestAnimationFrame(draw)
      analyser.getByteFrequencyData(data)
      const avg   = data.slice(0, 32).reduce((s, v) => s + v, 0) / 32
      const level = avg / 255
      const W = canvas.width
      const H = canvas.height
      ctx.clearRect(0, 0, W, H)
      const bars = 12
      const gap  = 2
      const barW = (W - gap * (bars - 1)) / bars
      const lit  = Math.round(level * bars)
      for (let i = 0; i < bars; i++) {
        ctx.fillStyle = i < lit ? '#58a6ff' : '#30363d'
        ctx.fillRect(i * (barW + gap), 0, barW, H)
      }
    }
    draw()
  }

  function stopVuMeter() {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    const canvas = canvasRef.current
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
  }

  // ── Time tracking rAF (60fps, independent of audio) ───

  function startTimeRaf() {
    function tick() {
      if (!seekingRef.current && videoRef.current)
        setCurrentTime(videoRef.current.currentTime)
      timeRafRef.current = requestAnimationFrame(tick)
    }
    timeRafRef.current = requestAnimationFrame(tick)
  }

  function stopTimeRaf() {
    if (timeRafRef.current) { cancelAnimationFrame(timeRafRef.current); timeRafRef.current = null }
  }

  // ── Bucket video time tracking rAF ───

  function startBucketTimeRaf() {
    function tick() {
      if (!bucketSeekingRef.current && bucketVideoRef.current)
        setBucketCurrentTime(bucketVideoRef.current.currentTime)
      bucketTimeRafRef.current = requestAnimationFrame(tick)
    }
    bucketTimeRafRef.current = requestAnimationFrame(tick)
  }

  function stopBucketTimeRaf() {
    if (bucketTimeRafRef.current) { cancelAnimationFrame(bucketTimeRafRef.current); bucketTimeRafRef.current = null }
  }

  // ── Video event handlers ───────────────────────────────

  function handlePlay() { setPlaying(true); startTimeRaf(); startVuMeter() }
  function handlePause()      { setPlaying(false); stopTimeRaf() }
  function handleEnded()      { setPlaying(false); stopTimeRaf() }
  function handleLoadedMeta() { setVideoDur(videoRef.current.duration) }

  async function togglePlay() {
    const vid = videoRef.current
    if (!vid) return
    if (vid.paused) {
      ensureAudioContext()
      if (audioCtxRef.current.state === 'suspended') await audioCtxRef.current.resume()
      vid.play()
    } else {
      vid.pause()
    }
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

  // ── Bucket Seek ──────────────────────────────────────────────

  function handleBucketSeekStart() {
    bucketSeekingRef.current = true
    if (bucketVideoRef.current && !bucketVideoRef.current.paused) bucketVideoRef.current.pause()
  }
  function handleBucketSeekInput(e) {
    const t = Number(e.target.value)
    setBucketCurrentTime(t)
    if (bucketVideoRef.current) bucketVideoRef.current.currentTime = t
  }
  function handleBucketSeekCommit(e) {
    bucketSeekingRef.current = false
    const t = Number(e.target.value)
    if (bucketVideoRef.current) bucketVideoRef.current.currentTime = t
    setBucketCurrentTime(t)
  }

  // ── Bucket event handlers ────────────────────────────────────

  function handleBucketPlay() { setBucketPlaying(true); startBucketTimeRaf() }
  function handleBucketPause()      { setBucketPlaying(false); stopBucketTimeRaf() }
  function handleBucketEnded()      { setBucketPlaying(false); stopBucketTimeRaf() }
  function handleBucketLoadedMeta() {
    const vid = bucketVideoRef.current
    if (vid) {
      setBucketDur(vid.duration)
      vid.play().catch(() => {}) // Auto-play on metadata load
    }
  }

  async function toggleBucketPlay() {
    const vid = bucketVideoRef.current
    if (!vid) return
    if (vid.paused) {
      ensureAudioContext(vid)
      if (audioCtxRef.current?.state === 'suspended') await audioCtxRef.current.resume()
      vid.play()
    } else {
      vid.pause()
    }
  }

  // ── Volume ─────────────────────────────────────────────

  function handleVolumeChange(e) {
    const v = Number(e.target.value)
    setVolume(v)
    if (videoRef.current) videoRef.current.volume = v
  }

  function toggleMute() {
    const next = !muted
    setMuted(next)
    if (videoRef.current) videoRef.current.muted = next
  }

  // ── Caption / tag handlers (unchanged) ────────────────

  function handleCaptionChange(val) {
    setCaption(val)
    setSaveStatus('')
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => doSaveCaption(val), 1200)
  }

  async function doSaveCaption(val) {
    setSaveStatus('saving')
    try {
      const r = await fetch(`/api/caption/${sceneId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caption: val }),
      })
      if (!r.ok) throw new Error()
      setSavedCaption(val)
      setSaveStatus('saved')
      player.onCaptionChange?.(val)
      setTimeout(() => setSaveStatus(s => s === 'saved' ? '' : s), 2000)
    } catch {
      setSaveStatus('error')
    }
  }

  function handleBlur() {
    clearTimeout(saveTimer.current)
    if (caption !== savedCaption) doSaveCaption(caption)
  }

  async function deleteCaption() {
    await fetch(`/api/caption/${sceneId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ caption: '' }),
    })
    setCaption('')
    setSavedCaption('')
    setSaveStatus('')
    player.onCaptionChange?.('')
  }

  async function addTag(tag) {
    const isNew = !tagMap[tag]
    const r = await fetch(`/api/tags/${sceneId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
    const next = n === rating ? 0 : n
    setRatingState(next)
    player.onRatingChange?.(next)
    await fetch(`/api/rating/${sceneId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating: next || null }),
    })
  }

  function openDropdown() {
    const rect = addBtnRef.current.getBoundingClientRect()
    setDropdownPos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX })
  }

  const tagSuggestions = Object.values(tagMap).filter(def => !tags.includes(def.tag))

  return (
    <div className="video-modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="video-modal-content">
        <div className="video-modal-header">
          <span className="video-modal-title">{title}</span>
          <button className="modal-close-btn" onClick={onClose}>&times;</button>
        </div>

        {/* Tabs */}
        <div className="video-tabs">
          <button
            className={`video-tab${activeTab === 'scene' ? ' video-tab--active' : ''}`}
            onClick={() => setActiveTab('scene')}
          >
            Full Scene ({duration.toFixed(1)}s)
          </button>
          {bucketData && (
            <button
              className={`video-tab${activeTab === 'bucket' ? ' video-tab--active' : ''}`}
              onClick={() => { console.log('Bucket tab clicked'); setActiveTab('bucket') }}
            >
              Optimal Bucket ({bucketDuration.toFixed(1)}s / {Math.round(bucketDuration * fps)}f)
            </button>
          )}
        </div>

        {/* Scene Video */}
        {activeTab === 'scene' && (
          <>
            <div className="modal-video-wrap">
              <video
                ref={videoRef}
                src={`/clip/${sceneId}`}
                autoPlay
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

            {/* Scene controls */}
            <div className="video-controls">
              {/* Play/Pause */}
              <button className="vc-btn" onClick={togglePlay} title={playing ? 'Pause' : 'Play'}>
                {playing
                  ? <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>
                  : <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                }
              </button>

              {/* Time */}
              <span className="vc-time">{fmtSecs(currentTime)} / {fmtSecs(videoDur)}</span>

              {/* Seek bar with waveform background */}
              <div className="vc-seek-wrap">
                {waveformUrl && (
                  <img src={waveformUrl} className="vc-waveform-img" alt="" aria-hidden="true"
                    onError={() => setWaveformUrl(null)} />
                )}
                <input
                  type="range"
                  className="vc-seek"
                  min={0}
                  max={videoDur || 1}
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
                type="range"
                className="vc-volume"
                min={0}
                max={1}
                step={0.05}
                value={muted ? 0 : volume}
                onChange={handleVolumeChange}
              />
            </div>

            {/* Frame info */}
            {(() => {
              const clipFrame = Math.round(currentTime * fps)
              const totalFrames = Math.round(videoDur * fps)
              const sceneStart = startFrame != null ? startFrame : Math.round(startTime * fps) - frameOffset - 1
              const absFrame = sceneStart + frameOffset + 1 + clipFrame
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

        {/* Bucket Video */}
        {activeTab === 'bucket' && bucketData && (
          <>
            <div className="modal-video-wrap">
              {console.log('Rendering bucket video, src:', `/bucket_clip/${sceneId}`)}
              <video
                ref={bucketVideoRef}
                src={`/bucket_clip/${sceneId}`}
                autoPlay
                loop
                muted={muted}
                onPlay={handleBucketPlay}
                onPause={handleBucketPause}
                onEnded={handleBucketEnded}
                onLoadedMetadata={handleBucketLoadedMeta}
                onError={(e) => {
                  console.error('Bucket video error:', e.currentTarget.error)
                  const vid = e.currentTarget
                  console.error('Video src:', vid.src)
                  console.error('Video error code:', vid.error?.code)
                  console.error('Video error message:', vid.error?.message)
                }}
                onClick={toggleBucketPlay}
                className="modal-video"
              />
            </div>

            {/* Bucket controls */}
            <div className="video-controls">
              {/* Play/Pause */}
              <button className="vc-btn" onClick={toggleBucketPlay} title={bucketPlaying ? 'Pause' : 'Play'}>
                {bucketPlaying
                  ? <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>
                  : <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                }
              </button>

               {/* Time */}
               <span className="vc-time">{fmtSecs(bucketCurrentTime)} / {fmtSecs(bucketDur)} ({Math.round(bucketCurrentTime * fps)}/{Math.round(bucketDur * fps)}f)</span>

              {/* Seek bar with waveform background */}
              <div className="vc-seek-wrap">
                {bucketWaveformUrl && (
                  <img src={bucketWaveformUrl} className="vc-waveform-img" alt="" aria-hidden="true"
                    onError={() => setBucketWaveformUrl(null)} />
                )}
                <input
                  type="range"
                  className="vc-seek"
                  min={0}
                  max={bucketDur || 1}
                  step={0.033}
                  value={bucketCurrentTime}
                  onMouseDown={handleBucketSeekStart}
                  onTouchStart={handleBucketSeekStart}
                  onChange={handleBucketSeekInput}
                  onMouseUp={handleBucketSeekCommit}
                  onTouchEnd={handleBucketSeekCommit}
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
                type="range"
                className="vc-volume"
                min={0}
                max={1}
                step={0.05}
                value={muted ? 0 : volume}
                onChange={handleVolumeChange}
              />
            </div>

            {/* Bucket frame info */}
            {(() => {
              const bucketFrame = Math.round(bucketCurrentTime * fps)
              const bucketTotalFrames = Math.round(bucketDur * fps)
              const bucketStartFrame = bucketData.start_frame
              const absFrame = bucketStartFrame + bucketFrame
              return (
                <div className="vc-frame-info">
                  bucket frame <strong>{bucketFrame}</strong> / {bucketTotalFrames}
                  &nbsp;&nbsp;·&nbsp;&nbsp;
                  source frame <strong>{absFrame}</strong>
                  {bucketData.speech_start_frame && (
                    <>
                      <br />
                      speech: frames {bucketData.speech_start_frame} - {bucketData.speech_end_frame}
                    </>
                  )}
                </div>
              )
            })()}
          </>
        )}

        <div className="video-modal-meta">
          <div className="star-rating">
            {[1, 2, 3].map(n => (
              <button
                key={n}
                className={`star-btn${rating >= n ? ' star-btn--active' : ''}`}
                onClick={() => setRating(n)}
                title={`${n} star${n > 1 ? 's' : ''}`}
              >★</button>
            ))}
          </div>

          <div className="tag-section">
            {tags.map(tag => (
              <span key={tag} className="tag-pill">
                {tagMap[tag]?.display_name || tag}
                <button className="tag-remove" onClick={() => removeTag(tag)}>✕</button>
              </span>
            ))}
            <button className="tag-add-btn" ref={addBtnRef} onClick={openDropdown}>+ Tag</button>
          </div>

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
                {caption && (
                  <button className="delete-caption-btn" onClick={deleteCaption}>Delete</button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {dropdownPos && createPortal(
        <TagDropdown
          position={dropdownPos}
          suggestions={tagSuggestions}
          onSelect={addTag}
          onClose={() => setDropdownPos(null)}
        />,
        document.body
      )}
    </div>
  )
}

function formatTime(secs) {
  const s = Math.floor(secs)
  return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

function fmtSecs(s) {
  s = Math.floor(s || 0)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
