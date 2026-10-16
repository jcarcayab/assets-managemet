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
  if (!res.ok) {
    const code = (data as { code?: string } | null)?.code
    if (res.status === 403 && (code === 'mfa_required' || code === 'mfa_setup_required')) {
      // The server wants the second factor (or enrollment): let the app re-check the session.
      window.dispatchEvent(new Event(AUTH_CHANGED))
    }
    throw new ApiError(res.status, data)
  }
  return data as T
}

export const AUTH_CHANGED = 'auth-changed'

/** Only same-site paths are allowed as post-login destinations. */
export function safeNext(raw: string | null): string | null {
  return raw && raw.startsWith('/') && !raw.startsWith('//') && !raw.startsWith('/\\') ? raw : null
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
  grant_types: Choice[]
  budget_kinds: Choice[]
  frequencies: Choice[]
  liability_kinds: Choice[]
  benchmarks: Choice[]
}

export type BudgetItem = {
  id: number
  name: string
  kind: 'income' | 'expense'
  kind_label: string
  category: string
  amount: number
  frequency: 'monthly' | 'annual'
  monthly: number
  essential: boolean
  notes: string
}

export type Liability = {
  id: number
  name: string
  kind: string
  kind_label: string
  balance: number
  interest_rate_pct: number
  minimum_payment: number
  promo_rate_pct: number | null
  promo_end_date: string | null
  deferred_interest: boolean
  updated_at: string
  notes: string
}

export type Budget = {
  monthly_income: number
  monthly_expenses: number
  monthly_essential: number
  monthly_savings: number
  savings_rate: number | null
  annual_expenses: number
  emergency_cash: number
  emergency_months: number | null
  emergency_target_months: number
  emergency_target: number
  emergency_gap: number
  by_category: { label: string; monthly: number; share: number | null }[]
}

export type Debts = {
  expected_return_pct: number
  total: number
  weighted_rate_pct: number | null
  minimum_payments: number
  annual_interest: number
  alerts: { name: string; level: 'warning' | 'critical'; message: string }[]
  rows: {
    id: number
    order: number
    name: string
    kind_label: string
    balance: number
    interest_rate_pct: number
    current_rate_pct: number
    in_promo: boolean
    promo_rate_pct: number | null
    promo_end_date: string | null
    promo_months_left: number | null
    deferred_interest: boolean
    payment_to_clear_promo: number | null
    clears_in_promo: boolean | null
    minimum_payment: number
    annual_interest: number
    months_to_payoff: number | null
    total_interest: number | null
    verdict: 'pay_first' | 'either' | 'invest' | 'promo'
  }[]
}

export type MonteCarlo = {
  base: string
  start: number
  paths: number
  success_probability: number
  uses_budget: boolean
  annual_spending: number | null
  fi_number: number | null
  fi_age: number | null
  at_retirement: { age: number; p10: number; p50: number; p90: number }
  bands: { age: number; p10: number; p50: number; p90: number }[]
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
  grant_type: 'nso' | 'iso' | 'shares'
  grant_type_label: string
  quantity: number
  strike: number
  fmv: number
  exercised: boolean
  grant_date: string | null
  vesting_start: string | null
  vesting_months: number
  cliff_months: number
  expiration_date: string | null
  post_termination_days: number
  liquidity_discount_pct: number
  sector: string
  notes: string
  cost_basis: number
  market_value: number
}

export type EquitySummary = {
  grants: {
    id: number
    company: string
    account: string
    grant_type: string
    grant_type_label: string
    is_option: boolean
    quantity: number
    vested: number
    unvested: number
    vested_pct: number | null
    next_vest_date: string | null
    fully_vested_date: string | null
    strike: number
    fmv: number
    liquidity_discount_pct: number
    value: number
    unvested_value: number
    value_without_discount: number
    exercise_cost: number
    spread: number
    exercise_tax: number
    amt_preference: number
    cash_to_exercise: number
    expiration_date: string | null
    days_to_expiration: number | null
    post_termination_days: number
  }[]
  alerts: { level: 'warning' | 'critical'; company: string; message: string }[]
  totals: { value: number; unvested_value: number; exercise_cost: number; exercise_tax: number; cash_to_exercise: number }
}

