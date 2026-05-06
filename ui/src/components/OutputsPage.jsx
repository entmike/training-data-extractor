import { useState, useEffect, useCallback, useRef, useContext } from 'react'
import { createPortal } from 'react-dom'
import JsonView from '@uiw/react-json-view'
import { darkTheme } from '@uiw/react-json-view/dark'
import Header from './Header'
import { AppContext } from '../context'

const PAGE_SIZE = 50

function fmtBytes(b) {
  if (!b) return '?'
  if (b < 1024) return `${b} B`
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`
  return `${(b / 1024 ** 3).toFixed(2)} GB`
}

function fmtDate(iso) {
  if (!iso) return '?'
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// ── Copy-on-click SHA-256 ────────────────────────────────────────────────────

function CopyHash({ hash }) {
  const [copied, setCopied] = useState(false)
  if (!hash) return null
  function handleClick() {
    function markCopied() { setCopied(true); setTimeout(() => setCopied(false), 1500) }
    if (navigator.clipboard) {
      navigator.clipboard.writeText(hash).then(markCopied).catch(() => fallback())
    } else {
      fallback()
    }
    function fallback() {
      const ta = document.createElement('textarea')
      ta.value = hash
      ta.style.cssText = 'position:fixed;opacity:0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      markCopied()
    }
  }
  return (
    <span>
      <b style={{ color: 'var(--text)' }}>SHA-256</b>{' '}
      <span
        onClick={handleClick}
        title={hash}
        style={{
          cursor: 'pointer',
          display: 'inline-block',
          padding: '1px 6px',
          borderRadius: 4,
          fontSize: 11,
          fontFamily: 'monospace',
          background: copied ? 'var(--accent, #7c6af7)' : 'var(--bg-hover)',
          color: copied ? '#fff' : 'var(--text-muted)',
        }}
      >
        {copied ? 'copied!' : hash.slice(0, 8)}
      </span>
    </span>
  )
}

// ── JSON editing utilities ───────────────────────────────────────────────────

function collectMatches(node, query, path = [], out = []) {
  if (node === null || node === undefined) return
  const q = query.toLowerCase()
  if (typeof node === 'object') {
    const entries = Array.isArray(node) ? node.map((v, i) => [i, v]) : Object.entries(node)
    for (const [k, v] of entries) collectMatches(v, query, [...path, k], out)
  } else {
    if (String(node).toLowerCase().includes(q)) out.push({ path, value: node })
  }
  return out
}

function collectKeyMatches(node, query, path = [], out = []) {
  if (node === null || node === undefined || typeof node !== 'object') return out
  const q = query.toLowerCase()
  const entries = Array.isArray(node) ? node.map((v, i) => [i, v]) : Object.entries(node)
  for (const [k, v] of entries) {
    if (String(k).toLowerCase().includes(q)) out.push({ path: [...path, k], value: v, matchedKey: String(k) })
    collectKeyMatches(v, query, [...path, k], out)
  }
  return out
}

function summariseValue(v) {
  if (v === null) return 'null'
  if (typeof v === 'object') return Array.isArray(v) ? `[ ${v.length} items ]` : `{ ${Object.keys(v).length} keys }`
  return String(v)
}

function setAtPath(obj, path, value) {
  if (path.length === 0) return value
  const [head, ...rest] = path
  if (Array.isArray(obj)) {
    const copy = [...obj]
    copy[head] = setAtPath(copy[head], rest, value)
    return copy
  }
  return { ...obj, [head]: setAtPath(obj[head] ?? {}, rest, value) }
}

function coerceValue(str, original) {
  if (typeof original === 'number') { const n = Number(str); return isNaN(n) ? str : n }
  if (typeof original === 'boolean') return str === 'true'
  return str
}

// ── ComfyUI node info helpers ────────────────────────────────────────────────

function SearchableSelect({ options, value, onChange }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [hovered, setHovered] = useState(null)
  const triggerRef = useRef(null)
  const searchRef = useRef(null)
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0, flip: false, maxH: 240 })

  const filtered = query
    ? options.filter(o => String(o).toLowerCase().includes(query.toLowerCase()))
    : options

  function handleOpen() {
    if (triggerRef.current) {
      const r = triggerRef.current.getBoundingClientRect()
      const SEARCH_H = 38        // search box + padding
      const ITEM_H   = 27        // approx per item
      const PADDING  = 8         // bottom viewport margin
      const spaceBelow = window.innerHeight - r.bottom - PADDING
      const spaceAbove = r.top - PADDING
      const wantH = Math.min(240, SEARCH_H + filtered.length * ITEM_H)
      const flip  = spaceBelow < wantH && spaceAbove > spaceBelow
      const maxH  = Math.min(240, (flip ? spaceAbove : spaceBelow) - SEARCH_H - PADDING)
      setPos({
        top:    flip ? undefined : r.bottom + 2,
        bottom: flip ? window.innerHeight - r.top + 2 : undefined,
        left:   r.left,
        width:  r.width,
        flip,
        maxH:   Math.max(80, maxH),
      })
    }
    setOpen(true)
    setQuery('')
    setHovered(null)
  }

  useEffect(() => {
    if (open && searchRef.current) searchRef.current.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    function onDown(e) {
      const drop = document.querySelector('[data-ssd]')
      if (!triggerRef.current?.contains(e.target) && !drop?.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const triggerStyle = {
    flex: 1, padding: '4px 8px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
    border: '1px solid var(--accent, #7c6af7)',
    background: 'var(--bg)', color: 'var(--text)', outline: 'none',
    display: 'flex', alignItems: 'center', userSelect: 'none',
  }

  return (
    <>
      <div ref={triggerRef} style={triggerStyle} onClick={handleOpen}>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {String(value ?? '')}
        </span>
        <span style={{ fontSize: 9, marginLeft: 6, opacity: 0.5, flexShrink: 0 }}>▼</span>
      </div>
      {open && createPortal(
        <div data-ssd style={{
          position: 'fixed',
          top: pos.top, bottom: pos.bottom, left: pos.left,
          width: Math.max(pos.width, 220),
          zIndex: 9999, background: '#0d0d1a',
          border: '1px solid var(--accent, #7c6af7)', borderRadius: 4,
          boxShadow: '0 6px 24px #000a', overflow: 'hidden',
          display: 'flex', flexDirection: pos.flip ? 'column-reverse' : 'column',
        }}>
          <div style={{ padding: '5px 5px 3px', flexShrink: 0 }}>
            <input
              ref={searchRef}
              type="text"
              placeholder="Search…"
              value={query}
              onChange={e => { setQuery(e.target.value); setHovered(null) }}
              onKeyDown={e => { if (e.key === 'Escape') setOpen(false) }}
              style={{
                width: '100%', boxSizing: 'border-box', padding: '4px 8px',
                borderRadius: 3, border: '1px solid var(--border)',
                background: '#1a1a2e', color: 'var(--text)', fontSize: 11, outline: 'none',
              }}
            />
          </div>
          <div style={{ maxHeight: pos.maxH, overflowY: 'auto' }}>
            {filtered.length === 0 ? (
              <div style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 11 }}>No matches</div>
            ) : filtered.map(opt => {
              const s = String(opt)
              const selected = s === String(value)
              return (
                <div
                  key={s}
                  onMouseDown={e => { e.preventDefault(); onChange(s); setOpen(false) }}
                  onMouseEnter={() => setHovered(s)}
                  onMouseLeave={() => setHovered(null)}
                  style={{
                    padding: '5px 10px', fontSize: 12, cursor: 'pointer',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    color: selected ? 'var(--accent, #7c6af7)' : 'var(--text)',
                    background: hovered === s || selected ? '#ffffff12' : 'transparent',
                  }}
                >{s}</div>
              )
            })}
          </div>
        </div>,
        document.body
      )}
    </>
  )
}

function getInputSpec(nodeInfo, class_type, input_key) {
  if (!nodeInfo || !class_type || !input_key) return null
  const node = nodeInfo[class_type]
  if (!node) return null
  return node.input?.required?.[input_key] ?? node.input?.optional?.[input_key] ?? null
}

function SmartInput({ spec, value, onChange, inputKey = '' }) {
  const inputStyle = {
    flex: 1, padding: '4px 8px', borderRadius: 4, fontSize: 12,
    border: '1px solid var(--accent, #7c6af7)',
    background: 'var(--bg)', color: 'var(--text)', outline: 'none',
  }

  if (!spec) {
    return (
      <input
        value={String(value ?? '')}
        onChange={e => onChange(coerceValue(e.target.value, value))}
        style={{ ...inputStyle, fontFamily: 'monospace' }}
      />
    )
  }

  const [typeOrOpts, opts = {}] = spec

  // Dropdown: first element is an array of option strings
  if (Array.isArray(typeOrOpts)) {
    return <SearchableSelect options={typeOrOpts} value={value} onChange={onChange} />
  }

  if (typeOrOpts === 'INT') {
    const isSeed = /seed/i.test(inputKey)
    return (
      <div style={{ display: 'flex', flex: 1, gap: 4, alignItems: 'center' }}>
        <input
          type="number"
          value={value ?? 0}
          min={opts.min} max={opts.max} step={opts.step ?? 1}
          onChange={e => { const n = parseInt(e.target.value, 10); onChange(isNaN(n) ? value : n) }}
          style={{ ...inputStyle, minWidth: 0 }}
        />
        {isSeed && (
          <button
            onClick={() => onChange(Math.floor(Math.random() * 2 ** 32))}
            title="Random seed"
            style={{
              background: 'var(--bg-hover)', border: '1px solid var(--border)',
              borderRadius: 4, cursor: 'pointer', fontSize: 14, padding: '3px 6px',
              flexShrink: 0, lineHeight: 1, color: 'var(--text)',
            }}
          >🎲</button>
        )}
      </div>
    )
  }

  if (typeOrOpts === 'FLOAT') {
    return (
      <input
        type="number"
        value={value ?? 0}
        min={opts.min} max={opts.max} step={opts.step ?? 0.01}
        onChange={e => { const n = parseFloat(e.target.value); onChange(isNaN(n) ? value : n) }}
        style={inputStyle}
      />
    )
  }

  if (typeOrOpts === 'BOOLEAN') {
    return (
      <label style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
        <input
          type="checkbox"
          checked={!!value}
          onChange={e => onChange(e.target.checked)}
          style={{ width: 15, height: 15, accentColor: 'var(--accent, #7c6af7)', cursor: 'pointer' }}
        />
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{value ? 'true' : 'false'}</span>
      </label>
    )
  }

  if (typeOrOpts === 'STRING' && opts.multiline) {
    return (
      <textarea
        value={String(value ?? '')}
        onChange={e => onChange(e.target.value)}
        rows={3}
        style={{ ...inputStyle, fontFamily: 'monospace', resize: 'vertical' }}
      />
    )
  }

  // STRING (single-line) or unknown
  return (
    <input
      value={String(value ?? '')}
      onChange={e => onChange(e.target.value)}
      style={{ ...inputStyle, fontFamily: 'monospace' }}
    />
  )
}

// ── JSON panel with search + editing ────────────────────────────────────────

function JsonPanel({ json, onChange, favorites = [], onToggleFavorite }) {
  const [editedJson, _setEditedJson] = useState(() => JSON.parse(JSON.stringify(json)))
  const jsonRef = useRef(editedJson)
  const [query, setQuery] = useState('')
  const [searchMode, setSearchMode] = useState('values') // 'values' | 'keys'
  const [editingIdx, setEditingIdx] = useState(null)
  const [editingVal, setEditingVal] = useState('')

  // Reset when a new json object is passed (different output / tab switch)
  useEffect(() => {
    const fresh = JSON.parse(JSON.stringify(json))
    jsonRef.current = fresh
    _setEditedJson(fresh)
    setQuery('')
    setEditingIdx(null)
    setSearchMode('values')
  }, [json])

  function setEditedJson(val) {
    jsonRef.current = val
    _setEditedJson(val)
    onChange?.(val)
  }

  const originalStr = JSON.stringify(json)
  const dirty = JSON.stringify(editedJson) !== originalStr

  // Called by @uiw/react-json-view when a value is edited in the tree
  function handleTreeChange({ value, keyName, parentValue }) {
    if (parentValue != null && keyName != null) {
      parentValue[keyName] = value   // mutate the live reference
    }
    setEditedJson(JSON.parse(JSON.stringify(jsonRef.current)))
  }

  function startSearchEdit(i, m) {
    setEditingIdx(i)
    setEditingVal(String(m.value))
  }

  function commitSearchEdit(m) {
    const coerced = coerceValue(editingVal, m.value)
    setEditedJson(setAtPath(jsonRef.current, m.path, coerced))
    setEditingIdx(null)
  }

  const trimmed = query.trim()
  const matches = trimmed
    ? (searchMode === 'keys' ? collectKeyMatches(editedJson, trimmed) : collectMatches(editedJson, trimmed))
    : null

  const btnStyle = (active) => ({
    padding: '3px 9px', borderRadius: 4, fontSize: 11, cursor: 'pointer',
    border: '1px solid var(--border)',
    background: active ? 'var(--bg-hover)' : 'transparent',
    color: active ? 'var(--text)' : 'var(--text-muted)',
    flexShrink: 0,
  })

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, alignItems: 'center' }}>
        <input
          type="text"
          placeholder={searchMode === 'keys' ? 'Search property names…' : 'Search values…'}
          value={query}
          onChange={e => { setQuery(e.target.value); setEditingIdx(null) }}
          style={{
            flex: 1, boxSizing: 'border-box', padding: '5px 10px',
            borderRadius: 4, border: '1px solid var(--border)',
            background: 'var(--bg)', color: 'var(--text)', fontSize: 12, outline: 'none',
          }}
        />
        <button style={btnStyle(searchMode === 'values')} onClick={() => { setSearchMode('values'); setEditingIdx(null) }}>Values</button>
        <button style={btnStyle(searchMode === 'keys')}   onClick={() => { setSearchMode('keys');   setEditingIdx(null) }}>Keys</button>
        {dirty && (
          <button
            onClick={() => { const fresh = JSON.parse(JSON.stringify(json)); jsonRef.current = fresh; _setEditedJson(fresh); onChange?.(fresh) }}
            className="modal-btn modal-btn--cancel"
            style={{ flexShrink: 0, fontSize: 11, padding: '3px 8px' }}
          >Reset</button>
        )}
      </div>

      <div style={{ borderRadius: 6, border: `1px solid ${dirty ? 'var(--accent, #7c6af7)' : 'var(--border)'}`,
                    background: '#1a1a2e', maxHeight: 360, overflow: 'auto' }}>
        {matches ? (
          matches.length === 0 ? (
            <div style={{ padding: 16, color: 'var(--text-muted)', fontSize: 12 }}>No matches.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'monospace' }}>
              <tbody>
                {matches.map((m, i) => {
                  const pathStr    = m.path.join('.')
                  const isPrimitive = typeof m.value !== 'object' || m.value === null
                  const isEditing  = editingIdx === i && isPrimitive
                  // Favoritable = path matches [nodeId, 'inputs', inputKey]
                  const canFav    = m.path.length >= 3 && m.path[1] === 'inputs' && typeof m.path[2] === 'string'
                  const nodeId    = canFav ? String(m.path[0]) : null
                  const classType = canFav ? (editedJson[m.path[0]]?.class_type ?? null) : null
                  const isFav     = classType && favorites.some(f => f.node_id === nodeId && f.class_type === classType && f.input_key === m.path[2])

                  // Build highlighted path (key mode: highlight matching segment; value mode: path is plain)
                  const pathParts = m.path.map(String)
                  const pathCell  = searchMode === 'keys' ? (
                    pathParts.map((seg, pi) => {
                      const lo = seg.toLowerCase().indexOf(trimmed.toLowerCase())
                      if (lo < 0) return <span key={pi}>{pi > 0 ? '.' : ''}{seg}</span>
                      return (
                        <span key={pi}>
                          {pi > 0 ? '.' : ''}
                          {seg.slice(0, lo)}
                          <mark style={{ background: '#facc1580', color: '#fef08a', borderRadius: 2, padding: '0 1px' }}>
                            {seg.slice(lo, lo + trimmed.length)}
                          </mark>
                          {seg.slice(lo + trimmed.length)}
                        </span>
                      )
                    })
                  ) : pathStr

                  // Build highlighted value (value mode only; key mode shows summary)
                  let valueCell
                  if (searchMode === 'keys') {
                    valueCell = (
                      <span style={{ color: isPrimitive ? '#e2e8f0' : '#ffffff50', fontStyle: isPrimitive ? 'normal' : 'italic' }}
                            onClick={() => isPrimitive && !isEditing && startSearchEdit(i, m)}>
                        {isPrimitive ? String(m.value) : summariseValue(m.value)}
                      </span>
                    )
                  } else {
                    const valStr = String(m.value)
                    const lo     = valStr.toLowerCase().indexOf(trimmed.toLowerCase())
                    const before = valStr.slice(0, lo)
                    const match  = valStr.slice(lo, lo + trimmed.length)
                    const after  = valStr.slice(lo + trimmed.length)
                    valueCell = (
                      <span style={{ cursor: 'text' }} onClick={() => !isEditing && startSearchEdit(i, m)}>
                        {before}
                        <mark style={{ background: '#facc1580', color: '#fef08a', borderRadius: 2, padding: '0 1px' }}>{match}</mark>
                        {after}
                      </span>
                    )
                  }

                  return (
                    <tr key={i} style={{ borderBottom: '1px solid #ffffff10' }}>
                      <td style={{ padding: '3px 6px', width: 22, textAlign: 'center' }}>
                        {classType && (
                          <button
                            onClick={e => { e.stopPropagation(); onToggleFavorite?.(nodeId, classType, m.path[2]) }}
                            title={isFav ? `Remove from favorites (${classType} › ${m.path[2]})` : `Add to favorites (${classType} › ${m.path[2]})`}
                            style={{ background: 'none', border: 'none', cursor: 'pointer',
                                     color: isFav ? '#facc15' : '#ffffff30', fontSize: 13, padding: 0,
                                     lineHeight: 1, transition: 'color 0.1s' }}
                          >{isFav ? '★' : '☆'}</button>
                        )}
                      </td>
                      <td style={{ padding: '5px 8px', color: '#7ecfff', verticalAlign: 'middle',
                                   whiteSpace: 'nowrap', width: '40%', maxWidth: 220,
                                   overflow: 'hidden', textOverflow: 'ellipsis' }}
                          title={pathStr}>{pathCell}</td>
                      <td style={{ padding: '4px 8px', color: '#e2e8f0', wordBreak: 'break-all' }}>
                        {isEditing ? (
                          <input
                            autoFocus
                            value={editingVal}
                            onChange={e => setEditingVal(e.target.value)}
                            onBlur={() => commitSearchEdit(m)}
                            onKeyDown={e => {
                              if (e.key === 'Enter') { e.preventDefault(); commitSearchEdit(m) }
                              if (e.key === 'Escape') setEditingIdx(null)
                            }}
                            style={{
                              width: '100%', boxSizing: 'border-box', padding: '2px 6px',
                              borderRadius: 3, border: '1px solid var(--accent, #7c6af7)',
                              background: '#0d0d1a', color: '#e2e8f0', fontSize: 11,
                              fontFamily: 'monospace', outline: 'none',
                            }}
                          />
                        ) : valueCell}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )
        ) : (
          <JsonView
            value={editedJson}
            editable
            onChange={handleTreeChange}
            style={{ ...darkTheme, padding: 14, fontSize: 12, lineHeight: 1.6,
                     background: 'transparent', fontFamily: 'monospace' }}
            collapsed={2}
            enableClipboard
            displayDataTypes={false}
            displayObjectSize={false}
          />
        )}
      </div>
    </div>
  )
}

// ── Favorites tab ────────────────────────────────────────────────────────────

function FavoritesTab({ editedJson, favorites, onUpdate, onRemoveFavorite, nodeInfo }) {
  if (!editedJson || typeof editedJson !== 'object') {
    return <div style={{ padding: 24, color: 'var(--text-muted)', fontSize: 13 }}>No prompt loaded.</div>
  }

  // Collect {nodeId, class_type, title, input_key, value, path} for each favorited param in this prompt
  const matches = []
  for (const fav of favorites) {
    const node = editedJson[fav.node_id]
    if (!node || typeof node !== 'object' || !node.class_type) continue
    if (fav.class_type !== node.class_type) continue
    const val = node.inputs?.[fav.input_key]
    if (val === undefined) continue
    matches.push({
      nodeId: fav.node_id, class_type: node.class_type,
      title: node._meta?.title || node.class_type,
      input_key: fav.input_key,
      value: val,
      path: [fav.node_id, 'inputs', fav.input_key],
    })
  }

  if (matches.length === 0) {
    return (
      <div style={{ padding: 24, color: 'var(--text-muted)', fontSize: 13, textAlign: 'center', lineHeight: 1.8 }}>
        {favorites.length === 0
          ? <>No favorites yet.<br />Search for a param in the Prompt (API) tab and click ☆ to add it.</>
          : 'None of your favorited params appear in this prompt.'}
      </div>
    )
  }

  const byNode = {}
  for (const m of matches) {
    const key = `${m.nodeId}::${m.class_type}`
    if (!byNode[key]) byNode[key] = { nodeId: m.nodeId, title: m.title, class_type: m.class_type, items: [] }
    byNode[key].items.push(m)
  }

  return (
    <div style={{ padding: '2px 0' }}>
      {Object.entries(byNode).map(([gkey, group]) => (
        <div key={gkey} style={{ marginBottom: 20 }}>
          <div style={{ marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>
              {group.title}
            </span>
            {group.title !== group.class_type && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>
                {group.class_type}
              </span>
            )}
            <span style={{ fontSize: 10, color: 'var(--text-dim, #ffffff30)',
                           marginLeft: 6, fontFamily: 'monospace' }}>
              #{group.nodeId}
            </span>
          </div>
          {group.items.map(m => {
            const spec = getInputSpec(nodeInfo, m.class_type, m.input_key)
            return (
              <div key={`${m.nodeId}.${m.input_key}`}
                   style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <button
                  onClick={() => onRemoveFavorite(m.nodeId, m.class_type, m.input_key)}
                  title="Remove from favorites"
                  style={{ background: 'none', border: 'none', cursor: 'pointer',
                           color: '#facc15', fontSize: 14, padding: 0, flexShrink: 0, lineHeight: 1 }}
                >★</button>
                <span style={{ fontSize: 12, color: 'var(--text-muted)', width: 160,
                               flexShrink: 0, fontFamily: 'monospace', overflow: 'hidden',
                               textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={m.input_key}>
                  {m.input_key}
                </span>
                <SmartInput
                  spec={spec}
                  value={m.value}
                  onChange={v => onUpdate(setAtPath(editedJson, m.path, v))}
                  inputKey={m.input_key}
                />
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

// ── Workflow detail modal ────────────────────────────────────────────────────

// Module-level cache so node_info is only fetched once per page load
let _nodeInfoCache = null

function WorkflowModal({ output, onClose, onPrev, onNext, hasPrev, hasNext, onDelete, inTrash, onRestore, onLikeToggle, onNsfwToggle }) {
  const [data, setData] = useState(null)
  const [tab, setTab] = useState('favorites')
  const isVideo = (output.mime_type || '').startsWith('video/')
  const videoRef = useRef(null)
  const [comfyEndpoint, setComfyEndpoint] = useState('')
  const [editedPrompt, setEditedPrompt] = useState(null)
  const [renderStatus, setRenderStatus] = useState(null) // null | 'sending' | {ok, msg}
  const [favorites, setFavorites] = useState([])
  const [nodeInfo, setNodeInfo] = useState(_nodeInfoCache)
  const [mediaHidden, setMediaHidden] = useState(false)

  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(d => setComfyEndpoint(d.comfyui_endpoint || '')).catch(() => {})
    fetch('/api/prompt-favorites').then(r => r.json()).then(d => setFavorites(d.favorites || [])).catch(() => {})
    if (!_nodeInfoCache) {
      fetch('/api/comfyui-cache/node_info')
        .then(r => r.json())
        .then(d => { if (d.data) { _nodeInfoCache = d.data; setNodeInfo(d.data) } })
        .catch(() => {})
    }
  }, [])

  async function handleToggleFavorite(node_id, class_type, input_key) {
    const isFav = favorites.some(f => f.node_id === node_id && f.class_type === class_type && f.input_key === input_key)
    const method = isFav ? 'DELETE' : 'POST'
    await fetch('/api/prompt-favorites', {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ node_id, class_type, input_key }),
    })
    setFavorites(prev => isFav
      ? prev.filter(f => !(f.node_id === node_id && f.class_type === class_type && f.input_key === input_key))
      : [...prev, { node_id, class_type, input_key }]
    )
  }

  function handleRemoveFavorite(node_id, class_type, input_key) {
    handleToggleFavorite(node_id, class_type, input_key)
  }

  useEffect(() => {
    fetch(`/api/outputs/${output.id}/workflow`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData({}))
    setEditedPrompt(null)
    setRenderStatus(null)
  }, [output.id])

  async function handleRender() {
    const prompt = editedPrompt ?? data?.prompt
    if (!prompt || !comfyEndpoint) return
    setRenderStatus('sending')
    try {
      const r = await fetch(`${comfyEndpoint}/prompt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const d = await r.json()
      if (r.ok && d.prompt_id) {
        setRenderStatus({ ok: true, msg: `Queued: ${d.prompt_id.slice(0, 8)}` })
      } else {
        setRenderStatus({ ok: false, msg: d.error || `HTTP ${r.status}` })
      }
    } catch (e) {
      setRenderStatus({ ok: false, msg: e.message })
    }
  }

  useEffect(() => {
    function onKey(e) {
      const inInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable
      if (e.key === 'Escape') { onClose(); return }
      if (inInput) return
      if (e.key === 'ArrowLeft'  && hasPrev) { onPrev(); return }
      if (e.key === 'ArrowRight' && hasNext) { onNext(); return }
      if (e.key === 'Delete' && !inTrash && onDelete) { onDelete(); return }
      if ((e.key === ' ' || e.key === 'Enter') && isVideo && videoRef.current) {
        e.preventDefault()
        videoRef.current.paused ? videoRef.current.play() : videoRef.current.pause()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, onPrev, onNext, hasPrev, hasNext, isVideo, onDelete, inTrash])

  const json = data?.[tab]
  const tabs = [
    { key: 'favorites', label: 'Parameters',    available: !!data?.prompt   },
    { key: 'prompt',    label: 'Prompt (API)',   available: !!data?.prompt   },
    { key: 'workflow',  label: 'Workflow graph', available: !!data?.workflow },
  ]

  return createPortal(
    <div className="scene-page-overlay">
      <Header isLoading={false} />
      <div className="video-page-wrap">
        <div
          className="video-page-content"
          style={{ display: 'flex', flexDirection: 'column', padding: 0 }}
        >
        {/* header: back + nav + filename */}
        <div className="video-modal-header" style={{ margin: 0, padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)', gap: 8 }}>
          <button className="video-page-back-btn" onClick={onClose} title="Back to list">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12"/>
              <polyline points="12 19 5 12 12 5"/>
            </svg>
            <span>Back</span>
          </button>
          <button className="modal-btn modal-btn--cancel" style={{ flexShrink: 0, padding: '3px 10px' }}
                  disabled={!hasPrev} onClick={onPrev}>←</button>
          <button className="modal-btn modal-btn--cancel" style={{ flexShrink: 0, padding: '3px 10px' }}
                  disabled={!hasNext} onClick={onNext}>→</button>
          <span className="video-modal-title" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{output.filename}</span>
        </div>

        {/* action bar */}
        <div style={{
          padding: '8px 16px', borderBottom: '1px solid var(--border-subtle)',
          display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, flexWrap: 'wrap',
        }}>
          <a
            href={`/output_image/${output.id}`}
            download={output.filename}
            className="modal-btn modal-btn--cancel"
            style={{ flexShrink: 0, textDecoration: 'none' }}
            onClick={e => e.stopPropagation()}
          >Download</a>
          {!inTrash && data?.prompt && (
            <>
              <button
                className="modal-btn modal-btn--save"
                style={{ flexShrink: 0 }}
                disabled={!comfyEndpoint || renderStatus === 'sending'}
                title={!comfyEndpoint ? 'Set ComfyUI endpoint in Config first' : ''}
                onClick={handleRender}
              >{renderStatus === 'sending' ? 'Sending…' : 'Render to ComfyUI'}</button>
              {renderStatus && renderStatus !== 'sending' && (
                <span style={{ fontSize: 12, flexShrink: 0,
                               color: renderStatus.ok ? 'var(--accent, #7c6af7)' : 'var(--error, #e55)' }}>
                  {renderStatus.msg}
                </span>
              )}
            </>
          )}
          <div style={{ flex: 1 }} />
          {!inTrash && (
            <>
              <button
                className={`modal-btn output-modal-like-btn${output.liked ? ' output-modal-like-btn--active' : ''}`}
                style={{ flexShrink: 0 }}
                onClick={() => onLikeToggle(output)}
                title={output.liked ? 'Unlike' : 'Like — prevents deletion'}
              >♥ {output.liked ? 'Liked' : 'Like'}</button>
              <button
                className={`modal-btn output-modal-nsfw-btn${output.nsfw ? ' output-modal-nsfw-btn--active' : ''}`}
                style={{ flexShrink: 0 }}
                onClick={() => onNsfwToggle(output)}
                title={output.nsfw ? 'Un-flag NSFW' : 'Mark as NSFW'}
              >⚠ {output.nsfw ? 'NSFW' : 'NSFW?'}</button>
            </>
          )}
          {inTrash ? (
            <button className="modal-btn modal-btn--save" style={{ flexShrink: 0 }} onClick={onRestore}>Restore</button>
          ) : (
            <button
              className="modal-btn modal-btn--cancel"
              style={{ flexShrink: 0, color: 'var(--error, #e55)', opacity: output.liked ? 0.35 : 1 }}
              onClick={onDelete}
              disabled={!!output.liked}
              title={output.liked ? 'Unlike before deleting' : 'Delete (Del)'}
            >Delete</button>
          )}
        </div>

        {/* media */}
        {!mediaHidden && (
          <div style={{ background: '#000', lineHeight: 0, flexShrink: 0, position: 'relative' }}>
            {isVideo ? (
              <video
                ref={videoRef}
                src={`/output_image/${output.id}`}
                controls
                className="modal-video"
              />
            ) : (
              <img
                src={`/output_image/${output.id}`}
                alt={output.filename}
                className="modal-video"
                style={{ objectFit: 'contain' }}
              />
            )}
            <button
              onClick={() => setMediaHidden(true)}
              title="Hide media"
              style={{
                position: 'absolute', top: 6, right: 6,
                background: '#00000080', border: 'none', borderRadius: 4,
                color: '#ffffffcc', fontSize: 11, padding: '2px 7px',
                cursor: 'pointer', lineHeight: 1.6,
              }}
            >Hide</button>
          </div>
        )}
        {mediaHidden && (
          <div style={{ background: '#111', flexShrink: 0, display: 'flex',
                        alignItems: 'center', justifyContent: 'center', padding: '8px 16px' }}>
            <button
              onClick={() => setMediaHidden(false)}
              className="modal-btn modal-btn--cancel"
              style={{ fontSize: 12 }}
            >Show media</button>
          </div>
        )}

        {/* metadata + workflow */}
        <div style={{ flex: 1, overflow: 'auto', padding: '14px 20px 20px' }}>
          {/* meta row */}
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 12,
                        color: 'var(--text-muted)', marginBottom: 16, lineHeight: 1.8 }}>
            {output.width && output.height && (
              <span><b style={{ color: 'var(--text)' }}>Dimensions</b> {output.width} × {output.height}</span>
            )}
            <span><b style={{ color: 'var(--text)' }}>Size</b> {fmtBytes(output.file_size)}</span>
            <span><b style={{ color: 'var(--text)' }}>Type</b> {output.mime_type || '?'}</span>
            <span><b style={{ color: 'var(--text)' }}>Modified</b> {fmtDate(output.file_mtime)}</span>
            <CopyHash hash={output.sha256} />
            {inTrash && output.deleted_at && (
              <span style={{ color: 'var(--error, #e55)' }}><b>Deleted</b> {fmtDate(output.deleted_at)}</span>
            )}
          </div>

          {/* workflow tabs */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            {tabs.map(t => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                disabled={!t.available}
                style={{
                  padding: '4px 12px', borderRadius: 4, border: '1px solid var(--border)',
                  background: tab === t.key ? 'var(--bg-hover)' : 'transparent',
                  color: t.available ? 'var(--text)' : 'var(--text-dim)',
                  cursor: t.available ? 'pointer' : 'default', fontSize: 12,
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          {data === null ? (
            <div style={{ padding: 16, color: 'var(--text-muted)' }}>Loading…</div>
          ) : tab === 'favorites' ? (
            <FavoritesTab
              editedJson={editedPrompt ?? data?.prompt}
              favorites={favorites}
              onUpdate={setEditedPrompt}
              onRemoveFavorite={handleRemoveFavorite}
              nodeInfo={nodeInfo}
            />
          ) : json ? (
            tab === 'prompt' ? (
              <JsonPanel
                json={json}
                onChange={setEditedPrompt}
                favorites={favorites}
                onToggleFavorite={handleToggleFavorite}
              />
            ) : (
              <div style={{ borderRadius: 6, border: '1px solid var(--border)', background: '#1a1a2e',
                            maxHeight: 360, overflow: 'auto' }}>
                <JsonView
                  value={json}
                  style={{ ...darkTheme, padding: 14, fontSize: 12, lineHeight: 1.6,
                           background: 'transparent', fontFamily: 'monospace' }}
                  collapsed={2}
                  enableClipboard
                  displayDataTypes={false}
                  displayObjectSize={false}
                />
              </div>
            )
          ) : (
            <div style={{ padding: 16, color: 'var(--text-muted)' }}>No {tab} data embedded in this file.</div>
          )}
        </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

// ── Output card ──────────────────────────────────────────────────────────────

function OutputCard({ output, onClick, inTrash, onRestore, onDelete, onLikeToggle, onNsfwToggle }) {
  const [imgError, setImgError] = useState(false)
  const isImage = (output.mime_type || '').startsWith('image/')
  const isVideo = (output.mime_type || '').startsWith('video/')
  const thumbSrc = isVideo ? `/output_thumb/${output.id}` : `/output_image/${output.id}`

  return (
    <div className="output-card" onClick={() => onClick(output)} title={output.path}
         style={inTrash ? { opacity: 0.65 } : undefined}>
      <div className="output-card-thumb">
        {(isImage || isVideo) && !imgError ? (
          <img
            src={thumbSrc}
            alt={output.filename}
            onError={() => setImgError(true)}
            loading="lazy"
          />
        ) : (
          <div className="output-card-thumb-placeholder">?</div>
        )}
        {isVideo && !imgError && (
          <div className="output-card-play-badge">▶</div>
        )}
        {!inTrash && (
          <>
            <button
              className={`output-like-btn${output.liked ? ' output-like-btn--active' : ''}`}
              onClick={e => { e.stopPropagation(); onLikeToggle(output) }}
              title={output.liked ? 'Unlike' : 'Like'}
            >♥</button>
            <button
              className={`output-nsfw-btn${output.nsfw ? ' output-nsfw-btn--active' : ''}`}
              onClick={e => { e.stopPropagation(); onNsfwToggle(output) }}
              title={output.nsfw ? 'Un-flag NSFW' : 'Mark as NSFW'}
            >⚠</button>
            {onDelete && !output.liked && (
              <button
                className="output-nsfw-btn"
                style={{ color: 'var(--error, #e55)' }}
                onClick={e => { e.stopPropagation(); onDelete() }}
                title="Delete"
              >🗑</button>
            )}
          </>
        )}
      </div>
      <div className="output-card-body">
        <div className="output-card-name" title={output.filename}>{output.filename}</div>
        <div className="output-card-meta">
          {output.width && output.height && <span>{output.width}×{output.height}</span>}
          <span>{fmtBytes(output.file_size)}</span>
        </div>
        <div className="output-card-badges">
          {output.has_workflow && <span className="output-badge output-badge--wf">workflow</span>}
          {output.has_prompt   && <span className="output-badge output-badge--pr">prompt</span>}
          {inTrash && (
            <button
              className="modal-btn modal-btn--save"
              style={{ fontSize: 10, padding: '1px 6px', marginTop: 2 }}
              onClick={e => { e.stopPropagation(); onRestore(output) }}
            >Restore</button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Recycle bin view ─────────────────────────────────────────────────────────

function RecycleBinView({ hideNsfw }) {
  const [items, setItems]     = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected]   = useState(null)
  const [selectedIdx, setSelectedIdx] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [emptying, setEmptying]   = useState(false)
  const [sort, setSort]           = useState('deleted')
  const [dir, setDir]             = useState('desc')

  const visibleItems = hideNsfw ? items.filter(o => !o.nsfw) : items
  const hiddenCount  = items.length - visibleItems.length

  const toggleSort = (col) => {
    if (sort === col) setDir(d => d === 'desc' ? 'asc' : 'desc')
    else setSort(col)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`/api/outputs/trash?sort=${sort}&dir=${dir}`)
      const data = await r.json()
      setItems(data.outputs || [])
    } catch (e) {
      console.error('Failed to load trash', e)
    } finally {
      setLoading(false)
    }
  }, [sort, dir])

  useEffect(() => { load() }, [load])

  async function handleRestore(output) {
    await fetch(`/api/outputs/${output.id}/restore`, { method: 'POST' })
    setItems(prev => prev.filter(o => o.id !== output.id))
    if (selected?.id === output.id) { setSelected(null); setSelectedIdx(null) }
  }

  async function handleEmpty() {
    setEmptying(true)
    try {
      await fetch('/api/outputs/trash', { method: 'DELETE' })
      setItems([])
      setSelected(null)
      setSelectedIdx(null)
    } finally {
      setEmptying(false)
      setConfirming(false)
    }
  }

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* toolbar */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)',
                    display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          {loading ? '…' : `${visibleItems.length} deleted file${visibleItems.length !== 1 ? 's' : ''}`}
          {!loading && hiddenCount > 0 && (
            <span style={{ marginLeft: 6, fontStyle: 'italic' }}>
              ({hiddenCount} NSFW hidden)
            </span>
          )}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Sort:</span>
        <button onClick={() => toggleSort('deleted')}
          style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-subtle)',
                   background: sort === 'deleted' ? 'var(--accent)' : 'transparent', color: sort === 'deleted' ? '#fff' : 'var(--text)' }}>
          Deleted date {sort === 'deleted' ? (dir === 'desc' ? '↓' : '↑') : ''}
        </button>
        <button onClick={() => toggleSort('mtime')}
          style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-subtle)',
                   background: sort === 'mtime' ? 'var(--accent)' : 'transparent', color: sort === 'mtime' ? '#fff' : 'var(--text)' }}>
          File date {sort === 'mtime' ? (dir === 'desc' ? '↓' : '↑') : ''}
        </button>
        {items.length > 0 && (
          confirming ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, color: 'var(--error, #e55)' }}>
                Permanently delete {items.length} file{items.length !== 1 ? 's' : ''} and their data?
              </span>
              <button className="modal-btn modal-btn--cancel" onClick={() => setConfirming(false)} disabled={emptying}>
                Cancel
              </button>
              <button
                className="modal-btn modal-btn--save"
                style={{ background: 'var(--error, #e55)', borderColor: 'var(--error, #e55)' }}
                onClick={handleEmpty}
                disabled={emptying}
              >
                {emptying ? 'Deleting…' : 'Yes, delete permanently'}
              </button>
            </div>
          ) : (
            <button
              className="modal-btn modal-btn--cancel"
              style={{ color: 'var(--error, #e55)', borderColor: 'var(--error, #e55)' }}
              onClick={() => setConfirming(true)}
            >
              Empty Recycle Bin
            </button>
          )
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {loading && (
          <div style={{ padding: 32, color: 'var(--text-muted)', textAlign: 'center' }}>Loading…</div>
        )}
        {!loading && visibleItems.length === 0 && (
          <div style={{ padding: 32, color: 'var(--text-muted)', textAlign: 'center' }}>
            {hiddenCount > 0 ? 'No non-NSFW deleted files. Unlock the NSFW tab to view hidden items.' : 'Recycle bin is empty.'}
          </div>
        )}
        <div className="outputs-grid">
          {visibleItems.map((o, i) => (
            <OutputCard
              key={o.id}
              output={o}
              inTrash
              onClick={() => { setSelected(o); setSelectedIdx(i) }}
              onRestore={handleRestore}
            />
          ))}
        </div>
      </div>

      {selected && (
        <WorkflowModal
          output={selected}
          inTrash
          onClose={() => { setSelected(null); setSelectedIdx(null) }}
          hasPrev={selectedIdx > 0}
          hasNext={selectedIdx < visibleItems.length - 1}
          onPrev={() => { const i = selectedIdx - 1; setSelected(visibleItems[i]); setSelectedIdx(i) }}
          onNext={() => { const i = selectedIdx + 1; setSelected(visibleItems[i]); setSelectedIdx(i) }}
          onRestore={() => handleRestore(selected)}
        />
      )}
    </div>
  )
}

