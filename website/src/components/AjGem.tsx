import ajGemUrl from '../assets/aj-gem.svg'

interface AjGemProps {
  size?: number
  className?: string
}

/**
 * The Aj Crew gem character: the brand mark with a face, as the Electron boot
 * sequence draws it. A static asset shown through `<img>`: the white body, its
 * ink outline and the dark eyes are the drawing's own colors, so they hold on
 * every theme. `scripts/brand/` generates the file.
 *
 * `object-contain` keeps the gem's proportions when a caller sizes the box by
 * class (`h-full w-full`) rather than by `size`.
 */
export function AjGem({ size = 40, className = '' }: AjGemProps) {
  const h = Math.round(size * 0.9)
  return (
    <img
      src={ajGemUrl}
      width={size}
      height={h}
      alt=""
      aria-hidden="true"
      draggable={false}
      className={`object-contain ${className}`.trim()}
    />
  )
}
