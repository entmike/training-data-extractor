export default function ViewToggle({ value, onChange }) {
  return (
    <div className="view-toggle">
      <button
        className={`view-toggle-btn${value === 'card' ? ' active' : ''}`}
        onClick={() => onChange('card')}
        title="Card view"
      >⊟</button>
      <button
        className={`view-toggle-btn${value === 'thumb' ? ' active' : ''}`}
        onClick={() => onChange('thumb')}
        title="Thumbnail view"
      >⊞</button>
    </div>
  )
}
