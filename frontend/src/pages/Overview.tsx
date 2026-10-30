import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CalendarClock } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { BorderBeam } from '../components/lightswind/border-beam'
import { CountUp } from '../components/lightswind/count-up'
import { Badge, Card, Notice, PageHeader, SectionTitle, Skeleton, StatusDot } from '../components/ui'
import { api } from '../lib/api'
import { date, dateTime } from '../lib/format'
import { ALERT_LABEL, HS_STATUS, RELATIONSHIP_LABEL, STAGES } from '../lib/labels'
import { useReveal } from '../lib/motion'
import type { AlertItem, AppSettings, BuyersResult, HsStatus, OverviewData, Provider, SourceFreshness } from '../lib/types'

const HS_BAR: Record<HsStatus, string> = {
  confirmed: 'bg-emerald-500',
  candidate: 'bg-amber-400',
  discrepancy: 'bg-orange-500',
  insufficient_info: 'bg-red-400',
  unmapped: 'bg-slate-300',
}
const TOPIC: Record<string, string> = {
  hs: 'HS classification',
  product: 'Products',
  entity: 'Entities',
  market: 'Markets',
  competitor: 'Competitors',
  account: 'Retail accounts',
  general: 'General',
}

function Kpi({ label, value, hint, to }: { label: string; value: number; hint: string; to: string }) {
  return (
    <Link to={to} data-reveal className="group relative block rounded-[14px] border border-line bg-white p-5 transition-shadow hover:shadow-lift">
      <div className="micro text-muted">{label}</div>
      <CountUp value={value} duration={1.1} className="num mt-3 text-[30px] leading-none font-medium text-ink-900" numberClassName="font-medium" />
      <div className="mt-2 flex items-center justify-between gap-2 text-[12px] text-muted">
        <span className="truncate">{hint}</span>
        <ArrowRight className="size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
    </Link>
  )
}

