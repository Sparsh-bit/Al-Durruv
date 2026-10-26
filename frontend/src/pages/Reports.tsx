import { useQuery } from '@tanstack/react-query'
import { ArrowRight, FileText } from 'lucide-react'
import { Link } from 'react-router'
import { Badge, Card, EmptyState, Notice, PageHeader, Skeleton, Table, td, th } from '../components/ui'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { ReportSummary } from '../lib/types'

export default function Reports() {
  const reports = useQuery({ queryKey: ['reports'], queryFn: () => api<ReportSummary[]>('/api/reports') })
  return (
    <>
      <PageHeader title="Reports" subtitle="All generated market and prospect briefs. Open one to review or export it." />
      <Card>
        {reports.isLoading ? (
          <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : reports.isError ? (
          <div className="p-5"><Notice tone="error">{reports.error.message}</Notice></div>
        ) : !reports.data?.length ? (
          <EmptyState icon={<FileText className="size-6" />} title="No reports yet">Generate a brief from a product workspace.</EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <th className={th}>Report</th>
                <th className={th}>HS code</th>
                <th className={th}>Validation</th>
                <th className={th}>Created</th>
                <th className={th}><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody>
              {reports.data.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50/60">
                  <td className={`${td} font-medium text-slate-900`}>{r.title}</td>
                  <td className={`${td} font-mono text-[13px]`}>{r.hs_code}</td>
                  <td className={td}>
                    <Badge tone="green">{r.validation.exported} exported</Badge>{' '}
                    {r.validation.withheld > 0 && <Badge tone="red">{r.validation.withheld} withheld</Badge>}
                  </td>
                  <td className={`${td} text-muted`}>{dateTime(r.created_at)}</td>
                  <td className={`${td} text-right`}>
                    <Link to={`/reports/${r.id}`} className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">
                      Open <ArrowRight className="size-3.5" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  )
}
