import * as Menu from '@radix-ui/react-dropdown-menu'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { BarChart3, Boxes, Building2, ChevronDown, FileText, KanbanSquare, KeyRound, LogOut, Menu as MenuIcon, Settings2, Ship, Sparkles, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useMatch } from 'react-router'
import { api } from '../lib/api'
import ChangePassword from './ChangePassword'
import { useAuth } from '../lib/auth'
import type { Product } from '../lib/types'

const lastProduct = {
  get: () => {
    try {
      return localStorage.getItem('ti.product')
    } catch {
      return null
    }
  },
  set: (id: string) => {
    try {
      localStorage.setItem('ti.product', id)
    } catch {
      /* ignore */
    }
  },
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#12305a" />
        <circle cx="16" cy="16" r="8.5" fill="none" stroke="#2DD4BF" strokeWidth="2.2" />
        <path d="M7.5 16h17M16 7.5c3 3.2 3 13.8 0 17M16 7.5c-3 3.2-3 13.8 0 17" fill="none" stroke="#2DD4BF" strokeWidth="1.6" />
      </svg>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-white">TradeScope</div>
        <div className="text-[11px] text-slate-400">Trade intelligence</div>
      </div>
    </div>
  )
}

function Item({ to, icon, children, end }: { to: string; icon: ReactNode; children: ReactNode; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx(
          'flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors',
          isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white',
        )
      }
    >
      <span className="[&>svg]:size-4.5">{icon}</span>
      {children}
    </NavLink>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user, can, logout } = useAuth()
  const [pwOpen, setPwOpen] = useState(false)
  const productId = useMatch('/p/:productId/*')?.params.productId ?? lastProduct.get()
  useEffect(() => {
    if (productId) lastProduct.set(productId)
  }, [productId])
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products') })
  const current = products.data?.find((p) => String(p.id) === productId) ?? products.data?.[0]
  const base = current ? `/p/${current.id}` : null

  return (
    <nav className="flex h-full flex-col gap-6 bg-ink-900 px-3 py-5" onClick={(e) => (e.target as HTMLElement).closest('a') && onNavigate?.()}>
      <Logo />
      <div className="space-y-1">
        <Item to="/products" icon={<Boxes />}>Product catalogue</Item>
      </div>
      {base && (
        <div>
          <div className="mb-2 px-3 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Workspace</div>
          <div className="mb-2 truncate px-3 text-xs text-brand-200" title={current?.name}>
            {current?.name} · HS {current?.hs_code}
          </div>
          <div className="space-y-1">
            <Item to={`${base}/markets`} icon={<BarChart3 />}>Market intelligence</Item>
            <Item to={`${base}/companies`} icon={<Building2 />}>Companies</Item>
            <Item to={`${base}/analyst`} icon={<Sparkles />}>AI analyst</Item>
            <Item to={`${base}/brief`} icon={<FileText />}>Market brief</Item>
          </div>
        </div>
      )}
      <div>
        <div className="mb-2 px-3 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">Operations</div>
        <div className="space-y-1">
          <Item to="/pipeline" icon={<KanbanSquare />}>Sales pipeline</Item>
          <Item to="/reports" icon={<FileText />}>Reports</Item>
          <Item to="/logistics" icon={<Ship />}>Logistics</Item>
          {can('admin') && <Item to="/admin" icon={<Settings2 />}>Administration</Item>}
        </div>
      </div>
      <div className="mt-auto">
        <Menu.Root>
          <Menu.Trigger className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-white/5">
            <div className="flex size-8 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white">
              {(user?.full_name || user?.email || '?')[0].toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-medium text-white">{user?.full_name || user?.email}</div>
              <div className="text-[11px] text-slate-400 capitalize">{user?.role}</div>
            </div>
            <ChevronDown className="size-4 text-slate-400" />
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Content side="top" align="start" sideOffset={6} className="z-50 w-56 rounded-xl border border-line bg-white p-1 shadow-pop">
              <div className="px-3 py-2 text-xs text-muted">{user?.email}</div>
              <Menu.Item onSelect={() => setPwOpen(true)} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 outline-none data-highlighted:bg-slate-100">
                <KeyRound className="size-4" /> Change password
              </Menu.Item>
              <Menu.Item onSelect={logout} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 outline-none data-highlighted:bg-slate-100">
                <LogOut className="size-4" /> Sign out
              </Menu.Item>
            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>
        <ChangePassword open={pwOpen} onOpenChange={setPwOpen} />
      </div>
    </nav>
  )
}

export default function Layout() {
  const [open, setOpen] = useState(false)

  return (
    <div className="min-h-screen lg:pl-64">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72">
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
          <button type="button" className="absolute top-4 right-4 rounded-lg bg-white/10 p-2 text-white" onClick={() => setOpen(false)} aria-label="Close menu">
            <X className="size-5" />
          </button>
        </div>
      )}
      <div className="sticky top-0 z-20 flex items-center gap-3 border-b border-line bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
        <button type="button" onClick={() => setOpen(true)} className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-100" aria-label="Open menu">
          <MenuIcon className="size-5" />
        </button>
        <span className="font-semibold">TradeScope</span>
      </div>
      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
        <Outlet />
      </main>
    </div>
  )
}