export default function Overview() {
  const ov = useQuery({ queryKey: ['overview-dash'], queryFn: () => api<OverviewData>('/api/overview') })
  const sources = useQuery({ queryKey: ['sources'], queryFn: () => api<(Provider & { last_run?: { status: string; finished_at: string | null } | null })[]>('/api/admin/sources') })
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<AppSettings>('/api/admin/settings') })
  const fresh = useQuery({ queryKey: ['freshness'], queryFn: () => api<{ sources: SourceFreshness[] }>('/api/admin/freshness') })
  const alerts = useQuery({ queryKey: ['alerts', 'unread'], queryFn: () => api<AlertItem[]>('/api/alerts?unread=true') })
  const buyers = useQuery({ queryKey: ['buyers', ''], queryFn: () => api<BuyersResult>('/api/buyers') })
  const ref = useReveal<HTMLDivElement>([ov.isSuccess])
  const [today] = useState(() => new Date().toLocaleDateString('en-CA'))
  const d = ov.data

  if (ov.isError) return <Notice tone="error">{ov.error.message}</Notice>
  if (!d) return <div className="grid gap-4 sm:grid-cols-3">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-32" />)}</div>

  const total = d.products.total || 1
  const openQ = Object.values(d.clarifications_open).reduce((a, b) => a + b, 0)
  const retail = d.accounts.filter((a) => a.relationship === 'retailer').reduce((n, a) => n + a.count, 0)
  const byRel = (['retailer', 'buyer', 'competitor'] as const).map((rel) => ({
    rel,
    stages: STAGES.map((s) => ({ ...s, count: d.accounts.find((a) => a.relationship === rel && a.stage === s.key)?.count ?? 0 })),
  }))
  const priorities = settings.data?.priority_categories ?? Object.keys(d.products.priority)
  const markets = (d.target_markets.existing ?? 0) + (d.target_markets.expansion ?? 0)

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow={settings.data?.company_profile.name || 'Overview'}
        title="Trade intelligence overview"
        subtitle={
          <>
            Data freshness: trade figures loaded for <b className="text-ink-900">{d.trade.loaded_hs}</b> of {d.trade.catalogue_hs} HS codes
            {d.trade.latest_year && <> · latest reported year <b className="text-ink-900">{d.trade.latest_year}</b></>}
            {d.trade.oldest_retrieval && <> · oldest retrieval {date(d.trade.oldest_retrieval)}</>}.
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Products" value={d.products.total} hint={`${d.products.with_client_code} carry a client HS code`} to="/products" />
        <Kpi label="HS codes confirmed" value={d.products.by_hs_status.confirmed} hint={`${d.products.by_hs_status.candidate + d.products.by_hs_status.discrepancy + d.products.by_hs_status.insufficient_info} need review`} to="/products" />
        <Kpi label="Retail accounts" value={retail} hint="Priority retailers tracked" to="/accounts" />
        <Kpi label="Open client questions" value={openQ} hint="Answers recorded, never assumed" to="/client" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card className="p-5">
          <SectionTitle title="Data freshness" hint="per source" action={<Link to="/data" className="text-[12.5px] font-medium text-brand-700 hover:underline">Data admin</Link>} />
          <ul className="space-y-2">
            {(fresh.data?.sources ?? []).map((src) => (
              <li key={src.key} className="flex items-start justify-between gap-3 text-[12.5px]">
                <span className="min-w-0">
                  <span className="block truncate text-ink-900">{src.name}</span>
                  <span className="text-muted">{src.latest_period ? `to ${src.latest_period} · ` : ''}{src.last_retrieved ? date(src.last_retrieved) : src.needs ? `needs ${src.needs}` : 'not loaded'}</span>
                </span>
                <span className="flex shrink-0 gap-1">
                  {src.stale && <Badge tone="red">stale</Badge>}
                  <Badge tone={src.confidence === 'official' ? 'green' : src.confidence === 'licensed' ? 'blue' : 'amber'}>{src.confidence}</Badge>
                </span>
              </li>
            ))}
          </ul>
        </Card>
        <Card className="p-5">
          <SectionTitle title="New alerts" action={<Link to="/alerts" className="text-[12.5px] font-medium text-brand-700 hover:underline">All alerts</Link>} />
          {(alerts.data ?? []).length === 0 ? (
            <p className="text-[13px] text-muted">No unread alerts.</p>
          ) : (
            <ul className="space-y-2">
              {alerts.data!.slice(0, 6).map((a) => (
                <li key={a.id} className="text-[12.5px]">
                  <Badge tone={(ALERT_LABEL[a.type] ?? { tone: 'blue' }).tone}>{(ALERT_LABEL[a.type] ?? { text: a.type }).text}</Badge>
                  <span className="ml-2 text-ink-900">{a.title}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-5">
          <SectionTitle title="Top-scored buyers" action={<Link to="/buyers" className="text-[12.5px] font-medium text-brand-700 hover:underline">Buyer finder</Link>} />
          {(buyers.data?.buyers ?? []).length === 0 ? (
            <p className="text-[13px] text-muted">No shipment records uploaded yet.</p>
          ) : (
            <ul className="divide-y divide-line-soft">
              {buyers.data!.buyers.slice(0, 6).map((b) => (
                <li key={b.company.id} className="flex items-center justify-between gap-3 py-2 text-[13px]">
                  <span className="truncate text-ink-900">{b.company.name} <span className="num text-[11px] text-muted">{b.company.country_iso3}</span></span>
                  <span className="num text-ink-900">{b.score?.toFixed(0) ?? '—'}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-9 grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        <Card className="relative overflow-hidden p-5" >
          {d.products.by_hs_status.confirmed === 0 && <BorderBeam size={90} duration={9} colorFrom="#5fc4be" colorTo="#20736e" />}
          <SectionTitle index="01" title="HS verification" hint="client codes preserved; analysis HS6 reviewed" action={<Link to="/products" className="text-[12.5px] font-medium text-brand-700 hover:underline">Review codes</Link>} />
          <div className="flex h-2.5 overflow-hidden rounded-full bg-fog" role="img" aria-label="HS status breakdown">
            {(Object.keys(HS_BAR) as HsStatus[]).map((s) => (
              <span key={s} className={HS_BAR[s]} style={{ width: `${(d.products.by_hs_status[s] / total) * 100}%` }} />
            ))}
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            {(Object.keys(HS_BAR) as HsStatus[]).map((s) => (
              <div key={s}>
                <dt className="flex items-center gap-1.5 text-[12px] text-muted"><span className={`size-2 rounded-full ${HS_BAR[s]}`} />{HS_STATUS[s].text}</dt>
                <dd className="num mt-1 text-[20px] text-ink-900">{d.products.by_hs_status[s]}</dd>
              </div>
            ))}
          </dl>
          {d.products.by_hs_status.confirmed === 0 && (
            <p className="mt-4 text-[12.5px] leading-relaxed text-body">
              No code is customs-confirmed yet. Market figures use candidate HS6 codes until the client or a broker confirms them.
            </p>
          )}
        </Card>

        <Card className="p-5">
          <SectionTitle index="02" title="Priority categories" action={<Link to="/opportunities" className="text-[12.5px] font-medium text-brand-700 hover:underline">Opportunity engine</Link>} />
          <ul className="divide-y divide-line-soft">
            {priorities.map((c) => (
              <li key={c} className="flex items-center justify-between py-2 text-[13.5px]" data-reveal>
                <span className="text-ink-900">{c}</span>
                <span className="num text-[12.5px] text-muted">{d.products.priority[c] ?? 0} products</span>
              </li>
            ))}
            {priorities.length === 0 && <li className="py-3 text-[13px] text-muted">No priority categories configured.</li>}
          </ul>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <SectionTitle index="03" title="CRM pipeline" hint="by account type and outreach stage" action={<Link to="/pipeline" className="text-[12.5px] font-medium text-brand-700 hover:underline">Open pipeline</Link>} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[13px]">
              <thead>
                <tr>
                  <th className="micro py-2 text-left font-medium text-muted" />
                  {STAGES.map((s) => <th key={s.key} className="micro py-2 text-right font-medium text-muted">{s.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {byRel.map(({ rel, stages }) => (
                  <tr key={rel} className="border-t border-line-soft">
                    <td className="py-2.5 text-ink-900">{RELATIONSHIP_LABEL[rel]}</td>
                    {stages.map((s) => (
                      <td key={s.key} className={`num py-2.5 text-right ${s.count ? 'text-ink-900' : 'text-muted/50'}`}>{s.count}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[12px] text-muted">Stages change only when someone records them. The platform never marks an account as contacted by itself.</p>
        </Card>

        <Card className="p-5">
          <SectionTitle index="04" title="Follow-ups" />
          {d.follow_ups.length === 0 ? (
            <p className="text-[13px] text-muted">No follow-up dates set. Add one on an account.</p>
          ) : (
            <ul className="space-y-2.5">
              {d.follow_ups.map((f) => {
                const overdue = f.follow_up_on < today
                return (
                  <li key={f.id} className="flex gap-3 text-[13px]">
                    <CalendarClock className={`mt-0.5 size-4 shrink-0 ${overdue ? 'text-red-600' : 'text-muted'}`} />
                    <div className="min-w-0">
                      <div className="font-medium text-ink-900">{f.name}</div>
                      <div className="text-muted">{date(f.follow_up_on)}{f.next_action && ` · ${f.next_action}`}</div>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card className="p-5">
          <SectionTitle index="05" title="Client clarifications" action={<Link to="/client" className="text-[12.5px] font-medium text-brand-700 hover:underline">Answer</Link>} />
          {openQ === 0 ? (
            <p className="text-[13px] text-muted">No open questions.</p>
          ) : (
            <ul className="divide-y divide-line-soft">
              {Object.entries(d.clarifications_open).sort((a, b) => b[1] - a[1]).map(([topic, n]) => (
                <li key={topic} className="flex items-center justify-between py-2 text-[13.5px]">
                  <span>{TOPIC[topic] ?? topic}</span>
                  <Badge tone="amber">{n} open</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-5">
          <SectionTitle index="06" title="Markets & entities" action={<Link to="/markets" className="text-[12.5px] font-medium text-brand-700 hover:underline">Manage</Link>} />
          <dl className="grid grid-cols-2 gap-4">
            <div><dt className="micro text-muted">Existing markets</dt><dd className="num mt-1 text-[22px]">{d.target_markets.existing ?? 0}</dd></div>
            <div><dt className="micro text-muted">Expansion markets</dt><dd className="num mt-1 text-[22px]">{d.target_markets.expansion ?? 0}</dd></div>
            <div><dt className="micro text-muted">Entities pending</dt><dd className="num mt-1 text-[22px]">{d.entities.pending_verification ?? 0}</dd></div>
            <div><dt className="micro text-muted">Entities verified</dt><dd className="num mt-1 text-[22px]">{d.entities.verified ?? 0}</dd></div>
          </dl>
          {markets === 0 && <p className="mt-4 text-[12.5px] text-amber-800">Your country list has not been imported yet.</p>}
        </Card>
        <Card className="p-5">
          <SectionTitle index="07" title="Integration health" action={<Link to="/integrations" className="text-[12.5px] font-medium text-brand-700 hover:underline">Details</Link>} />
          <ul className="space-y-2.5">
            {(sources.data ?? []).map((s) => (
              <li key={s.key} className="flex items-start justify-between gap-3 text-[13px]">
                <span className="min-w-0 truncate text-ink-900" title={s.name}>{s.name.split(' (')[0]}</span>
                <StatusDot tone={s.status === 'connected' ? 'green' : s.status === 'not_configured' ? 'red' : 'amber'}>
                  {s.status === 'connected' ? 'Connected' : s.status === 'not_configured' ? 'Not configured' : 'Not connected'}
                </StatusDot>
              </li>
            ))}
          </ul>
          {d.trade.last_run && (
            <p className="mt-4 text-[12px] text-muted">
              Last data refresh: {d.trade.last_run.scope} · {d.trade.last_run.status} · {dateTime(d.trade.last_run.finished_at ?? d.trade.last_run.started_at)}
            </p>
          )}
        </Card>
      </div>
    </div>
  )
}
