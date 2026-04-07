import { useState, useEffect, useRef } from 'react'
import CollectionItemEditor from './CollectionItemEditor'
import SceneCardGrid from './SceneCardGrid'

/** Map a collection item to the shape SceneCard / SceneThumbnail expect */
function itemToScene(item) {
  return {
    id: item.scene_id,
    preview_path: null,
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
    collection_count: 0,
  }
}

export default function ManageCollectionsModal({ tagMap, onClose }) {
  const [collections, setCollections] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [items, setItems] = useState([])
  const [loadingCollections, setLoadingCollections] = useState(true)
  const [loadingItems, setLoadingItems] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [renamingId, setRenamingId] = useState(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [editingItem, setEditingItem] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [clearingCaptions, setClearingCaptions] = useState(false)
  const [viewMode, setViewMode] = useState('thumb') // 'card' | 'thumb'
  const mouseDownOnOverlay = useRef(false)

  useEffect(() => {
    fetchCollections()
  }, [])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape' && !editingItem) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, editingItem])

  useEffect(() => {
    if (selectedId == null) { setItems([]); return }
    setLoadingItems(true)
    fetch(`/api/collections/${selectedId}/items`)
      .then(r => r.json())
      .then(d => { setItems(d.items || []); setLoadingItems(false) })
      .catch(() => setLoadingItems(false))
  }, [selectedId])

  async function fetchCollections() {
    setLoadingCollections(true)
    const r = await fetch('/api/collections')
    if (r.ok) {
      const d = await r.json()
      const cols = d.collections || []
      setCollections(cols)
      if (cols.length > 0 && selectedId == null) setSelectedId(cols[0].id)
    }
    setLoadingCollections(false)
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

  async function clearCaptions() {
    const captionedCount = items.filter(i => i.caption && !i.caption.startsWith('__')).length
    if (!confirm(`Clear captions for all ${items.length} items in "${selectedCol?.name}"?\n\n${captionedCount} item${captionedCount !== 1 ? 's' : ''} currently have captions. This cannot be undone.`)) return
    setClearingCaptions(true)
    await Promise.all(items.map(item =>
      fetch(`/api/collections/${selectedId}/items/${item.id}/caption`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caption: '' }),
      })
    ))
    setItems(prev => prev.map(i => ({ ...i, caption: '' })))
    setClearingCaptions(false)
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
              {loadingCollections ? (
                [1,2,3].map(n => (
                  <div key={n} className="collection-item collection-item--skeleton">
                    <span className="skeleton skeleton--text" style={{ width: `${50 + n * 15}%` }} />
                    <span className="skeleton skeleton--text" style={{ width: 20 }} />
                  </div>
                ))
              ) : collections.length === 0 ? (
                <div className="collections-empty">No collections yet</div>
              ) : collections.map(col => (
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
                    className="collection-clear-captions-btn"
                    onClick={clearCaptions}
                    disabled={clearingCaptions || items.length === 0}
                    title="Clear captions for all scenes in this collection"
                  >
                    {clearingCaptions ? 'Clearing…' : 'Clear captions'}
                  </button>
                  <div className="view-toggle">
                    <button
                      className={`view-toggle-btn${viewMode === 'card' ? ' active' : ''}`}
                      onClick={() => setViewMode('card')}
                      title="Card view"
                    >⊟</button>
                    <button
                      className={`view-toggle-btn${viewMode === 'thumb' ? ' active' : ''}`}
                      onClick={() => setViewMode('thumb')}
                      title="Thumbnail view"
                    >⊞</button>
                  </div>
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
                  <div className="collections-items-scroll">
                    <div className={viewMode === 'thumb' ? 'scenes-thumbgrid' : 'scenes-grid'}>
                      {Array.from({ length: 12 }).map((_, i) => (
                        <div key={i} className={viewMode === 'thumb' ? 'coll-skeleton-thumb' : 'coll-skeleton-card'}>
                          <span className="skeleton skeleton--bar coll-skeleton-img" />
                          {viewMode === 'card' && (
                            <div className="coll-skeleton-lines">
                              <span className="skeleton skeleton--text" style={{ width: '60%' }} />
                              <span className="skeleton skeleton--text" style={{ width: '85%' }} />
                              <span className="skeleton skeleton--text" style={{ width: '40%' }} />
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : items.length === 0 ? (
                  <div className="collections-empty">No items in this collection.</div>
                ) : (
                  <div className="collections-items-scroll">
                    <SceneCardGrid
                      scenes={items.map(itemToScene)}
                      tagMap={tagMap}
                      viewMode={viewMode}
                      onPlay={scene => setEditingItem(items.find(i => i.scene_id === scene.id) ?? null)}
                      renderOverlay={scene => {
                        const item = items.find(i => i.scene_id === scene.id)
                        return (
                          <div className="coll-item-overlays">
                            <button
                              className="coll-item-remove-btn"
                              title="Remove from collection"
                              onClick={() => item && removeItem(item.id)}
                            >✕</button>
                          </div>
                        )
                      }}
                    />
                  </div>
                )}
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
