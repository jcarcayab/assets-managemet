export class ApiError extends Error {
  status: number
  data: unknown

  constructor(status: number, data: unknown) {
    super(ApiError.describe(data) ?? `Error ${status}`)
    this.status = status
    this.data = data
  }

  static describe(data: unknown): string | null {
    if (!data || typeof data !== 'object') return null
    const obj = data as Record<string, unknown>
    if (typeof obj.detail === 'string') return obj.detail
    const parts = Object.entries(obj).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : String(v)}`)
    return parts.length ? parts.join(' · ') : null
  }
}

function cookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : ''
}

export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? (init.body !== undefined ? 'POST' : 'GET')
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(method !== 'GET' ? { 'X-CSRFToken': cookie('csrftoken') } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

// -- types mirroring the Django serializers --------------------------------------------------------

export type Choice = { value: string; label: string }
export type Choices = {
  account_types: Choice[]
  asset_classes: Choice[]
  price_sources: Choice[]
  transaction_kinds: Choice[]
  cash_flow_kinds: Choice[]
  tax_treatments: Choice[]
  exposure_categories: Choice[]
  benchmarks: Choice[]
}

export type Account = {
  id: number
  name: string
  institution: string
  account_type: string
  account_type_label: string
  is_liquid: boolean
  tax_treatment: string
  tax_treatment_label: string
  notes: string
  archived: boolean
}

export type Asset = {
  id: number
  symbol: string
  name: string
  asset_class: string
  asset_class_label: string
  price_source: string
  source_id: string
  manual_price: number | null
  last_price: number | null
  last_price_at: string | null
  price: number
  underlying: string
  sector: string
  exposures: Record<string, number>
}

export type TransactionKind = 'buy' | 'sell' | 'dividend' | 'interest' | 'staking' | 'fee' | 'split' | 'transfer'

export type Transaction = {
  id: number
  account: number
  account_name: string
  asset: number
  asset_symbol: string
  kind: TransactionKind
  kind_label: string
  date: string
  quantity: number
  price: number
  fees: number
  amount: number
  to_account: number | null
  to_account_name: string | null
  total: number
  external_id: string
  notes: string
}

export type CashFlow = {
  id: number
  account: number
  account_name: string
  kind: 'deposit' | 'withdrawal' | 'employer'
  kind_label: string
  date: string
  amount: number
  notes: string
}

export type EquityGrant = {
  id: number
  account: number
  company: string
  quantity: number
  strike: number
  fmv: number
  exercised: boolean
  grant_date: string | null
  sector: string
  notes: string
  cost_basis: number
  market_value: number
}

export type Target = { id: number; account: number; asset: number; target_pct: number }

export type Position = {
  account_id: number
  account_name: string
  asset_id: number | null
  symbol: string
  name: string
  asset_class: string
  quantity: number
  avg_cost: number
  cost_basis: number
  price: number
  market_value: number
  unrealized: number
  unrealized_pct: number | null
  realized: number
  income: number
  weight_in_account: number | null
  target_pct: number | null
  target_value: number | null
  rebalance: number | null
  extra: Record<string, number>
}

export type Group = {
  key: string | number
  label: string
  cost: number
  value: number
  gain: number
  gain_pct: number | null
  weight: number | null
  institution?: string
  account_type?: string
  is_liquid?: boolean
}

export type Summary = {
  net_worth: number
  net_worth_ex_private: number
  after_tax_net_worth: number
  estimated_taxes: number
  liquid: number
  illiquid: number
  cost: number
  unrealized: number
  unrealized_pct: number | null
  prices_as_of: string | null
  income_12m: { dividend: number; interest: number; staking: number; fees: number; total: number }
  by_account: Group[]
  by_class: Group[]
  by_tax_treatment: { key: string; label: string; value: number; tax: number; after_tax: number }[]
  crypto: { deposits: number; value: number; gain: number; gain_pct: number | null }
}

export type Period = {
  key: string
  start: string
  days: number
  twr: number
  twr_annualized: number | null
  benchmark: number | null
  xirr: number | null
  xirr_annualized: boolean
}

export type Performance =
  | { empty: true; benchmark: string; benchmark_label: string }
  | {
      empty: false
      benchmark: string
      benchmark_label: string
      start: string
      value: number
      net_invested: number
      gain: number
      benchmark_equivalent: number | null
      missing_benchmark: boolean
      recent_contribution_share: number
      periods: Period[]
      series: { date: string; value: number; invested: number; twr: number; benchmark: number | null }[]
    }

export type Income = {
  by_year: { year: number; dividend: number; interest: number; staking: number; fees: number; total: number }[]
  by_asset_12m: { symbol: string; value: number }[]
}

export type ExposureRow = { key: string; label: string; value: number; weight: number | null; via?: string[] }

export type Exposure = {
  gross_assets: number
  limit: number
  by_category: ExposureRow[]
  by_holding: ExposureRow[]
  by_sector: ExposureRow[]
  alerts: { kind: 'holding' | 'sector'; label: string; weight: number; value: number; via: string[] }[]
}

export type Snapshot = {
  id: number
  date: string
  net_worth: number
  net_worth_ex_private: number | null
  liquid: number | null
  cost: number | null
  unrealized: number | null
  notes: string
}

export type Settings = {
  take_profit_1_pct: number
  take_profit_2_pct: number
  stop_loss_pct: number
  current_age: number
  retirement_age: number
  annual_return_pct: number
  annual_contribution: number
  withdrawal_rate_pct: number
  inflation_pct: number
  benchmark: string
  concentration_limit_pct: number
  capital_gains_tax_pct: number
  retirement_tax_pct: number
  ordinary_income_tax_pct: number
}

export type User = { id: number; username: string }
