import { useState, useEffect, useRef } from 'react'

export default function ManageTagsModal({ onClose }) {
  const [tags, setTags] = useState([])
  const [loading, setLoading] = useState(true)
  const mouseDownOnOverlay = useRef(false)

  useEffect(() => {
    fetch('/api/tags/all')
      .then(r => r.json())
      .then(d => { setTags(d.tags || []); setLoading(false) })
  }, [])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-overlay" onMouseDown={e => { mouseDownOnOverlay.current = e.target === e.currentTarget }} onClick={e => { if (mouseDownOnOverlay.current && e.target === e.currentTarget) onClose() }}>
      <div className="modal-box">
        <div className="modal-header">
          <h2>Manage Tags</h2>
          <button className="modal-close-btn" onClick={onClose}>&times;</button>
        </div>

        {loading ? (
          <div className="modal-empty">Loading…</div>
        ) : tags.length === 0 ? (
          <div className="modal-empty">No tags in database</div>
        ) : (
          <div className="tags-grid">
            <div className="tags-grid-header">Tag key</div>
            <div className="tags-grid-header">Display name</div>
            <div className="tags-grid-header">Captioner description</div>
            <div className="tags-grid-header" />
            <div className="tags-grid-header" />
            {tags.map(t => (
              <TagRow key={t.tag} tagDef={t} onChange={(updated) => {
                setTags(prev => prev.map(x => x.tag === t.tag ? { ...x, ...updated } : x))
              }} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TagRow({ tagDef, onChange }) {
  const [keyVal, setKeyVal] = useState(tagDef.tag)
  const [displayName, setDisplayName] = useState(tagDef.display_name || '')
  const [description, setDescription] = useState(tagDef.description || '')
  const [savedDisplay, setSavedDisplay] = useState(tagDef.display_name || '')
  const [savedDesc, setSavedDesc] = useState(tagDef.description || '')
  const [renameStatus, setRenameStatus] = useState('')

  const keyDirty = keyVal.trim() !== tagDef.tag

  async function doRename() {
    const newTag = keyVal.trim().toLowerCase()
    if (!newTag || newTag === tagDef.tag) return
    setRenameStatus('Saving…')
    try {
      const r = await fetch('/api/tags/rename', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_tag: tagDef.tag, new_tag: newTag }),
      })
      if (!r.ok) throw new Error()
      const d = await r.json()
      onChange({ tag: newTag })
      setRenameStatus(`✓ ${d.updated} updated`)
      setTimeout(() => setRenameStatus(''), 3000)
    } catch {
      setRenameStatus('Error')
    }
  }

  async function saveDescFields() {
    const dn = displayName.trim()
    const desc = description.trim()
    if (dn === savedDisplay && desc === savedDesc) return
    setRenameStatus('Saving…')
    try {
      const r = await fetch('/api/tags/description', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: tagDef.tag, display_name: dn, description: desc }),
      })
      if (!r.ok) throw new Error()
      setSavedDisplay(dn)
      setSavedDesc(desc)
      setRenameStatus('✓ Saved')
      setTimeout(() => setRenameStatus(''), 3000)
    } catch {
      setRenameStatus('Error')
    }
  }

  return (
    <>
      <div className="tags-grid-sep" />
      <input
        type="text"
        value={keyVal}
        onChange={e => setKeyVal(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && keyDirty) doRename() }}
      />
      <input
        type="text"
        className="desc-input"
        value={displayName}
        placeholder="e.g. Deadpool, Jules…"
        onChange={e => setDisplayName(e.target.value)}
        onBlur={saveDescFields}
        onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }}
      />
      <input
        type="text"
        className="desc-input"
        value={description}
        placeholder="Visual description for captioner…"
        onChange={e => setDescription(e.target.value)}
        onBlur={saveDescFields}
        onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }}
      />
      <button
        className="tags-grid-btn"
        disabled={!keyDirty}
        onClick={doRename}
      >
        Rename
      </button>
      <span className="tags-grid-status">{renameStatus}</span>
    </>
  )
}
