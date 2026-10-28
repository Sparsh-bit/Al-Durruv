import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { usd } from '../lib/format'

// Validated categorical order (see dataviz reference palette); color follows the entity.
const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
const BAR = '#20736e'
const AXIS = { fontSize: 11, fill: '#5f696b', fontFamily: 'IBM Plex Mono' }
const GRID = '#eef1f2'

type TipPayload = { name?: string; value?: number; color?: string; payload?: Record<string, unknown> }

function TipBox({ active, payload, label, note }: { active?: boolean; payload?: TipPayload[]; label?: string | number; note?: (p: Record<string, unknown>) => string | null }) {
  if (!active || !payload?.length) return null
  const extra = note && payload[0].payload ? note(payload[0].payload) : null
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 text-xs shadow-pop">
      <div className="mb-1 font-semibold text-slate-900">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="tabular flex items-center gap-2 text-slate-700">
          {payload.length > 1 && <span className="size-2 rounded-full" style={{ background: p.color }} />}
          <span className="text-muted">{payload.length > 1 ? p.name : 'Value'}</span>
          <span className="ml-auto pl-4 font-medium text-slate-900">{usd(p.value ?? null)}</span>
        </div>
      ))}
      {extra && <div className="mt-1 text-muted">{extra}</div>}
    </div>
  )
}

export function YearBars({ data, height = 240 }: { data: { year: number; value_usd: number; complete?: boolean; reporters?: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="28%">
        <defs>
          <pattern id="partial" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#ccebe7" />
            <line x1="0" y1="0" x2="0" y2="6" stroke={BAR} strokeWidth="2" />
          </pattern>
        </defs>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="year" tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} width={56} tickFormatter={(v: number) => usd(v, 0)} />
        <Tooltip
          cursor={{ fill: 'rgb(15 118 110 / 0.06)' }}
          content={(p) => (
            <TipBox
              {...(p as object)}
              note={(row) =>
                row.reporters !== undefined
                  ? `${row.reporters} reporting countries${row.complete === false ? ' · partial year, not comparable' : ''}`
                  : null
              }
            />
          )}
        />
        <Bar dataKey="value_usd" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={d.year} fill={d.complete === false ? 'url(#partial)' : BAR} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function TrendLines({ series, height = 260, gaps = false }: { series: { name: string; series: { year: number; value_usd: number }[] }[]; height?: number; gaps?: boolean }) {
  const years = [...new Set(series.flatMap((s) => s.series.map((p) => p.year)))].sort()
  const data = years.map((year) => {
    const row: Record<string, number> = { year }
    for (const s of series) {
      const p = s.series.find((x) => x.year === year)
      if (p) row[s.name] = p.value_usd
    }
    return row
  })
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="year" tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} width={56} tickFormatter={(v: number) => usd(v, 0)} />
        <Tooltip content={(p) => <TipBox {...(p as object)} />} cursor={{ stroke: '#cbd5e1' }} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: '#334155', paddingTop: 8 }} />
        {series.map((s, i) => (
          <Line
            key={s.name}
            type="monotone"
            dataKey={s.name}
            stroke={SERIES[i % SERIES.length]}
            strokeWidth={2}
            dot={{ r: 3, strokeWidth: 2, fill: '#fff' }}
            activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }}
            connectNulls={!gaps}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

/** Horizontal share bars rendered in HTML: crisp labels, fully accessible, no legend needed. */
export function ShareBars({ rows, onSelect }: {
  rows: { key: string | number; label: string; chip?: string; value: number; share: number | null; hint?: string; highlight?: boolean; extra?: string }[]
  onSelect?: (key: string | number) => void
}) {
  const max = Math.max(...rows.map((r) => r.value), 1)
  return (
    <ul className="space-y-1">
      {rows.map((r) => {
        const inner = (
          <>
            <div className="flex items-baseline justify-between gap-3 text-[13px]">
              <span className="flex min-w-0 items-center gap-2">
                {r.chip && <span className="inline-flex h-5 min-w-9 items-center justify-center rounded bg-slate-100 px-1 font-mono text-[10.5px] font-semibold text-slate-600">{r.chip}</span>}
                <span className="truncate font-medium text-slate-800">{r.label}</span>
                {r.highlight && <span className="rounded-[5px] bg-brand-50 px-1.5 py-px text-[10.5px] font-medium text-brand-700 ring-1 ring-brand-200">your origin</span>}
              </span>
              <span className="tabular shrink-0 text-slate-700">
                {usd(r.value)} <span className="text-muted">· {r.share === null ? '—' : `${(r.share * 100).toFixed(1)}%`}{r.extra ? ` · ${r.extra}` : ''}</span>
              </span>
            </div>
            <div className="mt-1.5 h-1.5 rounded-full bg-slate-100">
              <div className={`h-1.5 rounded-full ${r.highlight ? 'bg-brand-500' : 'bg-ink-800'}`} style={{ width: `${Math.max(1.5, (r.value / max) * 100)}%` }} />
            </div>
          </>
        )
        return (
          <li key={r.key}>
            {onSelect ? (
              <button type="button" onClick={() => onSelect(r.key)} title={r.hint} className="block w-full rounded-lg px-2 py-2 text-left hover:bg-slate-50">
                {inner}
              </button>
            ) : (
              <div className="px-2 py-2" title={r.hint}>{inner}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
