import { useMemo } from 'react'
import { ChevronDown, Ellipsis, MessagesSquare, SquarePen } from 'lucide-react'
import { useAppDispatch, useAppSelector, useAppStore } from '../../store'
import { selectPersonSlots } from '../../store/dashboardSlice'
import { switchSlot } from '../../store/chatSlice'
import { useConnected } from '../../hooks/useConnected'
import { usePersistedBool } from '../../hooks/usePersistedBool'
import { useAskingNavigate } from '../../components/NavigationLeaveGuard'
import { focusComposerForOpenedSession } from '../../pages/chat/composerFocus'
import { comparePinnedThenSort, compareBySort } from '../../pages/chat/sessionOrder'
import { rankedPinnedKeys, reconcilePinnedSessionOrder } from '../../utils/pinnedSessionOrder'
import { isChatPageSurface } from '../../utils/channelOrigin'
import { sessionDisplayTitle } from '../../utils/sessionDisplayTitle'
import { appPathname } from '../../lib/basePath'
import { surfaceLabel } from '../../surfaces/registry'
import { isAppNavId } from '../../appNotificationBadges'
import { i18nT } from '../../i18n/t'
import type { ChatSlot } from '../../types'
import type { AppShell } from '../appShell'
import { SIMPLE_MORE_KEY, SIMPLE_RECENTS_LIMIT, readSessionsPinned, writeSessionsPinned } from '../../lib/simpleLayout'
import { NAV_ITEMS } from './navItems'
import { NavItem, NavBadge } from './navRow'
import { RailBrandToggle } from './railChrome'
import { isChatRoute } from './routeActive'
import { AppsNavRows, ConnectPhoneNavRow, SettingsNavRow, TerminalNavRow } from './shellRows'

/** The destinations the sidebar names outright, in this order; the rest sit under More. */
const PRIMARY_NAV_IDS = ['schedule', 'artifacts', 'members']

type ChatStatus = 'approval' | 'question' | 'running' | 'unread'

/** Same precedence as the sessions column: a request outranks activity, activity outranks unread. */
function chatStatus(slot: ChatSlot, unread: ReadonlySet<string>): ChatStatus | null {
  if (slot.pending_approval) return 'approval'
  if (slot.needs_input) return 'question'
  if (slot.running) return 'running'
  return unread.has(slot.key) ? 'unread' : null
}

const STATUS_DOT: Record<ChatStatus, string> = {
  approval: 'bg-warn',
  question: 'bg-info',
  running: 'bg-accent motion-safe:animate-pulse',
  unread: 'bg-ok',
}

function statusLabel(status: ChatStatus): string {
  if (status === 'approval') return i18nT('components.sessionTabStrip.status_permission')
  if (status === 'question') return i18nT('components.sessionTabStrip.status_question')
  if (status === 'running') return i18nT('components.sessionTabStrip.status_running')
  return i18nT('components.sessionTabStrip.status_unread')
}

/**
 * The person's chats, pinned first and then most recent first: the order the
 * sessions column's hover list uses, so a chat sits in the same place on both.
 */
export function recentChats(slots: readonly ChatSlot[]): ChatSlot[] {
  const rows = slots.filter(s => isChatPageSurface(s.surface ?? s.mode))
  const pinnedRows = rows.filter(s => s.pinned)
  const natural = [...pinnedRows].sort((a, b) => compareBySort(a, b, 'date-desc')).map(s => s.key)
  const order = reconcilePinnedSessionOrder(rankedPinnedKeys(rows), natural)
  const rank = new Map(order.map((key, index) => [key, index]))
  const pinned = new Set(pinnedRows.map(s => s.key))
  return [...rows].sort((a, b) => comparePinnedThenSort(a, b, 'date-desc', pinned, rank))
}

