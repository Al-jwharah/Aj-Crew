/**
 * The Simple layout on the chat page: an empty chat is the home (brand mark,
 * greeting, the composer centred in the pane, up to four suggested tasks that
 * fill it); a chat with messages keeps the composer docked at the bottom; an
 * approval prompt is on screen either way; and the Advanced layout draws the
 * page it always drew.
 *
 * The page harness (store, mocks) is ChatPage.chipUndo.test.tsx's, with the
 * real welcome views.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react'
import type { RootState } from '../store'
import { Provider } from 'react-redux'
import { MemoryRouter } from 'react-router-dom'
import { configureStore } from '@reduxjs/toolkit'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '../hooks/useTheme'
import chatReducer from '../store/chatSlice'
import dashboardReducer from '../store/dashboardSlice'
import notificationsReducer from '../store/notificationsSlice'
import { SHELL_LAYOUT_KEY, writeShellLayout } from '../hooks/useShellLayout'
import { SIMPLE_DOCK_BOTTOM_VAR } from '../shell/simple/simpleHome'

vi.mock('react-virtuoso', () => ({
  Virtuoso: ({ data, itemContent }: { data?: unknown[]; itemContent: (index: number, item: unknown) => ReactNode }) => (
    <div data-testid="virtuoso">{data?.map((d: unknown, i: number) => <div key={i}>{itemContent(i, d)}</div>)}</div>
  ),
}))
vi.mock('../api/client', () => ({
  api: {
    chatSlots: vi.fn().mockResolvedValue([]),
    chatSlotDetail: vi.fn().mockResolvedValue({ messages: [], running: false, has_more: false, total: 0 }),
    sendChat: vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ ok: true }) }),
    chatHistory: vi.fn().mockResolvedValue({ sessions: [] }),
    models: vi.fn().mockResolvedValue([]),
    agents: vi.fn().mockResolvedValue([]),
    agentDetail: vi.fn().mockResolvedValue({}),
    workspaces: vi.fn().mockResolvedValue({ workspaces: [] }),
    slackChannels: vi.fn().mockResolvedValue([]),
    spawnList: vi.fn().mockResolvedValue({ agents: [] }),
    uploadFiles: vi.fn().mockResolvedValue({ paths: [] }),
    screenshot: vi.fn().mockResolvedValue({ path: null }),
    createChatSlot: vi.fn().mockResolvedValue({ key: 'new-slot', title: 'new-slot', messages: 0, running: false }),
    suggestions: vi.fn().mockResolvedValue({ suggestions: [] }),
    dashboardConfig: vi.fn().mockResolvedValue({}),
    sharedCrewCapabilities: vi.fn().mockResolvedValue(null),
    sharedCrewMode: vi.fn().mockResolvedValue(null),
    sharedCrewPeople: vi.fn().mockResolvedValue(null),
  },
  SEARCH_MIN_CHARS: 2,
}))
vi.mock('../hooks/useVoiceInput', () => ({ useVoiceInput: () => ({ recording: false, transcribing: false, toggle: vi.fn() }), voiceInputSupported: false }))
vi.mock('../hooks/useBranding', () => ({ useBranding: () => ({ botName: 'Test', avatar: '' }) }))
vi.mock('../hooks/useAgents', () => ({ useAgents: () => ({ agents: [], defaultAgent: 'default' }) }))
vi.mock('../components/MarkdownRenderer', () => ({ default: ({ content }: { content: string }) => <span>{content}</span> }))
vi.mock('../components/MarkdownPanel', () => ({ default: () => null }))
vi.mock('../pages/chat/ActivityViewer', () => ({ default: () => null }))
vi.mock('../components/DetailPanel', () => ({ default: () => null }))
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => ({ subscribeLogs: () => {} }) }))

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
})

import ChatPage from '../pages/ChatPage'
import { api } from '../api/client'

type Message = { role: string; content: string; cls: string; meta?: Record<string, string> }
const TALK: Message[] = [
  { role: 'user', content: 'Summarize the open pull requests', cls: '' },
  { role: 'assistant', content: 'There are three open pull requests.', cls: '' },
]

function makeStore(messages: Message[], slot: Record<string, unknown> = {}) {
  // The page re-reads the open chat from the gateway: it answers with the same
  // transcript the store starts with.
  vi.mocked(api.chatSlotDetail).mockResolvedValue({ messages, running: !!slot.running, has_more: false, total: messages.length } as never)
  return configureStore({
    reducer: { dashboard: dashboardReducer, chat: chatReducer, notifications: notificationsReducer },
    preloadedState: {
      dashboard: {
        status: null, connected: true,
        slots: [{ key: 's1', messages: messages.length, running: false, mode: '', pending_approval: false, waiting_for_input: false, last_activity_ts: undefined, ...slot }],
        unreadSlots: [], refreshTrigger: 0, approvalMode: 'normal',
        subagentRunning: {}, subagentDetails: {}, subagentText: {},
      } as unknown as RootState['dashboard'],
      chat: {
        activeSlot: 's1', messages,
        slotRunning: false, slotStopping: false, slotState: 'idle',
        history: [], historyHasMore: false, pendingInput: null,
        subagents: {}, toolLog: [], activityOpen: false, activityTab: 'tools',
        slotHasMore: false, slotOldestIndex: 0, loadingOlder: false,
        slotStatusDetail: {}, slotContextPct: {}, slotActivity: {}, slotHistory: [],
        historyOffset: 0, _wsChunkedDuringFetch: false,
        slotMessages: {}, slotLoading: false,
      } as unknown as RootState['chat'],
      notifications: { items: [] } as unknown as RootState['notifications'],
    },
  })
}

async function renderPage(store: ReturnType<typeof makeStore>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let result!: ReturnType<typeof render>
  await act(async () => {
    result = render(
      <QueryClientProvider client={qc}>
        <Provider store={store}>
          <ThemeProvider>
            <MemoryRouter><ChatPage /></MemoryRouter>
          </ThemeProvider>
        </Provider>
      </QueryClientProvider>,
    )
  })
  await waitFor(() => expect(screen.getByLabelText('Message input')).toBeTruthy())
  return result
}

const composer = () => screen.getByLabelText('Message input') as HTMLTextAreaElement
const dock = () => screen.getByTestId('composer-dock-root')
/** The pane the dock is positioned in; it names the dock's state. */
const pane = () => dock().parentElement as HTMLElement

