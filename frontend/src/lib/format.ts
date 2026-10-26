export function usd(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e9) return `$${(v / 1e9).toFixed(digits + 1)}B`
  if (a >= 1e6) return `$${(v / 1e6).toFixed(digits)}M`
  if (a >= 1e3) return `$${(v / 1e3).toFixed(digits)}K`
  return `$${v.toFixed(0)}`
}

export const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : `${(v * 100).toFixed(digits)}%`

export const num = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : new Intl.NumberFormat('en-US').format(Math.round(v))

export const tonnes = (kg: number | null | undefined) =>
  kg === null || kg === undefined ? '—' : `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(kg / 1000)} t`

export const date = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'

export const dateTime = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '—'

export const hostname = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}
