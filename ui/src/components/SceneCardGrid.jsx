import SceneCard from './SceneCard'
import SceneThumbnail from './SceneThumbnail'

/**
 * Shared card/thumbnail grid used by both SceneGrid and ManageClipsModal.
 *
 * Props:
 *   scenes         — array of scene-shaped objects
 *   tagMap         — { [tag]: tagDef } from context/parent
 *   viewMode       — 'card' | 'thumb'
 *   onTagsChange   — (sceneId, tags) => void  (optional, no-op if omitted)
 *   onPlay         — (scene) => void  override click; if omitted uses VideoPlayerModal
 *   renderOverlay  — (scene) => ReactNode  per-item overlay (e.g. remove button)
 */
export default function SceneCardGrid({ scenes, tagMap, viewMode, onTagsChange, onPlay, renderOverlay }) {
  const hasOverlay = !!renderOverlay

  return (
    <div className={viewMode === 'thumb' ? 'scenes-thumbgrid' : 'scenes-grid'}>
      {scenes.map(scene => (
        <div key={scene.id} className={hasOverlay ? 'clip-scene-wrap' : undefined}>
          {viewMode === 'thumb' ? (
            <SceneThumbnail
              scene={scene}
              tagMap={tagMap}
              onPlay={onPlay ? () => onPlay(scene) : undefined}
            />
          ) : (
            <SceneCard
              scene={scene}
              tagMap={tagMap}
              visible={true}
              onTagsChange={onTagsChange ?? (() => {})}
              onPlay={onPlay ? () => onPlay(scene) : undefined}
            />
          )}
          {hasOverlay && renderOverlay(scene)}
        </div>
      ))}
    </div>
  )
}