beforeEach(() => { localStorage.setItem(SHELL_LAYOUT_KEY, 'simple') })
afterEach(() => { localStorage.removeItem(SHELL_LAYOUT_KEY) })

/** A shell command the agent is waiting on the person to allow. */
const APPROVAL: Message = {
  role: 'permission', content: 'Running: ls /tmp', cls: '',
  meta: {
    approval_id: 'ap-123', request_id: 'req-123', tool_input: '{"command":"ls /tmp"}', is_read_only: '1',
    tool_title: 'Running: ls /tmp', is_shell: '1', full_command: 'ls /tmp', base_command: 'ls',
    trust_command_grantable: '1', trust_base_grantable: '1', trust_grantable: '1', tool_call_id: 'tc-1',
  },
}

describe('Simple layout: home (an empty chat)', () => {
  it('draws the brand mark, a greeting, one composer and the suggested tasks', async () => {
    await renderPage(makeStore([]))
    const home = screen.getByTestId('simple-welcome')
    expect(within(home).getAllByRole('heading', { level: 2 })).toHaveLength(1)
    expect(home.querySelector('img, canvas')).not.toBeNull()
    expect(screen.getAllByLabelText('Message input')).toHaveLength(1)
    const chips = within(screen.getByRole('list', { name: 'Suggested tasks' })).getAllByRole('button')
    expect(chips.length).toBeGreaterThan(0)
    expect(chips.length).toBeLessThanOrEqual(4)
  })

  it('centres the composer: the pane names the home state and carries the dock offset', async () => {
    await renderPage(makeStore([]))
    expect(pane()).toHaveAttribute('data-simple-dock', 'home')
    expect(pane().style.getPropertyValue(SIMPLE_DOCK_BOTTOM_VAR)).toMatch(/^calc\(54% - \d+(\.\d+)?px\)$/)
    // The dock is the page's own, moved by a stylesheet rule and not re-created.
    expect(pane()).toContainElement(composer())
    expect(dock()).toHaveClass('absolute', 'bottom-0')
  })

  it('fills the composer from a suggested task', async () => {
    await renderPage(makeStore([]))
    expect(composer().value).toBe('')
    const chip = within(screen.getByTestId('simple-suggestions')).getAllByRole('button')[0]
    const task = chip.textContent!
    fireEvent.click(chip)
    await waitFor(() => expect(composer().value).toBe(task))
    // Filling is not sending: the chat is still the empty home.
    expect(screen.getByTestId('simple-welcome')).toBeInTheDocument()
  })

  it('does not draw the standard welcome under it', async () => {
    await renderPage(makeStore([]))
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1)
    expect(screen.queryByTestId('virtuoso')).toBeNull()
  })
})

describe('Simple layout: a chat with messages', () => {
  it('shows the transcript and docks the composer at the bottom', async () => {
    await renderPage(makeStore(TALK))
    expect(screen.queryByTestId('simple-welcome')).toBeNull()
    expect(screen.getByText('There are three open pull requests.')).toBeInTheDocument()
    expect(pane()).toHaveAttribute('data-simple-dock', 'settled')
    expect(pane().style.getPropertyValue(SIMPLE_DOCK_BOTTOM_VAR)).toBe('')
    expect(composer()).toBeInTheDocument()
  })

  it('keeps an approval prompt on screen', async () => {
    await renderPage(makeStore([TALK[0], APPROVAL], { running: true, pending_approval: true }))
    await waitFor(() => expect(screen.getByText(/Waiting for approval/)).toBeInTheDocument())
    // In the composer dock, where the Advanced layout draws it.
    expect(dock()).toContainElement(screen.getByText('Allow once'))
    expect(dock()).toContainElement(screen.getByRole('button', { name: 'Reject' }))
    expect(pane()).toHaveAttribute('data-simple-dock', 'settled')
  })
})

describe('Advanced layout: the chat page is the one it was', () => {
  it('draws the standard welcome and leaves the pane unmarked', async () => {
    localStorage.setItem(SHELL_LAYOUT_KEY, 'advanced')
    await renderPage(makeStore([]))
    expect(screen.queryByTestId('simple-welcome')).toBeNull()
    expect(screen.queryByTestId('simple-suggestions')).toBeNull()
    expect(pane()).not.toHaveAttribute('data-simple-dock')
    expect(pane().style.getPropertyValue(SIMPLE_DOCK_BOTTOM_VAR)).toBe('')
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1)
  })

  it('swaps between the two homes when the setting changes, without a reload', async () => {
    await renderPage(makeStore([]))
    expect(screen.getByTestId('simple-welcome')).toBeInTheDocument()
    await act(async () => { writeShellLayout('advanced') })
    expect(screen.queryByTestId('simple-welcome')).toBeNull()
    expect(pane()).not.toHaveAttribute('data-simple-dock')
    await act(async () => { writeShellLayout('simple') })
    expect(screen.getByTestId('simple-welcome')).toBeInTheDocument()
    expect(pane()).toHaveAttribute('data-simple-dock', 'home')
  })
})
