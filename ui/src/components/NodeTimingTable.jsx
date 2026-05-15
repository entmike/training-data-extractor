import { useState, useMemo } from 'react'

// ── Sort helpers ──────────────────────────────────────────────────────────────
function sortKey(nt, col) {
  switch (col) {
    case 'node':     return nt.node_id ?? ''
    case 'class':    return nt.class_type ?? ''
    case 'duration': return nt.duration_sec ?? -1
    case 'started':  return nt.started_at ? new Date(nt.started_at).getTime() : -1
    default: return 0
  }
}

function fmtDuration(seconds) {
  if (seconds == null || seconds == undefined) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds - mins * 60
  return `${mins}m ${secs.toFixed(0)}s`
}

function SortHeader({ label, col, currentCol, currentAsc, onSort }) {
  const icon = currentCol === col ? (currentAsc ? ' ▲' : ' ▼') : ''
  return (
    <th
      onClick={() => onSort(col)}
      style={{ cursor: 'pointer', userSelect: 'none', fontWeight: currentCol === col ? 'bold' : 'normal' }}
      title={`Sort by ${label}`}
    >
      {label}{icon}
    </th>
  )
}

// ── Reusable Node Timing Table ──────────────────────────────────────────────────
// Props:
//   nodes     : array of { node_id, class_type, duration_sec, step_value, steps, started_at, completed_at }
//   defaultSort?: default sort column ('duration' | 'node' | 'class' | 'started')
//   ascDefault?: default direction (default true)
export default function NodeTimingTable({ nodes, defaultSort = 'started', ascDefault = true }) {
  const [sortCol, setSortCol] = useState(defaultSort)
  const [asc, setAsc] = useState(ascDefault)

  function handleSort(col) {
    if (sortCol === col) {
      setAsc(!asc)
    } else {
      setSortCol(col)
      setAsc(true)
    }
  }

  const sorted = useMemo(() => {
    return [...(nodes || [])].sort((a, b) => {
      const ka = sortKey(a, sortCol)
      const kb = sortKey(b, sortCol)
      if (typeof ka === 'string') {
        return asc ? ka.localeCompare(kb) : kb.localeCompare(ka)
      }
      return asc ? ka - kb : kb - ka
    })
  }, [nodes, sortCol, asc])

  if (!nodes || nodes.length === 0) {
    return null
  }

  return (
    <table className="cq-node-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <SortHeader label="Node" col="node" currentCol={sortCol} currentAsc={asc} onSort={handleSort} />
          <SortHeader label="Class" col="class" currentCol={sortCol} currentAsc={asc} onSort={handleSort} />
          <SortHeader label="Duration" col="duration" currentCol={sortCol} currentAsc={asc} onSort={handleSort} />
          <th>Steps</th>
          <SortHeader label="Started" col="started" currentCol={sortCol} currentAsc={asc} onSort={handleSort} />
          <th>Completed</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((nt, i) => (
          <tr key={i} className={nt.completed_at ? '' : 'cq-node--active'}>
            <td title={nt.prompt_id ?? ''}>{nt.node_id}</td>
            <td>{nt.class_type}</td>
            <td>{fmtDuration(nt.duration_sec)}</td>
            <td>{nt.step_value != null ? `${nt.step_value}/${nt.steps ?? '?'}` : '—'}</td>
            <td>{nt.started_at ? new Date(nt.started_at).toLocaleTimeString() : '—'}</td>
            <td>{nt.completed_at ? new Date(nt.completed_at).toLocaleTimeString() : '…'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
