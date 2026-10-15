import type { Account } from '../api'
import { CrudPage } from '../components/CrudPage'
import { formOf } from '../format'
import { useChoices } from '../hooks'

export default function Accounts() {
  const choices = useChoices()
  return (
    <CrudPage<Account>
      title="Cuentas"
      noun="Cuenta"
      endpoint="/accounts/"
      columns={[
        { label: 'Nombre', render: (r) => <strong>{r.name}</strong> },
        { label: 'Institución', render: (r) => r.institution },
        { label: 'Tipo', render: (r) => r.account_type_label },
        { label: 'Accesible', render: (r) => (r.is_liquid ? 'Sí' : <span className="tag">retiro</span>) },
        { label: 'Estado', className: 'hide-sm', render: (r) => (r.archived ? 'Archivada' : 'Activa') },
      ]}
      fields={[
        { name: 'name', label: 'Nombre', required: true },
        { name: 'institution', label: 'Institución' },
        { name: 'account_type', label: 'Tipo', type: 'select', options: choices.data?.account_types, required: true },
        { name: 'is_liquid', label: 'Accesible sin penalización (cuenta líquida)', type: 'checkbox' },
        { name: 'archived', label: 'Archivada (no cuenta en el patrimonio)', type: 'checkbox' },
        { name: 'notes', label: 'Notas', type: 'textarea' },
      ]}
      defaults={{ name: '', institution: '', account_type: 'brokerage', is_liquid: true, archived: false, notes: '' }}
      toForm={(r) => formOf(r, ['name', 'institution', 'account_type', 'is_liquid', 'archived', 'notes'])}
    />
  )
}
