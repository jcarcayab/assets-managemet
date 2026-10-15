import { useState } from 'react'
import type { CashFlow, Transaction } from '../api'
import { CrudPage } from '../components/CrudPage'
import { useAccounts, useAssets, useChoices } from '../hooks'
import { money, qty, today, tone, formOf } from '../format'

export default function Transactions() {
  const [tab, setTab] = useState<'trades' | 'flows'>('trades')
  const [account, setAccount] = useState('')
  const accounts = useAccounts()
  const assets = useAssets()
  const choices = useChoices()

  const accountOptions = (accounts.data ?? []).map((a) => ({ value: String(a.id), label: a.name }))
  const assetOptions = (assets.data ?? []).map((a) => ({ value: String(a.id), label: `${a.symbol} — ${a.name}` }))
  const query = account ? `?account=${account}` : ''

  const filter = (
    <select value={account} onChange={(e) => setAccount(e.target.value)} aria-label="Filtrar por cuenta">
      <option value="">Todas las cuentas</option>
      {accountOptions.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )

  const tabs = (
    <div className="tabs" role="tablist">
      <button role="tab" aria-selected={tab === 'trades'} onClick={() => setTab('trades')}>
        Compras / ventas
      </button>
      <button role="tab" aria-selected={tab === 'flows'} onClick={() => setTab('flows')}>
        Depósitos / retiros
      </button>
    </div>
  )

  if (tab === 'flows') {
    return (
      <CrudPage<CashFlow>
        key="flows"
        title="Movimientos"
        noun="Depósito"
        endpoint="/cash-flows/"
        query={query}
        actions={filter}
        intro={
          <>
            {tabs}
            <p className="muted small">
              Dinero que entra (+) o sale (−) de una cuenta desde fuera. Se usa para medir el rendimiento real vs. lo depositado.
            </p>
          </>
        }
        columns={[
          { label: 'Fecha', render: (r) => r.date },
          { label: 'Cuenta', render: (r) => r.account_name },
          { label: 'Monto', className: 'num', render: (r) => <span className={tone(r.amount)}>{money(r.amount)}</span> },
          { label: 'Concepto', className: 'hide-sm', render: (r) => r.notes },
        ]}
        fields={[
          { name: 'account', label: 'Cuenta', type: 'select', options: accountOptions, required: true },
          { name: 'date', label: 'Fecha', type: 'date', required: true },
          { name: 'amount', label: 'Monto (USD)', type: 'number', required: true, help: 'Negativo para retiros' },
          { name: 'notes', label: 'Concepto' },
        ]}
        defaults={{ account, date: today(), amount: '', notes: '' }}
        toForm={(r) => formOf(r, ['account', 'date', 'amount', 'notes'])}
      />
    )
  }

  return (
    <CrudPage<Transaction>
      key="trades"
      title="Movimientos"
      noun="Movimiento"
      endpoint="/transactions/"
      query={query}
      actions={filter}
      intro={tabs}
      emptyText="No hay movimientos. Registra una compra para empezar."
      columns={[
        { label: 'Fecha', render: (r) => r.date },
        { label: 'Cuenta', className: 'hide-sm', render: (r) => r.account_name },
        {
          label: 'Tipo',
          render: (r) => <span className={`tag ${r.kind === 'buy' ? 'buy' : 'sell'}`}>{r.kind === 'buy' ? 'Compra' : 'Venta'}</span>,
        },
        { label: 'Activo', render: (r) => <strong>{r.asset_symbol}</strong> },
        { label: 'Cantidad', className: 'num', render: (r) => qty(r.quantity) },
        { label: 'Precio', className: 'num hide-sm', render: (r) => money(r.price) },
        { label: 'Total', className: 'num', render: (r) => money(r.total) },
      ]}
      fields={[
        { name: 'kind', label: 'Tipo', type: 'select', options: choices.data?.transaction_kinds, required: true },
        { name: 'date', label: 'Fecha', type: 'date', required: true },
        { name: 'account', label: 'Cuenta', type: 'select', options: accountOptions, required: true },
        { name: 'asset', label: 'Activo', type: 'select', options: assetOptions, required: true },
        { name: 'quantity', label: 'Cantidad', type: 'number', required: true },
        { name: 'price', label: 'Precio por unidad (USD)', type: 'number', required: true },
        { name: 'fees', label: 'Comisiones (USD)', type: 'number' },
        { name: 'external_id', label: 'Order ID' },
        { name: 'notes', label: 'Notas', type: 'textarea' },
      ]}
      defaults={{ kind: 'buy', date: today(), account, asset: '', quantity: '', price: '', fees: '0', external_id: '', notes: '' }}
      toForm={(r) => formOf(r, ['kind', 'date', 'account', 'asset', 'quantity', 'price', 'fees', 'external_id', 'notes'])}
    />
  )
}
