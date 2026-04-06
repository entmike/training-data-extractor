import { useState, useEffect, useRef } from 'react'
import CollectionItemEditor from './CollectionItemEditor'

function formatFrame(frame, fps) {
  const secs = frame / fps
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = Math.floor(secs % 60)
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function ManageCollectionsModal({ onClose }) {
  const [collections, setCollections] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [items, setItems] = useState([])
  const [loadingItems, setLoadingItems] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [renamingId, setRenamingId] = useState(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [editingItem, setEditingItem] = useState(null)
  const [exporting,   setExporting]   = useState(false)
  const [exportError, setExportError] = useState('')
  const mouseDownOnOverlay = useRef(false)

  useEffect(() => {
    fetchCollections()
  }, [])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    if (selectedId == null) { setItems([]); return }
    setLoadingItems(true)
    fetch(`/api/collections/${selectedId}/items`)
      .then(r => r.json())
      .then(d => { setItems(d.items || []); setLoadingItems(false) })
      .catch(() => setLoadingItems(false))
  }, [selectedId])

  async function fetchCollections() {
    const r = await fetch('/api/collections')
    if (r.ok) {
      const d = await r.json()
      const cols = d.collections || []
      setCollections(cols)
      if (cols.length > 0 && selectedId == null) setSelectedId(cols[0].id)
    }
  }

  async function createCollection() {
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    const r = await fetch('/api/collections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (r.ok) {
      const d = await r.json()
      setNewName('')
      await fetchCollections()
      setSelectedId(d.collection.id)
    }
    setCreating(false)
  }

  async function deleteCollection(id) {
    if (!confirm('Delete this collection and all its items?')) return
    await fetch(`/api/collections/${id}`, { method: 'DELETE' })
    const next = collections.filter(c => c.id !== id)
    setCollections(next)
    if (selectedId === id) setSelectedId(next.length > 0 ? next[0].id : null)
  }

  async function startRename(col) {
    setRenamingId(col.id)
    setRenameDraft(col.name)
  }

  async function commitRename(id) {
    const name = renameDraft.trim()
    if (!name) { setRenamingId(null); return }
    await fetch(`/api/collections/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    setCollections(cols => cols.map(c => c.id === id ? { ...c, name } : c))
    setRenamingId(null)
  }

  async function removeItem(itemId) {
    await fetch(`/api/collections/${selectedId}/items/${itemId}`, { method: 'DELETE' })
    setItems(prev => prev.filter(i => i.id !== itemId))
    setCollections(cols => cols.map(c => c.id === selectedId ? { ...c, item_count: c.item_count - 1 } : c))
  }

  function handleItemSaved(updated) {
    setItems(prev => prev.map(i => i.id === updated.id ? { ...i, ...updated } : i))
  }

  async function exportCollection() {
    setExporting(true); setExportError('')
    try {
      const r = await fetch(`/api/collections/${selectedId}/export`, { method: 'POST' })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.error || 'Export failed')
      }
      const blob = await r.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `${selectedCol.name}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      setExportError(e.message)
    }
    setExporting(false)
  }

  const selectedCol = collections.find(c => c.id === selectedId)

  return (
    <>
    <div
      className="modal-overlay"
      onMouseDown={e => { mouseDownOnOverlay.current = e.target === e.currentTarget }}
      onClick={e => { if (mouseDownOnOverlay.current && e.target === e.currentTarget) onClose() }}
    >
      <div className="modal-box collections-modal-box">
        <div className="modal-header">
          <h2 className="modal-title">Collections</h2>
          <button className="modal-close-btn" onClick={onClose}>&times;</button>
        </div>

        <div className="collections-layout">
          {/* Left sidebar: collection list */}
          <div className="collections-sidebar">
            <div className="collections-list">
              {collections.map(col => (
                <div
                  key={col.id}
                  className={`collection-item${col.id === selectedId ? ' collection-item--active' : ''}`}
                  onClick={() => setSelectedId(col.id)}
                >
                  {renamingId === col.id ? (
                    <input
                      className="collection-rename-input"
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
                    <span className="collection-name">{col.name}</span>
                  )}
                  <span className="collection-count">{col.item_count}</span>
                  <div className="collection-actions">
                    <button
                      className="collection-action-btn"
                      title="Rename"
                      onClick={e => { e.stopPropagation(); startRename(col) }}
                    >✎</button>
                    <button
                      className="collection-action-btn collection-action-btn--danger"
                      title="Delete"
                      onClick={e => { e.stopPropagation(); deleteCollection(col.id) }}
                    >✕</button>
                  </div>
                </div>
              ))}
              {collections.length === 0 && (
                <div className="collections-empty">No collections yet</div>
              )}
            </div>

            {/* New collection form */}
            <div className="new-collection-form">
              <input
                className="new-collection-input"
                placeholder="New collection name…"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createCollection()}
                disabled={creating}
              />
              <button
                className="new-collection-btn"
                onClick={createCollection}
                disabled={creating || !newName.trim()}
              >
                {creating ? '…' : '+'}
              </button>
            </div>
          </div>

          {/* Right: items */}
          <div className="collections-items-panel">
            {selectedCol ? (
              <>
                <div className="collections-items-header">
                  <strong>{selectedCol.name}</strong>
                  <span className="collection-count">{items.length} items</span>
                  <div className="header-spacer" />
                  {exportError && <span className="collection-export-error">{exportError}</span>}
                  <button
                    className="collection-export-btn"
                    onClick={exportCollection}
                    disabled={exporting || items.length === 0}
                    title="Extract clips + captions and download as zip"
                  >
                    {exporting ? 'Exporting…' : 'Export zip'}
                  </button>
                </div>
                {loadingItems ? (
                  <div className="collections-loading">Loading…</div>
                ) : items.length === 0 ? (
                  <div className="collections-empty">No items in this collection.</div>
                ) : (() => {
                  // Group by frame_count, sorted ascending
                  const groups = []
                  const seen = new Map()
                  for (const item of items) {
                    const fc = item.frame_count
                    if (!seen.has(fc)) { seen.set(fc, []); groups.push(fc) }
                    seen.get(fc).push(item)
                  }
                  groups.sort((a, b) => a - b)
                  return (
                    <div className="collections-items-list">
                      {groups.map(fc => (
                        <div key={fc} className="collection-fc-group">
                          <div className="collection-fc-header">
                            {fc}f &nbsp;·&nbsp; {seen.get(fc).length} item{seen.get(fc).length !== 1 ? 's' : ''}
                          </div>
                          {seen.get(fc).map(item => {
                            const fps = item.fps || 24
                            const startTC = formatFrame(item.start_frame, fps)
                            const endTC = formatFrame(item.end_frame, fps)
                            return (
                              <div key={item.id} className="collection-entry">
                                <div className="collection-entry-preview">
                                  <img
                                    src={`/scene_preview/${item.scene_id}`}
                                    alt=""
                                    className="collection-entry-thumb"
                                    loading="lazy"
                                  />
                                </div>
                                <div className="collection-entry-info">
                                  <div className="collection-entry-video">{item.video_name}</div>
                                  <div className="collection-entry-frames">
                                    <span title="Start frame">f{item.start_frame}</span>
                                    <span className="collection-entry-sep">→</span>
                                    <span title="End frame">f{item.end_frame}</span>
                                  </div>
                                  <div className="collection-entry-tc">
                                    {startTC} → {endTC}
                                  </div>
                                  <div className="collection-entry-scene">scene #{item.scene_id}</div>
                                  {item.caption && (
                                    <div className="collection-entry-caption" title={item.caption}>
                                      {item.caption.length > 80 ? item.caption.slice(0, 80) + '…' : item.caption}
                                    </div>
                                  )}
                                </div>
                                <div className="collection-entry-btns">
                                <button
                                  className="collection-entry-edit"
                                  title="Edit frame range"
                                  onClick={() => setEditingItem(item)}
                                >✎</button>
                                <button
                                  className="collection-entry-remove"
                                  title="Remove from collection"
                                  onClick={() => removeItem(item.id)}
                                >✕</button>
                              </div>
                              </div>
                            )
                          })}
                        </div>
                      ))}
                    </div>
                  )
                })()}
              </>
            ) : (
              <div className="collections-empty">Select a collection to view its items.</div>
            )}
          </div>
        </div>
      </div>
    </div>

    {editingItem && (
      <CollectionItemEditor
        item={editingItem}
        collectionId={selectedId}
        onClose={() => setEditingItem(null)}
        onSaved={updated => { handleItemSaved(updated); setEditingItem(prev => ({ ...prev, ...updated })) }}
      />
    )}
    </>
  )
}
