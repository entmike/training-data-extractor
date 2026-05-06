import { useEffect } from 'react'

export default function Toast({ toasts, dismiss }) {
  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className={`toast toast--${t.type}`} onClick={() => dismiss(t.id)}>
          <span className="toast-icon">{t.type === 'success' ? '✓' : '✕'}</span>
          <span className="toast-msg">{t.msg}</span>
        </div>
      ))}
    </div>
  )
}