// ── Main outputs view ────────────────────────────────────────────────────────

function OutputsView() {
  const [outputs, setOutputs]   = useState([])
  const [total, setTotal]       = useState(null)
  const [wfFilter, setWfFilter]     = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [sort, setSort]             = useState('desc')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch]           = useState('')
  const debounceRef = useRef(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isEmpty, setIsEmpty]   = useState(false)
  const [selected, setSelected]   = useState(null)
  const [selectedIdx, setSelectedIdx] = useState(null)

  const pageRef       = useRef(1)
  const hasMoreRef    = useRef(true)
  const loadingRef    = useRef(false)
  const fetchGenRef   = useRef(0)
  const scrollRef     = useRef(null)
  const nearBottomRef = useRef(false)

  useEffect(() => {
    fetchGenRef.current += 1
    setOutputs([])
    setIsEmpty(false)
    setTotal(null)
    pageRef.current = 1
    hasMoreRef.current = true
    loadingRef.current = false
  }, [wfFilter, typeFilter, sort, search])

  const loadNext = useCallback(async () => {
    if (loadingRef.current || !hasMoreRef.current) return
    loadingRef.current = true
    const gen = fetchGenRef.current
    setIsLoading(true)
    try {
      const params = new URLSearchParams({ page: pageRef.current, limit: PAGE_SIZE })
      if (wfFilter)   params.set('workflow', wfFilter)
      if (typeFilter) params.set('type', typeFilter)
      if (search)     params.set('search', search)
      params.set('sort', sort)
      const r = await fetch(`/api/outputs?${params}`)
      if (!r.ok) throw new Error('fetch failed')
      const data = await r.json()
      if (fetchGenRef.current !== gen) return
      if (data.outputs.length === 0 && pageRef.current === 1) setIsEmpty(true)
      setTotal(data.total)
      hasMoreRef.current = data.outputs.length === PAGE_SIZE
      pageRef.current += 1
      setOutputs(prev => [...prev, ...data.outputs])
    } catch (e) {
      console.error('Failed to load outputs', e)
    } finally {
      if (fetchGenRef.current === gen) {
        loadingRef.current = false
        setIsLoading(false)
        if (nearBottomRef.current && hasMoreRef.current) loadNext()
      }
    }
  }, [wfFilter, typeFilter, sort, search])

  useEffect(() => { loadNext() }, [loadNext])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    function onScroll() {
      const { scrollTop, scrollHeight, clientHeight } = el
      nearBottomRef.current = scrollHeight - scrollTop - clientHeight < 800
      if (nearBottomRef.current) loadNext()
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => el.removeEventListener('scroll', onScroll)
  }, [loadNext])

  function handleDelete(output) {
    if (output.liked) return
    fetch(`/api/outputs/${output.id}/delete`, { method: 'POST' })
    const idx = outputs.findIndex(o => o.id === output.id)
    const next = outputs.filter(o => o.id !== output.id)
    setOutputs(next)
    setTotal(t => (t ?? 1) - 1)
    if (selected?.id === output.id) {
      if (next.length === 0) {
        setSelected(null)
        setSelectedIdx(null)
      } else {
        const newIdx = Math.min(idx, next.length - 1)
        setSelected(next[newIdx])
        setSelectedIdx(newIdx)
      }
    }
  }

  function handleLikeToggle(output) {
    const newLiked = !output.liked
    fetch(`/api/outputs/${output.id}/${newLiked ? 'like' : 'unlike'}`, { method: 'POST' })
    const updated = { ...output, liked: newLiked }
    setOutputs(prev => prev.map(o => o.id === output.id ? updated : o))
    if (selected?.id === output.id) setSelected(updated)
  }

  function handleNsfwToggle(output) {
    const newNsfw = !output.nsfw
    fetch(`/api/outputs/${output.id}/${newNsfw ? 'nsfw' : 'unnsfw'}`, { method: 'POST' })
    if (newNsfw) {
      // Remove immediately from the outputs list
      const idx = outputs.findIndex(o => o.id === output.id)
      const next = outputs.filter(o => o.id !== output.id)
      setOutputs(next)
      setTotal(t => (t ?? 1) - 1)
      if (selected?.id === output.id) {
        if (next.length === 0) { setSelected(null); setSelectedIdx(null) }
        else { const i = Math.min(idx, next.length - 1); setSelected(next[i]); setSelectedIdx(i) }
      }
    } else {
      const updated = { ...output, nsfw: false }
      setOutputs(prev => prev.map(o => o.id === output.id ? updated : o))
      if (selected?.id === output.id) setSelected(updated)
    }
  }

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* toolbar */}
      <div style={{
        padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)',
        display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
      }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 13, flexShrink: 0 }}>
          {total == null ? '…' : `${total} file${total !== 1 ? 's' : ''}`}
        </span>
        <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
          <input
            type="text"
            placeholder="Search workflow/prompt…"
            value={searchInput}
            onChange={e => {
              const v = e.target.value
              setSearchInput(v)
              clearTimeout(debounceRef.current)
              debounceRef.current = setTimeout(() => setSearch(v.trim()), 350)
            }}
            style={{
              width: '100%', boxSizing: 'border-box',
              padding: searchInput ? '3px 26px 3px 10px' : '3px 10px',
              borderRadius: 4, fontSize: 12,
              border: '1px solid var(--border)', background: 'var(--bg)',
              color: 'var(--text)', outline: 'none',
            }}
          />
          {searchInput && (
            <button
              onClick={() => { setSearchInput(''); clearTimeout(debounceRef.current); setSearch('') }}
              style={{
                position: 'absolute', right: 4, top: '50%', transform: 'translateY(-50%)',
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--text-muted)', fontSize: 14, lineHeight: 1, padding: '0 2px',
              }}
            >×</button>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[['', 'All types'], ['image', 'Images'], ['video', 'Videos']].map(([val, label]) => (
            <button key={val} onClick={() => setTypeFilter(val)} style={{
              padding: '3px 10px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
              border: '1px solid var(--border)',
              background: typeFilter === val ? 'var(--bg-hover)' : 'transparent',
              color: typeFilter === val ? 'var(--text)' : 'var(--text-muted)',
            }}>{label}</button>
          ))}
        </div>
        <div style={{ width: 1, height: 16, background: 'var(--border)' }} />
        <div style={{ display: 'flex', gap: 4 }}>
          {[['', 'Any workflow'], ['yes', 'Has workflow'], ['no', 'No workflow']].map(([val, label]) => (
            <button key={val} onClick={() => setWfFilter(val)} style={{
              padding: '3px 10px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
              border: '1px solid var(--border)',
              background: wfFilter === val ? 'var(--bg-hover)' : 'transparent',
              color: wfFilter === val ? 'var(--text)' : 'var(--text-muted)',
            }}>{label}</button>
          ))}
        </div>
        <div style={{ width: 1, height: 16, background: 'var(--border)' }} />
        <button onClick={() => setSort(s => s === 'desc' ? 'asc' : 'desc')} style={{
          padding: '3px 10px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
          border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)',
        }}>
          Date {sort === 'desc' ? '↓' : '↑'}
        </button>
      </div>

      {/* scrollable grid */}
      <div ref={scrollRef} style={{ flex: 1, overflow: 'auto' }}>
        {isEmpty && (
          <div style={{ padding: 32, color: 'var(--text-muted)', textAlign: 'center' }}>
            No outputs found. Run <code>ltx2-build --config config.yaml --step scan-outputs</code> first.
          </div>
        )}
        <div className="outputs-grid">
          {outputs.map((o, i) => (
            <OutputCard key={o.id} output={o}
              onClick={() => { setSelected(o); setSelectedIdx(i) }}
              onLikeToggle={handleLikeToggle}
              onNsfwToggle={handleNsfwToggle}
            />
          ))}
        </div>
        {isLoading && (
          <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            Loading…
          </div>
        )}
        <div style={{ height: 1 }} />
      </div>

      {selected && (
        <WorkflowModal
          output={selected}
          onClose={() => { setSelected(null); setSelectedIdx(null) }}
          hasPrev={selectedIdx > 0}
          hasNext={selectedIdx < outputs.length - 1}
          onPrev={() => { const i = selectedIdx - 1; setSelected(outputs[i]); setSelectedIdx(i) }}
          onNext={() => { const i = selectedIdx + 1; setSelected(outputs[i]); setSelectedIdx(i) }}
          onDelete={() => handleDelete(selected)}
          onLikeToggle={handleLikeToggle}
          onNsfwToggle={handleNsfwToggle}
        />
      )}
    </div>
  )
}

