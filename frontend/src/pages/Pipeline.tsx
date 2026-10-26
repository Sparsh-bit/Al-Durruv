import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KanbanSquare } from 'lucide-react'
import { useState } from 'react'
import CompanyDrawer from '../components/CompanyDrawer'
import { Badge, Card, CountryChip, EmptyState, Notice, PageHeader, Select, Skeleton } from '../components/ui'
import { api, patch } from '../lib/api'
import { useAuth } from '../lib/auth'
import { STAGES } from '../lib/labels'
import type { Company, Stage } from '../lib/types'

const STAGE_TONE: Record<Stage, string> = {
  identified: 'border-t-slate-300',
  researched: 'border-t-indigo-400',
  contacted: 'border-t-sky-500',
  negotiating: 'border-t-amber-500',
  won: 'border-t-emerald-500',
  lost: 'border-t-red-400',
}

export default function Pipeline() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [openId, setOpenId] = useState<number | null>(null)
  const buyers = useQuery({ queryKey: ['companies', 'pipeline'], queryFn: () => api<Company[]>('/api/companies?relationship=buyer') })
  const move = useMutation({
    mutationFn: ({ id, stage }: { id: number; stage: Stage }) => patch<Company>(`/api/companies/${id}`, { pipeline_stage: stage }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }),
  })
  const active = (buyers.data ?? []).filter((c) => c.review_status !== 'rejected')
  const open = (buyers.data ?? []).find((c) => c.id === openId) ?? null

  return (
    <>
      <PageHeader title="Sales pipeline" subtitle="Potential buyers across all products, from first identification to a won or lost deal. Rejected candidates are hidden." />
      {buyers.isLoading ? (
        <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">{STAGES.map((s) => <Skeleton key={s.key} className="h-64" />)}</div>
      ) : buyers.isError ? (
        <Notice tone="error">{buyers.error.message}</Notice>
      ) : active.length === 0 ? (
        <Card>
          <EmptyState icon={<KanbanSquare className="size-6" />} title="No buyers in the pipeline yet">
            Research potential buyers from a product's Companies step; they appear here as “Identified”.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
          {STAGES.map((s) => {
            const items = active.filter((c) => c.pipeline_stage === s.key)
            return (
              <section key={s.key} className={`rounded-xl border border-t-4 border-line bg-white/60 ${STAGE_TONE[s.key]}`} aria-label={s.label}>
                <div className="flex items-center justify-between px-3 py-2.5">
                  <h2 className="text-[13px] font-semibold text-slate-800">{s.label}</h2>
                  <Badge>{items.length}</Badge>
                </div>
                <ul className="space-y-2 px-2 pb-2">
                  {items.map((c) => (
                    <li key={c.id} className="rounded-lg border border-line bg-white p-3 shadow-card">
                      <button type="button" onClick={() => setOpenId(c.id)} className="block w-full text-left">
                        <div className="truncate text-sm font-medium text-slate-900 hover:text-brand-700" title={c.name}>{c.name}</div>
                        <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted">
                          <span className="flex items-center gap-1"><CountryChip iso3={c.country_iso3} /></span>
                          {c.prospect_score !== null && <span className="tabular font-medium text-ink-800">{c.prospect_score.toFixed(0)} fit</span>}
                        </div>
                        <div className="mt-1 truncate font-mono text-[11px] text-muted">HS {c.hs_codes.join(', ')}</div>
                      </button>
                      {can('analyst') && (
                        <Select
                          className="mt-2 h-8! text-xs"
                          value={c.pipeline_stage}
                          aria-label={`Stage for ${c.name}`}
                          onChange={(e) => move.mutate({ id: c.id, stage: e.target.value as Stage })}
                        >
                          {STAGES.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
                        </Select>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )
          })}
        </div>
      )}
      <CompanyDrawer company={open} onClose={() => setOpenId(null)} />
    </>
  )
}
