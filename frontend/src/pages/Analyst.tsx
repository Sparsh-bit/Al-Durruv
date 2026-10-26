import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowUp, Bot, ShieldCheck, Sparkles, User } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router'
import { EvidenceList, StatementList } from '../components/Statements'
import { Card, CardHeader, LabelBadge, Notice, Select, Spinner, Textarea } from '../components/ui'
import { LABEL_META } from '../lib/labels'
import { WorkspaceHeader } from '../components/Workspace'
import { api, post } from '../lib/api'
import { useOverview, useProduct } from '../lib/hooks'
import type { AskResponse, Label } from '../lib/types'

type Msg = { role: 'user'; text: string } | { role: 'assistant'; answer: AskResponse } | { role: 'error'; text: string }

const SUGGESTIONS = [
  'Which three markets should we prioritise and why?',
  'Who are our main competitor supplier countries in the top market?',
  'What data is missing before we can quote prices to a buyer?',
  'Which markets are growing fastest from a meaningful base?',
]

function toHistory(msgs: Msg[]): { role: 'user' | 'assistant'; content: string }[] {
  return msgs.flatMap((m): { role: 'user' | 'assistant'; content: string }[] =>
    m.role === 'user'
      ? [{ role: 'user' as const, content: m.text }]
      : m.role === 'assistant'
        ? [{ role: 'assistant' as const, content: m.answer.statements.map((s) => s.text).join(' ') }]
        : [],
  )
}

