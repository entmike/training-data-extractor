import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useLocation } from 'react-router-dom'

function fmtBytes(b) {
  if (b < 1024) return `${b} B`
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`
  return `${(b / 1024 ** 3).toFixed(2)} GB`
}

const ROUTE_TITLES = [
  [/^\/videos/,   'Videos'],
  [/^\/clips/,    'Clips'],
  [/^\/tags/,     'Tags'],
  [/^\/discover/, 'Discover'],
  [/^\/cluster\//, 'Cluster'],
  [/^\/outputs/,  'Outputs'],
  [/^\/config/,   'Config'],
  [/^\/queue/,    'ComfyUI Queue'],
]

export default function Header({ isLoading, onManageTags, onManageVideos, onDiscover }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  const title = ROUTE_TITLES.find(([re]) => re.test(pathname))?.[1] ?? ''

  return (
    <header className="app-header">
      <div className="header-main">
        <span className="header-title">{title}</span>
        <div className="header-spacer" />
        <ManageMenu
          onManageTags={onManageTags}
          onManageVideos={onManageVideos}
          onManageClips={() => navigate('/clips')}
          onDiscover={onDiscover || (() => navigate('/discover'))}
          disabled={isLoading}
        />
      </div>
    </header>
  )
}

function ClearCacheModal({ sizeLabel, onConfirm, onCancel }) {
  const [typed, setTyped] = useState('')
  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  function onKey(e) {
    if (e.key === 'Escape') onCancel()
    if (e.key === 'Enter' && typed === sizeLabel) onConfirm()
  }

  return createPortal(
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" style={{ maxWidth: 380 }} onClick={e => e.stopPropagation()}>
        <div className="modal-title">Clear preview cache?</div>
        <p className="modal-body-text">
          This will delete all cached preview images ({sizeLabel}). They will be regenerated on demand.
        </p>
        <p className="modal-body-text">
          Type <code>{sizeLabel}</code> to confirm:
        </p>
        <input
          ref={inputRef}
          className="modal-video-select"
          value={typed}
          onChange={e => setTyped(e.target.value)}
          onKeyDown={onKey}
          placeholder={sizeLabel}
          spellCheck={false}
        />
        <div className="modal-actions">
          <button className="modal-btn modal-btn--cancel" onClick={onCancel}>Cancel</button>
          <button
            className="modal-btn modal-btn--confirm"
            style={{ background: typed === sizeLabel ? '#ef4444' : undefined }}
            disabled={typed !== sizeLabel}
            onClick={onConfirm}
          >
            Clear Cache
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

function ManageMenu({ onManageTags, onManageVideos, onManageClips, onDiscover, disabled }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [cacheSize, setCacheSize] = useState(null)  // null = unknown, false = clearing
  const [confirmOpen, setConfirmOpen] = useState(false)
  const btnRef = useRef(null)
  const dropdownRef = useRef(null)

  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (btnRef.current?.contains(e.target)) return
      if (dropdownRef.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  useEffect(() => {
    if (!open) return
    setCacheSize(null)
    fetch('/api/cache/previews')
      .then(r => r.json())
      .then(d => setCacheSize(d.size_bytes ?? 0))
      .catch(() => setCacheSize(0))
  }, [open])

  function openConfirm() {
    setOpen(false)
    setConfirmOpen(true)
  }

  async function clearCache() {
    setConfirmOpen(false)
    setCacheSize(false)
    await fetch('/api/cache/previews', { method: 'DELETE' })
    setCacheSize(0)
  }

  const cacheSizeLabel = cacheSize === null ? '…'
    : cacheSize === false ? 'Clearing…'
    : fmtBytes(cacheSize)

  const items = [
    { label: 'Tags', action: onManageTags },
    { label: 'Videos', action: onManageVideos },
    { label: 'Clips', action: onManageClips },
    { label: 'Discover', action: onDiscover },
    { label: 'Outputs',       action: () => navigate('/outputs') },
    { label: 'ComfyUI Queue', action: () => navigate('/queue')   },
    { label: 'Config',        action: () => navigate('/config')  },
  ]

  return (
    <div className="manage-menu">
      <button
        ref={btnRef}
        className={`action-btn manage-menu-btn${open ? ' active' : ''}`}
        onClick={() => setOpen(o => !o)}
        disabled={disabled}
      >
        Manage ▾
      </button>
      {open && createPortal(
        <div
          ref={dropdownRef}
          className="manage-menu-dropdown"
          style={(() => {
            const r = btnRef.current?.getBoundingClientRect()
            return r ? { top: r.bottom + 4, right: window.innerWidth - r.right } : {}
          })()}
        >
          {items.map(({ label, action }) => (
            <button
              key={label}
              className="manage-menu-item"
              onClick={() => { setOpen(false); action() }}
            >
              {label}
            </button>
          ))}
          <div className="manage-menu-sep" />
          <button
            className="manage-menu-item manage-menu-item--danger"
            disabled={cacheSize === null || cacheSize === false || cacheSize === 0}
            onClick={openConfirm}
          >
            Clear Cache ({cacheSizeLabel})
          </button>
        </div>,
        document.body
      )}

      {confirmOpen && cacheSize > 0 && (
        <ClearCacheModal
          sizeLabel={fmtBytes(cacheSize)}
          onConfirm={clearCache}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </div>
  )
}
