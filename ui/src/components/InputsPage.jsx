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
  const [currentDir, setCurrentDir] = useState('')

  const uploadInputRef = useRef(null)

  const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'])
  const VIDEO_EXTS = new Set(['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.wmv'])

  const loadFiles = useCallback((dirPath) => {
    const url = dirPath
      ? `/api/inputs?dir_path=${encodeURIComponent(dirPath)}`
      : '/api/inputs'
    fetch(url)
      .then(r => r.json())
      .then(d => {
        setFiles(d.files || [])
        setLoading(false)
      })
      .catch(() => {
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    loadFiles(currentDir)
  }, [loadFiles, currentDir])

  const filtered = files.filter(f => {
    // Always keep directories visible
    if (f.type === 'dir') return true
    const ext = (f.ext || '').toLowerCase()
    if (filterType === 'image' && !IMAGE_EXTS.has(ext)) return false
    if (filterType === 'video' && !VIDEO_EXTS.has(ext)) return false
    if (searchQuery) {
      if (!f.name.toLowerCase().includes(searchQuery.toLowerCase())) return false
    }
    return true
  })

  // --- Breadcrumb navigation ---
  const breadcrumbs = currentDir ? ['.../'] : [currentDir || '/']
  if (currentDir) {
    const parts = currentDir.split('/').filter(Boolean)
    for (const part of parts) {
      breadcrumbs.push(part)
    }
  }

  function handleDirClick(dirName) {
    if (dirName === '..') {
      // Navigate up one level
      const parts = currentDir.split('/').filter(Boolean)
      parts.pop()
      setCurrentDir(parts.join('/'))
    } else if (dirName === '/') {
      setCurrentDir('')
    } else if (dirName === '.../') {
      setCurrentDir('')
    } else {
      const newDir = currentDir ? `${currentDir}/${dirName}` : dirName
      setCurrentDir(newDir)
    }
  }

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
        loadFiles(currentDir)
      } else {
        setUploadResult({ error: d.error || 'Upload failed' })
      }
    }
    xhr.onerror = () => { setUploading(false); setUploadResult({ error: 'Upload failed' }) }
    xhr.open('POST', '/api/inputs/upload')
    xhr.send(fd)
  }

  function handleDelete(filename) {
    const url = currentDir
      ? `/api/inputs/${encodeURIComponent(filename)}?dir_path=${encodeURIComponent(currentDir)}`
      : `/api/inputs/${encodeURIComponent(filename)}`
    fetch(url, { method: 'DELETE' })
      .then(r => r.json())
      .then(() => loadFiles(currentDir))
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

  // Thumbnail URL — include dir_path for subdirectory files
  function thumbUrl(file) {
    const qs = currentDir ? `?dir_path=${encodeURIComponent(currentDir)}` : ''
    return `/api/inputs/thumb/${encodeURIComponent(file.name)}${qs}`
  }

  // Preview URL
  function previewUrl(file) {
    const qs = currentDir ? `?dir_path=${encodeURIComponent(currentDir)}` : ''
    return `/api/inputs/preview/${encodeURIComponent(file.name)}${qs}`
  }

  function breadcrumbLabel(crumb, i) {
    if (i === 0) {
      return crumb === '.../' ? '📁 Inputs' : '/'
    }
    return crumb
  }

  // Separator between breadcrumb items
  function breadcrumbSep(i, total) {
    return i < total - 1 ? '  ›  ' : ''
  }

  return (
    <div className="inputs-page">
      {/* Breadcrumb Navigation */}
      <div className="inputs-breadcrumb">
        {breadcrumbs.map((crumb, i) => (
          <span key={i} className="inputs-breadcrumb-item">
            <span
              className="inputs-breadcrumb-link"
              onClick={() => handleDirClick(crumb)}
            >
              {breadcrumbLabel(crumb, i)}
              {breadcrumbSep(i, breadcrumbs.length)}
            </span>
          </span>
        ))}
        {currentDir && (
          <span className="inputs-breadcrumb-parent" onClick={() => handleDirClick('..')}>
            ↑ Parent
          </span>
        )}
      </div>

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
              f.type === 'dir' && f.name !== '..' ? (
                <DirThumb
                  key={f.name}
                  file={f}
                  onNavigate={handleDirClick}
                  currentDir={currentDir}
                />
              ) : f.type === 'dir' && f.name === '..' ? (
                <div
                  key=".."
                  className="input-thumb dir-thumb"
                  onClick={() => handleDirClick('..')}
                  style={{ cursor: 'pointer' }}
                >
                  <div className="input-thumb__media">
                    <div className="input-thumb__blur" style={{ background: '#2a2a2e' }} />
                    <div className="input-thumb__dir-icon">↑</div>
                  </div>
                  <div className="input-thumb__info">
                    <div className="input-thumb__name">Parent</div>
                    <div className="input-thumb__meta">
                      <span className="input-thumb__dir-label">Go up</span>
                    </div>
                  </div>
                </div>
              ) : (
                <InputThumb
                  key={f.name}
                  file={f}
                  onPlay={handlePlay}
                  onDelete={handleDelete}
                  thumbUrl={thumbUrl(f)}
                  isVideo={VIDEO_EXTS.has(f.ext)}
                />
              )
            ))}
          </div>
        ) : (
          <div className="inputs-list">
            {filtered.map(f => (
              f.type === 'dir' && f.name !== '..' ? (
                <DirListItem
                  key={f.name}
                  file={f}
                  onNavigate={handleDirClick}
                />
              ) : f.type === 'dir' && f.name === '..' ? (
                <div
                  key=".."
                  className="input-list-item"
                  onClick={() => handleDirClick('..')}
                  style={{ cursor: 'pointer' }}
                >
                  <span className="input-list-icon">↑</span>
                  <span className="input-list-name">Parent</span>
                  <span className="input-list-size">Go up</span>
                  <span className="input-list-delete" style={{ visibility: 'hidden' }}>✕</span>
                </div>
              ) : (
                <InputListItem
                  key={f.name}
                  file={f}
                  onDelete={handleDelete}
                />
              )
            ))}
          </div>
        )}
      </div>
    </div>
  )}

