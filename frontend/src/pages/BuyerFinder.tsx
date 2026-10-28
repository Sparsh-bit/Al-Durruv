import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, Users } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { Badge, Button, Card, CountryChip, EmptyState, Field, InfoTip, Input, Modal, Notice, PageHeader, Pager, Select, Skeleton } from '../components/ui'
import { api, put } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date, num, pct } from '../lib/format'
import { growBars, useReveal } from '../lib/motion'
import type { BuyersResult, FitKey, Product } from '../lib/types'

const PAGE = 20
const SHORT: Record<FitKey, string> = {
  category_match: 'Category match',
  volume: 'Volume',
  consistency: 'Consistency',
  displaceable_origins: 'Displaceable origins',
  growth: 'Growth',
  supplier_change: 'Supplier change',
}

function Weights({ current, onDone }: { current: Record<FitKey, number>; onDone: () => void }) {
  const qc = useQueryClient()
  const [w, setW] = useState(current)
  const save = useMutation({
    mutationFn: () => put('/api/buyers/weights', w),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['buyers'] })
      toast.success('Weights saved')
      onDone()
    },
  })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      {(Object.keys(SHORT) as FitKey[]).map((k) => (
        <Field key={k} label={SHORT[k]}>
          <Input type="number" min={0} max={100} value={w[k]} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} />
        </Field>
      ))}
      <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onDone}>Cancel</Button><Button type="submit" loading={save.isPending}>Save weights</Button></div>
    </form>
  )
}

