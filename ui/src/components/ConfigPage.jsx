import { useState, useEffect, useRef, useContext } from 'react'
import { createPortal } from 'react-dom'
import { AppContext } from '../context'

function fmtBytes(b) {
  if (b < 1024) return `${b} B`
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`
  return `${(b / 1024 ** 3).toFixed(2)} GB`
}

const CONFIG_FIELDS = [
  {
    key: 'comfyui_endpoint',
    label: 'ComfyUI API Endpoint',
    description: 'Base URL of your ComfyUI instance (e.g. http://localhost:8188)',
    placeholder: 'http://localhost:8188',
    type: 'url',
  },
  {
    key: 'nsfw_password',
    label: 'NSFW Tab Password',
    description: 'Set a password to enable the NSFW tab in Outputs. Leave blank to hide the tab entirely.',
    placeholder: 'Enter password…',
    type: 'password',
  },
]

const CACHE_SECTIONS = [
  {
    key: 'node_info',
    label: 'Node Info',
    description: 'ComfyUI node definitions (/object_info). Used for smart input controls in the Outputs editor.',
  },
  {
    key: 'models',
    label: 'Models',
    description: 'ComfyUI available models (/models).',
  },
]

function ConfigField({ field, value, onSave }) {
  const [draft, setDraft] = useState(value)
  const [status, setStatus] = useState(null) // 'saving' | 'saved' | 'error'
  const timerRef = useRef(null)

  useEffect(() => { setDraft(value) }, [value])

  async function handleSave() {
    setStatus('saving')
    try {
      const r = await fetch(`/api/config/${field.key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: draft }),
      })
      if (!r.ok) throw new Error()
      onSave(field.key, draft)
      setStatus('saved')
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setStatus(null), 2000)
    } catch {
      setStatus('error')
    }
  }

  const dirty = draft !== value

  return (
    <div style={{ marginBottom: 32 }}>
      <label style={{ display: 'block', fontWeight: 600, fontSize: 14,
                      color: 'var(--text)', marginBottom: 4 }}>
        {field.label}
      </label>
      {field.description && (
        <p style={{ margin: '0 0 8px', fontSize: 12, color: 'var(--text-muted)' }}>
          {field.description}
        </p>
      )}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          type={field.type || 'text'}
          value={draft}
          placeholder={field.placeholder}
          onChange={e => { setDraft(e.target.value); setStatus(null) }}
          onKeyDown={e => { if (e.key === 'Enter') handleSave() }}
          style={{
            flex: 1, padding: '7px 12px', borderRadius: 6, fontSize: 13,
            border: '1px solid var(--border)', background: 'var(--bg)',
            color: 'var(--text)', outline: 'none',
            boxShadow: dirty ? '0 0 0 2px var(--accent, #7c6af7)33' : 'none',
          }}
        />
        <button
          onClick={handleSave}
          disabled={!dirty || status === 'saving'}
          className="modal-btn modal-btn--save"
          style={{ flexShrink: 0, opacity: !dirty ? 0.4 : 1 }}
        >
          {status === 'saving' ? 'Saving…' : 'Save'}
        </button>
        {status === 'saved' && (
          <span style={{ fontSize: 12, color: 'var(--accent, #7c6af7)' }}>Saved</span>
        )}
        {status === 'error' && (
          <span style={{ fontSize: 12, color: 'var(--error, #e55)' }}>Error saving</span>
        )}
      </div>
    </div>
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

function PreviewCacheSection() {
  const [cacheSize, setCacheSize] = useState(null)   // null = unknown, false = clearing
  const [confirmOpen, setConfirmOpen] = useState(false)

  function refresh() {
    setCacheSize(null)
    fetch('/api/cache/previews')
      .then(r => r.json())
      .then(d => setCacheSize(d.size_bytes ?? 0))
      .catch(() => setCacheSize(0))
  }

  useEffect(refresh, [])

  async function clearCache() {
    setConfirmOpen(false)
    setCacheSize(false)
    await fetch('/api/cache/previews', { method: 'DELETE' })
    setCacheSize(0)
  }

  const sizeLabel = cacheSize === null ? '…'
    : cacheSize === false ? 'Clearing…'
    : fmtBytes(cacheSize)
  const canClear = cacheSize !== null && cacheSize !== false && cacheSize > 0

  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>
        Preview Cache
      </div>
      <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--text-muted)' }}>
        Cached scene/clip preview images on disk. Safe to clear — they regenerate on demand.
      </p>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          onClick={() => setConfirmOpen(true)}
          disabled={!canClear}
          className="modal-btn modal-btn--confirm"
          style={{ flexShrink: 0, background: canClear ? '#ef4444' : undefined }}
        >
          Clear Cache ({sizeLabel})
        </button>
      </div>

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

function OutputsCleanupSection() {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)   // null | { checked, removed, skipped_parent_missing } | { error }
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [preview, setPreview] = useState(null)  // null | 'loading' | { checked, would_remove, skipped_parent_missing } | { error }
  const [force, setForce] = useState(false)

  async function fetchCleanup(extra) {
    const r = await fetch('/api/outputs/cleanup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force, ...extra }),
    })
    const d = await r.json()
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`)
    return d
  }

  async function openConfirm() {
    setResult(null)
    setConfirmOpen(true)
    setPreview('loading')
    try {
      setPreview(await fetchCleanup({ dry_run: true }))
    } catch (e) {
      setPreview({ error: e.message })
    }
  }

  async function run() {
    setConfirmOpen(false)
    setRunning(true)
    setResult(null)
    try {
      setResult(await fetchCleanup({ dry_run: false }))
    } catch (e) {
      setResult({ error: e.message })
    } finally {
      setRunning(false)
    }
  }

  // Re-run preview when force toggles while modal is open
  useEffect(() => {
    if (!confirmOpen) return
    let cancelled = false
    setPreview('loading')
    fetchCleanup({ dry_run: true })
      .then(d => { if (!cancelled) setPreview(d) })
      .catch(e => { if (!cancelled) setPreview({ error: e.message }) })
    return () => { cancelled = true }
  }, [force])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>
        Outputs
      </div>
      <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--text-muted)' }}>
        Remove DB records for output files that no longer exist on disk.
        Records whose parent directory is missing entirely (e.g. unmounted drive) are skipped.
      </p>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          onClick={openConfirm}
          disabled={running}
          className="modal-btn modal-btn--confirm"
          style={{ flexShrink: 0, background: running ? undefined : '#ef4444' }}
        >
          {running ? 'Cleaning…' : 'Clean up Outputs'}
        </button>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center',
                        fontSize: 12, color: 'var(--text-muted)', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={force}
            onChange={e => setForce(e.target.checked)}
          />
          <span>Also remove records whose parent directory is missing</span>
        </label>
        {result && !result.error && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Checked <span style={{ color: 'var(--text)' }}>{result.checked.toLocaleString()}</span>
            {' · '}removed <span style={{ color: 'var(--text)' }}>{result.removed.toLocaleString()}</span>
            {result.skipped_parent_missing > 0 && (
              <> · skipped <span style={{ color: 'var(--text)' }}>{result.skipped_parent_missing.toLocaleString()}</span> (parent dir missing)</>
            )}
          </span>
        )}
        {result?.error && (
          <span style={{ fontSize: 12, color: 'var(--error, #e55)' }}>{result.error}</span>
        )}
      </div>

      {confirmOpen && createPortal(
        <div className="modal-overlay" onClick={() => setConfirmOpen(false)}>
          <div className="modal-box" style={{ maxWidth: 380 }} onClick={e => e.stopPropagation()}>
            <div className="modal-title">Clean up Outputs?</div>
            <p className="modal-body-text">
              {preview === 'loading' && <>Counting stale records…</>}
              {preview && preview !== 'loading' && !preview.error && (
                <>
                  <strong>{preview.would_remove.toLocaleString()}</strong> of{' '}
                  <strong>{preview.checked.toLocaleString()}</strong> records will be permanently removed.
                  {!force && preview.skipped_parent_missing > 0 && (
                    <> <strong>{preview.skipped_parent_missing.toLocaleString()}</strong> additional records
                    will be skipped because their parent directory is missing (likely an unmounted drive).</>
                  )}
                  {force && (
                    <> <strong>Force mode is on</strong> — records whose parent directory is missing are
                    also being removed. Make sure that drive isn't temporarily unmounted.</>
                  )}
                </>
              )}
              {preview?.error && (
                <span style={{ color: 'var(--error, #e55)' }}>Preview failed: {preview.error}</span>
              )}
            </p>
            <div className="modal-actions">
              <button className="modal-btn modal-btn--cancel" onClick={() => setConfirmOpen(false)}>Cancel</button>
              <button
                className="modal-btn modal-btn--confirm"
                style={{ background: '#ef4444' }}
                onClick={run}
                disabled={preview === 'loading' || preview?.error || (preview && preview.would_remove === 0)}
              >
                {preview && preview !== 'loading' && !preview.error
                  ? `Remove ${preview.would_remove.toLocaleString()}`
                  : 'Clean up'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}

function fmtDate(iso) {
  if (!iso) return null
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function CacheSection({ section }) {
  const [meta, setMeta] = useState(null)   // { updated_at, count } | null
  const [status, setStatus] = useState(null) // null | 'refreshing' | { ok, msg }

  useEffect(() => {
    fetch(`/api/comfyui-cache/${section.key}`)
      .then(r => r.json())
      .then(d => setMeta({ updated_at: d.updated_at, count: d.count }))
      .catch(() => {})
  }, [section.key])

  async function handleRefresh() {
    setStatus('refreshing')
    try {
      const r = await fetch(`/api/comfyui-cache/${section.key}/refresh`, { method: 'POST' })
      const d = await r.json()
      if (!r.ok) {
        setStatus({ ok: false, msg: d.error || `HTTP ${r.status}` })
        return
      }
      setMeta({ updated_at: d.updated_at, count: d.count })
      setStatus({ ok: true, msg: 'Refreshed' })
      setTimeout(() => setStatus(null), 2500)
    } catch (e) {
      setStatus({ ok: false, msg: e.message })
    }
  }

  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>
        {section.label}
      </div>
      <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--text-muted)' }}>
        {section.description}
      </p>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          onClick={handleRefresh}
          disabled={status === 'refreshing'}
          className="modal-btn modal-btn--save"
          style={{ flexShrink: 0 }}
        >
          {status === 'refreshing' ? 'Refreshing…' : 'Refresh'}
        </button>
        {meta?.updated_at && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Last updated: <span style={{ color: 'var(--text)' }}>{fmtDate(meta.updated_at)}</span>
            {meta.count != null && (
              <> &mdash; <span style={{ color: 'var(--text)' }}>{meta.count.toLocaleString()} entries</span></>
            )}
          </span>
        )}
        {!meta?.updated_at && status !== 'refreshing' && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>Not cached yet</span>
        )}
        {status && status !== 'refreshing' && (
          <span style={{ fontSize: 12, color: status.ok ? 'var(--accent, #7c6af7)' : 'var(--error, #e55)' }}>
            {status.msg}
          </span>
        )}
      </div>
    </div>
  )
}

export default function ConfigPage() {
  const [config, setConfig] = useState({})
  const [loading, setLoading] = useState(true)
  const { setNsfwEnabled } = useContext(AppContext)

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(d => { setConfig(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  function handleSave(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
    if (key === 'nsfw_password') {
      setNsfwEnabled(!!(value || '').trim())
    }
  }

  return (
    <div>
      {loading ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>
      ) : (
        <>
          <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 28 }}>
            {CONFIG_FIELDS.map(field => (
              <ConfigField
                key={field.key}
                field={field}
                value={config[field.key] ?? ''}
                onSave={handleSave}
              />
            ))}
          </div>

          <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 24, marginTop: 8 }}>
            <h3 style={{ margin: '0 0 4px', fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>
              ComfyUI Cache
            </h3>
            <p style={{ margin: '0 0 20px', fontSize: 12, color: 'var(--text-muted)' }}>
              Cached data from your ComfyUI instance. Refresh to fetch the latest.
            </p>
            {CACHE_SECTIONS.map(section => (
              <CacheSection key={section.key} section={section} />
            ))}
            <PreviewCacheSection />
          </div>

          <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 24, marginTop: 8 }}>
            <h3 style={{ margin: '0 0 4px', fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>
              Maintenance
            </h3>
            <p style={{ margin: '0 0 20px', fontSize: 12, color: 'var(--text-muted)' }}>
              One-shot cleanups for stale DB records.
            </p>
            <OutputsCleanupSection />
          </div>
        </>
      )}
    </div>
  )
}
