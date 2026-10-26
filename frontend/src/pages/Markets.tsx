import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Building2, ChevronRight, Database, RefreshCw, RotateCcw, SlidersHorizontal, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { ShareBars, TrendLines, YearBars } from '../components/charts'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CountryChip,
  Drawer,
  EmptyState,
  InfoTip,
  Notice,
  Skeleton,
  SourceLink,
  Stat,
  Table,
  td,
  th,
} from '../components/ui'
import { WorkspaceHeader } from '../components/Workspace'
import { api, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date, dateTime, pct, tonnes, usd } from '../lib/format'
import { useOverview, useProduct, useRun } from '../lib/hooks'
import type { CountryDetail, Overview, Product, Quote, Provider, RankedMarket, Run, Weights } from '../lib/types'

const DEFAULT_WEIGHTS: Weights = { market_size: 35, growth: 25, openness: 20, price_level: 10, data_quality: 10 }
const SHORT: Record<keyof Weights, string> = {
  market_size: 'Size',
  growth: 'Growth',
  openness: 'Open',
  price_level: 'Price',
  data_quality: 'Data',
}

function RefreshPanel({ hs, run, onStarted }: { hs: string; run: Run | null | undefined; onStarted: (r: Run) => void }) {
  const { can } = useAuth()
  const start = useMutation({ mutationFn: () => post<Run>(`/api/markets/${hs}/refresh`), onSuccess: onStarted })
  const running = run?.status === 'running'
  return (
    <Card>
      <EmptyState
        icon={<Database className="size-6" />}
        title={running ? 'Loading official trade statistics…' : 'No trade statistics loaded for this HS code'}
        action={
          running ? (
            <div className="w-72">
              <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full w-1/3 animate-[shimmer_1.2s_infinite] rounded-full bg-brand-600" style={{ transform: 'translateX(-100%)' }} />
              </div>
              <div className="mt-2 text-xs text-muted">{run?.message} · {run?.rows ?? 0} records</div>
            </div>
          ) : can('analyst') ? (
            <Button icon={<Database className="size-4" />} loading={start.isPending} onClick={() => start.mutate()}>
              Load UN Comtrade data
            </Button>
          ) : (
            <span className="text-sm text-muted">Ask an analyst to load data for this product.</span>
          )
        }
      >
        {running
          ? 'Fetching imports and exports for all reporting countries, then supplier breakdowns for the largest markets. This takes about two minutes.'
          : 'Annual imports and exports for every reporting country over the last six years, from the UN Comtrade database.'}
        {run?.status === 'failed' && (
          <div className="mt-4 text-left">
            <Notice tone="error" title="The last refresh failed">{run.error}</Notice>
          </div>
        )}
      </EmptyState>
    </Card>
  )
}

function WeightsPanel({ weights, onChange }: { weights: Weights; onChange: (w: Weights) => void }) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0)
  return (
    <div className="grid gap-x-6 gap-y-3 border-b border-line bg-slate-50/60 px-5 py-4 sm:grid-cols-2 lg:grid-cols-5">
      {(Object.keys(DEFAULT_WEIGHTS) as (keyof Weights)[]).map((k) => (
        <label key={k} className="block">
          <div className="mb-1 flex justify-between text-xs">
            <span className="font-medium text-slate-700">{SHORT[k]}</span>
            <span className="tabular text-muted">{total ? Math.round((weights[k] / total) * 100) : 0}%</span>
          </div>
          <input
            type="range"
            min={0}
            max={50}
            step={5}
            value={weights[k]}
            onChange={(e) => onChange({ ...weights, [k]: Number(e.target.value) })}
            className="w-full accent-brand-700"
            aria-label={`${SHORT[k]} weight`}
          />
        </label>
      ))}
    </div>
  )
}

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="h-1.5 w-20 rounded-full bg-slate-100">
        <div className="h-1.5 rounded-full bg-brand-600" style={{ width: `${score}%` }} />
      </div>
      <span className="tabular w-9 text-[13px] font-semibold text-slate-900">{score.toFixed(1)}</span>
    </div>
  )
}

