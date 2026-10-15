import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Risk as RiskData } from '../api'
import { money, pct, tone } from '../format'

// Inputs for the custom stress scenario: exposure categories plus the crypto sector (catches crypto-company equity).
const CUSTOM_FIELDS = [
  { key: 'us_equity', label: 'Acciones EE.UU.' },
  { key: 'intl_equity', label: 'Acciones intl.' },
  { key: 'bonds', label: 'Bonos' },
  { key: 'crypto', label: 'Crypto' },
  { key: 'commodities', label: 'Metales' },
  { key: 'private_equity', label: 'Equity privada' },
  { key: 'sector.Crypto', label: 'Sector Crypto' },
]

function corrColor(v: number | null) {
  if (v === null) return 'transparent'
  const a = Math.min(Math.abs(v), 1) * 0.55
  return v >= 0 ? `rgb(220 38 38 / ${a})` : `rgb(37 99 235 / ${a})`
}

export default function Risk() {
  const [custom, setCustom] = useState('')
  const [draft, setDraft] = useState<Record<string, string>>({})
  const risk = useQuery({
    queryKey: ['risk', custom],
    queryFn: () => api<RiskData>(`/risk/${custom ? `?custom=${encodeURIComponent(custom)}` : ''}`),
  })

  const runCustom = (e: FormEvent) => {
    e.preventDefault()
    setCustom(
      Object.entries(draft)
        .filter(([, v]) => v !== '' && !Number.isNaN(Number(v)))
        .map(([k, v]) => `${k}:${v}`)
        .join(','),
    )
  }

  if (risk.isLoading || !risk.data) return <p className="muted">Calculando…</p>
  const { portfolio: p, holdings: h, scenarios } = risk.data

  return (
    <section>
      <div className="page-head">
        <h1>Riesgo</h1>
      </div>
      <p className="muted small">
        Métricas del último año a partir del historial diario. Las pruebas de estrés aplican caídas hipotéticas por categoría y
        sector a tus posiciones actuales — no son pronósticos.
      </p>

      {(p.recent_contribution_share ?? 0) > 50 && (
        <div className="card warn">
          <strong>Historial incompleto:</strong> la mayoría de tus posiciones tienen fecha de compra reciente, así que la volatilidad
          y la caída máxima reflejan solo lo que tiene historial. Corrige las fechas en Movimientos.
        </div>
      )}

      <div className="kpis">
        <div className="card kpi">
          <span className="kpi-label">Volatilidad anual</span>
          <strong className="kpi-value">{pct(p.volatility)}</strong>
          <span className="kpi-sub">S&amp;P 500 suele estar en 15–20%</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Caída máxima (12m)</span>
          <strong className="kpi-value neg">{p.max_drawdown === null ? '—' : `−${p.max_drawdown.toFixed(1)}%`}</strong>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Desde el máximo</span>
          <strong className={`kpi-value ${p.current_drawdown ? 'neg' : ''}`}>
            {p.current_drawdown === null ? '—' : `−${p.current_drawdown.toFixed(1)}%`}
          </strong>
        </div>
      </div>

      <div className="card">
        <h2>Pruebas de estrés</h2>
        <div className="table-wrap flush">
          <table>
            <thead>
              <tr>
                <th>Escenario</th>
                <th className="num">Impacto</th>
                <th className="num hide-sm">Patrimonio después</th>
                <th className="num hide-sm">Líquido</th>
                <th className="hide-sm">Mayores pérdidas</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => (
                <tr key={s.key}>
                  <td>
                    <strong>{s.label}</strong>
                    {s.description && <small className="block muted">{s.description}</small>}
                  </td>
                  <td className={`num ${tone(s.change)}`}>
                    {money(s.change, true)}
                    <small className="block">{pct(s.change_pct)}</small>
                  </td>
                  <td className="num hide-sm">{money(s.net_worth_after, true)}</td>
                  <td className={`num hide-sm ${tone(s.liquid_change)}`}>{money(s.liquid_change, true)}</td>
                  <td className="hide-sm small">{s.worst.map((w) => `${w.label} ${money(w.change, true)}`).join(' · ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form onSubmit={runCustom}>
          <h2 className="mt">Escenario personalizado (% de cambio)</h2>
          <div className="form-grid cols-3">
            {CUSTOM_FIELDS.map((f) => (
              <label key={f.key}>
                <span>{f.label}</span>
                <input
                  type="number"
                  inputMode="decimal"
                  placeholder="0"
                  value={draft[f.key] ?? ''}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
              </label>
            ))}
          </div>
          <div className="row-end">
            <button className="btn primary">Calcular</button>
          </div>
        </form>
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Volatilidad por activo (12m)</h2>
          <ul className="legend">
            {h.assets.map((a) => (
              <li key={a.symbol}>
                <span className="grow">
                  <strong>{a.symbol}</strong> <span className="muted small">{money(a.value, true)}</span>
                </span>
                <span className="num">{pct(a.volatility)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h2>Correlación de retornos diarios</h2>
          <p className="muted small">Cerca de 1 = se mueven juntos (no diversifican). Rojo = positiva, azul = negativa.</p>
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th />
                  {h.symbols.map((s) => (
                    <th key={s} className="num">
                      {s}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {h.matrix.map((row, i) => (
                  <tr key={h.symbols[i]}>
                    <th>{h.symbols[i]}</th>
                    {row.map((v, j) => (
                      <td key={j} className="num" style={{ background: i === j ? 'var(--bg)' : corrColor(v) }}>
                        {v === null ? '—' : v.toFixed(2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  )
}
