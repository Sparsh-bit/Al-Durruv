import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useParams } from 'react-router'
import { api } from './api'
import type { Overview, Product, Run } from './types'

export const isActive = (r: Pick<Run, 'status'> | null | undefined) => r?.status === 'queued' || r?.status === 'running'

export function useProduct() {
  const { productId } = useParams()
  return useQuery({
    queryKey: ['product', productId],
    queryFn: () => api<Product>(`/api/products/${productId}`),
    enabled: Boolean(productId),
  })
}

export function useOverview(hs: string | undefined) {
  return useQuery({
    queryKey: ['overview', hs],
    queryFn: () => api<Overview>(`/api/markets/${hs}/overview`),
    enabled: Boolean(hs),
  })
}

/** Polls a background run until it finishes, then calls onDone once. */
export function useRun(runId: number | null | undefined, onDone?: (run: Run) => void) {
  const done = useRef(onDone)
  useEffect(() => {
    done.current = onDone
  })
  const q = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api<Run>(`/api/markets/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) => (isActive(query.state.data) ? 2000 : false),
    staleTime: 0,
  })
  const status = q.data?.status
  const notified = useRef<number | null>(null)
  useEffect(() => {
    if (q.data && !isActive(q.data) && notified.current !== q.data.id) {
      notified.current = q.data.id
      done.current?.(q.data)
    }
  }, [q.data, status])
  return q.data
}
