import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CloudDownload, Download, LineChart as LineIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { TrendLines } from '../components/charts'
import { Badge, Button, Card, EmptyState, Field, Input, Notice, PageHeader, Segmented, Select, Skeleton, SourceLink } from '../components/ui'
import { api, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime, usd } from '../lib/format'
import { useReveal } from '../lib/motion'
import type { ExploreResult, MonthlyResult, Product, Region } from '../lib/types'

type Countries = { iso3: string; name: string }[]
const THIS_YEAR = new Date().getFullYear()

function csvCell(v: unknown) {
  const s = v === null || v === undefined ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

const OWN_ORIGINS = ['EGY', 'JOR', 'SYR']

function MonthlyPanel({ hs }: { hs: string }) {
  const [reporter, setReporter] = useState('USA')
  const m = useQuery({
    queryKey: ['monthly', hs, reporter],
    queryFn: () => api<MonthlyResult>(`/api/markets/${hs}/monthly?reporter=${reporter}`),
    enabled: reporter.length === 3,
  })
  const rows = m.data?.rows ?? []
  const periods = [...new Set(rows.map((r) => r.period))].sort().slice(-12)
  const partners = new Map<string, { name: string; iso: string; values: Record<string, number | null>; kg: number }>()
  for (const r of rows) {
    if (!periods.includes(r.period)) continue
    const key = r.partner_iso3 || r.partner_name
    const p = partners.get(key) ?? { name: r.partner_name, iso: r.partner_iso3, values: {}, kg: 0 }
    p.values[r.period] = (p.values[r.period] ?? 0) + (r.value_usd ?? 0)
    p.kg += r.net_weight_kg ?? 0
    partners.set(key, p)
  }
  const last = periods[periods.length - 1]
  const list = [...partners.values()].sort((a, b) => (b.values[last] ?? 0) - (a.values[last] ?? 0))
  const top = [...list.filter((p) => p.iso === 'WLD' || p.iso === 'XEU'), ...list.filter((p) => !['WLD', 'XEU'].includes(p.iso)).slice(0, 10), ...list.filter((p) => OWN_ORIGINS.includes(p.iso) && list.indexOf(p) > 12)]
  const sources = [...new Set(rows.map((r) => r.source))]
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line-soft px-5 py-4">
        <div>
          <h2 className="text-[15.5px] font-semibold">Monthly imports by origin</h2>
          <p className="text-[12.5px] text-muted">US Census (USA) or Eurostat Comext (EU members). Values in USD; EUR converted at the ECB monthly average.</p>
        </div>
        <Input className="w-24 font-mono uppercase" maxLength={3} value={reporter} onChange={(e) => setReporter(e.target.value.toUpperCase())} aria-label="Reporter" />
      </div>
      {m.isLoading ? <Skeleton className="m-5 h-40" /> : rows.length === 0 ? (
        <p className="px-5 py-6 text-[13px] text-muted">No monthly data from US Census or Eurostat for HS {hs} and {reporter}. An administrator can load it in Data admin → Connectors.</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead>
                <tr>
                  <th className="micro sticky left-0 border-b border-line bg-paper px-4 py-2.5 font-medium text-muted">Origin</th>
                  {periods.map((p) => <th key={p} className="micro border-b border-line bg-paper px-3 py-2.5 text-right font-medium text-muted">{p}</th>)}
                </tr>
              </thead>
              <tbody>
                {top.map((p) => (
                  <tr key={p.iso || p.name} className={OWN_ORIGINS.includes(p.iso) ? 'bg-brand-50/60' : ''}>
                    <td className="sticky left-0 border-b border-line-soft bg-inherit px-4 py-2 font-medium text-ink-900">
                      {p.iso === 'WLD' ? 'All origins' : p.iso === 'XEU' ? 'Outside the EU' : p.name} {OWN_ORIGINS.includes(p.iso) && <Badge tone="teal">your origin</Badge>}
                    </td>
                    {periods.map((per) => <td key={per} className="num border-b border-line-soft px-3 py-2 text-right">{p.values[per] === undefined ? <span className="text-muted/60">—</span> : usd(p.values[per])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line-soft px-5 py-3 text-[11.5px] text-muted">
            <span>Sources: {sources.join(', ')} (official)</span>
            {(m.data?.sources ?? []).slice(0, 3).map((src) => <span key={src.id}><SourceLink source={src} compact /> {dateTime(src.retrieved_at)}</span>)}
          </div>
        </>
      )}
    </Card>
  )
}

export default function Explorer() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products') })
  const regions = useQuery({ queryKey: ['regions'], queryFn: () => api<Region[]>('/api/regions') })
  const countries = useQuery({ queryKey: ['countries'], queryFn: () => api<Countries>('/api/countries') })
  const hsOptions = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const p of products.data ?? []) if (p.hs_code) m.set(p.hs_code, [...(m.get(p.hs_code) ?? []), p.name])
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [products.data])

  const [hs, setHs] = useState('')
  const [flow, setFlow] = useState<'M' | 'X'>('M')
  const [region, setRegion] = useState('')
  const [reporters, setReporters] = useState('')
  const [partner, setPartner] = useState('WLD')
  const [from, setFrom] = useState(String(THIS_YEAR - 6))
  const [to, setTo] = useState(String(THIS_YEAR - 1))
  const code = hs || hsOptions[0]?.[0] || ''
  const reporterList = reporters.split(/[\s,;]+/).map((r) => r.trim().toUpperCase()).filter(Boolean)

  const params = new URLSearchParams({ flow, partner: partner || 'WLD' })
  if (region) params.set('region', region)
  reporterList.forEach((r) => params.append('reporters', r))
  if (from) params.set('year_from', from)
  if (to) params.set('year_to', to)
  const badYears = Boolean(from && to && Number(from) > Number(to))

  const data = useQuery({
    queryKey: ['explore', code, params.toString()],
    queryFn: () => api<ExploreResult>(`/api/markets/${code}/explore?${params}`),
    enabled: Boolean(code) && !badYears,
  })
  const ref = useReveal<HTMLDivElement>([data.dataUpdatedAt])

  const live = useMutation({
    mutationFn: () => {
      const iso = data.data?.series.map((s) => s.iso3) ?? []
      const years = data.data?.years.length ? data.data.years : [THIS_YEAR - 1]
      return post<{ rows: number; stored: number; truncated: boolean }>(`/api/markets/${code}/explore/fetch`, {
        flow,
        reporters: (reporterList.length ? reporterList : iso).slice(0, 20),
        partner: partner || 'WLD',
        years: years.slice(-12),
      })
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['explore', code] })
      toast.success(r.rows ? `UN Comtrade returned ${r.rows} rows (${r.stored} stored)` : 'UN Comtrade returned no rows for this selection')
    },
  })

  const exportCsv = () => {
    const d = data.data
    if (!d) return
    const lines = [
      `# HS ${d.hs_code} · ${d.flow === 'M' ? 'imports' : 'exports'} · partner ${d.partner}${d.region ? ` · region ${d.region}` : ''}`,
      `# ${d.licence}`,
      ...d.sources.map((s) => `# Source ${s.id}: ${s.url} (retrieved ${s.retrieved_at})`),
      '# Empty cells mean not reported. They are not zero.',
      ['country', 'iso3', ...d.years.map(String), 'qty_unit', 'source_ids'].join(','),
      ...d.series.map((s) => [s.name, s.iso3, ...d.years.map((y) => s.values[y]), s.qty_unit, s.source_ids.join(' ')].map(csvCell).join(',')),
      ['Total (comparable years only)', '', ...d.totals.map((t) => t.value_usd)].map(csvCell).join(','),
    ]
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv' })),
      download: `trade-explorer-${d.hs_code}-${d.flow}.csv`,
    })
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  }

  const d = data.data
  const chartSeries = (d?.series ?? [])
    .filter((s) => s.latest_year)
    .slice(0, 8)
    .map((s) => ({ name: s.name, series: d!.years.filter((y) => s.values[y] !== null).map((y) => ({ year: y, value_usd: s.values[y] as number })) }))

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="UN Comtrade"
        title="Trade explorer"
        subtitle="Choose a product, reporters or a region, partner, flow and years. Gaps stay empty, never zero. Totals are shown only for years every selected country reported."
        actions={
          <>
            <Button variant="secondary" icon={<Download />} onClick={exportCsv} disabled={!d?.series.length}>Export CSV</Button>
            {can('admin') && (
              <Button icon={<CloudDownload />} loading={live.isPending} onClick={() => live.mutate()} disabled={!code || badYears}>
                Fetch from UN Comtrade
              </Button>
            )}
          </>
        }
      />

      <Card className="mb-6 p-5">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
          <div className="xl:col-span-2">
            <Field label="Product (HS6)">
              <Select value={code} onChange={(e) => setHs(e.target.value)}>
                {hsOptions.map(([c, names]) => (
                  <option key={c} value={c}>{c} · {names.slice(0, 2).join(', ')}{names.length > 2 ? ` +${names.length - 2}` : ''}</option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Region">
            <Select value={region} onChange={(e) => setRegion(e.target.value)}>
              <option value="">No region</option>
              {(regions.data ?? []).map((r) => <option key={r.name} value={r.name}>{r.name} ({r.members.length})</option>)}
            </Select>
          </Field>
          <div className="xl:col-span-2">
            <Field label="Reporters (ISO3)" hint="Comma separated. Leave empty for the largest reporters.">
              <Input list="iso-list" value={reporters} onChange={(e) => setReporters(e.target.value)} placeholder="DEU, FRA, USA" className="font-mono uppercase" />
              <datalist id="iso-list">{(countries.data ?? []).map((c) => <option key={c.iso3} value={c.iso3}>{c.name}</option>)}</datalist>
            </Field>
          </div>
          <Field label="Partner">
            <Input value={partner} onChange={(e) => setPartner(e.target.value.toUpperCase())} maxLength={3} className="font-mono uppercase" placeholder="WLD" />
          </Field>
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <div className="mb-1.5 text-[13px] font-medium text-ink-800">Flow</div>
            <Segmented label="Trade flow" value={flow} onChange={setFlow} options={[{ value: 'M', label: 'Imports' }, { value: 'X', label: 'Exports' }]} />
          </div>
          <Field label="From">
            <Input type="number" min={1988} max={THIS_YEAR - 1} value={from} onChange={(e) => setFrom(e.target.value)} className="w-28" />
          </Field>
          <Field label="To">
            <Input type="number" min={1988} max={THIS_YEAR - 1} value={to} onChange={(e) => setTo(e.target.value)} className="w-28" />
          </Field>
          {badYears && <span className="pb-2 text-[12.5px] text-red-700">The start year must not be after the end year.</span>}
        </div>
      </Card>

      {data.isLoading || products.isLoading ? (
        <Skeleton className="h-80" />
      ) : data.isError ? (
        <Notice tone="error">{data.error.message}</Notice>
      ) : !d || d.series.length === 0 ? (
        <Card>
          <EmptyState icon={<LineIcon />} title="No stored figures for this selection">
            {can('admin') ? 'Fetch this slice from UN Comtrade. Identical requests come from the cache and are not repeated.' : 'Ask an administrator to load this product’s trade data.'}
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-6">
          {d.warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
          <Card className="p-5" >
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-[16px] font-semibold">{d.flow === 'M' ? 'Imports' : 'Exports'}, HS {d.hs_code}, partner {d.partner}</h2>
              <span className="micro text-muted">USD · latest comparable year {d.latest_comparable_year ?? 'none'}</span>
            </div>
            <div data-reveal><TrendLines series={chartSeries} height={300} gaps /></div>
          </Card>
          <Card>
            <div className="relative overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr>
                    <th className="micro sticky left-0 border-b border-line bg-paper px-4 py-2.5 font-medium text-muted">Reporter</th>
                    {d.years.map((y) => <th key={y} className="micro border-b border-line bg-paper px-3 py-2.5 text-right font-medium text-muted">{y}</th>)}
                    <th className="micro border-b border-line bg-paper px-3 py-2.5 font-medium text-muted">Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {d.series.map((s) => (
                    <tr key={s.iso3} className="hover:bg-paper" data-reveal>
                      <td className="sticky left-0 border-b border-line-soft bg-white px-4 py-2.5">
                        <span className="font-medium text-ink-900">{s.name}</span> <span className="num text-[11px] text-muted">{s.iso3}</span>
                      </td>
                      {d.years.map((y) => {
                        const v = s.values[y]
                        return (
                          <td key={y} className="num border-b border-line-soft px-3 py-2.5 text-right">
                            {v === null ? <span className="text-muted/60" title="Not reported for this year">—</span> : usd(v)}
                          </td>
                        )
                      })}
                      <td className="border-b border-line-soft px-3 py-2.5 text-[12px] text-muted">{s.qty_unit || '—'}</td>
                    </tr>
                  ))}
                  <tr className="bg-paper">
                    <td className="sticky left-0 bg-paper px-4 py-2.5 font-semibold text-ink-900">Total</td>
                    {d.totals.map((t) => (
                      <td key={t.year} className="num px-3 py-2.5 text-right">
                        {t.comparable ? (
                          <span className="font-semibold text-ink-900">{usd(t.value_usd)}</span>
                        ) : (
                          <span className="text-[11px] text-muted" title={`${t.reporters_with_data} of ${t.reporters} reported`}>n/c {t.reporters_with_data}/{t.reporters}</span>
                        )}
                      </td>
                    ))}
                    <td />
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="border-t border-line-soft px-4 py-3 text-[12px] text-muted">
              “—” means not reported, not zero. “n/c” means not comparable because some countries did not report that year.
            </div>
          </Card>
          <Card className="p-5">
            <div className="micro mb-3 text-muted">Sources and licence</div>
            <ul className="space-y-1.5">
              {d.sources.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
                  <Badge>#{s.id}</Badge>
                  <SourceLink source={s} />
                  <span className="text-muted">retrieved {dateTime(s.retrieved_at)}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[12px] text-muted">{d.licence}</p>
          </Card>
          <MonthlyPanel hs={d.hs_code} />
        </div>
      )}
    </div>
  )
}
