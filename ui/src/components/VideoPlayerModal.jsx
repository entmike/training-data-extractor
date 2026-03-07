import { useState, useEffect, useRef, useContext } from 'react'
import { createPortal } from 'react-dom'
import { AppContext } from '../context'
import TagDropdown from './TagDropdown'

export default function VideoPlayerModal({ player, onClose }) {
  const videoRef = useRef(null)
  const addBtnRef = useRef(null)
  const saveTimer = useRef(null)
  const { tagMap, refreshTags } = useContext(AppContext)
  const { sceneId, videoPath, startTime, endTime } = player

  const rawCaption = (player.caption && !player.caption.startsWith('__')) ? player.caption : ''
  const [caption, setCaption] = useState(rawCaption)
  const [savedCaption, setSavedCaption] = useState(rawCaption)
  const [saveStatus, setSaveStatus] = useState('')
  const [tags, setTags] = useState(player.tags || [])
  const [dropdownPos, setDropdownPos] = useState(null)

  const isDirty = caption !== savedCaption
  const duration = endTime - startTime
  const title = `${videoPath?.split('/').pop()?.replace(/\.[^.]+$/, '') ?? ''} — ${formatTime(startTime)} (${duration.toFixed(1)}s)`

  useEffect(() => {
    function handleKey(e) {
      if (e.key === 'Escape' && !dropdownPos) onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose, dropdownPos])

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
  }

  async function addTag(tag) {
    const isNew = !tagMap[tag]
    const r = await fetch(`/api/tags/${sceneId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tag }),
    })
    if (r.ok) { const d = await r.json(); setTags(d.tags) }
    if (isNew) refreshTags()
    setDropdownPos(null)
  }

  async function removeTag(tag) {
    const r = await fetch(`/api/tags/${sceneId}/${encodeURIComponent(tag)}`, { method: 'DELETE' })
    if (r.ok) { const d = await r.json(); setTags(d.tags) }
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
        <video
          ref={videoRef}
          src={`/clip/${sceneId}`}
          controls
          autoPlay
          loop
        />

        <div className="video-modal-meta">
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
