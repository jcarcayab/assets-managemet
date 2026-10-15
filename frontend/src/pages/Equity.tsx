import type { EquityGrant } from '../api'
import { CrudPage } from '../components/CrudPage'
import { useAccounts } from '../hooks'
import { money, qty, formOf } from '../format'

export default function Equity() {
  const accounts = useAccounts()
  const accountOptions = (accounts.data ?? [])
    .filter((a) => a.account_type === 'private_equity')
    .map((a) => ({ value: String(a.id), label: a.name }))

  return (
    <CrudPage<EquityGrant>
      title="Equity privada"
      noun="Grant"
      endpoint="/equity-grants/"
      intro={
        <p className="muted small">
          Opciones sin ejercer se valoran a valor intrínseco: (FMV − strike) × opciones. Ejercidas: FMV × acciones, con costo = strike.
          {!accountOptions.length && ' Primero crea una cuenta de tipo “Equity privada”.'}
        </p>
      }
      columns={[
        { label: 'Empresa', render: (r) => <strong>{r.company}</strong> },
        { label: 'Opciones', className: 'num', render: (r) => qty(r.quantity) },
        { label: 'Strike', className: 'num', render: (r) => money(r.strike) },
        { label: 'FMV', className: 'num', render: (r) => money(r.fmv) },
        { label: 'Ejercidas', render: (r) => (r.exercised ? 'Sí' : 'No') },
        { label: 'Valor', className: 'num', render: (r) => money(r.market_value, true) },
      ]}
      fields={[
        { name: 'account', label: 'Cuenta', type: 'select', options: accountOptions, required: true },
        { name: 'company', label: 'Empresa', required: true },
        { name: 'quantity', label: 'Número de opciones/acciones', type: 'number', required: true },
        { name: 'strike', label: 'Strike (USD)', type: 'number', required: true },
        { name: 'fmv', label: 'FMV por acción (USD)', type: 'number', required: true },
        { name: 'grant_date', label: 'Fecha de grant', type: 'date', nullable: true },
        { name: 'sector', label: 'Sector', help: 'Para medir concentración, ej. Crypto' },
        { name: 'exercised', label: 'Ejercidas', type: 'checkbox' },
        { name: 'notes', label: 'Notas (vesting, etc.)', type: 'textarea' },
      ]}
      defaults={{
        account: accountOptions[0]?.value ?? '', company: '', quantity: '', strike: '', fmv: '', grant_date: '', sector: '',
        exercised: false, notes: '',
      }}
      toForm={(r) => formOf(r, ['account', 'company', 'quantity', 'strike', 'fmv', 'grant_date', 'sector', 'exercised', 'notes'])}
    />
  )
}
