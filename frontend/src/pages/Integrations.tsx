import { useQuery } from '@tanstack/react-query'
import { Database, PlugZap } from 'lucide-react'
import { Badge, Card, Notice, PageHeader, Skeleton, StatusDot } from '../components/ui'
import { api } from '../lib/api'
import { dateTime, num } from '../lib/format'
import { useReveal } from '../lib/motion'
import type { Run } from '../lib/types'

type Source = {
  key: string
  name: string
  status: 'connected' | 'not_configured' | 'not_connected' | string
  detail: string
  observations?: number
  cached_responses?: number
  companies?: number
  last_run?: Run | null
}
type Health = { status: string; ai_enabled: boolean; model: string }

const TONE = { connected: 'green', not_configured: 'red', not_connected: 'amber' } as const
const TEXT = { connected: 'Connected', not_configured: 'Not configured', not_connected: 'Not connected' } as const

export default function Integrations() {
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api<Source[]>('/api/admin/sources'), refetchInterval: 30_000 })
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/api/health'), refetchInterval: 30_000, retry: false })
  const ref = useReveal<HTMLDivElement>([sources.isSuccess])

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="System"
        title="Integration health"
        subtitle="Live state of each data source. Keys are stored on the server only and never shown here or sent to the browser."
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Card className="p-5">
          <div className="micro text-muted">API & database</div>
          <div className="mt-3">
            {health.isLoading ? <Skeleton className="h-5 w-24" /> : <StatusDot tone={health.data?.status === 'ok' ? 'green' : 'red'}>{health.data?.status === 'ok' ? 'Healthy' : 'Unreachable'}</StatusDot>}
          </div>
        </Card>
        <Card className="p-5">
          <div className="micro text-muted">AI model</div>
          <div className="num mt-3 text-[15px]">{health.data?.ai_enabled ? health.data.model : 'Not configured'}</div>
        </Card>
        <Card className="p-5">
          <div className="micro text-muted">Stored trade observations</div>
          <div className="num mt-3 text-[22px]">{num(sources.data?.find((s) => s.key === 'un_comtrade')?.observations ?? 0)}</div>
        </Card>
      </div>
      {sources.isError && <Notice tone="error">{sources.error.message}</Notice>}
      <div className="grid gap-4 lg:grid-cols-2">
        {(sources.data ?? []).map((s) => (
          <Card key={s.key} className="p-5" >
            <div data-reveal>
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="flex size-9 items-center justify-center rounded-full border border-line bg-paper text-ink-700">
                    {s.key === 'un_comtrade' ? <Database className="size-4" /> : <PlugZap className="size-4" />}
                  </span>
                  <h2 className="text-[15.5px] font-semibold text-ink-900">{s.name}</h2>
                </div>
                <StatusDot tone={TONE[s.status as keyof typeof TONE] ?? 'slate'}>{TEXT[s.status as keyof typeof TEXT] ?? s.status}</StatusDot>
              </div>
              <p className="mt-3 text-[13px] leading-relaxed text-body">{s.detail}</p>
              <dl className="mt-4 grid grid-cols-2 gap-3 text-[12.5px]">
                {s.cached_responses !== undefined && <div><dt className="micro text-muted">Cached responses</dt><dd className="num mt-1">{num(s.cached_responses)}</dd></div>}
                {s.companies !== undefined && <div><dt className="micro text-muted">Company records</dt><dd className="num mt-1">{num(s.companies)}</dd></div>}
                {s.last_run && (
                  <div className="col-span-2">
                    <dt className="micro text-muted">Last refresh</dt>
                    <dd className="mt-1 flex flex-wrap items-center gap-2">
                      <Badge tone={s.last_run.status === 'succeeded' ? 'green' : s.last_run.status === 'failed' ? 'red' : 'blue'}>{s.last_run.status}</Badge>
                      <span>{s.last_run.scope}</span>
                      <span className="text-muted">{dateTime(s.last_run.finished_at ?? s.last_run.started_at)}</span>
                    </dd>
                    {s.last_run.error && <dd className="mt-1 text-[12px] text-red-700">{s.last_run.error}</dd>}
                  </div>
                )}
              </dl>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
