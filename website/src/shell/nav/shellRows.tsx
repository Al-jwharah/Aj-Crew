import { Compass, LayoutGrid, SquareTerminal, Smartphone } from 'lucide-react'
import { toggleBottomTerminal } from '../../hooks/useBottomTerminal'
import { focusPopout as focusTerminalPopout } from '../../utils/terminalPopout'
import { i18nT } from '../../i18n/t'
import { uiLocation } from '../../uiLocations/uiLocation'
import { surfaceLabel } from '../../surfaces/registry'
import { NAV_ITEMS } from './navItems'
import { NavItem, NavBadge } from './navRow'
import type { AppShell } from '../appShell'

/**
 * Rail rows that both shell layouts draw: the Advanced rail (`navRail.tsx`)
 * and the Simple sidebar (`simpleRail.tsx`). One definition each, so a row
 * behaves the same wherever it is drawn.
 */
type RowProps = { shell: AppShell; collapsed: boolean }

/** Apps: Discover (the storefront) and Library (installed apps). */
export function AppsNavRows({ shell, collapsed }: RowProps) {
  const { discoverNavActive, libraryNavActive, closeMobileNav, discoverBadges } = shell
  return (
    <>
      <NavItem
        navId="apps"
        path="/apps"
        label={i18nT('nav.discover')}
        icon={<Compass size={20} />}
        active={discoverNavActive}
        collapsed={collapsed}
        onClick={closeMobileNav}
        badge={<NavBadge navId="apps" collapsed={collapsed} appBadges={discoverBadges} />}
      />
      <NavItem
        navId="apps-library"
        path="/apps/library"
        label={i18nT('nav.library')}
        icon={<LayoutGrid size={20} />}
        active={libraryNavActive}
        collapsed={collapsed}
        onClick={closeMobileNav}
      />
    </>
  )
}

/** Toggles the docked terminal panel; a popped-out terminal is focused instead. */
export function TerminalNavRow({ shell, collapsed }: RowProps) {
  const { terminalEnabled, bottomTerminalOpen, terminalPoppedOut, closeMobileNav, activeSlotProject } = shell
  if (!terminalEnabled) return null
  return (
    <NavItem
      path="#"
      label={i18nT('app.terminal')}
      icon={<SquareTerminal size={20} />}
      /* This row TOGGLES the docked panel instead of navigating, so
         "active" tracks the panel's open flag rather than the route.
         Without it the row only lit on hover, leaving no indication
         the panel below was open once the pointer moved away. */
      active={bottomTerminalOpen || terminalPoppedOut}
      pressed={bottomTerminalOpen || terminalPoppedOut}
      collapsed={collapsed}
      onClick={closeMobileNav}
      /* While popped out: focus only (a refused programmatic
         focus is a harmless no-op). Explicit re-dock lives in the
         TerminalDetachedBar below -- never a timing heuristic. */
      onClickOverride={() => { if (terminalPoppedOut) focusTerminalPopout(); else toggleBottomTerminal(activeSlotProject) }}
      {...uiLocation('shell.terminal')}
    />
  )
}

/** Opens the connect-your-phone dialog; same toggle contract as the terminal row. */
export function ConnectPhoneNavRow({ shell, collapsed }: RowProps) {
  const { hasRenderableMobileConnect, mobileConnectOpen, setMobileConnectOpen, closeMobileNav } = shell
  if (!hasRenderableMobileConnect) return null
  return (
    <NavItem
      path="#"
      label={i18nT('app.connect_your_phone')}
      icon={<Smartphone size={20} />}
      active={mobileConnectOpen}
      pressed={mobileConnectOpen}
      collapsed={collapsed}
      onClick={closeMobileNav}
      onClickOverride={() => setMobileConnectOpen(true)}
      {...uiLocation('shell.connect-phone')}
    />
  )
}

/** Settings, with the dot that says an update is available. */
export function SettingsNavRow({ shell, collapsed }: RowProps) {
  const { settingsDotLabel, activePath, closeMobileNav } = shell
  const s = NAV_ITEMS.find(n => n.id === 'settings')!
  return (
    <NavItem
      path={s.path}
      label={surfaceLabel(s)}
      icon={s.icon}
      active={activePath === s.path || activePath.startsWith(s.path + '/')}
      collapsed={collapsed}
      onClick={closeMobileNav}
      badge={settingsDotLabel ? <span title={settingsDotLabel.title} role="status" aria-label={settingsDotLabel.label} className={collapsed ? 'absolute top-1 right-1 w-2 h-2 bg-accent rounded-full z-10' : 'absolute top-1/2 -translate-y-1/2 right-2 w-2 h-2 bg-accent rounded-full z-10'} /> : undefined}
    />
  )
}
