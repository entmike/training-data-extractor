import { useState, useEffect, useContext } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { AppContext } from '../context'
import SceneGrid from './SceneGrid'

export default function TagsPage() {
  const { tag: tagParam } = useParams()
  const navigate = useNavigate()
  const { tagMap, refreshTags } = useContext(AppContext)
  const [tags, setTags] = useState([])
  const [loading, setLoading] = useState(true)
  const [detailCollapsed, setDetailCollapsed] = useState(false)
  const [activeTab, setActiveTab] = useState('scenes')
  const [allRefs, setAllRefs] = useState(null) // all refs for selected tag (null = not fetched)
  const [unverifiedOnly, setUnverifiedOnly] = useState(false)
  const [mobilePickerOpen, setMobilePickerOpen] = useState(false)

  const faceRefs = (allRefs || []).filter(r => !r.embedding_type || r.embedding_type === 'insightface')
  const clipRefs = (allRefs || []).filter(r => r.embedding_type === 'clip')

  const selectedTag = tagParam ? decodeURIComponent(tagParam) : null

  useEffect(() => {
    fetch('/api/tags/all')
      .then(r => r.json())
      .then(d => {
        setTags(d.tags || [])
        setLoading(false)
      })
  }, [])

  // Reset to scenes tab and fetch refs when switching tags
  useEffect(() => {
    setActiveTab('scenes')
    setAllRefs(null)
    setUnverifiedOnly(false)
    if (!selectedTag) return
    fetch(`/api/tag-refs?tag=${encodeURIComponent(selectedTag)}`)
      .then(r => r.json())
      .then(d => setAllRefs(d.refs || []))
      .catch(() => setAllRefs([]))
  }, [selectedTag])

  function selectTag(tag) {
    setMobilePickerOpen(false)
    navigate(tag === selectedTag ? '/tags' : `/tags/${encodeURIComponent(tag)}`)
  }

  function handleTagUpdated(oldTag, updated) {
    setTags(prev => prev.map(t => t.tag === oldTag ? { ...t, ...updated } : t))
    if (selectedTag === oldTag && updated.tag) navigate(`/tags/${encodeURIComponent(updated.tag)}`, { replace: true })
    refreshTags()
  }

  const selected = tags.find(t => t.tag === selectedTag) ?? null

  return (
    <div className="videos-page">
      <button
        type="button"
        className="list-mobile-picker"
        onClick={() => setMobilePickerOpen(o => !o)}
        aria-expanded={mobilePickerOpen}
      >
        <span className="list-mobile-picker__label">
          {selected ? (selected.display_name || selected.tag) : (tags.length === 0 ? 'No tags' : 'Choose tag…')}
        </span>
        <span className="list-mobile-picker__chev" aria-hidden="true">{mobilePickerOpen ? '▾' : '▸'}</span>
      </button>
      {mobilePickerOpen && (
        <div className="list-mobile-backdrop" onClick={() => setMobilePickerOpen(false)} />
      )}
      <div className="videos-layout">

        {/* Sidebar */}
        <div className={`videos-sidebar${mobilePickerOpen ? ' videos-sidebar--open' : ''}`}>
          {loading ? (
            [1,2,3,4].map(n => (
              <div key={n} className="video-sidebar-item video-sidebar-item--skeleton">
                <span className="skeleton skeleton--text" style={{ width: `${40 + n * 12}%` }} />
                <span className="skeleton skeleton--text" style={{ width: 24 }} />
                <span className="skeleton skeleton--text" style={{ width: 36 }} />
              </div>
            ))
          ) : tags.map(t => (
            <div
              key={t.tag}
              className={`video-sidebar-item${t.tag === selectedTag ? ' video-sidebar-item--active' : ''}`}
              onClick={() => selectTag(t.tag)}
            >
              <span className="video-sidebar-name">{t.display_name || t.tag}</span>
              <span className="video-sidebar-count">{t.scene_count ?? ''}</span>
              <span className="video-sidebar-frames" title="Total frames">{t.total_frames > 0 ? `${t.total_frames.toLocaleString()}f` : ''}</span>
            </div>
          ))}
        </div>

        {/* Right panel */}
        <div className="videos-right-panel">
          {selected ? (
            <>
              <div className="videos-detail-panel">
                <div className="detail-panel-header" onClick={() => setDetailCollapsed(c => !c)}>
                  <span className="collapse-toggle-btn">{detailCollapsed ? '▸' : '▾'}</span>
                  <span className="detail-panel-title">{selected.display_name || selected.tag}</span>
                </div>
                {!detailCollapsed && (
                  <TagDetail tag={selected} onUpdated={updated => handleTagUpdated(selected.tag, updated)} />
                )}
              </div>

              {/* Tab bar */}
              <div className="tag-tabs">
                <button
                  className={`tag-tab-btn${activeTab === 'scenes' ? ' tag-tab-btn--active' : ''}`}
                  onClick={() => setActiveTab('scenes')}
                >
                  Scenes
                  {selected.scene_count > 0 && <span className="tag-tab-count">{selected.scene_count}</span>}
                </button>
                <button
                  className={`tag-tab-btn${activeTab === 'refs' ? ' tag-tab-btn--active' : ''}`}
                  onClick={() => setActiveTab('refs')}
                >
                  Face refs
                  {faceRefs.length > 0 && <span className="tag-tab-count">{faceRefs.length}</span>}
                </button>
                <button
                  className={`tag-tab-btn tag-tab-btn--clip${activeTab === 'cliprefs' ? ' tag-tab-btn--active' : ''}`}
                  onClick={() => setActiveTab('cliprefs')}
                >
                  CLIP refs
                  {clipRefs.length > 0 && <span className="tag-tab-count tag-tab-count--clip">{clipRefs.length}</span>}
                </button>
                {activeTab === 'scenes' && (
                  <button
                    className={`tag-tab-filter-btn${unverifiedOnly ? ' tag-tab-filter-btn--active' : ''}`}
                    onClick={() => setUnverifiedOnly(v => !v)}
                    title="Show only auto-detected unverified scenes"
                  >
                    Unverified only
                  </button>
                )}
              </div>

              {/* Tab panels */}
              <div className="videos-scenes-panel" style={{ display: activeTab === 'scenes' ? 'flex' : 'none', flexDirection: 'column' }}>
                <SceneGrid
                  activeIncludeTags={new Set([selectedTag])}
                  activeExcludeTags={new Set()}
                  includeMode="and"
                  minFrames={0}
                  ratingFilter={new Set()}
                  tagMap={tagMap}
                  totalCount={selected.scene_count}
                  unconfirmedTag={unverifiedOnly ? selectedTag : undefined}
                />
              </div>

              {activeTab === 'refs' && (
                <div className="tag-refs-panel">
                  <FaceRefsPanel
                    refs={faceRefs}
                    loading={allRefs === null}
                    emptyMsg={<>No face references yet. While playing a scene, use <strong>+ Face ref</strong> to register one.</>}
                    onRefDeleted={id => setAllRefs(prev => prev.filter(r => r.id !== id))}
                  />
                </div>
              )}

              {activeTab === 'cliprefs' && (
                <div className="tag-refs-panel">
                  <FaceRefsPanel
                    refs={clipRefs}
                    loading={allRefs === null}
                    emptyMsg={<>No CLIP references yet. While playing a scene, use <strong>+ CLIP ref</strong> to register one.</>}
                    onRefDeleted={id => setAllRefs(prev => prev.filter(r => r.id !== id))}
                  />
                </div>
              )}
            </>
          ) : !loading && (
            <div className="videos-empty">Select a tag</div>
          )}
        </div>

      </div>
    </div>
  )
}

