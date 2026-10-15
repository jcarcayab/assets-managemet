const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const num = new Intl.NumberFormat('en-US', { maximumFractionDigits: 6 })

export const money = (v: number | null | undefined, whole = false) =>
  v === null || v === undefined ? '—' : (whole ? usd0 : usd).format(v)

export const qty = (v: number | null | undefined) => (v === null || v === undefined ? '—' : num.format(v))

export const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '' : '−'}${Math.abs(v).toFixed(digits)}%`

export const signed = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : '−'}${usd.format(Math.abs(v))}`

export const tone = (v: number | null | undefined) => (!v ? '' : v > 0 ? 'pos' : 'neg')

export const dateTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('es', { dateStyle: 'medium', timeStyle: 'short' }) : '—'

export const today = () => new Date().toLocaleDateString('en-CA') // YYYY-MM-DD in local time

/** Convert a row's values to strings for form inputs. */
export function formOf(row: object, keys: string[]): Record<string, string | boolean> {
  const r = row as Record<string, unknown>
  return Object.fromEntries(
    keys.map((k) => [k, typeof r[k] === 'boolean' ? (r[k] as boolean) : r[k] === null || r[k] === undefined ? '' : String(r[k])]),
  )
}
