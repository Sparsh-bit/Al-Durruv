import * as Menu from '@radix-ui/react-dropdown-menu'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Building2, Check, Download, ListPlus, Plus, Search, ShieldCheck, Sparkles, X } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import CompanyDrawer from '../components/CompanyDrawer'
import { Badge, Button, Card, CardHeader, CountryChip, EmptyState, Field, Input, Modal, Notice, Select, Skeleton } from '../components/ui'
import { WorkspaceHeader } from '../components/Workspace'
import { api, download, patch, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { isActive, useOverview, useProduct, useRun } from '../lib/hooks'
import { PL_META, STAGES } from '../lib/labels'
import type { Company, RankedMarket, Relationship, Run } from '../lib/types'

type ProspectList = { id: number; name: string; hs_code: string | null; companies: Company[] }
type Kind = 'buyers' | 'competitors' | 'suppliers'
const TABS: { key: Relationship; kind: Kind; label: string; help: string }[] = [
  { key: 'buyer', kind: 'buyers', label: 'Potential buyers', help: 'Importers, distributors, wholesalers, retailers and brand owners that could buy from you or use your private-label service.' },
  { key: 'competitor', kind: 'competitors', label: 'Competitors', help: 'Brands whose products compete with yours on the shelves of the target market.' },
  { key: 'supplier', kind: 'suppliers', label: 'Supplier landscape', help: 'Manufacturers and exporters supplying this product to the market, whatever their origin.' },
]
const STATUS_TONE = { candidate: 'amber', verified: 'green', rejected: 'red' } as const
const role = (r: string) => r.replace('_', ' ')

function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: () => api<{ ai_enabled: boolean; model: string }>('/api/health'), staleTime: 300_000 })
}

function ResearchPanel({ hs, productId, kind, label, markets, onFinished }: {
  hs: string
  productId: number
  kind: Kind
  label: string
  markets: RankedMarket[]
  onFinished: () => void
}) {
  const [params] = useSearchParams()
  const health = useHealth()
  const [country, setCountry] = useState(() => params.get('country') ?? '')
  const [runId, setRunId] = useState<number | null>(null)
  const chosen = country || (markets[0] ? String(markets[0].m49) : '')
  const start = useMutation({
    mutationFn: (force: boolean) => post<Run>('/api/research', { hs_code: hs, country_m49: Number(chosen), kind, product_id: productId, force }),
    onSuccess: (r) => setRunId(r.id),
  })
  const run = useRun(runId, (r) => {
    onFinished()
    if (r.status === 'succeeded') toast.success(r.message)
    else toast.error(r.error || 'Research failed')
  })
  const running = isActive(run)
  const cached = start.data?.status === 'succeeded' && run?.id === start.data.id

  if (health.data && !health.data.ai_enabled)
    return (
      <Notice tone="warn" title="AI research is not configured">
        Add <code>ANTHROPIC_API_KEY</code> to the backend <code>.env</code> file and restart the API to enable company discovery.
      </Notice>
    )

  return (
    <Card className="overflow-hidden">
      <div className="bg-gradient-to-r from-ink-900 to-ink-800 px-5 py-4 text-white">
        <div className="flex items-center gap-2 text-[15px] font-semibold"><Sparkles className="size-4 text-brand-200" /> Research {label.toLowerCase()}</div>
        <p className="mt-0.5 text-[13px] text-slate-300">
          Searches the public web and keeps only companies backed by a retrieved source page. Results start as <i>candidates</i> for your review. Each run costs a few cents and is cached for 7 days.
        </p>
      </div>
      <div className="grid items-end gap-4 p-5 md:grid-cols-[1fr_auto]">
        <Field label="Target market">
          <Select value={chosen} onChange={(e) => setCountry(e.target.value)} disabled={running}>
            {markets.map((m) => (
              <option key={m.m49} value={m.m49}>
                #{m.rank} {m.name} · score {m.score.toFixed(0)}{m.existing_market ? ' · existing market' : ''}
              </option>
            ))}
          </Select>
        </Field>
        <Button icon={<Search className="size-4" />} loading={running || start.isPending} disabled={!chosen} onClick={() => start.mutate(false)}>
          {running ? 'Researching…' : 'Run research'}
        </Button>
      </div>
      {running && <div className="border-t border-line bg-brand-50/50 px-5 py-3 text-sm text-brand-700">{run?.message} · usually 30-90 seconds.</div>}
      {cached && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-sm text-muted">
          Showing results from an earlier run (cached to avoid paying for the same searches twice).
          <Button size="sm" variant="secondary" onClick={() => start.mutate(true)}>Search again</Button>
        </div>
      )}
    </Card>
  )
}

