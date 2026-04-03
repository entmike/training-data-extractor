import { useState, useEffect, useRef } from 'react'

export default function ManageVideosModal({ onClose }) {
  const [videos, setVideos] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState(null)
  const mouseDownOnOverlay = useRef(false)

  useEffect(() => {
    fetch('/api/videos')
      .then(r => r.json())
      .then(d => {
        const vids = d.videos || []
        setVideos(vids)
        if (vids.length > 0) setSelectedId(vids[0].id)
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const selected = videos.find(v => v.id === selectedId) ?? null

  return (
    <div className="modal-overlay" onMouseDown={e => { mouseDownOnOverlay.current = e.target === e.currentTarget }} onClick={e => { if (mouseDownOnOverlay.current && e.target === e.currentTarget) onClose() }}>
      <div className="modal-box videos-modal-box">
        <div className="modal-header">
          <h2>Videos</h2>
          <button className="modal-close-btn" onClick={onClose}>&times;</button>
        </div>

        {loading ? (
          <div className="modal-empty">Loading…</div>
        ) : videos.length === 0 ? (
          <div className="modal-empty">No videos in database</div>
        ) : (
          <>
            <select
              className="video-select video-select--modal"
              value={selectedId ?? ''}
              onChange={e => setSelectedId(Number(e.target.value))}
            >
              {videos.map(v => (
                <option key={v.id} value={v.id}>
                  {v.name?.replace(/\.[^.]+$/, '') ?? v.name}
                </option>
              ))}
            </select>

            {selected && (
              <VideoRow
                key={selected.id}
                video={selected}
                onNameSaved={name => setVideos(vs => vs.map(v => v.id === selected.id ? { ...v, name } : v))}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}

function VideoRow({ video, onNameSaved }) {
  const [videoName, setVideoName] = useState(video.name || '')
  const [prompt, setPrompt] = useState(video.prompt || '')
  const [saved, setSaved] = useState({
    videoName: video.name || '',
    prompt: video.prompt || ''
  })
  const [status, setStatus] = useState('')

  // Reset when video changes
  useEffect(() => {
    setVideoName(video.name || '')
    setPrompt(video.prompt || '')
    setSaved({
      videoName: video.name || '',
      prompt: video.prompt || ''
    })
    setStatus('')
  }, [video.id])

  const isNameDirty = videoName !== saved.videoName
  const isPromptDirty = prompt !== saved.prompt
  const isDirty = isNameDirty || isPromptDirty
  const pct = video.scene_count > 0 ? Math.round((video.captioned / video.scene_count) * 100) : 0
  const meta = [
    video.width && video.height ? `${video.width}×${video.height}` : null,
    video.fps ? `${video.fps.toFixed(2)}fps` : null,
    video.duration ? `${Math.floor(video.duration / 60)}m ${Math.floor(video.duration % 60)}s` : null,
  ].filter(Boolean).join(' · ')

  async function savePrompt() {
    setStatus('Saving…')
    try {
      const r = await fetch(`/api/prompts/${video.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      if (!r.ok) throw new Error()
      setSaved(s => ({ ...s, prompt }))
      setStatus('✓ Saved')
      setTimeout(() => setStatus(''), 3000)
    } catch {
      setStatus('Error')
    }
  }

  async function saveVideoName() {
    setStatus('Saving…')
    try {
      const r = await fetch(`/api/videos/${video.id}/name`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: videoName }),
      })
      if (!r.ok) throw new Error()
      setSaved(s => ({ ...s, videoName }))
      onNameSaved(videoName)
      setStatus('✓ Saved')
      setTimeout(() => setStatus(''), 3000)
    } catch {
      setStatus('Error')
    }
  }

  return (
    <div className="video-row">
      <div className="video-row-header">
        <div className="video-row-meta">{meta}</div>
        <span className="video-row-stats">{video.captioned}/{video.scene_count} scenes ({pct}%)</span>
      </div>

      <div className="video-prompt-label">File</div>
      <input className="video-name-input" value={video.path} readOnly />

      <div className="video-prompt-label" style={{ marginTop: '16px' }}>Video name</div>
      <input
        className="video-name-input"
        value={videoName}
        placeholder="User-friendly name for this video"
        onChange={e => setVideoName(e.target.value)}
      />
      <div className="video-prompt-footer">
        <span className="video-prompt-status">{status}</span>
        <button className="save-btn" disabled={!isNameDirty} onClick={saveVideoName}>Save</button>
      </div>

      <div className="video-prompt-label" style={{ marginTop: '20px' }}>Captioning prompt</div>
      <textarea
        className="video-prompt-textarea"
        value={prompt}
        placeholder="Optional per-video system prompt for the captioner…"
        onChange={e => setPrompt(e.target.value)}
      />
      <div className="video-prompt-footer">
        <span className="video-prompt-status">{status}</span>
        <button className="save-btn" disabled={!isPromptDirty} onClick={savePrompt}>Save</button>
      </div>
    </div>
  )
}
