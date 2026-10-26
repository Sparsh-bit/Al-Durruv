import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Ship, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, Notice, PageHeader, Select, Skeleton, Table, td, th } from '../components/ui'
import { api, del, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date, usd } from '../lib/format'
import type { Provider, Quote } from '../lib/types'

const EMPTY = { origin: '', destination: '', destination_iso3: '', mode: 'sea', container: "40' HC", cost_usd: '', transit_days: '', source_note: '', valid_until: '' }

function QuoteForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState(EMPTY)
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }))
  const save = useMutation({
    mutationFn: () =>
      post<Quote>('/api/logistics', {
        ...f,
        destination_iso3: f.destination_iso3.toUpperCase(),
        cost_usd: f.cost_usd === '' ? null : Number(f.cost_usd),
        transit_days: f.transit_days === '' ? null : Number(f.transit_days),
        valid_until: f.valid_until ? new Date(f.valid_until).toISOString() : null,
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
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Origin (port or city)"><Input required minLength={2} value={f.origin} onChange={set('origin')} placeholder="e.g. Jebel Ali" /></Field>
        <Field label="Destination (port or city)"><Input required minLength={2} value={f.destination} onChange={set('destination')} placeholder="e.g. Felixstowe" /></Field>
        <Field label="Destination country (ISO3)"><Input required minLength={3} maxLength={3} value={f.destination_iso3} onChange={set('destination_iso3')} placeholder="GBR" /></Field>
        <Field label="Mode">
          <Select value={f.mode} onChange={set('mode')}>
            <option value="sea">Sea</option><option value="air">Air</option><option value="road">Road</option><option value="rail">Rail</option>
          </Select>
        </Field>
        <Field label="Equipment"><Input value={f.container} onChange={set('container')} /></Field>
        <Field label="Cost (USD)"><Input type="number" min={0} step="0.01" value={f.cost_usd} onChange={set('cost_usd')} /></Field>
        <Field label="Transit time (days)"><Input type="number" min={0} max={365} value={f.transit_days} onChange={set('transit_days')} /></Field>
        <Field label="Valid until"><Input type="date" value={f.valid_until} onChange={set('valid_until')} /></Field>
      </div>
      <Field label="Source" hint="Who quoted it and when, e.g. 'Forwarder X quote ref 1234, 20 Oct 2026'">
        <Input required minLength={3} value={f.source_note} onChange={set('source_note')} />
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>Save quote</Button>
      </div>
    </form>
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
        actions={can('analyst') && <Button icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>Add quote</Button>}
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
                  <td className={td}><Badge tone="amber">Client-provided</Badge><div className="mt-1 max-w-xs text-xs text-muted">{q.source_note}</div></td>
                  <td className={`${td} text-muted`}>{date(q.valid_until)}</td>
                  <td className={`${td} text-right`}>
                    {can('analyst') && <Button size="sm" variant="ghost" aria-label="Delete quote" loading={remove.isPending && remove.variables === q.id} onClick={() => remove.mutate(q.id)}><Trash2 className="size-4" /></Button>}
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