// --- Grid item for directories ---
function DirThumb({ file, onNavigate, currentDir }) {
  const [thumbSrc, setThumbSrc] = useState(null)
  const [thumbError, setThumbError] = useState(false)

  useEffect(() => {
    setThumbSrc(null)
    setThumbError(false)
    const qs = currentDir ? `?dir_path=${encodeURIComponent(currentDir)}` : ''
    const url = `/api/inputs/dir-thumb/${encodeURIComponent(file.name)}${qs}`
    fetch(url)
      .then(r => {
        if (!r.ok) {
          setThumbError(true)
          return null
        }
        return r.blob()
      })
      .then(blob => {
        if (blob) {
          const url = URL.createObjectURL(blob)
          setThumbSrc(url)
        }
      })
      .catch(() => setThumbError(true))
  }, [file.name, currentDir])

  return (
    <div
      className="input-thumb dir-thumb"
      onClick={() => onNavigate(file.name)}
      style={{ cursor: 'pointer' }}
    >
      <div className="input-thumb__media">
        <div className="input-thumb__blur" style={{ background: '#2a2a2e' }} />
        {thumbSrc && !thumbError ? (
          <img
            className="input-thumb__img"
            src={thumbSrc}
            alt={file.name}
            style={{ opacity: 1 }}
          />
        ) : (
          <div className="input-thumb__dir-icon">📁</div>
        )}
      </div>
      <div className="input-thumb__info">
        <div className="input-thumb__name" title={file.name}>{file.name}</div>
        <div className="input-thumb__meta">
          <span className="input-thumb__dir-label">Directory</span>
        </div>
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

function DirListItem({ file, onNavigate }) {
  return (
    <div
      className="input-list-item"
      onClick={() => onNavigate(file.name)}
      style={{ cursor: 'pointer' }}
    >
      <span className="input-list-icon">📁</span>
      <span className="input-list-name">{file.name}</span>
      <span className="input-list-size">Directory</span>
      <span className="input-list-delete" style={{ visibility: 'hidden' }}>✕</span>
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
