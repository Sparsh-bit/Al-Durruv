import clsx from 'clsx'
import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router'
import type { Product } from '../lib/types'
import { Skeleton } from './ui'

const STEPS = [
  { to: 'markets', label: 'Trade data & markets' },
  { to: 'companies', label: 'Companies' },
  { to: 'analyst', label: 'AI analyst' },
  { to: 'brief', label: 'Brief & export' },
]

export function WorkspaceHeader({ product, title, subtitle, actions, hasData }: {
  product: Product | undefined
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
  hasData?: boolean
}) {
  return (
    <div className="mb-6">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          {product ? (
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold tracking-wider text-brand-700 uppercase">
              <span>{product.name}</span>
              {product.pack_size && (
                <>
                  <span className="text-slate-300">·</span>
                  <span className="tracking-normal normal-case">{product.pack_size}</span>
                </>
              )}
              <span className="text-slate-300">·</span>
              <span className="font-mono tracking-normal">HS {product.hs_code}</span>
            </div>
          ) : (
            <Skeleton className="mb-2 h-4 w-48" />
          )}
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
          {subtitle && <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      <ol className="flex gap-1 overflow-x-auto rounded-xl border border-line bg-white p-1 shadow-card" aria-label="Workflow">
        {STEPS.map((s, i) => (
          <li key={s.to} className="min-w-fit flex-1">
            <NavLink
              to={`../${s.to}`}
              relative="path"
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium whitespace-nowrap transition-colors',
                  isActive ? 'bg-ink-900 text-white' : 'text-slate-600 hover:bg-slate-50',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={clsx(
                      'flex size-5.5 items-center justify-center rounded-full text-[11px] font-semibold',
                      isActive ? 'bg-brand-500 text-ink-950' : i === 0 && hasData ? 'bg-brand-100 text-brand-700' : 'bg-slate-100 text-slate-500',
                    )}
                  >
                    {i === 0 && hasData && !isActive ? <Check className="size-3" /> : i + 1}
                  </span>
                  {s.label}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ol>
    </div>
  )
}
