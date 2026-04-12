import { useEffect, useRef } from 'react'
import { decode } from 'blurhash'

const BLURHASH_ENABLED = false

export function blurhashToDataURL(hash) {
  if (!BLURHASH_ENABLED || !hash) return null
  const W = 256, H = 144
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
  const canvasRef = useRef(null)

  useEffect(() => {
    if (!BLURHASH_ENABLED || !hash || !canvasRef.current) return
    const W = 256, H = 144
    const pixels = decode(hash, W, H)
    const ctx = canvasRef.current.getContext('2d')
    const img = ctx.createImageData(W, H)
    img.data.set(pixels)
    ctx.putImageData(img, 0, 0)
  }, [hash])

  if (!BLURHASH_ENABLED || !hash) return null
  return <canvas ref={canvasRef} width={256} height={144} className={className} />
}
