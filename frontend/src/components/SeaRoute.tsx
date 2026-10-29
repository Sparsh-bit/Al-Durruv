import { useQuery } from '@tanstack/react-query'
import { Navigation } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { RouteLocation, SeaRoute as Route } from '../lib/types'
import { Badge, Button, Card, CardHeader, Field, Input, Notice, Select, Spinner } from './ui'

/** Plain SVG of the route (no map tiles, so no third-party requests). Longitudes across the antimeridian are
 * unwrapped so the line stays continuous. */
function RoutePlot({ coords }: { coords: [number, number][] }) {
  const pts: [number, number][] = []
  for (const [lon, lat] of coords) {
    const prev = pts[pts.length - 1]
    let x = lon
    if (prev) while (x - prev[0] > 180) x -= 360
    if (prev) while (prev[0] - x > 180) x += 360
    pts.push([x, lat])
  }
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1])
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const pad = 2, w = Math.max(x1 - x0, 1) + pad * 2, h = Math.max(y1 - y0, 1) + pad * 2
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${(x - x0 + pad).toFixed(3)},${(y1 - y + pad).toFixed(3)}`).join(' ')
  const [sx, sy] = [pts[0][0] - x0 + pad, y1 - pts[0][1] + pad]
  const [ex, ey] = [pts[pts.length - 1][0] - x0 + pad, y1 - pts[pts.length - 1][1] + pad]
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-56 w-full rounded-[10px] border border-line bg-paper" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Route shape">
      <path d={d} fill="none" stroke="#20736e" strokeWidth={Math.max(w, h) / 250} strokeLinejoin="round" />
      <circle cx={sx} cy={sy} r={Math.max(w, h) / 120} fill="#121c1e" />
      <circle cx={ex} cy={ey} r={Math.max(w, h) / 120} fill="#5fc4be" />
    </svg>
  )
}

export default function SeaRoute() {
  const locations = useQuery({ queryKey: ['route-locations'], queryFn: () => api<RouteLocation[]>('/api/route-locations') })
  const [o, setO] = useState('')
  const [d, setD] = useState('')
  const [canals, setCanals] = useState(true)
  const [speed, setSpeed] = useState('')
  const [run, setRun] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['sea-route', run],
    queryFn: () => {
      const p = new URLSearchParams({ origin_location_id: o, destination_location_id: d, canals: String(canals) })
      if (Number(speed) > 0) p.set('speed_knots', speed)
      return api<Route>(`/api/sea-routes?${p}`)
    },
    enabled: run !== null,
    retry: false,
  })
  const locs = locations.data ?? []
  const r = q.data
  return (
    <Card className="mb-6">
      <CardHeader title="Sea route distance" subtitle="Water path and distance between two saved route locations, computed by your self-hosted auto-sea-way service from OpenStreetMap coastlines. No prices, schedules or depth checks." />
      {locs.length < 2 ? (
        <p className="px-5 py-4 text-[13px] text-muted">Save at least two route locations from the Maersk search above.</p>
      ) : (
        <form className="flex flex-wrap items-end gap-3 px-5 py-4" onSubmit={(e) => { e.preventDefault(); setRun(`${o}|${d}|${canals}|${speed}|${Date.now()}`) }}>
          {([['Origin', o, setO], ['Destination', d, setD]] as const).map(([label, v, set]) => (
            <Field key={label} label={label}>
              <Select className="w-64!" value={v} onChange={(e) => set(e.target.value)} required>
                <option value="">Choose…</option>
                {locs.map((l) => <option key={l.id} value={l.id}>{l.location_name || l.city_name} · {l.un_location_code || l.carrier_geo_id}</option>)}
              </Select>
            </Field>
          ))}
          <label className="flex items-center gap-2 pb-2 text-[13px] text-ink-800"><input type="checkbox" className="size-4 accent-ink-900" checked={canals} onChange={(e) => setCanals(e.target.checked)} /> Allow canals (Suez, Panama…)</label>
          <Field label="Speed for an estimate (knots)" hint="Optional"><Input className="w-28" type="number" min={1} max={40} step="0.5" value={speed} onChange={(e) => setSpeed(e.target.value)} /></Field>
          <Button type="submit" icon={<Navigation />} disabled={!o || !d || o === d}>Compute route</Button>
        </form>
      )}
      {run !== null && (
        <div className="border-t border-line-soft px-5 py-4">
          {q.isLoading ? (
            <div className="flex items-center gap-2 text-[13px] text-muted"><Spinner className="size-4" /> Computing route…</div>
          ) : q.isError ? (
            <Notice tone="warn">{q.error.message}</Notice>
          ) : r ? (
            <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
              <div>
                <div className="num text-[28px] text-ink-900">{r.distance_nm.toLocaleString()} nm</div>
                <div className="text-[13px] text-muted">{r.distance_km.toLocaleString()} km · {r.canals ? 'canals allowed' : 'canals avoided'} · <Badge tone="blue">calculated</Badge></div>
                <div className="mt-2 text-[13px]">{r.origin.location_name} → {r.destination.location_name}</div>
                {r.sailing_time_estimate && (
                  <div className="mt-3 rounded-[10px] border border-amber-200 bg-amber-50/70 p-3 text-[13px] text-amber-950">
                    <b>~{r.sailing_time_estimate.days} days sailing</b> <Badge tone="amber">estimate</Badge>
                    <div className="mt-1 text-[12px]">{r.sailing_time_estimate.assumption}</div>
                  </div>
                )}
                <ul className="mt-3 list-disc space-y-1 pl-4 text-[12px] text-body">{r.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
                <p className="mt-3 text-[11.5px] text-muted">{r.source} · graph {r.graph_version}{r.computed_at && ` · computed ${dateTime(r.computed_at)}`} · {r.coordinates_source}</p>
              </div>
              {r.geometry && r.geometry.coordinates.length > 1 && <RoutePlot coords={r.geometry.coordinates} />}
            </div>
          ) : null}
        </div>
      )}
    </Card>
  )
}
