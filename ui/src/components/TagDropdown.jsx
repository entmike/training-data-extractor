import { useState, useEffect, useLayoutEffect, useRef } from 'react'

export default function TagDropdown({ position, suggestions = [], onSelect, onClose }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const [adjustedTop, setAdjustedTop] = useState(position.top)
  const inputRef = useRef(null)
  const wrapRef = useRef(null)

  useLayoutEffect(() => {
    if (!wrapRef.current) return
    const rect = wrapRef.current.getBoundingClientRect()
    if (rect.bottom > window.innerHeight - 8) {
      setAdjustedTop(t => t - (rect.bottom - window.innerHeight + 8))
    }
  }, [])

  const filtered = suggestions.filter(t =>
    t.tag.includes(query.toLowerCase()) ||
    (t.display_name || '').toLowerCase().includes(query.toLowerCase())
  )

  // If user typed something not in the list, offer it as a new tag
  const options = query.trim() && !suggestions.some(t => t.tag === query.toLowerCase())
    ? [{ tag: query.toLowerCase(), display_name: query.toLowerCase() }, ...filtered]
    : filtered

  useEffect(() => { inputRef.current?.focus() }, [])

  useEffect(() => {
    function onMouseDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [onClose])

  function handleKey(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => Math.min(c + 1, options.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)) }
    else if (e.key === 'Enter') { if (options[cursor]) onSelect(options[cursor].tag) }
    else if (e.key === 'Escape') onClose()
  }

  return (
    <div
      ref={wrapRef}
      className="tag-dropdown"
      style={{ position: 'absolute', top: adjustedTop, left: position.left, zIndex: 2000 }}
    >
      <input
        ref={inputRef}
        className="tag-dropdown-input"
        value={query}
        placeholder="Add tag…"
        onChange={e => { setQuery(e.target.value); setCursor(0) }}
        onKeyDown={handleKey}
      />
      {options.length > 0 && (
        <div className="tag-dropdown-list">
          {options.map((t, i) => (
            <div
              key={t.tag}
              className={`tag-dropdown-item${i === cursor ? ' tag-dropdown-item--active' : ''}`}
              onMouseDown={() => onSelect(t.tag)}
              onMouseEnter={() => setCursor(i)}
            >
              {t.display_name || t.tag}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
