import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import FrameCountStepper from './FrameCountStepper'

function fmtSecs(s) {
  s = Math.floor(s || 0)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export default function ClipItemEditor({ item, clipId, onClose, onSaved }) {
  const videoRef    = useRef(null)
  const seekWrapRef = useRef(null)
  const cropWrapRef = useRef(null)
  const timeRafRef  = useRef(null)
  const seekingRef  = useRef(false)
  const mouseDownOnOverlay = useRef(false)

  const fps            = item.fps || 24
  const frameOffset    = item.frame_offset || 0
  const sceneStart     = item.scene_start_frame || 0
  const sceneEnd       = item.scene_end_frame || 0
  const sceneFrames    = sceneEnd - sceneStart   // total frames in clip
  const sceneDur       = sceneFrames / fps        // clip duration in seconds

  // Working copies of start/end as frame offsets relative to scene start
  const [startOff, setStartOff] = useState(item.start_frame - sceneStart)
  const [endOff,   setEndOff]   = useState(item.end_frame   - sceneStart)
  // Last-persisted offsets — used for isDirty and Revert
  const [savedStart, setSavedStart] = useState(item.start_frame - sceneStart)
  const [savedEnd,   setSavedEnd]   = useState(item.end_frame   - sceneStart)

  const startOffRef = useRef(startOff)
  const endOffRef   = useRef(endOff)
  const autoSaveRef = useRef(null)

  const [playing,     setPlaying]     = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [videoDur,    setVideoDur]    = useState(sceneDur)
  const [muted,       setMuted]       = useState(false)
  const [volume,      setVolume]      = useState(1)
  const [waveformUrl] = useState(`/waveform/${item.scene_id}`)

  const frameTimer = useRef(null)
  const [savedFlash, setSavedFlash] = useState(false)
  const [itemMute, setItemMute] = useState(!!item.mute)
  const [itemDenoise, setItemDenoise] = useState(!!item.denoise)
  const [denoiseMix, setDenoiseMix] = useState(Math.round((item.denoise_mix ?? 1.0) * 100))
  const denoiseMixTimer = useRef(null)

  // Preview tab state
  const [videoTab, setVideoTab] = useState('preview') // 'original' | 'preview'
  const videoTabRef = useRef('preview')
  const previewVideoRef = useRef(null)
  const [previewStatus, setPreviewStatus] = useState('idle') // 'idle' | 'loading' | 'ready' | 'error'
  const [previewUrl, setPreviewUrl] = useState(null)

  // Caption state — auto-saves independently
  const rawCaption = (item.caption && !item.caption.startsWith('__')) ? item.caption : ''
  const [caption,      setCaption]      = useState(rawCaption)
  const [savedCaption, setSavedCaption] = useState(rawCaption)
  const [captionStatus, setCaptionStatus] = useState('') // '' | 'saving' | 'saved' | 'error'
  const captionTimer = useRef(null)
  const captionDirty = caption !== savedCaption

  // Drag state
  const dragMode       = useRef(null) // 'start' | 'end' | 'body'
  const dragStartX     = useRef(0)
  const dragStartState = useRef({ start: 0, end: 0 })
  const [isDragging, setIsDragging] = useState(false)

  // Keep refs in sync
  useEffect(() => { startOffRef.current = startOff }, [startOff])
  useEffect(() => { endOffRef.current   = endOff   }, [endOff])

  // Keyboard close
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Global mouse move/up for dragging
  useEffect(() => {
    function onMove(e) {
      if (!dragMode.current || !cropWrapRef.current) return
      const rect = cropWrapRef.current.getBoundingClientRect()
      const deltaPx = e.clientX - dragStartX.current
      const deltaFrames = Math.round((deltaPx / rect.width) * sceneFrames)
      const { start: s0, end: e0 } = dragStartState.current
      const dur = e0 - s0

      if (dragMode.current === 'start') {
        const newStart = Math.max(0, Math.min(e0 - 1, s0 + deltaFrames))
        setStartOff(newStart)
        startOffRef.current = newStart
        if (videoRef.current) { videoRef.current.currentTime = newStart / fps; setCurrentTime(newStart / fps) }
      } else if (dragMode.current === 'end') {
        const newEnd = Math.max(s0 + 1, Math.min(sceneFrames, e0 + deltaFrames))
        setEndOff(newEnd)
        endOffRef.current = newEnd
        if (videoRef.current) { videoRef.current.currentTime = newEnd / fps; setCurrentTime(newEnd / fps) }
      } else {
        // body — shift both, preserve duration
        const newStart = Math.max(0, Math.min(sceneFrames - dur, s0 + deltaFrames))
        const newEnd   = newStart + dur
        setStartOff(newStart); startOffRef.current = newStart
        setEndOff(newEnd);     endOffRef.current   = newEnd
        if (videoRef.current) { videoRef.current.currentTime = newStart / fps; setCurrentTime(newStart / fps) }
      }
    }
    function onUp() {
      if (!dragMode.current) return
      dragMode.current = null
      setIsDragging(false)
      autoSaveRef.current?.()
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',  onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup',  onUp)
    }
  }, [sceneFrames])

  // Time RAF — loops within selected range
  function startTimeRaf() {
    function tick() {
      const vid = videoRef.current
      if (vid && !seekingRef.current) {
        const endSecs = endOffRef.current / fps
        if (vid.currentTime >= endSecs) vid.currentTime = startOffRef.current / fps
        setCurrentTime(vid.currentTime)
      }
      timeRafRef.current = requestAnimationFrame(tick)
    }
    timeRafRef.current = requestAnimationFrame(tick)
  }
  function stopTimeRaf() {
    if (timeRafRef.current) { cancelAnimationFrame(timeRafRef.current); timeRafRef.current = null }
  }
  useEffect(() => () => stopTimeRaf(), [])

  function handlePlay()       { setPlaying(true);  startTimeRaf() }
  function handlePause()      { setPlaying(false); stopTimeRaf() }
  function handleLoadedMeta() {
    const vid = videoRef.current; if (!vid) return
    setVideoDur(vid.duration)
    vid.currentTime = startOffRef.current / fps
  }

  async function togglePlay() {
    const vid = videoRef.current; if (!vid) return
    if (vid.paused) vid.play()
    else vid.pause()
  }

  // Seek
  function handleSeekStart()   { seekingRef.current = true; if (videoRef.current && !videoRef.current.paused) videoRef.current.pause() }
  function handleSeekInput(e)  { const t = Number(e.target.value); setCurrentTime(t); if (videoRef.current) videoRef.current.currentTime = t }
  function handleSeekCommit(e) { seekingRef.current = false; const t = Number(e.target.value); if (videoRef.current) videoRef.current.currentTime = t; setCurrentTime(t) }

  function handleVolumeChange(e) { const v = Number(e.target.value); setVolume(v); if (videoRef.current) videoRef.current.volume = v }
  function toggleMute() { const n = !muted; setMuted(n); if (videoRef.current) videoRef.current.muted = n }

  // Range handle mousedown
  function startDrag(e, mode) {
    e.preventDefault(); e.stopPropagation()
    dragMode.current = mode
    dragStartX.current = e.clientX
    dragStartState.current = { start: startOffRef.current, end: endOffRef.current }
    setIsDragging(true)
  }

  // Caption handlers
  function handleCaptionChange(val) {
    setCaption(val); setCaptionStatus('')
    clearTimeout(captionTimer.current)
    captionTimer.current = setTimeout(() => doSaveCaption(val), 1200)
  }
  async function doSaveCaption(val) {
    setCaptionStatus('saving')
    try {
      const r = await fetch(`/api/clips/${clipId}/items/${item.id}/caption`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caption: val }),
      })
      if (!r.ok) throw new Error()
      setSavedCaption(val)
      setCaptionStatus('saved')
      onSaved({ ...item, caption: val })
      setTimeout(() => setCaptionStatus(s => s === 'saved' ? '' : s), 2000)
    } catch {
      setCaptionStatus('error')
    }
  }
  function handleCaptionBlur() {
    clearTimeout(captionTimer.current)
    if (caption !== savedCaption) doSaveCaption(caption)
  }

  // Keep autoSaveRef current so the drag effect + debounce can call it without stale closure
  autoSaveRef.current = async () => {
    const start = startOffRef.current
    const end   = endOffRef.current
    const newStart = sceneStart + start
    const newEnd   = sceneStart + end
    try {
      const r = await fetch(`/api/clips/${clipId}/items/${item.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_frame: newStart, end_frame: newEnd }),
      })
      if (!r.ok) throw new Error()
      setSavedStart(start)
      setSavedEnd(end)
      onSaved({ ...item, start_frame: newStart, end_frame: newEnd, frame_count: newEnd - newStart })
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 1800)
      if (videoTabRef.current === 'preview') loadPreview()
    } catch { /* silent */ }
  }

  function scheduleFrameSave() {
    clearTimeout(frameTimer.current)
    frameTimer.current = setTimeout(() => autoSaveRef.current?.(), 600)
  }

  async function toggleItemMute() {
    const newMute = !itemMute
    setItemMute(newMute)
    await fetch(`/api/clips/${clipId}/items/${item.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mute: newMute }),
    })
    onSaved({ ...item, mute: newMute })
    setSavedFlash(true); setTimeout(() => setSavedFlash(false), 1800)
    if (videoTabRef.current === 'preview') loadPreview()
  }

  async function toggleItemDenoise() {
    const newDenoise = !itemDenoise
    setItemDenoise(newDenoise)
    await fetch(`/api/clips/${clipId}/items/${item.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ denoise: newDenoise }),
    })
    onSaved({ ...item, denoise: newDenoise })
    setSavedFlash(true); setTimeout(() => setSavedFlash(false), 1800)
    if (videoTabRef.current === 'preview') loadPreview()
  }

  function handleDenoiseMixChange(pct) {
    setDenoiseMix(pct)
    clearTimeout(denoiseMixTimer.current)
    denoiseMixTimer.current = setTimeout(async () => {
      await fetch(`/api/clips/${clipId}/items/${item.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ denoise_mix: pct / 100 }),
      })
      onSaved({ ...item, denoise_mix: pct / 100 })
      if (videoTabRef.current === 'preview') loadPreview()
    }, 500)
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadPreview() }, [])

  async function loadPreview() {
    setPreviewUrl(null)
    setPreviewStatus('loading')
    try {
      const r = await fetch(`/api/clips/${clipId}/items/${item.id}/processed`)
      if (!r.ok) throw new Error('Failed')
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      setPreviewUrl(url)
      setPreviewStatus('ready')
    } catch {
      setPreviewStatus('error')
    }
  }

  function switchTab(tab) {
    if (tab === 'preview') {
      videoRef.current?.pause()
      setPlaying(false)
    } else {
      previewVideoRef.current?.pause()
    }
    videoTabRef.current = tab
    setVideoTab(tab)
    if (tab === 'preview') loadPreview()
  }

  const startPct = sceneFrames > 0 ? (startOff / sceneFrames) * 100 : 0
  const endPct   = sceneFrames > 0 ? (endOff   / sceneFrames) * 100 : 0
  const isDirty  = startOff !== savedStart || endOff !== savedEnd

  return createPortal(
    <div
      className="video-modal-overlay"
      onMouseDown={e => { mouseDownOnOverlay.current = e.target === e.currentTarget }}
      onClick={e => { if (mouseDownOnOverlay.current && e.target === e.currentTarget) onClose() }}
    >
      <div className="video-modal-content cie-modal">
        <div className="video-modal-header">
          <span className="video-modal-title">
            Edit clip item — {item.video_name} · scene #{item.scene_id}
          </span>
          <button className="modal-close-btn" onClick={onClose}>&times;</button>
        </div>

        {/* Video tabs */}
        <div className="cie-video-tabs">
          <button className={`cie-video-tab${videoTab === 'original' ? ' cie-video-tab--active' : ''}`} onClick={() => switchTab('original')}>Original</button>
          <button className={`cie-video-tab${videoTab === 'preview' ? ' cie-video-tab--active' : ''}`} onClick={() => switchTab('preview')}>Preview</button>
        </div>

        {/* Video */}
        <div className="modal-video-wrap" style={{ display: videoTab === 'original' ? undefined : 'none' }}>
          <video
            ref={videoRef}
            src={`/clip/${item.scene_id}`}
            loop
            muted={muted}
            onPlay={handlePlay}
            onPause={handlePause}
            onEnded={handlePause}
            onLoadedMetadata={handleLoadedMeta}
            onClick={togglePlay}
            className="modal-video"
          />
        </div>

        {/* Processed preview */}
        {videoTab === 'preview' && (
          <div className="modal-video-wrap cie-preview-wrap">
            {previewStatus === 'loading' && (
              <div className="cie-preview-loading">
                <div className="clip-loading-spinner" />
                <span className="clip-loading-label">Generating preview…</span>
              </div>
            )}
            {previewStatus === 'error' && (
              <div className="cie-preview-loading">
                <span style={{ color: '#f87171' }}>Preview failed</span>
                <button className="cie-revert-btn" style={{ marginTop: 8 }} onClick={loadPreview}>Retry</button>
              </div>
            )}
            {previewStatus === 'ready' && previewUrl && (
              <video
                ref={previewVideoRef}
                src={previewUrl}
                loop autoPlay controls
                className="modal-video"
              />
            )}
          </div>
        )}

        {/* Controls — hidden on preview tab */}
        <div className="video-controls" style={videoTab === 'preview' ? { display: 'none' } : undefined}>
          <button className="vc-btn" onClick={togglePlay} title={playing ? 'Pause' : 'Play'}>
            {playing
              ? <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>
              : <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>}
          </button>

          <span className="vc-time">{fmtSecs(currentTime)} / {fmtSecs(videoDur)}</span>

          {/* Seek bar — waveform + playback position only */}
          <div className="vc-seek-wrap" ref={seekWrapRef}>
            {waveformUrl && (
              <img src={waveformUrl} className="vc-waveform-img" alt="" aria-hidden="true"
                onError={() => {}} />
            )}
            <div className="vc-crop-dim" style={{ left: 0, width: `${startPct}%` }} />
            <div className="vc-crop-dim" style={{ left: `${endPct}%`, width: `${100 - endPct}%` }} />
            <input
              type="range"
              className="vc-seek"
              min={0} max={videoDur || 1} step={1 / fps}
              value={currentTime}
              onMouseDown={handleSeekStart}
              onTouchStart={handleSeekStart}
              onChange={handleSeekInput}
              onMouseUp={handleSeekCommit}
              onTouchEnd={handleSeekCommit}
            />
          </div>

          <button className="vc-btn" onClick={toggleMute} title={muted ? 'Unmute' : 'Mute'}>
            {muted
              ? <svg viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 12A4.5 4.5 0 0014 7.97v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.8 8.8 0 0021 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06A8.99 8.99 0 0017.73 18l1.28 1.27L20 18l-16-16-1.73 1.73zm9.73.73L9.13 8.6 12 11.47V4.73z"/></svg>
              : <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0014 7.97v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77 0-4.28-2.99-7.86-7-8.77z"/></svg>}
          </button>
          <input type="range" className="vc-volume" min={0} max={1} step={0.05}
            value={muted ? 0 : volume} onChange={handleVolumeChange} />
        </div>

        {/* Crop range handles — hidden on preview tab */}
        <div className="cie-crop-row" ref={cropWrapRef} style={videoTab === 'preview' ? { display: 'none' } : undefined}>
          {waveformUrl && (
            <img src={waveformUrl} className="vc-waveform-img" alt="" aria-hidden="true" onError={() => {}} />
          )}
          <div
            className={`cie-range-body${isDragging && dragMode.current === 'body' ? ' cie-range-body--dragging' : ''}`}
            style={{ left: `${startPct}%`, width: `${endPct - startPct}%` }}
            onMouseDown={e => startDrag(e, 'body')}
            title="Drag to shift range"
          />
          <div
            className="cie-handle cie-handle--start"
            style={{ left: `${startPct}%` }}
            onMouseDown={e => startDrag(e, 'start')}
            title="Drag to adjust start frame"
          />
          <div
            className="cie-handle cie-handle--end"
            style={{ left: `${endPct}%` }}
            onMouseDown={e => startDrag(e, 'end')}
            title="Drag to adjust end frame"
          />
        </div>

        {/* Frame info + inputs */}
        <div className="cie-frame-panel" style={videoTab === 'original' ? { display: 'none' } : undefined}>
          <div className="cie-frame-groups">
            <div className="cie-frame-group">
              <label className="cie-label">Start frame</label>
              <input
                type="number"
                className="cie-frame-input"
                value={sceneStart + startOff}
                min={sceneStart}
                max={sceneStart + endOff - 1}
                onChange={e => {
                  const abs = Math.max(sceneStart, Math.min(sceneStart + endOff - 1, parseInt(e.target.value) || sceneStart))
                  setStartOff(abs - sceneStart)
                  scheduleFrameSave()
                }}
              />
              <span className="cie-frame-hint">offset {startOff}f in scene</span>
            </div>

            <div className="cie-frame-group">
              <label className="cie-label">End frame</label>
              <input
                type="number"
                className="cie-frame-input"
                value={sceneStart + endOff}
                min={sceneStart + startOff + 1}
                max={sceneEnd}
                onChange={e => {
                  const abs = Math.max(sceneStart + startOff + 1, Math.min(sceneEnd, parseInt(e.target.value) || sceneEnd))
                  setEndOff(abs - sceneStart)
                  scheduleFrameSave()
                }}
              />
              <span className="cie-frame-hint">offset {endOff}f in scene</span>
            </div>

            <div className="cie-frame-group">
              <label className="cie-label">Frame count</label>
              <FrameCountStepper
                frameCount={endOff - startOff}
                min={1}
                max={sceneFrames - startOff}
                onChange={newCount => { setEndOff(startOff + newCount); scheduleFrameSave() }}
              />
            </div>
          </div>

          <div className="cie-save-row">
            {savedFlash && <span className="cie-save-flash">✓ Saved</span>}
            {isDirty && (
              <button className="cie-revert-btn" onClick={() => {
                clearTimeout(frameTimer.current)
                setStartOff(savedStart)
                setEndOff(savedEnd)
              }}>Revert</button>
            )}
            <label className="cie-mute-label">
              <input type="checkbox" checked={itemMute} onChange={toggleItemMute} />
              Mute
            </label>
            <label className="cie-denoise-label">
              <input type="checkbox" checked={itemDenoise} onChange={toggleItemDenoise} />
              Denoise
            </label>
            {itemDenoise && (
              <label className="cie-denoise-mix-label">
                <input
                  type="range" min={1} max={100} step={1}
                  value={denoiseMix}
                  className="cie-denoise-mix-slider"
                  onChange={e => handleDenoiseMixChange(Number(e.target.value))}
                />
                <span className="cie-denoise-mix-value">{denoiseMix}%</span>
              </label>
            )}
          </div>
        </div>

        {/* Caption */}
        <div className={`cie-caption-panel${captionDirty ? ' cie-caption-panel--dirty' : ''}`}>
          <textarea
            className="cie-caption-textarea"
            value={caption}
            placeholder="Enter caption…"
            onChange={e => handleCaptionChange(e.target.value)}
            onBlur={handleCaptionBlur}
          />
          <div className="cie-caption-footer">
            <span className="cie-caption-len">{caption.length} chars</span>
            <div className="cie-caption-actions">
              {captionStatus === 'saving' && <span className="save-status save-status--saving">Saving…</span>}
              {captionStatus === 'saved'  && <span className="save-status save-status--saved">✓ Saved</span>}
              {captionStatus === 'error'  && <span className="save-status save-status--error">Error</span>}
              {captionDirty && (
                <button className="revert-btn" onClick={() => { clearTimeout(captionTimer.current); setCaption(savedCaption); setCaptionStatus('') }}>
                  Revert
                </button>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>,
    document.body
  )
}
