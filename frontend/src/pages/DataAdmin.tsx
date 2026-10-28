import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, FileUp, Play, Plus, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Modal, Notice, PageHeader, Segmented, Select, Skeleton, SourceLink, StatusDot, td, th } from '../components/ui'
import { api, del, post } from '../lib/api'
import { date, dateTime, num } from '../lib/format'
import { useRun } from '../lib/hooks'
import { useReveal } from '../lib/motion'
import type { ImportBatch, Product, Run, ShipmentPreview, SourceFreshness, Tariff } from '../lib/types'

type Tab = 'shipments' | 'connectors' | 'tariffs'
const PROVIDERS = ['importgenius', 'panjiva', 'volza', 'other']

function Shipments() {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [provider, setProvider] = useState('importgenius')
  const [preview, setPreview] = useState<ShipmentPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const batches = useQuery({ queryKey: ['batches'], queryFn: () => api<ImportBatch[]>('/api/shipments/batches') })
  const form = (extra: Record<string, string> = {}) => {
    const fd = new FormData()
    fd.append('file', file!)
    fd.append('provider', provider)
    for (const [k, v] of Object.entries(extra)) fd.append(k, v)
    return fd
  }
  const doPreview = useMutation({
    mutationFn: () => api<ShipmentPreview>('/api/shipments/preview', { method: 'POST', body: form() }),
    onSuccess: (p) => {
      setPreview(p)
      setMapping(p.suggested_mapping)
    },
  })
  const doImport = useMutation({
    mutationFn: () => api<ImportBatch>('/api/shipments/import', { method: 'POST', body: form({ mapping: JSON.stringify(mapping), save_mapping: 'true' }) }),
    onSuccess: (b) => {
      toast.success(`${b.inserted} shipments imported, ${b.duplicates} duplicates skipped`)
      setPreview(null)
      setFile(null)
      qc.invalidateQueries({ queryKey: ['batches'] })
      qc.invalidateQueries({ queryKey: ['buyers'] })
      qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => del(`/api/shipments/batches/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['batches'] }),
  })
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Upload a shipment file" subtitle="CSV or Excel export from a licensed bill-of-lading provider (max 15 MB, 200,000 rows). Only cell values are read; formulas are never run. Rows are de-duplicated." />
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Provider">
              <Select className="w-48!" value={provider} onChange={(e) => setProvider(e.target.value)}>
                {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
              </Select>
            </Field>
            <input ref={input} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null) }} />
            <Button variant="secondary" icon={<FileUp />} onClick={() => input.current?.click()}>{file ? file.name : 'Choose file'}</Button>
            <Button disabled={!file} loading={doPreview.isPending} onClick={() => doPreview.mutate()}>Preview</Button>
          </div>
          {preview && (
            <>
              <p className="text-[13px] text-body">{num(preview.rows)} rows. Check the column mapping; it is saved for this provider.</p>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(preview.fields).map(([f, label]) => (
                  <Field key={f} label={label}>
                    <Select value={mapping[f] ?? ''} onChange={(e) => setMapping((m) => { const n = { ...m }; if (e.target.value) n[f] = e.target.value; else delete n[f]; return n })}>
                      <option value="">Not in file</option>
                      {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                    </Select>
                  </Field>
                ))}
              </div>
              {preview.mapping_error && <Notice tone="warn">{preview.mapping_error}</Notice>}
              {preview.sample_errors.length > 0 && (
                <Notice tone="warn" title="Rows that will be skipped or flagged (first 50 checked)">
                  <ul className="list-disc pl-4">{preview.sample_errors.slice(0, 6).map((e) => <li key={`${e.line}${e.error}`}>Line {e.line}: {e.error}</li>)}</ul>
                </Notice>
              )}
              {preview.sample.length > 0 && (
                <div className="overflow-x-auto rounded-[10px] border border-line">
                  <table className="w-full text-left text-[12px]">
                    <thead><tr>{['Date', 'Shipper', 'Consignee', 'Origin', 'Dest.', 'HS', 'kg'].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
                    <tbody>
                      {preview.sample.slice(0, 5).map((r, i) => (
                        <tr key={i}>
                          {['shipped_on', 'shipper_name', 'consignee_name', 'origin_iso3', 'destination_iso3', 'hs_code', 'weight_kg'].map((k) => <td key={k} className={td}>{String(r[k] ?? '')}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="flex justify-end"><Button loading={doImport.isPending} onClick={() => doImport.mutate()}>Import {num(preview.rows)} rows</Button></div>
            </>
          )}
        </div>
      </Card>
      <Card>
        <CardHeader title="Imports" subtitle="Raw rows are visible only to signed-in users and are not exported in bulk (provider licence)." />
        {batches.isLoading ? <Skeleton className="m-5 h-24" /> : (batches.data ?? []).length === 0 ? (
          <EmptyState icon={<Database />} title="No shipment files imported yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead><tr>{['File', 'Provider', 'Rows', 'New', 'Duplicates', 'Issues', 'Imported', ''].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>
                {batches.data!.map((b) => (
                  <tr key={b.id}>
                    <td className={td}>{b.filename}</td>
                    <td className={td}>{b.provider}</td>
                    <td className={`${td} num`}>{num(b.row_count)}</td>
                    <td className={`${td} num`}>{num(b.inserted)}</td>
                    <td className={`${td} num`}>{num(b.duplicates)}</td>
                    <td className={td}>{b.errors.length ? <span title={b.errors.slice(0, 5).map((e) => `Line ${e.line}: ${e.error}`).join('\n')} className="text-amber-800">{b.errors.length}</span> : '0'}</td>
                    <td className={`${td} text-[12px] text-muted`}>{dateTime(b.created_at)}</td>
                    <td className={`${td} text-right`}><Button size="sm" variant="ghost" aria-label={`Delete ${b.filename}`} onClick={() => remove.mutate(b.id)}><Trash2 /></Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function Connectors() {
  const qc = useQueryClient()
  const fresh = useQuery({ queryKey: ['freshness'], queryFn: () => api<{ sources: SourceFreshness[] }>('/api/admin/freshness') })
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products') })
  const [connector, setConnector] = useState<'comext' | 'census' | 'tariffs' | 'fx'>('comext')
  const [hs, setHs] = useState('200290')
  const [months, setMonths] = useState('12')
  const [markets, setMarkets] = useState('USA, EUN')
  const [runId, setRunId] = useState<number | null>(null)
  const run = useRun(runId, (r) => {
    qc.invalidateQueries({ queryKey: ['freshness'] })
    if (r.status === 'succeeded') toast.success(`${r.adapter}: ${r.message}`)
    else toast.error(r.error || 'Run failed')
  })
  const start = useMutation({
    mutationFn: () => post<Run>('/api/admin/etl', {
      connector,
      hs_codes: hs.split(/[\s,]+/).filter(Boolean),
      months_back: Number(months) || 12,
      markets: markets.split(/[\s,]+/).filter(Boolean),
    }),
    onSuccess: (r) => setRunId(r.id),
  })
  const hsList = [...new Set((products.data ?? []).map((p) => p.hs_code).filter(Boolean))].sort().join(', ')
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Data freshness" subtitle="Latest retrieval per source. Confidence: official (statistics agencies, tariff schedules), licensed (provider files), estimate (freight)." />
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead><tr>{['Source', 'Confidence', 'Rows', 'Latest period', 'Last retrieved', 'Last run'].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>
              {(fresh.data?.sources ?? []).map((s) => (
                <tr key={s.key}>
                  <td className={td}>
                    <div className="font-medium text-ink-900">{s.name}</div>
                    {s.needs && <div className="text-[12px] text-amber-800">Needs {s.needs}</div>}
                  </td>
                  <td className={td}><Badge tone={s.confidence === 'official' ? 'green' : s.confidence === 'licensed' ? 'blue' : 'amber'}>{s.confidence}</Badge></td>
                  <td className={`${td} num`}>{s.rows !== undefined ? num(s.rows) : '—'}</td>
                  <td className={`${td} num`}>{s.latest_period ?? '—'}</td>
                  <td className={`${td} text-[12px]`}>{s.last_retrieved ? dateTime(s.last_retrieved) : '—'}</td>
                  <td className={td}>
                    {s.last_run ? <StatusDot tone={s.last_run.status === 'succeeded' ? 'green' : s.last_run.status === 'failed' ? 'red' : 'amber'}>{s.last_run.status}</StatusDot> : '—'}
                    {s.last_run?.error && <div className="max-w-64 text-[11.5px] text-red-700">{s.last_run.error}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card>
        <CardHeader title="Run a connector" subtitle="Runs in the background and is logged. Responses are cached, so repeating a run does not spend quota twice." />
        <div className="flex flex-wrap items-end gap-3 p-5">
          <Field label="Connector">
            <Select className="w-56!" value={connector} onChange={(e) => setConnector(e.target.value as typeof connector)}>
              <option value="comext">Eurostat Comext (EU monthly)</option>
              <option value="census">US Census (US monthly)</option>
              <option value="tariffs">Tariffs (WITS + USITC)</option>
              <option value="fx">FX rates (ECB)</option>
            </Select>
          </Field>
          {connector !== 'fx' && <Field label="HS codes" hint={hsList ? `Catalogue: ${hsList.slice(0, 60)}…` : undefined}><Input className="w-64 font-mono" value={hs} onChange={(e) => setHs(e.target.value)} /></Field>}
          {connector !== 'tariffs' && <Field label="Months back"><Input className="w-24" type="number" min={1} max={36} value={months} onChange={(e) => setMonths(e.target.value)} /></Field>}
          {connector === 'tariffs' && <Field label="Markets (ISO3; EUN = EU)"><Input className="w-40 font-mono uppercase" value={markets} onChange={(e) => setMarkets(e.target.value)} /></Field>}
          <Button icon={<Play />} loading={start.isPending || (run && ['queued', 'running'].includes(run.status))} onClick={() => start.mutate()}>Run</Button>
          {run && <span className="text-[12.5px] text-muted">{run.status} · {run.message}</span>}
        </div>
        <p className="px-5 pb-4 text-[12px] text-muted">UN Comtrade annual data is refreshed from <Link to="/products" className="text-brand-700 underline">Products → Load missing data</Link>. Freight routes are managed in <Link to="/logistics" className="text-brand-700 underline">Logistics</Link>.</p>
      </Card>
    </div>
  )
}

function Tariffs() {
  const qc = useQueryClient()
  const [market, setMarket] = useState('USA')
  const [hs, setHs] = useState('2002')
  const [adding, setAdding] = useState(false)
  const [f, setF] = useState({ importer_iso3: 'USA', hs_code: '', origin_iso3: '', rate_type: 'additional', ad_valorem_pct: '', agreement: '', source_url: '', notes: '' })
  const list = useQuery({ queryKey: ['tariffs', market, hs], queryFn: () => api<Tariff[]>(`/api/tariffs?market=${market}&hs=${hs}`) })
  const add = useMutation({
    mutationFn: () => post('/api/tariffs', { ...f, ad_valorem_pct: f.ad_valorem_pct === '' ? null : Number(f.ad_valorem_pct) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tariffs'] })
      qc.invalidateQueries({ queryKey: ['access'] })
      setAdding(false)
      toast.success('Override saved')
    },
  })
  const remove = useMutation({ mutationFn: (id: number) => del(`/api/tariffs/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['tariffs'] }) })
  return (
    <Card>
      <CardHeader title="Tariffs" subtitle="Connector rates (WITS, USITC) and admin overrides. An override wins for the same importer, HS code, origin and type. Tariffs are never hard-coded." action={<Button size="sm" icon={<Plus />} onClick={() => setAdding(true)}>Add override</Button>} />
      <div className="flex flex-wrap gap-3 border-b border-line-soft px-5 py-3">
        <Input className="w-24 font-mono uppercase" value={market} maxLength={3} onChange={(e) => setMarket(e.target.value.toUpperCase())} aria-label="Importer" />
        <Input className="w-32 font-mono" value={hs} onChange={(e) => setHs(e.target.value)} aria-label="HS prefix" />
      </div>
      {list.isLoading ? <Skeleton className="m-5 h-24" /> : (list.data ?? []).length === 0 ? (
        <EmptyState icon={<Database />} title="No tariffs on file for this filter">Run the tariff connector or add an override.</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead><tr>{['Importer', 'HS', 'Origin', 'Type', 'Rate', 'Source', 'Verified', ''].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>
              {list.data!.map((t) => (
                <tr key={t.id}>
                  <td className={`${td} num`}>{t.importer_iso3}</td>
                  <td className={`${td} num`}>{t.hs_code}</td>
                  <td className={`${td} num`}>{t.origin_iso3 || 'any'}</td>
                  <td className={td}>{t.rate_type}{t.agreement && <div className="text-[11px] text-muted">{t.agreement}</div>}</td>
                  <td className={`${td} num`}>{t.ad_valorem_pct !== null ? `${t.ad_valorem_pct.toFixed(2)}%` : t.specific_rate || '—'}</td>
                  <td className={td}><Badge tone={t.source === 'override' ? 'amber' : 'green'}>{t.source}</Badge> {t.source_url && <SourceLink source={{ url: t.source_url }} compact />}{t.data_year && <span className="ml-1 text-[11px] text-muted">{t.data_year}</span>}</td>
                  <td className={`${td} text-[12px]`}>{date(t.verified_at)}</td>
                  <td className={`${td} text-right`}>{t.source === 'override' && <Button size="sm" variant="ghost" aria-label="Delete override" onClick={() => remove.mutate(t.id)}><Trash2 /></Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Modal open={adding} onOpenChange={setAdding} title="Tariff override" description="For rates the connectors do not carry, e.g. US Chapter 99 additional duties. A source URL is required.">
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
          <Field label="Importer (ISO3, EUN = EU)"><Input required maxLength={3} value={f.importer_iso3} onChange={(e) => setF({ ...f, importer_iso3: e.target.value.toUpperCase() })} /></Field>
          <Field label="HS code (6–10 digits)"><Input required pattern="\d{6,10}" value={f.hs_code} onChange={(e) => setF({ ...f, hs_code: e.target.value })} /></Field>
          <Field label="Origin (ISO3, empty = any)"><Input maxLength={3} value={f.origin_iso3} onChange={(e) => setF({ ...f, origin_iso3: e.target.value.toUpperCase() })} /></Field>
          <Field label="Type">
            <Select value={f.rate_type} onChange={(e) => setF({ ...f, rate_type: e.target.value })}>
              <option value="MFN">MFN</option><option value="preferential">Preferential</option><option value="additional">Additional duty</option>
            </Select>
          </Field>
          <Field label="Ad valorem %"><Input type="number" min={0} step="0.01" value={f.ad_valorem_pct} onChange={(e) => setF({ ...f, ad_valorem_pct: e.target.value })} /></Field>
          <Field label="Agreement / measure"><Input value={f.agreement} onChange={(e) => setF({ ...f, agreement: e.target.value })} /></Field>
          <div className="sm:col-span-2"><Field label="Source URL"><Input required type="url" value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} /></Field></div>
          <div className="sm:col-span-2"><Field label="Notes"><Input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field></div>
          <div className="flex justify-end gap-2 sm:col-span-2"><Button variant="secondary" onClick={() => setAdding(false)}>Cancel</Button><Button type="submit" loading={add.isPending}>Save</Button></div>
        </form>
      </Modal>
    </Card>
  )
}

export default function DataAdmin() {
  const [tab, setTab] = useState<Tab>('shipments')
  const ref = useReveal<HTMLDivElement>([tab])
  return (
    <div ref={ref}>
      <PageHeader eyebrow="Administration" title="Data admin" subtitle="Shipment uploads, connector runs and data freshness, and tariff overrides. Only administrators can change data here." />
      <div className="mb-5"><Segmented label="Section" value={tab} onChange={setTab} options={[{ value: 'shipments', label: 'Shipment files' }, { value: 'connectors', label: 'Connectors' }, { value: 'tariffs', label: 'Tariffs' }]} /></div>
      {tab === 'shipments' ? <Shipments /> : tab === 'connectors' ? <Connectors /> : <Tariffs />}
    </div>
  )
}
