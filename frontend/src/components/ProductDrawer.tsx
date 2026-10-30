import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, BadgeCheck, ExternalLink, FileQuestion, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { api, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime, pageImage } from '../lib/format'
import { HS_SOURCE, HS_STATUS } from '../lib/labels'
import type { Clarification, HsStatus, Product } from '../lib/types'
import MaerskCommodities from './MaerskCommodities'
import { HsPicker } from './ProductForm'
import { Badge, Button, Card, Drawer, Field, Select, Textarea } from './ui'

export function HsStatusBadge({ status }: { status: HsStatus }) {
  const m = HS_STATUS[status] ?? HS_STATUS.candidate
  return (
    <Badge tone={m.tone}>
      {status === 'confirmed' && <BadgeCheck className="size-3" />}
      {m.text}
    </Badge>
  )
}

function Row({ label, children, dir }: { label: string; children: React.ReactNode; dir?: 'rtl' }) {
  return (
    <div className="grid grid-cols-[130px_1fr] gap-3 py-2 text-[13.5px]">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-ink-900" dir={dir}>{children || <span className="text-muted">—</span>}</dd>
    </div>
  )
}

function HsReview({ p, onDone }: { p: Product; onDone: () => void }) {
  const qc = useQueryClient()
  const [code, setCode] = useState(p.hs_code ?? '')
  const [status, setStatus] = useState<HsStatus>('confirmed')
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () => post<Product>(`/api/products/${p.id}/hs-review`, { hs_code: code || null, status, note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['product'] })
      qc.invalidateQueries({ queryKey: ['overview-dash'] })
      toast.success('HS review recorded')
      onDone()
    },
  })
  return (
    <form
      className="mt-4 space-y-3 border-t border-line-soft pt-4"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="HS6 used for analysis">
          <HsPicker value={code} onChange={(c) => setCode(c)} />
        </Field>
        <Field label="Decision">
          <Select value={status} onChange={(e) => setStatus(e.target.value as HsStatus)}>
            {(Object.keys(HS_STATUS) as HsStatus[]).map((s) => <option key={s} value={s}>{HS_STATUS[s].text}</option>)}
          </Select>
        </Field>
      </div>
      <Field label="Reason / evidence" hint="e.g. broker's ruling, client confirmation, recipe detail. The client's own code is never changed.">
        <Textarea rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onDone}>Cancel</Button>
        <Button type="submit" size="sm" loading={save.isPending}>Record decision</Button>
      </div>
    </form>
  )
}