// ── Liked view ───────────────────────────────────────────────────────────────

function LikedView() {
  const [items, setItems]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [selected, setSelected]     = useState(null)
  const [selectedIdx, setSelectedIdx] = useState(null)
  const [sort, setSort]             = useState('liked')
  const [dir, setDir]               = useState('desc')

  const toggleSort = (col) => {
    if (sort === col) setDir(d => d === 'desc' ? 'asc' : 'desc')
    else setSort(col)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`/api/outputs/liked?sort=${sort}&dir=${dir}`)
      const d = await r.json()
      setItems(d.outputs ?? [])
    } catch (e) {
      console.error('Failed to load liked outputs', e)
    } finally {
      setLoading(false)
    }
  }, [sort, dir])

  useEffect(() => { load() }, [load])

  function handleUnlike(output) {
    fetch(`/api/outputs/${output.id}/unlike`, { method: 'POST' })
    const next = items.filter(o => o.id !== output.id)
    setItems(next)
    if (selected?.id === output.id) {
      const idx = items.findIndex(o => o.id === output.id)
      if (next.length === 0) { setSelected(null); setSelectedIdx(null) }
      else { const i = Math.min(idx, next.length - 1); setSelected(next[i]); setSelectedIdx(i) }
    }
  }

  function handleNsfwToggle(output) {
    const newNsfw = !output.nsfw
    fetch(`/api/outputs/${output.id}/${newNsfw ? 'nsfw' : 'unnsfw'}`, { method: 'POST' })
    if (newNsfw) {
      const idx = items.findIndex(o => o.id === output.id)
      const next = items.filter(o => o.id !== output.id)
      setItems(next)
      if (selected?.id === output.id) {
        if (next.length === 0) { setSelected(null); setSelectedIdx(null) }
        else { const i = Math.min(idx, next.length - 1); setSelected(next[i]); setSelectedIdx(i) }
      }
    } else {
      const updated = { ...output, nsfw: false }
      setItems(prev => prev.map(o => o.id === output.id ? updated : o))
      if (selected?.id === output.id) setSelected(updated)
    }
  }

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)',
        display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
      }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          {loading ? '…' : `${items.length} liked file${items.length !== 1 ? 's' : ''}`}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Sort:</span>
        <button onClick={() => toggleSort('liked')}
          style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-subtle)',
                   background: sort === 'liked' ? 'var(--accent)' : 'transparent', color: sort === 'liked' ? '#fff' : 'var(--text)' }}>
          Liked date {sort === 'liked' ? (dir === 'desc' ? '↓' : '↑') : ''}
        </button>
        <button onClick={() => toggleSort('mtime')}
          style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-subtle)',
                   background: sort === 'mtime' ? 'var(--accent)' : 'transparent', color: sort === 'mtime' ? '#fff' : 'var(--text)' }}>
          File date {sort === 'mtime' ? (dir === 'desc' ? '↓' : '↑') : ''}
        </button>
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {!loading && items.length === 0 && (
          <div style={{ padding: 32, color: 'var(--text-muted)', textAlign: 'center' }}>
            No liked outputs yet. Click ♥ on any output to like it.
          </div>
        )}
        <div className="outputs-grid">
          {items.map((o, i) => (
            <OutputCard key={o.id} output={o}
              onClick={() => { setSelected(o); setSelectedIdx(i) }}
              onLikeToggle={handleUnlike}
              onNsfwToggle={handleNsfwToggle}
            />
          ))}
        </div>
      </div>

      {selected && (
        <WorkflowModal
          output={selected}
          onClose={() => { setSelected(null); setSelectedIdx(null) }}
          hasPrev={selectedIdx > 0}
          hasNext={selectedIdx < items.length - 1}
          onPrev={() => { const i = selectedIdx - 1; setSelected(items[i]); setSelectedIdx(i) }}
          onNext={() => { const i = selectedIdx + 1; setSelected(items[i]); setSelectedIdx(i) }}
          onDelete={null}
          onLikeToggle={handleUnlike}
          onNsfwToggle={handleNsfwToggle}
        />
      )}
    </div>
  )
}

