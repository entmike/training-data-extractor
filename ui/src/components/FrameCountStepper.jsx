import { useState, useEffect } from 'react'

export default function FrameCountStepper({ frameCount, step = 12, min = 1, max = Infinity, disabled = false, onChange }) {
  const [draft, setDraft] = useState(String(frameCount))

  useEffect(() => { setDraft(String(frameCount)) }, [frameCount])

  function snapDown(n) { return Math.ceil(n / step) * step - step }
  function snapUp(n)   { return Math.floor(n / step) * step + step }

  function commit(raw) {
    const n = Math.max(min, Math.min(max === Infinity ? Infinity : max, parseInt(raw) || min))
    setDraft(String(n))
    if (n !== frameCount) onChange(n)
  }

  return (
    <div className="fcs-wrap">
      <button
        className="fcs-btn"
        onClick={() => onChange(Math.max(min, snapDown(frameCount)))}
        disabled={disabled || snapDown(frameCount) < min}
        title={`Previous multiple of ${step}`}
      >−{step}f</button>
      <input
        className="fcs-input"
        type="number"
        value={draft}
        min={min}
        max={max === Infinity ? undefined : max}
        step={step}
        disabled={disabled}
        onChange={e => setDraft(e.target.value)}
        onBlur={e => commit(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { e.target.blur(); commit(e.target.value) } }}
      />
      <button
        className="fcs-btn"
        onClick={() => onChange(Math.min(max, snapUp(frameCount)))}
        disabled={disabled || snapUp(frameCount) > max}
        title={`Next multiple of ${step}`}
      >+{step}f</button>
    </div>
  )
}
