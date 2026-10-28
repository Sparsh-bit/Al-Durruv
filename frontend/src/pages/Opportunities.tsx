import { useQuery } from '@tanstack/react-query'
import { Download, RotateCcw, Tags } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Badge, Button, Card, EmptyState, InfoTip, Notice, PageHeader, Pager, Select, Skeleton } from '../components/ui'
import { download, post } from '../lib/api'
import { pct, usd } from '../lib/format'
import { IDENTITY } from '../lib/labels'
import { growBars, useReveal } from '../lib/motion'
import type { OpportunityResult, PlWeights } from '../lib/types'

const PAGE = 20
const SHORT: Record<keyof PlWeights, string> = {
  market_size: 'Market size',
  growth: 'Growth',
  retailer_presence: 'Retailer presence',
  private_label_signal: 'Private-label signal',
  evidence: 'Evidence',
}

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v)
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms)
    return () => clearTimeout(t)
  }, [v, ms])
  return d
}

export default function Opportunities() {
  const [weights, setWeights] = useState<PlWeights | null>(null)
  const w = useDebounced(weights)
  const res = useQuery({
    queryKey: ['opportunities', w],
    queryFn: () => post<OpportunityResult>('/api/markets/opportunities', w ?? {}),
    placeholderData: (prev) => prev,
  })
  const [category, setCategory] = useState('')
  const [segment, setSegment] = useState('')
  const [retailerOnly, setRetailerOnly] = useState(false)
  const [page, setPage] = useState(0)
  const tableRef = useRef<HTMLTableSectionElement>(null)
  const ref = useReveal<HTMLDivElement>([res.isSuccess])

  const d = res.data
  const current = weights ?? d?.weights ?? null
  const rows = useMemo(
    () =>
      (d?.rows ?? []).filter(
        (r) => (!category || r.category === category) && (!segment || r.segment === segment) && (!retailerOnly || r.retailer),
      ),
    [d, category, segment, retailerOnly],
  )
  const categories = [...new Set((d?.rows ?? []).map((r) => r.category))]
  const pages = Math.max(1, Math.ceil(rows.length / PAGE))
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE)
  useEffect(() => growBars(tableRef.current), [page, category, segment, retailerOnly, d])
  const totalW = current ? Object.values(current).reduce((a, b) => a + b, 0) : 0

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Private label"
        title="Opportunity engine"
        subtitle="Priority category × target country × retailer. Each score is a weighted average of the components shown. A component without data is left out and the other weights are rescaled. Nothing is estimated."
        actions={<Button variant="secondary" icon={<Download />} onClick={() => download('/api/markets/opportunities/export')}>Export CSV</Button>}
      />

      {d?.note && <div className="mb-4"><Notice tone="warn">{d.note}</Notice></div>}
      {d && d.gaps.length > 0 && (
        <div className="mb-6">
          <Notice tone="info" title="Data gaps">
            <ul className="mt-1 list-disc space-y-0.5 pl-4">{d.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
          </Notice>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[300px_1fr]">
        <Card className="h-fit p-5 xl:sticky xl:top-20" >
          <div className="mb-4 flex items-center justify-between">
            <div className="micro text-muted">Weights</div>
            <button type="button" onClick={() => setWeights(null)} className="inline-flex items-center gap-1 text-[12px] text-muted hover:text-ink-900" disabled={!weights}>
              <RotateCcw className="size-3" /> Reset
            </button>
          </div>
          {current ? (
            <div className="space-y-4">
              {(Object.keys(SHORT) as (keyof PlWeights)[]).map((k) => (
                <label key={k} className="block">
                  <span className="mb-1.5 flex items-center justify-between text-[13px] text-ink-800">
                    <span className="flex items-center gap-1.5">{SHORT[k]} {d && <InfoTip content={d.components[k]} />}</span>
                    <span className="num text-[12px] text-muted">{totalW ? Math.round((current[k] / totalW) * 100) : 0}%</span>
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={current[k]}
                    onChange={(e) => setWeights({ ...current, [k]: Number(e.target.value) })}
                    className="w-full accent-ink-900"
                    aria-label={`${SHORT[k]} weight`}
                  />
                </label>
              ))}
              {totalW === 0 && <p className="text-[12px] text-red-700">At least one weight must be above zero.</p>}
              <p className="text-[11.5px] leading-relaxed text-muted">Changes apply to this view. Defaults are set in Administration.</p>
            </div>
          ) : (
            <Skeleton className="h-60" />
          )}
        </Card>

        <Card>
          <div className="flex flex-wrap items-center gap-3 border-b border-line-soft px-5 py-3">
            <Select className="w-auto!" value={category} onChange={(e) => { setCategory(e.target.value); setPage(0) }} aria-label="Category">
              <option value="">All priority categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
            <Select className="w-auto!" value={segment} onChange={(e) => { setSegment(e.target.value); setPage(0) }} aria-label="Segment">
              <option value="">Any segment</option>
              <option value="existing">Existing markets</option>
              <option value="expansion">Expansion markets</option>
              <option value="unclassified">Not in client list</option>
            </Select>
            <label className="flex items-center gap-2 text-[13px] text-ink-800">
              <input type="checkbox" className="size-4 accent-ink-900" checked={retailerOnly} onChange={(e) => { setRetailerOnly(e.target.checked); setPage(0) }} />
              With a tracked retailer
            </label>
            {res.isFetching && <span className="micro ml-auto text-muted">updating…</span>}
          </div>
          {res.isLoading ? (
            <Skeleton className="m-5 h-72" />
          ) : res.isError ? (
            <div className="p-5"><Notice tone="error">{res.error.message}</Notice></div>
          ) : rows.length === 0 ? (
            <EmptyState icon={<Tags />} title="No opportunities to score yet">
              Tag products with priority categories and load their trade data. Retailers come from the Accounts page.
            </EmptyState>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[880px] text-left text-[13px]">
                  <thead>
                    <tr>
                      {['Category', 'Country', 'Retailer', 'Imports', 'CAGR', 'Score', 'Components'].map((h) => (
                        <th key={h} className={`micro border-b border-line bg-paper px-4 py-2.5 font-medium text-muted ${h === 'Score' || h === 'Imports' || h === 'CAGR' ? 'text-right' : ''}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody ref={tableRef}>
                    {shown.map((r, i) => (
                      <tr key={`${r.category}-${r.iso3}-${r.retailer?.id ?? 'none'}-${i}`} className="align-top hover:bg-paper">
                        <td className="border-b border-line-soft px-4 py-3">
                          <div className="font-medium text-ink-900">{r.category}</div>
                          <div className="num text-[11px] text-muted">HS {r.hs_codes.join(' · ')}</div>
                        </td>
                        <td className="border-b border-line-soft px-4 py-3">
                          <span className="num text-[12.5px] text-ink-900">{r.iso3}</span>
                          <div><Badge tone={r.segment === 'existing' ? 'teal' : r.segment === 'expansion' ? 'blue' : 'slate'}>{r.segment}</Badge></div>
                        </td>
                        <td className="border-b border-line-soft px-4 py-3">
                          {r.retailer ? (
                            <>
                              <div className="text-ink-900">{r.retailer.name}</div>
                              <Badge tone={IDENTITY[r.retailer.identity_status].tone}>{IDENTITY[r.retailer.identity_status].text}</Badge>
                            </>
                          ) : (
                            <span className="text-[12.5px] text-muted">No tracked retailer</span>
                          )}
                        </td>
                        <td className="num border-b border-line-soft px-4 py-3 text-right">
                          {r.import_value_usd === null ? <span className="text-muted">—</span> : usd(r.import_value_usd)}
                          {r.latest_year && <div className="text-[11px] text-muted">{r.latest_year}</div>}
                        </td>
                        <td className="num border-b border-line-soft px-4 py-3 text-right">{r.cagr === null ? <span className="text-muted">—</span> : pct(r.cagr)}</td>
                        <td className="border-b border-line-soft px-4 py-3 text-right">
                          {r.score === null ? (
                            <span className="text-[11px] leading-tight text-muted">not scored:<br />no market data</span>
                          ) : (
                            <span className="num text-[18px] text-ink-900">{r.score.toFixed(1)}</span>
                          )}
                          {r.missing.length > 0 && <div className="text-[10.5px] text-muted">{r.missing.length} n/a</div>}
                        </td>
                        <td className="border-b border-line-soft px-4 py-3">
                          <div className="grid w-56 gap-1">
                            {(Object.keys(SHORT) as (keyof PlWeights)[]).map((k) => {
                              const v = r.components[k]
                              return (
                                <div key={k} className="grid grid-cols-[92px_1fr_28px] items-center gap-2 text-[11px]">
                                  <span className="truncate text-muted">{SHORT[k]}</span>
                                  <span className="h-1.5 overflow-hidden rounded-full bg-fog">
                                    {v !== null && <span data-bar className="block h-full origin-left rounded-full bg-ink-800" style={{ width: `${v}%` }} />}
                                  </span>
                                  <span className="num text-right text-ink-800">{v === null ? 'n/a' : Math.round(v)}</span>
                                </div>
                              )
                            })}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager page={page} pages={pages} onPage={setPage} total={rows.length} />
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
