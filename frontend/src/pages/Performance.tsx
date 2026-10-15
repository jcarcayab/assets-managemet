import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Area, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import type { Income, Performance as Perf } from '../api'
import { useAccounts, useChoices, useRefreshPrices, useSettings } from '../hooks'
import { money, pct, signed, tone } from '../format'
import { PALETTE } from '../palette'

const compact = new Intl.NumberFormat('en-US', { notation: 'compact', style: 'currency', currency: 'USD' })
const PERIOD_LABEL: Record<string, string> = { '1M': '1 mes', '3M': '3 meses', YTD: 'Este año', '1A': '1 año', Total: 'Desde el inicio' }

export default function Performance() {
  const settings = useSettings()
  const accounts = useAccounts()
  const choices = useChoices()
  const refresh = useRefreshPrices()
  const [account, setAccount] = useState('')
  const [benchmark, setBenchmark] = useState('')
  const bench = benchmark || settings.data?.benchmark || 'SPY'

  const perf = useQuery({
    queryKey: ['performance', account, bench],
    queryFn: () => api<Perf>(`/performance/?benchmark=${encodeURIComponent(bench)}${account ? `&account=${account}` : ''}`),
    enabled: Boolean(settings.data),
  })
  const income = useQuery({ queryKey: ['income'], queryFn: () => api<Income>('/income/') })

  const p = perf.data

  return (
    <section>
      <div className="page-head">
        <h1>Rendimiento</h1>
        <div className="actions">
          <select value={account} onChange={(e) => setAccount(e.target.value)} aria-label="Cuenta">
            <option value="">Todo el portafolio</option>
            {(accounts.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <select value={bench} onChange={(e) => setBenchmark(e.target.value)} aria-label="Benchmark">
            {(choices.data?.benchmarks ?? []).map((b) => (
              <option key={b.value} value={b.value}>
                vs. {b.label}
              </option>
            ))}
          </select>
          <button className="btn" onClick={() => refresh.mutate(undefined)} disabled={refresh.isPending}>
            {refresh.isPending ? 'Actualizando…' : 'Actualizar historial'}
          </button>
        </div>
      </div>
      <p className="muted small">
        <strong>TWR</strong> mide tus decisiones de inversión sin importar cuándo aportaste (es lo que se compara con el benchmark).{' '}
        <strong>Rendimiento del dinero (XIRR)</strong> mide lo que ganó tu dinero real según cuándo y cuánto pusiste. Excluye equity
        privada y deudas.
      </p>

      {perf.isLoading || !p ? (
        <p className="muted">Calculando…</p>
      ) : p.empty ? (
        <p className="empty">No hay movimientos para calcular rendimiento.</p>
      ) : (
        <>
          {p.recent_contribution_share > 50 && (
            <div className="card warn">
              <strong>Historial incompleto:</strong> {pct(p.recent_contribution_share, 0)} del valor actual entró en los últimos 7
              días. Si son saldos iniciales importados, edita en Movimientos la fecha real de esas compras para que el rendimiento
              histórico sea correcto.
            </div>
          )}
          {p.missing_benchmark && <div className="card warn">Sin historial de {p.benchmark_label}. Pulsa “Actualizar historial”.</div>}

          <div className="kpis">
            <div className="card kpi">
              <span className="kpi-label">Valor actual</span>
              <strong className="kpi-value">{money(p.value, true)}</strong>
              <span className="kpi-sub">desde {p.start}</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">Aportado neto</span>
              <strong className="kpi-value">{money(p.net_invested, true)}</strong>
              <span className="kpi-sub">compras − ventas</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">Ganancia</span>
              <strong className={`kpi-value ${tone(p.gain)}`}>{signed(p.gain)}</strong>
            </div>
            <div className="card kpi">
              <span className="kpi-label">Mismos aportes en {p.benchmark}</span>
              <strong className="kpi-value">{money(p.benchmark_equivalent, true)}</strong>
              {p.benchmark_equivalent !== null && (
                <span className={`kpi-sub ${tone(p.value - p.benchmark_equivalent)}`}>
                  {p.value >= p.benchmark_equivalent ? 'le ganas por ' : 'pierdes por '}
                  {money(Math.abs(p.value - p.benchmark_equivalent), true)}
                </span>
              )}
            </div>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Periodo</th>
                  <th className="num">TWR</th>
                  <th className="num">{p.benchmark}</th>
                  <th className="num">Diferencia</th>
                  <th className="num">Rend. del dinero</th>
                </tr>
              </thead>
              <tbody>
                {p.periods.map((r) => {
                  const diff = r.benchmark === null ? null : r.twr - r.benchmark
                  return (
                    <tr key={r.key}>
                      <td>
                        {PERIOD_LABEL[r.key] ?? r.key}
                        <small className="block muted">desde {r.start}</small>
                      </td>
                      <td className={`num ${tone(r.twr)}`}>
                        {pct(r.twr)}
                        {r.twr_annualized !== null && <small className="block">{pct(r.twr_annualized)} anual</small>}
                      </td>
                      <td className={`num ${tone(r.benchmark)}`}>{pct(r.benchmark)}</td>
                      <td className={`num ${tone(diff)}`}>
                        {diff === null ? '—' : `${diff >= 0 ? '+' : '−'}${Math.abs(diff).toFixed(1)} pp`}
                      </td>
                      <td className={`num ${tone(r.xirr)}`}>
                        {pct(r.xirr)}
                        {r.xirr !== null && <small className="block muted">{r.xirr_annualized ? 'anual' : 'en el periodo'}</small>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="grid-2">
            <div className="card">
              <h2>Rendimiento acumulado vs. {p.benchmark_label}</h2>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={p.series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="var(--muted)" minTickGap={40} />
                  <YAxis tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} stroke="var(--muted)" width={48} />
                  <Tooltip formatter={(v) => pct(Number(v))} />
                  <Legend />
                  <Line type="monotone" dataKey="twr" name="Tu portafolio (TWR)" stroke={PALETTE[0]} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="benchmark" name={p.benchmark} stroke={PALETTE[2]} strokeWidth={2} dot={false} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="card">
              <h2>Valor vs. dinero aportado</h2>
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={p.series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="var(--muted)" minTickGap={40} />
                  <YAxis tickFormatter={(v) => compact.format(v)} tick={{ fontSize: 11 }} stroke="var(--muted)" width={56} />
                  <Tooltip formatter={(v) => money(Number(v), true)} />
                  <Legend />
                  <Area type="monotone" dataKey="value" name="Valor" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.15} strokeWidth={2} />
                  <Line type="stepAfter" dataKey="invested" name="Aportado" stroke={PALETTE[8]} strokeDasharray="4 4" dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}

      <div className="card">
        <h2>Ingresos (dividendos, intereses, staking)</h2>
        {!income.data?.by_year.length ? (
          <p className="muted small">Aún no hay ingresos registrados. Añádelos en Movimientos con tipo Dividendo, Interés o Staking.</p>
        ) : (
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th>Año</th>
                  <th className="num">Dividendos</th>
                  <th className="num">Intereses</th>
                  <th className="num">Staking</th>
                  <th className="num">Comisiones</th>
                  <th className="num">Neto</th>
                </tr>
              </thead>
              <tbody>
                {income.data.by_year.map((r) => (
                  <tr key={r.year}>
                    <td>{r.year}</td>
                    <td className="num">{money(r.dividend)}</td>
                    <td className="num">{money(r.interest)}</td>
                    <td className="num">{money(r.staking)}</td>
                    <td className="num neg">{money(-r.fees)}</td>
                    <td className={`num ${tone(r.total)}`}>{money(r.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
