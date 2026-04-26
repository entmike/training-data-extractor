import { useState, useEffect, useRef } from 'react'

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

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(d => { setConfig(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  function handleSave(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
  }

  return (
    <div style={{ flex: 1, overflow: 'auto' }}>
      <div style={{ maxWidth: 640, margin: '0 auto', padding: '32px 24px' }}>
        <h2 style={{ margin: '0 0 4px', fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>
          Configuration
        </h2>
        <p style={{ margin: '0 0 32px', fontSize: 13, color: 'var(--text-muted)' }}>
          Settings are persisted in the database.
        </p>

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
            </div>
          </>
        )}
      </div>
    </div>
  )
}
