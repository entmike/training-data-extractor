import { useState, useContext } from 'react'
import { AppContext } from '../context'
import FileBrowser from './FileBrowser'
import BlurhashCanvas from './BlurhashCanvas'

export default function InputsPage() {
  const { openPlayer } = useContext(AppContext)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadResult, setUploadResult] = useState(null)
  const uploadInputRef = { current: null }

  const VIDEO_EXTS = new Set(['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.wmv'])

  function handleUploadInput(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setUploadResult(null)
    setUploading(true)
    setUploadProgress(0)
    const fd = new FormData()
    fd.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.upload.onprogress = ev => {
      if (ev.lengthComputable) setUploadProgress(Math.round(ev.loaded / ev.total * 100))
    }
    xhr.onload = () => {
      setUploading(false)
      setUploadProgress(0)
      const d = JSON.parse(xhr.responseText)
      if (xhr.status === 200 || xhr.status === 201) {
        setUploadResult({ name: d.filename, ext: d.ext })
        // Trigger a refresh by toggling a key — the FileBrowser will re-fetch
        setRefreshKey(k => k + 1)
      } else {
        setUploadResult({ error: d.error || 'Upload failed' })
      }
    }
    xhr.onerror = () => { setUploading(false); setUploadResult({ error: 'Upload failed' }) }
    xhr.open('POST', '/api/inputs/upload')
    xhr.send(fd)
  }

  function handlePlay(file) {
    if (!VIDEO_EXTS.has(file.ext)) return
    openPlayer({
      sceneId: 0,
      videoPath: file.path,
      videoName: file.name,
      fps: 24,
      frameOffset: 0,
      caption: '',
    })
  }

  function handleDelete(filename, currentDir) {
    const url = currentDir
      ? `/api/inputs/${encodeURIComponent(filename)}?dir_path=${encodeURIComponent(currentDir)}`
      : `/api/inputs/${encodeURIComponent(filename)}`
    fetch(url, { method: 'DELETE' })
      .then(r => r.json())
      .then(() => setRefreshKey(k => k + 1))
      .catch(() => {})
  }

  const [refreshKey, setRefreshKey] = useState(0)

  return (
    <div className="inputs-page">
      {/* Upload bar */}
      <div className="inputs-upload-bar">
        <input
          ref={uploadInputRef}
          type="file"
          accept=".mp4,.mkv,.avi,.mov,.webm,.m4v,.wmv,.jpg,.jpeg,.png,.webp,.bmp,.tiff,.tif"
          style={{ display: 'none' }}
          onChange={handleUploadInput}
        />
        {uploading ? (
          <div className="inputs-upload-progress">
            <div className="inputs-upload-progress-bar" style={{ width: `${uploadProgress}%` }} />
            <span>Uploading… {uploadProgress}%</span>
          </div>
        ) : (
          <button
            className="inputs-upload-btn"
            onClick={() => { setUploadResult(null); uploadInputRef.current?.click() }}
          >+ Upload to inputs</button>
        )}
        {uploadResult && (
          uploadResult.error
            ? <div className="inputs-upload-result inputs-upload-result--error">{uploadResult.error}</div>
            : <div className="inputs-upload-result inputs-upload-result--ok">Uploaded: {uploadResult.name}</div>
        )}
      </div>

      {/* Shared file browser */}
      <div key={refreshKey} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <FileBrowser />
      </div>
    </div>
  )
}
