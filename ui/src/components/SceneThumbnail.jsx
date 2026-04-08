import { useState, useContext } from 'react'
import { AppContext } from '../context'
import BlurhashCanvas from './BlurhashCanvas'

export default function SceneThumbnail({ scene, tagMap, onPlay }) {
  const { openPlayer } = useContext(AppContext)
  const [imgLoaded, setImgLoaded] = useState(false)

  const imgSrc = scene.preview_path
    ? `/preview/${scene.preview_path}`
    : `/scene_preview/${scene.id}`

  function playVideo() {
    if (onPlay) { onPlay(); return }
    openPlayer({
      sceneId: scene.id,
      videoPath: scene.video_path,
      startFrame: scene.start_frame,
      endFrame: scene.end_frame,
      startTime: scene.start_time,
      endTime: scene.end_time,
      fps: scene.fps,
      frameOffset: scene.frame_offset,
      blurhash: scene.blurhash,
      caption: (scene.caption && !scene.caption.startsWith('__')) ? scene.caption : '',
      tags: scene.tags || [],
      rating: scene.rating || 0,
      onCaptionChange: () => {},
      onTagsChange: () => {},
      onRatingChange: () => {},
    })
  }

  return (
    <div className="scene-thumb" onClick={playVideo} title={`Scene #${scene.id} — ${scene.video_name}\n${scene.start_time_hms} (${(scene.duration || 0).toFixed(1)}s)`}>
      <BlurhashCanvas hash={scene.blurhash} className="scene-thumb__blur" />
      <img
        className="scene-thumb__img"
        src={imgSrc}
        alt={`Scene ${scene.id}`}
        loading="lazy"
        onLoad={() => setImgLoaded(true)}
        style={{ opacity: imgLoaded ? 1 : 0 }}
      />
      {scene.rating > 0 && (
        <span className="scene-thumb__rating">{'★'.repeat(scene.rating)}</span>
      )}
      {scene.clip_count > 0 && (
        <span className="scene-thumb__clip">⊞{scene.clip_count}</span>
      )}
      <div className="scene-thumb__play">
        <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
      </div>
    </div>
  )
}
