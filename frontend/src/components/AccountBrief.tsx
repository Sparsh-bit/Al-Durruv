import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, FileDown, Mail, MessageCircle, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ApiError, api, download, downloadOrWarn, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime } from '../lib/format'
import type { BriefVersion, CompanyBrief } from '../lib/types'
import { EvidenceList, StatementList } from './Statements'
import { Button, Card, Notice, Segmented, Spinner } from './ui'

/** AI account brief (English or Arabic): grounded statements, email and WhatsApp drafts, PDF, history. */
export default function AccountBrief({ companyId, hasBrief }: { companyId: number; hasBrief: boolean }) {
  const { can, user } = useAuth()
  const qc = useQueryClient()
  const [language, setLanguage] = useState<'en' | 'ar'>(user?.language ?? 'en')
  const brief = useQuery({
    queryKey: ['company-brief', companyId],
    queryFn: () => api<CompanyBrief>(`/api/companies/${companyId}/brief`),
    enabled: hasBrief,
    retry: false,
  })
  const history = useQuery({
    queryKey: ['company-briefs', companyId],
    queryFn: () => api<BriefVersion[]>(`/api/companies/${companyId}/briefs`),
    enabled: hasBrief,
  })
  const generate = useMutation({
    mutationFn: () => post<CompanyBrief>(`/api/companies/${companyId}/brief`, { language }),
    onSuccess: (b) => {
      qc.setQueryData(['company-brief', companyId], b)
      qc.invalidateQueries({ queryKey: ['company-briefs', companyId] })
      qc.invalidateQueries({ queryKey: ['companies'] })
      qc.invalidateQueries({ queryKey: ['accounts'] })
      toast.success(`Brief ready (cost $${b.cost_usd.toFixed(4)})`)
    },
  })
  const pdf = useMutation({ mutationFn: () => download(`/api/companies/${companyId}/brief/pdf`) })
  const b = generate.data ?? brief.data
  const rtl = b?.language === 'ar'
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
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line-soft bg-paper px-4 py-3">
        <div className="flex items-center gap-2 text-[13.5px] font-semibold text-ink-900">
          <Sparkles className="size-4 text-brand-700" /> Account brief
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {can('analyst') && (
            <>
              <Segmented label="Brief language" value={language} onChange={setLanguage} options={[{ value: 'en', label: 'English' }, { value: 'ar', label: 'العربية' }]} />
              <Button size="sm" loading={generate.isPending} onClick={() => generate.mutate()}>{b ? 'Regenerate' : 'Generate'}</Button>
            </>
          )}
          {b && <Button size="sm" variant="secondary" icon={<FileDown />} loading={pdf.isPending} onClick={() => pdf.mutate()}>PDF</Button>}
        </div>
      </div>
      <div className="p-4">
        {generate.isPending ? (
          <div className="flex items-center gap-3 py-6 text-[13px] text-muted"><Spinner className="size-4" /> Writing the brief from the facts bundle…</div>
        ) : generate.isError ? (
          <Notice tone="error">{generate.error.message}</Notice>
        ) : b ? (
          <div className="space-y-5">
            <p className="micro text-muted">
              {dateTime(b.generated_at)} · ${b.cost_usd.toFixed(4)}
            </p>
            <div dir={rtl ? 'rtl' : 'ltr'} lang={rtl ? 'ar' : 'en'} className={rtl ? 'space-y-5 text-right' : 'space-y-5'}>
              {b.sections.map((s) => (
                <section key={s.title}>
                  <h4 className="mb-2 text-[14px] font-semibold text-ink-900">{s.title}</h4>
                  <StatementList statements={s.statements} evidence={b.evidence} />
                </section>
              ))}
              <section className="rounded-[10px] border border-line bg-paper p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h4 className="flex items-center gap-2 text-[13.5px] font-semibold text-ink-900"><Mail className="size-4" /> {rtl ? 'مسودة البريد الإلكتروني' : 'First-contact email'}</h4>
                  <Button size="sm" variant="ghost" icon={<Copy />} onClick={() => copy(`${b.outreach_email.subject}\n\n${b.outreach_email.body}`)}>Copy</Button>
                </div>
                <div className="text-[13px] font-medium text-ink-800">{b.outreach_email.subject}</div>
                <p className="mt-2 text-[13px] whitespace-pre-line text-body">{b.outreach_email.body}</p>
              </section>
              {b.whatsapp_message && (
                <section className="rounded-[10px] border border-line bg-paper p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <h4 className="flex items-center gap-2 text-[13.5px] font-semibold text-ink-900"><MessageCircle className="size-4" /> WhatsApp</h4>
                    <Button size="sm" variant="ghost" icon={<Copy />} onClick={() => copy(b.whatsapp_message ?? '')}>Copy</Button>
                  </div>
                  <p className="text-[13px] whitespace-pre-line text-body">{b.whatsapp_message}</p>
                </section>
              )}
            </div>
            <p className="text-[11.5px] text-muted">Drafts only. Nothing is sent from the platform; review before use.</p>
            <details className="rounded-[10px] border border-line px-3 py-2">
              <summary className="cursor-pointer text-[12px] font-medium text-body">Facts bundle ({b.evidence.length})</summary>
              <div className="mt-2"><EvidenceList evidence={b.evidence} /></div>
            </details>
            {(history.data?.length ?? 0) > 1 && (
              <details className="rounded-[10px] border border-line px-3 py-2">
                <summary className="cursor-pointer text-[12px] font-medium text-body">Earlier versions ({history.data!.length})</summary>
                <ul className="mt-2 space-y-1 text-[12px] text-muted">
                  {history.data!.map((h) => (
                    <li key={h.id} className="flex items-center justify-between gap-2">
                      <span>{dateTime(h.created_at)} · {h.language.toUpperCase()}</span>
                      <button type="button" className="text-brand-700 hover:underline" onClick={() => downloadOrWarn(`/api/companies/${companyId}/brief/pdf?brief_id=${h.id}`)}>PDF</button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        ) : brief.isError && !(brief.error instanceof ApiError && brief.error.status === 404) ? (
          <Notice tone="error">{brief.error.message}</Notice>
        ) : (
          <p className="text-[13px] leading-relaxed text-body">
            Who they are, what they import and from whom, which of your products fit, a negotiation angle and risks, plus a first email and a WhatsApp message, in English or Arabic. Every number is checked against the facts bundle; a draft with unsupported numbers is rejected.
          </p>
        )}
      </div>
    </Card>
  )
}
