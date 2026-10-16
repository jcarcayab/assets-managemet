import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError, apiUpload } from '../api'
import type { CsvPreview } from '../api'
import { money, qty } from '../format'

const TEMPLATE = `date,type,symbol,quantity,price,fees,amount,notes,id
2024-01-02,deposit,,,,,5000,Transferencia inicial,
2024-01-03,buy,VOO,10,400.50,1,,,
2024-02-01,dividend,VOO,,,,12.34,,
2024-03-01,sell,VOO,4,450,0,,,orden-123
2024-03-31,interest,,,,,1.25,Interés del mes,
`
const PREVIEW_ROWS = 50

function downloadTemplate() {
  const url = URL.createObjectURL(new Blob([TEMPLATE], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'plantilla-movimientos.csv'
  a.click()
  URL.revokeObjectURL(url)
}

/** Upload a CSV of movements into one account: preview first, then import (all or nothing). */
export function CsvImport({ accounts, initialAccount, onClose }: { accounts: { value: string; label: string }[]; initialAccount: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [account, setAccount] = useState(initialAccount)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const send = async (dryRun: boolean) => {
    if (!file || !account) return
    setBusy(true)
    setError(null)
    const form = new FormData()
    form.append('account', account)
    form.append('file', file)
    form.append('dry_run', String(dryRun))
    try {
      const data = await apiUpload<CsvPreview>('/import/csv/', form)
      setPreview(data)
      if (!dryRun) qc.invalidateQueries()
    } catch (e) {
      const data = e instanceof ApiError ? (e.data as CsvPreview | null) : null
      if (data?.rows) setPreview(data)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const done = preview?.created
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-label="Importar CSV">
        <header className="modal-head">
          <h2>Importar movimientos desde CSV</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Cerrar">
            ×
          </button>
        </header>
        <p className="muted small">
          Columnas: <code>date, type, symbol, quantity, price, fees, amount, notes, id</code> (también en español). Tipos: buy, sell,
          dividend, interest, fee, staking, split, deposit, withdrawal, employer. Volver a importar el mismo archivo no duplica nada.{' '}
          <button type="button" className="link" onClick={downloadTemplate}>
            Descargar plantilla
          </button>
        </p>
        <div className="form-grid">
          <label>
            <span>Cuenta *</span>
            <select value={account} onChange={(e) => (setAccount(e.target.value), setPreview(null))}>
              <option value="">—</option>
              {accounts.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Archivo CSV *</span>
            <input type="file" accept=".csv,text/csv" onChange={(e) => (setFile(e.target.files?.[0] ?? null), setPreview(null))} />
          </label>
        </div>

        {preview && !done && (
          <>
            <p className="small">
              <strong>{preview.new_count}</strong> movimientos nuevos
              {preview.duplicate_count > 0 && `, ${preview.duplicate_count} ya importados (se omiten)`}
              {preview.errors.length > 0 && <span className="neg">, {preview.errors.length} con errores</span>}.
              {preview.new_symbols.length > 0 && ` Activos nuevos (precio de Yahoo): ${preview.new_symbols.join(', ')}.`}
            </p>
            {preview.errors.length > 0 && (
              <ul className="error small">
                {preview.errors.slice(0, 20).map((e) => (
                  <li key={e.line}>
                    Línea {e.line}: {e.error}
                  </li>
                ))}
              </ul>
            )}
            <div className="table-wrap flush preview-table">
              <table>
                <thead>
                  <tr>
                    <th>Línea</th>
                    <th>Fecha</th>
                    <th>Tipo</th>
                    <th>Activo</th>
                    <th className="num">Cantidad</th>
                    <th className="num">Precio</th>
                    <th className="num">Monto</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.slice(0, PREVIEW_ROWS).map((r) => (
                    <tr key={r.line} className={r.status === 'duplicate' ? 'muted' : ''}>
                      <td>{r.line}</td>
                      <td>{r.date}</td>
                      <td>
                        {r.kind}
                        {r.status === 'duplicate' && ' (ya importado)'}
                      </td>
                      <td>{r.symbol || '—'}</td>
                      <td className="num">{r.quantity ? qty(r.quantity) : '—'}</td>
                      <td className="num">{r.price ? money(r.price) : '—'}</td>
                      <td className="num">{r.amount ? money(r.amount) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.rows.length > PREVIEW_ROWS && <p className="muted small">… y {preview.rows.length - PREVIEW_ROWS} filas más.</p>}
          </>
        )}
        {done && (
          <p className="pos">
            Importados: {done.transactions} movimientos y {done.cash_flows} depósitos/retiros
            {done.assets > 0 && `, ${done.assets} activos nuevos`}
            {done.duplicates > 0 && ` (${done.duplicates} ya estaban)`}.
          </p>
        )}
        {error && !done && <p className="error">{error}</p>}

        <footer className="modal-foot">
          <button type="button" className="btn" onClick={onClose}>
            {done ? 'Cerrar' : 'Cancelar'}
          </button>
          {!done && (
            <button type="button" className="btn" disabled={busy || !file || !account} onClick={() => send(true)}>
              Vista previa
            </button>
          )}
          {!done && preview && preview.errors.length === 0 && preview.new_count > 0 && (
            <button type="button" className="btn primary" disabled={busy} onClick={() => send(false)}>
              Importar {preview.new_count}
            </button>
          )}
        </footer>
      </div>
    </div>
  )
}
