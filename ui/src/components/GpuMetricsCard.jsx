import { useState, useEffect, useCallback } from 'react'

function fmtGB(bytes) {
  if (bytes == null) return '—'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

function fmtMB(bytes) {
  if (bytes == null) return '—'
  return (bytes / (1024 * 1024)).toFixed(0) + ' MB'
}

export default function GpuMetricsCard({ fetchInterval = 5000 }) {
  const [metrics, setMetrics] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchMetrics = useCallback(async () => {
    try {
      const r = await fetch('/api/gpu-metrics')
      const d = await r.json()
      if (d.error) {
        setError(d.error)
        setMetrics(null)
        return
      }
      setMetrics(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMetrics()
    const t = setInterval(fetchMetrics, fetchInterval)
    return () => clearInterval(t)
  }, [fetchMetrics, fetchInterval])

  if (loading) {
    return (
      <div className="gmc gmc--loading">
        <div className="gmc-body">Loading GPU metrics…</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="gmc gmc--error">
        <div className="gmc-body">{error}</div>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="gmc gmc--empty">
        <div className="gmc-body">No GPU metrics available</div>
      </div>
    )
  }

  const {
    gpu_utilization,
    gpu_temperature,
    gpu_power_draw,
    gpu_power_limit,
    gpu_memory_used_gb,
    gpu_memory_total_gb,
    gpu_memory_pct,
    device_name,
    comfyui_vram_total,
    comfyui_vram_free,
    torch_vram_total,
    torch_vram_free,
  } = metrics

  const utilColor =
    gpu_utilization >= 90
      ? '#ef4444'
      : gpu_utilization >= 60
        ? '#f59e0b'
        : gpu_utilization >= 30
          ? '#10b981'
          : '#6b7280'

  const tempColor =
    gpu_temperature >= 85
      ? '#ef4444'
      : gpu_temperature >= 70
        ? '#f59e0b'
        : gpu_temperature >= 55
          ? '#10b981'
          : '#6b7280'

  const utilWidth = gpu_utilization + '%'
  const tempWidth = Math.min(100, gpu_temperature * 100 / 105) + '%'
  const powerRatio = gpu_power_limit > 0 ? gpu_power_draw / gpu_power_limit : 0
  const powerWidth = Math.min(100, powerRatio * 100) + '%'
  const memWidth = gpu_memory_pct + '%'

  const powerColor =
    powerRatio >= 0.9
      ? '#ef4444'
      : powerRatio >= 0.6
        ? '#f59e0b'
        : '#10b981'

  const memColor =
    gpu_memory_pct >= 90
      ? '#ef4444'
      : gpu_memory_pct >= 60
        ? '#f59e0b'
        : '#10b981'

  return (
    <div className="gmc">
      <div className="gmc-header">
        <span className="gmc-title">GPU Metrics</span>
        <span className="gmc-poll-dot" title={"Auto-refreshing every " + (fetchInterval / 1000) + "s"} />
      </div>
      <div className="gmc-body">
        {device_name && <div className="gmc-device">{device_name}</div>}

        <div className="gmc-grid">
          {/* GPU Utilization */}
          <div className="gmc-card">
            <div className="gmc-card-label">Utilization</div>
            <div className="gmc-bar-bg">
              <div
                className="gmc-bar-fill"
                style={{
                  width: utilWidth,
                  backgroundColor: utilColor,
                }}
              />
            </div>
            <div className="gmc-value" style={{ color: utilColor }}>
              {gpu_utilization}%
            </div>
          </div>

          {/* Temperature */}
          <div className="gmc-card">
            <div className="gmc-card-label">Temperature</div>
            <div className="gmc-bar-bg">
              <div
                className="gmc-bar-fill"
                style={{
                  width: tempWidth,
                  backgroundColor: tempColor,
                }}
              />
            </div>
            <div className="gmc-value" style={{ color: tempColor }}>
              {gpu_temperature}°C
            </div>
          </div>

          {/* Power Draw */}
          <div className="gmc-card">
            <div className="gmc-card-label">Power</div>
            <div className="gmc-bar-bg">
              <div
                className="gmc-bar-fill"
                style={{
                  width: powerWidth,
                  backgroundColor: powerColor,
                }}
              />
            </div>
            <div className="gmc-value">
              {gpu_power_draw.toFixed(1)}W / {gpu_power_limit.toFixed(0)}W
            </div>
          </div>

          {/* VRAM */}
          <div className="gmc-card">
            <div className="gmc-card-label">VRAM</div>
            <div className="gmc-bar-bg">
              <div
                className="gmc-bar-fill"
                style={{
                  width: memWidth,
                  backgroundColor: memColor,
                }}
              />
            </div>
            <div className="gmc-value">
              {gpu_memory_used_gb} / {gpu_memory_total_gb}
            </div>
          </div>
        </div>

        {/* ComfyUI VRAM (torch tracking) */}
        {comfyui_vram_total != null && (
          <div className="gmc-section">
            <div className="gmc-section-title">ComfyUI VRAM Tracking</div>
            <div className="gmc-grid gmc-grid--2">
              <div className="gmc-card">
                <div className="gmc-card-label">Torch VRAM</div>
                <div className="gmc-value">{fmtMB(torch_vram_total)}</div>
              </div>
              <div className="gmc-card">
                <div className="gmc-card-label">Torch Free</div>
                <div className="gmc-value">{fmtMB(torch_vram_free)}</div>
              </div>
              <div className="gmc-card">
                <div className="gmc-card-label">Total VRAM</div>
                <div className="gmc-value">{fmtGB(comfyui_vram_total)}</div>
              </div>
              <div className="gmc-card">
                <div className="gmc-card-label">Free VRAM</div>
                <div className="gmc-value">{fmtGB(comfyui_vram_free)}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
