import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from '../api'
import type {
  ExchangeConnection,
  ExchangeReport,
  Liability,
  PlaidAccount,
  PlaidItem,
  PlaidStatus,
  SyncReport,
} from '../api'
import { FormModal } from '../components/FormModal'
import { useAccounts } from '../hooks'
import { dateTime, money } from '../format'
import { openPlaidLink, takePendingOAuth } from '../plaidLink'

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
  const debts = useQuery({ queryKey: ['/liabilities/', ''], queryFn: () => api<Liability[]>('/liabilities/') })
  const isDebt = pa.type === 'credit' || pa.type === 'loan'
  const supported = isDebt || pa.type === 'investment' || pa.type === 'depository'
  const target = isDebt ? pa.liability : pa.account
  const targetName = isDebt ? pa.liability_name : pa.account_name
  const value = !pa.enabled ? OFF : target ? String(target) : NEW
  const options = isDebt
    ? (debts.data ?? []).map((d) => ({ id: d.id, name: d.name }))
    : (accounts.data ?? []).map((a) => ({ id: a.id, name: a.name }))

  const update = async (v: string) => {
    const field = isDebt ? 'liability' : 'account'
    const body = v === OFF ? { enabled: false } : { enabled: true, [field]: v === NEW ? null : Number(v) }
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
            <option value={NEW}>
              {targetName ? `→ ${targetName}` : isDebt ? 'Crear deuda nueva al sincronizar' : 'Crear cuenta nueva al sincronizar'}
            </option>
            {options
              .filter((o) => o.id !== target)
              .map((o) => (
                <option key={o.id} value={o.id}>
                  Usar “{o.name}”
                </option>
              ))}
            <option value={OFF}>No sincronizar</option>
          </select>
        ) : (
          <span className="muted small">No compatible</span>
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
      if (await openPlaidLink(link_token, { itemId: item.id })) setReport(await syncItem(item.id))
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
          conciliación{report.liabilities ? `, ${report.liabilities} deudas actualizadas` : ''}{report.skipped ? `, ${report.skipped} sin equivalente (cubiertos por la conciliación)` : ''}.
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

async function syncExchange(id: number): Promise<ExchangeReport> {
  try {
    return await api<ExchangeReport>(`/exchanges/${id}/sync/`, { method: 'POST' })
  } catch (e) {
    const report = e instanceof ApiError ? (e.data as ExchangeReport | null) : null
    if (report?.error) return report
    throw e
  }
}

function ExchangeCard({ conn, refresh }: { conn: ExchangeConnection; refresh: () => void }) {
  const qc = useQueryClient()
  const accounts = useAccounts()
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<ExchangeReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const name = conn.label || conn.provider_label

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      qc.invalidateQueries()
      refresh()
    }
  }

  const remove = () => {
    if (!window.confirm(`¿Olvidar las llaves de ${name}? La cuenta y el historial se conservan.`)) return
    run(() => api(`/exchanges/${conn.id}/`, { method: 'DELETE' }))
  }

  const setAccount = (value: string) =>
    run(() => api(`/exchanges/${conn.id}/`, { method: 'PATCH', body: { account: value ? Number(value) : null } }))

  return (
    <div className="card">
      <div className="card-head">
        <h2>
          {name}{' '}
          <span className="muted small">
            · llave …{conn.key_hint} ·{' '}
            {conn.last_synced_at ? `sincronizada ${dateTime(conn.last_synced_at)}` : 'sin sincronizar'}
          </span>
        </h2>
        <div className="actions">
          <button className="btn primary" disabled={busy} onClick={() => run(async () => setReport(await syncExchange(conn.id)))}>
            {busy ? 'Sincronizando…' : 'Sincronizar'}
          </button>
          <button className="btn danger" disabled={busy} onClick={remove}>
            Quitar
          </button>
        </div>
      </div>
      {conn.last_error && <p className="error small">{conn.last_error}</p>}
      {error && <p className="error">{error}</p>}
      {report && !report.error && (
        <p className="pos small">
          {report.trades} trades, {report.rewards} recompensas de staking y {report.cash_flows} depósitos nuevos;{' '}
          {report.adjustments} ajustes de conciliación
          {report.skipped ? ` (${report.skipped} movimientos sin costo, como transferencias entre wallets)` : ''}.
        </p>
      )}
      <div className="form-grid">
        <label>
          <span>Se refleja en</span>
          <select value={conn.account ?? ''} onChange={(e) => setAccount(e.target.value)} disabled={busy}>
            <option value="">{conn.account_name ? `→ ${conn.account_name}` : 'Crear cuenta nueva al sincronizar'}</option>
            {(accounts.data ?? [])
              .filter((a) => a.id !== conn.account)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  Usar “{a.name}”
                </option>
              ))}
          </select>
        </label>
      </div>
    </div>
  )
}

