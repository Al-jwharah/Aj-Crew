import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Check, Copy, Cpu, KeyRound, RefreshCw, Trash2 } from 'lucide-react'

import { apiTransport as tReq } from '../../api/apiTransport'
import ErrorNotice from '../../components/ErrorNotice'
import { Badge, Btn } from '../../components/ui'
import { clearCachedModels } from '../../providers/adapters/acp'

export interface NativeProviderStatusRow {
  id: string
  label: string
  kind: string
  auth_mode: string
  base_url: string
  default_model: string
  enabled: boolean
  connected: boolean
  account_hint: string
}

export interface DiscoveredModelRow {
  id: string
  label: string
  provider_id: string
}

interface SubscriptionsResponse {
  providers: NativeProviderStatusRow[]
  models: DiscoveredModelRow[]
}

interface BeginConnectResponse {
  provider: string
  connect_url: string
  state: string
  loopback_listening: boolean
}

const SUBSCRIPTIONS_QUERY_KEY = ['nativeSubscriptions']

const subscriptionsApi = {
  status: () => tReq.get('/api/subscriptions').then(tReq.j) as Promise<SubscriptionsResponse>,
  begin: (provider: string, clientId = '') =>
    tReq.post('/api/subscriptions/begin', { provider, client_id: clientId }).then(tReq.j) as Promise<BeginConnectResponse>,
  complete: (provider: string, value: string, nonce = '') =>
    tReq.post('/api/subscriptions/complete', { provider, value, nonce }).then(tReq.j),
  save: (provider: string, apiKey: string, baseUrl: string) =>
    tReq.post('/api/subscriptions/save', { provider, api_key: apiKey, base_url: baseUrl }).then(tReq.j),
  remove: (provider: string) =>
    tReq.del(`/api/subscriptions/${encodeURIComponent(provider)}`).then(tReq.j),
  refreshModels: () =>
    tReq.post('/api/subscriptions/refresh-models', {}).then(tReq.j) as Promise<{ ok: boolean; models: DiscoveredModelRow[] }>,
}

