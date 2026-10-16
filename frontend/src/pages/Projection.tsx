import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api'
import type { ClassAssumption, ContributionLimits, MonteCarlo, Settings } from '../api'
import { useSettings, useSummary, useWrite } from '../hooks'
import { money, pct } from '../format'
import { PALETTE } from '../palette'

type Params = Pick<
  Settings,
  | 'current_age'
  | 'retirement_age'
  | 'annual_return_pct'
  | 'annual_contribution'
  | 'withdrawal_rate_pct'
  | 'inflation_pct'
  | 'expected_volatility_pct'
  | 'employer_match_annual'
  | 'social_security_annual'
  | 'social_security_age'
  | 'life_expectancy'
>

type Row = { age: number; year: number; start: number; interest: number; contribution: number; withdrawal: number; end: number; real: number }

const END_AGE = 95
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', style: 'currency', currency: 'USD' })

/** Monthly compounding, contributions until retirement, then a fixed withdrawal of `rate` × balance at retirement. */
function project(start: number, p: Params): Row[] {
  const yearly = Math.pow(1 + p.annual_return_pct / 100 / 12, 12) - 1
  const thisYear = new Date().getFullYear()
  const rows: Row[] = []
  let balance = start
  let withdrawal = 0
  for (let age = p.current_age, i = 0; age <= END_AGE; age++, i++) {
    if (age === p.retirement_age) withdrawal = balance * (p.withdrawal_rate_pct / 100)
    const retired = age >= p.retirement_age
    const interest = balance * yearly
    const contribution = retired ? 0 : p.annual_contribution
    const out = retired ? Math.min(withdrawal, balance + interest) : 0
    const end = Math.max(balance + interest + contribution - out, 0)
    rows.push({
      age,
      year: thisYear + i,
      start: balance,
      interest,
      contribution,
      withdrawal: out,
      end,
      real: end / Math.pow(1 + p.inflation_pct / 100, i + 1),
    })
    balance = end
  }
  return rows
}

const FIELDS: { key: keyof Params; label: string; step?: string }[] = [
  { key: 'current_age', label: 'Edad actual', step: '1' },
  { key: 'retirement_age', label: 'Edad de retiro', step: '1' },
  { key: 'annual_return_pct', label: 'Rendimiento anual %' },
  { key: 'annual_contribution', label: 'Aporte anual (USD)', step: '100' },
  { key: 'withdrawal_rate_pct', label: 'Tasa de retiro %' },
  { key: 'inflation_pct', label: 'Inflación %' },
  { key: 'expected_volatility_pct', label: 'Volatilidad esperada % (Monte Carlo)' },
  { key: 'employer_match_annual', label: 'Match del empleador anual (USD)', step: '100' },
  { key: 'social_security_annual', label: 'Seguro Social anual (USD de hoy)', step: '100' },
  { key: 'social_security_age', label: 'Edad de Seguro Social', step: '1' },
  { key: 'life_expectancy', label: 'Planear hasta la edad', step: '1' },
]

type Edits = Record<string, { return: number; volatility: number }>

