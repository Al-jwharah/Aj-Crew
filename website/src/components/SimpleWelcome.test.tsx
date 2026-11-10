/**
 * The Simple layout's home (an empty chat): brand mark, a greeting, and up to
 * four suggested tasks that fill the composer. The composer itself is the chat
 * page's dock; this component only frames it.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderWithProviders } from '../test/helpers'
import SimpleWelcome from './SimpleWelcome'
import { welcomeGreetings } from './WelcomeView'
import { api } from '../api/client'

const FALLBACK = [
  'Set up a daily reminder',
  'What should I work on next?',
  'Search code for usage examples',
  "Summarize this week's chat activity",
]

afterEach(() => { vi.restoreAllMocks() })

describe('SimpleWelcome', () => {
  it('renders the brand mark, one greeting and the suggested tasks', () => {
    renderWithProviders(<SimpleWelcome setInput={vi.fn()} dockH={120} />)
    const home = screen.getByTestId('simple-welcome')
    expect(home.querySelector('img, canvas')).not.toBeNull()
    const headings = within(home).getAllByRole('heading', { level: 2 })
    expect(headings).toHaveLength(1)
    expect(welcomeGreetings()).toContain(headings[0].textContent)
    expect(screen.getByRole('list', { name: 'Suggested tasks' })).toBeInTheDocument()
  })

  it('offers the first four built-in tasks when the server has none', () => {
    renderWithProviders(<SimpleWelcome setInput={vi.fn()} dockH={120} />)
    const chips = within(screen.getByTestId('simple-suggestions')).getAllByRole('button')
    expect(chips.map(c => c.textContent)).toEqual(FALLBACK)
  })

  it('never shows more than four, whatever the server sends', async () => {
    vi.spyOn(api, 'suggestions').mockResolvedValue({
      suggestions: ['one', { text: 'two', kind: 'code' }, 'three', 'four', 'five', 'six'],
    } as Awaited<ReturnType<typeof api.suggestions>>)
    renderWithProviders(<SimpleWelcome setInput={vi.fn()} dockH={120} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'one' })).toBeInTheDocument())
    const chips = within(screen.getByTestId('simple-suggestions')).getAllByRole('button')
    expect(chips.map(c => c.textContent)).toEqual(['one', 'two', 'three', 'four'])
    expect(chips[1]).toHaveAttribute('data-kind', 'code')
  })

  it('fills the composer with the task and does not take focus from it', () => {
    const setInput = vi.fn()
    renderWithProviders(<SimpleWelcome setInput={setInput} dockH={120} />)
    const chip = screen.getByRole('button', { name: FALLBACK[1] })
    expect(chip).toHaveAttribute('type', 'button')
    // A cancelled mousedown keeps focus in the composer, so Enter sends the task.
    expect(fireEvent.mouseDown(chip)).toBe(false)
    fireEvent.click(chip)
    expect(setInput).toHaveBeenCalledTimes(1)
    expect(setInput).toHaveBeenCalledWith(FALLBACK[1])
  })

  it('says so when the suggestions fail to load, and still offers the built-in tasks', async () => {
    vi.spyOn(api, 'suggestions').mockRejectedValue(new Error('network down'))
    renderWithProviders(<SimpleWelcome setInput={vi.fn()} dockH={120} />)
    await waitFor(() => expect(screen.getByText("Couldn't load suggestions")).toBeInTheDocument())
    expect(screen.getByRole('button', { name: FALLBACK[0] })).toBeInTheDocument()
  })

  it('frames the dock from its measured height', () => {
    renderWithProviders(<SimpleWelcome setInput={vi.fn()} dockH={200} />)
    const [hero, tasks] = [...screen.getByTestId('simple-welcome').children] as HTMLElement[]
    expect(hero.style.bottom).toBe('calc(54% + 100px)')
    expect(tasks.style.top).toBe('calc(46% + 100px)')
  })
})
