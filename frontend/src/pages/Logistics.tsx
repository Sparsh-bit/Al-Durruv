import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Ship, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, Notice, PageHeader, Select, Skeleton, Table, td, th } from '../components/ui'
import { api, del, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date, usd } from '../lib/format'
import type { Provider, Quote, RouteLocation } from '../lib/types'
import RouteLocations from '../components/RouteLocations'

const EMPTY = {
  origin: '',
  origin_iso3: '',
  payload_kg: '',
  destination: '',
  destination_iso3: '',
  mode: 'sea',
  container: "40' HC",
  carrier: '',
  incoterm: 'FOB',
  cost_usd: '',
  transit_days: '',
  source_note: '',
  assumptions: '',
  valid_until: '',
  origin_location_id: '',
  destination_location_id: '',
}
const INCOTERMS = ['', 'EXW', 'FCA', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP']

function QuoteForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState(EMPTY)
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }))
  const locations = useQuery({ queryKey: ['route-locations'], queryFn: () => api<RouteLocation[]>('/api/route-locations') })
  const pickLocation = (side: 'origin' | 'destination', id: string) => {
    const l = locations.data?.find((x) => String(x.id) === id)
    setF((s) => ({
      ...s,
      [`${side}_location_id`]: id,
      ...(l ? { [side]: l.location_name || l.city_name, ...(side === 'destination' ? { destination_iso3: l.country_iso3 } : {}) } : {}),
    }))
  }
  const save = useMutation({
    mutationFn: () =>
      post<Quote>('/api/logistics', {
        ...f,
        destination_iso3: f.destination_iso3.toUpperCase(),
        cost_usd: f.cost_usd === '' ? null : Number(f.cost_usd),
        payload_kg: f.payload_kg === '' ? null : Number(f.payload_kg),
        transit_days: f.transit_days === '' ? null : Number(f.transit_days),
        valid_until: f.valid_until ? new Date(f.valid_until).toISOString() : null,
        origin_location_id: f.origin_location_id ? Number(f.origin_location_id) : null,
        destination_location_id: f.destination_location_id ? Number(f.destination_location_id) : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['logistics'] })
      toast.success('Quote saved')
      onDone()
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <Notice>Enter only quotes you actually received (from a forwarder, carrier or platform). They are labelled <b>Client-provided</b> everywhere.</Notice>
      {(locations.data?.length ?? 0) > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {(['origin', 'destination'] as const).map((side) => (
            <Field key={side} label={`${side === 'origin' ? 'Origin' : 'Destination'} from saved Maersk locations`}>
              <Select value={f[`${side}_location_id`]} onChange={(e) => pickLocation(side, e.target.value)}>
                <option value="">Not linked</option>
                {locations.data!.map((l) => <option key={l.id} value={l.id}>{l.location_name || l.city_name} · {l.un_location_code || l.carrier_geo_id} · {l.country_code}</option>)}
              </Select>
            </Field>
          ))}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Origin (port or city)"><Input required minLength={2} value={f.origin} onChange={set('origin')} placeholder="e.g. Alexandria" /></Field>
        <Field label="Factory country (ISO3)" hint="EGY, JOR or SYR: used for landed cost"><Input maxLength={3} pattern="[A-Za-z]{3}" value={f.origin_iso3} onChange={set('origin_iso3')} className="font-mono uppercase" /></Field>
        <Field label="Destination (port or city)"><Input required minLength={2} value={f.destination} onChange={set('destination')} placeholder="e.g. Felixstowe" /></Field>
        <Field label="Destination country (ISO3)"><Input required minLength={3} maxLength={3} value={f.destination_iso3} onChange={set('destination_iso3')} placeholder="GBR" /></Field>
        <Field label="Mode">
          <Select value={f.mode} onChange={set('mode')}>
            <option value="sea">Sea</option><option value="air">Air</option><option value="road">Road</option><option value="rail">Rail</option>
          </Select>
        </Field>
        <Field label="Equipment"><Input maxLength={40} value={f.container} onChange={set('container')} /></Field>
        <Field label="Carrier / forwarder"><Input maxLength={120} value={f.carrier} onChange={set('carrier')} placeholder="e.g. MSC via forwarder X" /></Field>
        <Field label="Incoterm">
          <Select value={f.incoterm} onChange={set('incoterm')}>
            {INCOTERMS.map((t) => <option key={t} value={t}>{t || 'Not stated'}</option>)}
          </Select>
        </Field>
        <Field label="Cost (USD)"><Input type="number" min={0} step="0.01" value={f.cost_usd} onChange={set('cost_usd')} /></Field>
        <Field label="Cargo per container (kg)" hint="Gives freight per kg"><Input type="number" min={1} step="1" value={f.payload_kg} onChange={set('payload_kg')} /></Field>
        <Field label="Transit time (days)"><Input type="number" min={0} max={365} value={f.transit_days} onChange={set('transit_days')} /></Field>
        <Field label="Valid until"><Input type="date" value={f.valid_until} onChange={set('valid_until')} /></Field>
      </div>
      <Field label="Source" hint="Who quoted it and when, e.g. 'Forwarder X quote ref 1234, 20 Oct 2026'">
        <Input required minLength={3} value={f.source_note} onChange={set('source_note')} />
      </Field>
      <Field label="Assumptions" hint="Weight, pallets, service level, surcharges included or excluded…">
        <Input maxLength={2000} value={f.assumptions} onChange={set('assumptions')} />
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>Save quote</Button>
      </div>
    </form>
  )
}

function Comparison({ quotes }: { quotes: Quote[] }) {
  const groups = [...new Map(quotes.map((q) => [q.destination_iso3, quotes.filter((x) => x.destination_iso3 === q.destination_iso3)])).entries()].filter(
    ([, qs]) => qs.length > 1,
  )
  if (!groups.length) return null
  return (
    <Card className="mb-6">
      <CardHeader title="Route comparison" subtitle="Destinations with more than one quote. Compare like for like: check equipment, Incoterm and assumptions." />
      <div className="divide-y divide-line">
        {groups.map(([iso, qs]) => {
          const priced = qs.filter((q) => q.cost_usd !== null)
          const timed = qs.filter((q) => q.transit_days !== null)
          const cheapest = priced.length ? Math.min(...priced.map((q) => q.cost_usd!)) : null
          const fastest = timed.length ? Math.min(...timed.map((q) => q.transit_days!)) : null
          return (
            <div key={iso} className="px-5 py-3">
              <div className="mb-2 text-sm font-semibold text-slate-900">To {iso}</div>
              <ul className="space-y-1.5 text-sm">
                {qs.map((q) => (
                  <li key={q.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="min-w-56">{q.origin} → {q.destination} <span className="text-muted capitalize">· {q.mode}{q.container ? ` · ${q.container}` : ''}{q.incoterm ? ` · ${q.incoterm}` : ''}</span></span>
                    <span className="tabular">{q.cost_usd === null ? '—' : usd(q.cost_usd, 2)}</span>
                    <span className="tabular text-muted">{q.transit_days === null ? '—' : `${q.transit_days} d`}</span>
                    {q.cost_usd !== null && q.cost_usd === cheapest && <Badge tone="green">Cheapest</Badge>}
                    {q.transit_days !== null && q.transit_days === fastest && <Badge tone="blue">Fastest</Badge>}
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

export default function Logistics() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const data = useQuery({ queryKey: ['logistics', 'all'], queryFn: () => api<{ providers: Provider[]; quotes: Quote[] }>('/api/logistics') })
  const remove = useMutation({
    mutationFn: (id: number) => del(`/api/logistics/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['logistics'] })
      toast.success('Quote deleted')
    },
  })
  return (
    <>
      <PageHeader
        title="Logistics"
        subtitle="Freight rates and transit times. Nothing here is estimated by AI: values come from a connected provider or are entered by your team with their source."
        actions={can('admin') && <Button icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>Add quote</Button>}
      />
      <div className="mb-6 grid gap-4 md:grid-cols-2">
        {data.data?.providers.map((p) => (
          <Card key={p.key} className="p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="text-sm font-semibold text-slate-900">{p.name}</div>
              <Badge tone="amber">Not connected</Badge>
            </div>
            <p className="mt-2 text-[13px] text-muted">{p.detail}</p>
          </Card>
        ))}
      </div>
      <Comparison quotes={data.data?.quotes ?? []} />
      <RouteLocations />
      <Card>
        <CardHeader title="Client-provided quotes" subtitle="Shown in market detail and cited by the AI analyst as labelled estimates" />
        {data.isLoading ? (
          <div className="p-5"><Skeleton className="h-24" /></div>
        ) : data.isError ? (
          <div className="p-5"><Notice tone="error">{data.error.message}</Notice></div>
        ) : !data.data?.quotes.length ? (
          <EmptyState icon={<Ship className="size-6" />} title="No quotes yet">Add quotes from your forwarders to compare routes and landed costs.</EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <th className={th}>Route</th><th className={th}>Mode</th><th className={`${th} text-right`}>Cost</th><th className={`${th} text-right`}>Transit</th>
                <th className={th}>Source</th><th className={th}>Valid until</th><th className={th}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {data.data.quotes.map((q) => (
                <tr key={q.id}>
                  <td className={td}><div className="font-medium">{q.origin} → {q.destination}</div><div className="text-xs text-muted">{q.destination_iso3}</div></td>
                  <td className={`${td} capitalize`}>{q.mode} {q.container && <span className="text-muted">· {q.container}</span>}</td>
                  <td className={`${td} tabular text-right`}>{q.cost_usd === null ? '—' : usd(q.cost_usd, 2)}</td>
                  <td className={`${td} tabular text-right`}>{q.transit_days === null ? '—' : `${q.transit_days} d`}</td>
                  <td className={td}>
                    <Badge tone="amber">Client-provided</Badge>
                    <div className="mt-1 max-w-xs text-xs text-muted">{q.source_note}{q.carrier ? ` · ${q.carrier}` : ''}{q.incoterm ? ` · ${q.incoterm}` : ''}</div>
                    {q.assumptions && <div className="mt-0.5 max-w-xs text-xs text-muted italic">{q.assumptions}</div>}
                  </td>
                  <td className={`${td} text-muted`}>{date(q.valid_until)}</td>
                  <td className={`${td} text-right`}>
                    {can('admin') && <Button size="sm" variant="ghost" aria-label="Delete quote" loading={remove.isPending && remove.variables === q.id} onClick={() => remove.mutate(q.id)}><Trash2 className="size-4" /></Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Modal open={open} onOpenChange={setOpen} title="Add freight quote" wide>
        {open && <QuoteForm onDone={() => setOpen(false)} />}
      </Modal>
    </>
  )
}
