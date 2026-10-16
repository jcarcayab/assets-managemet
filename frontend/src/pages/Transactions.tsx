import { useState } from 'react'
import type { CashFlow, Transaction, TransactionKind } from '../api'
import { CrudPage } from '../components/CrudPage'
import { CsvImport } from '../components/CsvImport'
import type { FormValues } from '../components/FormModal'
import { useAccounts, useAssets, useChoices } from '../hooks'
import { formOf, money, qty, today, tone } from '../format'

const is = (...kinds: TransactionKind[]) => (v: FormValues) => kinds.includes(v.kind as TransactionKind)

const TAG: Partial<Record<TransactionKind, string>> = {
  buy: 'buy',
  staking: 'buy',
  dividend: 'buy',
  interest: 'buy',
  sell: 'sell',
  fee: 'sell',
}

function detail(r: Transaction) {
  switch (r.kind) {
    case 'dividend':
    case 'interest':
    case 'fee':
      return money(r.amount)
    case 'split':
      return `${qty(r.quantity)} : 1`
    case 'transfer':
      return `${qty(r.quantity)} → ${r.to_account_name ?? '?'}`
    default:
      return `${qty(r.quantity)} × ${money(r.price)}`
  }
}

export default function Transactions() {
  const [tab, setTab] = useState<'trades' | 'flows'>('trades')
  const [account, setAccount] = useState('')
  const [asset, setAsset] = useState('')
  const [kind, setKind] = useState('')
  const [importing, setImporting] = useState(false)
  const accounts = useAccounts()
  const assets = useAssets()
  const choices = useChoices()

  const accountOptions = (accounts.data ?? []).map((a) => ({ value: String(a.id), label: a.name }))
  const assetOptions = (assets.data ?? []).map((a) => ({ value: String(a.id), label: `${a.symbol} — ${a.name}` }))
  const kindOptions = (tab === 'trades' ? choices.data?.transaction_kinds : choices.data?.cash_flow_kinds) ?? []
  const params = new URLSearchParams()
  if (account) params.set('account', account)
  if (tab === 'trades' && asset) params.set('asset', asset)
  if (kind) params.set('kind', kind)
  const query = params.toString() ? `?${params}` : ''

  const select = (label: string, value: string, set: (v: string) => void, options: { value: string; label: string }[]) => (
    <select value={value} onChange={(e) => set(e.target.value)} aria-label={`Filtrar por ${label.toLowerCase()}`}>
      <option value="">{label}: todos</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )

  const filter = (
    <>
      {select('Cuenta', account, setAccount, accountOptions)}
      {tab === 'trades' && select('Activo', asset, setAsset, assetOptions)}
      {select('Tipo', kind, setKind, kindOptions)}
      <button className="btn" onClick={() => setImporting(true)}>
        Importar CSV
      </button>
      {importing && <CsvImport accounts={accountOptions} initialAccount={account} onClose={() => setImporting(false)} />}
    </>
  )

  const switchTab = (next: 'trades' | 'flows') => {
    setTab(next)
    setKind('') // transaction and cash-flow kinds are different lists
  }

  const tabs = (
    <div className="tabs" role="tablist">
      <button role="tab" aria-selected={tab === 'trades'} onClick={() => switchTab('trades')}>
        Operaciones
      </button>
      <button role="tab" aria-selected={tab === 'flows'} onClick={() => switchTab('flows')}>
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
        paginated
        actions={filter}
        intro={
          <>
            {tabs}
            <p className="muted small">
              Dinero que entra o sale de una cuenta desde fuera (incluye el match del empleador en el 401k). Se usa para medir el
              rendimiento contra lo depositado.
            </p>
          </>
        }
        columns={[
          { label: 'Fecha', render: (r) => r.date },
          { label: 'Cuenta', render: (r) => r.account_name },
          { label: 'Tipo', className: 'hide-sm', render: (r) => r.kind_label },
          { label: 'Monto', className: 'num', render: (r) => <span className={tone(r.amount)}>{money(r.amount)}</span> },
          { label: 'Concepto', className: 'hide-sm', render: (r) => r.notes },
        ]}
        fields={[
          { name: 'kind', label: 'Tipo', type: 'select', options: choices.data?.cash_flow_kinds, required: true },
          { name: 'account', label: 'Cuenta', type: 'select', options: accountOptions, required: true },
          { name: 'date', label: 'Fecha', type: 'date', required: true },
          { name: 'amount', label: 'Monto (USD)', type: 'number', required: true, help: 'El signo lo pone el tipo' },
          { name: 'notes', label: 'Concepto' },
        ]}
        defaults={{ kind: 'deposit', account, date: today(), amount: '', notes: '' }}
        toForm={(r) => ({ ...formOf(r, ['kind', 'account', 'date', 'notes']), amount: String(Math.abs(r.amount)) })}
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
      paginated
      actions={filter}
      intro={tabs}
      emptyText="No hay movimientos. Registra una compra para empezar."
      columns={[
        { label: 'Fecha', render: (r) => r.date },
        { label: 'Cuenta', className: 'hide-sm', render: (r) => r.account_name },
        { label: 'Tipo', render: (r) => <span className={`tag ${TAG[r.kind] ?? ''}`}>{r.kind_label}</span> },
        { label: 'Activo', render: (r) => <strong>{r.asset_symbol}</strong> },
        { label: 'Detalle', className: 'num hide-sm', render: detail },
        { label: 'Total', className: 'num', render: (r) => (r.kind === 'split' ? '—' : money(r.total)) },
      ]}
      fields={[
        { name: 'kind', label: 'Tipo', type: 'select', options: choices.data?.transaction_kinds, required: true },
        { name: 'date', label: 'Fecha', type: 'date', required: true },
        { name: 'account', label: 'Cuenta', type: 'select', options: accountOptions, required: true },
        {
          name: 'asset',
          label: 'Activo',
          type: 'select',
          options: assetOptions,
          required: true,
          help: 'Dividendo: el activo que paga. Interés: USD.',
        },
        {
          name: 'to_account',
          label: 'Cuenta destino',
          type: 'select',
          options: accountOptions,
          show: is('transfer'),
          nullable: true,
        },
        {
          name: 'quantity',
          label: 'Cantidad (unidades, o ratio en un split)',
          type: 'number',
          show: is('buy', 'sell', 'staking', 'split', 'transfer'),
          help: 'Split 2-por-1 = 2',
        },
        {
          name: 'price',
          label: 'Precio por unidad (USD)',
          type: 'number',
          show: is('buy', 'sell', 'staking', 'transfer'),
          help: 'Staking: valor de mercado al recibirlo. Transferencia: precio de ese día (opcional).',
        },
        { name: 'fees', label: 'Comisiones (USD)', type: 'number', show: is('buy', 'sell') },
        {
          name: 'amount',
          label: 'Monto (USD)',
          type: 'number',
          show: is('dividend', 'interest', 'fee'),
          help: 'Se abona (o descuenta) del efectivo de la cuenta automáticamente.',
        },
        { name: 'external_id', label: 'Order ID', show: is('buy', 'sell') },
        { name: 'notes', label: 'Notas', type: 'textarea' },
      ]}
      defaults={{
        kind: 'buy', date: today(), account, asset: '', to_account: '', quantity: '', price: '', fees: '0', amount: '',
        external_id: '', notes: '',
      }}
      toForm={(r) =>
        formOf(r, ['kind', 'date', 'account', 'asset', 'to_account', 'quantity', 'price', 'fees', 'amount', 'external_id', 'notes'])
      }
    />
  )
}