export function NativeProvidersCard() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [nonces, setNonces] = useState<Record<string, string>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [baseUrls, setBaseUrls] = useState<Record<string, string>>({})
  const [geminiClientId, setGeminiClientId] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const subQ = useQuery({
    queryKey: SUBSCRIPTIONS_QUERY_KEY,
    queryFn: subscriptionsApi.status,
  })

  const invalidateAll = async () => {
    clearCachedModels()
    await Promise.all([
      qc.invalidateQueries({ queryKey: SUBSCRIPTIONS_QUERY_KEY }),
      qc.invalidateQueries({ queryKey: ['ajcrewConfig'] }),
      qc.invalidateQueries({ queryKey: ['acpBackends'] }),
      qc.invalidateQueries({ queryKey: ['models'] }),
    ])
  }

  const beginMut = useMutation({
    mutationFn: ({ provider, clientId }: { provider: string; clientId?: string }) =>
      subscriptionsApi.begin(provider, clientId),
    onSuccess: async res => {
      setErrorMsg(null)
      setNonces(prev => ({ ...prev, [res.provider]: res.state }))
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(res.connect_url)
      }
      setCopiedId(res.provider)
      window.setTimeout(() => setCopiedId(cur => (cur === res.provider ? null : cur)), 2500)
    },
    onError: (err: Error) => setErrorMsg(err.message || t('pages.developer.nativeProviders.action_failed')),
  })

  const completeMut = useMutation({
    mutationFn: ({ provider, value }: { provider: string; value: string }) =>
      subscriptionsApi.complete(provider, value, nonces[provider] || ''),
    onSuccess: async (_res, vars) => {
      setErrorMsg(null)
      setDrafts(prev => ({ ...prev, [vars.provider]: '' }))
      await invalidateAll()
    },
    onError: (err: Error) => setErrorMsg(err.message || t('pages.developer.nativeProviders.action_failed')),
  })

  const saveMut = useMutation({
    mutationFn: ({ provider, apiKey, baseUrl }: { provider: string; apiKey: string; baseUrl: string }) =>
      subscriptionsApi.save(provider, apiKey, baseUrl),
    onSuccess: async (_res, vars) => {
      setErrorMsg(null)
      setDrafts(prev => ({ ...prev, [vars.provider]: '' }))
      await invalidateAll()
    },
    onError: (err: Error) => setErrorMsg(err.message || t('pages.developer.nativeProviders.action_failed')),
  })

  const removeMut = useMutation({
    mutationFn: (provider: string) => subscriptionsApi.remove(provider),
    onSuccess: async () => {
      setErrorMsg(null)
      await invalidateAll()
    },
    onError: (err: Error) => setErrorMsg(err.message || t('pages.developer.nativeProviders.action_failed')),
  })

  const refreshMut = useMutation({
    mutationFn: () => subscriptionsApi.refreshModels(),
    onSuccess: async () => {
      setErrorMsg(null)
      await invalidateAll()
    },
    onError: (err: Error) => setErrorMsg(err.message || t('pages.developer.nativeProviders.action_failed')),
  })

  const providers = subQ.data?.providers ?? []
  const modelsCount = subQ.data?.models?.length ?? 0

  return (
    <section
      data-testid="native-providers-card"
      className="space-y-4 rounded-xl border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h4 className="m-0 flex items-center gap-2 text-[13px] font-semibold text-text">
            <KeyRound size={14} aria-hidden="true" />
            {t('pages.developer.nativeProviders.title')}
          </h4>
          <p className="m-0 text-[12px] leading-relaxed text-muted">
            {t('pages.developer.nativeProviders.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-muted">
            {t('pages.developer.nativeProviders.models_discovered')}: {modelsCount}
          </span>
          <Btn
            disabled={refreshMut.isPending}
            onClick={() => refreshMut.mutate()}
            data-testid="native-refresh-models"
          >
            <RefreshCw size={13} className="lucide-inline" aria-hidden="true" />
            {t('pages.developer.nativeProviders.refresh_models')}
          </Btn>
        </div>
      </div>

      {/* No hand-off: credential inputs hold unsaved provider secrets and backend setup state. */}
      {errorMsg && (
        <ErrorNotice
          message={errorMsg}
          variant="inline"
          onDismiss={() => setErrorMsg(null)}
        />
      )}

      <div className="space-y-3">
        {providers.map(row => {
          const isSubscription =
            row.auth_mode === 'oauth_pkce' ||
            row.auth_mode === 'oauth_or_key' ||
            row.auth_mode === 'connect_link_or_key'
          const isKeyless = row.auth_mode === 'keyless'
          const draft = drafts[row.id] ?? ''
          const urlVal = baseUrls[row.id] ?? row.base_url

          return (
            <div
              key={row.id}
              data-testid={`native-provider-${row.id}`}
              className="space-y-2 rounded-lg border border-border bg-bg p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-text">{row.label}</span>
                  <Badge variant={row.connected ? 'ok' : 'muted'}>
                    {row.connected
                      ? t('pages.developer.nativeProviders.connected')
                      : t('pages.developer.nativeProviders.not_connected')}
                  </Badge>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {isSubscription && (
                    <Btn
                      disabled={beginMut.isPending}
                      onClick={() =>
                        beginMut.mutate({
                          provider: row.id,
                          clientId: row.id === 'gemini' ? geminiClientId : '',
                        })
                      }
                      data-testid={`native-copy-link-${row.id}`}
                    >
                      {copiedId === row.id ? (
                        <>
                          <Check size={13} className="lucide-inline" aria-hidden="true" />
                          {t('pages.developer.nativeProviders.copied')}
                        </>
                      ) : (
                        <>
                          <Copy size={13} className="lucide-inline" aria-hidden="true" />
                          {t('pages.developer.nativeProviders.copy_connect_link')}
                        </>
                      )}
                    </Btn>
                  )}
                  {isKeyless && !row.connected && (
                    <Btn
                      primary
                      disabled={saveMut.isPending}
                      onClick={() => saveMut.mutate({ provider: row.id, apiKey: '', baseUrl: urlVal })}
                      data-testid={`native-enable-${row.id}`}
                    >
                      <Cpu size={13} className="lucide-inline" aria-hidden="true" />
                      {t('pages.developer.nativeProviders.enable_ollama')}
                    </Btn>
                  )}
                  {row.connected && (
                    <Btn
                      danger
                      disabled={removeMut.isPending}
                      onClick={() => removeMut.mutate(row.id)}
                      data-testid={`native-disconnect-${row.id}`}
                    >
                      <Trash2 size={13} className="lucide-inline" aria-hidden="true" />
                      {t('pages.developer.nativeProviders.disconnect')}
                    </Btn>
                  )}
                </div>
              </div>

              {row.id === 'gemini' && !row.connected && (
                <input
                  type="text"
                  value={geminiClientId}
                  onChange={e => setGeminiClientId(e.target.value)}
                  placeholder={t('pages.developer.nativeProviders.client_id_placeholder')}
                  aria-label={t('pages.developer.nativeProviders.client_id_placeholder')}
                  className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-[12px] text-text"
                />
              )}

              {!isKeyless && (
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="password"
                    value={draft}
                    onChange={e => setDrafts(prev => ({ ...prev, [row.id]: e.target.value }))}
                    placeholder={
                      isSubscription
                        ? t('pages.developer.nativeProviders.paste_placeholder')
                        : t('pages.developer.nativeProviders.api_key_placeholder')
                    }
                    aria-label={
                      isSubscription
                        ? t('pages.developer.nativeProviders.paste_placeholder')
                        : t('pages.developer.nativeProviders.api_key_placeholder')
                    }
                    className="min-w-0 flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-[12px] text-text"
                  />
                  {!isSubscription && (
                    <input
                      type="url"
                      value={urlVal}
                      onChange={e => setBaseUrls(prev => ({ ...prev, [row.id]: e.target.value }))}
                      placeholder={t('pages.developer.nativeProviders.base_url_placeholder')}
                      aria-label={t('pages.developer.nativeProviders.base_url_placeholder')}
                      className="w-52 rounded-md border border-border bg-surface px-2.5 py-1.5 text-[12px] text-text"
                    />
                  )}
                  <Btn
                    disabled={!draft.trim() || completeMut.isPending || saveMut.isPending}
                    onClick={() => {
                      const trimmed = draft.trim()
                      if (!trimmed) return
                      if (isSubscription) {
                        completeMut.mutate({ provider: row.id, value: trimmed })
                      } else {
                        saveMut.mutate({ provider: row.id, apiKey: trimmed, baseUrl: urlVal })
                      }
                    }}
                    data-testid={`native-submit-${row.id}`}
                  >
                    {isSubscription
                      ? t('pages.developer.nativeProviders.complete_connect')
                      : t('pages.developer.nativeProviders.save_key')}
                  </Btn>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
