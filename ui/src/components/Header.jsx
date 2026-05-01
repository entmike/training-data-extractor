import { useNavigate, useLocation } from 'react-router-dom'

const TABS = [
  { path: '/videos',   label: 'Videos'   },
  { path: '/tags',     label: 'Tags'     },
  { path: '/clips',    label: 'Clips'    },
  { path: '/discover', label: 'Discover' },
  { path: '/outputs',  label: 'Outputs'  },
  { path: '/config',   label: 'Config'   },
]

export default function Header({ isLoading }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  return (
    <header className="app-header">
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
    </header>
  )
}