export default function BuyerFinder() {
  const { can } = useAuth()
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products') })
  const [hs, setHs] = useState('')
  const [market, setMarket] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)
  const [editing, setEditing] = useState(false)
  const params = new URLSearchParams()
  if (hs) params.set('hs', hs)
  if (market.length === 3) params.set('market', market)
  const res = useQuery({ queryKey: ['buyers', params.toString()], queryFn: () => api<BuyersResult>(`/api/buyers?${params}`) })
  const hsOptions = useMemo(() => [...new Set((products.data ?? []).map((p) => p.hs_code).filter(Boolean) as string[])].sort(), [products.data])
  const rows = (res.data?.buyers ?? []).filter((b) => !q || b.company.name.toLowerCase().includes(q.toLowerCase()))
  const pages = Math.max(1, Math.ceil(rows.length / PAGE))
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE)
  const tbody = useRef<HTMLTableSectionElement>(null)
  useEffect(() => growBars(tbody.current), [page, res.data, q])
  const ref = useReveal<HTMLDivElement>([res.isSuccess])

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Shipment data"
        title="Buyer finder"
        subtitle="Importers that buy your categories, ranked by a private-label fit score you can trace: every component is shown with its weight. Built only from the shipment files you upload."
        actions={can('admin') && res.data && <Button variant="secondary" onClick={() => setEditing(true)}>Adjust weights</Button>}
      />
      <Card className="mb-6 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="HS code">
            <Select className="w-56!" value={hs} onChange={(e) => { setHs(e.target.value); setPage(0) }}>
              <option value="">All your HS codes</option>
              {hsOptions.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
          </Field>
          <Field label="Market (ISO3)">
            <Input className="w-28 font-mono uppercase" maxLength={3} value={market} onChange={(e) => { setMarket(e.target.value.toUpperCase()); setPage(0) }} placeholder="USA" />
          </Field>
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="w-64 pl-9" placeholder="Search importer" value={q} onChange={(e) => { setQ(e.target.value); setPage(0) }} aria-label="Search importer" />
          </div>
        </div>
      </Card>
      {res.isLoading ? (
        <Skeleton className="h-72" />
      ) : res.isError ? (
        <Notice tone="error">{res.error.message}</Notice>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState icon={<Users />} title="No shipment records yet">
            Buyer Finder works from bill-of-lading files (ImportGenius, Panjiva or Volza exports). {can('admin') ? <>Upload one in <Link to="/data" className="text-brand-700 underline">Data admin</Link>.</> : 'Ask an administrator to upload one.'}
          </EmptyState>
        </Card>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-[13px]">
              <thead>
                <tr>
                  {['Importer', 'Shipments (12m)', 'Weight (12m)', 'Trend', 'Origins', 'Top suppliers', 'Fit score', 'Components'].map((h) => (
                    <th key={h} className="micro border-b border-line bg-paper px-4 py-2.5 font-medium text-muted">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody ref={tbody}>
                {shown.map((b) => (
                  <tr key={b.company.id} className="align-top hover:bg-paper">
                    <td className="border-b border-line-soft px-4 py-3">
                      <div className="font-medium text-ink-900">{b.company.name}</div>
                      <div className="mt-1 flex items-center gap-1.5"><CountryChip iso3={b.company.country_iso3} /><span className="num text-[11px] text-muted">HS {b.hs_codes.join(', ')}</span></div>
                      <div className="mt-1 text-[11px] text-muted">last {date(b.metrics.last_shipment)}</div>
                    </td>
                    <td className="num border-b border-line-soft px-4 py-3">{b.metrics.shipments_12m}<div className="text-[11px] text-muted">{b.metrics.active_months_12m}/12 months</div></td>
                    <td className="num border-b border-line-soft px-4 py-3">
                      {num(Math.round(b.metrics.weight_kg_12m))} kg
                      {b.metrics.rows_without_weight_12m > 0 && <div className="text-[11px] text-muted">{b.metrics.rows_without_weight_12m} rows without weight</div>}
                    </td>
                    <td className="num border-b border-line-soft px-4 py-3">{b.metrics.trend === null ? '—' : pct(b.metrics.trend)}</td>
                    <td className="border-b border-line-soft px-4 py-3">
                      <div className="flex max-w-40 flex-wrap gap-1">
                        {Object.keys(b.metrics.origins_12m).slice(0, 4).map((o) => <CountryChip key={o} iso3={o} />)}
                      </div>
                      {b.metrics.new_origins_6m.length > 0 && <Badge tone="amber" className="mt-1">new: {b.metrics.new_origins_6m.join(', ')}</Badge>}
                    </td>
                    <td className="border-b border-line-soft px-4 py-3 text-[12px] text-body">
                      {b.top_suppliers.slice(0, 3).map((s) => <div key={s.name} className="max-w-48 truncate" title={s.name}>{s.name} <span className="text-muted">({s.shipments})</span></div>)}
                    </td>
                    <td className="border-b border-line-soft px-4 py-3"><span className="num text-[19px] text-ink-900">{b.score?.toFixed(0) ?? '—'}</span></td>
                    <td className="border-b border-line-soft px-4 py-3">
                      <div className="grid w-60 gap-1">
                        {(Object.keys(SHORT) as FitKey[]).map((k) => (
                          <div key={k} className="grid grid-cols-[110px_1fr_26px] items-center gap-2 text-[11px]">
                            <span className="flex items-center gap-1 truncate text-muted">{SHORT[k]}</span>
                            <span className="h-1.5 overflow-hidden rounded-full bg-fog">
                              {b.components[k] !== null && <span data-bar className="block h-full origin-left rounded-full bg-ink-800" style={{ width: `${b.components[k]}%` }} />}
                            </span>
                            <span className="num text-right">{b.components[k] === null ? 'n/a' : Math.round(b.components[k]!)}</span>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} pages={pages} onPage={setPage} total={rows.length} />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line-soft px-4 py-3 text-[11.5px] text-muted">
            <span>{res.data!.source_note}</span>
            <span className="flex items-center gap-1">How the score works <InfoTip content={<ul className="space-y-1">{(Object.keys(SHORT) as FitKey[]).map((k) => <li key={k}><b>{SHORT[k]} ({res.data!.weights[k]}):</b> {res.data!.labels[k]}</li>)}</ul>} /></span>
          </div>
        </Card>
      )}
      <Modal open={editing} onOpenChange={setEditing} title="Fit score weights" description="Weights are relative; components without data are left out and the rest are rescaled.">
        {res.data && <Weights current={res.data.weights} onDone={() => setEditing(false)} />}
      </Modal>
    </div>
  )
}
