import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { ClientMark, ConcilioMark, CONCILIO_URL } from '../components/Brand'
import DotPattern from '../components/lightswind/dot-pattern'
import { Button, Field, Input, Notice } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useReveal } from '../lib/motion'

const LEDGER = [
  ['01', 'Trade statistics', 'UN Comtrade imports and exports by HS code, with the source and retrieval date on every figure.'],
  ['02', 'Product master', "Client HS codes kept exactly as given, next to the HS6 used for analysis, with a review trail."],
  ['03', 'Retail & private label', 'Priority retailers, vendor routes and opportunity scores you can trace to each input.'],
  ['04', 'Grounded advisor', 'AI answers that separate sourced facts, client information, hypotheses and unknowns.'],
]

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const brand = useQuery({
    queryKey: ['branding'],
    queryFn: () => api<{ client_name: string; client_brand: string }>('/api/branding'),
    staleTime: Infinity,
    retry: false,
  })
  const ref = useReveal<HTMLDivElement>([])

  if (user) return <Navigate to={from} replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed')
    } finally {
      setBusy(false)
    }
  }
  const clientName = brand.data?.client_name
  const clientBrand = brand.data?.client_brand || clientName || ''

  return (
    <div ref={ref} className="grid min-h-screen bg-white lg:grid-cols-[1.15fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-line bg-canvas lg:flex lg:flex-col">
        <DotPattern width={22} height={22} cr={0.9} className="fill-ink-900/[0.09] blur-0 [mask-image:linear-gradient(to_bottom,black,transparent_85%)]" />
        <div className="relative flex items-center justify-between px-12 pt-10">
          <a href={CONCILIO_URL} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2.5" data-reveal>
            <ConcilioMark className="size-8" />
            <span className="font-display text-[16px] font-semibold text-ink-900">Concilio Solutions</span>
          </a>
          <span className="micro text-muted" data-reveal>Global trade intelligence</span>
        </div>

        <div className="relative mt-auto px-12 pb-12">
          {clientBrand && (
            <div className="mb-6 flex items-center gap-3" data-reveal>
              <ClientMark brand={clientBrand} className="size-10 text-[19px]" />
              <div className="leading-tight">
                <div className="font-display text-[17px] font-semibold text-ink-900">{clientBrand}</div>
                {clientName && clientName !== clientBrand && <div className="text-[12.5px] text-muted">{clientName}</div>}
              </div>
            </div>
          )}
          <h1 className="max-w-xl text-[44px] leading-[1.05] font-semibold text-ink-900" data-reveal>
            Know where your next container should go, <span className="text-brand-700">and why.</span>
          </h1>
          <dl className="mt-10 grid max-w-2xl grid-cols-2 border-t border-ink-900/15">
            {LEDGER.map(([n, t, d], i) => (
              <div key={n} className={`border-b border-ink-900/10 py-5 pr-6 ${i % 2 ? 'pl-6' : 'border-r'}`} data-reveal>
                <dt className="flex items-baseline gap-2.5">
                  <span className="num text-[11.5px] text-brand-700">{n}</span>
                  <span className="text-[14px] font-semibold text-ink-900">{t}</span>
                </dt>
                <dd className="mt-1.5 text-[13px] leading-relaxed text-body">{d}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="flex flex-col px-6 py-10 sm:px-12">
        <div className="flex items-center gap-2.5 lg:hidden">
          <ConcilioMark className="size-7" />
          <span className="font-display text-[15px] font-semibold">Concilio Solutions</span>
        </div>
        <form onSubmit={submit} className="m-auto w-full max-w-sm py-10" data-reveal>
          <div className="micro text-brand-700">Secure sign-in</div>
          <h2 className="mt-2 text-[28px] font-semibold text-ink-900">Welcome back</h2>
          <p className="mt-1.5 text-[13.5px] text-body">Use the account your administrator gave you.</p>
          <div className="mt-8 space-y-4">
            {error && <Notice tone="error">{error}</Notice>}
            <Field label="Work email">
              <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
            </Field>
            <Field label="Password">
              <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Button type="submit" loading={busy} className="h-10.5 w-full">Sign in</Button>
          </div>
        </form>
        <p className="text-center text-[11.5px] text-muted">
          A platform by{' '}
          <a href={CONCILIO_URL} target="_blank" rel="noopener noreferrer" className="font-medium text-ink-900 hover:underline">
            concilio.solutions
          </a>
        </p>
      </section>
    </div>
  )
}
