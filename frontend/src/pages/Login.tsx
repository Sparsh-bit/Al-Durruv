import { BarChart3, Building2, ShieldCheck, Sparkles } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { Button, Field, Input, Notice } from '../components/ui'
import { useAuth } from '../lib/auth'

const POINTS = [
  { icon: BarChart3, title: 'Official trade statistics', text: 'UN Comtrade import and export data for every HS code you sell.' },
  { icon: Building2, title: 'Buyer discovery with evidence', text: 'Importers, distributors and retailers, each linked to its public source.' },
  { icon: Sparkles, title: 'Grounded AI analyst', text: 'Answers and briefs that cite their evidence and label uncertainty.' },
]

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/products'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden bg-ink-900 p-12 text-white lg:flex lg:flex-col">
        <div className="pointer-events-none absolute -top-40 -right-40 size-[520px] rounded-full bg-brand-500/15 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-48 -left-24 size-[460px] rounded-full bg-ink-700/60 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <svg viewBox="0 0 32 32" className="size-10" aria-hidden>
            <rect width="32" height="32" rx="8" fill="#12305a" />
            <circle cx="16" cy="16" r="8.5" fill="none" stroke="#2DD4BF" strokeWidth="2.2" />
            <path d="M7.5 16h17M16 7.5c3 3.2 3 13.8 0 17M16 7.5c-3 3.2-3 13.8 0 17" fill="none" stroke="#2DD4BF" strokeWidth="1.6" />
          </svg>
          <span className="text-xl font-semibold tracking-tight">TradeScope</span>
        </div>
        <div className="relative mt-auto max-w-lg">
          <h1 className="text-4xl leading-tight font-semibold tracking-tight">Find the markets and buyers worth your next shipment.</h1>
          <p className="mt-4 text-[15px] leading-relaxed text-slate-300">
            Trade intelligence for exporters and private-label manufacturers. Every figure is traceable to its source.
          </p>
          <ul className="mt-10 space-y-5">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white/10 text-brand-200">
                  <Icon className="size-5" />
                </div>
                <div>
                  <div className="font-medium">{title}</div>
                  <div className="text-sm text-slate-400">{text}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="relative mt-12 flex items-center gap-2 text-xs text-slate-400">
          <ShieldCheck className="size-4" /> Country statistics: UN Comtrade · Company data: public sources with links
        </div>
      </div>

      <div className="flex items-center justify-center px-6 py-12">
        <form onSubmit={submit} className="w-full max-w-sm">
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Sign in</h2>
          <p className="mt-1 text-sm text-muted">Use the account provided by your administrator.</p>
          <div className="mt-8 space-y-4">
            {error && <Notice tone="error">{error}</Notice>}
            <Field label="Email">
              <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
            </Field>
            <Field label="Password">
              <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Button type="submit" loading={busy} className="w-full">
              Sign in
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
