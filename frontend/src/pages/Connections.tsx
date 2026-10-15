import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from '../api'
import type { PlaidAccount, PlaidItem, PlaidStatus, SyncReport } from '../api'
import { useAccounts } from '../hooks'
import { dateTime, money } from '../format'
import { openPlaidLink } from '../plaidLink'

const NEW = 'new'
const OFF = 'off'

/** Sync; a failed sync comes back as 502 with the report, whose error explains what Plaid said. */
async function syncItem(id: number): Promise<SyncReport> {
  try {
    return await api<SyncReport>(`/plaid/items/${id}/sync/`, { method: 'POST' })
  } catch (e) {
    const report = e instanceof ApiError ? (e.data as SyncReport | null) : null
    if (report?.error) return report
    throw e
  }
}

function AccountRow({ pa, onChange }: { pa: PlaidAccount; onChange: () => void }) {
  const accounts = useAccounts()
  const supported = pa.type === 'investment' || pa.type === 'depository'
  const value = !pa.enabled ? OFF : pa.account ? String(pa.account) : NEW

  const update = async (v: string) => {
    const body = v === OFF ? { enabled: false } : { enabled: true, account: v === NEW ? null : Number(v) }
    await api(`/plaid/accounts/${pa.id}/`, { method: 'PATCH', body })
    onChange()
  }

  return (
    <tr>
      <td>
        <strong>{pa.name}</strong> {pa.mask && <span className="muted">····{pa.mask}</span>}
        <small className="block muted">
          {pa.type} · {pa.subtype}
        </small>
      </td>
      <td className="num hide-sm">{money(pa.current_balance)}</td>
      <td>
        {supported ? (
          <select value={value} onChange={(e) => update(e.target.value)} aria-label={`Destino de ${pa.name}`}>
            <option value={NEW}>{pa.account_name ? `→ ${pa.account_name}` : 'Crear cuenta nueva al sincronizar'}</option>
            {(accounts.data ?? [])
              .filter((a) => a.id !== pa.account)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  Usar “{a.name}”
                </option>
              ))}
            <option value={OFF}>No sincronizar</option>
          </select>
        ) : (
          <span className="muted small">No compatible (tarjetas y préstamos van en Deudas)</span>
        )}
      </td>
    </tr>
  )
}

function ItemCard({ item, refresh }: { item: PlaidItem; refresh: () => void }) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<SyncReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      qc.invalidateQueries() // positions, summary, accounts… may all have changed
      refresh()
    }
  }

  const sync = () => run(async () => setReport(await syncItem(item.id)))

  const reconnect = () =>
    run(async () => {
      const { link_token } = await api<{ link_token: string }>('/plaid/link-token/', { body: { item: item.id } })
      if (await openPlaidLink(link_token)) setReport(await syncItem(item.id))
    })

  const disconnect = () => {
    if (!window.confirm(`¿Desconectar ${item.institution_name}? Las cuentas y el historial importado se conservan.`)) return
    run(() => api(`/plaid/items/${item.id}/`, { method: 'DELETE' }))
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>
          {item.institution_name || 'Institución'}{' '}
          <span className="muted small">
            · {item.last_synced_at ? `sincronizada ${dateTime(item.last_synced_at)}` : 'sin sincronizar'}
          </span>
        </h2>
        <div className="actions">
          {item.needs_reauth ? (
            <button className="btn primary" onClick={reconnect} disabled={busy}>
              Reconectar
            </button>
          ) : (
            <button className="btn primary" onClick={sync} disabled={busy}>
              {busy ? 'Sincronizando…' : 'Sincronizar'}
            </button>
          )}
          <button className="btn danger" onClick={disconnect} disabled={busy}>
            Desconectar
          </button>
        </div>
      </div>
      {item.needs_reauth && <p className="error small">La institución pide volver a iniciar sesión. Pulsa “Reconectar”.</p>}
      {item.last_error && !item.needs_reauth && <p className="error small">{item.last_error}</p>}
      {error && <p className="error">{error}</p>}
      {report && !report.error && (
        <p className="pos small">
          {report.transactions} movimientos y {report.cash_flows} depósitos nuevos, {report.adjustments} ajustes de
          conciliación{report.skipped ? `, ${report.skipped} sin equivalente (cubiertos por la conciliación)` : ''}.
        </p>
      )}
      <div className="table-wrap flush">
        <table>
          <thead>
            <tr>
              <th>Cuenta en {item.institution_name || 'la institución'}</th>
              <th className="num hide-sm">Saldo</th>
              <th>Se refleja en</th>
            </tr>
          </thead>
          <tbody>
            {item.accounts.map((pa) => (
              <AccountRow key={pa.id} pa={pa} onChange={refresh} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function Connections() {
  const status = useQuery({ queryKey: ['plaid-status'], queryFn: () => api<PlaidStatus>('/plaid/status/') })
  const items = useQuery({ queryKey: ['plaid-items'], queryFn: () => api<PlaidItem[]>('/plaid/items/') })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const connect = async () => {
    setBusy(true)
    setError(null)
    try {
      const { link_token } = await api<{ link_token: string }>('/plaid/link-token/', { method: 'POST' })
      const publicToken = await openPlaidLink(link_token)
      if (publicToken) await api('/plaid/exchange/', { body: { public_token: publicToken } })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      items.refetch()
    }
  }

  return (
    <section>
      <div className="page-head">
        <h1>Conexiones</h1>
        <div className="actions">
          <button className="btn primary" onClick={connect} disabled={busy || !status.data?.configured}>
            {busy ? 'Abriendo…' : '+ Conectar institución'}
          </button>
        </div>
      </div>
      <p className="muted small">
        Conecta brokers y cuentas de retiro con Plaid para importar posiciones y movimientos (se sincroniza a diario). Tus
        credenciales las maneja Plaid; aquí solo se guarda un token cifrado. Plaid entrega hasta 24 meses de historia: lo anterior
        se registra como saldo inicial al costo promedio que reporta tu broker. Revisa a qué cuenta va cada una antes de
        sincronizar por primera vez.
        {status.data?.env === 'sandbox' && ' Modo sandbox: entra con usuario user_good y contraseña pass_good.'}
      </p>

      {status.data && !status.data.configured && (
        <div className="card warn">
          <strong>Plaid no está configurado.</strong> Crea una cuenta en dashboard.plaid.com y define <code>PLAID_CLIENT_ID</code>,{' '}
          <code>PLAID_SECRET</code> y <code>PLAID_ENV</code> (sandbox o production) en el archivo <code>.env</code>.
        </div>
      )}
      {error && <p className="error">{error}</p>}

      {items.data?.length === 0 && status.data?.configured && <p className="empty">Todavía no hay instituciones conectadas.</p>}
      {items.data?.map((item) => (
        <ItemCard key={item.id} item={item} refresh={() => items.refetch()} />
      ))}
    </section>
  )
}
