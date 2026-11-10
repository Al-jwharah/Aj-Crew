/**
 * useActionsProvider — the React wiring around the pure provider factory
 * (which actionsProvider.test.ts covers): a failed "New session" create is
 * reported on the shell notice, since the palette has closed by then.
 */
import { describe, expect, it, vi } from 'vitest'
import { act, waitFor } from '@testing-library/react'

vi.mock('../../../store/chatSlice', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../store/chatSlice')>()),
  createSlot: () => () => {
    const p = Promise.reject(new Error('zzq create failed'))
    return Object.assign(p.catch(() => undefined), { unwrap: () => p, requestId: 'zzq-create' })
  },
}))

import { renderHookWithProviders } from '../../../test/helpers'
import { useActionsProvider } from './actionsProvider'
import { SHELL_LAYOUT_KEY } from '../../../hooks/useShellLayout'

describe('useActionsProvider — New session', () => {
  it('reports a failed create on the shell notice', async () => {
    const { result, store } = renderHookWithProviders(() => useActionsProvider({ openShortcuts: vi.fn() }))
    const rows = await Promise.resolve(result.current.search(''))
    const newSession = rows.find((r) => r.id === 'actions:new-session')
    expect(newSession?.onActivate).toBeDefined()
    newSession!.onActivate!()

    await waitFor(() => expect(store.getState().chat.agentSwitchNotice).toEqual({ title: "Couldn't create a new chat.", message: 'zzq create failed', error: true }))
  })
})

describe('useActionsProvider — shell layout', () => {
  it('offers the layout switch and persists the choice', async () => {
    localStorage.setItem(SHELL_LAYOUT_KEY, 'simple')
    try {
      const { result } = renderHookWithProviders(() => useActionsProvider({ openShortcuts: vi.fn() }))
      const rows = await Promise.resolve(result.current.search('layout'))
      expect(rows.map((r) => r.title)).toEqual(['Switch to Advanced layout'])
      act(() => { rows[0].onActivate!() })
      expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBe('advanced')
      await waitFor(async () => {
        const next = await Promise.resolve(result.current.search('layout'))
        expect(next.map((r) => r.title)).toEqual(['Switch to Simple layout'])
      })
    } finally {
      localStorage.removeItem(SHELL_LAYOUT_KEY)
    }
  })

  it('passes the shell commands through as actions', async () => {
    const reportProblem = vi.fn()
    const { result } = renderHookWithProviders(() => useActionsProvider({ openShortcuts: vi.fn(), shellActions: { reportProblem } }))
    const rows = await Promise.resolve(result.current.search('report'))
    rows.find((r) => r.id === 'actions:report-problem')!.onActivate!()
    expect(reportProblem).toHaveBeenCalledTimes(1)
  })
})
