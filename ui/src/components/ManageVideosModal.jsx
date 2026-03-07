import { useState, useEffect } from 'react'

export default function ManageVideosModal({ onClose }) {
  const [videos, setVideos] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/videos')
      .then(r => r.json())
      .then(d => { setVideos(d.videos || []); setLoading(false) })
  }, [])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {videos.map(v => <VideoRow key={v.id} video={v} />)}
          </div>
        )}
      </div>
    </div>
  )
}

function VideoRow({ video }) {
  const [prompt, setPrompt] = useState(video.prompt || '')
  const [saved, setSaved] = useState(video.prompt || '')
  const [status, setStatus] = useState('')

  const isDirty = prompt !== saved
  const pct = video.scene_count > 0 ? Math.round((video.captioned / video.scene_count) * 100) : 0
  const name = video.name?.replace(/\.[^.]+$/, '') ?? video.name
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
      setSaved(prompt)
      setStatus('✓ Saved')
      setTimeout(() => setStatus(''), 3000)
    } catch {
      setStatus('Error')
    }
  }

  return (
    <div className="video-row">
      <div className="video-row-header">
        <div>
          <div className="video-row-name">{name}</div>
          <div className="video-row-meta">{meta}</div>
        </div>
        <span className="video-row-stats">
          {video.captioned}/{video.scene_count} scenes ({pct}%)
        </span>
      </div>

      <div className="video-prompt-label">Captioning prompt</div>
      <textarea
        className="video-prompt-textarea"
        value={prompt}
        placeholder="Optional per-video system prompt for the captioner…"
        onChange={e => setPrompt(e.target.value)}
      />
      <div className="video-prompt-footer">
        <span className="video-prompt-status">{status}</span>
        <button className="save-btn" disabled={!isDirty} onClick={savePrompt}>Save</button>
      </div>
    </div>
  )
}
