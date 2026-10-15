import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Link } from 'react-router-dom'
import type { ExposureRow } from '../api'
import { useExposure, useSummary } from '../hooks'
import { money, pct } from '../format'
import { PALETTE } from '../palette'

function Bars({ rows, limit }: { rows: ExposureRow[]; limit?: number }) {
  const data = rows.map((r) => ({ ...r, weight: Number(r.weight ?? 0) }))
  const max = Math.max(limit ?? 0, ...data.map((r) => r.weight))
  return (
    <ResponsiveContainer width="100%" height={Math.max(120, data.length * 34)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, left: 8, bottom: 4 }}>
        <XAxis type="number" hide domain={[0, max * 1.05]} />
        <YAxis type="category" dataKey="label" width={150} tick={{ fontSize: 12 }} stroke="var(--muted)" />
        <Tooltip formatter={(v) => pct(Number(v))} />
        {limit !== undefined && <ReferenceLine x={limit} stroke="var(--neg)" strokeDasharray="4 4" />}
        <Bar
          dataKey="weight"
          name="% de tus activos"
          radius={[0, 4, 4, 0]}
          label={{ position: 'right', fontSize: 11, formatter: (v: unknown) => `${Number(v).toFixed(0)}%` }}
        >
          {data.map((r, i) => (
            <Cell key={r.key} fill={limit !== undefined && r.weight > limit ? 'var(--neg)' : PALETTE[i % PALETTE.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export default function Exposure() {
  const exposure = useExposure()
  const summary = useSummary()
  const e = exposure.data
  const s = summary.data

  if (exposure.isLoading || !e) return <p className="muted">Cargando…</p>
  const limit = Number(e.limit)

  return (
    <section>
      <div className="page-head">
        <h1>Exposición y riesgo</h1>
      </div>
      <p className="muted small">
        Lo que realmente tienes detrás de cada fondo, como % de tus activos ({money(e.gross_assets, true)}, sin deudas). El límite de
        concentración ({pct(limit, 0)}) se cambia en Ajustes; el subyacente, sector y desglose de cada fondo, en{' '}
        <Link to="/activos">Activos</Link>.
      </p>

      {e.alerts.length > 0 && (
        <div className="card warn">
          <h2>Alertas de concentración</h2>
          <ul className="alerts">
            {e.alerts.map((a) => (
              <li key={`${a.kind}-${a.label}`}>
                <strong>{a.label}</strong> — {pct(a.weight)} ({money(a.value, true)}){' '}
                <span className="muted">
                  {a.kind === 'sector' ? 'sector' : 'posición'} · vía {a.via.join(', ')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h2>Por categoría (look-through)</h2>
          <Bars rows={e.by_category} />
        </div>
        <div className="card">
          <h2>Por sector</h2>
          {e.by_sector.length ? (
            <Bars rows={e.by_sector} limit={limit} />
          ) : (
            <p className="muted small">Asigna un sector a tus activos para ver la concentración sectorial.</p>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Por posición subyacente</h2>
        <Bars rows={e.by_holding.slice(0, 12)} limit={limit} />
      </div>

      {s && (
        <div className="card">
          <h2>Patrimonio después de impuestos</h2>
          <p className="muted small">
            Estimación con tasas planas (Ajustes): ganancias en cuentas gravables, retiro total de 401k/IRA tradicional y spread de
            opciones como ingreso ordinario. Orientativo, no asesoría fiscal.
          </p>
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th>Tratamiento</th>
                  <th className="num">Valor</th>
                  <th className="num">Impuesto est.</th>
                  <th className="num">Después de impuestos</th>
                </tr>
              </thead>
              <tbody>
                {s.by_tax_treatment.map((r) => (
                  <tr key={r.key}>
                    <td>{r.label}</td>
                    <td className="num">{money(r.value, true)}</td>
                    <td className="num neg">{money(-r.tax, true)}</td>
                    <td className="num">{money(r.after_tax, true)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td>Total</td>
                  <td className="num">{money(s.net_worth, true)}</td>
                  <td className="num neg">{money(-s.estimated_taxes, true)}</td>
                  <td className="num">{money(s.after_tax_net_worth, true)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
