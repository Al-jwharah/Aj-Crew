// The Simple layout (the shipped default shell): one slim sidebar that lists
// the recent chats directly, three named destinations, the rest under More,
// Settings last; a top bar with the sidebar toggle, search and notifications.
// Every destination the Advanced rail reaches is still reached here, nothing
// that needs the person is folded away, and switching back returns the
// Advanced shell. The module mocks and the matchMedia / ResizeObserver stubs
// are App.topbarAndShortcuts.test.tsx's.
//
// The suite's setup file pins an empty store to the Advanced layout for the
// tests that predate this one; every test here stores Simple, as an install
// that chose it (or never chose) would read it.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, act, fireEvent, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '../../integration/mocks/server'
import { renderWithProviders } from './helpers'
import { namedCeiling } from './namedCeiling'
import App from '../App'
import { SHELL_LAYOUT_KEY, writeShellLayout } from '../hooks/useShellLayout'
import { focusModeEnabled, __resetFocusMode } from '../hooks/useFocusMode'
import { setTerminalEnabledFlag } from '../utils/terminalRegistry'
import { __resetBottomTerminal } from '../hooks/useBottomTerminal'
import { addSlotOptimistic, markSlotUnread } from '../store/dashboardSlice'
import type { RootState } from '../store'
import type { ChatSlot } from '../types'

