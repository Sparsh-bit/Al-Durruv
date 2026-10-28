import { useQuery } from '@tanstack/react-query'
import { Award, Calculator } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, Card, CountryChip, EmptyState, Field, Input, Notice, PageHeader, Select, Skeleton, SourceLink } from '../components/ui'
import { api } from '../lib/api'
import { date } from '../lib/format'
import { useReveal } from '../lib/motion'
import type { AccessOrigin, AccessResult, Product } from '../lib/types'

const money = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `$${v.toFixed(3)}`)
const NAMES: Record<string, string> = { EGY: 'Egypt', JOR: 'Jordan', SYR: 'Syria' }

function Row({ label, value, note }: { label: string; value: string; note?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line-soft py-2 text-[13px] last:border-b-0">
      <span className="text-body">{label}{note && <div className="mt-0.5 text-[11px] text-muted">{note}</div>}</span>
      <span className="num shrink-0 text-ink-900">{value}</span>
    </div>
  )
}

function OriginCard({ o, best }: { o: AccessOrigin; best: boolean }) {
  return (
    <Card className={best ? 'border-ink-900 shadow-lift' : ''}>
      <div className="flex items-center justify-between gap-3 border-b border-line-soft px-4 py-3">
        <div className="flex items-center gap-2 font-display text-[16px] font-semibold"><CountryChip iso3={o.origin_iso3} /> {NAMES[o.origin_iso3] ?? o.origin_iso3}</div>
        {best && <Badge tone="teal"><Award className="size-3" /> Best factory</Badge>}
      </div>
      <div className="px-4 py-2">
        <Row label="FOB" value={money(o.fob_usd_per_kg)} note={o.fob_basis} />
        <Row
          label="Freight / kg"
          value={money(o.freight_usd_per_kg)}
          note={o.freight ? `${o.freight.carrier || o.freight.mode} ${o.freight.container}: $${o.freight.cost_usd} ÷ ${o.freight.payload_kg.toLocaleString()} kg · ${o.freight.transit_days ?? '?'} days · estimate${o.freight.valid_until ? `, valid to ${date(o.freight.valid_until)}` : ''}` : 'No valid freight route; add one in Logistics.'}
        />
        <Row label="Insurance" value={money(o.insurance_usd_per_kg)} />
        <Row
          label={o.duty ? `Duty ${o.duty.rate_pct.toFixed(1)}% (${o.duty.basis}${o.duty.agreement ? `, ${o.duty.agreement}` : ''})` : 'Duty'}
          value={money(o.duty_usd_per_kg)}
          note={o.duty ? (
            <span className="flex flex-wrap items-center gap-x-2">
              {o.duty.source.toUpperCase()} {o.duty.hs_line} {o.duty.data_year ? `· data ${o.duty.data_year}` : ''} · verified {date(o.duty.verified_at)}
              {o.duty.source_url && <SourceLink source={{ url: o.duty.source_url }} compact />}
              {o.duty.additional.length > 0 && <span className="text-amber-800">incl. additional duties</span>}
              {o.duty.note && <span className="block text-amber-800">{o.duty.note}</span>}
            </span>
          ) : 'No tariff on file for this origin; fetch tariffs in Data admin or add an override.'}
        />
        <div className="flex items-center justify-between py-3">
          <span className="text-[13px] font-semibold text-ink-900">Landed cost / kg</span>
          <span className="num text-[22px] text-ink-900">{money(o.landed_usd_per_kg)}</span>
        </div>
        {o.missing.length > 0 && <p className="pb-3 text-[12px] text-amber-800">Missing: {o.missing.join(', ')}. Not compared.</p>}
        <p className="pb-3 text-[11.5px] text-muted">
          Imports from {NAMES[o.origin_iso3] ?? o.origin_iso3}: {o.origin_unit_value.usd_per_kg ? `$${o.origin_unit_value.usd_per_kg.toFixed(2)}/kg in ${o.origin_unit_value.year}` : 'no unit value on record'}
          {o.origin_unit_value.excluded > 0 && ` (${o.origin_unit_value.excluded} rows without weight excluded)`}
        </p>
      </div>
    </Card>
  )
}

export default function MarketAccess() {
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products') })
  const hsOptions = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of products.data ?? []) if (p.hs_code && !m.has(p.hs_code)) m.set(p.hs_code, p.name)
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [products.data])
  const [hs, setHs] = useState('')
  const [market, setMarket] = useState('USA')
  const [fob, setFob] = useState('')
  const [ins, setIns] = useState('0.5')
  const code = hs || hsOptions.find(([c]) => c === '200290')?.[0] || hsOptions[0]?.[0] || ''
  const params = new URLSearchParams({ market, hs: code, insurance_pct: ins || '0' })
  if (Number(fob) > 0) params.set('fob', fob)
  const res = useQuery({
    queryKey: ['access', params.toString()],
    queryFn: () => api<AccessResult>(`/api/access?${params}`),
    enabled: Boolean(code) && market.length === 3,
  })
  const ref = useReveal<HTMLDivElement>([res.dataUpdatedAt])
  const d = res.data

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Market access"
        title="Landed cost & best factory"
        subtitle="Duty for Egyptian-, Jordanian- and Syrian-origin goods, plus freight and insurance, per kilogram. Every part shows its source; freight is always an estimate."
      />
      <Card className="mb-6 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Product (HS6)">
            <Select className="w-72!" value={code} onChange={(e) => setHs(e.target.value)}>
              {hsOptions.map(([c, n]) => <option key={c} value={c}>{c} · {n}</option>)}
            </Select>
          </Field>
          <Field label="Market (ISO3)"><Input className="w-24 font-mono uppercase" maxLength={3} value={market} onChange={(e) => setMarket(e.target.value.toUpperCase())} /></Field>
          <Field label="FOB $/kg" hint="Empty = market benchmark"><Input className="w-32" type="number" min={0} step="0.01" value={fob} onChange={(e) => setFob(e.target.value)} /></Field>
          <Field label="Insurance %"><Input className="w-24" type="number" min={0} max={10} step="0.1" value={ins} onChange={(e) => setIns(e.target.value)} /></Field>
        </div>
      </Card>
      {res.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-80" />)}</div>
      ) : res.isError ? (
        <Notice tone="error">{res.error.message}</Notice>
      ) : !d ? (
        <Card><EmptyState icon={<Calculator />} title="Choose a product and a market" /></Card>
      ) : (
        <>
          {d.note && <div className="mb-4"><Notice tone="warn">{d.note}</Notice></div>}
          <div className="grid gap-4 lg:grid-cols-3">
            {d.origins.map((o) => <div key={o.origin_iso3} data-reveal><OriginCard o={o} best={o.origin_iso3 === d.best_origin} /></div>)}
          </div>
          <Card className="mt-6 p-4 text-[12.5px] text-body">
            <div className="micro mb-2 text-muted">How this is calculated</div>
            <p className="num text-[12px]">{d.formula}</p>
            <p className="mt-2">
              Benchmark FOB: average {d.market} import value per kg for HS {d.hs6}
              {d.benchmark.usd_per_kg ? ` = $${d.benchmark.usd_per_kg.toFixed(3)}/kg in ${d.benchmark.year}` : ': not available'}
              {d.benchmark.excluded > 0 && ` (${d.benchmark.excluded} rows without weight excluded)`}
              {d.benchmark.source_url && <> · <SourceLink source={{ url: d.benchmark.source_url }} compact /></>}
            </p>
            <p className="mt-1 text-muted">US additional duties (Chapter 99) are not in the line rates; add them as tariff overrides with their source.</p>
          </Card>
        </>
      )}
    </div>
  )
}
