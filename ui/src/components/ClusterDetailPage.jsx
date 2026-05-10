import { useState, useEffect, useContext, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { AppContext } from '../context'
import SceneCardGrid from './SceneCardGrid'

export default function ClusterDetailPage() {
  const { clusterId } = useParams()
  const navigate = useNavigate()
  const { tagMap, refreshTags } = useContext(AppContext)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [viewMode, setViewMode] = useState('card')

  // Stable key editing state
  const [stableKey, setStableKey] = useState(null)
  const [editingKey, setEditingKey] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [keySaving, setKeySaving] = useState(false)
  const [keyError, setKeyError] = useState(null)
  const editInputRef = useRef(null)

  useEffect(() => {
    fetch(`/api/clusters/${clusterId}/scenes`)
      .then(r => r.json())
      .then(d => {
        if (d.error) throw new Error(d.error)
        setData(d)
        const ck = d.cluster.stable_key
        setStableKey(ck)
        setEditValue(ck || '')
      })
      .catch(e => setError(e.message))
  }, [clusterId])

  async function saveStableKey() {
    const val = (editValue || '').trim().toLowerCase()
    if (!val) return
    setKeySaving(true)
    setKeyError(null)
    try {
      const r = await fetch(`/api/clusters/${clusterId}/stable-key`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stable_key: val }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'Failed to update stable_key')
      setStableKey(d.stable_key)
      setEditingKey(false)
      refreshTags()
    } catch (e) {
      setKeyError(e.message)
    } finally {
      setKeySaving(false)
    }
  }

  function cancelEdit() {
    setEditingKey(false)
    setKeyError(null)
    setEditValue(stableKey || '')
  }

  if (error) return <div className="discover-empty">Error: {error}</div>
  if (!data) return <div className="discover-loading">Loading…</div>

  const { cluster, scenes } = data
  const label = cluster.promoted_tag || cluster.nearest_tag || `Cluster #${clusterId}`

  return (
    <div className="cluster-detail-page">
      <div className="cluster-detail-header">
        <button className="cluster-detail-back" onClick={() => navigate('/discover')}>← Discover</button>
        <div className="cluster-detail-title">{label}</div>
        <div className="cluster-detail-meta">
          <span className="discover-card-badge discover-card-badge--faces">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
            {cluster.size}
          </span>
          <span className="discover-card-badge discover-card-badge--scenes">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 9l5 3-5 3V9z" fill="#000" opacity=".5"/></svg>
            {cluster.scene_count}
          </span>

          {/* Stable key editor */}
          <div className="cluster-detail-stable-key">
            <span className="cluster-detail-stable-key-label">stable_key:</span>
            {editingKey ? (
              <div className="cluster-detail-key-edit-row">
                <input
                  ref={editInputRef}
                  className="cluster-detail-key-edit-input"
                  value={editValue}
                  onChange={e => { setEditValue(e.target.value); setKeyError(null) }}
                  onKeyDown={e => {
                    if (e.key === 'Enter') saveStableKey()
                    if (e.key === 'Escape') cancelEdit()
                  }}
                  autoFocus
                  placeholder="e.g. star-lord"
                />
                <button className="cluster-detail-key-save-btn" onClick={saveStableKey} disabled={keySaving || !editValue.trim()}>
                  {keySaving ? '…' : '✓'}
                </button>
                <button className="cluster-detail-key-cancel-btn" onClick={cancelEdit}>✕</button>
              </div>
            ) : (
              <div className="cluster-detail-key-display" onClick={() => { setEditingKey(true); setEditValue(stableKey || '') }} title="Click to edit">
                {stableKey || '<not set>'}
                <span className="cluster-detail-key-edit-icon">✎</span>
              </div>
            )}
            {keyError && <div className="cluster-detail-key-error">{keyError}</div>}
          </div>

          <div className="cluster-detail-view-toggle">
            {['card', 'thumb'].map(m => (
              <button
                key={m}
                className={`filter-btn${viewMode === m ? ' active' : ''}`}
                onClick={() => setViewMode(m)}
              >{m === 'card' ? 'Cards' : 'Thumbs'}</button>
            ))}
          </div>
        </div>
      </div>

      {scenes.length === 0 ? (
        <div className="discover-empty">
          No scenes found - re-run clustering to populate scene associations.
        </div>
      ) : (
        <div className="cluster-detail-scroll">
          <SceneCardGrid
            scenes={scenes}
            tagMap={tagMap}
            viewMode={viewMode}
          />
        </div>
      )}
    </div>
  )
}
