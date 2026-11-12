/**
 * The shell layout setting (`mc-shell-layout`): Simple is what an install with
 * nothing stored draws, a choice persists, every mounted reader follows a
 * change at once, and a refused write still applies to this tab.
 *
 * The suite's setup file pins an empty store to `advanced` for the tests that
 * predate the Simple layout; the cases about the shipped default lift that pin.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, render, screen } from '@testing-library/react'
import {
  SHELL_LAYOUT_DEFAULT, SHELL_LAYOUT_KEY, __setShellLayoutFallbackForTests, readShellLayout, useShellLayout,
  writeShellLayout,
} from './useShellLayout'

function Probe({ id }: { id: string }) {
  const [layout, setLayout] = useShellLayout()
  return (
    <button data-testid={id} onClick={() => setLayout(layout === 'simple' ? 'advanced' : 'simple')}>{layout}</button>
  )
}

beforeEach(() => {
  localStorage.removeItem(SHELL_LAYOUT_KEY)
  __setShellLayoutFallbackForTests(null)
})

afterEach(() => {
  // Unmount first: resetting the seam below notifies mounted readers.
  cleanup()
  vi.restoreAllMocks()
  localStorage.removeItem(SHELL_LAYOUT_KEY)
  __setShellLayoutFallbackForTests(null)
})

describe('shell layout setting', () => {
  it('defaults to Simple when nothing is stored', () => {
    expect(SHELL_LAYOUT_DEFAULT).toBe('simple')
    expect(readShellLayout()).toBe('simple')
    render(<Probe id="a" />)
    expect(screen.getByTestId('a')).toHaveTextContent('simple')
  })

  it('reads a stored choice, and ignores a value it does not know', () => {
    localStorage.setItem(SHELL_LAYOUT_KEY, 'advanced')
    expect(readShellLayout()).toBe('advanced')
    localStorage.setItem(SHELL_LAYOUT_KEY, 'compact')
    expect(readShellLayout()).toBe('simple')
  })

  it('persists a choice both ways', () => {
    writeShellLayout('advanced')
    expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBe('advanced')
    expect(readShellLayout()).toBe('advanced')
    writeShellLayout('simple')
    expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBe('simple')
    expect(readShellLayout()).toBe('simple')
  })

  it('moves every mounted reader at once', () => {
    render(<><Probe id="a" /><Probe id="b" /></>)
    act(() => { screen.getByTestId('a').click() })
    expect(screen.getByTestId('a')).toHaveTextContent('advanced')
    expect(screen.getByTestId('b')).toHaveTextContent('advanced')
    expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBe('advanced')
  })

  it('follows a change made in another tab', () => {
    render(<Probe id="a" />)
    act(() => {
      localStorage.setItem(SHELL_LAYOUT_KEY, 'advanced')
      window.dispatchEvent(new StorageEvent('storage', { key: SHELL_LAYOUT_KEY, newValue: 'advanced' }))
    })
    expect(screen.getByTestId('a')).toHaveTextContent('advanced')
  })

  it('applies the choice to this tab when the store refuses the write', () => {
    render(<Probe id="a" />)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    act(() => { screen.getByTestId('a').click() })
    expect(screen.getByTestId('a')).toHaveTextContent('advanced')
    expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBeNull()
  })

  it('lets the suite pin what an empty store resolves to, without touching a stored choice', () => {
    __setShellLayoutFallbackForTests('advanced')
    expect(readShellLayout()).toBe('advanced')
    localStorage.setItem(SHELL_LAYOUT_KEY, 'simple')
    expect(readShellLayout()).toBe('simple')
  })
})
