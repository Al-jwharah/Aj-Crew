/**
 * The roster filter matches what the roster shows.
 *
 * Each card and row labels a crewmate's memory by whose it is ("Private to
 * this bot", "Shared") and its Built from by a display name, never the ids the
 * binding stores. The filter only searched those hidden ids, so typing a word
 * the reader could see on a card ("Shared") hid every crewmate.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, cleanup } from '@testing-library/react'
import { renderWithProviders } from './helpers'
import { i18nT } from '../i18n/t'

globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as typeof ResizeObserver

const mockApi = vi.hoisted(() => ({
  ajcrewAgents: vi.fn(),
  agentsInstalled: vi.fn(),
  agentCatalog: vi.fn(),
  workspaces: vi.fn(),
  ajcrewConfig: vi.fn(),
  agentResolvedModel: vi.fn(),
  models: vi.fn(),
  members: vi.fn(),
  crons: vi.fn(),
  webhooks: vi.fn(),
}))
vi.mock('../api/client', () => ({ api: mockApi }))

import AjCrewAgentsPage from '../pages/AjCrewAgentsPage'

/** Owns its file and its memory: "Built from" reads as a mate, memory as private. */
const ADA = {
  name: 'ada', display_name: 'Ada', kiro_agent: 'ada', workspace: 'member-ada',
  memory_store: 'member-ada-ae2d738f', source: 'ajcrew', owns_mate_file: true,
}
/** On a shared store: memory reads as "Shared". */
const OPS = {
  name: 'ops', kiro_agent: 'oncall-agent', workspace: 'oncall', memory_store: 'team-mem', source: 'ajcrew',
}

beforeEach(() => {
  vi.clearAllMocks()
  mockApi.ajcrewAgents.mockResolvedValue({ agents: [ADA, OPS], default_agent: 'ajcrew' })
  mockApi.agentsInstalled.mockResolvedValue([])
  mockApi.agentCatalog.mockResolvedValue({ agents: [] })
  mockApi.workspaces.mockResolvedValue({ workspaces: [] })
  mockApi.ajcrewConfig.mockResolvedValue({
    memory_stores: { 'member-ada-ae2d738f': { memory_version: 2, owner_member: 'ada' }, 'team-mem': {} },
  })
  mockApi.agentResolvedModel.mockResolvedValue({ model: '' })
  mockApi.models.mockResolvedValue([])
  mockApi.members.mockResolvedValue({ members: [] })
  mockApi.crons.mockResolvedValue({ jobs: [] })
  mockApi.webhooks.mockResolvedValue({ tokens: [] })
})
afterEach(() => { vi.restoreAllMocks(); cleanup() })

const editButton = (name: string) => screen.queryByRole('button', { name: i18nT('pages.ajCrewAgentsPage.edit_crew_named', { name }) })

async function renderAndFilter(text: string) {
  renderWithProviders(<AjCrewAgentsPage />, { route: '/capabilities' })
  await screen.findByText(i18nT('pages.ajCrewAgentsPage.memory_label_shared'))
  fireEvent.change(screen.getByLabelText(i18nT('pages.ajCrewAgentsPage.filter_agents')), { target: { value: text } })
}

describe('AjCrewAgentsPage roster filter', () => {
  it('finds a crewmate by the memory label on its card', async () => {
    await renderAndFilter(i18nT('pages.ajCrewAgentsPage.memory_label_shared'))
    expect(editButton('ops')).toBeInTheDocument()
    expect(editButton('Ada')).toBeNull()
  })

  it('finds a crewmate by the Built from label on its card', async () => {
    await renderAndFilter(i18nT('pages.membersPage.built_from_mate_label'))
    expect(editButton('Ada')).toBeInTheDocument()
    expect(editButton('ops')).toBeNull()
  })

  it('still finds a crewmate by its key, as before', async () => {
    await renderAndFilter('oncall-agent')
    expect(editButton('ops')).toBeInTheDocument()
  })
})