vi.mock('../pages/ChatPage', () => ({ default: () => <div data-testid="chat-page">ChatPage</div> }))
vi.mock('../pages/SystemPage', () => ({ default: () => <div data-testid="system-page">SystemPage</div> }))
vi.mock('../pages/ProjectsPage', () => ({ default: () => <div data-testid="projects-page">ProjectsPage</div> }))
vi.mock('../pages/LogsPage', () => ({ default: () => <div data-testid="logs-page">LogsPage</div> }))
vi.mock('../pages/AjCrewAgentsPage', () => ({ default: () => <div data-testid="mc-agents-page">MCAgentsPage</div> }))
vi.mock('../pages/CapabilitiesPage', () => ({ default: () => <div data-testid="capabilities-page">CapabilitiesPage</div> }))
vi.mock('../pages/NotificationsPage', () => ({ default: () => <div data-testid="notifications-page">NotificationsPage</div> }))
vi.mock('../pages/SchedulePage', () => ({ default: () => <div data-testid="schedule-page">SchedulePage</div> }))
vi.mock('../pages/ArtifactsPage', () => ({ default: () => <div data-testid="artifacts-page">ArtifactsPage</div> }))
vi.mock('../pages/members/MembersPage', () => ({ default: () => <div data-testid="members-page">MembersPage</div> }))
vi.mock('../pages/SettingsPage', () => ({ default: () => <div data-testid="settings-page">SettingsPage</div> }))
vi.mock('../pages/apps/DiscoverPage', () => ({ default: () => <div data-testid="discover-page">DiscoverPage</div> }))
vi.mock('../pages/apps/LibraryPage', () => ({ default: () => <div data-testid="library-page">LibraryPage</div> }))
// The docked terminal mounts a real xterm, which the test DOM has no canvas for.
vi.mock('../components/CliPanel', () => ({
  default: () => <div data-testid="cli-panel" />,
  disposeTerminalSession: vi.fn(),
  useDeleteTerminalSession: () => vi.fn(),
}))
vi.mock('../components/MobileConnectModal', () => ({
  default: () => <div data-testid="mobile-connect-modal" />,
}))
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => ({ subscribeLogs: () => {} }) }))
vi.mock('../hooks/useAgents', () => ({ useAgents: vi.fn(() => ({ agents: [{ name: 'ajcrew' }, { name: 'reviewer' }, { name: 'oracle' }], defaultAgent: 'ajcrew' })) }))
vi.mock('../providers/context', () => ({ useProvider: () => ({ id: 'acp' }) }))
vi.mock('../components/MarkdownRenderer', () => ({ default: ({ content }: { content: string }) => <span>{content}</span>, Lightbox: () => null }))
vi.mock('../api/client', () => ({
  api: {
    chatSlots: vi.fn().mockResolvedValue([]),
    notifications: vi.fn().mockResolvedValue({ notifications: [] }),
    status: vi.fn().mockResolvedValue({ uptime: '1h', sessions: 0, messages: 0, cron_jobs: 0, subagents: 0, lessons: 0 }),
    sessionsUsage: vi.fn().mockResolvedValue({ usage: { credits_used: 3044, credits_covered: 3044, credits_overage: 0, credits_plan: 10000, resets: '2026-07-01', plan: 'KIRO POWER', cost_usd: 0, overage_rate: '0.04', bonus_credits: [{ name: 'Launch bonus', used: 250, total: 1000, days_left: 30 }], email: 'owner@example.com', account_type: 'Social' } }),
    listApps: vi.fn().mockResolvedValue([]),
    // A NON-Kiro harness by default, so the credit pill's Kiro-only surfaces
    // (the no-reading dash) stay off unless a test names the kiro backend.
    ajcrewConfig: vi.fn().mockResolvedValue({ agent: { acp_backend: 'claude' } }),
    system: vi.fn().mockResolvedValue({ mem_used_gb: 4.0, mem_total_gb: 16.0, cpu_pct: 25.0, disk_total_gb: 100.0, disk_free_gb: 60.0 }),
    chatSlotAgent: vi.fn().mockResolvedValue({}),
    // The left dock reads the roster; an empty one keeps its notice out of these frames.
    members: vi.fn().mockResolvedValue({ members: [] }),
    chatSlotReasoningEffort: vi.fn().mockResolvedValue({}),
    chatSlotModel: vi.fn().mockResolvedValue({}),
    chatMode: vi.fn().mockResolvedValue({}),
    listInstances: vi.fn().mockResolvedValue({ instances: [], warm_set_cap: 5 }),
    themes: vi.fn().mockResolvedValue({ themes: [] }),
    themeDetail: vi.fn().mockResolvedValue({}),
    themeBoot: vi.fn().mockResolvedValue({
      mode: '',
      color: '',
      onboarded: true,
      import_onboarded: true,
    }),
    updateThemeConfig: vi.fn().mockResolvedValue({}),
    onboardingImportScan: vi.fn().mockResolvedValue({
      sources: [],
      skipped: [],
      merge_only: true,
    }),
    onboardingImportState: vi.fn().mockResolvedValue({}),
    // The first-run Privacy chapter renders the real TelemetryToggle.
    beaconStatus: vi.fn().mockResolvedValue({
      enabled: true,
      would_send: true,
      reason: 'ready',
      endpoint_configured: true,
      env_override: false,
      env_var: 'AJCREW_TELEMETRY_DISABLED',
    }),
    patchConfig: vi.fn().mockResolvedValue({}),
    createChatSlot: vi.fn().mockResolvedValue({ key: 'feature-slot', title: 'feature-slot', messages: 0, running: false }),
    chatSlotContext: vi.fn().mockResolvedValue({ ok: true }),
    sendChat: vi.fn().mockResolvedValue({ ok: true }),
    mobileConnectMethods: vi.fn().mockResolvedValue({ methods: [{ id: 'link', kind: 'login_link' }] }),
  },
  // Default to "no auth banner showing" so existing App tests render the
  // normal connected/offline pill paths. The dedicated auth-banner
  // suppression test lives in App.offlinePill.test.tsx.
  isAuthBannerShown: vi.fn(() => false),
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  },
}))

// Mock matchMedia for useTheme and useIsMobile (jsdom doesn't provide it)
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: query === '(prefers-color-scheme: dark)',
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })),
})

// ResizeObserver stub for jsdom (used by SegmentedControl)
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as typeof ResizeObserver


const SETTLE = namedCeiling('SHELL_SETTLED', 5000)

/** Everything the shell starts at mount has landed: the 600ms timer that
 *  retires the entrance class, and each mount-time query. */
const shellSettled = (queryClient: { isFetching: () => number }) =>
  waitFor(() => {
    expect(screen.getByTestId('dashboard-shell')).not.toHaveClass('animate-rise')
    expect(queryClient.isFetching()).toBe(0)
  }, SETTLE)

/** Mount the shell in the Simple layout and wait for what it starts by itself. */
async function mountSimple(options: { route?: string; preloadedState?: Partial<RootState> } = {}) {
  const rendered = renderWithProviders(<App />, { route: options.route ?? '/chat', preloadedState: options.preloadedState })
  await shellSettled(rendered.queryClient)
  return rendered
}

