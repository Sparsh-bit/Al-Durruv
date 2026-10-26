import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { api, post, put } from '../lib/api'
import type { Product } from '../lib/types'
import { Button, Field, Input, Select, Textarea } from './ui'

type HS = { code: string; description: string }
type FormState = {
  sku: string
  name: string
  brand: string
  category: string
  hs_code: string
  hs_status: Product['hs_status']
  hs_note: string
  pack_size: string
  net_quantity: string
  net_unit: Product['net_unit']
  packaging: string
  catalogue_page: string
  description: string
  notes: string
}

const EMPTY: FormState = {
  sku: '',
  name: '',
  brand: 'Durra',
  category: '',
  hs_code: '',
  hs_status: 'suggested',
  hs_note: '',
  pack_size: '',
  net_quantity: '',
  net_unit: 'g',
  packaging: '',
  catalogue_page: '',
  description: '',
  notes: '',
}

function fromProduct(p: Product): FormState {
  return {
    sku: p.sku,
    name: p.name,
    brand: p.brand,
    category: p.category,
    hs_code: p.hs_code,
    hs_status: p.hs_status,
    hs_note: p.hs_note,
    pack_size: p.pack_size,
    net_quantity: p.net_quantity === null ? '' : String(p.net_quantity),
    net_unit: p.net_unit,
    packaging: p.packaging,
    catalogue_page: p.catalogue_page,
    description: p.description,
    notes: p.notes,
  }
}

export function HsPicker({ value, onChange }: { value: string; onChange: (code: string, desc?: string) => void }) {
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
        required
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

export default function ProductForm({ initial, categories, onDone }: { initial?: Product; categories: string[]; onDone: (p?: Product) => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState<FormState>(initial ? fromProduct(initial) : EMPTY)
  const [hsDesc, setHsDesc] = useState(initial?.hs_description ?? '')
  const set = (k: keyof FormState) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }))

  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...f,
        net_quantity: f.net_quantity === '' ? null : Number(f.net_quantity),
        net_unit: f.net_quantity === '' ? '' : f.net_unit,
      }
      return initial ? put<Product>(`/api/products/${initial.id}`, body) : post<Product>('/api/products', body)
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['product'] })
      qc.invalidateQueries({ queryKey: ['data-status'] })
      toast.success(initial ? 'Product updated' : 'Product added')
      onDone(p)
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="mb-3 text-xs font-semibold tracking-wider text-muted uppercase">Product</legend>
        <Field label="Product name">
          <Input required maxLength={255} value={f.name} onChange={set('name')} />
        </Field>
        <Field label="SKU">
          <Input required maxLength={64} value={f.sku} onChange={set('sku')} />
        </Field>
        <Field label="Collection">
          <Input list="collections" maxLength={120} value={f.category} onChange={set('category')} placeholder="e.g. Olives" />
          <datalist id="collections">
            {categories.map((c) => <option key={c} value={c} />)}
          </datalist>
        </Field>
        <Field label="Brand">
          <Input maxLength={120} value={f.brand} onChange={set('brand')} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Description">
            <Textarea rows={2} maxLength={4000} value={f.description} onChange={set('description')} />
          </Field>
        </div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-4">
        <legend className="mb-3 text-xs font-semibold tracking-wider text-muted uppercase">Pack</legend>
        <div className="sm:col-span-2">
          <Field label="Pack size (as printed)" hint="e.g. 600 g (drained 400 g)">
            <Input maxLength={80} value={f.pack_size} onChange={set('pack_size')} />
          </Field>
        </div>
        <Field label="Net quantity">
          <Input type="number" min={0} step="any" value={f.net_quantity} onChange={set('net_quantity')} />
        </Field>
        <Field label="Unit">
          <Select value={f.net_unit} onChange={set('net_unit')}>
            <option value="g">g</option>
            <option value="kg">kg</option>
            <option value="ml">ml</option>
            <option value="L">L</option>
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Packaging">
            <Input maxLength={80} value={f.packaging} onChange={set('packaging')} placeholder="e.g. Glass jar" />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Catalogue page(s)" hint="Numbers separated by commas">
            <Input maxLength={40} pattern="[0-9, ]*" value={f.catalogue_page} onChange={set('catalogue_page')} />
          </Field>
        </div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="mb-3 text-xs font-semibold tracking-wider text-muted uppercase">Customs classification</legend>
        <Field label="HS code (6-digit)" hint={hsDesc || 'Search the official UN Comtrade HS classification.'}>
          <HsPicker
            value={f.hs_code}
            onChange={(code, desc) => {
              setF((s) => ({ ...s, hs_code: code, hs_status: code === initial?.hs_code ? s.hs_status : 'suggested' }))
              setHsDesc(desc ?? '')
            }}
          />
        </Field>
        <Field label="Classification status" hint="Confirm only after a customs broker or the client has verified the code.">
          <Select value={f.hs_status} onChange={set('hs_status')}>
            <option value="suggested">Suggested</option>
            <option value="confirmed">Confirmed</option>
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Classification note">
            <Input maxLength={2000} value={f.hs_note} onChange={set('hs_note')} />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Internal notes">
            <Textarea rows={2} maxLength={4000} value={f.notes} onChange={set('notes')} />
          </Field>
        </div>
      </fieldset>

      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button variant="secondary" onClick={() => onDone()}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>{initial ? 'Save changes' : 'Add product'}</Button>
      </div>
    </form>
  )
}
