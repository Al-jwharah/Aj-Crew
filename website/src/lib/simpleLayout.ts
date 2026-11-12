/**
 * Browser-local state the Simple layout keeps SEPARATE from the Advanced
 * shell's, so that neither layout's choices leak into the other: the Advanced
 * shell must come back exactly as the user left it.
 *
 * Each helper takes the layout as an argument rather than reading it, so the
 * caller decides (the shell reads `useShellLayout`; an embed or a popout, which
 * draws no shell, always passes `false`).
 */
import { safeSetItem } from '../utils/safeStorage'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** Storage key for the sidebar's collapsed flag ('1' collapsed, '0' open). */
export function navCollapsedKey(simple: boolean): string {
  return simple ? 'mc-simple-nav' : 'mc-nav'
}

/**
 * Whether the sidebar starts collapsed. The Advanced rail starts collapsed
 * until the user expands it (only a stored '0' opens it). The Simple sidebar
 * carries the recent chats, so it starts open and only a stored '1' collapses it.
 */
export function readNavCollapsed(simple: boolean): boolean {
  const stored = read(navCollapsedKey(simple))
  return simple ? stored === '1' : stored !== '0'
}

/** Storage key for the chat page's sessions column ('true' / 'false'). */
export function sessionsPinnedKey(simple: boolean): string {
  return simple ? 'mc-simple-sessions-pinned' : 'mc-sidebar-pinned'
}

/**
 * Whether the chat page's sessions column starts open. Advanced: open unless
 * the user closed it. Simple: closed unless the user opened it, because the
 * sidebar already lists the recent chats; its toggle, flyout and every row
 * action stay where they are.
 */
export function readSessionsPinned(simple: boolean): boolean {
  const stored = read(sessionsPinnedKey(simple))
  return simple ? stored === 'true' : stored !== 'false'
}

export function writeSessionsPinned(simple: boolean, pinned: boolean) {
  safeSetItem(sessionsPinnedKey(simple), String(pinned))
}

/** Storage key for the sidebar's More group ('1' open). Closed by default. */
export const SIMPLE_MORE_KEY = 'mc-simple-more'

/** Recent chats the sidebar lists before it defers to the full sessions page. */
export const SIMPLE_RECENTS_LIMIT = 30

/** Suggested-task chips under the home composer. */
export const SIMPLE_SUGGESTION_LIMIT = 4
