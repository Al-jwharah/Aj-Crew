/**
 * Geometry of the Simple layout's home: an empty chat draws the brand mark and
 * a greeting, the composer in the middle of the pane, and the suggested tasks
 * under it.
 *
 * The composer is the SAME dock the chat uses (one element, one draft, every
 * control), only anchored higher: its `bottom` moves from the pane's edge to
 * the middle, and returns to the edge when the first message is sent. The
 * greeting and the suggestions are laid out against the dock's measured height
 * from the same percentages, so the three never overlap whatever the composer
 * grows to.
 */
import { useCallback, useRef, useState, type CSSProperties } from 'react'

/** Where the composer's centre sits, as a percentage of the pane from its top. */
const HOME_CENTRE_PCT = 46

/** Room the greeting needs above the composer, and the suggestions below it (px). */
export const SIMPLE_HOME_MIN_BAND = 150

/** Widest the home composer's column grows (px); the chat's own column may be wider.
 *  `styles/simple-layout.css` states the same number for the dock. */
export const SIMPLE_HOME_COMPOSER_MAX_W = 760

export interface SimpleHomeGeometry {
  /** `bottom` of the composer dock. */
  dockBottom: string
  /** `bottom` of the band holding the brand mark and the greeting. */
  heroBottom: string
  /** `top` of the band holding the suggested tasks. */
  suggestionsTop: string
}

export function simpleHomeGeometry(dockH: number): SimpleHomeGeometry {
  const half = Math.round(dockH / 2)
  return {
    dockBottom: `calc(${100 - HOME_CENTRE_PCT}% - ${half}px)`,
    heroBottom: `calc(${100 - HOME_CENTRE_PCT}% + ${half}px)`,
    suggestionsTop: `calc(${HOME_CENTRE_PCT}% + ${dockH - half}px)`,
  }
}

/** The custom property the pane hands the dock its home `bottom` through. */
export const SIMPLE_DOCK_BOTTOM_VAR = '--simple-dock-bottom'

/**
 * What the chat pane carries for its composer dock in the Simple layout. The
 * dock's own element is not touched (the Advanced layout, split panes and
 * popouts share it as it is); the pane names the dock's state and a rule in
 * `styles/simple-layout.css` reads it:
 *
 *   home    : the dock sits at `--simple-dock-bottom`, in a capped, centred column.
 *   settled : the dock is at the bottom edge, and glides there on leaving home.
 *
 * Nothing is set outside the Simple layout.
 */
export function simpleDockProps(simple: boolean, home: boolean, dockH: number): {
  'data-simple-dock'?: 'home' | 'settled'
  style?: CSSProperties
} {
  if (!simple) return {}
  if (!home) return { 'data-simple-dock': 'settled' }
  return {
    'data-simple-dock': 'home',
    style: { [SIMPLE_DOCK_BOTTOM_VAR]: simpleHomeGeometry(dockH).dockBottom } as CSSProperties,
  }
}

/**
 * Whether the pane has room for the centred home. A short pane (a small
 * window, a tall terminal dock, a long draft) keeps the composer at the bottom
 * and shows the standard welcome, which already handles tight heights.
 * An unmeasured pane (`null`) counts as roomy.
 */
export function simpleHomeFits(paneH: number | null, dockH: number): boolean {
  return paneH === null || paneH - dockH >= 2 * SIMPLE_HOME_MIN_BAND
}

/** Measures the chat pane's height; `null` until a box with a height is seen. */
export function usePaneHeight(): { paneRef: (el: HTMLElement | null) => void; paneH: number | null } {
  const [paneH, setPaneH] = useState<number | null>(null)
  const observer = useRef<ResizeObserver | null>(null)
  const paneRef = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect()
    observer.current = null
    if (!el) { setPaneH(null); return }
    const measure = () => setPaneH(el.offsetHeight > 0 ? el.offsetHeight : null)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    observer.current = new ResizeObserver(measure)
    observer.current.observe(el)
  }, [])
  return { paneRef, paneH }
}
