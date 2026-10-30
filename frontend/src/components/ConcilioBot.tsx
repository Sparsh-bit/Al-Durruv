import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowUp, MessageCircle, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useMatch } from 'react-router'
import { api, post } from '../lib/api'
import { lastProduct } from '../lib/hooks'
import { toHistory, type Msg } from '../lib/chat'
import type { AskResponse, Product } from '../lib/types'
import { ConcilioMark } from './Brand'
import { EvidenceList, StatementList } from './Statements'
import { Select, Spinner } from './ui'

/** Ask the AI from any page. Answers come from the same checked endpoint as the AI advisor, for one product at a time. */
export default function ConcilioBot() {
  const route = useMatch('/p/:productId/*')
  const onAdvisor = useMatch('/p/:productId/analyst')
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<{ ai_enabled: boolean }>('/api/health'), enabled: open })
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products'), enabled: open })
  const withHs = (products.data ?? []).filter((p) => p.hs_code)
  const wanted = picked || route?.params.productId || lastProduct.get()
  const product = withHs.find((p) => String(p.id) === wanted) ?? withHs[0]

  const ask = useMutation({
    meta: { silent: true },
    mutationFn: (question: string) =>
      post<AskResponse>('/api/ai/ask', { hs_code: product?.hs_code, question, history: toHistory(msgs).slice(-6) }),
    onSuccess: (answer) => setMsgs((m) => [...m, { role: 'assistant', answer }]),
    onError: (err) => setMsgs((m) => [...m, { role: 'error', text: err.message }]),
  })

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [msgs, ask.isPending])

  const aiOff = health.data?.ai_enabled === false
  const canAsk = Boolean(product) && !aiOff
  // Focus once the box is usable: it starts disabled while the product list loads.
  useEffect(() => {
    if (open && canAsk) inputRef.current?.focus()
  }, [open, canAsk])

  // The advisor page has the full version of this chat.
  if (onAdvisor) return null

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const question = text.trim()
    if (question.length < 3 || ask.isPending || !canAsk) return
    setMsgs((m) => [...m, { role: 'user', text: question }])
    setText('')
    ask.mutate(question)
  }

  return (
    <div className="fixed right-4 bottom-4 z-30 flex flex-col items-end gap-3 sm:right-6 sm:bottom-6">
      {open && (
        <section
          aria-label="Concilio Bot"
          onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
          className="flex h-[min(600px,calc(100dvh-6.5rem))] w-[min(420px,calc(100vw-2rem))] flex-col overflow-hidden rounded-[14px] border border-line bg-white shadow-pop"
        >
          <header className="flex items-center gap-2.5 bg-ink-900 px-4 py-3 text-white">
            <ConcilioMark inverted className="size-6" />
            <div className="min-w-0 flex-1">
              <div className="text-[14px] font-semibold">Concilio Bot</div>
              <div className="text-[11.5px] text-white/65">Answers from your platform's data</div>
            </div>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close Concilio Bot" className="rounded-[8px] p-1.5 hover:bg-white/10"><X className="size-4" /></button>
          </header>
          <div className="border-b border-line-soft px-4 py-2.5">
            <label className="mb-1 block text-[11.5px] font-medium text-muted" htmlFor="bot-product">Product you are asking about</label>
            <Select
              id="bot-product"
              value={product ? String(product.id) : ''}
              onChange={(e) => {
                setPicked(e.target.value)
                setMsgs([])
              }}
            >
              {withHs.map((p) => <option key={p.id} value={p.id}>{p.name} · HS {p.hs_code}</option>)}
            </Select>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
            {aiOff ? (
              <p className="text-[13px] text-amber-800">AI is not configured. Ask your administrator to turn it on.</p>
            ) : msgs.length === 0 ? (
              <p className="text-[13px] text-muted">Hi, I'm Concilio Bot. Ask me about markets, competitors, tariffs or buyers for this product. If the data isn't in the platform, I'll tell you.</p>
            ) : null}
            {msgs.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-tr-sm bg-ink-900 px-3.5 py-2 text-[13.5px] text-white">{m.text}</div>
              ) : m.role === 'error' ? (
                <p key={i} role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-800">{m.text}</p>
              ) : (
                <div key={i} className="space-y-2">
                  <StatementList statements={m.answer.statements} evidence={m.answer.evidence} />
                  {m.answer.evidence.length > 0 && (
                    <details className="text-[12.5px]">
                      <summary className="cursor-pointer font-medium text-body">Sources ({m.answer.evidence.length})</summary>
                      <div className="mt-2"><EvidenceList evidence={m.answer.evidence} /></div>
                    </details>
                  )}
                </div>
              ),
            )}
            {ask.isPending && <div className="flex items-center gap-2 text-[13px] text-muted"><Spinner className="size-4" /> Thinking…</div>}
            <div ref={endRef} />
          </div>
          <form onSubmit={submit} className="flex items-center gap-2 border-t border-line-soft p-3">
            <input
              ref={inputRef}
              aria-label="Your question"
              value={text}
              maxLength={2000}
              disabled={!canAsk}
              onChange={(e) => setText(e.target.value)}
              placeholder="Ask a question…"
              className="h-10 min-w-0 flex-1 rounded-[9px] border border-line px-3 text-[13.5px] text-ink-900 outline-none focus:border-brand-500 disabled:bg-fog"
            />
            <button type="submit" aria-label="Send" disabled={!canAsk || ask.isPending || text.trim().length < 3} className="flex size-10 shrink-0 items-center justify-center rounded-[9px] bg-ink-900 text-white disabled:opacity-40"><ArrowUp className="size-4" /></button>
          </form>
        </section>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? 'Close Concilio Bot' : 'Open Concilio Bot'}
        className="flex h-12 items-center gap-2 rounded-full bg-ink-900 px-4 text-[13.5px] font-medium text-white shadow-pop hover:bg-ink-800"
      >
        {open ? <X className="size-5" /> : <MessageCircle className="size-5 text-brand-300" />}
        <span>Concilio Bot</span>
      </button>
    </div>
  )
}