function ComponentCells({ m }: { m: RankedMarket }) {
  return (
    <div className="flex gap-1">
      {(Object.keys(SHORT) as (keyof Weights)[]).map((k) => {
        const c = m.components[k]
        const v = c.normalized
        return (
          <div
            key={k}
            title={`${c.label}: ${c.status === 'ok' ? fmtComponent(k, c.value) + ` (score ${v?.toFixed(2)}, ${c.period})` : 'unavailable'}`}
            className={clsx('flex h-6 w-11 items-center justify-center rounded text-[10px] font-semibold', c.status !== 'ok' && 'bg-slate-100 text-slate-400')}
            style={c.status === 'ok' && v !== null ? { background: `rgb(15 118 110 / ${0.1 + v * 0.75})`, color: v > 0.55 ? '#fff' : '#0f3d3a' } : undefined}
          >
            {c.status === 'ok' && v !== null ? Math.round(v * 100) : 'n/a'}
          </div>
        )
      })}
    </div>
  )
}

function fmtComponent(k: keyof Weights, v: number | null): string {
  if (v === null) return '—'
  if (k === 'market_size') return usd(v)
  if (k === 'growth') return `${pct(v)} CAGR`
  if (k === 'openness') return v.toFixed(2)
  if (k === 'price_level') return `$${v.toFixed(2)}/kg`
  return `${v} years`
}

