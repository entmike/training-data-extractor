import { useState, useRef, useContext } from 'react'
import { createPortal } from 'react-dom'
import { AppContext } from '../context'
import TagDropdown from './TagDropdown'
import BlurhashCanvas from './BlurhashCanvas'
import ClipItemEditor from './ClipItemEditor'

function formatRelativeTime(ts) {
  const d = new Date(ts)
  if (isNaN(d)) return ts
  const diff = (Date.now() - d) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d ago`
  return d.toLocaleDateString()
}

export default function SceneCard({ scene: initialScene, tagMap, visible, onTagsChange, onPlay }) {
  const { openPlayer, refreshTags } = useContext(AppContext)

  const rawCaption = (initialScene.caption && !initialScene.caption.startsWith('__'))
    ? initialScene.caption : ''
  const [caption, setCaption] = useState(rawCaption)
  const [savedCaption, setSavedCaption] = useState(rawCaption)
  const [saveStatus, setSaveStatus] = useState('') // '' | 'saving' | 'saved' | 'error'
  const [tags, setTags] = useState(initialScene.tags || [])
  const [autoTags, setAutoTags] = useState(initialScene.auto_tags || [])
  const [cardTab, setCardTab] = useState('caption')
  const [rating, setRatingState] = useState(initialScene.rating || 0)
  const [dropdownPos, setDropdownPos] = useState(null)
  const saveTimer = useRef(null)
  const addBtnRef = useRef(null)

  const [imgLoaded, setImgLoaded] = useState(false)
  const isDirty = caption !== savedCaption

  // Clip badge state
  const [clipItems, setClipItems] = useState(null) // null = not fetched
  const [clipLoading, setClipLoading] = useState(false)
  const [showClipPicker, setShowClipPicker] = useState(false)
  const [editingClipItem, setEditingClipItem] = useState(null)
  const badgeRef = useRef(null)

  async function handleBadgeClick(e) {
    e.stopPropagation()
    setClipLoading(true)
    setShowClipPicker(false)
    try {
      const r = await fetch(`/api/scenes/${initialScene.id}/clip_items`)
      const d = await r.json()
      const fetched = d.items || []
      setClipItems(fetched)
      if (fetched.length === 1) {
        setEditingClipItem(fetched[0])
      } else if (fetched.length > 1) {
        setShowClipPicker(true)
      }
    } finally {
      setClipLoading(false)
    }
  }
  const imgSrc = initialScene.previewUrl
    ?? (initialScene.preview_path
      ? `/preview/${initialScene.preview_path}`
      : `/scene_preview/${initialScene.id}/card`)

  function handleCaptionChange(val) {
    setCaption(val)
    setSaveStatus('')
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => doSaveCaption(val), 1200)
  }

  const captionUrl = initialScene.captionUrl ?? `/api/caption/${initialScene.id}`

  async function doSaveCaption(val) {
    setSaveStatus('saving')
    try {
      const r = await fetch(captionUrl, {
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
    await fetch(captionUrl, {
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
    if (r.ok) { const d = await r.json(); setTags(d.tags); onTagsChange?.(initialScene.id, d.tags) }
    if (isNew) refreshTags()
    setDropdownPos(null)
  }

  async function removeTag(tag) {
    const r = await fetch(`/api/tags/${initialScene.id}/${encodeURIComponent(tag)}`, { method: 'DELETE' })
    if (r.ok) { const d = await r.json(); setTags(d.tags); onTagsChange?.(initialScene.id, d.tags) }
  }

  async function confirmAutoTag(tag) {
    const r = await fetch(`/api/tags/${initialScene.id}/${encodeURIComponent(tag)}/confirm`, { method: 'PUT' })
    if (r.ok) {
      setAutoTags(prev => prev.filter(t => t !== tag))
      setTags(prev => [...prev, tag])
      onTagsChange?.(initialScene.id, [...tags, tag])
    }
  }

  async function rejectAutoTag(tag) {
    const r = await fetch(`/api/tags/${initialScene.id}/${encodeURIComponent(tag)}`, { method: 'DELETE' })
    if (r.ok) setAutoTags(prev => prev.filter(t => t !== tag))
  }

  function openDropdown() {
    const rect = addBtnRef.current.getBoundingClientRect()
    setDropdownPos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX })
  }

  async function setRating(n) {
    const next = n === rating ? 0 : n
    setRatingState(next)
    await fetch(`/api/rating/${initialScene.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating: next || null }),
    })
  }

  function playVideo() {
    if (onPlay) { onPlay(); return }
    openPlayer({
      sceneId: initialScene.id,
      videoPath: initialScene.video_path,
      startFrame: initialScene.start_frame,
      endFrame: initialScene.end_frame,
      videoTotalFrames: initialScene.video_total_frames || 0,
      startTime: initialScene.start_time,
      endTime: initialScene.end_time,
      fps: initialScene.fps,
      frameOffset: initialScene.frame_offset,
      blurhash: initialScene.blurhash,
      videoWidth: initialScene.video_width || 0,
      videoHeight: initialScene.video_height || 0,
      caption,
      tags,
      rating,
      subtitles: initialScene.subtitles || '',
      onCaptionChange: (newCaption) => { setCaption(newCaption); setSavedCaption(newCaption) },
      onTagsChange: (newTags) => { setTags(newTags); onTagsChange?.(initialScene.id, newTags) },
      autoTags,
      onAutoTagsChange: (newAutoTags) => setAutoTags(newAutoTags),
      onRatingChange: (newRating) => setRatingState(newRating),
    })
  }

  const tagSuggestions = Object.entries(tagMap)
    .map(([tag, def]) => def)
    .filter(def => !tags.includes(def.tag))

  if (!visible) return <div className="scene-card scene-card--hidden" />

  return (
    <div className="scene-card">
      <div className="preview-container" onClick={playVideo}>
        <BlurhashCanvas hash={initialScene.blurhash} className="blurhash-bg" />
        <img
          className="scene-preview"
          src={imgSrc}
          alt={`Scene ${initialScene.id}`}
          loading="lazy"
          onLoad={() => setImgLoaded(true)}
          style={{ opacity: imgLoaded ? 1 : 0 }}
        />
        <div className="play-overlay">
          <div className="play-icon">
            <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
          </div>
        </div>
      </div>

      <div className="star-rating">
        {[1, 2, 3].map(n => (
          <button
            key={n}
            className={`star-btn${rating >= n ? ' star-btn--active' : ''}`}
            onClick={() => setRating(n)}
            title={`${n} star${n > 1 ? 's' : ''}`}
          >★</button>
        ))}
        {initialScene.mute && (
          <span className="scene-card__mute" title="Muted">
            <svg viewBox="0 0 24 24" fill="currentColor" width="11" height="11"><path d="M16.5 12A4.5 4.5 0 0014 7.97v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.8 8.8 0 0021 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06A8.99 8.99 0 0017.73 18l1.28 1.27L20 18l-16-16-1.73 1.73zm9.73.73L9.13 8.6 12 11.47V4.73z"/></svg>
          </span>
        )}
        {initialScene.denoise && (
          <span className="scene-card__denoise" title="Denoise">
            <svg viewBox="0 0 24 24" fill="currentColor" width="11" height="11"><path d="M3 9h2V5H3v4zm0 4h2v-2H3v2zm0 4h2v-2H3v2zm4 0h2v-2H7v2zm0-8h2V5H7v4zm4 12v-4h-2v4h2zm-4-4h2v-2H7v2zm8 0h2v-2h-2v2zm2-12v4h2V5h-2zm0 8h2v-2h-2v2zM3 21h2v-2H3v2zm12-4h2v-2h-2v2zm2 4h2v-2h-2v2zm-8 0h2v-2h-2v2zm-4-8h2V9H7v4zm8 4h2v-4h-2v4zm-4 4h2V5h-2v16zm4-8h2V9h-2v4z"/></svg>
          </span>
        )}
        {initialScene.clip_count > 0 && (
          <span
            ref={badgeRef}
            className={`clip-count-badge clip-count-badge--clickable${clipLoading ? ' clip-count-badge--loading' : ''}`}
            title={`In ${initialScene.clip_count} clip${initialScene.clip_count !== 1 ? 's' : ''} — click to edit`}
            onClick={handleBadgeClick}
          >
            ⊞ {initialScene.clip_count}
          </span>
        )}
        {initialScene.face_ref_count > 0 && (
          <span
            className="face-ref-badge"
            title={`${initialScene.face_ref_count} face reference${initialScene.face_ref_count !== 1 ? 's' : ''} in this scene`}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
            </svg>
          </span>
        )}
        {initialScene.max_faces > 0 && (
          <span
            className="face-count-badge"
            title={`Up to ${initialScene.max_faces} face${initialScene.max_faces !== 1 ? 's' : ''} detected in this scene`}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
            </svg>
            {initialScene.max_faces}
          </span>
        )}
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

        <div className="card-tabs">
          <button
            className={`card-tab-btn${cardTab === 'caption' ? ' card-tab-btn--active' : ''}`}
            onClick={() => setCardTab('caption')}
          >Caption</button>
          {initialScene.subtitles && (
            <button
              className={`card-tab-btn${cardTab === 'subtitles' ? ' card-tab-btn--active' : ''}`}
              onClick={() => setCardTab('subtitles')}
            >Subtitles</button>
          )}
        </div>

        {cardTab === 'caption' && (
          <div className={`caption-box${isDirty ? ' caption-box--dirty' : ''}`}>
            <textarea
              className="caption-textarea"
              value={caption}
              placeholder="Enter caption..."
              onChange={e => handleCaptionChange(e.target.value)}
              onBlur={handleBlur}
            />
            <div className="caption-footer">
              <span className="caption-length">
                {caption.length} chars
                {initialScene.caption_finished_at && (
                  <span className="caption-timestamp" title={initialScene.caption_finished_at}>
                    {' · '}{formatRelativeTime(initialScene.caption_finished_at)}
                  </span>
                )}
              </span>
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
        )}

        {cardTab === 'subtitles' && (
          <div className="subtitle-box">
            {initialScene.subtitles}
          </div>
        )}

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
      </div>

      {dropdownPos && createPortal(
        <TagDropdown
          position={dropdownPos}
          suggestions={tagSuggestions}
          onSelect={addTag}
          onClose={() => setDropdownPos(null)}
          sceneId={initialScene.id}
        />,
        document.body
      )}

      {showClipPicker && clipItems && createPortal(
        <div className="clip-picker-overlay" onClick={() => setShowClipPicker(false)}>
          <div
            className="clip-picker-popup"
            onClick={e => e.stopPropagation()}
          >
            <div className="clip-picker-title">Select clip</div>
            {clipItems.map(ci => (
              <button
                key={ci.id}
                className="clip-picker-row"
                onClick={() => { setShowClipPicker(false); setEditingClipItem(ci) }}
              >
                <span className="clip-picker-name">{ci.clip_name}</span>
                <span className="clip-picker-frames">{ci.frame_count}f</span>
              </button>
            ))}
          </div>
        </div>,
        document.body
      )}

      {editingClipItem && (
        <ClipItemEditor
          item={editingClipItem}
          clipId={editingClipItem.clip_id}
          onClose={() => setEditingClipItem(null)}
          onSaved={updated => setEditingClipItem(prev => ({ ...prev, ...updated }))}
        />
      )}
    </div>
  )
}
