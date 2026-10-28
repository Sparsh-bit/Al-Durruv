import * as Dialog from '@radix-ui/react-dialog'
import * as Menu from '@radix-ui/react-dropdown-menu'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ArrowUpRight,
  BarChart3,
  Bell,
  Calculator,
  DatabaseZap,
  Languages,
  UserSearch,
  Boxes,
  Building2,
  ChevronDown,
  CircleHelp,
  FileText,
  Gauge,
  Globe2,
  KanbanSquare,
  KeyRound,
  LineChart,
  LogOut,
  Menu as MenuIcon,
  PlugZap,
  Search,
  Settings2,
  Ship,
  Sparkles,
  Store,
  Tags,
  X,
} from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useMatch, useNavigate } from 'react-router'
import { api, patch } from '../lib/api'
import { useAuth } from '../lib/auth'
import { slideTo } from '../lib/motion'
import type { AlertItem, AppSettings, Company, Product, User } from '../lib/types'
import { ClientMark, PoweredBy } from './Brand'
import ChangePassword from './ChangePassword'

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

function useClient() {
  const q = useQuery({ queryKey: ['settings'], queryFn: () => api<AppSettings>('/api/admin/settings'), staleTime: 300_000 })
  return q.data?.company_profile
}

function Item({ to, icon, children, end }: { to: string; icon: ReactNode; children: ReactNode; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx(
          'relative flex items-center gap-3 rounded-[9px] px-3 py-[7px] text-[13.5px] transition-colors',
          isActive ? 'bg-fog font-medium text-ink-900' : 'text-body hover:bg-paper hover:text-ink-900',
        )
      }
    >
      <span className="text-muted [&>svg]:size-[17px] [&>svg]:stroke-[1.75]">{icon}</span>
      <span className="truncate">{children}</span>
    </NavLink>
  )
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="micro mb-1.5 px-3 text-muted/80">{label}</div>
      <div className="space-y-px">{children}</div>
    </div>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { can } = useAuth()
  const client = useClient()
  const location = useLocation()
  const productId = useMatch('/p/:productId/*')?.params.productId ?? lastProduct.get()
  useEffect(() => {
    if (productId) lastProduct.set(productId)
  }, [productId])
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products') })
  const withHs = products.data?.filter((p) => p.hs_code)
  const current = withHs?.find((p) => String(p.id) === productId) ?? withHs?.[0]
  const base = current ? `/p/${current.id}` : null
  const navRef = useRef<HTMLDivElement>(null)
  const barRef = useRef<HTMLSpanElement>(null)

  useLayoutEffect(() => {
    const active = navRef.current?.querySelector<HTMLElement>('a[aria-current="page"]') ?? null
    slideTo(barRef.current, active)
  }, [location.pathname, base])

  return (
    <nav className="flex h-full flex-col border-r border-line bg-white" onClick={(e) => (e.target as HTMLElement).closest('a') && onNavigate?.()}>
      <div className="flex items-center gap-3 px-5 pt-5 pb-4">
        <ClientMark brand={client?.brand || client?.name || ''} className="size-9 text-[17px]" />
        <div className="min-w-0 leading-tight">
          <div className="truncate font-display text-[15.5px] font-semibold text-ink-900">{client?.brand || client?.name || 'Workspace'}</div>
          <div className="micro mt-0.5 text-muted">Trade intelligence</div>
        </div>
      </div>

      <div ref={navRef} className="relative flex-1 space-y-5 overflow-y-auto px-3 pt-2 pb-4">
        <span ref={barRef} className="pointer-events-none absolute left-1 w-[3px] rounded-full bg-brand-500 opacity-0" style={{ top: 0 }} aria-hidden />
        <Group label="Command">
          <Item to="/" end icon={<Gauge />}>Overview</Item>
          <Item to="/products" icon={<Boxes />}>Products &amp; HS codes</Item>
        </Group>
        {base && (
          <Group label="Product workspace">
            <div className="mx-3 mb-1.5 truncate rounded-[7px] border border-line-soft bg-paper px-2 py-1 text-[11.5px] text-body" title={current?.name}>
              <span className="num text-brand-700">{current?.hs_code}</span> · {current?.name}
            </div>
            <Item to={`${base}/markets`} icon={<BarChart3 />}>Market intelligence</Item>
            <Item to={`${base}/companies`} icon={<Building2 />}>Buyers &amp; competitors</Item>
            <Item to={`${base}/analyst`} icon={<Sparkles />}>AI advisor</Item>
            <Item to={`${base}/brief`} icon={<FileText />}>Market brief</Item>
          </Group>
        )}
        <Group label="Markets">
          <Item to="/explorer" icon={<LineChart />}>Trade explorer</Item>
          <Item to="/markets" icon={<Globe2 />}>Markets &amp; regions</Item>
          <Item to="/access" icon={<Calculator />}>Landed cost</Item>
          <Item to="/opportunities" icon={<Tags />}>Private-label engine</Item>
        </Group>
        <Group label="Accounts">
          <Item to="/buyers" icon={<UserSearch />}>Buyer finder</Item>
          <Item to="/accounts" icon={<Store />}>Retailers &amp; competitors</Item>
          <Item to="/pipeline" icon={<KanbanSquare />}>CRM pipeline</Item>
          <Item to="/alerts" icon={<Bell />}>Alerts</Item>
        </Group>
        <Group label="Client &amp; system">
          <Item to="/client" icon={<CircleHelp />}>Questions &amp; entities</Item>
          <Item to="/reports" icon={<FileText />}>AI reports</Item>
          <Item to="/logistics" icon={<Ship />}>Logistics</Item>
          <Item to="/integrations" icon={<PlugZap />}>Integration health</Item>
          {can('admin') && <Item to="/data" icon={<DatabaseZap />}>Data admin</Item>}
          {can('admin') && <Item to="/admin" icon={<Settings2 />}>Administration</Item>}
        </Group>
      </div>
      <div className="border-t border-line-soft px-5 py-3.5">
        <PoweredBy />
      </div>
    </nav>
  )
}

function SearchPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [q, setQ] = useState('')
  const navigate = useNavigate()
  const products = useQuery({ queryKey: ['products'], queryFn: () => api<Product[]>('/api/products'), enabled: open })
  const companies = useQuery({ queryKey: ['companies-all'], queryFn: () => api<Company[]>('/api/companies'), enabled: open })
  const results = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (t.length < 2) return []
    const ps = (products.data ?? [])
      .filter((p) => `${p.name} ${p.name_ar} ${p.sku} ${p.hs_code ?? ''} ${p.client_hs_code} ${p.category}`.toLowerCase().includes(t))
      .slice(0, 7)
      .map((p) => ({ key: `p${p.id}`, title: p.name, meta: `${p.sku} · HS ${p.hs_code ?? '—'}${p.client_hs_code ? ` · client ${p.client_hs_code}` : ''}`, kind: 'Product', to: p.hs_code ? `/p/${p.id}/markets` : '/products' }))
    const cs = (companies.data ?? [])
      .filter((c) => `${c.name} ${c.country_name} ${c.website}`.toLowerCase().includes(t))
      .slice(0, 6)
      .map((c) => ({ key: `c${c.id}`, title: c.name, meta: `${c.relationship_type} · ${c.country_name || c.country_iso3 || 'country unknown'}`, kind: 'Company', to: ['retailer', 'competitor'].includes(c.relationship_type) ? '/accounts' : '/pipeline' }))
    return [...ps, ...cs]
  }, [q, products.data, companies.data])
  const go = (to: string) => {
    onOpenChange(false)
    setQ('')
    navigate(to)
  }
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-950/30" />
        <Dialog.Content aria-describedby={undefined} className="fixed top-[12vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-[16px] border border-line bg-white shadow-pop">
          <Dialog.Title className="sr-only">Search</Dialog.Title>
          <div className="flex items-center gap-3 border-b border-line px-4">
            <Search className="size-4 text-muted" />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && results[0] && go(results[0].to)}
              placeholder="Search products, HS codes, client codes, companies…"
              className="h-13 flex-1 bg-transparent text-[14.5px] text-ink-900 outline-none placeholder:text-muted/70"
              aria-label="Search"
            />
            <kbd className="micro rounded border border-line px-1.5 py-0.5 text-muted">esc</kbd>
          </div>
          <ul className="max-h-[50vh] overflow-y-auto p-1.5">
            {q.trim().length < 2 ? (
              <li className="px-3 py-6 text-center text-[13px] text-muted">Type at least two characters.</li>
            ) : results.length === 0 ? (
              <li className="px-3 py-6 text-center text-[13px] text-muted">No matches for “{q}”.</li>
            ) : (
              results.map((r) => (
                <li key={r.key}>
                  <button type="button" onClick={() => go(r.to)} className="flex w-full items-center gap-3 rounded-[9px] px-3 py-2.5 text-left hover:bg-fog">
                    <span className="micro w-16 shrink-0 text-muted">{r.kind}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-medium text-ink-900">{r.title}</span>
                      <span className="block truncate text-[12px] text-muted">{r.meta}</span>
                    </span>
                    <ArrowUpRight className="size-4 text-muted" />
                  </button>
                </li>
              ))
            )}
          </ul>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function AlertBell() {
  const navigate = useNavigate()
  const unread = useQuery({ queryKey: ['alerts', 'unread'], queryFn: () => api<AlertItem[]>('/api/alerts?unread=true'), refetchInterval: 120_000 })
  const n = unread.data?.length ?? 0
  return (
    <button type="button" onClick={() => navigate('/alerts')} className="relative rounded-[9px] p-2 text-body hover:bg-fog" aria-label={`Alerts${n ? `, ${n} unread` : ''}`}>
      <Bell className="size-[18px]" />
      {n > 0 && <span className="num absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-ink-900 px-1 text-center text-[10px] leading-4 text-white">{n > 99 ? '99+' : n}</span>}
    </button>
  )
}

