import * as Dialog from '@radix-ui/react-dialog'
import * as Tooltip from '@radix-ui/react-tooltip'
import clsx from 'clsx'
import { AlertTriangle, ExternalLink, Info, Loader2, X } from 'lucide-react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { LABEL_META } from '../lib/labels'
import type { Label } from '../lib/types'
import { dateTime, hostname } from '../lib/format'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-ink-900 text-white hover:bg-ink-700 active:bg-ink-950',
  secondary: 'bg-white text-ink-900 border border-line hover:border-ink-900/25 hover:bg-paper',
  ghost: 'text-body hover:bg-fog hover:text-ink-900',
  danger: 'bg-white text-red-700 border border-red-200 hover:bg-red-50',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex shrink-0 items-center justify-center gap-2 rounded-[9px] font-medium whitespace-nowrap transition-[background-color,border-color,color,transform] duration-150 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 [&>svg]:size-4',
        size === 'sm' ? 'h-8 px-3 text-[13px]' : 'h-9.5 px-4 text-[13.5px]',
        VARIANTS[variant],
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={clsx('min-w-0 rounded-[14px] border border-line bg-white shadow-card', className)}>{children}</section>
}

export function CardHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line-soft px-5 py-4">
      <div className="min-w-0">
        <h2 className="text-[15.5px] font-semibold text-ink-900">{title}</h2>
        {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-x-6 gap-y-4 border-b border-line pb-5">
      <div className="min-w-0">
        {eyebrow && <div className="micro mb-2 flex items-center gap-2 text-brand-700"><span className="h-px w-5 bg-brand-500" />{eyebrow}</div>}
        <h1 className="text-[27px] leading-[1.15] font-semibold text-ink-900 sm:text-[30px]">{title}</h1>
        {subtitle && <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-body">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export function Stat({ label, value, hint, accent }: { label: string; value: ReactNode; hint?: ReactNode; accent?: boolean }) {
  return (
    <Card className={clsx('relative overflow-hidden p-5', accent && 'border-ink-900! bg-ink-900! text-white')}>
      {accent && <span className="absolute inset-x-0 top-0 h-[3px] bg-brand-500" aria-hidden />}
      <div className={clsx('micro', accent ? 'text-brand-200' : 'text-muted')}>{label}</div>
      <div className="num mt-3 text-[26px] leading-none font-medium">{value}</div>
      {hint && <div className={clsx('mt-2 text-xs leading-snug', accent ? 'text-white/65' : 'text-muted')}>{hint}</div>}
    </Card>
  )
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-ink-800">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-xs text-red-600">{error}</span> : hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  )
}

const inputCls =
  'h-9.5 w-full rounded-[9px] border border-line bg-white px-3 text-[13.5px] text-ink-900 placeholder:text-muted/70 transition-colors hover:border-ink-900/20 focus:border-brand-600 focus:ring-3 focus:ring-brand-100 focus:outline-none disabled:bg-fog'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={clsx(inputCls, props.className)} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={clsx(inputCls, 'pr-8', props.className)} />
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={clsx(inputCls, 'h-auto py-2', props.className)} />
}

export function Badge({ tone = 'slate', children, className }: { tone?: 'slate' | 'green' | 'amber' | 'blue' | 'red' | 'teal'; children: ReactNode; className?: string }) {
  const tones = {
    slate: 'bg-fog text-body ring-line',
    green: 'bg-emerald-50 text-emerald-800 ring-emerald-200/80',
    amber: 'bg-amber-50 text-amber-900 ring-amber-200/80',
    blue: 'bg-sky-50 text-sky-900 ring-sky-200/80',
    red: 'bg-red-50 text-red-800 ring-red-200/80',
    teal: 'bg-brand-50 text-brand-700 ring-brand-200',
  }
  return <span className={clsx('inline-flex shrink-0 items-center gap-1 rounded-[6px] px-1.75 py-0.5 text-[11.5px] font-medium whitespace-nowrap ring-1 ring-inset', tones[tone], className)}>{children}</span>
}

export function LabelBadge({ label }: { label: Label }) {
  const m = LABEL_META[label]
  return (
    <Tip content={m.help}>
      <span tabIndex={0}>
        <Badge tone={m.tone}>{m.text}</Badge>
      </span>
    </Tip>
  )
}

export function CountryChip({ iso3 }: { iso3: string }) {
  return <span className="inline-flex h-5 min-w-9 items-center justify-center rounded-[5px] border border-line bg-paper px-1 font-mono text-[10.5px] font-medium text-body">{iso3 || '—'}</span>
}

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <Tooltip.Root delayDuration={150}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content sideOffset={6} className="z-50 max-w-xs rounded-[9px] bg-ink-900 px-3 py-2 text-xs leading-relaxed text-white shadow-pop">
          {content}
          <Tooltip.Arrow className="fill-ink-900" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

export function InfoTip({ content }: { content: ReactNode }) {
  return (
    <Tip content={content}>
      <button type="button" aria-label="More information" className="inline-flex text-muted/70 hover:text-ink-900">
        <Info className="size-3.5" />
      </button>
    </Tip>
  )
}

