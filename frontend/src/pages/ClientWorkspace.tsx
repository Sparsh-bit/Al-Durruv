import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleHelp, Factory, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, CountryChip, EmptyState, Field, Input, Modal, Notice, PageHeader, Segmented, Select, Skeleton, Textarea, td, th } from '../components/ui'
import { api, patch, post, put } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date } from '../lib/format'
import { useReveal } from '../lib/motion'
import type { Clarification, Entity } from '../lib/types'

const TOPICS: Record<Clarification['topic'], string> = {
  hs: 'HS classification',
  product: 'Product',
  entity: 'Entity',
  market: 'Market',
  competitor: 'Competitor',
  account: 'Retail account',
  general: 'General',
}
const ENTITY_STATUS = {
  pending_verification: { tone: 'amber', text: 'Pending verification' },
  verified: { tone: 'green', text: 'Verified' },
  rejected: { tone: 'red', text: 'Rejected' },
} as const

function QuestionRow({ q }: { q: Clarification }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [answer, setAnswer] = useState(q.answer)
  const [open, setOpen] = useState(false)
  const save = useMutation({
    mutationFn: (status?: Clarification['status']) => patch<Clarification>(`/api/clarifications/${q.id}`, { answer, ...(status ? { status } : {}) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clarifications'] })
      qc.invalidateQueries({ queryKey: ['overview-dash'] })
      toast.success('Saved')
      setOpen(false)
    },
  })
  return (
    <li className="px-5 py-4" data-reveal>
      <div className="flex flex-wrap items-start gap-3">
        <span className="num w-9 shrink-0 pt-0.5 text-[11.5px] text-brand-700">Q{String(q.id).padStart(2, '0')}</span>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <Badge>{TOPICS[q.topic]}</Badge>
            <Badge tone={q.status === 'open' ? 'amber' : q.status === 'answered' ? 'green' : 'slate'}>{q.status}</Badge>
            {q.product && <span className="text-[12px] text-muted">· {q.product}</span>}
          </div>
          <p className="text-[13.5px] leading-relaxed text-ink-900">{q.question}</p>
          {q.context && <p className="mt-1 text-[12px] text-muted">{q.context}</p>}
          {q.answer && !open && (
            <div className="mt-2 flex gap-2 rounded-[9px] bg-emerald-50/70 px-3 py-2 text-[13px] text-emerald-950">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
              <div>{q.answer}{q.answered_at && <span className="ml-2 text-[11.5px] text-emerald-800/70">{date(q.answered_at)}</span>}</div>
            </div>
          )}
          {open && (
            <div className="mt-3 space-y-2">
              <Textarea rows={3} value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Your answer, as given" aria-label="Answer" />
              <div className="flex flex-wrap justify-end gap-2">
                <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
                <Button size="sm" variant="secondary" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save draft</Button>
                <Button size="sm" loading={save.isPending} disabled={!answer.trim()} onClick={() => save.mutate('answered')}>Mark answered</Button>
              </div>
            </div>
          )}
        </div>
        {can('analyst') && !open && (
          <div className="flex gap-1.5">
            <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>{q.answer ? 'Edit answer' : 'Record answer'}</Button>
            {q.status !== 'closed' && <Button size="sm" variant="ghost" onClick={() => save.mutate('closed')}>Close</Button>}
          </div>
        )}
      </div>
    </li>
  )
}

function EntityForm({ initial, onDone }: { initial?: Entity; onDone: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({
    name: initial?.name ?? '',
    country_iso3: initial?.country_iso3 ?? '',
    role: initial?.role ?? 'manufacturer',
    status: initial?.status ?? 'pending_verification',
    notes: initial?.notes ?? '',
    source_note: initial?.source_note ?? '',
  })
  const save = useMutation({
    mutationFn: () => (initial ? put(`/api/entities/${initial.id}`, f) : post('/api/entities', f)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['entities'] })
      toast.success('Entity saved')
      onDone()
    },
  })
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Legal name"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Country (ISO3)"><Input maxLength={3} pattern="[A-Za-z]{3}" value={f.country_iso3} onChange={(e) => setF({ ...f, country_iso3: e.target.value.toUpperCase() })} className="font-mono" /></Field>
        <Field label="Role">
          <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Entity['role'] })}>
            <option value="manufacturer">Manufacturer</option><option value="exporter">Export entity</option><option value="both">Both</option>
          </Select>
        </Field>
        <Field label="Verification">
          <Select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as Entity['status'] })}>
            <option value="pending_verification">Pending verification</option><option value="verified">Verified</option><option value="rejected">Rejected</option>
          </Select>
        </Field>
      </div>
      <Field label="Notes"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      <Field label="Verification source" hint="e.g. commercial registry extract, client document reference"><Input value={f.source_note} onChange={(e) => setF({ ...f, source_note: e.target.value })} /></Field>
      <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onDone}>Cancel</Button><Button type="submit" loading={save.isPending}>Save entity</Button></div>
    </form>
  )
}

