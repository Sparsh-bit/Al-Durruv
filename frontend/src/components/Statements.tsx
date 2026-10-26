import clsx from 'clsx'
import { AlertTriangle } from 'lucide-react'
import type { Evidence, Statement } from '../lib/types'
import { LabelBadge, SourceLink, Tip } from './ui'

export function EvidenceChip({ id, evidence }: { id: string; evidence?: Evidence }) {
  return (
    <Tip
      content={
        evidence ? (
          <div className="space-y-1">
            <div className="font-semibold text-brand-200">{id} · {evidence.kind.replace('_', ' ')}</div>
            <div>{evidence.text}</div>
            {evidence.source && <div className="text-slate-400">Source: {evidence.source.url}</div>}
          </div>
        ) : (
          id
        )
      }
    >
      <a
        href={`#ev-${id}`}
        className="ml-1 inline-flex h-4.5 items-center rounded bg-ink-900/[0.06] px-1 align-[1px] font-mono text-[10.5px] font-semibold text-ink-700 hover:bg-brand-100"
      >
        {id}
      </a>
    </Tip>
  )
}

export function StatementList({ statements, evidence }: { statements: Statement[]; evidence: Evidence[] }) {
  const byId = new Map(evidence.map((e) => [e.id, e]))
  return (
    <ul className="space-y-2.5">
      {statements.map((s, i) => (
        <li key={i} className={clsx('flex gap-3', s.label === 'unverified' && 'rounded-lg bg-red-50/70 p-2')}>
          <div className="w-24 shrink-0 pt-0.5"><LabelBadge label={s.label} /></div>
          <div className="min-w-0 text-[14px] leading-relaxed text-slate-800">
            <span className={clsx(s.label === 'unverified' && 'text-red-900')}>{s.text}</span>
            {s.evidence_ids.map((id) => <EvidenceChip key={id} id={id} evidence={byId.get(id)} />)}
            {s.issues.some((x) => x.startsWith('unsupported_number')) && (
              <div className="mt-1 flex items-center gap-1.5 text-xs text-red-700">
                <AlertTriangle className="size-3.5" /> A number in this statement does not match its cited evidence. It is excluded from client exports.
              </div>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  return (
    <ol className="space-y-2">
      {evidence.map((e) => (
        <li key={e.id} id={`ev-${e.id}`} className="scroll-mt-24 rounded-lg border border-line bg-white px-3 py-2 text-[13px] target:ring-2 target:ring-brand-200">
          <div className="flex gap-2">
            <span className="font-mono text-[11px] font-semibold text-ink-700">{e.id}</span>
            <span className="text-slate-700">{e.text}</span>
          </div>
          {e.source?.url && <div className="mt-1 pl-7"><SourceLink source={e.source} /></div>}
        </li>
      ))}
    </ol>
  )
}