/** The recent chats, listed directly in the sidebar. */
function RecentChats({ shell, onAllChats }: { shell: AppShell; onAllChats: () => void }) {
  const { isChat } = shell
  const dispatch = useAppDispatch()
  const store = useAppStore()
  const navigate = useAskingNavigate()
  const connected = useConnected()
  const slots = useAppSelector(selectPersonSlots)
  const activeSlot = useAppSelector(s => s.chat.activeSlot)
  const unreadSlots = useAppSelector(s => s.dashboard.unreadSlots)
  const unread = useMemo(() => new Set(unreadSlots), [unreadSlots])
  const ordered = useMemo(() => recentChats(slots), [slots])
  const rows = ordered.slice(0, SIMPLE_RECENTS_LIMIT)

  const open = (key: string) => {
    if (!connected) return
    // Leaving another page asks its leave guard first; a refusal keeps the
    // person, and the chat they had open, where they were.
    if (!isChatRoute(appPathname()) && !navigate('/chat')) return
    const switched = dispatch(switchSlot({ key, announceOnMissing: true, gesture: true })).unwrap()
    focusComposerForOpenedSession(switched, key, store)
  }

  return (
    <div className="flex min-h-[72px] flex-1 flex-col" data-testid="simple-recent-chats">
      <div className="flex shrink-0 items-center gap-2 pr-2 pl-[18px] pt-3 pb-1">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-muted" title={i18nT('simpleLayout.recent')}>{i18nT('simpleLayout.recent')}</span>
        {/* The whole list (folders, search, sort, every row action) is the
            chat page's sessions column; this opens it. */}
        <button
          type="button"
          data-testid="simple-all-chats"
          onClick={onAllChats}
          className="shrink-0 cursor-pointer rounded-md border-none bg-transparent px-2 py-0.5 text-[12px] text-muted transition-colors hover:bg-bg-hover hover:text-text"
        >
          {i18nT('simpleLayout.all_chats')}
        </button>
      </div>
      <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto overscroll-y-none scrollbar-none px-2 pb-1" aria-label={i18nT('simpleLayout.recent')}>
        {rows.length === 0 && (
          <li className="px-2.5 py-1.5 text-[13px] text-muted">{i18nT('simpleLayout.no_chats')}</li>
        )}
        {rows.map(slot => {
          const active = isChat && slot.key === activeSlot
          const status = chatStatus(slot, unread)
          const label = sessionDisplayTitle(slot)
          return (
            <li key={slot.key}>
              <button
                type="button"
                data-slot-key={slot.key}
                aria-current={active ? 'page' : undefined}
                aria-disabled={!connected}
                title={label}
                onClick={() => open(slot.key)}
                className={`flex w-full items-center gap-2 rounded-md border-none px-2.5 py-1.5 text-left text-[13px] transition-colors duration-200 ${
                  active
                    ? 'bg-accent-subtle font-semibold text-text-strong'
                    : connected
                      ? 'bg-transparent text-text hover:bg-bg-hover/60'
                      : 'bg-transparent text-muted opacity-50'
                } ${connected ? 'cursor-pointer' : 'cursor-not-allowed'}`}
              >
                <span className="min-w-0 flex-1 truncate">{label}</span>
                {status && (
                  <span role="img" aria-label={statusLabel(status)} title={statusLabel(status)} className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[status]}`} />
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * The Simple layout's sidebar: brand and New chat, the recent chats, at most
 * three named destinations, everything else under More, and Settings last.
 * Collapsed, the same rows are an icon rail and the chat list gives way to one
 * All chats row (expanded, All chats is the list header's own control).
 *
 * Nothing the Advanced rail reaches is missing; the rows are the same
 * components with the same behaviour (`shellRows.tsx`, `NavItem`). The
 * community links are the one deliberate omission.
 */
export function SimpleRailBody({ shell }: { shell: AppShell }) {
  const {
    effectiveCollapsed: collapsed, toggleNav, avatar, branding, botName, advertisedNavItems, sortedAppGroup,
    navRowActive, appBadges, railAppBadges, railAppRunStates, isChat, navigate, startNewChat, newChatPending,
    discoverNavActive, libraryNavActive, bottomTerminalOpen, terminalPoppedOut, mobileConnectOpen,
  } = shell
  const [moreStored, setMoreStored] = usePersistedBool(SIMPLE_MORE_KEY, false)

  const row = (n: { path: string; id: string; label: string; labelKey?: string; icon: React.ReactNode; appName?: string }) => (
    <NavItem
      key={n.id}
      navId={n.id}
      path={n.path}
      label={surfaceLabel(n)}
      icon={n.icon}
      active={navRowActive(n.path)}
      collapsed={collapsed}
      badge={<NavBadge navId={n.id} collapsed={collapsed} appBadges={isAppNavId(n.id) ? railAppBadges : appBadges} runState={n.appName ? railAppRunStates[n.appName] : undefined} />}
    />
  )

  const main = advertisedNavItems.filter(n => n.group === 'Main' && n.id !== 'chat')
  const primary = PRIMARY_NAV_IDS.flatMap(id => main.filter(n => n.id === id))
  // Whatever else the rail advertises (a Customize tab the person pinned).
  const extra = main.filter(n => !PRIMARY_NAV_IDS.includes(n.id))
  const customize = NAV_ITEMS.find(n => n.id === 'capabilities')!
  const moreRows = [...extra, ...sortedAppGroup, customize]
  // A destination under More that is the page on screen, or a panel it opened,
  // keeps the group open: where the person is must never be folded away.
  const moreHoldsCurrent = discoverNavActive || libraryNavActive || bottomTerminalOpen || terminalPoppedOut
    || mobileConnectOpen || moreRows.some(n => navRowActive(n.path))
  const moreOpen = moreStored || moreHoldsCurrent

  // All chats: the chat page with its sessions column (folders, search, sort,
  // every row action). On the chat page it toggles that column, as the
  // Advanced rail's Sessions row does.
  const allChats = () => {
    if (isChatRoute(appPathname())) {
      window.dispatchEvent(new Event('toggle-pin-chat-sidebar'))
      return
    }
    if (!readSessionsPinned(true)) writeSessionsPinned(true, true)
    navigate('/chat')
  }

  return (
    <>
      <div className="flex shrink-0 flex-col gap-0.5 px-2 pt-2">
        <RailBrandToggle effectiveCollapsed={collapsed} toggleNav={toggleNav} avatar={avatar} branding={branding} botName={botName} arrow={false} />
        <NavItem
          navId="chat"
          path="#"
          label={i18nT('pages.chat.sessionFlyout.new_chat')}
          icon={<SquarePen size={20} />}
          active={false}
          collapsed={collapsed}
          onClickOverride={() => { if (!newChatPending) startNewChat() }}
        />
        {collapsed && (
          <NavItem
            path="#"
            label={i18nT('simpleLayout.all_chats')}
            icon={<MessagesSquare size={20} />}
            active={isChat}
            collapsed
            onClickOverride={allChats}
          />
        )}
      </div>

      {collapsed ? <div className="min-h-0 flex-1" /> : <RecentChats shell={shell} onAllChats={allChats} />}

      <div className={`flex min-h-0 shrink flex-col gap-0.5 overflow-y-auto overscroll-y-none scrollbar-none px-2 pt-1 ${collapsed ? '' : 'max-h-[62%] border-t border-border'}`}>
        {primary.map(row)}
        <NavItem
          path="#"
          label={i18nT('simpleLayout.more')}
          icon={<Ellipsis size={20} />}
          active={false}
          pressed={moreOpen}
          collapsed={collapsed}
          onClickOverride={() => setMoreStored(!moreOpen)}
          badge={collapsed ? undefined : <ChevronDown size={14} aria-hidden className={`shrink-0 text-muted transition-transform duration-200 motion-reduce:transition-none ${moreOpen ? 'rotate-180' : ''}`} />}
        />
        {moreOpen && (
          <div role="group" aria-label={i18nT('simpleLayout.more')} data-testid="simple-more-group" className={`flex flex-col gap-0.5 ${collapsed ? '' : 'ml-3 border-l border-border pl-1.5'}`}>
            <AppsNavRows shell={shell} collapsed={collapsed} />
            {extra.map(row)}
            {sortedAppGroup.map(row)}
            <TerminalNavRow shell={shell} collapsed={collapsed} />
            <ConnectPhoneNavRow shell={shell} collapsed={collapsed} />
            {row(customize)}
          </div>
        )}
      </div>

      <div className="shrink-0 px-2 pt-1 pb-2">
        <SettingsNavRow shell={shell} collapsed={collapsed} />
      </div>
    </>
  )
}