export default function ClientWorkspace() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const qs = useQuery({ queryKey: ['clarifications'], queryFn: () => api<Clarification[]>('/api/clarifications') })
  const entities = useQuery({ queryKey: ['entities'], queryFn: () => api<Entity[]>('/api/entities') })
  const [status, setStatus] = useState<'open' | 'answered' | 'all'>('open')
  const [topic, setTopic] = useState('')
  const [editing, setEditing] = useState<Entity | 'new' | null>(null)
  const [asking, setAsking] = useState(false)
  const [newQ, setNewQ] = useState({ topic: 'general' as Clarification['topic'], question: '' })
  const ref = useReveal<HTMLDivElement>([qs.isSuccess, status, topic])
  const add = useMutation({
    mutationFn: () => post('/api/clarifications', newQ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clarifications'] })
      setAsking(false)
      setNewQ({ topic: 'general', question: '' })
      toast.success('Question added')
    },
  })
  const rows = useMemo(
    () => (qs.data ?? []).filter((q) => (status === 'all' || q.status === status) && (!topic || q.topic === topic)),
    [qs.data, status, topic],
  )
  const openCount = (qs.data ?? []).filter((q) => q.status === 'open').length

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Client workspace"
        title="Questions & entities"
        subtitle="Open points to settle together, plus your manufacturing and export entities. Answers are recorded as given. The platform does not assume them."
        actions={can('analyst') && <Button icon={<Plus />} onClick={() => setAsking(true)}>Add question</Button>}
      />
      <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader title={`Clarification checklist · ${openCount} open`} />
          <div className="flex flex-wrap items-center gap-3 border-b border-line-soft px-5 py-3">
            <Segmented label="Status" value={status} onChange={setStatus} options={[{ value: 'open', label: 'Open' }, { value: 'answered', label: 'Answered' }, { value: 'all', label: 'All' }]} />
            <Select className="w-auto!" value={topic} onChange={(e) => setTopic(e.target.value)} aria-label="Topic">
              <option value="">All topics</option>
              {Object.entries(TOPICS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </div>
          {qs.isLoading ? (
            <Skeleton className="m-5 h-60" />
          ) : qs.isError ? (
            <div className="p-5"><Notice tone="error">{qs.error.message}</Notice></div>
          ) : rows.length === 0 ? (
            <EmptyState icon={<CircleHelp />} title="Nothing here">No questions match these filters.</EmptyState>
          ) : (
            <ul className="divide-y divide-line-soft">{rows.map((q) => <QuestionRow key={q.id} q={q} />)}</ul>
          )}
        </Card>

        <Card className="h-fit">
          <CardHeader title="Manufacturing & export entities" action={can('analyst') && <Button size="sm" variant="secondary" icon={<Plus />} onClick={() => setEditing('new')}>Add</Button>} />
          {entities.isLoading ? (
            <Skeleton className="m-5 h-32" />
          ) : (entities.data ?? []).length === 0 ? (
            <EmptyState icon={<Factory />} title="No entities recorded" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead><tr><th className={th}>Entity</th><th className={th}>Role</th><th className={th}>Status</th></tr></thead>
                <tbody>
                  {entities.data!.map((e) => (
                    <tr key={e.id} className={can('analyst') ? 'cursor-pointer hover:bg-paper' : ''} onClick={() => can('analyst') && setEditing(e)}>
                      <td className={td}>
                        <div className="flex items-center gap-2 font-medium text-ink-900"><CountryChip iso3={e.country_iso3} /> {e.name}</div>
                        {e.notes && <div className="mt-1 line-clamp-2 text-[12px] text-muted">{e.notes}</div>}
                        <div className="mt-1 text-[11.5px] text-muted">{e.products} products linked</div>
                      </td>
                      <td className={`${td} capitalize`}>{e.role}</td>
                      <td className={td}><Badge tone={ENTITY_STATUS[e.status].tone}>{ENTITY_STATUS[e.status].text}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Modal open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} title={editing === 'new' ? 'Add entity' : 'Edit entity'}>
        {editing !== null && <EntityForm key={editing === 'new' ? 'new' : editing.id} initial={editing === 'new' ? undefined : editing} onDone={() => setEditing(null)} />}
      </Modal>
      <Modal open={asking} onOpenChange={setAsking} title="Add a question for the client">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
          <Field label="Topic">
            <Select value={newQ.topic} onChange={(e) => setNewQ({ ...newQ, topic: e.target.value as Clarification['topic'] })}>
              {Object.entries(TOPICS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Question"><Textarea rows={3} required minLength={5} value={newQ.question} onChange={(e) => setNewQ({ ...newQ, question: e.target.value })} /></Field>
          <div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setAsking(false)}>Cancel</Button><Button type="submit" loading={add.isPending}>Add</Button></div>
        </form>
      </Modal>
    </div>
  )
}
