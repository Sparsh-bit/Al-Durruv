import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowRight, Boxes, Database, Download, Eye, FileUp, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import ProductDrawer, { HsStatusBadge } from '../components/ProductDrawer'
import ProductForm from '../components/ProductForm'
import { Badge, Button, Card, EmptyState, Input, Modal, Notice, PageHeader, Select, Skeleton, Spinner } from '../components/ui'
import { api, del, download, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { pageImage } from '../lib/format'
import type { DataStatus, Product } from '../lib/types'

type ImportResult = { created: number; updated: number; errors: { line: number; error: string }[] }

function ImportDialog({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return api<ImportResult>('/api/products/import', { method: 'POST', body: fd })
    },
    onSuccess: (r) => {
      setResult(r)
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['data-status'] })
      toast.success(`Imported ${r.created} new, ${r.updated} updated`)
    },
  })
  const template = () => {
    const csv =
      'sku,name,brand,category,hs_code,pack_size,net_quantity,net_unit,packaging,catalogue_page,description\n' +
      'DUR-JAM-001,Apricot Fruit Spread,Durra,Fruit Jams & Spreads,200799,430 g,430,g,Glass jar,2,Apricot fruit spread\n'
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob([csv], { type: 'text/csv' })), download: 'product-template.csv' })
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  }
  return (
    <div className="space-y-4">
      <Notice>
        Upload a <b>.csv</b> or <b>.xlsx</b> file. Required columns: <code>sku</code>, <code>name</code>, <code>hs_code</code>. Optional: <code>brand</code>,{' '}
        <code>category</code>, <code>pack_size</code>, <code>net_quantity</code>, <code>net_unit</code>, <code>packaging</code>, <code>catalogue_page</code>,{' '}
        <code>description</code>, <code>hs_status</code>, <code>hs_note</code>, <code>notes</code>. Existing SKUs are updated.
      </Notice>
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={upload.isPending}
        className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-line px-6 py-10 text-sm text-muted hover:border-brand-500 hover:bg-brand-50/40 disabled:opacity-60"
      >
        {upload.isPending ? <Spinner /> : <FileUp className="size-6 text-brand-600" />}
        {upload.isPending ? 'Importing…' : 'Choose a file to upload (max 5 MB)'}
      </button>
      <input
        ref={input}
        type="file"
        accept=".csv,.xlsx,.xls"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) upload.mutate(f)
          e.target.value = ''
        }}
      />
      {result && result.errors.length > 0 && (
        <Notice tone="warn" title={`${result.errors.length} row(s) skipped`}>
          <ul className="mt-1 max-h-40 list-disc overflow-y-auto pl-4">
            {result.errors.map((e) => (
              <li key={e.line}>Line {e.line}: {e.error}</li>
            ))}
          </ul>
        </Notice>
      )}
      <div className="flex justify-between gap-2">
        <Button variant="ghost" icon={<Download className="size-4" />} onClick={template}>Download template</Button>
        <Button variant="secondary" onClick={onDone}>Close</Button>
      </div>
    </div>
  )
}

function CoveragePanel() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const status = useQuery({
    queryKey: ['data-status'],
    queryFn: () => api<DataStatus>('/api/markets/status'),
    refetchInterval: (q) => ((q.state.data?.active.length ?? 0) > 0 ? 5000 : false),
  })
  const start = useMutation({
    mutationFn: () => post<{ queued: number; already_active: number }>('/api/markets/refresh-missing'),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['data-status'] })
      toast.success(r.queued ? `Queued trade data for ${r.queued} HS codes` : 'All HS codes are already loading')
    },
  })
  const d = status.data
  const activeCount = d?.active.length ?? 0
  const wasActive = useRef(false)
  useEffect(() => {
    // refresh product badges once a batch of trade-data loads finishes
    if (wasActive.current && activeCount === 0) qc.invalidateQueries({ queryKey: ['products'] })
    wasActive.current = activeCount > 0
  }, [activeCount, qc])
  if (!d || d.hs_codes === 0) return null
  const running = d.active.find((a) => a.status === 'running')
  const queued = d.active.filter((a) => a.status === 'queued').length
  const missing = d.hs_codes - d.loaded - d.active.length
  const pct = Math.round((d.loaded / d.hs_codes) * 100)

  return (
    <Card className="mb-6 p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0 flex-[1_1_18rem]">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Database className="size-4 text-brand-700" /> Trade statistics coverage
          </div>
          <p className="mt-0.5 text-[13px] text-muted">
            UN Comtrade data loaded for <b className="tabular text-slate-800">{d.loaded}</b> of <b className="tabular text-slate-800">{d.hs_codes}</b> HS codes used by your catalogue.
            {running && <> HS {running.hs_code}: {running.message}{queued ? ` · ${queued} queued` : ''}.</>}
          </p>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Trade data coverage">
            <div className="h-full rounded-full bg-brand-600 transition-[width] duration-700" style={{ width: `${pct}%` }} />
          </div>
        </div>
        {can('analyst') && d.active.length === 0 && missing > 0 && (
          <Button icon={<Database className="size-4" />} loading={start.isPending} onClick={() => start.mutate()}>
            Load missing data ({missing})
          </Button>
        )}
        {d.active.length > 0 &&
          (running?.message.startsWith('Paused') ? (
            <Badge tone="amber">Paused for API quota · resumes automatically</Badge>
          ) : (
            <Badge tone="blue"><Spinner className="size-3" /> Loading · {d.active.length} HS code{d.active.length === 1 ? '' : 's'} to go</Badge>
          ))}
      </div>
      {d.failed.length > 0 && d.active.length === 0 && (
        <p className="mt-3 text-xs text-amber-800">Last attempt failed for HS {d.failed.join(', ')}. Use “Load missing data” to retry.</p>
      )}
    </Card>
  )
}

