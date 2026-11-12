/**
 * The composer's default-effort read answers from the shared ['ajcrewConfig']
 * query instead of issuing its own GET of the same body: with the sidebar's
 * observer of that key mounted in the same commit, boot sends ONE
 * `GET /api/config/ajcrew`, and the default effort still comes out of it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'

vi.mock('../api/client', () => ({
  api: {
    ajcrewConfig: vi.fn(),
    agentDetail: vi.fn(),
    agentResolvedModel: vi.fn(),
  },
}))

import { api } from '../api/client'
import { AcpAdapter } from '../providers/adapters/acp'
import { useAjcrewConfigReader } from '../hooks/useAjcrewConfigReader'

const ajcrewConfig = api.ajcrewConfig as unknown as ReturnType<typeof vi.fn>

function wrapperFor(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

/** The two readers as the chat page mounts them: the sidebar's config
 *  observer and the composer's default-effort query. */
function useBootReaders() {
  const provider = new AcpAdapter()
  const cfg = useQuery({ queryKey: ['ajcrewConfig'], queryFn: () => api.ajcrewConfig() })
  const readAjcrewConfig = useAjcrewConfigReader()
  const effort = useQuery({
    queryKey: ['default-effort', provider.id],
    queryFn: () => provider.resolveDefaultEffort(readAjcrewConfig),
  })
  return { cfg: cfg.data, effort: effort.data }
}

describe('default effort reads the shared ajcrewConfig query', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('sends one GET /api/config/ajcrew for the sidebar observer and the default effort', async () => {
    ajcrewConfig.mockResolvedValue({ agent: { reasoning_effort: 'high' } })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    const { result } = renderHook(() => useBootReaders(), { wrapper: wrapperFor(qc) })
    await waitFor(() => expect(result.current.effort).toBe('high'))
    expect(result.current.cfg).toEqual({ agent: { reasoning_effort: 'high' } })
    expect(ajcrewConfig).toHaveBeenCalledTimes(1)
  })

  it('answers from data already in the shared key without a request', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    qc.setQueryData(['ajcrewConfig'], { agent: { reasoning_effort: 'low' } })
    const { result } = renderHook(() => {
      const read = useAjcrewConfigReader()
      return useQuery({
        queryKey: ['default-effort', 'acp'],
        queryFn: () => new AcpAdapter().resolveDefaultEffort(read),
      }).data
    }, { wrapper: wrapperFor(qc) })
    await waitFor(() => expect(result.current).toBe('low'))
    expect(ajcrewConfig).not.toHaveBeenCalled()
  })

  it('reports "" when the shared read fails, as the adapter always has', async () => {
    ajcrewConfig.mockRejectedValue(new Error('503'))
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    const { result } = renderHook(() => {
      const read = useAjcrewConfigReader()
      return useQuery({
        queryKey: ['default-effort', 'acp'],
        queryFn: () => new AcpAdapter().resolveDefaultEffort(read),
      })
    }, { wrapper: wrapperFor(qc) })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toBe('')
  })
})
