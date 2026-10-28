import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { api, post, put } from '../lib/api'
import type { AppSettings, Entity, Product } from '../lib/types'
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
  name_ar: string
  client_hs_code: string
  ingredients: string
  processing: string
  manufacturing_country: string
  priority_category: string
  export_entity_id: string
}

const EMPTY: FormState = {
  sku: '',
  name: '',
  brand: '',
  category: '',
  hs_code: '',
  hs_status: 'candidate',
  hs_note: '',
  pack_size: '',
  net_quantity: '',
  net_unit: 'g',
  packaging: '',
  catalogue_page: '',
  description: '',
  notes: '',
  name_ar: '',
  client_hs_code: '',
  ingredients: '',
  processing: '',
  manufacturing_country: '',
  priority_category: '',
  export_entity_id: '',
}

function fromProduct(p: Product): FormState {
  return {
    sku: p.sku,
    name: p.name,
    brand: p.brand,
    category: p.category,
    hs_code: p.hs_code ?? '',
    hs_status: p.hs_status,
    hs_note: p.hs_note,
    pack_size: p.pack_size,
    net_quantity: p.net_quantity === null ? '' : String(p.net_quantity),
    net_unit: p.net_unit,
    packaging: p.packaging,
    catalogue_page: p.catalogue_page,
    description: p.description,
    notes: p.notes,
    name_ar: p.name_ar,
    client_hs_code: p.client_hs_code,
    ingredients: p.ingredients,
    processing: p.processing,
    manufacturing_country: p.manufacturing_country,
    priority_category: p.priority_category,
    export_entity_id: p.export_entity_id ? String(p.export_entity_id) : '',
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
                className="flex w-full gap-3 rounded-md px-2.5 py-2 text-left text-sm hover:bg-fog"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setQ(h.code)
                  onChange(h.code, h.description)
                  setOpen(false)
                }}
              >
                <span className="font-mono text-xs font-semibold text-brand-700">{h.code}</span>
                <span className="line-clamp-2 text-ink-800">{h.description}</span>
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
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<AppSettings>('/api/admin/settings') })
  const entities = useQuery({ queryKey: ['entities'], queryFn: () => api<Entity[]>('/api/entities') })
  const defaultBrand = settings.data?.company_profile.brand ?? ''

  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...f,
        net_quantity: f.net_quantity === '' ? null : Number(f.net_quantity),
        net_unit: f.net_quantity === '' ? '' : f.net_unit,
        brand: f.brand || (initial ? '' : defaultBrand),
        hs_code: f.hs_code || null,
        export_entity_id: f.export_entity_id ? Number(f.export_entity_id) : null,
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
        <legend className="micro mb-3 text-muted">Product</legend>
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
          <Input maxLength={120} value={f.brand} onChange={set('brand')} placeholder={initial ? '' : defaultBrand} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Description">
            <Textarea rows={2} maxLength={4000} value={f.description} onChange={set('description')} />
          </Field>
        </div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="micro mb-3 text-muted">Product master</legend>
        <Field label="Arabic name">
          <Input dir="rtl" lang="ar" maxLength={255} value={f.name_ar} onChange={set('name_ar')} />
        </Field>
        <Field label="Priority private-label category">
          <Select value={f.priority_category} onChange={set('priority_category')}>
            <option value="">Not a priority category</option>
            {(settings.data?.priority_categories ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
            {f.priority_category && !settings.data?.priority_categories.includes(f.priority_category) && <option value={f.priority_category}>{f.priority_category}</option>}
          </Select>
        </Field>
        <Field label="Manufacturing country (ISO3)">
          <Input maxLength={3} pattern="[A-Za-z]{3}" value={f.manufacturing_country} onChange={set('manufacturing_country')} placeholder="e.g. EGY" className="font-mono uppercase" />
        </Field>
        <Field label="Export / manufacturing entity">
          <Select value={f.export_entity_id} onChange={set('export_entity_id')}>
            <option value="">Not assigned</option>
            {(entities.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.name} ({e.country_iso3 || '—'})</option>)}
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Ingredients">
            <Textarea rows={2} maxLength={4000} value={f.ingredients} onChange={set('ingredients')} />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Processing" hint="e.g. in brine, in vinegar, pasteurised, frozen. This decides several HS subheadings.">
            <Textarea rows={2} maxLength={4000} value={f.processing} onChange={set('processing')} />
          </Field>
        </div>
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-4">
        <legend className="micro mb-3 text-muted">Pack</legend>
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
        <legend className="micro mb-3 text-muted">Customs classification</legend>
        <Field label="HS code (6-digit)" hint={hsDesc || 'Search the official UN Comtrade HS classification.'}>
          <HsPicker
            value={f.hs_code}
            onChange={(code, desc) => {
              setF((s) => ({ ...s, hs_code: code, hs_status: code === initial?.hs_code ? s.hs_status : 'candidate' }))
              setHsDesc(desc ?? '')
            }}
          />
        </Field>
        <Field
          label="Client HS code (as provided)"
          hint={initial?.client_hs_code ? 'Kept exactly as the client provided it.' : 'National 8–10 digit code from the client, if any.'}
        >
          <Input
            value={f.client_hs_code}
            onChange={set('client_hs_code')}
            readOnly={Boolean(initial?.client_hs_code)}
            inputMode="numeric"
            pattern="[0-9. ]*"
            maxLength={14}
            className="font-mono"
          />
        </Field>
        <p className="text-xs leading-relaxed text-muted sm:col-span-2">
          Confirm or change the classification from the product panel (HS review). Editing the code here resets it to Candidate.
        </p>
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
