/**
 * Skeleton placeholder that mirrors the visual structure of SceneCard / SceneThumbnail.
 * Used by SceneGrid and ManageClipsModal while loading.
 */
export default function SceneCardSkeleton({ viewMode = 'card' }) {
  if (viewMode === 'thumb') {
    return <div className="scene-thumb-skeleton" />
  }

  return (
    <div className="scene-card-skeleton">
      {/* Image */}
      <div className="scs-img" />

      {/* Star rating row */}
      <div className="scs-stars">
        <span className="scs-star" />
        <span className="scs-star" />
        <span className="scs-star" />
      </div>

      {/* Info section */}
      <div className="scs-info">
        {/* Meta row: scene ID + time */}
        <div className="scs-meta">
          <div className="scs-meta-left">
            <span className="skeleton skeleton--text" style={{ width: 70 }} />
            <span className="skeleton skeleton--text" style={{ width: 110, marginTop: 5 }} />
          </div>
          <span className="skeleton skeleton--text" style={{ width: 60 }} />
        </div>

        {/* Caption box */}
        <div className="scs-caption" />

        {/* Tag row */}
        <div className="scs-tags">
          <span className="scs-tag-pill" style={{ width: 52 }} />
          <span className="scs-tag-pill" style={{ width: 38 }} />
          <span className="scs-tag-pill" style={{ width: 62 }} />
        </div>
      </div>
    </div>
  )
}