// ── NSFW view ─────────────────────────────────────────────────────────────────

function NsfwView() {
  const [items, setItems]           = useState([])
  const [loading, setLoading]       = useState(true)
  const [selected, setSelected]     = useState(null)
  const [selectedIdx, setSelectedIdx] = useState(null)
  const [sort, setSort]             = useState('nsfw')
  const [dir, setDir]               = useState('desc')
  const [deleting, setDeleting]     = useState(null) // output.id being deleted

  const toggleSort = (col) => {
    if (sort === col) setDir(d => d === 'desc' ? 'asc' : 'desc')
    else setSort(col)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`/api/outputs/nsfw?sort=${sort}&dir=${dir}`)
      const d = await r.json()
      setItems(d.outputs ?? [])
    } catch (e) {
      console.error('Failed to load NSFW outputs', e)
    } finally {
      setLoading(false)
    }
  }, [sort, dir])

  useEffect(() => { load() }, [load])

  function handleUnflag(output) {
    fetch(`/api/outputs/${output.id}/unnsfw`, { method: 'POST' })
    const next = items.filter(o => o.id !== output.id)
    setItems(next)
    if (selected?.id === output.id) {
      const idx = items.findIndex(o => o.id === output.id)
      if (next.length === 0) { setSelected(null); setSelectedIdx(null) }
      else { const i = Math.min(idx, next.length - 1); setSelected(next[i]); setSelectedIdx(i) }
    }
  }

  function handleDelete(output) {
    if (output.liked) return
    setDeleting(output.id)
    fetch(`/api/outputs/${output.id}/delete`, { method: 'POST' })
      .then(() => {
        const idx = items.findIndex(o => o.id === output.id)
        const next = items.filter(o => o.id !== output.id)
        setItems(next)
        if (selected?.id === output.id) {
          if (next.length === 0) { setSelected(null); setSelectedIdx(null) }
          else { const i = Math.min(idx, next.length - 1); setSelected(next[i]); setSelectedIdx(i) }
        }
      })
      .catch(e => console.error('Failed to delete NSFW output', e))
      .finally(() => setDeleting(null))
  }

  function handleLikeToggle(output) {
    const newLiked = !output.liked
    fetch(`/api/outputs/${output.id}/${newLiked ? 'like' : 'unlike'}`, { method: 'POST' })
    const updated = { ...output, liked: newLiked }
    setItems(prev => prev.map(o => o.id === output.id ? updated : o))
    if (selected?.id === output.id) setSelected(updated)
  }

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)',
        display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
      }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          {loading ? '…' : `${items.length} NSFW file${items.length !== 1 ? 's' : ''}`}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Sort:</span>
        <button onClick={() => toggleSort('nsfw')}
          style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-subtle)',
                   background: sort === 'nsfw' ? 'var(--accent)' : 'transparent', color: sort === 'nsfw' ? '#fff' : 'var(--text)' }}>
          NSFW date {sort === 'nsfw' ? (dir === 'desc' ? '↓' : '↑') : ''}
        </button>
        <button onClick={() => toggleSort('mtime')}
          style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-subtle)',
                   background: sort === 'mtime' ? 'var(--accent)' : 'transparent', color: sort === 'mtime' ? '#fff' : 'var(--text)' }}>
          File date {sort === 'mtime' ? (dir === 'desc' ? '↓' : '↑') : ''}
        </button>
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {!loading && items.length === 0 && (
          <div style={{ padding: 32, color: 'var(--text-muted)', textAlign: 'center' }}>
            No NSFW-flagged outputs yet. Click ⚠ on any output to flag it.
          </div>
        )}
        <div className="outputs-grid">
          {items.map((o, i) => (
            <OutputCard key={o.id} output={o}
              onClick={() => { setSelected(o); setSelectedIdx(i) }}
              onDelete={() => handleDelete(o)}
              onNsfwToggle={handleUnflag}
              onLikeToggle={handleLikeToggle}
            />
          ))}
        </div>
      </div>

      {selected && (
        <WorkflowModal
          output={selected}
          onClose={() => { setSelected(null); setSelectedIdx(null) }}
          hasPrev={selectedIdx > 0}
          hasNext={selectedIdx < items.length - 1}
          onPrev={() => { const i = selectedIdx - 1; setSelected(items[i]); setSelectedIdx(i) }}
          onNext={() => { const i = selectedIdx + 1; setSelected(items[i]); setSelectedIdx(i) }}
          inTrash={false}
          onDelete={() => handleDelete(selected)}
          onNsfwToggle={handleUnflag}
          onLikeToggle={handleLikeToggle}
        />
      )}
    </div>
  )
}