const rail = () => screen.getByRole('navigation')
const railButton = (name: string) => within(rail()).getByRole('button', { name })
const header = () => document.querySelector('header.topbar') as HTMLElement
const slot = (key: string, title: string, extra: Partial<ChatSlot> = {}) =>
  ({ key, title, agent: 'ajcrew', messages: 2, running: false, ...extra }) as unknown as ChatSlot

beforeEach(() => {
  localStorage.setItem(SHELL_LAYOUT_KEY, 'simple')
  __resetFocusMode()
  setTerminalEnabledFlag(true)
  __resetBottomTerminal()
  server.use(http.get('/api/terminal/sessions', () => HttpResponse.json({ enabled: true, sessions: [] })))
})

afterEach(() => {
  act(() => {
    __resetBottomTerminal()
    setTerminalEnabledFlag(false)
    __resetFocusMode()
  })
  for (const key of [SHELL_LAYOUT_KEY, 'mc-simple-nav', 'mc-simple-more', 'mc-nav', 'mc-simple-topbar-capsule-collapsed', 'mc-topbar-metrics', 'mc-topbar-search']) {
    localStorage.removeItem(key)
  }
})

describe('Simple layout: sidebar', () => {
  it('draws brand and New chat, the recent chats, three destinations, More and Settings, in that order', async () => {
    await mountSimple()
    const nav = rail()
    const newChat = railButton('New chat')
    const recents = within(nav).getByTestId('simple-recent-chats')
    const schedule = railButton('Schedule')
    const artifacts = railButton('Artifacts')
    const mates = railButton('Bots')
    const more = railButton('More')
    const settings = railButton('Settings')
    const order = [newChat, recents, schedule, artifacts, mates, more, settings]
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING, `item ${i} follows item ${i - 1}`).toBeTruthy()
    }
    // The brand row leads the sidebar, and is itself a way to collapse it.
    const brand = nav.querySelector('[data-ui-location="shell.nav-toggle"]') as HTMLElement
    expect(brand).toHaveAccessibleName('Collapse sidebar')
    expect(brand.compareDocumentPosition(newChat) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // Folded until asked for: the remaining destinations are not on the rail yet.
    expect(more).toHaveAttribute('aria-pressed', 'false')
    expect(within(nav).queryByTestId('simple-more-group')).toBeNull()
    for (const name of ['Discover', 'Library', 'Terminal', 'Connect your phone', 'Customize']) {
      expect(within(nav).queryByText(name), name).toBeNull()
    }
  })

  it('carries no promo links', async () => {
    await mountSimple()
    expect(screen.queryByText('Star us')).toBeNull()
    expect(screen.queryByText('Report issue')).toBeNull()
    expect(screen.queryByLabelText(/Discord/)).toBeNull()
    expect(screen.queryByText('Request a Feature')).toBeNull()
    expect(document.querySelector('a[href*="discord"]')).toBeNull()
  })

  it('has no separate Sessions row: the chats are listed in the sidebar itself', async () => {
    const { store } = await mountSimple()
    expect(within(rail()).queryByRole('button', { name: 'Sessions' })).toBeNull()
    expect(within(rail()).getByText('No chats yet')).toBeInTheDocument()
    act(() => {
      store.dispatch(addSlotOptimistic(slot('s1', 'Fix the login page')))
      store.dispatch(addSlotOptimistic(slot('s2', 'Plan the release')))
    })
    const list = within(rail()).getByRole('list', { name: 'Recent' })
    expect(within(list).getByRole('button', { name: 'Fix the login page' })).toHaveAttribute('data-slot-key', 's1')
    expect(within(list).getByRole('button', { name: 'Plan the release' })).toHaveAttribute('data-slot-key', 's2')
    expect(within(rail()).queryByText('No chats yet')).toBeNull()
  })

  it('reaches Schedule, Artifacts and Bots in one click each', async () => {
    await mountSimple()
    fireEvent.click(railButton('Schedule'))
    expect(await screen.findByTestId('schedule-page')).toBeInTheDocument()
    expect(railButton('Schedule')).toHaveClass('nav-active')
    fireEvent.click(railButton('Artifacts'))
    expect(await screen.findByTestId('artifacts-page')).toBeInTheDocument()
    fireEvent.click(railButton('Bots'))
    expect(await screen.findByTestId('members-page')).toBeInTheDocument()
  })

  it('reaches Settings in one click', async () => {
    await mountSimple()
    fireEvent.click(railButton('Settings'))
    expect(await screen.findByTestId('settings-page')).toBeInTheDocument()
    expect(railButton('Settings')).toHaveClass('nav-active')
  })

  it('creates a chat from New chat, the way the new-chat shortcut does', async () => {
    const { api } = await import('../api/client')
    const create = vi.mocked(api.createChatSlot)
    create.mockClear()
    await mountSimple()
    await act(async () => { fireEvent.click(railButton('New chat')) })
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('chat-page')).toBeInTheDocument()
  })

  it('reaches Discover, Library and Customize in two clicks, through More', async () => {
    await mountSimple()
    fireEvent.click(railButton('More'))
    const group = within(rail()).getByRole('group', { name: 'More' })
    expect(railButton('More')).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(within(group).getByRole('button', { name: 'Discover' }))
    expect(await screen.findByTestId('discover-page')).toBeInTheDocument()
    fireEvent.click(railButton('Library'))
    expect(await screen.findByTestId('library-page')).toBeInTheDocument()
    fireEvent.click(railButton('Customize'))
    expect(await screen.findByTestId('capabilities-page')).toBeInTheDocument()
    expect(railButton('Customize')).toHaveClass('nav-active')
  })

  it('opens the terminal and the phone dialog in two clicks, through More', async () => {
    await mountSimple()
    fireEvent.click(railButton('More'))
    const terminal = await waitFor(() => railButton('Terminal'))
    expect(terminal).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(terminal)
    await waitFor(() => expect(railButton('Terminal')).toHaveAttribute('aria-pressed', 'true'))
    fireEvent.click(railButton('Connect your phone'))
    expect(await screen.findByTestId('mobile-connect-modal')).toBeInTheDocument()
  })

  it('remembers More, and never folds away the page on screen', async () => {
    const first = await mountSimple()
    fireEvent.click(railButton('More'))
    expect(localStorage.getItem('mc-simple-more')).toBe('1')
    fireEvent.click(railButton('More'))
    expect(localStorage.getItem('mc-simple-more')).toBe('0')
    expect(within(rail()).queryByTestId('simple-more-group')).toBeNull()
    first.unmount()
    // More is stored closed, and the page on screen is one it holds.
    await mountSimple({ route: '/capabilities' })
    expect(await screen.findByTestId('capabilities-page')).toBeInTheDocument()
    expect(within(rail()).getByTestId('simple-more-group')).toBeInTheDocument()
    expect(railButton('Customize')).toHaveClass('nav-active')
  })

  it('collapses to an icon rail under its own key, keeping every destination', async () => {
    await mountSimple()
    const toggle = screen.getByTestId('simple-sidebar-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveAccessibleName('Collapse sidebar')
    fireEvent.click(toggle)
    expect(localStorage.getItem('mc-simple-nav')).toBe('1')
    // The Advanced rail's own collapse is left as it was.
    expect(localStorage.getItem('mc-nav')).toBeNull()
    expect(screen.getByTestId('simple-sidebar-toggle')).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByTestId('simple-sidebar-toggle')).toHaveAccessibleName('Expand sidebar')
    expect(within(rail()).queryByTestId('simple-recent-chats')).toBeNull()
    for (const name of ['New chat', 'All chats', 'More']) expect(railButton(name), name).toBeInTheDocument()
    for (const name of ['Schedule', 'Artifacts', 'Bots', 'Settings']) expect(railButton(name), name).toBeInTheDocument()
    fireEvent.click(railButton('More'))
    for (const name of ['Discover', 'Library', 'Customize']) expect(railButton(name), name).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('simple-sidebar-toggle'))
    expect(localStorage.getItem('mc-simple-nav')).toBe('0')
    expect(within(rail()).getByTestId('simple-recent-chats')).toBeInTheDocument()
  })

  it('collapses from the brand row too, in step with the top-bar toggle', async () => {
    await mountSimple()
    const brand = () => rail().querySelector('[data-ui-location="shell.nav-toggle"]') as HTMLElement
    fireEvent.click(brand())
    expect(screen.getByTestId('simple-sidebar-toggle')).toHaveAttribute('aria-expanded', 'false')
    expect(brand()).toHaveAccessibleName('Expand sidebar')
    expect(localStorage.getItem('mc-simple-nav')).toBe('1')
  })
})

