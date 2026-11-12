/**
 * The Aj Crew gem mark (`components/AjMark.tsx`) and its use as the
 * "Agent Capabilities" nav icon.
 *
 * Three things are pinned here:
 * - the mark paints the gem asset as a CSS mask over `currentColor`, which is
 *   what lets it follow the rail's active (accent) / idle colour states instead
 *   of being a fixed-colour <img>;
 * - the asset keeps Lucide's geometry contract (24x24 viewBox, 2px stroke), so
 *   the glyph weighs the same as the icons beside it;
 * - the `capabilities` built-in surface renders that mark rather than a Lucide
 *   glyph (regression guard for the icon swap).
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement } from 'react'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { AjMark } from '../components/AjMark'
import { KiroGhostMark } from '../components/KiroGhostMark'
import '../surfaces/builtins'
import { getBuiltinSurface } from '../surfaces/registry'

const ASSET = join(dirname(fileURLToPath(import.meta.url)), '..', 'assets', 'aj-mark.svg')

describe('AjMark', () => {
  // The mask contract must be asserted against React's OWN style serialization,
  // not the test DOM: jsdom's `cssstyle` does not implement the `mask-*`
  // longhands, so React's CSSOM assignment is silently dropped and neither
  // `el.style` nor the serialized `style` attribute carries them under jsdom.
  // `renderToStaticMarkup` emits every style key verbatim (React escapes the
  // inline `"` as `&quot;`), independent of the DOM's CSS-property allowlist.
  // DOM-observable props (background-color, size, aria-hidden) are still checked
  // via jsdom, which handles them.
  const maskStyle = () => {
    const html = renderToStaticMarkup(<AjMark />)
    return /style="([^"]*)"/.exec(html)?.[1] ?? ''
  }

  it('paints the gem asset as a mask over currentColor', () => {
    const { getByTestId } = render(<AjMark />)
    // currentColor is what makes the glyph inherit the nav row's text colour.
    expect(getByTestId('aj-mark').style.backgroundColor).toBe('currentcolor')
    const style = maskStyle()
    // The gem SVG (well under the 4 KB inline limit) is inlined as a
    // `data:image/svg+xml,…` URI by the bundler, so the mask paints the gem art
    // directly. The component's `url={ajMarkUrl}` binding guarantees it is the
    // gem asset specifically.
    expect(style).toContain('data:image/svg+xml') // the gem asset is the mask source
    expect(style).toContain('mask-size:contain')
  })

  it('quotes the mask URL', () => {
    // Regression guard: Vite inlines the SVG as a `data:image/svg+xml,…` URI
    // whose attributes are single-quoted. An UNQUOTED css `url(…)` token cannot
    // contain quotes, so the browser drops the declaration and the glyph paints
    // as a solid `currentColor` square. React serializes the quotes as `&quot;`.
    expect(maskStyle()).toMatch(/mask-image:url\(&quot;/)
  })

  it('is decorative (hidden from the accessibility tree)', () => {
    const { getByTestId } = render(<AjMark />)
    expect(getByTestId('aj-mark').getAttribute('aria-hidden')).toBe('true')
  })

  it('sizes the box from the size prop', () => {
    const { getByTestId } = render(<AjMark size={24} />)
    const el = getByTestId('aj-mark')
    expect(el.style.width).toBe('24px')
    expect(el.style.height).toBe('24px')
  })
})

describe('aj-mark.svg line weight', () => {
  it('is drawn on the Lucide grid at the Lucide stroke', () => {
    const svg = readFileSync(ASSET, 'utf8')
    expect(svg).toContain('viewBox="0 0 24 24"')
    expect(svg).toContain('stroke-width="2"')
    expect(svg).toContain('stroke-linecap="round"')
  })
})

describe('Customize nav icon', () => {
  it('uses the Aj Crew gem mark, not the Kiro harness logo', () => {
    const surface = getBuiltinSurface('capabilities')
    expect(surface?.label).toBe('Customize')
    expect((surface?.icon as ReactElement).type).toBe(AjMark)
    expect((surface?.icon as ReactElement).type).not.toBe(KiroGhostMark)
  })
})