function CountryDrawer({ hs, m49, product, onClose }: { hs: string; m49: number | null; product: Product | undefined; onClose: () => void }) {
  const navigate = useNavigate()
  const detail = useQuery({
    queryKey: ['country', hs, m49],
    queryFn: () => api<CountryDetail>(`/api/markets/${hs}/countries/${m49}`),
    enabled: m49 !== null,
  })
  const d = detail.data
  const logistics = useQuery({
    queryKey: ['logistics', d?.iso3],
    queryFn: () => api<{ providers: Provider[]; quotes: Quote[] }>(`/api/logistics?destination_iso3=${d!.iso3}`),
    enabled: Boolean(d?.iso3),
  })
  const latest = d?.series.at(-1)
  return (
    <Drawer
      open={m49 !== null}
      onOpenChange={(o) => !o && onClose()}
      title={d ? <span className="flex items-center gap-2"><CountryChip iso3={d.iso3} /> {d.name}</span> : 'Market detail'}
      subtitle={d ? `HS ${hs} imports · latest reported year ${d.latest_year}` : undefined}
    >
      {detail.isLoading || !d ? (
        detail.isError ? <Notice tone="error">{detail.error.message}</Notice> : <div className="space-y-4"><Skeleton className="h-24" /><Skeleton className="h-56" /></div>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-3 gap-3">
            <Stat label={`Imports ${d.latest_year}`} value={usd(d.latest_value_usd)} />
            <Stat label="Volume" value={tonnes(latest?.net_weight_kg)} />
            <Stat label="Unit value" value={latest?.unit_value ? `$${latest.unit_value.toFixed(2)}/kg` : '—'} />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button icon={<Building2 className="size-4" />} onClick={() => navigate(`/p/${product?.id}/companies?country=${d.m49}`)}>Find buyers in {d.name}</Button>
            <Button variant="secondary" icon={<Sparkles className="size-4" />} onClick={() => navigate(`/p/${product?.id}/analyst?focus=${d.m49}`)}>Ask the AI analyst</Button>
          </div>
          <Card>
            <CardHeader title="Import value by year" subtitle="Partner: World" />
            <div className="p-4"><YearBars data={d.series} height={200} /></div>
            <div className="border-t border-line px-5 py-2.5"><SourceLink source={d.series.at(-1)!.source} /></div>
          </Card>
          <Card>
            <CardHeader
              title="Who supplies this market"
              subtitle={d.supplier_data_available ? `Competitor supplier countries, ${d.latest_year}` : undefined}
            />
            <div className="p-3">
              {d.supplier_data_available ? (
                <ShareBars rows={d.suppliers.slice(0, 10).map((s) => ({ key: s.m49, label: s.name, chip: s.iso3, value: s.value_usd, share: s.share }))} />
              ) : (
                <div className="p-3"><Notice>Supplier breakdown is loaded for the 15 largest markets only. This market is outside that set.</Notice></div>
              )}
            </div>
            {d.home_country && (
              <div className="border-t border-line px-5 py-3 text-sm">
                Your country ({d.home_country}) share: <b className="tabular">{d.home_share === null ? 'not available' : pct(d.home_share)}</b>
              </div>
            )}
          </Card>
          <Card>
            <CardHeader title="Logistics" subtitle="Freight data is shown only from connected providers or client-provided quotes." />
            <div className="space-y-3 p-5 text-sm">
              {logistics.data?.providers.filter((p) => p.key === 'freight').map((p) => (
                <Notice key={p.key} tone="warn" title={`${p.name}: not connected`}>{p.detail}</Notice>
              ))}
              {(logistics.data?.quotes.length ?? 0) > 0 ? (
                <ul className="divide-y divide-line">
                  {logistics.data!.quotes.map((q) => (
                    <li key={q.id} className="flex justify-between gap-4 py-2">
                      <span>{q.origin} → {q.destination} <span className="text-muted capitalize">· {q.mode}</span></span>
                      <span className="tabular text-right">{q.cost_usd !== null ? usd(q.cost_usd, 2) : '—'} · {q.transit_days ?? '—'} days <Badge tone="amber">Client-provided</Badge></span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted">No client-provided quotes for {d.name} yet. Add them on the Logistics page.</p>
              )}
            </div>
          </Card>
        </div>
      )}
    </Drawer>
  )
}

function Dashboard({ ov, product, onRefresh, refreshing }: { ov: Extract<Overview, { has_data: true }>; product: Product | undefined; onRefresh: () => void; refreshing: boolean }) {
  const { can } = useAuth()
  const [weights, setWeights] = useState(DEFAULT_WEIGHTS)
  const [showWeights, setShowWeights] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)
  const ranking = useQuery({
    queryKey: ['ranking', ov.hs_code, weights],
    queryFn: () => post<{ markets: RankedMarket[] }>(`/api/markets/${ov.hs_code}/ranking`, weights),
    placeholderData: (prev) => prev,
  })
  const markets = ranking.data?.markets ?? []
  const top = ov.top_importers[0]
  const topX = ov.top_exporters[0]
  const partial = ov.trend.filter((t) => !t.complete)
  const src = top.source

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat accent label={`Reported imports ${ov.reference_year}`} value={usd(ov.world_imports_usd)} hint={`${ov.reporters} reporting countries`} />
        <Stat label="Import growth (CAGR)" value={ov.world_cagr === null ? '—' : pct(ov.world_cagr)} hint={ov.world_cagr_period ? `Complete years ${ov.world_cagr_period}` : 'Not enough complete years'} />
        <Stat label="Largest import market" value={top.name} hint={`${usd(top.value_usd)} · ${pct(top.share)} share`} />
        <Stat label="Largest supplier country" value={topX?.name ?? '—'} hint={topX ? `${usd(topX.value_usd)} · ${pct(topX.share)} of exports ${ov.exporters_year}` : 'No export data'} />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader
            title="Global import value"
            subtitle="Sum of imports reported to UN Comtrade, by year"
            action={partial.length > 0 && <Badge tone="amber">{partial.map((p) => p.year).join(', ')} partial</Badge>}
          />
          <div className="p-4"><YearBars data={ov.trend} /></div>
          {partial.length > 0 && (
            <p className="border-t border-line px-5 py-2.5 text-xs text-muted">
              Hatched bars: fewer than 80% of usual reporters have submitted data, so totals are not comparable with earlier years.
            </p>
          )}
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader title="Top import markets" subtitle={`${ov.reference_year} · click a market for detail`} />
          <div className="p-3">
            <ShareBars
              rows={ov.top_importers.slice(0, 8).map((r) => ({ key: r.m49, label: r.name, chip: r.iso3, value: r.value_usd, share: r.share }))}
              onSelect={(k) => setSelected(Number(k))}
            />
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader
          title={<span className="flex items-center gap-2">Market opportunity ranking <InfoTip content="A deterministic 0–100 score. Each component is scaled 0–1 across candidate markets (imports ≥ $1M) and weighted. Missing components are excluded and the remaining weights rescaled. Hover a cell to see the underlying value and period." /></span>}
          subtitle="Explainable score computed from official statistics. Adjust weights to match your strategy."
          action={
            <div className="flex gap-2">
              {showWeights && <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={() => setWeights(DEFAULT_WEIGHTS)}>Reset</Button>}
              <Button size="sm" variant={showWeights ? 'primary' : 'secondary'} icon={<SlidersHorizontal className="size-3.5" />} onClick={() => setShowWeights((v) => !v)}>Weights</Button>
            </div>
          }
        />
        {showWeights && <WeightsPanel weights={weights} onChange={setWeights} />}
        {ranking.isError ? (
          <div className="p-5"><Notice tone="error">{ranking.error.message}</Notice></div>
        ) : !ranking.data ? (
          <div className="space-y-2 p-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-9" />)}</div>
        ) : (
          <Table className={clsx(ranking.isFetching && 'opacity-60 transition-opacity')}>
            <thead>
              <tr>
                <th className={`${th} w-12`}>#</th>
                <th className={th}>Market</th>
                <th className={th}>Score</th>
                <th className={th}>
                  <span className="flex gap-1">{Object.values(SHORT).map((s) => <span key={s} className="w-11 text-center tracking-normal normal-case">{s}</span>)}</span>
                </th>
                <th className={`${th} text-right`}>Imports</th>
                <th className={`${th} text-right`}>Year</th>
                <th className={th}><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody>
              {markets.slice(0, 20).map((m) => (
                <tr key={m.m49} className="cursor-pointer hover:bg-slate-50/70" onClick={() => setSelected(m.m49)}>
                  <td className={`${td} tabular font-semibold text-slate-500`}>{m.rank}</td>
                  <td className={td}>
                    <span className="flex items-center gap-2 font-medium text-slate-900"><CountryChip iso3={m.iso3} /> {m.name}</span>
                  </td>
                  <td className={td}><ScoreBar score={m.score} /></td>
                  <td className={td}><ComponentCells m={m} /></td>
                  <td className={`${td} tabular text-right`}>{usd(m.latest_value_usd)}</td>
                  <td className={`${td} tabular text-right text-muted`}>{m.latest_year}</td>
                  <td className={`${td} text-right`}><ChevronRight className="inline size-4 text-slate-400" /></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <div className="border-t border-line px-5 py-2.5 text-xs text-muted">
          Showing top 20 of {markets.length} markets with imports of at least $1M. Cell values are component scores (0–100); n/a = data unavailable.
        </div>
      </Card>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title="Import trend: top 5 markets" subtitle="Annual import value, partner World" />
          <div className="p-4"><TrendLines series={ov.top_importer_trends} /></div>
        </Card>
        <Card>
          <CardHeader title="Competitor supplier countries" subtitle={ov.exporters_year ? `Largest exporters, ${ov.exporters_year} · world ${usd(ov.world_exports_usd)}` : undefined} />
          <div className="p-3">
            {ov.top_exporters.length ? (
              <ShareBars rows={ov.top_exporters.slice(0, 8).map((r) => ({ key: r.m49, label: r.name, chip: r.iso3, value: r.value_usd, share: r.share }))} />
            ) : (
              <Notice>No export statistics available.</Notice>
            )}
          </div>
        </Card>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 text-xs text-muted">
        <span>
          Source: <SourceLink source={src} /> · {ov.note} Retrieved {date(src.retrieved_at)}.
        </span>
        {can('analyst') && (
          <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} loading={refreshing} onClick={onRefresh}>
            {refreshing ? 'Refreshing…' : `Refresh data${ov.refresh?.finished_at ? ` (last ${dateTime(ov.refresh.finished_at)})` : ''}`}
          </Button>
        )}
      </div>
      <CountryDrawer hs={ov.hs_code} m49={selected} product={product} onClose={() => setSelected(null)} />
    </>
  )
}

export default function Markets() {
  const qc = useQueryClient()
  const product = useProduct()
  const hs = product.data?.hs_code
  const overview = useOverview(hs)
  const [runId, setRunId] = useState<number | null>(null)
  const activeRunId = runId ?? (overview.data?.refresh?.status === 'running' ? overview.data.refresh.id : null)
  const run = useRun(activeRunId, (r) => {
    qc.invalidateQueries({ queryKey: ['overview', hs] })
    qc.invalidateQueries({ queryKey: ['ranking', hs] })
    qc.invalidateQueries({ queryKey: ['products'] })
    qc.invalidateQueries({ queryKey: ['product'] })
    if (!runId) return
    setRunId(null)
    if (r.status === 'succeeded') toast.success(r.message)
    else toast.error(`Refresh failed: ${r.error}`)
  })
  const refresh = useMutation({ mutationFn: () => post<Run>(`/api/markets/${hs}/refresh`), onSuccess: (r) => setRunId(r.id) })
  const ov = overview.data

  return (
    <>
      <WorkspaceHeader
        product={product.data}
        hasData={ov?.has_data}
        title="Market intelligence"
        subtitle="Where this product is imported, how demand is moving, and which countries compete to supply it."
      />
      {product.isError ? (
        <Notice tone="error">{product.error.message}</Notice>
      ) : overview.isError ? (
        <Notice tone="error">{overview.error.message}</Notice>
      ) : !ov ? (
        <div className="grid gap-4 sm:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>
      ) : !ov.has_data ? (
        <RefreshPanel hs={ov.hs_code} run={run ?? ov.refresh} onStarted={(r) => setRunId(r.id)} />
      ) : (
        <Dashboard ov={ov} product={product.data} refreshing={run?.status === 'running' || refresh.isPending} onRefresh={() => refresh.mutate()} />
      )}
    </>
  )
}
