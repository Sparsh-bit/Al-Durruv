import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, ExternalLink, Mail, MapPin, Phone, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ApiError, api, patch, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { date, dateTime } from '../lib/format'
import { PL_META, RELATIONSHIP_LABEL, STAGES } from '../lib/labels'
import type { Company, CompanyBrief, Relationship, Stage } from '../lib/types'
import { EvidenceList, StatementList } from './Statements'
import { Badge, Button, Card, CountryChip, Drawer, Notice, Select, SourceLink, Spinner, Textarea } from './ui'

export function ScoreBreakdown({ c }: { c: Company }) {
  if (c.prospect_score === null) return null
  return (
    <div className="space-y-1.5">
      {Object.entries(c.score_components).map(([k, v]) => (
        <div key={k} className="grid grid-cols-[1fr_60px_36px] items-center gap-2 text-xs">
          <span className="text-slate-600">{v.label}</span>
          <div className="h-1.5 rounded-full bg-slate-100">
            {v.normalized !== null && <div className="h-1.5 rounded-full bg-brand-600" style={{ width: `${v.normalized * 100}%` }} />}
          </div>
          <span className="tabular text-right text-muted">{v.status === 'ok' ? `×${v.weight}` : 'n/a'}</span>
        </div>
      ))}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <div className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">{title}</div>
      {children}
    </Card>
  )
}

function BriefPanel({ company }: { company: Company }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const brief = useQuery({
    queryKey: ['company-brief', company.id],
    queryFn: () => api<CompanyBrief>(`/api/companies/${company.id}/brief`),
    enabled: company.has_brief,
    retry: false,
  })
  const generate = useMutation({
    mutationFn: () => post<CompanyBrief>(`/api/companies/${company.id}/brief`),
    onSuccess: (b) => {
      qc.setQueryData(['company-brief', company.id], b)
      qc.invalidateQueries({ queryKey: ['companies'] })
      toast.success(`Brief ready (cost $${b.cost_usd.toFixed(4)})`)
    },
  })
  const b = generate.data ?? brief.data
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success('Copied to clipboard')
    } catch {
      toast.error('Copy failed: select the text and copy it manually.')
    }
  }
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r from-ink-900 to-ink-800 px-4 py-3 text-white">
        <div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-brand-200" /> AI company brief</div>
        {can('analyst') && (
          <Button size="sm" variant="secondary" loading={generate.isPending} onClick={() => generate.mutate()}>
            {b ? 'Regenerate' : 'Generate brief'}
          </Button>
        )}
      </div>
      <div className="p-4">
        {generate.isPending ? (
          <div className="flex items-center gap-3 py-6 text-sm text-muted"><Spinner className="size-4" /> Writing the brief from the evidence…</div>
        ) : b ? (
          <div className="space-y-5">
            <p className="text-xs text-muted">Generated {dateTime(b.generated_at)} · {b.model} · ${b.cost_usd.toFixed(4)}</p>
            {b.sections.map((s) => (
              <section key={s.title}>
                <h4 className="mb-2 text-sm font-semibold text-ink-900">{s.title}</h4>
                <StatementList statements={s.statements} evidence={b.evidence} />
              </section>
            ))}
            <section className="rounded-lg border border-line bg-slate-50/70 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h4 className="flex items-center gap-2 text-sm font-semibold text-ink-900"><Mail className="size-4" /> Draft first-contact email</h4>
                <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />} onClick={() => copy(`Subject: ${b.outreach_email.subject}\n\n${b.outreach_email.body}`)}>
                  Copy
                </Button>
              </div>
              {b.outreach_email.warnings.map((w) => <div key={w} className="mb-2"><Notice tone="warn">{w}</Notice></div>)}
              <div className="text-sm font-medium text-slate-800">Subject: {b.outreach_email.subject}</div>
              <p className="mt-2 text-sm whitespace-pre-line text-slate-700">{b.outreach_email.body}</p>
              <p className="mt-2 text-[11px] text-muted">Draft only. Nothing is sent from the platform; review before use.</p>
            </section>
            <details className="rounded-lg border border-line px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">Evidence used ({b.evidence.length})</summary>
              <div className="mt-2"><EvidenceList evidence={b.evidence} /></div>
            </details>
          </div>
        ) : brief.isError && !(brief.error instanceof ApiError && brief.error.status === 404) ? (
          <Notice tone="error">{brief.error.message}</Notice>
        ) : (
          <p className="text-sm text-muted">
            A pre-meeting brief: company overview, fit with your products and private-label offer, what is known and unknown about purchasing, market context, negotiation approach and a draft first email. Each statement is labelled and cited.
          </p>
        )}
      </div>
    </Card>
  )
}

