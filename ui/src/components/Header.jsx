import { useNavigate, useLocation } from 'react-router-dom'
import { useContext } from 'react'
import { AppContext } from '../context'

const TABS = [
  { path: '/videos',   label: 'Videos'   },
  { path: '/tags',     label: 'Tags'     },
  { path: '/clips',    label: 'Clips'    },
  { path: '/discover', label: 'Discover' },
  { path: '/outputs',  label: 'Outputs'  },
]

export default function Header({ isLoading }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { configOpen, toggleConfig, queueOpen, toggleQueue, comfyQueue } = useContext(AppContext)
  const queueCount = (comfyQueue?.running?.length ?? 0) + (comfyQueue?.pending?.length ?? 0)

  return (
    <header className="app-header">
      <div className="header-inner">
        <nav className="header-tabs" role="tablist">
          {TABS.map(({ path, label }) => {
            const active = pathname === path || pathname.startsWith(path + '/')
            return (
              <button
                key={path}
                role="tab"
                aria-selected={active}
                className={`header-tab${active ? ' header-tab--active' : ''}`}
                onClick={() => navigate(path)}
                disabled={isLoading}
              >
                {label}
              </button>
            )
          })}
        </nav>
        <div style={{ display: 'flex', alignItems: 'stretch', flexShrink: 0 }}>
          <button
            className={`header-config-btn${queueOpen ? ' header-config-btn--active' : ''}`}
            onClick={toggleQueue}
            title="ComfyUI Queue"
            aria-label="Toggle ComfyUI queue"
            style={{ position: 'relative' }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" style={{ display: 'block' }}>
              <rect x="1" y="2" width="14" height="2" rx="1"/>
              <rect x="1" y="7" width="14" height="2" rx="1"/>
              <rect x="1" y="12" width="9" height="2" rx="1"/>
            </svg>
            {queueCount > 0 && (
              <span className="header-queue-badge">{queueCount}</span>
            )}
          </button>
          <button
            className={`header-config-btn${configOpen ? ' header-config-btn--active' : ''}`}
            onClick={toggleConfig}
            title="Configuration"
            aria-label="Toggle configuration panel"
          >
            ⚙
          </button>
        </div>
      </div>
    </header>
  )
}