/** Expected return and volatility per asset class: today's mix gives the portfolio's numbers for Monte Carlo. */
function AssumptionsCard({ m }: { m: MonteCarlo }) {
  const a = m.assumptions
  const initial = () => Object.fromEntries(a.by_class.map((c) => [c.asset_class, { return: c.return_pct, volatility: c.volatility_pct }]))
  const [byClass, setByClass] = useState(a.by_asset_class)
  const [edits, setEdits] = useState<Edits>(initial)
  const save = useWrite((body: Partial<Settings>) => api('/settings/', { method: 'PATCH', body }))

  const isDefault = (c: ClassAssumption) =>
    edits[c.asset_class].return === c.default_return_pct && edits[c.asset_class].volatility === c.default_volatility_pct
  const dirty =
    byClass !== a.by_asset_class ||
    a.by_class.some((c) => edits[c.asset_class].return !== c.return_pct || edits[c.asset_class].volatility !== c.volatility_pct)
  const submit = () =>
    save.mutate({
      projection_by_asset_class: byClass,
      // Only what differs from the defaults is stored, so better defaults later still reach the rest.
      return_assumptions: Object.fromEntries(a.by_class.filter((c) => !isDefault(c)).map((c) => [c.asset_class, edits[c.asset_class]])),
    })
  const set = (cls: string, key: 'return' | 'volatility', value: number) =>
    setEdits({ ...edits, [cls]: { ...edits[cls], [key]: value } })

  return (
    <div className="card">
      <h2>Supuestos por tipo de activo</h2>
      <label className="check">
        <input type="checkbox" checked={byClass} onChange={(e) => setByClass(e.target.checked)} /> Usar mi asignación actual
        (si no, la tasa única de arriba)
      </label>
      <p className="muted small">
        Con tu asignación de hoy: rendimiento esperado <strong>{pct(a.allocation_return_pct)}</strong> y volatilidad{' '}
        <strong>{pct(a.allocation_volatility_pct)}</strong> al año, teniendo en cuenta cómo se mueven juntos (p. ej. crypto y
        acciones). Son supuestos de largo plazo nominales; ajústalos si tienes otra visión.
      </p>
      <div className="table-wrap flush">
        <table>
          <thead>
            <tr>
              <th>Tipo de activo</th>
              <th className="num">Peso hoy</th>
              <th className="num">Rendimiento %</th>
              <th className="num">Volatilidad %</th>
            </tr>
          </thead>
          <tbody>
            {a.by_class.map((c) => (
              <tr key={c.asset_class}>
                <td>
                  {c.label}
                  {!isDefault(c) && <span className="muted small"> · propio</span>}
                </td>
                <td className="num">{pct(c.weight_pct, 0)}</td>
                {(['return', 'volatility'] as const).map((key) => (
                  <td className="num" key={key}>
                    <input
                      className="num-input"
                      type="number"
                      inputMode="decimal"
                      step="0.5"
                      aria-label={`${c.label} ${key === 'return' ? 'rendimiento' : 'volatilidad'}`}
                      value={edits[c.asset_class][key]}
                      onChange={(e) => set(c.asset_class, key, Number(e.target.value))}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row-end">
        <button
          className="btn"
          onClick={() =>
            setEdits(Object.fromEntries(a.by_class.map((c) => [c.asset_class, { return: c.default_return_pct, volatility: c.default_volatility_pct }])))
          }
        >
          Valores por defecto
        </button>
        {dirty && (
          <button className="btn primary" onClick={submit} disabled={save.isPending}>
            Guardar supuestos
          </button>
        )}
      </div>
    </div>
  )
}

/** This year's 401k / IRA contributions against the IRS limits. */
function LimitsCard() {
  const q = useQuery({ queryKey: ['contribution-limits'], queryFn: () => api<ContributionLimits>('/contribution-limits/') })
  const d = q.data
  if (!d) return null
  const rows = [
    { label: '401k: tus aportes (antes de impuestos / Roth)', used: d.k401.elective, limit: d.k401.elective_limit, room: d.k401.elective_room },
    {
      label: '401k: total (tú + empresa + after-tax)',
      used: d.k401.total,
      limit: d.k401.total_limit,
      room: d.k401.total_room,
    },
    { label: 'IRA (Roth + tradicional)', used: d.ira.contributed, limit: d.ira.limit, room: d.ira.room },
  ]
  return (
    <div className="card">
      <h2>
        Aportes de {d.year} vs límites del IRS <span className="muted small">· edad {d.age}</span>
      </h2>
      {d.limits_year !== d.year && (
        <p className="muted small">Sin límites publicados para {d.year}: uso los de {d.limits_year}.</p>
      )}
      <div className="table-wrap flush">
        <table>
          <thead>
            <tr>
              <th>Cuenta</th>
              <th className="num">Aportado</th>
              <th className="num">Límite</th>
              <th className="num">Te queda</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <td>
                  {r.label}
                  <div className="bar-split mt-xs" role="img" aria-label={`${pct((r.used / r.limit) * 100, 0)} del límite`}>
                    <span style={{ flex: Math.min(r.used, r.limit) }} className="liquid" />
                    <span style={{ flex: Math.max(r.limit - r.used, 0) }} />
                  </div>
                </td>
                <td className="num">{money(r.used, true)}</td>
                <td className="num">{money(r.limit, true)}</td>
                <td className={`num ${r.room > 0 ? '' : 'neg'}`}>{money(r.room, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Sale de los depósitos registrados este año (Plaid los trae del 401k; el match cuenta como aporte del empleador). Los aportes
        “after-tax” no cuentan para tu límite personal, solo para el total. Incluye el catch-up si tienes 50+ (60–63: el ampliado).
      </p>
    </div>
  )
}

function MonteCarloSection({ base }: { base: string }) {
  const mc = useQuery({ queryKey: ['monte-carlo', base], queryFn: () => api<MonteCarlo>(`/monte-carlo/?base=${base}`) })
  const m = mc.data
  if (mc.isLoading || !m) return <div className="card muted">Simulando…</div>
  const data = m.bands.map((b) => ({ ...b, range: [b.p10, b.p90] }))
  const success = m.success_probability
  return (
    <div className="card">
      <h2>Monte Carlo ({m.paths.toLocaleString()} escenarios, en dólares de hoy)</h2>
      <p className="muted small">
        Retornos aleatorios: {pct(m.assumptions.return_pct)} de media y {pct(m.assumptions.volatility_pct)} de volatilidad al año
        {m.assumptions.by_asset_class ? ' (de tu asignación por tipo de activo)' : ' (tasa única)'}.{' '}
        {m.uses_budget
          ? `En el retiro gasta ${money(m.annual_spending, true)}/año (tu presupuesto), ajustado por inflación y menos Seguro Social.`
          : 'Sin presupuesto definido: retira la tasa de retiro sobre el saldo al jubilarte. Define tu Presupuesto para un cálculo más real.'}{' '}
        Usa los supuestos guardados.
      </p>
      <div className="kpis">
        <div className="card kpi">
          <span className="kpi-label">Probabilidad de éxito</span>
          <strong className={`kpi-value ${success >= 85 ? 'pos' : success < 70 ? 'neg' : ''}`}>{success.toFixed(0)}%</strong>
          <span className="kpi-sub">no quedarte sin dinero · 85%+ es cómodo</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">A los {m.at_retirement.age} (mediana)</span>
          <strong className="kpi-value">{money(m.at_retirement.p50, true)}</strong>
          <span className="kpi-sub">
            rango {money(m.at_retirement.p10, true)} – {money(m.at_retirement.p90, true)}
          </span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Número de independencia</span>
          <strong className="kpi-value">{money(m.fi_number, true)}</strong>
          <span className="kpi-sub">
            {m.fi_number === null ? 'requiere presupuesto' : m.fi_age ? `lo alcanzas ~${m.fi_age} años (mediana)` : 'no se alcanza en la mediana'}
          </span>
        </div>
        {m.rmd.deferred_share_pct > 0 && (
          <div className="card kpi">
            <span className="kpi-label">Retiro mínimo obligatorio (RMD) a los {m.rmd.start_age}</span>
            <strong className="kpi-value">{money(m.rmd.first_p50, true)}</strong>
            <span className="kpi-sub">
              mediana, $ de hoy · {pct(m.rmd.deferred_share_pct, 0)} de tu saldo es 401k/IRA tradicional · impuesto por retiros
              forzados {money(m.rmd.forced_tax_p50, true)}
            </span>
          </div>
        )}
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="age" tick={{ fontSize: 12 }} stroke="var(--muted)" />
          <YAxis tickFormatter={(v) => compact.format(v)} tick={{ fontSize: 12 }} stroke="var(--muted)" width={64} />
          <Tooltip
            formatter={(v) => (Array.isArray(v) ? `${money(Number(v[0]), true)} – ${money(Number(v[1]), true)}` : money(Number(v), true))}
            labelFormatter={(age) => `Edad ${age}`}
          />
          <Legend />
          <Area type="monotone" dataKey="range" name="10%–90% de escenarios" stroke="none" fill={PALETTE[0]} fillOpacity={0.15} />
          <Line type="monotone" dataKey="p50" name="Mediana" stroke={PALETTE[0]} strokeWidth={2} dot={false} />
          {m.fi_number !== null && (
            <ReferenceLine y={m.fi_number} stroke={PALETTE[2]} strokeDasharray="4 4" label={{ value: 'Independencia', fontSize: 11, fill: 'var(--muted)' }} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <AssumptionsCard key={JSON.stringify(m.assumptions)} m={m} />
    </div>
  )
}

export default function Projection() {
  const settings = useSettings()
  const summary = useSummary()
  const save = useWrite((body: Partial<Params>) => api('/settings/', { method: 'PATCH', body }))
  const [params, setParams] = useState<Params | null>(null)
  const [base, setBase] = useState<'net_worth' | 'net_worth_ex_private' | 'liquid'>('net_worth_ex_private')

  useEffect(() => {
    if (settings.data && !params) setParams(settings.data)
  }, [settings.data, params])

  const start = summary.data?.[base] ?? 0
  const rows = useMemo(() => (params ? project(start, params) : []), [start, params])

  if (!params || !summary.data) return <p className="muted">Cargando…</p>

  const retireIdx = rows.findIndex((r) => r.age === params.retirement_age)
  const atRetirement = retireIdx >= 0 ? rows[retireIdx] : undefined
  const retireReal = atRetirement ? atRetirement.start / Math.pow(1 + params.inflation_pct / 100, retireIdx) : null
  const annualDraw = atRetirement ? atRetirement.start * (params.withdrawal_rate_pct / 100) : null
  const dirty = FIELDS.some((f) => Number(params[f.key]) !== Number(settings.data?.[f.key]))

  return (
    <section>
      <div className="page-head">
        <h1>Proyección de retiro</h1>
      </div>

      <div className="card">
        <div className="form-grid cols-3">
          <label>
            <span>Saldo inicial</span>
            <select value={base} onChange={(e) => setBase(e.target.value as typeof base)}>
              <option value="net_worth">Patrimonio total ({money(summary.data.net_worth, true)})</option>
              <option value="net_worth_ex_private">Sin equity privada ({money(summary.data.net_worth_ex_private, true)})</option>
              <option value="liquid">Solo líquido ({money(summary.data.liquid, true)})</option>
            </select>
          </label>
          {FIELDS.map((f) => (
            <label key={f.key}>
              <span>{f.label}</span>
              <input
                type="number"
                inputMode="decimal"
                step={f.step ?? '0.1'}
                value={params[f.key]}
                onChange={(e) => setParams({ ...params, [f.key]: Number(e.target.value) })}
              />
            </label>
          ))}
        </div>
        {dirty && (
          <div className="row-end">
            <button className="btn primary" onClick={() => save.mutate(params)} disabled={save.isPending}>
              Guardar supuestos
            </button>
          </div>
        )}
      </div>

      <div className="kpis">
        <div className="card kpi">
          <span className="kpi-label">Saldo a los {params.retirement_age}</span>
          <strong className="kpi-value">{money(atRetirement?.start, true)}</strong>
          <span className="kpi-sub">en dólares de hoy: {money(retireReal, true)}</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Retiro anual ({params.withdrawal_rate_pct}%)</span>
          <strong className="kpi-value">{money(annualDraw, true)}</strong>
          <span className="kpi-sub">≈ {money(annualDraw === null ? null : annualDraw / 12, true)} / mes</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Saldo a los {END_AGE}</span>
          <strong className="kpi-value">{money(rows[rows.length - 1]?.end, true)}</strong>
          <span className="kpi-sub">en dólares de hoy: {money(rows[rows.length - 1]?.real, true)}</span>
        </div>
      </div>

      <div className="card">
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={rows} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="age" tick={{ fontSize: 12 }} stroke="var(--muted)" />
            <YAxis tickFormatter={(v) => compact.format(v)} tick={{ fontSize: 12 }} stroke="var(--muted)" width={64} />
            <Tooltip formatter={(v) => money(Number(v), true)} labelFormatter={(age) => `Edad ${age}`} />
            <Legend />
            <ReferenceLine
              x={params.retirement_age}
              stroke="var(--muted)"
              strokeDasharray="4 4"
              label={{ value: 'Retiro', fontSize: 12, fill: 'var(--muted)' }}
            />
            <Area type="monotone" dataKey="end" name="Saldo nominal" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.15} strokeWidth={2} />
            <Area type="monotone" dataKey="real" name="Dólares de hoy" stroke={PALETTE[1]} fill={PALETTE[1]} fillOpacity={0.1} strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <MonteCarloSection base={base} />

      <LimitsCard />

      <details className="card">
        <summary>Tabla año por año (proyección determinista)</summary>
        <div className="table-wrap flush">
          <table>
            <thead>
              <tr>
                <th>Edad</th>
                <th className="hide-sm">Año</th>
                <th className="num">Inicial</th>
                <th className="num hide-sm">Interés</th>
                <th className="num hide-sm">Aporte</th>
                <th className="num">Retiro</th>
                <th className="num">Final</th>
                <th className="num hide-sm">Real</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.age} className={r.age === params.retirement_age ? 'highlight' : ''}>
                  <td>{r.age}</td>
                  <td className="hide-sm">{r.year}</td>
                  <td className="num">{money(r.start, true)}</td>
                  <td className="num hide-sm">{money(r.interest, true)}</td>
                  <td className="num hide-sm">{money(r.contribution, true)}</td>
                  <td className="num">{money(r.withdrawal, true)}</td>
                  <td className="num">{money(r.end, true)}</td>
                  <td className="num hide-sm">{money(r.real, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}
