import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Allocation, ExposureRow } from '../api'
import { FormModal } from '../components/FormModal'
import type { Field } from '../components/FormModal'
import { useChoices, useExposure, useSettings, useSummary, useWrite } from '../hooks'
import { money, pct, tone } from '../format'
import { PALETTE } from '../palette'

const TAX_SHORT: Record<string, string> = { taxable: 'gravable', tax_deferred: 'diferida', tax_free: 'libre' }

function AllocationSection() {
  const allocation = useQuery({ queryKey: ['allocation'], queryFn: () => api<Allocation>('/allocation/') })
  const settings = useSettings()
  const choices = useChoices()
  const [editing, setEditing] = useState(false)
  const save = useWrite((body: Record<string, unknown>) => api('/settings/', { method: 'PATCH', body }))
  const a = allocation.data
  const categories = choices.data?.exposure_categories ?? []

  const fields: Field[] = [
    ...categories.map<Field>((c) => ({ name: c.value, label: `${c.label} %`, type: 'number', local: true })),
    { name: 'rebalance_threshold_pct', label: 'Rebalancear si se desvía más de (pp)', type: 'number', required: true },
  ]
  const initial = {
    ...Object.fromEntries(categories.map((c) => [c.value, String(settings.data?.target_allocation?.[c.value] ?? '')])),
    rebalance_threshold_pct: String(settings.data?.rebalance_threshold_pct ?? 5),
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>Asignación objetivo del hogar</h2>
        <button className="btn" onClick={() => setEditing(true)} disabled={!settings.data || !categories.length}>
          {a?.has_target ? 'Editar objetivo' : 'Definir objetivo'}
        </button>
      </div>
      {!a ? (
        <p className="muted">Cargando…</p>
      ) : !a.has_target ? (
        <p className="muted small">
          Define tu mezcla ideal (p. ej. 60% acciones EE.UU., 20% internacional, 10% bonos, 10% crypto) para ver cuánto te desvías
          y dónde rebalancear pagando menos impuestos.
        </p>
      ) : (
        <>
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th>Categoría</th>
                  <th className="num">Actual</th>
                  <th className="num">Objetivo</th>
                  <th className="num">Desviación</th>
                  <th className="num">Ajuste</th>
                </tr>
              </thead>
              <tbody>
                {a.rows.map((r) => (
                  <tr key={r.key}>
                    <td>
                      {r.label}
                      {!r.tradeable && <small className="block muted">no se puede vender</small>}
                    </td>
                    <td className="num">
                      {pct(r.weight)}
                      <small className="block muted">{money(r.value, true)}</small>
                    </td>
                    <td className="num">{pct(r.target_pct, 0)}</td>
                    <td className={`num ${r.action === 'sell' ? 'neg' : r.action === 'buy' ? 'pos' : ''}`}>
                      {r.drift === null ? '—' : `${r.drift >= 0 ? '+' : '−'}${Math.abs(r.drift).toFixed(1)} pp`}
                    </td>
                    <td className={`num ${r.action === 'locked' ? 'muted' : tone(r.diff)}`}>
                      {r.action === 'locked'
                        ? 'Ilíquido'
                        : r.action
                          ? `${r.action === 'buy' ? 'Comprar' : 'Vender'} ${money(Math.abs(r.diff ?? 0), true)}`
                          : 'OK'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {a.sells.map((plan) => (
            <div key={plan.category} className="mt">
              <h2>
                Para reducir {plan.label} ({money(plan.amount, true)}), vende primero:
              </h2>
              <ol className="alerts">
                {plan.items.map((it, i) => (
                  <li key={i}>
                    <strong>{money(it.sell, true)}</strong> de {it.symbol} en {it.account}{' '}
                    <span className="tag">{TAX_SHORT[it.tax_treatment] ?? it.tax_treatment}</span>{' '}
                    <span className="muted small">
                      {Number(it.estimated_tax) ? `impuesto est. ${money(it.estimated_tax, true)}` : 'sin impuesto'}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          ))}
          {a.rows.some((r) => r.action === 'buy') && (
            <p className="muted small mt">
              Para comprar lo que falta usa nuevos aportes
              {a.cash_available.length
                ? ` o el efectivo disponible (${a.cash_available.map((c) => `${c.account} ${money(c.value, true)}`).join(', ')})`
                : ''}
              . Regla general de ubicación: bonos en cuentas con impuesto diferido, lo de mayor crecimiento en Roth.
            </p>
          )}
        </>
      )}

      {editing && (
        <FormModal
          title="Asignación objetivo (debe sumar 100%)"
          fields={fields}
          initial={initial}
          onSubmit={(body, values) => {
            const target: Record<string, number> = {}
            for (const c of categories) {
              const n = Number(values[c.value] || 0)
              if (n) target[c.value] = n
            }
            return save.mutateAsync({ ...body, target_allocation: target })
          }}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  )
}

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

      <AllocationSection />

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
