import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import ClipItemEditor from './ClipItemEditor'
import SceneCardPanel from './SceneCardPanel'

/** Map a clip item to the shape SceneCard / SceneThumbnail expect */
function itemToScene(item, clipId) {
  return {
    id: item.scene_id,
    preview_path: null,
    previewUrl: `/clip_item_preview/${item.id}`,
    blurhash: item.blurhash,
    video_path: item.video_path,
    start_frame: item.start_frame,
    end_frame: item.end_frame,
    start_time: item.start_time,
    end_time: item.end_time,
    fps: item.fps,
    frame_offset: item.frame_offset,
    caption: item.caption,
    tags: item.tags || [],
    rating: item.rating,
    video_name: item.video_name,
    start_time_hms: item.start_time_hms,
    duration: item.duration,
    clip_count: 0,
    captionUrl: `/api/clips/${clipId}/items/${item.id}/caption`,
  }
}

export default function ManageClipsModal({ tagMap, onClose, initialClipName, onClipSelect }) {
  const [clips, setClips] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [items, setItems] = useState([])
  const [loadingClips, setLoadingClips] = useState(true)
  const [loadingItems, setLoadingItems] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [renamingId, setRenamingId] = useState(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [editingItem, setEditingItem] = useState(null)
  const [exportProgress, setExportProgress] = useState(null) // null | { done, total }
  const [exportError, setExportError] = useState('')
  const [clearingCaptions, setClearingCaptions] = useState(false)
  const [captionPromptDraft, setCaptionPromptDraft] = useState('')
  const [savingPrompt, setSavingPrompt] = useState(false)
  const [detailCollapsed, setDetailCollapsed] = useState(false)
  const [sort, setSort] = useState('')

  useEffect(() => {
    fetchClips()
  }, [])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape' && !editingItem) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, editingItem])

  useEffect(() => {
    if (selectedId == null) { setItems([]); return }
    setLoadingItems(true)
    const params = new URLSearchParams()
    if (sort) params.set('sort', sort)
    fetch(`/api/clips/${selectedId}/items?${params}`)
      .then(r => r.json())
      .then(d => { setItems(d.items || []); setLoadingItems(false) })
      .catch(() => setLoadingItems(false))
  }, [selectedId, sort])

  useEffect(() => {
    const col = clips.find(c => c.id === selectedId)
    setCaptionPromptDraft(col?.caption_prompt || '')
  }, [selectedId, clips])

  async function fetchClips() {
    setLoadingClips(true)
    const r = await fetch('/api/clips')
    if (r.ok) {
      const d = await r.json()
      const cols = d.clips || []
      setClips(cols)
      if (cols.length > 0 && selectedId == null && initialClipName) {
        const match = cols.find(c => c.name === initialClipName)
        if (match) setSelectedId(match.id)
      }
    }
    setLoadingClips(false)
  }

  function selectClip(col) {
    setSelectedId(col.id)
    onClipSelect?.(col.name)
  }

  async function createClip() {
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    const r = await fetch('/api/clips', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (r.ok) {
      const d = await r.json()
      setNewName('')
      await fetchClips()
      setSelectedId(d.clip.id)
    }
    setCreating(false)
  }

  async function deleteClip(id) {
    if (!confirm('Delete this clip and all its items?')) return
    await fetch(`/api/clips/${id}`, { method: 'DELETE' })
    const next = clips.filter(c => c.id !== id)
    setClips(next)
    if (selectedId === id) setSelectedId(next.length > 0 ? next[0].id : null)
  }

  async function startRename(col) {
    setRenamingId(col.id)
    setRenameDraft(col.name)
  }

  async function commitRename(id) {
    const name = renameDraft.trim()
    if (!name) { setRenamingId(null); return }
    const r = await fetch(`/api/clips/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (r.ok) {
      const d = await r.json()
      setClips(cols => cols.map(c => c.id === id ? { ...c, ...d.clip } : c))
    }
    setRenamingId(null)
  }

  async function saveCaptionPrompt() {
    if (!selectedId) return
    setSavingPrompt(true)
    const r = await fetch(`/api/clips/${selectedId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ caption_prompt: captionPromptDraft }),
    })
    if (r.ok) {
      const d = await r.json()
      setClips(cols => cols.map(c => c.id === selectedId ? { ...c, ...d.clip } : c))
    }
    setSavingPrompt(false)
  }

  async function removeItem(itemId) {
    await fetch(`/api/clips/${selectedId}/items/${itemId}`, { method: 'DELETE' })
    setItems(prev => prev.filter(i => i.id !== itemId))
    setClips(cols => cols.map(c => c.id === selectedId ? { ...c, item_count: c.item_count - 1 } : c))
  }

  function handleItemSaved(updated) {
    setItems(prev => prev.map(i => i.id === updated.id ? { ...i, ...updated } : i))
  }

  async function clearCaptions() {
    const captionedCount = items.filter(i => i.caption && !i.caption.startsWith('__')).length
    if (!confirm(`Clear captions for all ${items.length} items in "${selectedCol?.name}"?\n\n${captionedCount} item${captionedCount !== 1 ? 's' : ''} currently have captions. This cannot be undone.`)) return
    setClearingCaptions(true)
    await Promise.all(items.map(item =>
      fetch(`/api/clips/${selectedId}/items/${item.id}/caption`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caption: '' }),
      })
    ))
    setItems(prev => prev.map(i => ({ ...i, caption: '' })))
    setClearingCaptions(false)
  }

  function exportClip() {
    setExportError('')
    setExportProgress({ done: 0, total: items.length })
    const es = new EventSource(`/api/clips/${selectedId}/export/stream`)
    es.onmessage = e => {
      const msg = JSON.parse(e.data)
      if (msg.error) {
        es.close()
        setExportProgress(null)
        setExportError(msg.error)
      } else if (msg.token) {
        es.close()
        setExportProgress(null)
        const a = document.createElement('a')
        a.href = `/api/clips/export/download/${msg.token}`
        a.download = `${selectedCol.name}.zip`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
      } else if (msg.done != null) {
        setExportProgress({ done: msg.done, total: msg.total })
      }
    }
    es.onerror = () => {
      es.close()
      setExportProgress(null)
      setExportError('Export failed')
    }
  }

  const selectedCol = clips.find(c => c.id === selectedId)

  return (
    <>
    <div className="clips-page">
        <div className="clips-layout">
          {/* Left sidebar: clip list */}
          <div className="clips-sidebar">
            <div className="clips-list">
              {loadingClips ? (
                [1,2,3].map(n => (
                  <div key={n} className="clip-item clip-item--skeleton">
                    <span className="skeleton skeleton--text" style={{ width: `${50 + n * 15}%` }} />
                    <span className="skeleton skeleton--text" style={{ width: 20 }} />
                  </div>
                ))
              ) : clips.length === 0 ? (
                <div className="clips-empty">No clips yet</div>
              ) : clips.map(col => (
                <div
                  key={col.id}
                  className={`clip-item${col.id === selectedId ? ' clip-item--active' : ''}`}
                  onClick={() => selectClip(col)}
                >
                  {renamingId === col.id ? (
                    <input
                      className="clip-rename-input"
                      value={renameDraft}
                      autoFocus
                      onChange={e => setRenameDraft(e.target.value)}
                      onBlur={() => commitRename(col.id)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') commitRename(col.id)
                        if (e.key === 'Escape') setRenamingId(null)
                      }}
                      onClick={e => e.stopPropagation()}
                    />
                  ) : (
                    <span className="clip-name">{col.name}</span>
                  )}
                  <span className="clip-count">{col.item_count}</span>
                  <div className="clip-actions">
                    <button
                      className="clip-action-btn"
                      title="Rename"
                      onClick={e => { e.stopPropagation(); startRename(col) }}
                    >✎</button>
                    <button
                      className="clip-action-btn clip-action-btn--danger"
                      title="Delete"
                      onClick={e => { e.stopPropagation(); deleteClip(col.id) }}
                    >✕</button>
                  </div>
                </div>
              ))}
            </div>

            {/* New clip form */}
            <div className="new-clip-form">
              <input
                className="new-clip-input"
                placeholder="New clip name…"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createClip()}
                disabled={creating}
              />
              <button
                className="new-clip-btn"
                onClick={createClip}
                disabled={creating || !newName.trim()}
              >
                {creating ? '…' : '+'}
              </button>
            </div>
          </div>

          {/* Right: items */}
          <div className="clips-items-panel">
            {selectedCol ? (
              <>
                <div className="clips-items-header detail-panel-header" onClick={() => setDetailCollapsed(c => !c)}>
                  <span className="collapse-toggle-btn">{detailCollapsed ? '▸' : '▾'}</span>
                  <strong className="detail-panel-title">{selectedCol.name}</strong>
                </div>
                {!detailCollapsed && <div className="clip-prompt-section">
                  <label className="clip-prompt-label">
                    Caption prompt override
                    <span className="clip-prompt-hint"> — overrides video prompt; leave blank to use video default</span>
                  </label>
                  <textarea
                    className="clip-prompt-textarea"
                    value={captionPromptDraft}
                    onChange={e => setCaptionPromptDraft(e.target.value)}
                    placeholder="Leave blank to use the video's prompt (or system default if none set)"
                    rows={3}
                  />
                  {captionPromptDraft !== (selectedCol?.caption_prompt || '') && (
                    <button
                      className="clip-prompt-save-btn"
                      onClick={saveCaptionPrompt}
                      disabled={savingPrompt}
                    >
                      {savingPrompt ? '…' : 'Save'}
                    </button>
                  )}
                </div>}
                <SceneCardPanel
                  scenes={items.map(item => itemToScene(item, selectedId))}
                  tagMap={tagMap}
                  loading={loadingItems}
                  emptyMessage="No items in this clip."
                  sort={sort}
                  onSortChange={setSort}
                  actions={<>
                    <span className="toolbar-count">{items.length} items</span>
                    <div className="header-spacer" />
                    {exportError && <span className="clip-export-error">{exportError}</span>}
                    <button
                      className="clip-clear-captions-btn"
                      onClick={clearCaptions}
                      disabled={clearingCaptions || items.length === 0}
                      title="Clear captions for all scenes in this clip"
                    >{clearingCaptions ? 'Clearing…' : 'Clear captions'}</button>
                    <button
                      className="clip-export-btn"
                      onClick={exportClip}
                      disabled={exportProgress != null || items.length === 0}
                      title="Extract clips + captions and download as zip"
                    >Export zip</button>
                  </>}
                  onPlay={scene => setEditingItem(items.find(i => i.scene_id === scene.id) ?? null)}
                  renderOverlay={scene => {
                    const item = items.find(i => i.scene_id === scene.id)
                    return (
                      <div className="clip-item-overlays">
                        <button
                          className="clip-item-remove-btn"
                          title="Remove from clip"
                          onClick={() => item && removeItem(item.id)}
                        >✕</button>
                      </div>
                    )
                  }}
                />
              </>
            ) : (
              <div className="clips-empty">Select a clip to view its items.</div>
            )}
          </div>
        </div>
    </div>

    {editingItem && (
      <ClipItemEditor
        item={editingItem}
        clipId={selectedId}
        onClose={() => setEditingItem(null)}
        onSaved={updated => { handleItemSaved(updated); setEditingItem(prev => ({ ...prev, ...updated })) }}
      />
    )}
    {exportProgress != null && createPortal(
      <ExportProgressModal
        done={exportProgress.done}
        total={exportProgress.total}
        clipName={selectedCol?.name}
      />,
      document.body
    )}
    </>
  )
}

function ExportProgressModal({ done, total, clipName }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div className="export-progress-overlay">
      <div className="export-progress-box">
        <div className="export-progress-title">Exporting "{clipName}"</div>
        <div className="export-progress-count">{done} / {total} clips</div>
        <div className="export-progress-bar-wrap">
          <div className="export-progress-bar" style={{ width: `${pct}%` }} />
        </div>
        <div className="export-progress-pct">{pct}%</div>
      </div>
    </div>
  )
}