describe('Simple layout: top bar', () => {
  it('keeps the sidebar toggle, search and notifications, and drops the rest', async () => {
    await mountSimple()
    const bar = header()
    expect(within(bar).getByTestId('simple-sidebar-toggle')).toBeInTheDocument()
    const search = within(bar).getByTestId('simple-search')
    expect(search).toHaveAccessibleName('Search sessions, files, and commands')
    expect(within(bar).getByRole('button', { name: /notifications/i })).toBeInTheDocument()
    expect(bar).toHaveClass('topbar-no-search')
    expect(within(bar).getByTestId('simple-topbar-centre')).toBeEmptyDOMElement()
    expect(within(bar).queryByTestId('focus-mode-toggle')).toBeNull()
    expect(within(bar).queryByText('Request a Feature')).toBeNull()
    // The readouts are folded behind the connection glyph until asked for.
    expect(within(bar).queryByLabelText('System metrics')).toBeNull()
    expect(within(bar).queryByText(/KIRO POWER/)).toBeNull()
  })

  it('opens Search everywhere from the icon', async () => {
    await mountSimple()
    expect(screen.queryByRole('dialog', { name: 'Search everywhere' })).toBeNull()
    fireEvent.click(screen.getByTestId('simple-search'))
    expect(screen.getByRole('dialog', { name: 'Search everywhere' })).toBeInTheDocument()
  })

  it('opens Search everywhere from the shortcut', async () => {
    await mountSimple()
    act(() => { fireEvent.keyDown(window, { key: 'k', ctrlKey: true }) })
    expect(screen.getByRole('dialog', { name: 'Search everywhere' })).toBeInTheDocument()
  })

  it('unfolds the readouts from the connection glyph, under its own key', async () => {
    await mountSimple()
    const glyph = header().querySelector('.tb-capsule [data-conn-state]')!.closest('button')!
    expect(glyph).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(glyph)
    expect(await within(header()).findByLabelText('System metrics')).toBeInTheDocument()
    expect(localStorage.getItem('mc-simple-topbar-capsule-collapsed')).toBe('0')
    // The Advanced bar's own fold is not what was opened.
    fireEvent.click(glyph)
    expect(localStorage.getItem('mc-simple-topbar-capsule-collapsed')).toBe('1')
    expect(localStorage.getItem('mc-topbar-capsule-collapsed')).not.toBe('1')
  })

  it('keeps focus mode on its chord', async () => {
    await mountSimple()
    expect(focusModeEnabled()).toBe(false)
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'M', code: 'KeyM', altKey: true, shiftKey: true, bubbles: true }))
    })
    expect(focusModeEnabled()).toBe(true)
  })
})