function AddToList({ company, lists }: { company: Company; lists: ProspectList[] }) {
  const qc = useQueryClient()
  const add = useMutation({
    mutationFn: (listId: number) => post(`/api/prospect-lists/${listId}/companies/${company.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['prospect-lists'] })
      toast.success(`${company.name} added to list`)
    },
  })
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <Button size="sm" variant="ghost" icon={<ListPlus className="size-3.5" />}>List</Button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="start" sideOffset={4} className="z-50 min-w-48 rounded-xl border border-line bg-white p-1 shadow-pop">
          {lists.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted">Create a prospect list first.</div>
          ) : (
            lists.map((l) => (
              <Menu.Item key={l.id} onSelect={() => add.mutate(l.id)} className="cursor-pointer rounded-lg px-3 py-2 text-sm text-slate-700 outline-none data-highlighted:bg-slate-100">
                {l.name}
              </Menu.Item>
            ))
          )}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}

function CompanyCard({ c, lists, onOpen }: { c: Company; lists: ProspectList[]; onOpen: () => void }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const review = useMutation({
    mutationFn: (status: Company['review_status']) => patch<Company>(`/api/companies/${c.id}`, { review_status: status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }),
  })
  const buyer = c.relationship_type === 'buyer'
  return (
    <Card className={clsx('flex flex-col', c.review_status === 'rejected' && 'opacity-60')}>
      <button type="button" onClick={onOpen} className="flex-1 text-left">
        <div className="flex items-start justify-between gap-3 px-5 pt-4">
          <div className="min-w-0">
            <h3 className="truncate text-[15px] font-semibold text-slate-900 hover:text-brand-700" title={c.name}>{c.name}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
              <CountryChip iso3={c.country_iso3} /> {c.country_name}
            </div>
          </div>
          {buyer && c.prospect_score !== null ? (
            <div className="shrink-0 text-right">
              <div className="tabular text-xl font-semibold text-ink-900">{c.prospect_score.toFixed(0)}</div>
              <div className="text-[10.5px] tracking-wide text-muted uppercase">fit score</div>
            </div>
          ) : (
            <Badge tone={STATUS_TONE[c.review_status]} className="capitalize">{c.review_status}</Badge>
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5 px-5">
          {buyer && <Badge tone={STATUS_TONE[c.review_status]} className="capitalize">{c.review_status}</Badge>}
          {c.roles.map((r) => <Badge key={r} tone="teal" className="capitalize">{role(r)}</Badge>)}
          {buyer && <Badge tone={PL_META[c.private_label].tone}>{PL_META[c.private_label].text}</Badge>}
          {buyer && c.pipeline_stage !== 'identified' && <Badge tone="blue">{STAGES.find((s) => s.key === c.pipeline_stage)?.label}</Badge>}
        </div>
        {(c.product_fit || c.summary) && <p className="mt-3 line-clamp-3 px-5 text-[13px] leading-relaxed text-slate-600">{c.product_fit || c.summary}</p>}
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 px-5 pb-4 text-xs text-muted">
          <span>{c.evidence.length} source{c.evidence.length === 1 ? '' : 's'}</span>
          {c.buying_signals.length > 0 && <span>{c.buying_signals.length} buying signal{c.buying_signals.length === 1 ? '' : 's'}</span>}
          {Object.keys(c.contact).length > 0 && <span>Public contact on file</span>}
          {c.has_brief && <span className="text-brand-700">Brief ready</span>}
        </div>
      </button>
      <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-2">
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={onOpen}>Profile</Button>
          {buyer && <AddToList company={c} lists={lists} />}
        </div>
        {can('analyst') && (
          <div className="flex gap-1">
            {c.review_status !== 'verified' && (
              <Button size="sm" variant="ghost" className="text-emerald-700" aria-label={`Verify ${c.name}`} icon={<Check className="size-3.5" />} loading={review.isPending && review.variables === 'verified'} onClick={() => review.mutate('verified')}>
                Verify
              </Button>
            )}
            {c.review_status !== 'rejected' && (
              <Button size="sm" variant="ghost" className="text-red-700" aria-label={`Reject ${c.name}`} icon={<X className="size-3.5" />} loading={review.isPending && review.variables === 'rejected'} onClick={() => review.mutate('rejected')}>
                Reject
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

function ListsPanel({ hs, lists }: { hs: string; lists: ProspectList[] }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: () => post('/api/prospect-lists', { name, hs_code: hs }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['prospect-lists'] })
      setOpen(false)
      setName('')
      toast.success('Prospect list created')
    },
  })
  const exp = useMutation({ mutationFn: (id: number) => download(`/api/prospect-lists/${id}/export`) })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <Card>
      <CardHeader title="Prospect lists" action={can('analyst') && <Button size="sm" variant="secondary" icon={<Plus className="size-3.5" />} onClick={() => setOpen(true)}>New</Button>} />
      {lists.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted">Group verified buyers into lists for outreach.</p>
      ) : (
        <ul className="divide-y divide-line">
          {lists.map((l) => (
            <li key={l.id} className="px-5 py-3">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="font-medium text-slate-800">{l.name}</span>
                <span className="flex items-center gap-1">
                  <Badge>{l.companies.length}</Badge>
                  <Button size="sm" variant="ghost" aria-label={`Export ${l.name}`} disabled={!l.companies.length} loading={exp.isPending && exp.variables === l.id} onClick={() => exp.mutate(l.id)}>
                    <Download className="size-3.5" />
                  </Button>
                </span>
              </div>
              {l.companies.length > 0 && <div className="mt-1 line-clamp-2 text-xs text-muted">{l.companies.map((c) => c.name).join(', ')}</div>}
            </li>
          ))}
        </ul>
      )}
      <Modal open={open} onOpenChange={setOpen} title="New prospect list">
        <form onSubmit={submit} className="space-y-4">
          <Field label="List name">
            <Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. UK distributors Q1" autoFocus />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" loading={create.isPending}>Create list</Button>
          </div>
        </form>
      </Modal>
    </Card>
  )
}

export default function Companies() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const product = useProduct()
  const hs = product.data?.hs_code
  const overview = useOverview(hs)
  const hasData = overview.data?.has_data
  const tab = TABS.find((t) => t.key === params.get('tab')) ?? TABS[0]
  const ranking = useQuery({
    queryKey: ['ranking', hs, 'default'],
    queryFn: () => post<{ markets: RankedMarket[] }>(`/api/markets/${hs}/ranking`, {}),
    enabled: Boolean(hasData),
  })
  const companies = useQuery({ queryKey: ['companies', hs], queryFn: () => api<Company[]>(`/api/companies?hs=${hs}`), enabled: Boolean(hs) })
  const lists = useQuery({ queryKey: ['prospect-lists'], queryFn: () => api<ProspectList[]>('/api/prospect-lists') })
  const exp = useMutation({ mutationFn: () => download(`/api/companies/export?hs=${hs}&relationship=${tab.key}`) })
  const [status, setStatus] = useState('')
  const [country, setCountry] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)

  const all = useMemo(() => companies.data ?? [], [companies.data])
  const inTab = all.filter((c) => c.relationship_type === tab.key)
  const rows = inTab.filter((c) => (!status || c.review_status === status) && (!country || c.country_iso3 === country))
  const countries = [...new Map(inTab.map((c) => [c.country_iso3, c.country_name])).entries()]
  const counts = (s: Company['review_status']) => inTab.filter((c) => c.review_status === s).length
  const open = all.find((c) => c.id === openId) ?? null
  const setTab = (key: Relationship) => {
    const next = new URLSearchParams(params)
    next.set('tab', key)
    setParams(next, { replace: true })
    setStatus('')
    setCountry('')
  }

  return (
    <>
      <WorkspaceHeader
        product={product.data}
        hasData={hasData}
        title="Companies"
        subtitle="Buyers, competitors and suppliers are kept separate: a competitor is not a prospect, and an exporter is not necessarily a manufacturer. Every company links to the public source that supports it."
      />
      {!hasData && overview.data ? (
        <Notice tone="warn" title="Load trade data first">Company research targets markets from the opportunity ranking. Load trade statistics on the Market intelligence step.</Notice>
      ) : (
        <>
          <div className="mb-5 flex flex-wrap gap-1 rounded-xl border border-line bg-white p-1 shadow-card" role="tablist">
            {TABS.map((t) => {
              const n = all.filter((c) => c.relationship_type === t.key && c.review_status !== 'rejected').length
              return (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={tab.key === t.key}
                  onClick={() => setTab(t.key)}
                  className={clsx('flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-[13px] font-medium whitespace-nowrap', tab.key === t.key ? 'bg-ink-900 text-white' : 'text-slate-600 hover:bg-slate-50')}
                >
                  {t.label} <span className={clsx('rounded-full px-1.5 text-[11px]', tab.key === t.key ? 'bg-white/15' : 'bg-slate-100')}>{n}</span>
                </button>
              )
            })}
          </div>
          <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
            <div className="min-w-0 space-y-6">
              <p className="text-sm text-muted">{tab.help}</p>
              {hs && product.data && ranking.data && (
                <ResearchPanel key={tab.kind} hs={hs} productId={product.data.id} kind={tab.kind} label={tab.label} markets={ranking.data.markets.slice(0, 30)} onFinished={() => qc.invalidateQueries({ queryKey: ['companies', hs] })} />
              )}
              <div className="flex flex-wrap items-center gap-3">
                <Select className="w-auto!" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
                  <option value="">All statuses ({inTab.length})</option>
                  <option value="candidate">Candidates ({counts('candidate')})</option>
                  <option value="verified">Verified ({counts('verified')})</option>
                  <option value="rejected">Rejected ({counts('rejected')})</option>
                </Select>
                <Select className="w-auto!" value={country} onChange={(e) => setCountry(e.target.value)} aria-label="Filter by country">
                  <option value="">All countries</option>
                  {countries.map(([iso, name]) => <option key={iso} value={iso}>{name}</option>)}
                </Select>
                <Button className="ml-auto" size="sm" variant="secondary" icon={<Download className="size-3.5" />} disabled={!inTab.length} loading={exp.isPending} onClick={() => exp.mutate()}>
                  Export CSV
                </Button>
              </div>
              {companies.isLoading ? (
                <div className="grid gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-56" />)}</div>
              ) : companies.isError ? (
                <Notice tone="error">{companies.error.message}</Notice>
              ) : rows.length === 0 ? (
                <Card>
                  <EmptyState icon={<Building2 className="size-6" />} title={inTab.length ? 'No companies match these filters' : `No ${tab.label.toLowerCase()} researched yet`}>
                    {inTab.length ? 'Clear a filter to see more.' : 'Choose a target market above and run research.'}
                  </EmptyState>
                </Card>
              ) : (
                <div className="grid gap-4 md:grid-cols-2">
                  {rows.map((c) => <CompanyCard key={c.id} c={c} lists={lists.data ?? []} onOpen={() => setOpenId(c.id)} />)}
                </div>
              )}
            </div>
            <div className="space-y-6">
              {hs && <ListsPanel hs={hs} lists={lists.data ?? []} />}
              <Card className="p-5 text-[13px] leading-relaxed text-slate-600">
                <div className="mb-2 flex items-center gap-2 font-semibold text-slate-900"><ShieldCheck className="size-4 text-brand-700" /> How companies are qualified</div>
                <ol className="list-decimal space-y-1.5 pl-4">
                  <li>AI searches public pages for the target market and role.</li>
                  <li>Companies and buying signals without a retrieved source URL are discarded.</li>
                  <li>Only generic business contacts on the company's own domain are kept.</li>
                  <li>The source page is re-fetched to check the company name appears.</li>
                  <li>An analyst verifies or rejects each candidate before outreach.</li>
                </ol>
                <p className="mt-3 text-xs text-muted">Purchase volumes, budgets and shipments require a licensed shipment-data provider (not connected) or your own sales records.</p>
              </Card>
            </div>
          </div>
        </>
      )}
      <CompanyDrawer company={open} onClose={() => setOpenId(null)} />
    </>
  )
}
