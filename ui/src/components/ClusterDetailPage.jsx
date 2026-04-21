import { useState, useEffect, useContext } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { AppContext } from '../context'
import SceneCardGrid from './SceneCardGrid'

export default function ClusterDetailPage() {
  const { clusterId } = useParams()
  const navigate = useNavigate()
  const { tagMap } = useContext(AppContext)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [viewMode, setViewMode] = useState('card')

  useEffect(() => {
    fetch(`/api/clusters/${clusterId}/scenes`)
      .then(r => r.json())
      .then(d => {
        if (d.error) throw new Error(d.error)
        setData(d)
      })
      .catch(e => setError(e.message))
  }, [clusterId])

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
          No scenes found — re-run clustering to populate scene associations.
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
