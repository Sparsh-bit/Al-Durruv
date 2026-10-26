import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, UserCheck, UserX } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, Field, Input, Modal, Notice, PageHeader, Select, Skeleton, Table, td, th } from '../components/ui'
import { api, patch, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime, num } from '../lib/format'
import type { Role, Run, User } from '../lib/types'

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
      <Field label="Temporary password" hint="At least 10 characters. Share it securely.">
        <Input type="password" required minLength={10} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
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
      <PageHeader title="Administration" subtitle="Data sources, refresh history and user access." />
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
      <Modal open={adding} onOpenChange={setAdding} title="Add user">
        {adding && <NewUser onDone={() => setAdding(false)} />}
      </Modal>
    </>
  )
}