// ── NSFW password gate ────────────────────────────────────────────────────────

function NsfwGate({ onUnlocked }) {
  const [pw, setPw]       = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy]   = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const r = await fetch('/api/config/nsfw-unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      })
      if (r.ok) { onUnlocked() }
      else { setError('Incorrect password'); setPw('') }
    } catch { setError('Request failed') }
    finally { setBusy(false) }
  }

  return (
    <div style={{
      flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <form onSubmit={handleSubmit} style={{
        display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'center',
        padding: 32, borderRadius: 10, border: '1px solid var(--border)',
        background: 'var(--bg-card, var(--bg))', minWidth: 260,
      }}>
        <div style={{ fontSize: 28 }}>⚠</div>
        <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)' }}>NSFW content</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>
          Enter the NSFW password to view this tab.
        </div>
        <input
          type="password"
          value={pw}
          onChange={e => { setPw(e.target.value); setError(null) }}
          placeholder="Password…"
          autoFocus
          style={{
            width: '100%', padding: '7px 12px', borderRadius: 6, fontSize: 13,
            border: `1px solid ${error ? 'var(--error, #e55)' : 'var(--border)'}`,
            background: 'var(--bg)', color: 'var(--text)', outline: 'none',
            boxSizing: 'border-box',
          }}
        />
        {error && <div style={{ fontSize: 12, color: 'var(--error, #e55)' }}>{error}</div>}
        <button
          type="submit"
          disabled={!pw || busy}
          className="modal-btn modal-btn--save"
          style={{ width: '100%', opacity: !pw ? 0.4 : 1 }}
        >{busy ? 'Checking…' : 'Unlock'}</button>
      </form>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function OutputsPage() {
  const [activeTab, setActiveTab]       = useState('outputs')
  const [nsfwUnlocked, setNsfwUnlocked] = useState(false)
  const { nsfwEnabled } = useContext(AppContext)

  const tabs = [
    ['outputs', 'Outputs'],
    ['liked', '♥ Liked'],
    ...(nsfwEnabled ? [['nsfw', '⚠ NSFW']] : []),
    ['trash', '🗑 Recycle Bin'],
  ]

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* tab bar */}
      <div style={{
        padding: '0 16px', borderBottom: '1px solid var(--border-subtle)',
        display: 'flex', gap: 0, flexShrink: 0,
      }}>
        {tabs.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            style={{
              padding: '10px 16px', fontSize: 13, cursor: 'pointer',
              border: 'none', borderBottom: activeTab === key ? '2px solid var(--accent, #7c6af7)' : '2px solid transparent',
              background: 'transparent',
              color: activeTab === key ? 'var(--text)' : 'var(--text-muted)',
              fontWeight: activeTab === key ? 600 : 400,
              marginBottom: -1,
            }}
          >{label}</button>
        ))}
      </div>

      {activeTab === 'outputs' ? <OutputsView />
        : activeTab === 'liked' ? <LikedView />
        : activeTab === 'nsfw'
          ? (nsfwUnlocked ? <NsfwView /> : <NsfwGate onUnlocked={() => setNsfwUnlocked(true)} />)
        : <RecycleBinView hideNsfw={nsfwEnabled && !nsfwUnlocked} />}
    </div>
  )
}
