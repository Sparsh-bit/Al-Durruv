import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PackageSearch } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { api, del, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime } from '../lib/format'
import { HS_SOURCE } from '../lib/labels'
import type { Product, ProductCommodities } from '../lib/types'
import { Badge, Button, Card, Notice, Spinner } from './ui'

/** Maersk commodity references for a product, next to the client code and the analysis HS6. Suggestions never
 * replace the client's code; using one for analysis is an explicit admin choice and stays "needs review". */
export default function MaerskCommodities({ p }: { p: Product }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [asked, setAsked] = useState(false)
  const [choice, setChoice] = useState<{ code: string; hs: string } | null>(null)
  const [useForAnalysis, setUseForAnalysis] = useState(false)
  const q = useQuery({
    queryKey: ['maersk-commodities', p.id],
    queryFn: () => api<ProductCommodities>(`/api/products/${p.id}/maersk-commodities`),
    enabled: asked,
    retry: false,
    staleTime: 10 * 60_000,
  })
  const save = useMutation({
    mutationFn: () => post(`/api/products/${p.id}/maersk-commodity`, { commodity_code: choice!.code, hs_code: choice!.hs, use_for_analysis: useForAnalysis }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['product'] })
      qc.invalidateQueries({ queryKey: ['maersk-commodities', p.id] })
      toast.success(useForAnalysis ? 'Maersk reference saved and used for trade analysis (still needs review)' : 'Maersk reference saved')
      setChoice(null)
    },
  })
  const clear = useMutation({
    mutationFn: () => del(`/api/products/${p.id}/maersk-commodity`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['product'] })
    },
  })
  const d = q.data
  const sel = p.maersk_commodity

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="micro text-muted">Maersk commodity reference</div>
          <p className="mt-1 text-[12.5px] text-body">Code source for analysis: <b>{HS_SOURCE[p.hs_source] ?? p.hs_source}</b></p>
        </div>
        {!asked && <Button size="sm" variant="secondary" icon={<PackageSearch />} onClick={() => setAsked(true)}>Look up in Maersk</Button>}
      </div>

      {sel && (
        <div className="mt-3 rounded-[10px] border border-line bg-paper p-3 text-[13px]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink-900">{sel.commodity_code} · {sel.commodity_name}</span>
            {can('analyst') && <Button size="sm" variant="ghost" loading={clear.isPending} onClick={() => clear.mutate()}>Remove</Button>}
          </div>
          <div className="mt-1 text-[12px] text-muted">
            HS listed by Maersk: {sel.hs_codes.map((h) => h.code).join(', ') || 'none'}{sel.selected_hs && ` · chosen ${sel.selected_hs}`} · selected by {sel.selected_by} · retrieved {dateTime(sel.retrieved_at)}
          </div>
        </div>
      )}

      {asked && (
        <div className="mt-4">
          {q.isLoading ? (
            <div className="flex items-center gap-2 text-[13px] text-muted"><Spinner className="size-4" /> Searching Maersk reference data…</div>
          ) : q.isError ? (
            <Notice tone="warn">{q.error.message} The rest of the product record and trade analysis still work.</Notice>
          ) : d ? (
            <div className="space-y-3">
              {d.message && <Notice tone="info">{d.message}</Notice>}
              {d.ambiguous && <p className="text-[12.5px] text-amber-800">Several commodities match. Choose the one that fits the product, or none.</p>}
              <ul className="space-y-2">
                {d.candidates.map((c) => (
                  <li key={c.commodity_code} className="rounded-[10px] border border-line p-3 text-[13px]">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="num text-ink-900">{c.commodity_code}</span>
                      <span className="font-medium text-ink-900">{c.commodity_name}</span>
                      {c.matches_analysis_hs6 && <Badge tone="green">matches analysis HS6</Badge>}
                      {c.matches_client_hs6 && <Badge tone="teal">matches client HS6</Badge>}
                      {c.cargo_types.map((t) => <Badge key={t}>{t}</Badge>)}
                    </div>
                    <div className="mt-1 text-[11.5px] text-muted">found by {c.matched_by}</div>
                    {c.hs_codes.length === 0 ? (
                      <div className="mt-2 text-[12px] text-muted">Maersk lists no HS code for this commodity.</div>
                    ) : (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {c.hs_codes.map((h) => (
                          <label key={h.code} className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-line-soft px-2 py-1 text-[12px]">
                            <input type="radio" name={`hs-${p.id}`} className="accent-ink-900" disabled={!can('analyst')} checked={choice?.code === c.commodity_code && choice.hs === h.code} onChange={() => setChoice({ code: c.commodity_code, hs: h.code })} />
                            <span className="num">{h.code}</span> <span className="text-muted">{h.name}</span>
                          </label>
                        ))}
                      </div>
                    )}
                    {c.hs_codes.length === 0 && can('analyst') && (
                      <Button size="sm" variant="ghost" className="mt-1" onClick={() => setChoice({ code: c.commodity_code, hs: '' })}>Select this commodity</Button>
                    )}
                  </li>
                ))}
              </ul>
              {choice && can('analyst') && (
                <div className="flex flex-wrap items-center gap-3 border-t border-line-soft pt-3">
                  {can('admin') && choice.hs && (
                    <label className="flex items-center gap-2 text-[12.5px] text-ink-800">
                      <input type="checkbox" className="size-4 accent-ink-900" checked={useForAnalysis} onChange={(e) => setUseForAnalysis(e.target.checked)} />
                      Use HS {choice.hs.slice(0, 6)} for trade analysis (client code is kept)
                    </label>
                  )}
                  <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>Save reference</Button>
                </div>
              )}
              <p className="text-[11.5px] leading-relaxed text-muted">{d.disclaimer} Searched: {d.searches.map((s) => `${s.by} “${s.term}” (${s.results})`).join(', ')}.</p>
            </div>
          ) : null}
        </div>
      )}
    </Card>
  )
}
