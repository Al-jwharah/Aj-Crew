// The Aj Crew gem mark, sized and tinted for use as a nav/UI glyph.
//
// The source art (`aj-mark.svg`) is the gem from the product icon, drawn as an
// OUTLINE on Lucide's own grid (24x24 viewBox, 2px round stroke) so that at the
// rail's `size={16}` it carries the same optical weight as the Lucide glyphs it
// sits beside. It is a static brand asset rendered from a plain URL import (NOT
// svgr/`?react`, and no inline SVG paths in TSX), the brand-mark carve-out from
// the `use-lucide-icons` rule that `components/BrandIcon.tsx` documents.
//
// Rendering is delegated to `BrandGlyph`, the shared masked-brand-glyph span:
// unlike an <img>, it paints the asset as a CSS mask over `currentColor`, so the
// mark inherits the nav rail's colour states (accent when the row is active,
// muted when idle) exactly like the glyphs around it.
//
// The art is generated, not hand-edited: `scripts/brand/` holds the kit that
// writes this file together with every other drawing of the mark.
import { BrandGlyph } from './BrandIcon'
import ajMarkUrl from '../assets/aj-mark.svg'

/**
 * Aj Crew brand glyph.
 *
 * @param size  Box edge in px; the gem is aspect-fit inside it (default 16,
 *              matching the `size={16}` Lucide glyphs in the nav rail).
 */
export function AjMark({ size = 16, className = 'inline-block shrink-0' }: { size?: number; className?: string }) {
  return <BrandGlyph url={ajMarkUrl} size={size} className={className} testId="aj-mark" />
}
