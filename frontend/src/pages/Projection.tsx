import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import type { Settings } from '../api'
import { useSettings, useSummary, useWrite } from '../hooks'
import { money } from '../format'
import { PALETTE } from '../palette'

type Params = Pick<
  Settings,
  'current_age' | 'retirement_age' | 'annual_return_pct' | 'annual_contribution' | 'withdrawal_rate_pct' | 'inflation_pct'
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
]

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

      <details className="card">
        <summary>Tabla año por año</summary>
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