export default function CompanyDrawer({ company, onClose }: { company: Company | null; onClose: () => void }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [notes, setNotes] = useState<string | null>(null)
  const update = useMutation({
    mutationFn: (body: Partial<Pick<Company, 'pipeline_stage' | 'notes' | 'relationship_type' | 'review_status'>>) =>
      patch<Company>(`/api/companies/${company!.id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['companies'] })
      setNotes(null)
    },
  })
  const c = company
  return (
    <Drawer
      open={c !== null}
      onOpenChange={(o) => {
        if (!o) {
          onClose()
          setNotes(null)
        }
      }}
      title={c ? <span className="flex items-center gap-2"><CountryChip iso3={c.country_iso3} /> {c.name}</span> : ''}
      subtitle={c ? `${RELATIONSHIP_LABEL[c.relationship_type]} · ${c.country_name}${c.roles.length ? ' · ' + c.roles.map((r) => r.replace('_', ' ')).join(', ') : ''}` : undefined}
    >
      {c && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={c.review_status === 'verified' ? 'green' : c.review_status === 'rejected' ? 'red' : 'amber'} className="capitalize">{c.review_status}</Badge>
            {c.relationship_type === 'buyer' && <Badge tone={PL_META[c.private_label].tone}>{PL_META[c.private_label].text}</Badge>}
            {c.website && <SourceLink source={{ url: c.website.startsWith('http') ? c.website : `https://${c.website}` }} compact />}
          </div>

          {can('analyst') && (
            <div className="grid gap-3 sm:grid-cols-2">
              {c.relationship_type === 'buyer' && (
                <label className="block text-xs text-muted">
                  Pipeline stage
                  <Select className="mt-1" value={c.pipeline_stage} onChange={(e) => update.mutate({ pipeline_stage: e.target.value as Stage })}>
                    {STAGES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </Select>
                </label>
              )}
              <label className="block text-xs text-muted">
                Classified as
                <Select className="mt-1" value={c.relationship_type} onChange={(e) => update.mutate({ relationship_type: e.target.value as Relationship })}>
                  <option value="buyer">Potential buyer</option>
                  <option value="competitor">Competitor</option>
                  <option value="supplier">Supplier</option>
                </Select>
              </label>
            </div>
          )}

          {c.prospect_score !== null && (
            <Section title={`Prospect fit score · ${c.prospect_score.toFixed(1)} / 100`}>
              <ScoreBreakdown c={c} />
              <p className="mt-2 text-[11px] text-muted">Computed from market data, business type, private-label evidence, sourced buying signals and verification. Not an estimate of purchase volume.</p>
            </Section>
          )}

          <Section title="Profile">
            <dl className="space-y-2 text-sm">
              {c.summary && <div><dt className="text-xs text-muted">Summary</dt><dd>{c.summary}</dd></div>}
              {c.product_range && <div><dt className="text-xs text-muted">Product range</dt><dd>{c.product_range}</dd></div>}
              {c.product_fit && <div><dt className="text-xs text-muted">Fit with our products</dt><dd>{c.product_fit}</dd></div>}
              {c.private_label_evidence && <div><dt className="text-xs text-muted">Private-label evidence</dt><dd>{c.private_label_evidence}</dd></div>}
              {c.markets_served.length > 0 && (
                <div><dt className="text-xs text-muted">Markets served</dt><dd className="mt-1 flex flex-wrap gap-1">{c.markets_served.map((m) => <CountryChip key={m} iso3={m} />)}</dd></div>
              )}
              <div>
                <dt className="text-xs text-muted">Purchase volumes and order frequency</dt>
                <dd className="text-slate-600">Unknown: needs shipment records or your sales history.</dd>
              </div>
            </dl>
          </Section>

          {c.buying_signals.length > 0 && (
            <Section title="Buying signals">
              <ul className="space-y-2">
                {c.buying_signals.map((s) => (
                  <li key={s.url + s.text} className="text-sm">
                    {s.text}
                    <div className="mt-0.5"><SourceLink source={{ url: s.url }} compact /></div>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="Public business contact">
            {Object.keys(c.contact).length === 0 ? (
              <p className="text-sm text-muted">None published on the sources found.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {c.contact.email && <li className="flex items-center gap-2"><Mail className="size-3.5 text-muted" /> <a className="text-brand-700 hover:underline" href={`mailto:${c.contact.email}`}>{c.contact.email}</a></li>}
                {c.contact.phone && <li className="flex items-center gap-2"><Phone className="size-3.5 text-muted" /> {c.contact.phone}</li>}
                {c.contact.address && <li className="flex items-center gap-2"><MapPin className="size-3.5 text-muted" /> {c.contact.address}</li>}
                {c.contact.contact_url && (
                  <li><a className="inline-flex items-center gap-1 text-brand-700 hover:underline" href={c.contact.contact_url} target="_blank" rel="noopener noreferrer"><ExternalLink className="size-3.5" /> Contact page</a></li>
                )}
              </ul>
            )}
          </Section>

          <BriefPanel key={c.id} company={c} />

          <Section title="Evidence">
            <div className="space-y-2">
              {c.evidence.map((e) => (
                <div key={e.id} className="rounded-lg border border-line bg-slate-50/70 p-3">
                  {e.excerpt && <blockquote className="text-[12.5px] text-slate-700 italic">“{e.excerpt}”</blockquote>}
                  <div className="mt-1.5 text-[11.5px] text-muted">{e.claim}</div>
                  <div className="mt-1.5 flex items-center justify-between gap-2">
                    <SourceLink source={e.source} compact />
                    <span className="shrink-0 text-[11px] text-muted">Retrieved {date(e.source.retrieved_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Notes">
            {can('analyst') ? (
              <>
                <Textarea rows={4} maxLength={8000} value={notes ?? c.notes} onChange={(e) => setNotes(e.target.value)} placeholder="Call notes, contacts met at fairs, next steps…" aria-label="Notes" />
                {notes !== null && notes !== c.notes && (
                  <div className="mt-2 flex justify-end">
                    <Button size="sm" loading={update.isPending} onClick={() => update.mutate({ notes })}>Save notes</Button>
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm whitespace-pre-line text-slate-700">{c.notes || 'No notes.'}</p>
            )}
          </Section>
        </div>
      )}
    </Drawer>
  )
}