const KEY_HELP = (
  <div className="muted small key-help">
    <p>
      <strong>Coinbase:</strong> portal.cdp.coinbase.com → API Keys → Create API key → permiso solo <em>View</em> (sin Trade ni
      Transfer), algoritmo ECDSA. API key = el nombre <code>organizations/…/apiKeys/…</code>; secreto = la llave privada.
    </p>
    <p>
      <strong>Kraken:</strong> Settings → API → Create API key → marca solo <em>Query Funds</em>,{' '}
      <em>Query Closed Orders &amp; Trades</em> y <em>Query Ledger Entries</em>. Nada de Deposit, Withdraw ni Trade.
    </p>
  </div>
)

function ExchangesSection() {
  const conns = useQuery({ queryKey: ['exchanges'], queryFn: () => api<ExchangeConnection[]>('/exchanges/') })
  const [adding, setAdding] = useState(false)

  return (
    <>
      <div className="page-head mt">
        <h2>Exchanges de crypto</h2>
        <button className="btn primary" onClick={() => setAdding(true)}>
          + Conectar exchange
        </button>
      </div>
      <p className="muted small">
        Coinbase y Kraken con llaves de <strong>solo lectura</strong>: importan trades, recompensas de staking y depósitos, y
        cuadran con tus saldos (se sincroniza a diario). Las llaves se guardan cifradas y nunca se muestran. Lo que llega por
        transferencia desde otra wallet no trae su costo original: esas unidades se registran al precio actual.
      </p>
      {conns.data?.length === 0 && <p className="empty">Ningún exchange conectado.</p>}
      {conns.data?.map((c) => (
        <ExchangeCard key={c.id} conn={c} refresh={() => conns.refetch()} />
      ))}
      {adding && (
        <FormModal
          title="Conectar exchange (solo lectura)"
          fields={[
            {
              name: 'provider',
              label: 'Exchange',
              type: 'select',
              required: true,
              options: [
                { value: 'kraken', label: 'Kraken' },
                { value: 'coinbase', label: 'Coinbase' },
              ],
            },
            { name: 'label', label: 'Nombre (opcional)', help: 'Ej. Kraken personal' },
            { name: 'api_key', label: 'API key', required: true },
            { name: 'api_secret', label: 'Secreto / llave privada', type: 'textarea', required: true },
          ]}
          initial={{ provider: 'kraken', label: '', api_key: '', api_secret: '' }}
          footer={KEY_HELP}
          onSubmit={async (body) => {
            await api('/exchanges/', { body })
            conns.refetch()
          }}
          onClose={() => setAdding(false)}
        />
      )}
    </>
  )
}

export default function Connections() {
  const status = useQuery({ queryKey: ['plaid-status'], queryFn: () => api<PlaidStatus>('/plaid/status/') })
  const items = useQuery({ queryKey: ['plaid-items'], queryFn: () => api<PlaidItem[]>('/plaid/items/') })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const resumed = useRef(false)

  // Back from an OAuth bank: reopen Link with the same token to finish, then clean the URL.
  useEffect(() => {
    if (resumed.current) return
    resumed.current = true
    const pending = takePendingOAuth()
    if (!pending) return
    window.history.replaceState(null, '', window.location.pathname)
    setBusy(true)
    openPlaidLink(pending.linkToken, { resumeOAuth: true })
      .then(async (publicToken) => {
        if (!publicToken) return
        if (pending.itemId) await syncItem(pending.itemId)
        else await api('/plaid/exchange/', { body: { public_token: publicToken } })
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        setBusy(false)
        items.refetch()
      })
  }, [items])

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

      <ExchangesSection />
    </section>
  )
}
