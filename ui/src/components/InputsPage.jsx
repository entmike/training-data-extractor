import { useState, useEffect, useRef, useContext, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppContext } from '../context'
import BlurhashCanvas from './BlurhashCanvas'

export default function InputsPage() {
  const { openPlayer } = useContext(AppContext)
  const navigate = useNavigate()

  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadResult, setUploadResult] = useState(null)
  const [viewMode, setViewMode] = useState('grid')  // 'grid' | 'list'

  const [filterType, setFilterType] = useState('all')  // 'all', 'image', 'video'
  const [searchQuery, setSearchQuery] = useState('')

  const uploadInputRef = useRef(null)

  const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'])
  const VIDEO_EXTS = new Set(['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.wmv'])

  const loadFiles = useCallback(() => {
    fetch('/api/inputs')
      .then(r => r.json())
      .then(d => setFiles(d.files || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadFiles()
  }, [loadFiles])

  const filtered = files.filter(f => {
    const ext = f.ext.toLowerCase()
    if (filterType === 'image' && !IMAGE_EXTS.has(ext)) return false
    if (filterType === 'video' && !VIDEO_EXTS.has(ext)) return false
    if (searchQuery) {
      if (!f.name.toLowerCase().includes(searchQuery.toLowerCase())) return false
    }
    return true
  })

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
        loadFiles()
      } else {
        setUploadResult({ error: d.error || 'Upload failed' })
      }
    }
    xhr.onerror = () => { setUploading(false); setUploadResult({ error: 'Upload failed' }) }
    xhr.open('POST', '/api/inputs/upload')
    xhr.send(fd)
  }

  function handleDelete(filename) {
    fetch(`/api/inputs/${encodeURIComponent(filename)}`, { method: 'DELETE' })
      .then(r => r.json())
      .then(() => loadFiles())
      .catch(() => {})
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

  // Thumbnail URL for images: serve directly from inputs dir
  function thumbUrl(file) {
    return IMAGE_EXTS.has(file.ext)
      ? `/api/inputs/thumb/${encodeURIComponent(file.name)}`
      : `/api/inputs/preview/${encodeURIComponent(file.name)}`
  }

  return (
    <div className="inputs-page">
      {/* Header */}
      <div className="inputs-header">
        <div className="inputs-header-left">
          <h1 className="inputs-title">📥 Inputs</h1>
          <span className="inputs-count">{filtered.length} file{filtered.length !== 1 ? 's' : ''}
            {files.length !== filtered.length ? ` (of ${files.length})` : ''}</span>
        </div>
        <div className="inputs-header-right">
          {/* Search */}
          <input
            className="inputs-search"
            type="text"
            placeholder="Search files…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {/* Filter tabs */}
          <div className="inputs-filters">
            {['all', 'image', 'video'].map(t => (
              <button
                key={t}
                className={`inputs-filter-btn${filterType === t ? ' inputs-filter-btn--active' : ''}`}
                onClick={() => setFilterType(t)}
              >{t === 'all' ? 'All' : t === 'image' ? 'Images' : 'Videos'}</button>
            ))}
          </div>
          {/* View toggle */}
          <div className="inputs-view-toggle">
            <button
              className={`inputs-view-btn${viewMode === 'grid' ? ' inputs-view-btn--active' : ''}`}
              onClick={() => setViewMode('grid')}
              title="Grid view"
            >⊞</button>
            <button
              className={`inputs-view-btn${viewMode === 'list' ? ' inputs-view-btn--active' : ''}`}
              onClick={() => setViewMode('list')}
              title="List view"
            >☰</button>
          </div>
        </div>
      </div>

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

      {/* Content */}
      <div className="inputs-content">
        {filtered.length === 0 && !loading ? (
          <div className="inputs-empty">
            <div className="inputs-empty-icon">📭</div>
            <div className="inputs-empty-text">
              {files.length === 0
                ? 'No files in inputs folder. Upload images or videos above.'
                : 'No files match your filter.'}
            </div>
          </div>
        ) : viewMode === 'grid' ? (
          <div className="inputs-grid">
            {filtered.map(f => (
              <InputThumb
                key={f.name}
                file={f}
                onPlay={handlePlay}
                onDelete={handleDelete}
                thumbUrl={thumbUrl(f)}
                isVideo={VIDEO_EXTS.has(f.ext)}
              />
            ))}
          </div>
        ) : (
          <div className="inputs-list">
            {filtered.map(f => (
              <InputListItem
                key={f.name}
                file={f}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )}

function InputThumb({ file, onPlay, onDelete, thumbUrl, isVideo }) {
  const [imgLoaded, setImgLoaded] = useState(false)

  return (
    <div className="input-thumb">
      <div className="input-thumb__media">
        <div className="input-thumb__blur" style={{ background: '#2a2a2e' }} />
        <img
          className="input-thumb__img"
          src={thumbUrl}
          alt={file.name}
          loading="lazy"
          onLoad={() => setImgLoaded(true)}
          style={{ opacity: imgLoaded ? 1 : 0 }}
        />
        {isVideo && (
          <div className="input-thumb__play" onClick={() => onPlay(file)}>
            <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
          </div>
        )}
        <div className="input-thumb__delete" onClick={() => onDelete(file.name)} title="Delete">✕</div>
      </div>
      <div className="input-thumb__info">
        <div className="input-thumb__name" title={file.name}>{file.name}</div>
        <div className="input-thumb__meta">
          <span>{(file.size / 1024).toFixed(0)} KB</span>
          <span>{file.ext}</span>
        </div>
      </div>
    </div>
  )}

function InputListItem({ file, onDelete }) {
  return (
    <div className="input-list-item">
      <span className="input-list-icon">{file.ext}</span>
      <span className="input-list-name">{file.name}</span>
      <span className="input-list-size">{(file.size / 1024).toFixed(0)} KB</span>
      <button className="input-list-delete" onClick={() => onDelete(file.name)} title="Delete">✕</button>
    </div>
  )}