export default function Analyst() {
  const [params] = useSearchParams()
  const product = useProduct()
  const hs = product.data?.hs_code
  const overview = useOverview(hs)
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<{ ai_enabled: boolean; model: string }>('/api/health'), staleTime: 300_000 })
  const ov = overview.data?.has_data ? overview.data : null
  const [focus, setFocus] = useState(params.get('focus') ?? '')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  const ask = useMutation({
    meta: { silent: true },
    mutationFn: (question: string) =>
      post<AskResponse>('/api/ai/ask', { hs_code: hs, question, focus_m49: focus ? Number(focus) : null, history: toHistory(msgs).slice(-6) }),
    onSuccess: (answer) => setMsgs((m) => [...m, { role: 'assistant', answer }]),
    onError: (err) => setMsgs((m) => [...m, { role: 'error', text: err.message }]),
  })

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [msgs, ask.isPending])

  const send = (q: string) => {
    const question = q.trim()
    if (question.length < 3 || ask.isPending || !hs) return
    setMsgs((m) => [...m, { role: 'user', text: question }])
    setText('')
    ask.mutate(question)
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    send(text)
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(text)
    }
  }
  const disabled = health.data?.ai_enabled === false || !ov

  return (
    <>
      <WorkspaceHeader
        product={product.data}
        hasData={Boolean(ov)}
        title="AI business analyst"
        subtitle="Ask questions about markets, competitors and prospects. Answers use only the platform's data, cite their evidence and label uncertainty."
      />
      {health.data?.ai_enabled === false && (
        <div className="mb-6"><Notice tone="warn" title="AI is not configured">Add <code>ANTHROPIC_API_KEY</code> to the backend <code>.env</code> file and restart the API.</Notice></div>
      )}
      {overview.data && !ov && (
        <div className="mb-6"><Notice tone="warn" title="Load trade data first">The analyst answers from loaded statistics. Load data on the Market intelligence step.</Notice></div>
      )}
      <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
        <Card className="flex min-h-[560px] flex-col">
          <div className="flex-1 space-y-6 overflow-y-auto p-5">
            {msgs.length === 0 && (
              <div className="py-8 text-center">
                <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-brand-50 text-brand-700"><Sparkles className="size-6" /></div>
                <h2 className="mt-4 text-[15px] font-semibold text-slate-900">What would you like to know?</h2>
                <p className="mt-1 text-sm text-muted">Try one of these questions.</p>
                <div className="mx-auto mt-5 grid max-w-2xl gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" disabled={disabled} onClick={() => send(s)} className="rounded-xl border border-line bg-white px-4 py-3 text-left text-[13px] text-slate-700 shadow-card hover:border-brand-500 hover:bg-brand-50/40 disabled:cursor-not-allowed disabled:opacity-50">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="flex justify-end gap-3">
                  <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-ink-900 px-4 py-2.5 text-[14px] text-white">{m.text}</div>
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-600"><User className="size-4" /></div>
                </div>
              ) : m.role === 'error' ? (
                <div key={i} className="pl-11"><Notice tone="error">{m.text}</Notice></div>
              ) : (
                <div key={i} className="flex gap-3">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white"><Bot className="size-4" /></div>
                  <div className="min-w-0 flex-1 space-y-4">
                    <StatementList statements={m.answer.statements} evidence={m.answer.evidence} />
                    {m.answer.usage.cost_usd !== undefined && (
                      <p className="text-[11px] text-muted">
                        {m.answer.usage.model} · {m.answer.usage.input_tokens + m.answer.usage.output_tokens} tokens · ${m.answer.usage.cost_usd.toFixed(4)}
                      </p>
                    )}
                    {m.answer.evidence.length > 0 && (
                      <details className="group rounded-lg border border-line bg-slate-50/60 px-3 py-2">
                        <summary className="cursor-pointer text-xs font-medium text-slate-600">Evidence used ({m.answer.evidence.length})</summary>
                        <div className="mt-2"><EvidenceList evidence={m.answer.evidence} /></div>
                      </details>
                    )}
                    {m.answer.follow_up_questions.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {m.answer.follow_up_questions.map((q) => (
                          <button key={q} type="button" onClick={() => send(q)} disabled={ask.isPending} className="rounded-full border border-line bg-white px-3 py-1.5 text-xs text-slate-700 hover:border-brand-500 hover:text-brand-700 disabled:opacity-50">
                            {q}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
            {ask.isPending && (
              <div className="flex items-center gap-3 pl-11 text-sm text-muted"><Spinner className="size-4" /> Analysing the evidence…</div>
            )}
            <div ref={endRef} />
          </div>
          <form onSubmit={submit} className="border-t border-line p-3">
            <div className="flex items-end gap-2 rounded-xl border border-line bg-white p-2 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
              <Textarea
                rows={1}
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={onKey}
                disabled={disabled}
                placeholder={disabled ? 'AI analyst unavailable' : 'Ask about markets, competitors, buyers or data gaps…'}
                className="max-h-40 min-h-9 resize-none border-0 shadow-none focus:ring-0"
                aria-label="Question"
              />
              <button type="submit" disabled={disabled || ask.isPending || text.trim().length < 3} aria-label="Send" className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-ink-900 text-white hover:bg-ink-800 disabled:opacity-40">
                <ArrowUp className="size-4" />
              </button>
            </div>
          </form>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader title="Focus market" subtitle="Adds supplier detail for one country" />
            <div className="p-4">
              <Select value={focus} onChange={(e) => setFocus(e.target.value)} aria-label="Focus market">
                <option value="">Top 3 markets (default)</option>
                {ov?.top_importers.map((r) => <option key={r.m49} value={r.m49}>{r.name}</option>)}
              </Select>
            </div>
          </Card>
          <Card className="p-5">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900"><ShieldCheck className="size-4 text-brand-700" /> Reading the labels</div>
            <ul className="space-y-2.5">
              {(Object.keys(LABEL_META) as Label[]).map((l) => (
                <li key={l} className="flex gap-3 text-xs text-slate-600">
                  <div className="w-24 shrink-0"><LabelBadge label={l} /></div>
                  {LABEL_META[l].help}
                </li>
              ))}
            </ul>
            {health.data?.model && <p className="mt-4 text-[11px] text-muted">Model: {health.data.model}</p>}
          </Card>
        </div>
      </div>
    </>
  )
}
