import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Check } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, EmptyState, Notice, PageHeader, Segmented, Skeleton } from '../components/ui'
import { api, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime } from '../lib/format'
import { useReveal } from '../lib/motion'
import { ALERT_LABEL } from '../lib/labels'
import type { AlertItem } from '../lib/types'

export default function Alerts() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [filter, setFilter] = useState<'unread' | 'all'>('unread')
  const alerts = useQuery({ queryKey: ['alerts', filter], queryFn: () => api<AlertItem[]>(`/api/alerts?unread=${filter === 'unread'}`) })
  const read = useMutation({
    mutationFn: (id: number) => post(`/api/alerts/${id}/read`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })
  const run = useMutation({
    mutationFn: () => post<{ created: number }>('/api/alerts/run'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })
  const ref = useReveal<HTMLDivElement>([alerts.dataUpdatedAt])
  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Signals"
        title="Alerts"
        subtitle="New importers of your HS codes in target markets, buyers adding a supplier origin, volume swings and competitors winning buyers. Generated after every data refresh or upload."
        actions={can('admin') && <Button variant="secondary" loading={run.isPending} onClick={() => run.mutate()}>Check now</Button>}
      />
      <div className="mb-4"><Segmented label="Show" value={filter} onChange={setFilter} options={[{ value: 'unread', label: 'Unread' }, { value: 'all', label: 'All' }]} /></div>
      {alerts.isLoading ? (
        <Skeleton className="h-48" />
      ) : alerts.isError ? (
        <Notice tone="error">{alerts.error.message}</Notice>
      ) : (alerts.data ?? []).length === 0 ? (
        <Card><EmptyState icon={<Bell />} title={filter === 'unread' ? 'No unread alerts' : 'No alerts yet'}>Alerts come from shipment data and refreshed trade data.</EmptyState></Card>
      ) : (
        <Card>
          <ul className="divide-y divide-line-soft">
            {alerts.data!.map((a) => {
              const meta = ALERT_LABEL[a.type] ?? { text: a.type, tone: 'blue' as const }
              return (
                <li key={a.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5" data-reveal>
                  <Badge tone={meta.tone}>{meta.text}</Badge>
                  <span className={`min-w-0 flex-1 text-[13.5px] ${a.read_at ? 'text-muted' : 'text-ink-900'}`}>{a.title}</span>
                  {a.hs_code && <span className="num text-[11.5px] text-muted">HS {a.hs_code}</span>}
                  <span className="text-[12px] text-muted">{dateTime(a.created_at)}</span>
                  {!a.read_at && <Button size="sm" variant="ghost" icon={<Check />} onClick={() => read.mutate(a.id)}>Mark read</Button>}
                </li>
              )
            })}
          </ul>
        </Card>
      )}
    </div>
  )
}
