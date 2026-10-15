import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import type { Snapshot } from '../api'
import { useWrite } from '../hooks'
import { money, pct, tone } from '../format'
import { PALETTE } from '../palette'

const compact = new Intl.NumberFormat('en-US', { notation: 'compact', style: 'currency', currency: 'USD' })

export default function History() {
  const snaps = useQuery({ queryKey: ['snapshots'], queryFn: () => api<Snapshot[]>('/snapshots/') })
  const take = useWrite(() => api('/snapshots/', { method: 'POST', body: {} }))
  const remove = useWrite((id: number) => api(`/snapshots/${id}/`, { method: 'DELETE' }))

  const rows = snaps.data ?? []
  const desc = [...rows].reverse()

  return (
    <section>
      <div className="page-head">
        <h1>Historial</h1>
        <div className="actions">
          <button className="btn primary" onClick={() => take.mutate(undefined)} disabled={take.isPending}>
            Guardar foto de hoy
          </button>
        </div>
      </div>
      <p className="muted small">
        Una foto guarda tus totales del día. Configura <code>manage.py take_snapshot</code> en un cron diario para que se haga sola.
      </p>

      {rows.length > 1 && (
        <div className="card">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={rows} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="var(--muted)" />
              <YAxis tickFormatter={(v) => compact.format(v)} tick={{ fontSize: 12 }} stroke="var(--muted)" width={64} />
              <Tooltip formatter={(v) => money(Number(v), true)} />
              <Legend />
              <Line type="monotone" dataKey="net_worth" name="Patrimonio" stroke={PALETTE[0]} strokeWidth={2} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="net_worth_ex_private" name="Sin equity" stroke={PALETTE[1]} strokeWidth={2} dot={{ r: 3 }} connectNulls />
              <Line type="monotone" dataKey="liquid" name="Líquido" stroke={PALETTE[2]} strokeWidth={2} dot={{ r: 3 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {snaps.isLoading ? (
        <p className="muted">Cargando…</p>
      ) : !rows.length ? (
        <p className="empty">Todavía no hay fotos.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th className="num">Patrimonio</th>
                <th className="num">Cambio</th>
                <th className="num hide-sm">Sin equity</th>
                <th className="num hide-sm">Líquido</th>
                <th className="hide-sm">Nota</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {desc.map((s, i) => {
                const prev = desc[i + 1]
                const change = prev ? s.net_worth - prev.net_worth : null
                return (
                  <tr key={s.id}>
                    <td>{s.date}</td>
                    <td className="num">{money(s.net_worth, true)}</td>
                    <td className={`num ${tone(change)}`}>
                      {change === null ? '—' : money(change, true)}
                      {change !== null && prev.net_worth ? <small className="block">{pct((change / prev.net_worth) * 100)}</small> : null}
                    </td>
                    <td className="num hide-sm">{money(s.net_worth_ex_private, true)}</td>
                    <td className="num hide-sm">{money(s.liquid, true)}</td>
                    <td className="hide-sm muted">{s.notes}</td>
                    <td className="num">
                      <button
                        className="icon-btn"
                        aria-label="Borrar foto"
                        onClick={() => window.confirm(`¿Borrar la foto del ${s.date}?`) && remove.mutate(s.id)}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
