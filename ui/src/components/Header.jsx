import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useLocation } from 'react-router-dom'

const ROUTE_TITLES = [
  [/^\/videos/, 'Videos'],
  [/^\/clips/,  'Clips'],
  [/^\/tags/,   'Tags'],
]

export default function Header({ isLoading, onManageTags, onManageVideos }) {
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
          disabled={isLoading}
        />
      </div>
    </header>
  )
}

function ManageMenu({ onManageTags, onManageVideos, onManageClips, disabled }) {
  const [open, setOpen] = useState(false)
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

  const items = [
    { label: 'Tags', action: onManageTags },
    { label: 'Videos', action: onManageVideos },
    { label: 'Clips', action: onManageClips },
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
        </div>,
        document.body
      )}
    </div>
  )
}
