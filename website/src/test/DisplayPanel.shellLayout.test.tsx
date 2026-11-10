// SettingsSelect wraps Radix Select, which needs pointer APIs jsdom lacks; the
// Display panel's View section renders one (Language), so the same lightweight
// mock DisplayPanel.language.test.tsx uses stands in for it.
vi.mock('@radix-ui/react-select', async () => await import('./__mocks__/@radix-ui/react-select'))

/**
 * The Layout setting (Settings -> Display -> View): a two-way choice between
 * the Simple and Advanced shells, stored at `mc-shell-layout` through
 * useShellLayout. Simple is selected on an install with nothing stored; the
 * choice reaches every other reader in the tab at once (the probe stands in
 * for the shell); and the generated settings registry lists it, which is what
 * the command palette's settings search and the in-app setting links read.
 * The shell half is in App.simpleLayout.test.tsx. The panel mocks are
 * topbarSearch.test.tsx's.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import React from 'react'

import { renderWithProviders } from './helpers'
import { SHELL_LAYOUT_KEY, __setShellLayoutFallbackForTests, useShellLayout } from '../hooks/useShellLayout'
import { SETTINGS_REGISTRY } from '../components/commandPalette/settingsRegistry.gen'
import en from '../i18n/locales/en.manual.json'

vi.mock('../hooks/ZoomProvider', () => ({
  useZoomCtx: () => ({
    zoom: 100, zoomSupported: true, zoomIn: vi.fn(), zoomOut: vi.fn(), reset: vi.fn(),
    family: 'sans', setFontFamily: vi.fn(), cycleFamily: vi.fn(),
  }),
}))
vi.mock('../hooks/useTheme', () => ({
  useTheme: () => ({
    preference: 'dark', setTheme: vi.fn(), colorTheme: 'default', setColorTheme: vi.fn(),
    allThemes: [{ value: 'default', label: 'Default', custom: false }], theme: 'dark',
    themeVersion: 0, themeSwitching: false, addCustomTheme: vi.fn(), deleteCustomTheme: vi.fn(),
    loadCustomThemes: vi.fn(),
  }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
  CUSTOM_THEMES_CHANGED_EVENT: 'custom-themes-changed',
}))
vi.mock('../hooks/useUIMode', () => ({
  useUIMode: () => ({ uiMode: 'chat', setUIMode: vi.fn(), toggleUIMode: vi.fn() }),
  UIModeProvider: ({ children }: { children: React.ReactNode }) => children,
}))
vi.mock('../hooks/useSessionPalette', () => ({
  useSessionPalette: () => ({
    paletteColors: ['#ff0000', '#00ff00', '#0000ff'], colorMode: 'tint' as const,
    paletteName: 'trailhead', intensity: 'clear',
    boost: { activePct: [60, 60, 60], idlePct: [30, 30, 30] },
  }),
}))

import { DisplayPanel } from '../pages/settings/DisplayPanel'

/** A second reader of the setting, mounted beside the control as the shell is. */
function ShellProbe() {
  const [layout] = useShellLayout()
  return <output data-testid="shell-probe">{layout}</output>
}

function renderLayoutControl() {
  renderWithProviders(<><DisplayPanel /><ShellProbe /></>, { route: '/settings?tab=display&sub=view' })
  const group = screen.getByRole('radiogroup', { name: 'Layout' })
  const option = (name: string) => within(group).getByRole('radio', { name })
  return { group, simple: option('Simple'), advanced: option('Advanced') }
}

beforeEach(() => {
  localStorage.removeItem(SHELL_LAYOUT_KEY)
  // The shipped default, not the suite's Advanced pin.
  __setShellLayoutFallbackForTests(null)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  localStorage.removeItem(SHELL_LAYOUT_KEY)
  __setShellLayoutFallbackForTests(null)
})

describe('Settings → Display → View: Layout', () => {
  it('offers Simple and Advanced, with Simple selected on a fresh install', () => {
    const { group, simple, advanced } = renderLayoutControl()
    expect(within(group).getAllByRole('radio')).toHaveLength(2)
    expect(simple).toHaveAttribute('aria-checked', 'true')
    expect(advanced).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByTestId('shell-probe')).toHaveTextContent('simple')
    // Selected is shown, not yet stored: only a choice writes the key.
    expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBeNull()
  })

  it('sits first in the View card, ahead of Interface', () => {
    const { group } = renderLayoutControl()
    const groups = screen.getAllByRole('radiogroup')
    const names = groups.map(g => g.getAttribute('aria-label'))
    expect(names.indexOf('Layout')).toBeLessThan(names.indexOf('Interface'))
    expect(groups).toContain(group)
  })

  it('stores the choice and moves the shell at once, both ways', () => {
    const { simple, advanced } = renderLayoutControl()
    fireEvent.click(advanced)
    expect(advanced).toHaveAttribute('aria-checked', 'true')
    expect(simple).toHaveAttribute('aria-checked', 'false')
    expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBe('advanced')
    expect(screen.getByTestId('shell-probe')).toHaveTextContent('advanced')

    fireEvent.click(simple)
    expect(simple).toHaveAttribute('aria-checked', 'true')
    expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBe('simple')
    expect(screen.getByTestId('shell-probe')).toHaveTextContent('simple')
  })

  it('shows a stored Advanced choice as selected', () => {
    localStorage.setItem(SHELL_LAYOUT_KEY, 'advanced')
    const { simple, advanced } = renderLayoutControl()
    expect(advanced).toHaveAttribute('aria-checked', 'true')
    expect(simple).toHaveAttribute('aria-checked', 'false')
  })

  it('still applies the choice to the page when the store refuses the write', () => {
    const { advanced } = renderLayoutControl()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    fireEvent.click(advanced)
    expect(advanced).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByTestId('shell-probe')).toHaveTextContent('advanced')
    expect(localStorage.getItem(SHELL_LAYOUT_KEY)).toBeNull()
  })
})

describe('settings registry', () => {
  it('lists the Layout setting under Display → View, so search and setting links find it', () => {
    const entry = SETTINGS_REGISTRY.find(e => e.id === 'display.layout')
    expect(entry).toBeDefined()
    expect(entry).toMatchObject({
      label: 'Layout',
      labelKey: 'simpleLayout.layout_label',
      tab: 'display',
      type: 'buttonGroup',
      params: { sub: 'view' },
    })
    expect(entry!.hint).toBe(en.simpleLayout.layout_hint)
    expect(SETTINGS_REGISTRY.filter(e => e.id === 'display.layout')).toHaveLength(1)
  })
})
