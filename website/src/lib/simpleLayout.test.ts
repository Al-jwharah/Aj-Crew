/**
 * The Simple layout keeps its own browser-local state, so the Advanced shell
 * comes back exactly as it was left, and its home lays out against the
 * composer dock's measured height.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import {
  SIMPLE_MORE_KEY, SIMPLE_SUGGESTION_LIMIT, navCollapsedKey, readNavCollapsed, readSessionsPinned,
  sessionsPinnedKey, writeSessionsPinned,
} from './simpleLayout'
import {
  SIMPLE_DOCK_BOTTOM_VAR, SIMPLE_HOME_MIN_BAND, simpleDockProps, simpleHomeFits, simpleHomeGeometry,
} from './simpleHome'

beforeEach(() => { localStorage.clear() })

describe('per-layout sidebar state', () => {
  it('stores each layout under its own keys', () => {
    expect(navCollapsedKey(false)).toBe('mc-nav')
    expect(navCollapsedKey(true)).toBe('mc-simple-nav')
    expect(sessionsPinnedKey(false)).toBe('mc-sidebar-pinned')
    expect(sessionsPinnedKey(true)).toBe('mc-simple-sessions-pinned')
    expect(new Set([navCollapsedKey(true), sessionsPinnedKey(true), SIMPLE_MORE_KEY, 'mc-nav', 'mc-sidebar-pinned']).size).toBe(5)
  })

  it('opens the Simple sidebar by default and keeps the Advanced rail default', () => {
    expect(readNavCollapsed(true)).toBe(false)
    expect(readNavCollapsed(false)).toBe(true)
    localStorage.setItem('mc-simple-nav', '1')
    localStorage.setItem('mc-nav', '0')
    expect(readNavCollapsed(true)).toBe(true)
    expect(readNavCollapsed(false)).toBe(false)
  })

  it('closes the sessions column by default in Simple only, and a choice in one layout leaves the other alone', () => {
    expect(readSessionsPinned(true)).toBe(false)
    expect(readSessionsPinned(false)).toBe(true)
    writeSessionsPinned(true, true)
    expect(readSessionsPinned(true)).toBe(true)
    expect(localStorage.getItem('mc-sidebar-pinned')).toBeNull()
    writeSessionsPinned(false, false)
    expect(readSessionsPinned(false)).toBe(false)
    expect(readSessionsPinned(true)).toBe(true)
  })

  it('offers at most four suggested tasks', () => {
    expect(SIMPLE_SUGGESTION_LIMIT).toBe(4)
  })
})

describe('home geometry', () => {
  it('frames the dock: the greeting ends where the dock starts and the suggestions start where it ends', () => {
    const { dockBottom, heroBottom, suggestionsTop } = simpleHomeGeometry(120)
    expect(dockBottom).toBe('calc(54% - 60px)')
    expect(heroBottom).toBe('calc(54% + 60px)')
    expect(suggestionsTop).toBe('calc(46% + 60px)')
  })

  it('keeps the two bands a whole dock apart for an odd height', () => {
    const { heroBottom, suggestionsTop } = simpleHomeGeometry(121)
    expect(heroBottom).toBe('calc(54% + 61px)')
    expect(suggestionsTop).toBe('calc(46% + 60px)')
  })

  it('centres only while both bands have room, and treats an unmeasured pane as roomy', () => {
    expect(simpleHomeFits(null, 120)).toBe(true)
    expect(simpleHomeFits(2 * SIMPLE_HOME_MIN_BAND + 120, 120)).toBe(true)
    expect(simpleHomeFits(2 * SIMPLE_HOME_MIN_BAND + 119, 120)).toBe(false)
    // A draft that grows the composer can use up the room.
    expect(simpleHomeFits(600, 120)).toBe(true)
    expect(simpleHomeFits(600, 320)).toBe(false)
  })

  it('names the dock state on the pane only in the Simple layout', () => {
    expect(simpleDockProps(false, false, 120)).toEqual({})
    expect(simpleDockProps(false, true, 120)).toEqual({})
    expect(simpleDockProps(true, false, 120)).toEqual({ 'data-simple-dock': 'settled' })
    expect(simpleDockProps(true, true, 120)).toEqual({
      'data-simple-dock': 'home',
      style: { [SIMPLE_DOCK_BOTTOM_VAR]: 'calc(54% - 60px)' },
    })
  })
})