describe('Simple layout: nothing that needs the person is folded away', () => {
  it('still shows a metrics failure', async () => {
    const { api } = await import('../api/client')
    const sysMock = vi.mocked(api.system)
    sysMock.mockRejectedValueOnce(new Error('boom'))
    localStorage.setItem('mc-topbar-metrics', '1')
    const { queryClient } = renderWithProviders(<App />, { route: '/chat' })
    expect(await screen.findByText(/metrics unavailable/)).toBeInTheDocument()
    // The readouts are still folded: the failure shows through the fold.
    expect(header().querySelector('.tb-capsule [data-conn-state]')!.closest('button')).toHaveAttribute('aria-expanded', 'false')
    await shellSettled(queryClient)
    sysMock.mockResolvedValue({ mem_used_gb: 4.0, mem_total_gb: 16.0, cpu_pct: 25.0, disk_total_gb: 100.0, disk_free_gb: 60.0 } as never)
  })

  it('still says the gateway is offline', async () => {
    const { queryClient } = renderWithProviders(<App />, {
      route: '/chat',
      preloadedState: { dashboard: { connected: false, status: { platform: 'darwin' }, slots: [], approvalMode: 'normal' } as unknown as RootState['dashboard'] },
    })
    const glyph = header().querySelector('[data-conn-state]')!
    expect(glyph.getAttribute('data-conn-state')).toBe('offline')
    expect(glyph.closest('button')!.getAttribute('aria-label')).toMatch(/reconnecting/i)
    await shellSettled(queryClient)
  })

  it('shows a spent credits allowance through the fold, and not a healthy one', async () => {
    const { api } = await import('../api/client')
    const usage = vi.mocked(api.sessionsUsage)
    const original = await api.sessionsUsage()
    const reading = (used: number) => ({ usage: { ...original.usage, credits_used: used, credits_covered: used, bonus_credits: [] } })
    const credits = () => within(header()).queryByRole('button', { name: /^Kiro account & credits/ })
    try {
      usage.mockResolvedValue(reading(3044) as never)
      const first = await mountSimple()
      expect(header().querySelector('.tb-capsule [data-conn-state]')).not.toBeNull()
      expect(credits()).toBeNull()
      first.unmount()

      usage.mockResolvedValue(reading(10000) as never)
      await mountSimple()
      await waitFor(() => expect(credits()).not.toBeNull(), SETTLE)
      expect(credits()).toHaveTextContent('10K/10K')
    } finally {
      usage.mockResolvedValue(original as never)
    }
  })

  it('shows a failed credits read through the fold on a Kiro harness', async () => {
    const { api } = await import('../api/client')
    const usage = vi.mocked(api.sessionsUsage)
    const config = vi.mocked(api.ajcrewConfig)
    const original = await api.sessionsUsage()
    usage.mockRejectedValue(new Error('usage read failed'))
    config.mockResolvedValue({ agent: { acp_backend: 'kiro' } } as never)
    try {
      await mountSimple()
      await waitFor(() => expect(within(header()).getByRole('button', { name: 'Kiro account & credits — unavailable' })).toBeInTheDocument(), SETTLE)
    } finally {
      usage.mockResolvedValue(original as never)
      config.mockResolvedValue({ agent: { acp_backend: 'claude' } } as never)
    }
  })

  it('marks a chat that is waiting on an approval, a question, or unread', async () => {
    const { store } = await mountSimple()
    act(() => {
      store.dispatch(addSlotOptimistic(slot('quiet', 'Quiet chat')))
      store.dispatch(addSlotOptimistic(slot('ask', 'Run the migration', { pending_approval: true })))
      store.dispatch(addSlotOptimistic(slot('q', 'Pick a database', { needs_input: true })))
      store.dispatch(addSlotOptimistic(slot('new', 'Weekly summary')))
      store.dispatch(markSlotUnread('new'))
    })
    const list = within(rail()).getByRole('list', { name: 'Recent' })
    const row = (key: string) => list.querySelector(`[data-slot-key="${key}"]`) as HTMLElement
    expect(within(row('ask')).getByRole('img')).toHaveAccessibleName('needs permission')
    expect(within(row('q')).getByRole('img')).toHaveAccessibleName('waiting on you')
    expect(within(row('new')).getByRole('img')).toHaveAccessibleName('unread')
    expect(within(row('quiet')).queryByRole('img')).toBeNull()
  })
})

