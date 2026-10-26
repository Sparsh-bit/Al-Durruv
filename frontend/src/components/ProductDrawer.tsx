import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, BadgeCheck, ExternalLink, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { put } from '../lib/api'
import { useAuth } from '../lib/auth'
import { pageImage } from '../lib/format'
import type { Product } from '../lib/types'
import { Badge, Button, Card, Drawer } from './ui'

export function HsStatusBadge({ status }: { status: Product['hs_status'] }) {
  return status === 'confirmed' ? (
    <Badge tone="green"><BadgeCheck className="size-3" /> Confirmed</Badge>
  ) : (
    <Badge tone="amber">Suggested</Badge>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[130px_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-slate-900">{children || '—'}</dd>
    </div>
  )
}

export default function ProductDrawer({ product, siblings, onClose, onEdit }: {
  product: Product | null
  siblings: Product[]
  onClose: () => void
  onEdit: (p: Product) => void
}) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [pageIdx, setPageIdx] = useState(0)
  const confirm = useMutation({
    mutationFn: (p: Product) => put<Product>(`/api/products/${p.id}`, { ...p, hs_status: 'confirmed' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['product'] })
      toast.success('HS code marked as confirmed')
    },
  })
  const p = product
  const page = p?.catalogue_pages[Math.min(pageIdx, (p?.catalogue_pages.length ?? 1) - 1)]

  return (
    <Drawer
      open={p !== null}
      onOpenChange={(o) => {
        if (!o) {
          onClose()
          setPageIdx(0)
        }
      }}
      title={p ? p.name : ''}
      subtitle={p ? `${p.brand ? p.brand + ' · ' : ''}${p.sku}${p.pack_size ? ' · ' + p.pack_size : ''}` : undefined}
    >
      {p && (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            <Link to={`/p/${p.id}/markets`} className="inline-flex h-9.5 items-center gap-2 rounded-lg bg-ink-900 px-4 text-sm font-medium text-white hover:bg-ink-800">
              Open market workspace <ArrowRight className="size-4" />
            </Link>
            {can('analyst') && <Button variant="secondary" icon={<Pencil className="size-4" />} onClick={() => onEdit(p)}>Edit</Button>}
          </div>

          {p.notes && (
            <div className="flex gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <div><div className="font-medium">Catalogue note</div>{p.notes}</div>
            </div>
          )}

          <div className="grid gap-5 sm:grid-cols-[200px_1fr]">
            <div>
              {page ? (
                <a href={pageImage(page)} target="_blank" rel="noopener noreferrer" className="group block overflow-hidden rounded-lg border border-line bg-white" title="Open the full catalogue page">
                  <img src={pageImage(page)} alt={`Catalogue page ${page} showing ${p.name}`} className="aspect-[798/1129] w-full object-cover transition-transform group-hover:scale-[1.02]" loading="lazy" />
                </a>
              ) : (
                <div className="flex aspect-[798/1129] items-center justify-center rounded-lg border border-dashed border-line text-xs text-muted">No catalogue page</div>
              )}
              {p.catalogue_pages.length > 1 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.catalogue_pages.map((n, i) => (
                    <button key={n} type="button" onClick={() => setPageIdx(i)} className={`rounded px-2 py-0.5 text-xs ${i === pageIdx ? 'bg-ink-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>
                      p. {n}
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
              <dl className="divide-y divide-line">
                <Row label="Collection">{p.category}</Row>
                <Row label="Description">{p.description}</Row>
                <Row label="Pack size">{p.pack_size}</Row>
                <Row label="Net quantity">{p.net_quantity !== null ? `${p.net_quantity} ${p.net_unit}` : 'Not stated'}</Row>
                <Row label="Packaging">{p.packaging}</Row>
                <Row label="Catalogue page">{p.catalogue_page}</Row>
              </dl>
            </Card>
          </div>

          <Card className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold tracking-wider text-muted uppercase">HS classification</div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-mono text-lg font-semibold text-ink-900">{p.hs_code}</span>
                  <HsStatusBadge status={p.hs_status} />
                </div>
                <p className="mt-1 text-sm text-slate-700">{p.hs_description}</p>
                {p.hs_note && <p className="mt-2 text-xs text-muted">{p.hs_note}</p>}
              </div>
              {can('analyst') && p.hs_status === 'suggested' && (
                <Button size="sm" variant="secondary" icon={<BadgeCheck className="size-3.5" />} loading={confirm.isPending} onClick={() => confirm.mutate(p)}>
                  Mark confirmed
                </Button>
              )}
            </div>
            {p.hs_status === 'suggested' && (
              <p className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
                The catalogue does not state HS codes. This code was assigned from the product description and should be verified by a customs broker before use in declarations.
              </p>
            )}
          </Card>

          {siblings.length > 0 && (
            <Card>
              <div className="border-b border-line px-4 py-3 text-sm font-semibold text-slate-900">
                Also classified under HS {p.hs_code} <span className="font-normal text-muted">· share the same market data</span>
              </div>
              <ul className="divide-y divide-line">
                {siblings.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
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
