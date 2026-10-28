import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, UserCheck, UserX } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, Field, Input, Modal, Notice, PageHeader, Select, Skeleton, Table, Textarea, td, th } from '../components/ui'
import { api, patch, post, put } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime, num } from '../lib/format'
import type { AppSettings, CompanyProfile, Role, Run, User } from '../lib/types'

type Source = { key: string; name: string; status: string; detail: string; observations?: number; cached_responses?: number; companies?: number; last_run?: Run | null }
const STATUS: Record<string, { tone: 'green' | 'amber' | 'red'; text: string }> = {
  connected: { tone: 'green', text: 'Connected' },
  not_configured: { tone: 'red', text: 'Not configured' },
  not_connected: { tone: 'amber', text: 'Not connected' },
}
const RUN_TONE = { queued: 'slate', running: 'blue', succeeded: 'green', failed: 'red' } as const

function NewUser({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ email: '', full_name: '', password: '', role: 'viewer' as Role })
  const save = useMutation({
    mutationFn: () => post<User>('/api/auth/users', f),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] })
      toast.success('User created')
      onDone()
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Full name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
      <Field label="Email"><Input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
      <Field label="Temporary password" hint="At least 8 characters. Share it securely.">
        <Input type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
      </Field>
      <Field label="Role">
        <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
          <option value="viewer">Viewer: read dashboards and reports</option>
          <option value="analyst">Analyst: load data, research, generate briefs</option>
          <option value="admin">Admin: everything plus users and data sources</option>
        </Select>
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>Create user</Button>
      </div>
    </form>
  )
}

type Usage = {
  month_spend_usd: number
  budget_usd: number
  model: string
  by_feature: { feature: string; calls: number; cost_usd: number; input_tokens: number; output_tokens: number; web_searches: number }[]
  recent: { at: string; feature: string; model: string; input_tokens: number; output_tokens: number; cache_read_tokens: number; web_searches: number; cost_usd: number }[]
}
type AuditEntry = { at: string; user: string; action: string; entity: string; entity_id: string; detail: string }
const FEATURE_LABEL: Record<string, string> = {
  analyst: 'AI analyst questions',
  market_brief: 'Market briefs',
  company_brief: 'Company briefs',
  market_news: 'Market news research',
  research_buyers: 'Buyer research',
  research_competitors: 'Competitor research',
  research_suppliers: 'Supplier research',
}

function SettingsCard() {
  const qc = useQueryClient()
  const current = useQuery({ queryKey: ['app-settings'], queryFn: () => api<AppSettings>('/api/admin/settings') })
  const countries = useQuery({ queryKey: ['countries'], queryFn: () => api<{ iso3: string; name: string }[]>('/api/countries') })
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const s = draft ?? current.data
  const save = useMutation({
    mutationFn: (body: AppSettings) => put<AppSettings>('/api/admin/settings', body),
    onSuccess: (r) => {
      qc.setQueryData(['app-settings'], r)
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['opportunities'] })
      setDraft(null)
      toast.success('Settings saved')
    },
  })
  if (!s) return <Skeleton className="mb-8 h-64" />
  const names = new Map((countries.data ?? []).map((c) => [c.iso3, c.name]))
  const setProfile = (k: keyof CompanyProfile) => (e: { target: { value: string } }) =>
    setDraft({ ...s, company_profile: { ...s.company_profile, [k]: e.target.value } })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate(s)
  }
  return (
    <Card className="mb-8">
      <CardHeader title="Client profile and scoring" subtitle="Used by the AI to judge product fit and by the private-label opportunity engine." />
      <form onSubmit={submit} className="space-y-5 p-5">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Company name"><Input required value={s.company_profile.name} onChange={setProfile('name')} /></Field>
          <Field label="Brand"><Input value={s.company_profile.brand} onChange={setProfile('brand')} /></Field>
          <Field label="Home country (ISO3)" hint={names.get(s.company_profile.country_iso3.toUpperCase()) ?? 'e.g. SYR'}>
            <Input required pattern="[A-Za-z]{3}" maxLength={3} value={s.company_profile.country_iso3} onChange={setProfile('country_iso3')} />
          </Field>
          <div className="sm:col-span-3">
            <Field label="What we make and sell"><Textarea rows={3} maxLength={2000} value={s.company_profile.description} onChange={setProfile('description')} /></Field>
          </div>
          <Field label="Label languages" hint="Comma separated">
            <Input value={s.company_profile.label_languages.join(', ')} onChange={(e) => setDraft({ ...s, company_profile: { ...s.company_profile, label_languages: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) } })} />
          </Field>
          <Field label="Certifications" hint="Comma separated, e.g. Halal, ISO 22000">
            <Input value={s.company_profile.certifications.join(', ')} onChange={(e) => setDraft({ ...s, company_profile: { ...s.company_profile, certifications: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) } })} />
          </Field>
          <Field label="Monthly AI budget (USD)" hint="AI features pause when this is reached">
            <Input type="number" min={0} step="1" value={s.ai_monthly_budget_usd} onChange={(e) => setDraft({ ...s, ai_monthly_budget_usd: Number(e.target.value) })} />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Priority private-label categories" hint="Comma separated. Products are tagged with these in the catalogue.">
            <Input
              value={s.priority_categories.join(', ')}
              onChange={(e) => setDraft({ ...s, priority_categories: e.target.value.split(',').map((x) => x.trimStart()) })}
              onBlur={() => setDraft({ ...s, priority_categories: s.priority_categories.map((x) => x.trim()).filter(Boolean) })}
            />
          </Field>
          <div>
            <div className="mb-1.5 text-[13px] font-medium text-ink-800">Private-label opportunity weights</div>
            <div className="grid grid-cols-5 gap-2">
              {(Object.keys(s.private_label_weights) as (keyof AppSettings['private_label_weights'])[]).map((k) => (
                <label key={k} className="block">
                  <span className="micro mb-1 block truncate text-muted" title={k.replace(/_/g, ' ')}>{k.replace(/_/g, ' ')}</span>
                  <Input type="number" min={0} max={100} value={s.private_label_weights[k]} onChange={(e) => setDraft({ ...s, private_label_weights: { ...s.private_label_weights, [k]: Number(e.target.value) } })} />
                </label>
              ))}
            </div>
          </div>
        </div>
        <p className="text-xs text-muted">Existing and expansion markets and regions are managed on the Markets &amp; regions page.</p>
        <div className="flex justify-end gap-2 border-t border-line pt-4">
          {draft && <Button variant="secondary" onClick={() => setDraft(null)}>Discard</Button>}
          <Button type="submit" disabled={!draft} loading={save.isPending}>Save settings</Button>
        </div>
      </form>
    </Card>
  )
}

