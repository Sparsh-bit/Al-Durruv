import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Boxes, Database, Download, FileUp, Pencil, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { Badge, Button, Card, EmptyState, Field, Input, Modal, Notice, PageHeader, Skeleton, Table, td, th } from '../components/ui'
import { api, del, post, put } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { Product } from '../lib/types'

type HS = { code: string; description: string }
const EMPTY = { sku: '', name: '', hs_code: '', description: '', category: '' }

function HsPicker({ value, onChange }: { value: string; onChange: (code: string, desc?: string) => void }) {
  const [q, setQ] = useState(value)
  const [open, setOpen] = useState(false)
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 200)
    return () => clearTimeout(t)
  }, [q])
  const results = useQuery({
    queryKey: ['hs', debounced],
    queryFn: () => api<HS[]>(`/api/hs-codes?q=${encodeURIComponent(debounced)}&limit=12`),
    enabled: open && debounced.trim().length >= 2,
  })
  return (
    <div className="relative">
      <Input
        value={q}
        placeholder="Type a code (1905) or keyword (biscuits)"
        onChange={(e) => {
          setQ(e.target.value)
          onChange(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {open && (results.data?.length ?? 0) > 0 && (
        <ul className="absolute z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-line bg-white p-1 shadow-pop" role="listbox">
          {results.data!.map((h) => (
            <li key={h.code}>
              <button
                type="button"
                className="flex w-full gap-3 rounded-md px-2.5 py-2 text-left text-sm hover:bg-slate-50"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setQ(h.code)
                  onChange(h.code, h.description)
                  setOpen(false)
                }}
              >
                <span className="font-mono text-xs font-semibold text-brand-700">{h.code}</span>
                <span className="line-clamp-2 text-slate-700">{h.description}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ProductForm({ initial, onDone }: { initial?: Product; onDone: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState(initial ? { ...EMPTY, ...initial } : EMPTY)
  const [hsDesc, setHsDesc] = useState(initial?.hs_description ?? '')
  const save = useMutation({
    mutationFn: () => {
      const body = { sku: form.sku, name: form.name, hs_code: form.hs_code, description: form.description, category: form.category }
      return initial ? put<Product>(`/api/products/${initial.id}`, body) : post<Product>('/api/products', body)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['product'] })
      toast.success(initial ? 'Product updated' : 'Product added')
      onDone()
    },
  })
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="SKU">
          <Input required maxLength={64} value={form.sku} onChange={set('sku')} />
        </Field>
        <Field label="Category">
          <Input value={form.category} onChange={set('category')} placeholder="e.g. Bakery" />
        </Field>
      </div>
      <Field label="Product name">
        <Input required maxLength={255} value={form.name} onChange={set('name')} />
      </Field>
      <Field label="HS code (6-digit)" hint={hsDesc || 'Search the official UN Comtrade HS classification.'}>
        <HsPicker
          value={form.hs_code}
          onChange={(code, desc) => {
            setForm((f) => ({ ...f, hs_code: code }))
            setHsDesc(desc ?? '')
          }}
        />
      </Field>
      <Field label="Description">
        <Input value={form.description} onChange={set('description')} />
      </Field>
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" onClick={onDone}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>{initial ? 'Save changes' : 'Add product'}</Button>
      </div>
    </form>
  )
}

function ImportDialog({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<{ created: number; updated: number; errors: { line: number; error: string }[] } | null>(null)
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return api<NonNullable<typeof result>>('/api/products/import', { method: 'POST', body: fd })
    },
    onSuccess: (r) => {
      setResult(r)
      qc.invalidateQueries({ queryKey: ['products'] })
      toast.success(`Imported ${r.created} new, ${r.updated} updated`)
    },
  })
  const template = () => {
    const csv = 'sku,name,hs_code,category,description\nBISC-001,Butter cookies 200 g,190531,Bakery,Retail pack\n'
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob([csv], { type: 'text/csv' })), download: 'product-template.csv' })
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  }
  return (
    <div className="space-y-4">
      <Notice>
        Upload a <b>.csv</b> or <b>.xlsx</b> file with columns <code>sku</code>, <code>name</code>, <code>hs_code</code> and optionally{' '}
        <code>category</code>, <code>description</code>. Existing SKUs are updated.
      </Notice>
      <button
        type="button"
        onClick={() => input.current?.click()}
        className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-line px-6 py-10 text-sm text-muted hover:border-brand-500 hover:bg-brand-50/40"
      >
        <FileUp className="size-6 text-brand-600" />
        {upload.isPending ? 'Uploading…' : 'Choose a file to upload (max 5 MB)'}
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

export default function Products() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products') })
  const [editing, setEditing] = useState<Product | 'new' | null>(null)
  const [importing, setImporting] = useState(false)
  const [confirm, setConfirm] = useState<Product | null>(null)
  const [filter, setFilter] = useState('')
  const remove = useMutation({
    mutationFn: (p: Product) => del(`/api/products/${p.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      toast.success('Product deleted')
      setConfirm(null)
    },
  })
  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase()
    return (products.data ?? []).filter((p) => !f || `${p.name} ${p.sku} ${p.hs_code} ${p.category}`.toLowerCase().includes(f))
  }, [products.data, filter])

  return (
    <>
      <PageHeader
        title="Product catalogue"
        subtitle="Your products and their HS codes. Open a product to analyse its markets, buyers and competitors."
        actions={
          can('analyst') && (
            <>
              <Button variant="secondary" icon={<FileUp className="size-4" />} onClick={() => setImporting(true)}>Import CSV / Excel</Button>
              <Button icon={<Plus className="size-4" />} onClick={() => setEditing('new')}>Add product</Button>
            </>
          )
        }
      />
      <Card>
        <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-3">
          <Input className="max-w-xs" placeholder="Filter products…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter products" />
          <span className="text-xs text-muted">{rows.length} product{rows.length === 1 ? '' : 's'}</span>
        </div>
        {products.isLoading ? (
          <div className="space-y-3 p-5">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}
          </div>
        ) : products.isError ? (
          <div className="p-5"><Notice tone="error">{products.error.message}</Notice></div>
        ) : rows.length === 0 ? (
          <EmptyState icon={<Boxes className="size-6" />} title={filter ? 'No matching products' : 'No products yet'}>
            {filter ? 'Try a different search.' : 'Add a product or import your catalogue to get started.'}
          </EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <th className={th}>Product</th>
                <th className={th}>HS code</th>
                <th className={th}>Category</th>
                <th className={th}>Trade data</th>
                <th className={`${th} text-right`}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="group hover:bg-slate-50/60">
                  <td className={td}>
                    <div className="font-medium text-slate-900">{p.name}</div>
                    <div className="text-xs text-muted">{p.sku}</div>
                  </td>
                  <td className={td}>
                    <div className="font-mono text-[13px] font-semibold text-ink-800">{p.hs_code}</div>
                    <div className="line-clamp-1 max-w-sm text-xs text-muted" title={p.hs_description}>{p.hs_description}</div>
                  </td>
                  <td className={`${td} text-slate-600`}>{p.category || '—'}</td>
                  <td className={td}>
                    {p.has_trade_data ? <Badge tone="green"><Database className="size-3" /> Loaded</Badge> : <Badge>Not loaded</Badge>}
                  </td>
                  <td className={`${td} text-right whitespace-nowrap`}>
                    {can('analyst') && (
                      <>
                        <Button variant="ghost" size="sm" aria-label={`Edit ${p.name}`} onClick={() => setEditing(p)}><Pencil className="size-4" /></Button>
                        <Button variant="ghost" size="sm" aria-label={`Delete ${p.name}`} onClick={() => setConfirm(p)}><Trash2 className="size-4" /></Button>
                      </>
                    )}
                    <Link to={`/p/${p.id}/markets`} className="ml-2 inline-flex h-8 items-center gap-1.5 rounded-lg bg-ink-900 px-3 text-[13px] font-medium text-white hover:bg-ink-800">
                      Open <ArrowRight className="size-3.5" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} title={editing === 'new' ? 'Add product' : 'Edit product'}>
        {editing !== null && <ProductForm key={editing === 'new' ? 'new' : editing.id} initial={editing === 'new' ? undefined : editing} onDone={() => setEditing(null)} />}
      </Modal>
      <Modal open={importing} onOpenChange={setImporting} title="Import products" description="Bulk-add your catalogue from a spreadsheet.">
        <ImportDialog onDone={() => setImporting(false)} />
      </Modal>
      <Modal open={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)} title="Delete product?" description={confirm ? `"${confirm.name}" will be removed from the catalogue. Trade data for HS ${confirm.hs_code} is kept.` : undefined}>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant="danger" loading={remove.isPending} onClick={() => confirm && remove.mutate(confirm)}>Delete</Button>
        </div>
      </Modal>
    </>
  )
}