function TopBar({ onMenu, onSearch }: { onMenu: () => void; onSearch: () => void }) {
  const { user, logout, refresh } = useAuth()
  const setLanguage = async (language: 'en' | 'ar') => {
    await patch<User>('/api/auth/me', { language })
    await refresh()
  }
  const [pwOpen, setPwOpen] = useState(false)
  const client = useClient()
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-canvas/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-3 px-4 sm:px-6 lg:px-10">
        <button type="button" onClick={onMenu} className="rounded-[8px] p-1.5 text-body hover:bg-fog lg:hidden" aria-label="Open menu">
          <MenuIcon className="size-5" />
        </button>
        <div className="hidden min-w-0 text-[12.5px] text-muted md:block">
          <span className="truncate">{client?.name}</span>
        </div>
        <button
          type="button"
          onClick={onSearch}
          className="ml-auto flex h-9 w-full max-w-xs items-center gap-2 rounded-[9px] border border-line bg-white px-3 text-[13px] text-muted transition-colors hover:border-ink-900/20"
        >
          <Search className="size-4" /> <span className="flex-1 text-left">Search</span>
          <kbd className="micro rounded border border-line px-1.5 py-0.5">⌘K</kbd>
        </button>
        <AlertBell />
        <Menu.Root>
          <Menu.Trigger className="flex items-center gap-2 rounded-[9px] py-1 pr-1.5 pl-1 hover:bg-fog" aria-label="Account menu">
            <span className="flex size-7.5 items-center justify-center rounded-full bg-brand-100 text-[12.5px] font-semibold text-brand-700">
              {(user?.full_name || user?.email || '?')[0].toUpperCase()}
            </span>
            <span className="hidden text-left leading-tight sm:block">
              <span className="block max-w-36 truncate text-[12.5px] font-medium text-ink-900">{user?.full_name || user?.email}</span>
              <span className="micro block text-muted">{user?.role}</span>
            </span>
            <ChevronDown className="size-3.5 text-muted" />
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Content align="end" sideOffset={6} className="z-50 w-56 rounded-[12px] border border-line bg-white p-1 shadow-pop">
              <div className="px-3 py-2 text-xs text-muted">{user?.email}</div>
              <Menu.Item onSelect={() => setLanguage(user?.language === 'ar' ? 'en' : 'ar')} className="flex cursor-pointer items-center gap-2 rounded-[8px] px-3 py-2 text-[13px] text-ink-800 outline-none data-highlighted:bg-fog">
                <Languages className="size-4" /> AI output: {user?.language === 'ar' ? 'العربية (switch to English)' : 'English (switch to Arabic)'}
              </Menu.Item>
              <Menu.Item onSelect={() => setPwOpen(true)} className="flex cursor-pointer items-center gap-2 rounded-[8px] px-3 py-2 text-[13px] text-ink-800 outline-none data-highlighted:bg-fog">
                <KeyRound className="size-4" /> Change password
              </Menu.Item>
              <Menu.Item onSelect={logout} className="flex cursor-pointer items-center gap-2 rounded-[8px] px-3 py-2 text-[13px] text-ink-800 outline-none data-highlighted:bg-fog">
                <LogOut className="size-4" /> Sign out
              </Menu.Item>
            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>
        <ChangePassword open={pwOpen} onOpenChange={setPwOpen} />
      </div>
    </header>
  )
}

export default function Layout() {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearch(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="min-h-screen lg:pl-[260px]">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[260px] lg:block">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/35" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-[280px] shadow-pop">
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
          <button type="button" className="absolute top-4 right-4 rounded-[9px] bg-white p-2 text-ink-900 shadow-lift" onClick={() => setOpen(false)} aria-label="Close menu">
            <X className="size-5" />
          </button>
        </div>
      )}
      <TopBar onMenu={() => setOpen(true)} onSearch={() => setSearch(true)} />
      <SearchPalette open={search} onOpenChange={setSearch} />
      <main className="mx-auto max-w-[1440px] px-4 py-7 sm:px-6 lg:px-10 lg:py-9">
        <Outlet />
      </main>
      <footer className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-5 text-[11.5px] text-muted sm:px-6 lg:px-10">
        <span>Figures cite their source. Unverified items are labelled as such.</span>
        <PoweredBy />
      </footer>
    </div>
  )
}