export default function ProductDrawer({ product, siblings, onClose, onEdit }: {
  product: Product | null
  siblings: Product[]
  onClose: () => void
  onEdit: (p: Product) => void
}) {
  const { can } = useAuth()
  const [pageIdx, setPageIdx] = useState(0)
  const [reviewing, setReviewing] = useState(false)
  const p = product
  const page = p?.catalogue_pages[Math.min(pageIdx, (p?.catalogue_pages.length ?? 1) - 1)]
  const questions = useQuery({
    queryKey: ['clarifications'],
    queryFn: () => api<Clarification[]>('/api/clarifications'),
    enabled: p !== null,
  })
  const mine = (questions.data ?? []).filter((q) => q.product_id === p?.id)

  return (
    <Drawer
      open={p !== null}
      onOpenChange={(o) => {
        if (!o) {
          onClose()
          setPageIdx(0)
          setReviewing(false)
        }
      }}
      title={p ? p.name : ''}
      subtitle={p ? `${p.brand ? p.brand + ' · ' : ''}${p.sku}${p.pack_size ? ' · ' + p.pack_size : ''}` : undefined}
    >
      {p && (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            {p.hs_code ? (
              <Link to={`/p/${p.id}/markets`} className="inline-flex h-9.5 items-center gap-2 rounded-[9px] bg-ink-900 px-4 text-[13.5px] font-medium text-white hover:bg-ink-700">
                Open market workspace <ArrowRight className="size-4" />
              </Link>
            ) : (
              <Badge tone="slate">Map an HS6 code to open market data</Badge>
            )}
            {can('analyst') && <Button variant="secondary" icon={<Pencil />} onClick={() => onEdit(p)}>Edit product</Button>}
          </div>

          <Card className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="micro text-muted">HS classification</div>
              <HsStatusBadge status={p.hs_status} />
            </div>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <div className="rounded-[10px] border border-line bg-paper p-3">
                <div className="micro text-muted">Client code (as provided)</div>
                <div className="num mt-1.5 text-[19px] text-ink-900">{p.client_hs_code || <span className="text-muted">not provided</span>}</div>
                {p.client_hs_source && <div className="mt-1 text-[11.5px] leading-snug text-muted">{p.client_hs_source}</div>}
              </div>
              <div className="rounded-[10px] border border-line p-3">
                <div className="micro text-muted">HS6 used for analysis</div>
                <div className="num mt-1.5 text-[19px] text-ink-900">{p.hs_code ?? <span className="text-muted">unmapped</span>}</div>
                {p.hs_description && <div className="mt-1 line-clamp-2 text-[11.5px] leading-snug text-muted">{p.hs_description}</div>}
                <div className="mt-1 text-[11px] text-brand-700">{HS_SOURCE[p.hs_source] ?? p.hs_source}</div>
              </div>
            </div>
            {p.hs_check.issues.length > 0 && (
              <ul className="mt-4 space-y-1.5">
                {p.hs_check.issues.map((i) => (
                  <li key={i} className="flex gap-2 text-[13px] text-ink-800">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-600" /> {i}
                  </li>
                ))}
              </ul>
            )}
            {p.hs_note && <p className="mt-3 text-[13px] leading-relaxed text-body">{p.hs_note}</p>}
            {p.hs_reviewed_at && <p className="micro mt-3 text-muted">Reviewed {dateTime(p.hs_reviewed_at)}</p>}
            {p.hs_status !== 'confirmed' && (
              <p className="mt-3 rounded-[8px] bg-fog px-3 py-2 text-xs leading-relaxed text-body">
                Not customs-certain. Verify with the client or a customs broker before using it in declarations.
              </p>
            )}
            {can('admin') &&
              (reviewing ? (
                <HsReview p={p} onDone={() => setReviewing(false)} />
              ) : (
                <div className="mt-4">
                  <Button size="sm" variant="secondary" icon={<BadgeCheck />} onClick={() => setReviewing(true)}>Review classification</Button>
                </div>
              ))}
          </Card>

          <MaerskCommodities p={p} />

          {mine.length > 0 && (
            <Card>
              <div className="flex items-center gap-2 border-b border-line-soft px-4 py-3 text-[13.5px] font-semibold text-ink-900">
                <FileQuestion className="size-4 text-brand-700" /> Open questions
              </div>
              <ul className="divide-y divide-line-soft">
                {mine.map((q) => (
                  <li key={q.id} className="px-4 py-3 text-[13px] leading-relaxed text-ink-800">
                    <Badge tone={q.status === 'open' ? 'amber' : 'green'} className="mr-2">{q.status}</Badge>
                    {q.question}
                    {q.answer && <div className="mt-1 text-body">Answer: {q.answer}</div>}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {p.notes && (
            <div className="flex gap-3 rounded-[10px] border border-amber-200 bg-amber-50/70 px-4 py-3 text-[13px] text-amber-950">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <div><div className="font-medium">Note</div>{p.notes}</div>
            </div>
          )}

          <div className="grid gap-5 sm:grid-cols-[200px_1fr]">
            <div>
              {page ? (
                <a href={pageImage(page)} target="_blank" rel="noopener noreferrer" className="group block overflow-hidden rounded-[10px] border border-line bg-white" title="Open the full catalogue page">
                  <img src={pageImage(page)} alt={`Catalogue page ${page} showing ${p.name}`} className="aspect-[798/1129] w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]" loading="lazy" />
                </a>
              ) : (
                <div className="flex aspect-[798/1129] items-center justify-center rounded-[10px] border border-dashed border-line px-4 text-center text-xs text-muted">Not shown in the catalogue PDF</div>
              )}
              {p.catalogue_pages.length > 1 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.catalogue_pages.map((n, i) => (
                    <button key={n} type="button" onClick={() => setPageIdx(i)} className={`num rounded px-2 py-0.5 text-[11px] ${i === pageIdx ? 'bg-ink-900 text-white' : 'bg-fog text-body hover:bg-line'}`}>
                      p.{n}
                    </button>
                  ))}
                </div>
              )}
              {page && (
                <a href={pageImage(page)} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-brand-700 hover:underline">
                  <ExternalLink className="size-3" /> Full page {page}
                </a>
              )}
            </div>
            <Card className="px-4 py-2">
              <dl className="divide-y divide-line-soft">
                <Row label="Arabic name" dir="rtl">{p.name_ar}</Row>
                <Row label="Collection">{p.category}</Row>
                <Row label="Priority category">{p.priority_category && <Badge tone="teal">{p.priority_category}</Badge>}</Row>
                <Row label="Description">{p.description}</Row>
                <Row label="Pack size">{p.pack_size}</Row>
                <Row label="Net quantity">{p.net_quantity !== null ? `${p.net_quantity} ${p.net_unit}` : 'Not stated'}</Row>
                <Row label="Packaging">{p.packaging}</Row>
                <Row label="Ingredients">{p.ingredients}</Row>
                <Row label="Processing">{p.processing}</Row>
                <Row label="Made in">{p.manufacturing_country}</Row>
                <Row label="Export entity">{p.export_entity}</Row>
              </dl>
            </Card>
          </div>

          {siblings.length > 0 && (
            <Card>
              <div className="border-b border-line-soft px-4 py-3 text-[13.5px] font-semibold text-ink-900">
                Also analysed under HS {p.hs_code} <span className="font-normal text-muted">· they share the same market data</span>
              </div>
              <ul className="divide-y divide-line-soft">
                {siblings.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]">
                    <span className="truncate">{s.name}</span>
                    <span className="shrink-0 text-xs text-muted">{s.pack_size}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </Drawer>
  )
}