function FaceRefsPanel({ refs, loading, emptyMsg, onRefDeleted }) {
  async function deleteRef(id) {
    const r = await fetch(`/api/tag-refs/${id}`, { method: 'DELETE' })
    if (r.ok) onRefDeleted?.(id)
  }

  if (loading) return <div className="tag-refs-loading">Loading…</div>

  if (refs.length === 0) return (
    <div className="tag-refs-empty">{emptyMsg}</div>
  )

  return (
    <div className="tag-refs-grid">
      {refs.map(ref => (
        <div key={ref.id} className="tag-ref-card">
          <button
            className="tag-ref-delete-btn"
            title="Remove this reference"
            onClick={() => deleteRef(ref.id)}
          >✕</button>
          <img
            className="tag-ref-img"
            src={`/api/tag-refs/${ref.id}/image`}
            alt={`ref frame ${ref.frame_number}`}
            loading="lazy"
          />
          <div className="tag-ref-meta">
            frame {ref.frame_number ?? '?'}
          </div>
        </div>
      ))}
    </div>
  )
}

function TagDetail({ tag, onUpdated }) {
  const [keyVal, setKeyVal] = useState(tag.tag)
  const [displayName, setDisplayName] = useState(tag.display_name || '')
  const [description, setDescription] = useState(tag.description || '')
  const [savedDisplay, setSavedDisplay] = useState(tag.display_name || '')
  const [savedDesc, setSavedDesc] = useState(tag.description || '')
  const [renameStatus, setRenameStatus] = useState('')
  const [descStatus, setDescStatus] = useState('')

  useEffect(() => {
    setKeyVal(tag.tag)
    setDisplayName(tag.display_name || '')
    setDescription(tag.description || '')
    setSavedDisplay(tag.display_name || '')
    setSavedDesc(tag.description || '')
    setRenameStatus('')
    setDescStatus('')
  }, [tag.tag])

  const keyDirty = keyVal.trim() !== tag.tag

  async function doRename() {
    const newTag = keyVal.trim().toLowerCase()
    if (!newTag || newTag === tag.tag) return
    setRenameStatus('Saving…')
    try {
      const r = await fetch('/api/tags/rename', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_tag: tag.tag, new_tag: newTag }),
      })
      if (!r.ok) throw new Error()
      const d = await r.json()
      onUpdated({ tag: newTag })
      setRenameStatus(`✓ ${d.updated} scenes updated`)
      setTimeout(() => setRenameStatus(''), 3000)
    } catch {
      setRenameStatus('Error')
    }
  }

  async function saveDescFields() {
    const dn = displayName.trim()
    const desc = description.trim()
    if (dn === savedDisplay && desc === savedDesc) return
    setDescStatus('Saving…')
    try {
      const r = await fetch('/api/tags/description', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: tag.tag, display_name: dn, description: desc }),
      })
      if (!r.ok) throw new Error()
      setSavedDisplay(dn)
      setSavedDesc(desc)
      onUpdated({ display_name: dn, description: desc })
      setDescStatus('✓ Saved')
      setTimeout(() => setDescStatus(''), 3000)
    } catch {
      setDescStatus('Error')
    }
  }

  return (
    <div className="video-detail">
      <div className="video-detail-fields">

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">Tag key</label>
          <div className="video-detail-input-row">
            <input
              className="video-detail-input"
              value={keyVal}
              onChange={e => setKeyVal(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && keyDirty) doRename() }}
            />
            <span className="video-detail-status">{renameStatus}</span>
            <button className="save-btn" disabled={!keyDirty} onClick={doRename}>Rename</button>
          </div>
        </div>

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">Display name</label>
          <div className="video-detail-input-row">
            <input
              className="video-detail-input"
              value={displayName}
              placeholder="e.g. Deadpool, Jules…"
              onChange={e => setDisplayName(e.target.value)}
              onBlur={saveDescFields}
              onKeyDown={e => { if (e.key === 'Enter') e.target.blur() }}
            />
            <span className="video-detail-status">{descStatus}</span>
          </div>
        </div>

        <div className="video-detail-field video-detail-field--full">
          <label className="video-detail-label">
            Captioner description
            <span className="video-detail-label-hint"> — shown to the VLM to identify this tag</span>
          </label>
          <textarea
            className="video-detail-textarea"
            value={description}
            placeholder="Visual description for captioner…"
            rows={3}
            onChange={e => setDescription(e.target.value)}
            onBlur={saveDescFields}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) e.target.blur() }}
          />
        </div>

      </div>
    </div>
  )
}
