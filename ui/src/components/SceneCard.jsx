import { useState, useRef, useContext } from 'react'
import { createPortal } from 'react-dom'
import { AppContext } from '../context'
import TagDropdown from './TagDropdown'

export default function SceneCard({ scene: initialScene, tagMap, visible }) {
  const { openPlayer, refreshTags } = useContext(AppContext)

  const rawCaption = (initialScene.caption && !initialScene.caption.startsWith('__'))
    ? initialScene.caption : ''
  const [caption, setCaption] = useState(rawCaption)
  const [savedCaption, setSavedCaption] = useState(rawCaption)
  const [saveStatus, setSaveStatus] = useState('') // '' | 'saving' | 'saved' | 'error'
  const [tags, setTags] = useState(initialScene.tags || [])
  const [dropdownPos, setDropdownPos] = useState(null)
  const saveTimer = useRef(null)
  const addBtnRef = useRef(null)

  const isDirty = caption !== savedCaption
  const imgSrc = initialScene.preview_path
    ? `/preview/${initialScene.preview_path}`
    : `/scene_preview/${initialScene.id}`

  function handleCaptionChange(val) {
    setCaption(val)
    setSaveStatus('')
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => doSaveCaption(val), 1200)
  }

  async function doSaveCaption(val) {
    setSaveStatus('saving')
    try {
      const r = await fetch(`/api/caption/${initialScene.id}`, {
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
    await fetch(`/api/caption/${initialScene.id}`, {
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
    const r = await fetch(`/api/tags/${initialScene.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tag }),
    })
    if (r.ok) { const d = await r.json(); setTags(d.tags) }
    if (isNew) refreshTags()
    setDropdownPos(null)
  }

  async function removeTag(tag) {
    const r = await fetch(`/api/tags/${initialScene.id}/${encodeURIComponent(tag)}`, { method: 'DELETE' })
    if (r.ok) { const d = await r.json(); setTags(d.tags) }
  }

  function openDropdown() {
    const rect = addBtnRef.current.getBoundingClientRect()
    setDropdownPos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX })
  }

  function playVideo() {
    openPlayer({
      sceneId: initialScene.id,
      videoPath: initialScene.video_path,
      startFrame: initialScene.start_frame,
      endFrame: initialScene.end_frame,
      startTime: initialScene.start_time,
      endTime: initialScene.end_time,
      fps: initialScene.fps,
      frameOffset: initialScene.frame_offset,
      caption,
      tags,
    })
  }

  const tagSuggestions = Object.entries(tagMap)
    .map(([tag, def]) => def)
    .filter(def => !tags.includes(def.tag))

  if (!visible) return <div className="scene-card scene-card--hidden" />

  return (
    <div className="scene-card">
      <div className="preview-container" onClick={playVideo}>
        <img className="scene-preview" src={imgSrc} alt={`Scene ${initialScene.id}`} loading="lazy" />
        <div className="play-overlay">
          <div className="play-icon">
            <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
          </div>
        </div>
      </div>

      <div className="scene-info">
        <div className="scene-meta">
          <div>
            <span className="scene-id">Scene #{initialScene.id}</span>
            <div className="scene-video">{initialScene.video_name}</div>
          </div>
          <span className="scene-time">
            {initialScene.start_time_hms} ({(initialScene.duration || 0).toFixed(1)}s)
          </span>
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

        <div className="tag-section">
          {tags.map(tag => (
            <span key={tag} className="tag-pill">
              {tagMap[tag]?.display_name || tag}
              <button className="tag-remove" onClick={() => removeTag(tag)}>✕</button>
            </span>
          ))}
          <button className="tag-add-btn" ref={addBtnRef} onClick={openDropdown}>+ Tag</button>
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