export function SourceLink({ source, compact }: { source: { url: string; retrieved_at?: string; period?: string }; compact?: boolean }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex max-w-full items-center gap-1 text-xs text-brand-700 hover:text-brand-600 hover:underline"
      title={source.retrieved_at ? `Retrieved ${dateTime(source.retrieved_at)}` : undefined}
    >
      <ExternalLink className="size-3 shrink-0" />
      <span className="truncate">{compact ? hostname(source.url) : hostname(source.url) + (source.period ? ` · ${source.period}` : '')}</span>
    </a>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('size-5 animate-spin text-brand-600', className)} aria-label="Loading" />
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={clsx('relative overflow-hidden rounded-md bg-fog', className)}>
      <div className="absolute inset-0 -translate-x-full animate-[shimmer_1.4s_infinite] bg-gradient-to-r from-transparent via-white/60 to-transparent" />
    </div>
  )
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon && <div className="mb-4 flex size-11 items-center justify-center rounded-full border border-line bg-paper text-ink-700 [&>svg]:size-5">{icon}</div>}
      <h3 className="text-[16px] font-semibold text-ink-900">{title}</h3>
      {children && <div className="mt-1.5 max-w-md text-sm text-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Notice({ tone = 'info', title, children }: { tone?: 'info' | 'warn' | 'error'; title?: string; children: ReactNode }) {
  const t = {
    info: 'border-line border-l-brand-600 bg-white text-ink-900',
    warn: 'border-amber-200 border-l-amber-500 bg-amber-50/70 text-amber-950',
    error: 'border-red-200 border-l-red-600 bg-red-50/70 text-red-950',
  }[tone]
  const Icon = tone === 'info' ? Info : AlertTriangle
  return (
    <div className={clsx('flex gap-3 rounded-[10px] border border-l-[3px] px-4 py-3 text-[13.5px] leading-relaxed', t)} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        {title && <div className="font-medium">{title}</div>}
        <div className={clsx(title && 'mt-0.5 opacity-90')}>{children}</div>
      </div>
    </div>
  )
}

export function Modal({ open, onOpenChange, title, description, children, wide }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: string
  description?: string
  children: ReactNode
  wide?: boolean
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-950/35" />
        <Dialog.Content
          className={clsx(
            'fixed top-1/2 left-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[16px] border border-line bg-white p-6 shadow-pop',
            wide ? 'max-w-3xl' : 'max-w-lg',
          )}
          {...(description ? {} : { 'aria-describedby': undefined })}
        >
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-[19px] font-semibold text-ink-900">{title}</Dialog.Title>
              {description && <Dialog.Description className="mt-1 text-[13.5px] text-body">{description}</Dialog.Description>}
            </div>
            <Dialog.Close className="rounded-md p-1 text-muted hover:bg-fog hover:text-ink-900" aria-label="Close">
              <X className="size-5" />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function Drawer({ open, onOpenChange, title, subtitle, children }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-950/25" />
        <Dialog.Content aria-describedby={undefined} className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col bg-canvas shadow-pop">
          <div className="flex items-start justify-between gap-4 border-b border-line bg-white px-6 py-5">
            <div className="min-w-0">
              <Dialog.Title className="text-[19px] font-semibold text-ink-900">{title}</Dialog.Title>
              {subtitle && <div className="mt-1 text-[13.5px] text-body">{subtitle}</div>}
            </div>
            <Dialog.Close className="rounded-md p-1 text-muted hover:bg-fog hover:text-ink-900" aria-label="Close">
              <X className="size-5" />
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-6">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={clsx('relative overflow-x-auto', className)}>
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  )
}

export const th = 'micro px-4 py-2.5 text-muted bg-paper border-b border-line whitespace-nowrap font-medium'
export const td = 'px-4 py-3 border-b border-line-soft align-middle'

/** Numbered section heading used to give long pages an editorial rhythm. */
export function SectionTitle({ index, title, hint, action }: { index?: string; title: string; hint?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
      <div className="flex items-baseline gap-3">
        {index && <span className="num text-[12px] text-brand-700">{index}</span>}
        <h2 className="text-[17px] font-semibold text-ink-900">{title}</h2>
        {hint && <span className="text-[12.5px] text-muted">{hint}</span>}
      </div>
      {action}
    </div>
  )
}

/** Segmented toggle (filters, flow switches). */
export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: ReactNode }[]
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[10px] border border-line bg-paper p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            'h-7.5 rounded-[8px] px-3 text-[12.5px] font-medium whitespace-nowrap transition-colors',
            o.value === value ? 'bg-white text-ink-900 shadow-[0_0_0_1px_var(--color-line),0_1px_2px_rgb(14_21_23/0.06)]' : 'text-muted hover:text-ink-900',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Small coloured dot + text for statuses. */
export function StatusDot({ tone, children }: { tone: 'green' | 'amber' | 'red' | 'slate' | 'teal'; children: ReactNode }) {
  const c = { green: 'bg-emerald-500', amber: 'bg-amber-500', red: 'bg-red-500', slate: 'bg-slate-400', teal: 'bg-brand-500' }[tone]
  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px] whitespace-nowrap text-ink-800">
      <span className={clsx('size-1.5 rounded-full', c)} aria-hidden />
      {children}
    </span>
  )
}

/** Simple client-side pager for long tables. */
export function Pager({ page, pages, onPage, total }: { page: number; pages: number; onPage: (p: number) => void; total: number }) {
  if (pages <= 1) return <div className="micro px-4 py-3 text-muted">{total} rows</div>
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <span className="micro text-muted">{total} rows · page {page + 1} of {pages}</span>
      <div className="flex gap-1.5">
        <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => onPage(page - 1)}>Previous</Button>
        <Button size="sm" variant="secondary" disabled={page >= pages - 1} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  )
}
