import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MapPin, Search, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { api, del, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime } from '../lib/format'
import type { LocationSearch, MaerskLocation, RouteLocation } from '../lib/types'
import { Badge, Button, Card, CardHeader, CountryChip, EmptyState, Field, Input, Notice, Segmented, Select, Skeleton, Spinner } from './ui'

const TYPES = ['', 'CITY', 'TERMINAL', 'DEPOT', 'RAIL TERMINAL', 'BARGE TERMINAL', 'CONTAINER FREIGHT STATION', 'COUNTRY']

function LocRow({ l, action }: { l: MaerskLocation; action?: React.ReactNode }) {
  return (
    <li className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-[13px]">
      <CountryChip iso3={l.country_code} />
      <div className="min-w-0 flex-1">
        <div className="font-medium text-ink-900">{l.location_name || l.city_name}</div>
        <div className="text-[11.5px] text-muted">
          {l.location_type || 'type n/a'}{l.city_name && ` · ${l.city_name}`}{l.region_name && `, ${l.region_name}`} · {l.country_name}
          {l.has_cy_service !== null && ` · CY service ${l.has_cy_service ? 'yes' : 'no'}`}
        </div>
      </div>
      <div className="text-right text-[11.5px]">
        <div><span className="text-muted">UN/LOCODE</span> <span className="num">{l.un_location_code || '—'}</span></div>
        <div><span className="text-muted">Maersk Geo ID</span> <span className="num">{l.carrier_geo_id || '—'}</span></div>
      </div>
      {action}
    </li>
  )
}

/** Search Maersk locations and keep the ones used on shipment routes. Nothing is auto-selected. */
export default function RouteLocations() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [mode, setMode] = useState<'name' | 'unlocode' | 'geo'>('name')
  const [q, setQ] = useState('')
  const [country, setCountry] = useState('')
  const [type, setType] = useState('')
  const [submitted, setSubmitted] = useState<string | null>(null)
  const saved = useQuery({ queryKey: ['route-locations'], queryFn: () => api<RouteLocation[]>('/api/route-locations') })
  const search = useQuery({
    queryKey: ['maersk-locations', submitted],
    queryFn: () => {
      if (mode === 'geo') return api<MaerskLocation>(`/api/maersk/locations/${encodeURIComponent(q.trim())}`).then((l) => ({ results: [l], next_page: null, retrieved_at: '', source: 'Maersk Locations API v4', ambiguous: false, message: null }) as LocationSearch)
      const p = new URLSearchParams({ mode, limit: '25' })
      if (q.trim()) p.set('q', q.trim())
      if (country.trim()) p.set('country', country.trim())
      if (type) p.set('type', type)
      return api<LocationSearch>(`/api/maersk/locations?${p}`)
    },
    enabled: submitted !== null,
    retry: false,
  })
  const save = useMutation({
    mutationFn: (geo: string) => post<RouteLocation>('/api/route-locations', { carrier_geo_id: geo }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['route-locations'] })
      qc.invalidateQueries({ queryKey: ['maersk-locations'] })
      toast.success(`${r.location_name} saved for routes`)
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => del(`/api/route-locations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['route-locations'] }),
  })
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(`${mode}|${q}|${country}|${type}|${Date.now()}`)
  }
  const d = search.data

  return (
    <Card className="mb-6">
      <CardHeader title="Route locations" subtitle="Search Maersk's location reference (cities, ports, terminals, depots) and save the ones used in your routes. Maersk Geo ID and UN/LOCODE are different identifiers and are kept separately. Reference data only: no prices or schedules." />
      <form className="flex flex-wrap items-end gap-3 border-b border-line-soft px-5 py-4" onSubmit={submit}>
        <div>
          <div className="mb-1.5 text-[13px] font-medium text-ink-800">Search by</div>
          <Segmented label="Search by" value={mode} onChange={setMode} options={[{ value: 'name', label: 'City / port name' }, { value: 'unlocode', label: 'UN/LOCODE' }, { value: 'geo', label: 'Maersk Geo ID' }]} />
        </div>
        <Field label={mode === 'name' ? 'Name' : mode === 'unlocode' ? 'UN/LOCODE' : 'Geo ID'}>
          <Input className="w-56" value={q} onChange={(e) => setQ(e.target.value)} placeholder={mode === 'name' ? 'e.g. Alexandria' : mode === 'unlocode' ? 'e.g. EGALY' : '13 characters'} maxLength={mode === 'geo' ? 13 : 50} />
        </Field>
        {mode !== 'geo' && (
          <>
            <Field label="Country (ISO2/ISO3)"><Input className="w-24 font-mono uppercase" maxLength={3} value={country} onChange={(e) => setCountry(e.target.value.toUpperCase())} /></Field>
            <Field label="Type">
              <Select className="w-48!" value={type} onChange={(e) => setType(e.target.value)}>
                {TYPES.map((t) => <option key={t} value={t}>{t || 'Any type'}</option>)}
              </Select>
            </Field>
          </>
        )}
        <Button type="submit" icon={<Search />} disabled={!q.trim() && !country.trim()}>Search Maersk</Button>
      </form>
      {submitted !== null && (
        <div className="border-b border-line-soft">
          {search.isLoading ? (
            <div className="flex items-center gap-2 px-5 py-4 text-[13px] text-muted"><Spinner className="size-4" /> Searching…</div>
          ) : search.isError ? (
            <div className="p-4"><Notice tone="warn">{search.error.message} Saved locations and quotes below still work.</Notice></div>
          ) : d ? (
            <>
              {d.message && <p className={`px-5 pt-3 text-[12.5px] ${d.ambiguous ? 'text-amber-800' : 'text-muted'}`}>{d.message}</p>}
              <ul className="divide-y divide-line-soft">
                {d.results.map((l) => (
                  <LocRow key={l.carrier_geo_id || l.location_name} l={l} action={
                    l.saved ? <Badge tone="green">saved</Badge> : can('analyst') && l.carrier_geo_id ? (
                      <Button size="sm" variant="secondary" loading={save.isPending && save.variables === l.carrier_geo_id} onClick={() => save.mutate(l.carrier_geo_id)}>Use for routes</Button>
                    ) : null
                  } />
                ))}
              </ul>
              <p className="px-5 py-2 text-[11px] text-muted">{d.source}{d.retrieved_at && ` · retrieved ${dateTime(d.retrieved_at)}`}{d.next_page && ' · more results exist; narrow the search'}</p>
            </>
          ) : null}
        </div>
      )}
      <div className="px-5 pt-4 pb-1 micro text-muted">Saved for routes ({saved.data?.length ?? 0})</div>
      {saved.isLoading ? <Skeleton className="m-5 h-16" /> : (saved.data ?? []).length === 0 ? (
        <EmptyState icon={<MapPin />} title="No route locations yet">Search above and choose the exact port or terminal; nothing is selected automatically.</EmptyState>
      ) : (
        <ul className="divide-y divide-line-soft">
          {saved.data!.map((l) => (
            <LocRow key={l.id} l={l} action={can('admin') && <Button size="sm" variant="ghost" aria-label={`Remove ${l.location_name}`} onClick={() => remove.mutate(l.id)}><Trash2 /></Button>} />
          ))}
        </ul>
      )}
    </Card>
  )
}
