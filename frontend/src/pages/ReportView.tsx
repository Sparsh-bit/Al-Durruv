import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router'
import ReportViewer from '../components/ReportViewer'
import { Notice, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import type { ReportContent, ReportSummary } from '../lib/types'

export default function ReportView() {
  const { reportId } = useParams()
  const report = useQuery({
    queryKey: ['report', Number(reportId)],
    queryFn: () => api<ReportSummary & { content: ReportContent }>(`/api/reports/${reportId}`),
  })
  return (
    <>
      <Link to="/reports" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-slate-900">
        <ArrowLeft className="size-4" /> All reports
      </Link>
      {report.isError ? (
        <Notice tone="error">{report.error.message}</Notice>
      ) : report.data ? (
        <ReportViewer id={report.data.id} content={report.data.content} />
      ) : (
        <Skeleton className="h-96" />
      )}
    </>
  )
}
