import { useCallback, useSyncExternalStore } from 'react'
import { safeSetItem } from '../utils/safeStorage'

/**
 * Which shell the dashboard draws.
 *
 *   simple   : chat-first. One slim sidebar (New chat, recent chats, a few
 *              destinations, More, Settings), a top bar with only the sidebar
 *              toggle, search and notifications, and a centred composer on an
 *              empty chat.
 *   advanced : the full workspace shell (rail, sessions column, readouts).
 *
 * Browser-local, like the other how-this-window-draws choices in Settings ->
 * Display (`mc-topbar-search`, `mc-ui`): persisted to localStorage under
 * `mc-shell-layout`, default Simple. Every mounted reader follows a change at
 * once (same tab through the module's listeners, other tabs through the DOM
 * `storage` event), so the Settings switch and the command palette action
 * need no reload.
 *
 * The phone form (under 768px) is one bar and a drawer in both layouts; the
 * shell reads this value only for the desktop form.
 */
export type ShellLayout = 'simple' | 'advanced'

export const SHELL_LAYOUT_KEY = 'mc-shell-layout'

/** What an install with nothing stored gets. */
export const SHELL_LAYOUT_DEFAULT: ShellLayout = 'simple'

let fallbackLayout: ShellLayout = SHELL_LAYOUT_DEFAULT
// A choice the store refused (quota, private mode). It holds for this tab so
// the switch still does what it says; a write that lands, or another tab's,
// clears it.
let unsavedLayout: ShellLayout | null = null
const listeners = new Set<() => void>()

function storedLayout(): ShellLayout | null {
  try {
    const stored = localStorage.getItem(SHELL_LAYOUT_KEY)
    if (stored === 'simple' || stored === 'advanced') return stored
  } catch {
    /* storage unavailable: nothing stored */
  }
  return null
}

/** The layout to draw: this tab's unsaved choice, else the stored one, else the default. */
export function readShellLayout(): ShellLayout {
  return unsavedLayout ?? storedLayout() ?? fallbackLayout
}

/** Persist the layout and tell every mounted reader in this tab. */
export function writeShellLayout(layout: ShellLayout) {
  safeSetItem(SHELL_LAYOUT_KEY, layout)
  unsavedLayout = storedLayout() === layout ? null : layout
  listeners.forEach(l => l())
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  const onStorage = (e: StorageEvent) => {
    if (e.key !== null && e.key !== SHELL_LAYOUT_KEY) return
    unsavedLayout = null
    cb()
  }
  window.addEventListener('storage', onStorage)
  return () => {
    listeners.delete(cb)
    window.removeEventListener('storage', onStorage)
  }
}

export function useShellLayout(): readonly [ShellLayout, (layout: ShellLayout) => void] {
  const layout = useSyncExternalStore(subscribe, readShellLayout, readShellLayout)
  const setLayout = useCallback((next: ShellLayout) => writeShellLayout(next), [])
  return [layout, setLayout] as const
}

/**
 * Test seam: the layout an empty store resolves to. The suite's setup file
 * pins it to `advanced`, because the tests written before the Simple layout
 * existed assert the Advanced shell and many of them clear localStorage
 * between cases; a Simple-layout test stores `simple` (or passes it here).
 * `null` restores the shipped default.
 */
export function __setShellLayoutFallbackForTests(layout: ShellLayout | null) {
  fallbackLayout = layout ?? SHELL_LAYOUT_DEFAULT
  unsavedLayout = null
  listeners.forEach(l => l())
}
