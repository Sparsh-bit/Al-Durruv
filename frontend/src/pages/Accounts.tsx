import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, ShieldAlert, Store, Tags } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge, Button, Card, CountryChip, EmptyState, Field, Input, Notice, PageHeader, Segmented, Select, Skeleton, SourceLink, Textarea } from '../components/ui'
import { api, download, patch, put } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date } from '../lib/format'
import { IDENTITY, PL_META, STAGES } from '../lib/labels'
import { useReveal } from '../lib/motion'
import type { Company, CompetitorTracker, Identity, Requirement, RetailerPath, Stage, User } from '../lib/types'
import AccountBrief from '../components/AccountBrief'
import { num } from '../lib/format'

type Kind = 'retailer' | 'competitor'

const REQ_STATUS: Record<Requirement['status'], { text: string; tone: 'slate' | 'amber' | 'green' }> = {
  todo: { text: 'To do', tone: 'slate' },
  in_progress: { text: 'In progress', tone: 'amber' },
  met: { text: 'Met', tone: 'green' },
  not_applicable: { text: 'N/A', tone: 'slate' },
}

function RetailerPathPanel({ id }: { id: number }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const path = useQuery({ queryKey: ['retailer-path', id], queryFn: () => api<RetailerPath>(`/api/retailers/${id}/path`) })
  const setStatus = useMutation({
    mutationFn: ({ rid, status }: { rid: number; status: Requirement['status'] }) => patch(`/api/requirements/${rid}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['retailer-path', id] }),
  })
  const d = path.data
  if (!d) return <Skeleton className="m-5 h-32" />
  return (
    <div className="grid gap-5 p-5 lg:grid-cols-2">
      <div>
        <div className="micro mb-2 text-muted">Direct imports (shipment records)</div>
        {d.direct_importer ? (
          <>
            <p className="text-[13px] text-ink-900">{d.direct_shipments} shipments on record as consignee, {d.direct_client_hs_shipments} under your HS codes.</p>
            <ul className="mt-2 space-y-1 text-[12.5px]">
              {d.suppliers.slice(0, 6).map((s) => (
                <li key={s.shipper} className="flex justify-between gap-3"><span className="truncate">{s.shipper} <CountryChip iso3={s.origin_iso3} /></span><span className="num text-muted">{num(Math.round(s.weight_kg))} kg</span></li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-[13px] text-body">Not found as a direct importer in the uploaded shipment files.</p>
        )}
        <div className="micro mt-4 mb-2 text-muted">Likely route in: importers of your categories in its markets</div>
        {d.route_in.length === 0 ? (
          <p className="text-[13px] text-muted">None found yet in the shipment files for {d.company.markets.join(', ') || 'its markets'}.</p>
        ) : (
          <ul className="space-y-1 text-[12.5px]">
            {d.route_in.slice(0, 6).map((b) => (
              <li key={b.company.id} className="flex justify-between gap-3"><span className="truncate">{b.company.name}</span><span className="num text-muted">fit {b.score?.toFixed(0) ?? '—'}</span></li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <div className="micro mb-2 text-muted">Supplier requirements (sourced, admin-maintained)</div>
        {d.requirements.length === 0 ? <p className="text-[13px] text-muted">None recorded.</p> : (
          <ul className="space-y-2.5">
            {d.requirements.map((r) => (
              <li key={r.id} className="rounded-[9px] border border-line-soft p-2.5 text-[12.5px]">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-ink-900">{r.title}{r.market_iso3 && <span className="ml-1 text-muted">({r.market_iso3})</span>}</span>
                  {can('analyst') ? (
                    <Select className="h-7.5! w-auto! py-0 text-[12px]" value={r.status} onChange={(e) => setStatus.mutate({ rid: r.id, status: e.target.value as Requirement['status'] })} aria-label={`Status of ${r.title}`}>
                      {Object.entries(REQ_STATUS).map(([k, v]) => <option key={k} value={k}>{v.text}</option>)}
                    </Select>
                  ) : <Badge tone={REQ_STATUS[r.status].tone}>{REQ_STATUS[r.status].text}</Badge>}
                </div>
                {r.detail && <p className="mt-1 text-body">{r.detail}</p>}
                <div className="mt-1 flex items-center gap-2 text-[11px] text-muted"><SourceLink source={{ url: r.source_url }} compact />{r.verified_at && <span>verified {date(r.verified_at)}</span>}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function CompetitorPanel({ id }: { id: number }) {
  const t = useQuery({ queryKey: ['competitor', id], queryFn: () => api<CompetitorTracker>(`/api/competitors/${id}/tracker`) })
  const d = t.data
  if (!d) return <Skeleton className="m-5 h-32" />
  if (d.shipments === 0) {
    return <p className="p-5 text-[13px] text-body">No shipments by this company or its aliases in the uploaded files yet. Upload provider files that cover its exports to track its buyers.</p>
  }
  return (
    <div className="grid gap-5 p-5 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <div className="micro mb-2 text-muted">Its buyers ({d.buyers.length}) · not yet yours: {d.not_our_buyers.length}</div>
        <ul className="space-y-1 text-[12.5px]">
          {d.buyers.slice(0, 10).map((b) => (
            <li key={b.id} className="flex justify-between gap-3">
              <span className="truncate">{b.name} {!b.ours && <Badge tone="teal">prospect</Badge>}</span>
              <span className="num text-muted">{b.shipments} · {num(Math.round(b.weight_kg))} kg · last {date(b.last)}</span>
            </li>
          ))}
        </ul>
        {!d.client_shippers_configured && <p className="mt-2 text-[11.5px] text-amber-800">Client shipper names are not configured, so every buyer counts as "not yet yours".</p>}
      </div>
      <div>
        <div className="micro mb-2 text-muted">Volume by quarter (kg)</div>
        <ul className="space-y-0.5 text-[12px]">{Object.entries(d.by_quarter).slice(-8).map(([q, v]) => <li key={q} className="flex justify-between"><span>{q}</span><span className="num">{num(Math.round(v))}</span></li>)}</ul>
        <div className="micro mt-3 mb-2 text-muted">Markets</div>
        <div className="flex flex-wrap gap-1">{Object.keys(d.by_market).slice(0, 8).map((m) => <CountryChip key={m} iso3={m} />)}</div>
      </div>
    </div>
  )
}

function Aliases({ c }: { c: Company }) {
  const qc = useQueryClient()
  const [v, setV] = useState(c.aliases.join(', '))
  const save = useMutation({
    mutationFn: () => put(`/api/companies/${c.id}/aliases`, { aliases: v.split(',').map((x) => x.trim()).filter(Boolean) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['accounts'] }); toast.success('Aliases saved') },
  })
  return (
    <form className="flex flex-wrap items-end gap-2 border-t border-line-soft px-5 py-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      <Field label="Aliases used to match shipment records (exact names, comma separated)">
        <Input className="w-[min(560px,80vw)]" value={v} onChange={(e) => setV(e.target.value)} />
      </Field>
      <Button type="submit" size="sm" variant="secondary" loading={save.isPending}>Save aliases</Button>
    </form>
  )
}

function AccountExtras({ c }: { c: Company }) {
  const { can } = useAuth()
  const [open, setOpen] = useState(false)
  return (
    <div className="border-t border-line">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-5 py-3 text-left text-[13px] font-medium text-ink-900 hover:bg-paper" aria-expanded={open}>
        <span className="flex items-center gap-2"><Tags className="size-4 text-brand-700" />{c.relationship_type === 'retailer' ? 'Path to retailer, requirements and account brief' : 'Competitor tracker and account brief'}</span>
        <span className="text-muted">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <>
          {c.relationship_type === 'retailer' ? <RetailerPathPanel id={c.id} /> : <CompetitorPanel id={c.id} />}
          {can('admin') && <Aliases c={c} />}
          <div className="border-t border-line-soft p-5"><AccountBrief companyId={c.id} hasBrief={c.has_brief} /></div>
        </>
      )}
    </div>
  )
}

function AccountCard({ c, users }: { c: Company; users: User[] | undefined }) {
  const { can, user } = useAuth()
  const qc = useQueryClient()
  const [f, setF] = useState({
    pipeline_stage: c.pipeline_stage,
    identity_status: c.identity_status,
    owner_id: c.owner_id,
    next_action: c.next_action,
    follow_up_on: c.follow_up_on ?? '',
    notes: c.notes,
    vendor_url: c.vendor_url,
  })
  const dirty =
    f.pipeline_stage !== c.pipeline_stage ||
    f.identity_status !== c.identity_status ||
    f.owner_id !== c.owner_id ||
    f.next_action !== c.next_action ||
    (f.follow_up_on || null) !== c.follow_up_on ||
    f.notes !== c.notes ||
    f.vendor_url !== c.vendor_url
  const save = useMutation({
    mutationFn: () => patch<Company>(`/api/companies/${c.id}`, { ...f, follow_up_on: f.follow_up_on || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['accounts'] })
      qc.invalidateQueries({ queryKey: ['overview-dash'] })
      toast.success(`${c.name} updated`)
    },
  })
  const ownerName = (id: number | null) => (id === null ? 'Unassigned' : id === user?.id ? 'You' : users?.find((u) => u.id === id)?.full_name || users?.find((u) => u.id === id)?.email || `User #${id}`)
  const editable = can('analyst')
  const id = IDENTITY[c.identity_status]

  return (
    <Card className="overflow-hidden" >
      <div className="grid lg:grid-cols-[1.25fr_1fr]">
        <div className="border-b border-line-soft p-5 lg:border-r lg:border-b-0">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-[19px] font-semibold text-ink-900">{c.name}</h3>
              {c.aliases.length > 0 && <div className="mt-0.5 text-[12px] text-muted">Also known as: {c.aliases.join(' · ')}</div>}
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
                <CountryChip iso3={c.country_iso3} />
                {c.website ? (
                  <a href={c.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-brand-700 hover:underline">
                    {c.website.replace(/^https?:\/\//, '')} <ExternalLink className="size-3" />
                  </a>
                ) : (
                  <span>No official website confirmed</span>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge tone={id.tone}>{id.text}</Badge>
              <Badge tone={PL_META[c.private_label].tone}>{PL_META[c.private_label].text}</Badge>
            </div>
          </div>
          {c.summary && <p className="mt-3 text-[13.5px] leading-relaxed text-body">{c.summary}</p>}
          {c.identity_status !== 'confirmed' && (
            <div className="mt-3 flex gap-2 rounded-[9px] bg-amber-50/80 px-3 py-2 text-[12.5px] text-amber-950">
              <ShieldAlert className="mt-0.5 size-4 shrink-0" />
              Named by the client; not yet matched to a legal entity. Facts about similarly named companies are not attached.
            </div>
          )}

          <div className="mt-5">
            <div className="micro mb-2 text-muted">Vendor onboarding</div>
            {c.vendor_url ? (
              <a href={c.vendor_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-[13px] font-medium text-brand-700 hover:underline">
                Official supplier registration page <ExternalLink className="size-3.5" />
              </a>
            ) : (
              <span className="text-[13px] text-muted">No official onboarding route found yet.</span>
            )}
          </div>

          <div className="mt-5">
            <div className="micro mb-2 text-muted">Sourced facts ({c.evidence.length})</div>
            {c.evidence.length === 0 ? (
              <p className="text-[13px] text-muted">None yet. Only facts with an official or cited source are recorded here.</p>
            ) : (
              <ol className="space-y-2.5">
                {c.evidence.map((e, i) => (
                  <li key={e.id} className="grid grid-cols-[22px_1fr] gap-2 text-[13px] leading-relaxed">
                    <span className="num pt-px text-[11px] text-brand-700">{String(i + 1).padStart(2, '0')}</span>
                    <div>
                      <div className="text-ink-900">{e.claim}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted">
                        <SourceLink source={e.source} compact /> <span>retrieved {date(e.source.retrieved_at)}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div className="mt-5">
            <div className="micro mb-2 text-muted">Verified contacts</div>
            {Object.keys(c.contact).length ? (
              <ul className="text-[13px]">{Object.entries(c.contact).map(([k, v]) => <li key={k}><span className="text-muted">{k}:</span> {v}</li>)}</ul>
            ) : (
              <p className="text-[13px] text-muted">None recorded. Contacts are added only once verified from the company's own sources.</p>
            )}
          </div>
        </div>

        <form
          className="space-y-3.5 bg-paper p-5"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <div className="micro text-muted">Outreach</div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Status">
              <Select value={f.pipeline_stage} disabled={!editable} onChange={(e) => setF({ ...f, pipeline_stage: e.target.value as Stage })}>
                {STAGES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </Select>
            </Field>
            <Field label="Identity">
              <Select value={f.identity_status} disabled={!editable} onChange={(e) => setF({ ...f, identity_status: e.target.value as Identity })}>
                {(Object.keys(IDENTITY) as Identity[]).map((k) => <option key={k} value={k}>{IDENTITY[k].text}</option>)}
              </Select>
            </Field>
            <Field label="Owner">
              {users ? (
                <Select value={f.owner_id ?? ''} disabled={!editable} onChange={(e) => setF({ ...f, owner_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">Unassigned</option>
                  {users.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.full_name || u.email}</option>)}
                </Select>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-[13px] text-ink-800">{ownerName(f.owner_id)}</span>
                  {editable && f.owner_id !== user?.id && (
                    <Button size="sm" variant="ghost" onClick={() => setF({ ...f, owner_id: user?.id ?? null })}>Assign to me</Button>
                  )}
                </div>
              )}
            </Field>
            <Field label="Follow-up date">
              <Input type="date" value={f.follow_up_on} disabled={!editable} onChange={(e) => setF({ ...f, follow_up_on: e.target.value })} />
            </Field>
          </div>
          <Field label="Next action">
            <Input value={f.next_action} maxLength={2000} disabled={!editable} onChange={(e) => setF({ ...f, next_action: e.target.value })} placeholder="e.g. Register as prospect vendor in Supplier Hub" />
          </Field>
          <Field label="Vendor onboarding URL" hint="Official page only.">
            <Input type="url" value={f.vendor_url} disabled={!editable} onChange={(e) => setF({ ...f, vendor_url: e.target.value })} />
          </Field>
          <Field label="Notes">
            <Textarea rows={3} maxLength={8000} value={f.notes} disabled={!editable} onChange={(e) => setF({ ...f, notes: e.target.value })} />
          </Field>
          {editable && (
            <div className="flex justify-end">
              <Button type="submit" size="sm" disabled={!dirty} loading={save.isPending}>Save account</Button>
            </div>
          )}
        </form>
      </div>
      <AccountExtras c={c} />
    </Card>
  )
}

export default function Accounts() {
  const { can } = useAuth()
  const [kind, setKind] = useState<Kind>('retailer')
  const list = useQuery({ queryKey: ['accounts', kind], queryFn: () => api<Company[]>(`/api/companies?relationship=${kind}`) })
  const users = useQuery({ queryKey: ['users'], queryFn: () => api<User[]>('/api/auth/users'), enabled: can('admin') })
  const ref = useReveal<HTMLDivElement>([list.dataUpdatedAt])

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Accounts"
        title="Retailers & competitors"
        subtitle="Priority retail accounts and named competitors. Every fact links to an official or cited source with its retrieval date. The platform records outreach only when your team does."
        actions={<Button variant="secondary" onClick={() => download(`/api/companies/export?relationship=${kind}`)}>Export CSV</Button>}
      />
      <div className="mb-5">
        <Segmented label="Account type" value={kind} onChange={setKind} options={[{ value: 'retailer', label: 'Retail accounts' }, { value: 'competitor', label: 'Competitors' }]} />
      </div>
      {list.isLoading ? (
        <div className="space-y-4">{[0, 1].map((i) => <Skeleton key={i} className="h-72" />)}</div>
      ) : list.isError ? (
        <Notice tone="error">{list.error.message}</Notice>
      ) : (list.data ?? []).length === 0 ? (
        <Card><EmptyState icon={<Store />} title={kind === 'retailer' ? 'No retail accounts yet' : 'No competitors yet'}>Accounts come from the client setup or from research in a product workspace.</EmptyState></Card>
      ) : (
        <div className="space-y-5">
          {list.data!.map((c) => (
            <div key={c.id} data-reveal>
              <AccountCard key={`${c.id}-${c.pipeline_stage}-${c.identity_status}-${c.follow_up_on}-${c.owner_id}`} c={c} users={users.data} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
