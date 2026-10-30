import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import ReportViewer from '../components/ReportViewer'
import { Button, Card, EmptyState, Notice, Select, Skeleton, Spinner } from '../components/ui'
import { WorkspaceHeader } from '../components/Workspace'
import { api, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime } from '../lib/format'
import { useOverview, useProduct } from '../lib/hooks'
import type { ReportContent, ReportSummary } from '../lib/types'

export default function Brief() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const product = useProduct()
  const hs = product.data?.hs_code
  const overview = useOverview(hs)
  const hasData = overview.data?.has_data
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<{ ai_enabled: boolean }>('/api/health'), staleTime: 300_000 })
  const reports = useQuery({ queryKey: ['reports'], queryFn: () => api<ReportSummary[]>('/api/reports') })
  const mine = (reports.data ?? []).filter((r) => r.product_id === product.data?.id)
  const [picked, setPicked] = useState<number | null>(null)
  const selectedId = picked ?? mine[0]?.id ?? null
  const report = useQuery({
    queryKey: ['report', selectedId],
    queryFn: () => api<ReportSummary & { content: ReportContent }>(`/api/reports/${selectedId}`),
    enabled: selectedId !== null,
  })
  const generate = useMutation({
    mutationFn: () => post<ReportSummary & { content: ReportContent }>('/api/reports', { product_id: product.data!.id }),
    onSuccess: (r) => {
      qc.setQueryData(['report', r.id], r)
      qc.invalidateQueries({ queryKey: ['reports'] })
      setPicked(r.id)
      toast.success('Brief generated')
    },
  })
  const aiOff = health.data?.ai_enabled === false

  return (
    <>
      <WorkspaceHeader
        product={product.data}
        hasData={hasData}
        title="Market & prospect brief"
        subtitle="An AI-written brief for sales negotiations, grounded in the data above. Every statement carries a label and evidence; failed checks are withheld from exports."
        actions={
          <>
            {mine.length > 1 && (
              <Select className="w-auto!" value={selectedId ?? ''} onChange={(e) => setPicked(Number(e.target.value))} aria-label="Select version">
                {mine.map((r) => <option key={r.id} value={r.id}>{dateTime(r.created_at)}</option>)}
              </Select>
            )}
            {can('analyst') && (
              <Button icon={<Sparkles className="size-4" />} loading={generate.isPending} disabled={!hasData || aiOff} onClick={() => generate.mutate()}>
                {mine.length ? 'Generate new version' : 'Generate brief'}
              </Button>
            )}
          </>
        }
      />
      {aiOff && <div className="mb-6"><Notice tone="warn" title="AI is not configured">Ask your administrator to turn on AI.</Notice></div>}
      {overview.data && !hasData && <div className="mb-6"><Notice tone="warn" title="Load trade data first">A brief needs trade statistics. Load data on the Market intelligence step.</Notice></div>}
      {generate.isPending ? (
        <Card>
          <EmptyState icon={<Spinner className="size-6" />} title="Writing the brief…">
            Building the evidence pack, drafting and checking every statement. This usually takes under a minute.
          </EmptyState>
        </Card>
      ) : report.data ? (
        <ReportViewer id={report.data.id} content={report.data.content} />
      ) : report.isLoading || reports.isLoading ? (
        <Skeleton className="h-96" />
      ) : (
        <Card>
          <EmptyState icon={<FileText className="size-6" />} title="No brief yet">
            Research a few companies first for a richer brief, then generate it here. You can export it as PDF or Excel for client review.
          </EmptyState>
        </Card>
      )}
    </>
  )
}