export type TaxLots = {
  rates: { short: number; long: number }
  short_gain: number
  long_gain: number
  estimated_tax: number
  positions: {
    symbol: string
    name: string
    account: string
    price: number
    gain: number
    lots: {
      date: string
      quantity: number
      unit_cost: number
      cost: number
      value: number
      gain: number
      term: 'short' | 'long'
      days_to_long_term: number | null
    }[]
  }[]
  harvest: {
    symbol: string
    account: string
    date: string
    loss: number
    term: 'short' | 'long'
    tax_saving: number
    wash_sale_rule: boolean
    wash_sale_risk: boolean
  }[]
  harvest_total_loss: number
  harvest_total_saving: number
  soon_long_term: { symbol: string; account: string; date: string; gain: number; days_to_long_term: number; saving_if_wait: number }[]
}

export type Allocation = {
  total: number
  threshold: number
  has_target: boolean
  rows: {
    key: string
    label: string
    value: number
    weight: number
    target_pct: number | null
    target_value: number | null
    diff: number | null
    drift: number | null
    action: 'buy' | 'sell' | 'locked' | null
    tradeable: boolean
  }[]
  sells: {
    category: string
    label: string
    amount: number
    items: { symbol: string; account: string; tax_treatment: string; sell: number; estimated_tax: number }[]
  }[]
  cash_available: { account: string; value: number; tax_treatment: string }[]
}

export type Scenario = {
  key: string
  label: string
  description: string
  change: number
  change_pct: number | null
  net_worth_after: number
  liquid_change: number
  worst: { label: string; change: number }[]
}

export type Risk = {
  portfolio: {
    window_days: number
    volatility: number | null
    max_drawdown: number | null
    current_drawdown: number | null
    recent_contribution_share?: number
  }
  holdings: {
    assets: { symbol: string; value: number; volatility: number | null }[]
    symbols: string[]
    matrix: (number | null)[][]
  }
  scenarios: Scenario[]
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
  assets: number
  liabilities: number
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
  target_allocation: Record<string, number>
  rebalance_threshold_pct: number
  emergency_fund_months: number
  expected_volatility_pct: number
  employer_match_annual: number
  social_security_annual: number
  social_security_age: number
  life_expectancy: number
}

export type PlaidStatus = { configured: boolean; env: string }
export type PlaidAccount = {
  id: number
  name: string
  official_name: string
  mask: string
  type: string
  subtype: string
  current_balance: number | null
  account: number | null
  account_name: string | null
  enabled: boolean
}
export type PlaidItem = {
  id: number
  institution_name: string
  created_at: string
  last_synced_at: string | null
  last_error: string
  needs_reauth: boolean
  accounts: PlaidAccount[]
}
export type SyncReport = {
  accounts: number
  transactions: number
  cash_flows: number
  adjustments: number
  skipped: number
  error: { code: string; message: string; needs_reauth: boolean } | null
}

export type ExchangeConnection = {
  id: number
  provider: 'coinbase' | 'kraken'
  provider_label: string
  label: string
  key_hint: string
  account: number | null
  account_name: string | null
  created_at: string
  last_synced_at: string | null
  last_error: string
}
export type ExchangeReport = {
  trades: number
  rewards: number
  cash_flows: number
  adjustments: number
  skipped: number
  error: string | null
}

export type User = { id: number; username: string; mfa_enabled: boolean }
export type SessionInfo = { user: User | null; mfa_setup_required: boolean }
export type LoginResult = SessionInfo | { mfa_required: true; mfa_token: string }
export type TwoFactorStatus = { enabled: boolean; confirmed_at: string | null; recovery_codes_left: number; required: boolean }
export type TwoFactorSetup = { secret: string; otpauth_uri: string; qr_svg: string }