describe('Simple layout: switching', () => {
  it('returns the Advanced shell at once, and Simple again, without a reload', async () => {
    await mountSimple()
    expect(screen.getByTestId('simple-sidebar-toggle')).toBeInTheDocument()

    // Async: the top bar's contents change, and its collapse ladder re-measures
    // from a mutation callback.
    await act(async () => { writeShellLayout('advanced') })
    expect(screen.queryByTestId('simple-sidebar-toggle')).toBeNull()
    expect(screen.queryByTestId('simple-recent-chats')).toBeNull()
    expect(screen.getByTestId('focus-mode-toggle')).toBeInTheDocument()
    expect(screen.getByText('Star us')).toBeInTheDocument()
    expect(within(rail()).getByRole('button', { name: 'Sessions' })).toBeInTheDocument()
    expect(header()).not.toHaveClass('topbar-no-search')

    await act(async () => { writeShellLayout('simple') })
    expect(screen.getByTestId('simple-sidebar-toggle')).toBeInTheDocument()
    expect(screen.getByTestId('simple-recent-chats')).toBeInTheDocument()
    expect(screen.queryByText('Star us')).toBeNull()
  })

  it('draws the Advanced shell for an install that stored Advanced', async () => {
    localStorage.setItem(SHELL_LAYOUT_KEY, 'advanced')
    await mountSimple()
    expect(screen.queryByTestId('simple-sidebar-toggle')).toBeNull()
    expect(screen.queryByTestId('simple-search')).toBeNull()
    expect(screen.getByText('Star us')).toBeInTheDocument()
  })
})
