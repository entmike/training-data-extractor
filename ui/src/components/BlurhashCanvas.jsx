import { useState, useEffect, useRef, useMemo } from 'react'
import { decode } from 'blurhash'

const W = 170, H = 96

export function blurhashToDataURL(hash) {
  if (!hash) return null
  const pixels = decode(hash, W, H)
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  const img = ctx.createImageData(W, H)
  img.data.set(pixels)
  ctx.putImageData(img, 0, 0)
  return canvas.toDataURL()
}

export default function BlurhashCanvas({ hash, className }) {
  const ref = useRef(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!hash) return
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisible(true); obs.disconnect() } },
      { rootMargin: '200px' }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [hash])

  const dataUrl = useMemo(() => (visible ? blurhashToDataURL(hash) : null), [visible, hash])

  return (
    <div
      ref={ref}
      className={className}
      style={dataUrl ? { backgroundImage: `url(${dataUrl})`, backgroundSize: '100% 100%' } : undefined}
    />
  )
}