function UsageCard() {
  const usage = useQuery({ queryKey: ['ai-usage'], queryFn: () => api<Usage>('/api/admin/ai-usage'), refetchInterval: 30_000 })
  const u = usage.data
  if (!u) return <Skeleton className="mb-8 h-40" />
  const pct = u.budget_usd ? Math.min(100, (u.month_spend_usd / u.budget_usd) * 100) : 100
  return (
    <Card className="mb-8">
      <CardHeader title="AI usage and cost" subtitle={`This month · model ${u.model} · costs estimated from token counts at list prices`} />
      <div className="p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="tabular text-2xl font-semibold text-slate-900">${u.month_spend_usd.toFixed(2)} <span className="text-sm font-normal text-muted">of ${u.budget_usd.toFixed(2)} budget</span></div>
          <span className="text-xs text-muted">{pct.toFixed(0)}% used</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="AI budget used">
          <div className={`h-full rounded-full ${pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-amber-500' : 'bg-brand-600'}`} style={{ width: `${pct}%` }} />
        </div>
        {u.by_feature.length === 0 ? (
          <p className="mt-4 text-sm text-muted">No AI calls this month.</p>
        ) : (
          <Table className="mt-4">
            <thead>
              <tr><th className={th}>Feature</th><th className={`${th} text-right`}>Calls</th><th className={`${th} text-right`}>Tokens in / out</th><th className={`${th} text-right`}>Web searches</th><th className={`${th} text-right`}>Cost</th></tr>
            </thead>
            <tbody>
              {u.by_feature.map((f) => (
                <tr key={f.feature}>
                  <td className={td}>{FEATURE_LABEL[f.feature] ?? f.feature}</td>
                  <td className={`${td} tabular text-right`}>{num(f.calls)}</td>
                  <td className={`${td} tabular text-right`}>{num(f.input_tokens)} / {num(f.output_tokens)}</td>
                  <td className={`${td} tabular text-right`}>{num(f.web_searches)}</td>
                  <td className={`${td} tabular text-right`}>${f.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </Card>
  )
}

function AuditCard() {
  const log = useQuery({ queryKey: ['audit'], queryFn: () => api<AuditEntry[]>('/api/admin/audit?limit=100') })
  return (
    <Card className="mt-8">
      <CardHeader title="Audit trail" subtitle="Last 100 changes to products, companies, settings, users and reports" />
      {!log.data?.length ? (
        <p className="px-5 py-4 text-sm text-muted">{log.isLoading ? 'Loading…' : 'No changes recorded yet.'}</p>
      ) : (
        <Table>
          <thead>
            <tr><th className={th}>When</th><th className={th}>User</th><th className={th}>Action</th><th className={th}>Detail</th></tr>
          </thead>
          <tbody>
            {log.data.map((e, i) => (
              <tr key={i}>
                <td className={`${td} whitespace-nowrap text-muted`}>{dateTime(e.at)}</td>
                <td className={`${td} text-xs`}>{e.user}</td>
                <td className={`${td} whitespace-nowrap`}><Badge>{e.action}</Badge> <span className="text-xs text-muted">{e.entity}{e.entity_id ? ` #${e.entity_id}` : ''}</span></td>
                <td className={`${td} max-w-md text-xs text-muted`}><span className="line-clamp-2" title={e.detail}>{e.detail}</span></td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

export default function Admin() {
  const { user: me } = useAuth()
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api<Source[]>('/api/admin/sources') })
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => api<Run[]>('/api/admin/runs'), refetchInterval: 10_000 })
  const users = useQuery({ queryKey: ['users'], queryFn: () => api<User[]>('/api/auth/users') })
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: number; role?: Role; is_active?: boolean }) => patch<User>(`/api/auth/users/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  return (
    <>
      <PageHeader title="Administration" subtitle="Company profile, AI budget, data sources, refresh history, users and the audit trail." />
      <SettingsCard />
      <UsageCard />
      <h2 className="mb-3 text-sm font-semibold text-slate-900">Data sources</h2>
      <div className="mb-8 grid gap-4 md:grid-cols-2">
        {sources.isLoading && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-32" />)}
        {sources.isError && <Notice tone="error">{sources.error.message}</Notice>}
        {sources.data?.map((s) => (
          <Card key={s.key} className="p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="text-sm font-semibold text-slate-900">{s.name}</div>
              <Badge tone={STATUS[s.status]?.tone ?? 'amber'}>{STATUS[s.status]?.text ?? s.status}</Badge>
            </div>
            <p className="mt-2 text-[13px] text-muted">{s.detail}</p>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-600">
              {s.observations !== undefined && <span><b className="tabular">{num(s.observations)}</b> observations</span>}
              {s.cached_responses !== undefined && <span><b className="tabular">{num(s.cached_responses)}</b> cached responses</span>}
              {s.companies !== undefined && <span><b className="tabular">{num(s.companies)}</b> companies</span>}
              {s.last_run && <span>Last run {dateTime(s.last_run.started_at)}</span>}
            </div>
          </Card>
        ))}
      </div>

      <Card className="mb-8">
        <CardHeader title="Refresh history" subtitle="Trade-data loads and AI research runs" />
        {runs.isLoading ? (
          <div className="p-5"><Skeleton className="h-24" /></div>
        ) : !runs.data?.length ? (
          <p className="px-5 py-4 text-sm text-muted">No runs yet.</p>
        ) : (
          <Table>
            <thead>
              <tr><th className={th}>Source</th><th className={th}>Scope</th><th className={th}>Status</th><th className={`${th} text-right`}>Records</th><th className={th}>Detail</th><th className={th}>Started</th></tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.id}>
                  <td className={`${td} font-mono text-xs`}>{r.adapter}</td>
                  <td className={`${td} whitespace-nowrap`}>{r.scope}</td>
                  <td className={td}><Badge tone={RUN_TONE[r.status]} className="capitalize">{r.status}</Badge></td>
                  <td className={`${td} tabular text-right`}>{num(r.rows)}</td>
                  <td className={`${td} max-w-md text-xs text-muted`}><span className="line-clamp-2" title={r.error || r.message}>{r.error || r.message}</span></td>
                  <td className={`${td} text-muted whitespace-nowrap`}>{dateTime(r.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title="Users" action={<Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setAdding(true)}>Add user</Button>} />
        <Table>
          <thead>
            <tr><th className={th}>User</th><th className={th}>Role</th><th className={th}>Status</th><th className={th}><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id}>
                <td className={td}><div className="font-medium">{u.full_name || '—'}</div><div className="text-xs text-muted">{u.email}</div></td>
                <td className={td}>
                  <Select className="w-36" value={u.role} disabled={u.id === me?.id} onChange={(e) => update.mutate({ id: u.id, role: e.target.value as Role })} aria-label={`Role for ${u.email}`}>
                    <option value="viewer">Viewer</option><option value="analyst">Analyst</option><option value="admin">Admin</option>
                  </Select>
                </td>
                <td className={td}>{u.is_active ? <Badge tone="green">Active</Badge> : <Badge>Disabled</Badge>}</td>
                <td className={`${td} text-right`}>
                  {u.id !== me?.id && (
                    <Button size="sm" variant="ghost" icon={u.is_active ? <UserX className="size-4" /> : <UserCheck className="size-4" />} onClick={() => update.mutate({ id: u.id, is_active: !u.is_active })}>
                      {u.is_active ? 'Disable' : 'Enable'}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <AuditCard />
      <Modal open={adding} onOpenChange={setAdding} title="Add user">
        {adding && <NewUser onDone={() => setAdding(false)} />}
      </Modal>
    </>
  )
}
