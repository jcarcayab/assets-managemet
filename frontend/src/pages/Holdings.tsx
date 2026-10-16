import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Position, Target } from '../api'
import { FormModal } from '../components/FormModal'
import { useRefreshPrices, useWrite } from '../hooks'
import { money, pct, qty, signed, tone } from '../format'

type Editing = { position: Position; target?: Target }

export default function Holdings() {
  const positions = useQuery({ queryKey: ['positions'], queryFn: () => api<Position[]>('/positions/') })
  const targets = useQuery({ queryKey: ['targets'], queryFn: () => api<Target[]>('/targets/') })
  const refresh = useRefreshPrices()
  const [editing, setEditing] = useState<Editing | null>(null)

  const saveTarget = useWrite(async (body: Record<string, unknown>) => {
    const { position, target } = editing!
    if (body.target_pct === null) return target && api(`/targets/${target.id}/`, { method: 'DELETE' })
    return target
      ? api(`/targets/${target.id}/`, { method: 'PATCH', body })
      : api('/targets/', { body: { ...body, account: position.account_id, asset: position.asset_id } })
  })

  if (positions.isLoading) return <p className="muted">Cargando…</p>
  if (positions.error) return <p className="error">{String(positions.error)}</p>

  const byAccount = new Map<string, Position[]>()
  for (const p of positions.data ?? []) byAccount.set(p.account_name, [...(byAccount.get(p.account_name) ?? []), p])

  return (
    <section>
      <div className="page-head">
        <h1>Posiciones</h1>
        <div className="actions">
          <button className="btn" onClick={() => refresh.mutate(undefined)} disabled={refresh.isPending}>
            {refresh.isPending ? 'Actualizando…' : 'Actualizar precios'}
          </button>
        </div>
      </div>
      <p className="muted small">
        Calculadas desde tus movimientos (costo promedio). Toca la columna “Objetivo” para definir la asignación deseada.
      </p>

      {!byAccount.size && <p className="empty">No hay posiciones abiertas.</p>}

      {[...byAccount.entries()].map(([account, rows]) => {
        const total = rows.reduce((s, p) => s + p.market_value, 0)
        return (
          <div className="card" key={account}>
            <div className="card-head">
              <h2>{account}</h2>
              <strong className="num">{money(total)}</strong>
            </div>
            <div className="table-wrap flush">
              <table>
                <thead>
                  <tr>
                    <th>Activo</th>
                    <th className="num">Cantidad</th>
                    <th className="num hide-sm">Costo prom.</th>
                    <th className="num hide-sm">Precio</th>
                    <th className="num">Valor</th>
                    <th className="num">Ganancia</th>
                    <th className="num hide-sm">% cuenta</th>
                    <th className="num">Objetivo</th>
                    <th className="num hide-sm">Rebalanceo</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={`${p.account_id}-${p.symbol}`}>
                      <td>
                        <strong>{p.symbol}</strong>
                        <small className="block muted">{p.name}</small>
                      </td>
                      <td className="num">{qty(p.quantity)}</td>
                      <td className="num hide-sm">{money(p.avg_cost)}</td>
                      <td className="num hide-sm">{money(p.price)}</td>
                      <td className="num">{money(p.market_value)}</td>
                      <td className={`num ${tone(p.unrealized)}`}>
                        {signed(p.unrealized)}
                        <small className="block">{pct(p.unrealized_pct)}</small>
                      </td>
                      <td className="num hide-sm">{pct(p.weight_in_account)}</td>
                      <td className="num">
                        {p.asset_id ? (
                          <button
                            className="link"
                            onClick={() =>
                              setEditing({
                                position: p,
                                target: targets.data?.find((t) => t.account === p.account_id && t.asset === p.asset_id),
                              })
                            }
                          >
                            {p.target_pct === null ? 'definir' : pct(p.target_pct)}
                          </button>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className={`num hide-sm ${tone(p.rebalance)}`}>
                        {p.rebalance === null ? '—' : `${p.rebalance >= 0 ? 'Comprar' : 'Vender'} ${money(Math.abs(p.rebalance))}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}

      {editing && (
        <FormModal
          title={`Objetivo: ${editing.position.symbol} en ${editing.position.account_name}`}
          fields={[
            {
              name: 'target_pct',
              label: 'Objetivo % de la cuenta',
              type: 'number',
              nullable: true,
              help: 'Vacío = sin objetivo. La suma por cuenta debería ser 100.',
            },
          ]}
          initial={{ target_pct: editing.target ? String(editing.target.target_pct) : '' }}
          onSubmit={(body) => saveTarget.mutateAsync(body)}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  )
}
