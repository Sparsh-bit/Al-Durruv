import * as Menu from '@radix-ui/react-dropdown-menu'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Building2, Check, ListPlus, Plus, Search, ShieldCheck, Sparkles, X } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, CountryChip, EmptyState, Field, Input, Modal, Notice, Select, Skeleton, SourceLink } from '../components/ui'
import { WorkspaceHeader } from '../components/Workspace'
import { api, patch, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date } from '../lib/format'
import { isActive, useOverview, useProduct, useRun } from '../lib/hooks'
import type { Company, RankedMarket, Run } from '../lib/types'

type ProspectList = { id: number; name: string; hs_code: string | null; companies: Company[] }
const STATUS_TONE = { candidate: 'amber', verified: 'green', rejected: 'red' } as const
const ROLE_LABEL = (r: string) => r.replace('_', ' ')

function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: () => api<{ ai_enabled: boolean; model: string }>('/api/health'), staleTime: 300_000 })
}

function ResearchPanel({ hs, productId, markets, onFinished }: { hs: string; productId: number; markets: RankedMarket[]; onFinished: () => void }) {
  const [params] = useSearchParams()
  const health = useHealth()
  const [country, setCountry] = useState(() => params.get('country') ?? '')
  const [kind, setKind] = useState<'buyers' | 'competitors'>('buyers')
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
        <div className="flex items-center gap-2 text-[15px] font-semibold"><Sparkles className="size-4 text-brand-200" /> AI company research</div>
        <p className="mt-0.5 text-[13px] text-slate-300">
          Searches the public web and keeps only companies backed by a retrieved source page. Results start as <i>candidates</i> for your review.
        </p>
      </div>
      <div className="grid items-end gap-4 p-5 md:grid-cols-[1fr_1fr_auto]">
        <Field label="Target market">
          <Select value={chosen} onChange={(e) => setCountry(e.target.value)} disabled={running}>
            {markets.map((m) => (
              <option key={m.m49} value={m.m49}>
                #{m.rank} {m.name} — score {m.score.toFixed(0)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Looking for">
          <Select value={kind} onChange={(e) => setKind(e.target.value as 'buyers' | 'competitors')} disabled={running}>
            <option value="buyers">Buyers: importers, distributors, retailers, brand owners</option>
            <option value="competitors">Competitors: manufacturers and exporters</option>
          </Select>
        </Field>
        <Button icon={<Search className="size-4" />} loading={running || start.isPending} disabled={!chosen} onClick={() => start.mutate(false)}>
          {running ? 'Researching…' : 'Run research'}
        </Button>
      </div>
      {running && (
        <div className="border-t border-line bg-brand-50/50 px-5 py-3 text-sm text-brand-700">{run?.message} — this usually takes 30–90 seconds.</div>
      )}
      {cached && (
        <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3 text-sm text-muted">
          Showing results from a research run on {date(run.started_at)} (cached to avoid repeat search costs).
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
        <Button size="sm" variant="ghost" icon={<ListPlus className="size-3.5" />}>Add to list</Button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="end" sideOffset={4} className="z-50 min-w-48 rounded-xl border border-line bg-white p-1 shadow-pop">
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

function CompanyCard({ c, lists }: { c: Company; lists: ProspectList[] }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const review = useMutation({
    mutationFn: (status: Company['review_status']) => patch<Company>(`/api/companies/${c.id}`, { review_status: status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }),
  })
  return (
    <Card className={clsx('flex flex-col', c.review_status === 'rejected' && 'opacity-60')}>
      <div className="flex items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <h3 className="truncate text-[15px] font-semibold text-slate-900" title={c.name}>{c.name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <CountryChip iso3={c.country_iso3} /> {c.country_name}
            {c.website && (
              <>
                <span className="text-slate-300">·</span>
                <SourceLink source={{ url: c.website.startsWith('http') ? c.website : `https://${c.website}` }} compact />
              </>
            )}
          </div>
        </div>
        <Badge tone={STATUS_TONE[c.review_status]} className="capitalize">{c.review_status}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5 px-5">
        {c.roles.map((r) => <Badge key={r} tone="teal" className="capitalize">{ROLE_LABEL(r)}</Badge>)}
      </div>
      {c.summary && <p className="mt-3 px-5 text-[13px] leading-relaxed text-slate-600">{c.summary}</p>}
      <div className="mt-3 space-y-2 px-5 pb-4">
        {c.evidence.slice(0, 2).map((e) => (
          <div key={e.id} className="rounded-lg border border-line bg-slate-50/70 p-3">
            {e.excerpt && <blockquote className="line-clamp-3 text-[12.5px] text-slate-700 italic">“{e.excerpt}”</blockquote>}
            <div className="mt-1.5 text-[11.5px] text-muted">{e.claim}</div>
            <div className="mt-1.5 flex items-center justify-between gap-2">
              <SourceLink source={e.source} compact />
              <span className="shrink-0 text-[11px] text-muted">Retrieved {date(e.source.retrieved_at)}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-line px-3 py-2">
        <AddToList company={c} lists={lists} />
        {can('analyst') && (
          <div className="flex gap-1">
            {c.review_status !== 'verified' && (
              <Button size="sm" variant="ghost" className="text-emerald-700" icon={<Check className="size-3.5" />} loading={review.isPending && review.variables === 'verified'} onClick={() => review.mutate('verified')}>
                Verify
              </Button>
            )}
            {c.review_status !== 'rejected' && (
              <Button size="sm" variant="ghost" className="text-red-700" icon={<X className="size-3.5" />} loading={review.isPending && review.variables === 'rejected'} onClick={() => review.mutate('rejected')}>
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
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <Card>
      <CardHeader
        title="Prospect lists"
        action={can('analyst') && <Button size="sm" variant="secondary" icon={<Plus className="size-3.5" />} onClick={() => setOpen(true)}>New</Button>}
      />
      {lists.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted">Group verified companies into lists for outreach.</p>
      ) : (
        <ul className="divide-y divide-line">
          {lists.map((l) => (
            <li key={l.id} className="px-5 py-3">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-slate-800">{l.name}</span>
                <Badge>{l.companies.length}</Badge>
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
  const product = useProduct()
  const hs = product.data?.hs_code
  const overview = useOverview(hs)
  const hasData = overview.data?.has_data
  const ranking = useQuery({
    queryKey: ['ranking', hs, 'default'],
    queryFn: () => post<{ markets: RankedMarket[] }>(`/api/markets/${hs}/ranking`, {}),
    enabled: Boolean(hasData),
  })
  const companies = useQuery({ queryKey: ['companies', hs], queryFn: () => api<Company[]>(`/api/companies?hs=${hs}`), enabled: Boolean(hs) })
  const lists = useQuery({ queryKey: ['prospect-lists'], queryFn: () => api<ProspectList[]>('/api/prospect-lists') })
  const [status, setStatus] = useState('')
  const [role, setRole] = useState('')
  const [country, setCountry] = useState('')

  const rows = useMemo(
    () =>
      (companies.data ?? []).filter(
        (c) => (!status || c.review_status === status) && (!role || c.roles.includes(role)) && (!country || c.country_iso3 === country),
      ),
    [companies.data, status, role, country],
  )
  const countries = [...new Map((companies.data ?? []).map((c) => [c.country_iso3, c.country_name])).entries()]
  const roles = [...new Set((companies.data ?? []).flatMap((c) => c.roles))]
  const counts = (s: Company['review_status']) => (companies.data ?? []).filter((c) => c.review_status === s).length

  return (
    <>
      <WorkspaceHeader
        product={product.data}
        hasData={hasData}
        title="Companies"
        subtitle="Prospective buyers and competitors, each linked to the public source that supports it. Country statistics never imply a company's purchases."
      />
      {!hasData && overview.data ? (
        <Notice tone="warn" title="Load trade data first">Company research targets markets from the opportunity ranking. Load trade statistics on the Market intelligence step.</Notice>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
          <div className="min-w-0 space-y-6">
            {hs && product.data && ranking.data && (
              <ResearchPanel hs={hs} productId={product.data.id} markets={ranking.data.markets.slice(0, 30)} onFinished={() => qc.invalidateQueries({ queryKey: ['companies', hs] })} />
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Select className="w-auto!" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
                <option value="">All statuses ({companies.data?.length ?? 0})</option>
                <option value="candidate">Candidates ({counts('candidate')})</option>
                <option value="verified">Verified ({counts('verified')})</option>
                <option value="rejected">Rejected ({counts('rejected')})</option>
              </Select>
              <Select className="w-auto!" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Filter by role">
                <option value="">All roles</option>
                {roles.map((r) => <option key={r} value={r} className="capitalize">{ROLE_LABEL(r)}</option>)}
              </Select>
              <Select className="w-auto!" value={country} onChange={(e) => setCountry(e.target.value)} aria-label="Filter by country">
                <option value="">All countries</option>
                {countries.map(([iso, name]) => <option key={iso} value={iso}>{name}</option>)}
              </Select>
            </div>
            {companies.isLoading ? (
              <div className="grid gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-56" />)}</div>
            ) : companies.isError ? (
              <Notice tone="error">{companies.error.message}</Notice>
            ) : rows.length === 0 ? (
              <Card>
                <EmptyState icon={<Building2 className="size-6" />} title={companies.data?.length ? 'No companies match these filters' : 'No companies researched yet'}>
                  {companies.data?.length ? 'Clear a filter to see more.' : 'Choose a target market above and run AI research to discover importers, distributors and retailers.'}
                </EmptyState>
              </Card>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {rows.map((c) => <CompanyCard key={c.id} c={c} lists={lists.data ?? []} />)}
              </div>
            )}
          </div>
          <div className="space-y-6">
            {hs && <ListsPanel hs={hs} lists={lists.data ?? []} />}
            <Card className="p-5 text-[13px] leading-relaxed text-slate-600">
              <div className="mb-2 flex items-center gap-2 font-semibold text-slate-900"><ShieldCheck className="size-4 text-brand-700" /> How companies are qualified</div>
              <ol className="list-decimal space-y-1.5 pl-4">
                <li>AI searches public pages for the target market and role.</li>
                <li>Any company without a retrieved source URL is discarded.</li>
                <li>The source page is re-fetched to check the company name appears.</li>
                <li>An analyst verifies or rejects each candidate before outreach.</li>
              </ol>
              <p className="mt-3 text-xs text-muted">Purchase volumes, budgets and shipments require a licensed shipment-data provider (not connected).</p>
            </Card>
          </div>
        </div>
      )}
    </>
  )
}
