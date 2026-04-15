import { useMemo } from 'react'
import { decode } from 'blurhash'

const BLURHASH_ENABLED = true
const W = 170, H = 96

export function blurhashToDataURL(hash) {
  if (!BLURHASH_ENABLED || !hash) return null
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
  const dataUrl = useMemo(() => blurhashToDataURL(hash), [hash])
  if (!dataUrl) return null
  return (
    <div
      className={className}
      style={{ backgroundImage: `url(${dataUrl})`, backgroundSize: '100% 100%' }}
    />
  )
}
