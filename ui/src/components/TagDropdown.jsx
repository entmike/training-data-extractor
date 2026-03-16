import { useState, useEffect, useLayoutEffect, useRef } from 'react'

export default function TagDropdown({ position, suggestions = [], onSelect, onClose, sceneId }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const [adjustedTop, setAdjustedTop] = useState(position.top)
  const [fetchedSuggestions, setFetchedSuggestions] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const inputRef = useRef(null)
  const wrapRef = useRef(null)

  useLayoutEffect(() => {
    if (!wrapRef.current) return
    const rect = wrapRef.current.getBoundingClientRect()
    if (rect.bottom > window.innerHeight - 8) {
      setAdjustedTop(t => t - (rect.bottom - window.innerHeight + 8))
    }
  }, [])

  const allSuggestions = [...suggestions, ...fetchedSuggestions]
  
  // Deduplicate by tag, keeping the one with the highest score
  const deduped = new Map()
  for (const tag of allSuggestions) {
    const existing = deduped.get(tag.tag)
    if (!existing || (tag.score !== undefined && tag.score > existing.score)) {
      deduped.set(tag.tag, tag)
    }
  }
  
  const filtered = [...deduped.values()].filter(t =>
    t.tag.includes(query.toLowerCase()) ||
    (t.display_name || '').toLowerCase().includes(query.toLowerCase())
  )

  // If user typed something not in the list, offer it as a new tag
  const options = query.trim() && !allSuggestions.some(t => t.tag === query.toLowerCase())
    ? [{ tag: query.toLowerCase(), display_name: query.toLowerCase() }, ...filtered]
    : filtered

  useEffect(() => { inputRef.current?.focus() }, [])

  useEffect(() => {
    if (sceneId && position && fetchedSuggestions.length === 0) {
      setIsLoading(true)
      fetch(`/api/tags/suggestions/${sceneId}`)
        .then(r => r.json())
        .then(data => {
          if (data.suggestions) {
            setFetchedSuggestions(data.suggestions)
          }
          setIsLoading(false)
        })
        .catch(() => setIsLoading(false))
    }
  }, [sceneId, position])

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
      {isLoading && <div className="tag-dropdown-loading">Loading suggestions…</div>}
      {options.length > 0 && (
        <div className="tag-dropdown-list">
          {options.map((t, i) => (
            <div
              key={t.tag}
              className={`tag-dropdown-item${i === cursor ? ' tag-dropdown-item--active' : ''}`}
              onMouseDown={() => onSelect(t.tag)}
              onMouseEnter={() => setCursor(i)}
            >
              <span className="tag-dropdown-item-main">{t.display_name || t.tag}</span>
              {t.score !== undefined && t.score > 0 && (
                <span className="tag-dropdown-item-score">{t.score.toFixed(1)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
