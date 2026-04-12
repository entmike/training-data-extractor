import { useState } from 'react'
import SceneCardGrid from './SceneCardGrid'
import SceneCardSkeleton from './SceneCardSkeleton'
import ViewToggle from './ViewToggle'

/**
 * Self-contained panel: owns viewMode + toggle, handles loading skeletons,
 * and renders SceneCardGrid. Used wherever a static list of scenes/items
 * needs card/thumb switching without external state management.
 */
const SORTS = [['', 'Default'], ['frames_asc', 'Start ↑'], ['frames_desc', 'Start ↓']]

export default function SceneCardPanel({ scenes, tagMap, loading, emptyMessage = 'No items.', onPlay, renderOverlay, defaultViewMode = 'card', sort = '', onSortChange, actions }) {
  const [viewMode, setViewMode] = useState(defaultViewMode)

  return (
    <div className="scene-card-panel">
      <div className="scene-card-panel-toolbar">
        <ViewToggle value={viewMode} onChange={setViewMode} />
        <div className="filter-buttons">
          {SORTS.map(([val, label]) => (
            <button
              key={val}
              className={`filter-btn${sort === val ? ' active' : ''}`}
              onClick={() => onSortChange?.(val)}
            >{label}</button>
          ))}
        </div>
        {actions}
      </div>
      <div className="scene-card-panel-body">
        {loading ? (
          <div className={viewMode === 'thumb' ? 'scenes-thumbgrid' : 'scenes-grid'}>
            {Array.from({ length: viewMode === 'thumb' ? 24 : 6 }).map((_, i) => (
              <SceneCardSkeleton key={i} viewMode={viewMode} />
            ))}
          </div>
        ) : scenes.length === 0 ? (
          <div className="clips-empty">{emptyMessage}</div>
        ) : (
          <SceneCardGrid
            scenes={scenes}
            tagMap={tagMap}
            viewMode={viewMode}
            onPlay={onPlay}
            renderOverlay={renderOverlay}
          />
        )}
      </div>
    </div>
  )
}
