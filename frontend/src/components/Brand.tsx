import clsx from 'clsx'

export const CONCILIO_URL = 'https://concilio.solutions'

/** Concilio Solutions mark (from concilio.solutions favicon). */
export function ConcilioMark({ className, inverted }: { className?: string; inverted?: boolean }) {
  const fg = inverted ? '#121c1e' : '#e9e8ed'
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden>
      <rect width="48" height="48" rx="11" fill={inverted ? '#ffffff' : '#121c1e'} />
      <g transform="translate(1.2 1.2) scale(0.95)">
        <path d="M38.73 40.23A21 21 0 1 1 38.73 7.77" fill="none" stroke={fg} strokeWidth="5.6" strokeLinecap="round" />
        <path d="M33.47 35.56A14.1 14.1 0 1 1 33.47 12.44" fill="none" stroke="#5fc4be" strokeWidth="2.8" strokeLinecap="round" />
        <path d="M16.5 24.8 21.8 30.1 37.8 14.1" fill="none" stroke={fg} strokeWidth="4.2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="43.7" cy="24" r="3" fill={fg} />
      </g>
    </svg>
  )
}

/** The client's monogram: first letter of its brand, set in the display face. */
export function ClientMark({ brand, className }: { brand: string; className?: string }) {
  return (
    <span
      className={clsx('flex shrink-0 items-center justify-center rounded-[10px] bg-ink-900 font-display font-semibold text-white', className)}
      aria-hidden
    >
      {(brand || '·').trim().charAt(0).toUpperCase()}
    </span>
  )
}

export function PoweredBy({ className, tone = 'dark' }: { className?: string; tone?: 'dark' | 'light' }) {
  return (
    <a
      href={CONCILIO_URL}
      target="_blank"
      rel="noopener noreferrer"
      className={clsx(
        'group inline-flex items-center gap-2 text-[11.5px] transition-colors',
        tone === 'dark' ? 'text-muted hover:text-ink-900' : 'text-white/60 hover:text-white',
        className,
      )}
    >
      <ConcilioMark className="size-4.5" inverted={tone === 'light'} />
      <span>
        Powered by <span className="font-semibold">Concilio Solutions</span>
      </span>
    </a>
  )
}
