import { useState, useEffect, useCallback } from 'react'

/**
 * Reusable file browser with folder thumbnails.
 * Shared by InputsPage and FilePickerModal in OutputsPage.
 *
 * Props:
 *   onClose?        — called when the browser should close (for modal usage)
 *   onSelect?       — called when a file is selected (for modal usage)
 *   value?           — pre-selected file path (for modal usage)
 *   className?       — extra class for the root element
 *   title?           — header title text (default: 'Inputs')
 */
export default function FileBrowser({ onClose, onSelect, value, className = '', title = 'Inputs' }) {
  const isModal = onClose !== undefined

  // Derive the basename from the full path for selection matching
  const valueBasename = value ? value.substring(value.lastIndexOf('/') + 1) : ''

  const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'])
  const VIDEO_EXTS = new Set(['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.wmv'])

  // Synchronously determine initial directory + filter from value to avoid race with useEffect
  const initDir = isModal && value && value.lastIndexOf('/') !== -1
    ? value.substring(0, value.lastIndexOf('/'))
    : ''

  function getInitFilter() {
    if (!isModal || !valueBasename) return 'all'
    const ext = valueBasename.substring(valueBasename.lastIndexOf('.')).toLowerCase()
    if (IMAGE_EXTS.has(ext)) return 'image'
    if (VIDEO_EXTS.has(ext)) return 'video'
    return 'all'
  }

  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState(getInitFilter())
  const [viewMode, setViewMode] = useState('grid')
  const [currentDir, setCurrentDir] = useState(initDir)

  const loadFiles = useCallback((dirPath) => {
    const url = dirPath
      ? `/api/inputs?dir_path=${encodeURIComponent(dirPath)}`
      : '/api/inputs'
    setLoading(true)
    fetch(url)
      .then(r => r.json())
      .then(d => { setFiles(d.files || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadFiles(currentDir)
  }, [loadFiles, currentDir])

  const breadcrumbs = currentDir ? ['Inputs'] : ['Inputs']
  if (currentDir) {
    const parts = currentDir.split('/').filter(Boolean)
    for (const part of parts) {
      breadcrumbs.push(part)
    }
  }

  function handleBreadcrumbClick(crumb) {
    if (crumb === 'Inputs') {
      setCurrentDir('')
      return
    }
    const parts = currentDir.split('/').filter(Boolean)
    const idx = parts.indexOf(crumb)
    if (idx !== -1) {
      setCurrentDir(parts.slice(0, idx + 1).join('/'))
    }
  }

  function handleFolderNavigate(folderName) {
    if (folderName === '..') {
      const parts = currentDir.split('/').filter(Boolean)
      parts.pop()
      setCurrentDir(parts.join('/'))
    } else {
      const newDir = currentDir ? `${currentDir}/${folderName}` : folderName
      setCurrentDir(newDir)
    }
  }

  const filtered = files.filter(f => {
    if (f.type === 'dir') return true
    if (!f.ext) return false
    const ext = f.ext.toLowerCase()
    if (filterType === 'image' && !IMAGE_EXTS.has(ext)) return false
    if (filterType === 'video' && !VIDEO_EXTS.has(ext)) return false
    if (searchQuery && !f.name.toLowerCase().includes(searchQuery.toLowerCase())) return false
    return true
  })

  // Sort: parent (..) first, then directories alphabetically, then files alphabetically
  const sorted = filtered.slice().sort((a, b) => {
    const aIsParent = a.name === '..'
    const bIsParent = b.name === '..'
    if (aIsParent) return -1
    if (bIsParent) return 1
    if (a.type !== b.type) {
      return (a.type === 'dir' ? -1 : 1)
    }
    return a.name.localeCompare(b.name)
  })

  function thumbUrl(file) {
    const qs = currentDir ? `?dir_path=${encodeURIComponent(currentDir)}` : ''
    return `/api/inputs/thumb/${encodeURIComponent(file.name)}${qs}`
  }

  const rootClass = `file-browser${className ? ' ' + className : ''}`

  const content = (
    <>
      {/* Breadcrumb */}
      <div className="file-browser-breadcrumb">
        {breadcrumbs.map((crumb, i) => (
          <span key={i} className="file-browser-breadcrumb-item">
            <span
              className="file-browser-breadcrumb-link"
              onClick={() => handleBreadcrumbClick(crumb)}
            >
              {crumb}
              {i < breadcrumbs.length - 1 ? '  ›  ' : ''}
            </span>
          </span>
        ))}
        {isModal && (
          <button className="file-browser-close-btn" onClick={onClose} aria-label="Close">✕</button>
        )}
      </div>

      {/* Toolbar */}
      <div className="file-browser-toolbar">
        <input
          className="file-browser-search"
          type="text"
          placeholder="Search files…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
        />
        <div className="file-browser-filters">
          {['all', 'image', 'video'].map(t => (
            <button
              key={t}
              className={`file-browser-filter-btn${filterType === t ? ' file-browser-filter-btn--active' : ''}`}
              onClick={() => setFilterType(t)}
            >{t === 'all' ? 'All' : t === 'image' ? 'Images' : 'Videos'}</button>
          ))}
        </div>
        <div className="file-browser-view-toggle">
          <button
            className={`file-browser-view-btn${viewMode === 'grid' ? ' file-browser-view-btn--active' : ''}`}
            onClick={() => setViewMode('grid')}
          >⊞</button>
          <button
            className={`file-browser-view-btn${viewMode === 'list' ? ' file-browser-view-btn--active' : ''}`}
            onClick={() => setViewMode('list')}
          >☰</button>
        </div>
      </div>

      {/* Content */}
      <div className="file-browser-content">
        {loading ? (
          <div className="file-browser-empty"><span>Loading…</span></div>
        ) : sorted.length === 0 ? (
          <div className="file-browser-empty"><span>No matching files</span></div>
        ) : viewMode === 'grid' ? (
          <div className="file-browser-grid">
            {sorted.map(f => (
              f.type === 'dir' && f.name !== '..' ? (
                <FileBrowserDirThumb
                  key={f.name}
                  file={f}
                  onNavigate={handleFolderNavigate}
                  currentDir={currentDir}
                />
              ) : f.type === 'dir' && f.name === '..' ? (
                <div
                  key=".."
                  className="file-browser-thumb file-browser-dir-thumb"
                  onClick={() => handleFolderNavigate('..')}
                >
                  <div className="file-browser-thumb__media">
                    <div className="file-browser-thumb__blur" />
                    <div className="file-browser-thumb__dir-icon">↑</div>
                  </div>
                  <div className="file-browser-thumb__info">
                    <div className="file-browser-thumb__name">Parent</div>
                    <div className="file-browser-thumb__meta">
                      <span className="file-browser-thumb__dir-label">Go up</span>
                    </div>
                  </div>
                </div>
              ) : (
                <FileBrowserThumb
                  key={f.name}
                  file={f}
                  thumbUrl={thumbUrl(f)}
                  isSelected={isModal && f.name === valueBasename}
                  onClick={() => {
                    if (onSelect) {
                      onSelect(currentDir ? `${currentDir}/${f.name}` : f.name)
                    }
                  }}
                  isVideo={VIDEO_EXTS.has(f.ext || '')}
                />
              )
            ))}
          </div>
        ) : (
          <div className="file-browser-list">
            {sorted.map(f => (
              f.type === 'dir' && f.name !== '..' ? (
                <FileBrowserDirListItem
                  key={f.name}
                  file={f}
                  onNavigate={handleFolderNavigate}
                />
              ) : f.type === 'dir' && f.name === '..' ? (
                <div
                  key=".."
                  className="file-browser-list-item"
                  onClick={() => handleFolderNavigate('..')}
                >
                  <span className="file-browser-list-icon">↑</span>
                  <span className="file-browser-list-name">Parent</span>
                  <span className="file-browser-list-size">Go up</span>
                </div>
              ) : (
                <FileBrowserListItem
                  key={f.name}
                  file={f}
                  onDelete={() => {}}
                />
              )
            ))}
          </div>
        )}
      </div>
    </>
  )

  if (isModal) {
    return (
      <div className="modal-overlay file-browser-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
        <div className="file-browser-modal" onClick={e => e.stopPropagation()}>
          {content}
        </div>
      </div>
    )
  }

  return <div className={rootClass}>{content}</div>
}

// ── Sub-components ──

function FileBrowserDirThumb({ file, onNavigate, currentDir }) {
  const [thumbSrc, setThumbSrc] = useState(null)
  const [thumbError, setThumbError] = useState(false)

  useEffect(() => {
    setThumbSrc(null)
    setThumbError(false)
    const qs = currentDir ? `?dir_path=${encodeURIComponent(currentDir)}` : ''
    const url = `/api/inputs/dir-thumb/${encodeURIComponent(file.name)}${qs}`
    fetch(url)
      .then(r => {
        if (!r.ok) { setThumbError(true); return null }
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
    <div className="file-browser-thumb file-browser-dir-thumb" onClick={() => onNavigate(file.name)}>
      <div className="file-browser-thumb__media">
        <div className="file-browser-thumb__blur" />
        {thumbSrc && !thumbError ? (
          <img className="file-browser-thumb__img" src={thumbSrc} alt={file.name} style={{ opacity: 1 }} />
        ) : (
          <div className="file-browser-thumb__dir-icon">📁</div>
        )}
      </div>
      <div className="file-browser-thumb__info">
        <div className="file-browser-thumb__name" title={file.name}>{file.name}</div>
        <div className="file-browser-thumb__meta">
          <span className="file-browser-thumb__dir-label">Directory</span>
        </div>
      </div>
    </div>
  )
}

function FileBrowserThumb({ file, thumbUrl, isSelected, onClick, isVideo }) {
  const [imgLoaded, setImgLoaded] = useState(false)
  const [imgError, setImgError] = useState(false)

  return (
    <div className={`file-browser-thumb${isSelected ? ' file-browser-thumb--selected' : ''}`} onClick={onClick}>
      <div className="file-browser-thumb__media">
        <div className="file-browser-thumb__blur" />
        <img
          className="file-browser-thumb__img"
          src={thumbUrl}
          alt={file.name}
          loading="lazy"
          onLoad={() => { setImgLoaded(true); setImgError(false) }}
          onError={() => setImgError(true)}
          style={{ opacity: imgLoaded ? 1 : 0 }}
        />
        {isVideo && <div className="file-browser-thumb__play">▶</div>}
        {isSelected && <div className="file-browser-thumb__check">✓</div>}
      </div>
      <div className="file-browser-thumb__info">
        <div className="file-browser-thumb__name" title={file.name}>{file.name}</div>
        <div className="file-browser-thumb__meta">
          <span>{file.size ? (file.size / 1024).toFixed(0) + ' KB' : ''}</span>
          <span>{file.ext}</span>
        </div>
      </div>
    </div>
  )
}

function FileBrowserDirListItem({ file, onNavigate }) {
  return (
    <div className="file-browser-list-item" onClick={() => onNavigate(file.name)}>
      <span className="file-browser-list-icon">📁</span>
      <span className="file-browser-list-name">{file.name}</span>
      <span className="file-browser-list-size">Directory</span>
    </div>
  )
}

function FileBrowserListItem({ file }) {
  return (
    <div className="file-browser-list-item">
      <span className="file-browser-list-icon">{file.ext}</span>
      <span className="file-browser-list-name">{file.name}</span>
      <span className="file-browser-list-size">{file.size ? (file.size / 1024).toFixed(0) + ' KB' : ''}</span>
    </div>
  )
}
