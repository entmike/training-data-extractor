import { useState, useContext } from 'react'
import { AppContext } from '../context'
import BlurhashCanvas from './BlurhashCanvas'

export default function SceneThumbnail({ scene, tagMap, onPlay }) {
  const { openPlayer } = useContext(AppContext)
  const [imgLoaded, setImgLoaded] = useState(false)

  const imgSrc = scene.preview_path
    ? `/preview/${scene.preview_path}`
    : `/scene_preview/${scene.id}/thumb`

  function playVideo() {
    if (onPlay) { onPlay(); return }
    openPlayer({
      sceneId: scene.id,
      videoPath: scene.video_path,
      startFrame: scene.start_frame,
      endFrame: scene.end_frame,
      videoTotalFrames: scene.video_total_frames || 0,
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
      {(scene.rating > 0 || scene.mute || scene.denoise) && (
        <div className="scene-thumb__meta">
          {scene.rating > 0 && <span className="scene-thumb__rating">{'★'.repeat(scene.rating)}</span>}
          {scene.mute && (
            <span className="scene-thumb__mute" title="Muted">
              <svg viewBox="0 0 24 24" fill="currentColor" width="10" height="10"><path d="M16.5 12A4.5 4.5 0 0014 7.97v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.8 8.8 0 0021 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06A8.99 8.99 0 0017.73 18l1.28 1.27L20 18l-16-16-1.73 1.73zm9.73.73L9.13 8.6 12 11.47V4.73z"/></svg>
            </span>
          )}
          {scene.denoise && (
            <span className="scene-thumb__denoise" title="Denoise">
              <svg viewBox="0 0 24 24" fill="currentColor" width="10" height="10"><path d="M3 9h2V5H3v4zm0 4h2v-2H3v2zm0 4h2v-2H3v2zm4 0h2v-2H7v2zm0-8h2V5H7v4zm4 12v-4h-2v4h2zm-4-4h2v-2H7v2zm8 0h2v-2h-2v2zm2-12v4h2V5h-2zm0 8h2v-2h-2v2zM3 21h2v-2H3v2zm12-4h2v-2h-2v2zm2 4h2v-2h-2v2zm-8 0h2v-2h-2v2zm-4-8h2V9H7v4zm8 4h2v-4h-2v4zm-4 4h2V5h-2v16zm4-8h2V9h-2v4z"/></svg>
            </span>
          )}
        </div>
      )}
      {scene.clip_count > 0 && (
        <span className="scene-thumb__clip">⊞{scene.clip_count}</span>
      )}
      {scene.max_faces > 0 && (
        <span className="scene-thumb__faces" title={`Up to ${scene.max_faces} face${scene.max_faces !== 1 ? 's' : ''} detected`}>
          👤{scene.max_faces}
        </span>
      )}
      <div className="scene-thumb__play">
        <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
      </div>
    </div>
  )
}
