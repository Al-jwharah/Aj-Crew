import { motion } from 'framer-motion'
import ErrorNotice from './ErrorNotice'
import {
  SUGGESTION_KIND_STYLE, WelcomeBrandMark, useWelcomeGreetingKey, useWelcomeSuggestions,
} from './WelcomeView'
import { reportForError } from '../utils/errorReport'
import { simpleHomeGeometry, SIMPLE_HOME_COMPOSER_MAX_W } from '../lib/simpleHome'
import { SIMPLE_SUGGESTION_LIMIT } from '../lib/simpleLayout'
import { i18nT } from '../i18n/t'

interface SimpleWelcomeProps {
  setInput: (v: string) => void
  /** Measured height of the composer dock, which sits between the two bands. */
  dockH: number
}

/**
 * The Simple layout's home: the brand mark and a greeting above the composer,
 * and up to four suggested tasks under it. A suggestion fills the composer; it
 * does not send, so the task can be edited first.
 *
 * Both bands are positioned against the chat pane (the composer dock's own
 * containing block) from `simpleHomeGeometry`, so they frame the dock wherever
 * it sits and whatever height it has. The wrapper takes no pointer events: the
 * dock paints over it, and only the suggestions need the pointer.
 */
export default function SimpleWelcome({ setInput, dockH }: SimpleWelcomeProps) {
  const greetingKey = useWelcomeGreetingKey()
  const { suggestions, isError, error } = useWelcomeSuggestions()
  const { heroBottom, suggestionsTop } = simpleHomeGeometry(dockH)
  const chips = suggestions.slice(0, SIMPLE_SUGGESTION_LIMIT)
  return (
    <motion.div
      key="simple-welcome"
      data-testid="simple-welcome"
      className="absolute inset-0 pointer-events-none"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
    >
      <div
        className="absolute inset-x-0 top-0 flex flex-col items-center justify-end gap-4 overflow-hidden px-8 pb-7 text-center"
        style={{ bottom: heroBottom }}
      >
        <WelcomeBrandMark className="" />
        <h2 className="text-3xl font-light tracking-tight text-text-strong">{i18nT(greetingKey)}</h2>
      </div>
      <div
        className="absolute inset-x-0 bottom-0 overflow-y-auto px-8 pt-4 pb-6 scrollbar-none"
        style={{ top: suggestionsTop }}
      >
        <div className="mx-auto w-full pointer-events-auto" style={{ maxWidth: SIMPLE_HOME_COMPOSER_MAX_W }}>
          {/* A failed fetch still offers the built-in tasks below, but says so,
              as the standard welcome does. */}
          {isError && (
            <ErrorNotice
              message={i18nT('components.welcomeView.suggestions_failed_to_load')}
              report={reportForError(error)}
              variant="inline"
              askAgent
              className="mb-3"
            />
          )}
          <ul
            aria-label={i18nT('simpleLayout.suggestions_label')}
            data-testid="simple-suggestions"
            className="m-0 mx-auto flex max-w-[600px] list-none flex-wrap justify-center gap-2 p-0"
          >
            {chips.map(({ text, kind }, i) => {
              const { Icon } = SUGGESTION_KIND_STYLE[kind]
              return (
                <li key={`${i}-${text}`} className="min-w-0 max-w-full">
                  {/* type=button + onMouseDown preventDefault keep keyboard
                      focus in the composer, so a follow-up Enter sends the
                      filled task instead of pressing the chip again. */}
                  <button
                    type="button"
                    data-kind={kind}
                    onMouseDown={e => e.preventDefault()}
                    onClick={() => setInput(text)}
                    title={text}
                    className="flex h-9 max-w-full cursor-pointer items-center gap-2 rounded-full border border-border bg-card px-3.5 text-[13px] text-text transition-colors hover:border-border-strong hover:bg-bg-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    <Icon size={14} aria-hidden="true" className="shrink-0 text-muted" />
                    <span className="min-w-0 max-w-[300px] truncate">{text}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </motion.div>
  )
}