export default function Products() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products') })
  const [editing, setEditing] = useState<Product | 'new' | null>(null)
  const [viewing, setViewing] = useState<Product | null>(null)
  const [importing, setImporting] = useState(false)
  const [confirm, setConfirm] = useState<Product | null>(null)
  const [filter, setFilter] = useState('')
  const [category, setCategory] = useState('')
  const [hsStatus, setHsStatus] = useState('')
  const exp = useMutation({ mutationFn: () => download('/api/products/export') })
  const remove = useMutation({
    mutationFn: (p: Product) => del(`/api/products/${p.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['data-status'] })
      toast.success('Product deleted')
      setConfirm(null)
      setViewing(null)
    },
  })

  const all = useMemo(() => products.data ?? [], [products.data])
  const categories = useMemo(() => {
    const m = new Map<string, number>()
    for (const p of all) m.set(p.category || 'Uncategorised', (m.get(p.category || 'Uncategorised') ?? 0) + 1)
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [all])
  const groups = useMemo(() => {
    const f = filter.trim().toLowerCase()
    const rows = all.filter(
      (p) =>
        (!category || (p.category || 'Uncategorised') === category) &&
        (!hsStatus || p.hs_status === hsStatus) &&
        (!f || `${p.name} ${p.sku} ${p.hs_code} ${p.category} ${p.pack_size} ${p.packaging}`.toLowerCase().includes(f)),
    )
    const m = new Map<string, Product[]>()
    for (const p of rows) m.set(p.category || 'Uncategorised', [...(m.get(p.category || 'Uncategorised') ?? []), p])
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [all, filter, category, hsStatus])
  const shown = groups.reduce((n, [, ps]) => n + ps.length, 0)
  const hsCount = new Set(all.map((p) => p.hs_code)).size
  const brands = [...new Set(all.map((p) => p.brand).filter(Boolean))]
  const current = viewing ? (all.find((p) => p.id === viewing.id) ?? viewing) : null

  return (
    <>
      <PageHeader
        eyebrow={brands.length === 1 ? `${brands[0]} catalogue` : undefined}
        title="Product catalogue"
        subtitle={
          all.length
            ? `${all.length} products in ${categories.length} collections, classified under ${hsCount} HS codes. Open a product to analyse its markets, buyers and competitors.`
            : 'Your products and their HS codes.'
        }
        actions={
          <>
            <Button variant="secondary" icon={<Download className="size-4" />} loading={exp.isPending} onClick={() => exp.mutate()} disabled={!all.length}>
              Export CSV
            </Button>
            {can('analyst') && (
              <>
                <Button variant="secondary" icon={<FileUp className="size-4" />} onClick={() => setImporting(true)}>Import</Button>
                <Button icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>Add product</Button>
              </>
            )}
          </>
        }
      />
      <CoveragePanel />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" />
            <Input className="pl-9" placeholder="Search name, SKU, HS code…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Search products" />
          </div>
          <Select className="w-auto!" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Filter by collection">
            <option value="">All collections ({all.length})</option>
            {categories.map(([c, n]) => (
              <option key={c} value={c}>{c} ({n})</option>
            ))}
          </Select>
          <Select className="w-auto!" value={hsStatus} onChange={(e) => setHsStatus(e.target.value)} aria-label="Filter by HS status">
            <option value="">Any HS status</option>
            <option value="suggested">Suggested HS code</option>
            <option value="confirmed">Confirmed HS code</option>
          </Select>
          <span className="ml-auto text-xs text-muted">{shown} shown</span>
        </div>
        {products.isLoading ? (
          <div className="space-y-3 p-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : products.isError ? (
          <div className="p-5"><Notice tone="error">{products.error.message}</Notice></div>
        ) : shown === 0 ? (
          <EmptyState icon={<Boxes className="size-6" />} title={all.length ? 'No matching products' : 'No products yet'}>
            {all.length ? 'Try a different search or clear a filter.' : 'Add a product or import your catalogue to get started.'}
          </EmptyState>
        ) : (
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead>
                <tr className="text-[11.5px] font-semibold tracking-wide text-muted uppercase">
                  <th className="w-16 border-b border-line bg-slate-50/80 px-4 py-2.5"><span className="sr-only">Image</span></th>
                  <th className="border-b border-line bg-slate-50/80 px-4 py-2.5">Product</th>
                  <th className="border-b border-line bg-slate-50/80 px-4 py-2.5">Pack</th>
                  <th className="border-b border-line bg-slate-50/80 px-4 py-2.5">HS code</th>
                  <th className="border-b border-line bg-slate-50/80 px-4 py-2.5">Trade data</th>
                  <th className="border-b border-line bg-slate-50/80 px-4 py-2.5 text-right"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              {groups.map(([cat, ps]) => (
                <tbody key={cat}>
                  <tr>
                    <th colSpan={6} scope="colgroup" className="border-b border-line bg-ink-900/[0.03] px-4 py-2 text-[12.5px] font-semibold text-ink-800">
                      {cat} <span className="ml-1 font-normal text-muted">· {ps.length}</span>
                    </th>
                  </tr>
                  {ps.map((p) => (
                    <tr key={p.id} className="cursor-pointer hover:bg-slate-50/70" onClick={() => setViewing(p)}>
                      <td className="border-b border-line/70 px-4 py-2">
                        {p.catalogue_pages[0] ? (
                          <img src={pageImage(p.catalogue_pages[0], true)} alt="" loading="lazy" className="h-14 w-10 rounded border border-line object-cover" />
                        ) : (
                          <div className="h-14 w-10 rounded border border-dashed border-line" />
                        )}
                      </td>
                      <td className="border-b border-line/70 px-4 py-2">
                        <div className="font-medium text-slate-900">{p.name}</div>
                        <div className="text-xs text-muted">{p.sku}{p.notes && <span className="ml-2 text-amber-700" title={p.notes}>· catalogue note</span>}</div>
                      </td>
                      <td className="border-b border-line/70 px-4 py-2">
                        <div className="text-slate-800">{p.pack_size || '—'}</div>
                        <div className="text-xs text-muted">{p.packaging}</div>
                      </td>
                      <td className="border-b border-line/70 px-4 py-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[13px] font-semibold text-ink-800">{p.hs_code}</span>
                          <HsStatusBadge status={p.hs_status} />
                        </div>
                        <div className="line-clamp-1 max-w-56 text-xs text-muted" title={p.hs_description}>{p.hs_description}</div>
                      </td>
                      <td className="border-b border-line/70 px-4 py-2">
                        {p.has_trade_data ? <Badge tone="green"><Database className="size-3" /> Loaded</Badge> : <Badge>Not loaded</Badge>}
                      </td>
                      <td className="border-b border-line/70 px-4 py-2 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                        <Button variant="ghost" size="sm" aria-label={`View ${p.name}`} onClick={() => setViewing(p)}><Eye className="size-4" /></Button>
                        {can('analyst') && (
                          <>
                            <Button variant="ghost" size="sm" aria-label={`Edit ${p.name}`} onClick={() => setEditing(p)}><Pencil className="size-4" /></Button>
                            <Button variant="ghost" size="sm" aria-label={`Delete ${p.name}`} onClick={() => setConfirm(p)}><Trash2 className="size-4" /></Button>
                          </>
                        )}
                        <Link
                          to={`/p/${p.id}/markets`}
                          className={clsx('ml-2 inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium', 'bg-ink-900 text-white hover:bg-ink-800')}
                        >
                          Open <ArrowRight className="size-3.5" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          </div>
        )}
      </Card>

      <ProductDrawer
        product={current}
        siblings={current ? all.filter((p) => p.hs_code === current.hs_code && p.id !== current.id) : []}
        onClose={() => setViewing(null)}
        onEdit={(p) => {
          setViewing(null)
          setEditing(p)
        }}
      />
      <Modal open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} title={editing === 'new' ? 'Add product' : 'Edit product'} wide>
        {editing !== null && (
          <ProductForm
            key={editing === 'new' ? 'new' : editing.id}
            initial={editing === 'new' ? undefined : editing}
            categories={categories.map(([c]) => c)}
            onDone={() => setEditing(null)}
          />
        )}
      </Modal>
      <Modal open={importing} onOpenChange={setImporting} title="Import products" description="Bulk-add or update your catalogue from a spreadsheet." wide>
        <ImportDialog onDone={() => setImporting(false)} />
      </Modal>
      <Modal
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title="Delete product?"
        description={confirm ? `"${confirm.name}" (${confirm.sku}) will be removed from the catalogue. Trade data for HS ${confirm.hs_code} is kept.` : undefined}
      >
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant="danger" loading={remove.isPending} onClick={() => confirm && remove.mutate(confirm)}>Delete</Button>
        </div>
      </Modal>
    </>
  )
}
