import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileUp, Globe2, Plus, Trash2, X } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, EmptyState, Input, Notice, PageHeader, Pager, Segmented, Select, Skeleton, Spinner, td, th } from '../components/ui'
import { api, del, put } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date } from '../lib/format'
import { useReveal } from '../lib/motion'
import type { Region, TargetMarket } from '../lib/types'

type Markets = { markets: TargetMarket[]; counts: Record<string, number> }
type ImportResult = { imported: number; errors: { line: number; error: string }[] }
const PAGE = 25

function RegionEditor({ regions }: { regions: Region[] }) {
  const qc = useQueryClient()
  const { can } = useAuth()
  const [draft, setDraft] = useState<Record<string, string[]> | null>(null)
  const [add, setAdd] = useState<Record<string, string>>({})
  const [newRegion, setNewRegion] = useState('')
  const value = draft ?? Object.fromEntries(regions.map((r) => [r.name, r.members.map((m) => m.iso3)]))
  const names = new Map(regions.flatMap((r) => r.members.map((m) => [m.iso3, m.name] as const)))
  const save = useMutation({
    mutationFn: () => put<Region[]>('/api/regions', { regions: value }),
    onSuccess: (r) => {
      qc.setQueryData(['regions'], r)
      qc.invalidateQueries({ queryKey: ['target-markets'] })
      setDraft(null)
      toast.success('Regions saved')
    },
  })
  const edit = (region: string, members: string[]) => setDraft({ ...value, [region]: [...new Set(members)].sort() })
  return (
    <Card>
      <CardHeader
        title="Regions"
        subtitle="Region membership drives explorer totals and filters. Defaults: EU-27 with the UK, Switzerland, Norway and Iceland; the USA; and East and South-East Asia. Edit to match the client's definitions."
        action={can('admin') && draft && <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>Save regions</Button>}
      />
      <div className="divide-y divide-line-soft">
        {Object.entries(value).map(([region, members]) => (
          <div key={region} className="px-5 py-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="font-display text-[15px] font-semibold">{region} <span className="num ml-1 text-[12px] font-normal text-muted">{members.length}</span></div>
              {can('admin') && (
                <button type="button" className="text-[12px] text-muted hover:text-red-700" onClick={() => setDraft(Object.fromEntries(Object.entries(value).filter(([k]) => k !== region)))}>
                  Remove region
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {members.map((m) => (
                <span key={m} className="inline-flex items-center gap-1 rounded-[6px] border border-line bg-paper px-1.5 py-0.5 text-[11.5px]" title={names.get(m)}>
                  <span className="num">{m}</span>
                  {can('admin') && (
                    <button type="button" aria-label={`Remove ${m} from ${region}`} onClick={() => edit(region, members.filter((x) => x !== m))} className="text-muted hover:text-red-700">
                      <X className="size-3" />
                    </button>
                  )}
                </span>
              ))}
              {can('admin') && (
                <form
                  className="inline-flex"
                  onSubmit={(e) => {
                    e.preventDefault()
                    const codes = (add[region] ?? '').split(/[\s,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean)
                    if (codes.length) edit(region, [...members, ...codes])
                    setAdd({ ...add, [region]: '' })
                  }}
                >
                  <input
                    value={add[region] ?? ''}
                    onChange={(e) => setAdd({ ...add, [region]: e.target.value })}
                    placeholder="+ ISO3"
                    aria-label={`Add countries to ${region}`}
                    className="num h-6 w-20 rounded-[6px] border border-dashed border-line bg-white px-1.5 text-[11.5px] uppercase outline-none focus:border-brand-600"
                  />
                </form>
              )}
            </div>
          </div>
        ))}
        {can('admin') && (
          <form
            className="flex gap-2 px-5 py-4"
            onSubmit={(e) => {
              e.preventDefault()
              const n = newRegion.trim()
              if (n && !value[n]) setDraft({ ...value, [n]: [] })
              setNewRegion('')
            }}
          >
            <Input value={newRegion} onChange={(e) => setNewRegion(e.target.value)} placeholder="New region name" className="max-w-xs" />
            <Button type="submit" variant="secondary" icon={<Plus />} disabled={!newRegion.trim()}>Add region</Button>
          </form>
        )}
      </div>
      {draft && <p className="px-5 pb-4 text-[12px] text-amber-800">Unsaved changes. Unknown country codes are rejected when you save.</p>}
    </Card>
  )
}

export default function MarketsRegions() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const markets = useQuery({ queryKey: ['target-markets'], queryFn: () => api<Markets>('/api/target-markets') })
  const regions = useQuery({ queryKey: ['regions'], queryFn: () => api<Region[]>('/api/regions') })
  const fileRef = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [segment, setSegment] = useState<'all' | 'existing' | 'expansion'>('all')
  const [region, setRegion] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)
  const ref = useReveal<HTMLDivElement>([markets.isSuccess])

  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return api<ImportResult>('/api/target-markets/import', { method: 'POST', body: fd })
    },
    onSuccess: (r) => {
      setResult(r)
      qc.invalidateQueries({ queryKey: ['target-markets'] })
      qc.invalidateQueries({ queryKey: ['overview-dash'] })
      toast.success(`${r.imported} countries imported`)
    },
  })
  const setSeg = useMutation({
    mutationFn: (m: TargetMarket) => put(`/api/target-markets/${m.iso3}`, { segment: m.segment === 'existing' ? 'expansion' : 'existing', notes: m.notes }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['target-markets'] }),
  })
  const remove = useMutation({
    mutationFn: (iso3: string) => del(`/api/target-markets/${iso3}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['target-markets'] }),
  })

  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    return (markets.data?.markets ?? []).filter(
      (m) => (segment === 'all' || m.segment === segment) && (!region || m.regions.includes(region)) && (!t || `${m.iso3} ${m.name}`.toLowerCase().includes(t)),
    )
  }, [markets.data, segment, region, q])
  const pages = Math.max(1, Math.ceil(rows.length / PAGE))
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE)
  const counts = markets.data?.counts ?? {}
  const total = (counts.existing ?? 0) + (counts.expansion ?? 0)

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Target markets"
        title="Markets & regions"
        subtitle="The client's country list, split into existing and expansion markets. It comes from the client's own file and is not hard-coded."
        actions={
          can('analyst') && (
            <>
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
              <Button icon={upload.isPending ? <Spinner className="size-4 text-white" /> : <FileUp />} onClick={() => fileRef.current?.click()}>
                Import country list
              </Button>
            </>
          )
        }
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Card className="p-5" ><div className="micro text-muted">Countries in list</div><div className="num mt-2 text-[28px]">{total}</div></Card>
        <Card className="p-5"><div className="micro text-muted">Existing markets</div><div className="num mt-2 text-[28px]">{counts.existing ?? 0}</div></Card>
        <Card className="p-5"><div className="micro text-muted">Expansion markets</div><div className="num mt-2 text-[28px]">{counts.expansion ?? 0}</div></Card>
      </div>
      {result && result.errors.length > 0 && (
        <div className="mb-6">
          <Notice tone="warn" title={`${result.errors.length} rows were not imported`}>
            <ul className="mt-1 list-disc pl-4">{result.errors.slice(0, 8).map((e) => <li key={e.line}>Line {e.line}: {e.error}</li>)}</ul>
          </Notice>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <div className="flex flex-wrap items-center gap-3 border-b border-line-soft px-5 py-3">
            <Segmented label="Segment" value={segment} onChange={(v) => { setSegment(v); setPage(0) }} options={[{ value: 'all', label: 'All' }, { value: 'existing', label: 'Existing' }, { value: 'expansion', label: 'Expansion' }]} />
            <Select className="w-auto!" value={region} onChange={(e) => { setRegion(e.target.value); setPage(0) }} aria-label="Filter by region">
              <option value="">Any region</option>
              {(regions.data ?? []).map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
            </Select>
            <Input className="max-w-48" placeholder="Search country" value={q} onChange={(e) => { setQ(e.target.value); setPage(0) }} aria-label="Search countries" />
          </div>
          {markets.isLoading ? (
            <Skeleton className="m-5 h-48" />
          ) : total === 0 ? (
            <EmptyState icon={<Globe2 />} title="The client's country list is not loaded yet">
              Import a CSV or Excel file with a <code>country</code> column (name or ISO3) and a <code>segment</code> column (<i>existing</i> or <i>expansion</i>), plus optional <code>notes</code>.
            </EmptyState>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[13px]">
                  <thead><tr><th className={th}>Country</th><th className={th}>Segment</th><th className={th}>Regions</th><th className={th}>Source</th><th className={th} /></tr></thead>
                  <tbody>
                    {shown.map((m) => (
                      <tr key={m.iso3} className="hover:bg-paper">
                        <td className={td}><span className="font-medium text-ink-900">{m.name}</span> <span className="num text-[11px] text-muted">{m.iso3}</span></td>
                        <td className={td}>
                          <button type="button" disabled={!can('analyst')} onClick={() => setSeg.mutate(m)} title={can('analyst') ? 'Switch segment' : undefined}>
                            <Badge tone={m.segment === 'existing' ? 'teal' : 'blue'}>{m.segment}</Badge>
                          </button>
                        </td>
                        <td className={td}>{m.regions.join(', ') || <span className="text-muted">—</span>}</td>
                        <td className={`${td} text-[12px] text-muted`}>{m.source} · {date(m.updated_at)}</td>
                        <td className={`${td} text-right`}>
                          {can('analyst') && <Button size="sm" variant="ghost" aria-label={`Remove ${m.name}`} onClick={() => remove.mutate(m.iso3)}><Trash2 /></Button>}
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
        {regions.data ? <RegionEditor regions={regions.data} /> : <Skeleton className="h-64" />}
      </div>
    </div>
  )
}
