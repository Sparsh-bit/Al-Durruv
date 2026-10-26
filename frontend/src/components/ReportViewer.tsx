import { useMutation } from '@tanstack/react-query'
import { FileDown, FileSpreadsheet, ShieldCheck } from 'lucide-react'
import { download } from '../lib/api'
import { dateTime, usd } from '../lib/format'
import type { ReportContent } from '../lib/types'
import { EvidenceList, StatementList } from './Statements'
import { Badge, Button, Card, CardHeader, CountryChip, Notice, SourceLink, Table, td, th } from './ui'

export default function ReportViewer({ id, content }: { id: number; content: ReportContent }) {
  const exp = useMutation({ mutationFn: (fmt: 'pdf' | 'xlsx') => download(`/api/reports/${id}/export?format=${fmt}`) })
  const cited = new Set(content.sections.flatMap((s) => s.statements.flatMap((x) => x.evidence_ids)))
  const v = content.validation
  return (
    <div className="space-y-6">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4 bg-gradient-to-r from-ink-900 to-ink-800 px-6 py-5 text-white">
          <div>
            <h2 className="text-lg font-semibold">{content.title}</h2>
            <p className="mt-1 text-[13px] text-slate-300">
              HS {content.hs_code} · {content.hs_description}
            </p>
            <p className="mt-1 text-xs text-slate-400">Generated {dateTime(content.generated_at)} · {content.model}</p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" icon={<FileDown className="size-4" />} loading={exp.isPending && exp.variables === 'pdf'} onClick={() => exp.mutate('pdf')}>PDF</Button>
            <Button variant="secondary" icon={<FileSpreadsheet className="size-4" />} loading={exp.isPending && exp.variables === 'xlsx'} onClick={() => exp.mutate('xlsx')}>Excel</Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line px-6 py-3 text-[13px]">
          <span className="flex items-center gap-2 text-slate-700"><ShieldCheck className="size-4 text-brand-700" /> Validation</span>
          <span><b className="tabular">{v.statements}</b> statements</span>
          <span className="text-emerald-700"><b className="tabular">{v.exported}</b> exported</span>
          {v.withheld > 0 && <span className="text-red-700"><b className="tabular">{v.withheld}</b> withheld (unsupported number)</span>}
        </div>
        <div className="space-y-7 px-6 py-6">
          {content.sections.map((s) => (
            <section key={s.title}>
              <h3 className="mb-3 text-[15px] font-semibold text-ink-900">{s.title}</h3>
              <StatementList statements={s.statements} evidence={content.evidence} />
            </section>
          ))}
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title="Market ranking (deterministic)" subtitle="Included as Appendix A" />
          <Table>
            <thead>
              <tr><th className={th}>#</th><th className={th}>Market</th><th className={`${th} text-right`}>Score</th><th className={`${th} text-right`}>Imports</th></tr>
            </thead>
            <tbody>
              {content.ranking.slice(0, 10).map((r) => (
                <tr key={r.iso3 + r.rank}>
                  <td className={`${td} tabular text-muted`}>{r.rank}</td>
                  <td className={td}><span className="flex items-center gap-2"><CountryChip iso3={r.iso3} /> {r.name}</span></td>
                  <td className={`${td} tabular text-right font-semibold`}>{r.score.toFixed(1)}</td>
                  <td className={`${td} tabular text-right`}>{usd(r.latest_value_usd)} <span className="text-xs text-muted">{r.latest_year}</span></td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card>
          <CardHeader title="Companies" subtitle="Included as Appendix B" />
          {content.companies.length === 0 ? (
            <div className="p-5"><Notice>No companies researched for this product when the brief was generated.</Notice></div>
          ) : (
            <ul className="divide-y divide-line">
              {content.companies.slice(0, 12).map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                  <span className="flex min-w-0 items-center gap-2"><CountryChip iso3={c.country_iso3} /><span className="truncate">{c.name}</span></span>
                  <span className="flex shrink-0 items-center gap-2">
                    {c.evidence[0] && <SourceLink source={c.evidence[0].source} compact />}
                    <Badge tone={c.review_status === 'verified' ? 'green' : 'amber'} className="capitalize">{c.review_status}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card>
        <CardHeader title="Evidence and sources" subtitle="Appendix C · every cited fact with its source" />
        <div className="p-4"><EvidenceList evidence={content.evidence.filter((e) => cited.has(e.id))} /></div>
      </Card>
    </div>
  )
}
