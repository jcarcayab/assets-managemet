import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Budget as BudgetData, BudgetItem } from '../api'
import { CrudPage } from '../components/CrudPage'
import { useChoices } from '../hooks'
import { formOf, money, pct } from '../format'

function Overview({ b }: { b: BudgetData }) {
  const covered = b.emergency_months === null ? null : Number(b.emergency_months)
  const target = Number(b.emergency_target_months)
  return (
    <>
      <div className="kpis">
        <div className="card kpi">
          <span className="kpi-label">Ingreso mensual neto</span>
          <strong className="kpi-value">{money(b.monthly_income, true)}</strong>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Gastos mensuales</span>
          <strong className="kpi-value">{money(b.monthly_expenses, true)}</strong>
          <span className="kpi-sub">esenciales {money(b.monthly_essential, true)}</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Tasa de ahorro</span>
          <strong className={`kpi-value ${Number(b.savings_rate ?? 0) >= 20 ? 'pos' : ''}`}>{pct(b.savings_rate)}</strong>
          <span className="kpi-sub">{money(b.monthly_savings, true)} / mes · 20%+ es sólido</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Fondo de emergencia</span>
          <strong className={`kpi-value ${covered !== null && covered < target ? 'neg' : 'pos'}`}>
            {covered === null ? '—' : `${covered.toFixed(1)} meses`}
          </strong>
          <span className="kpi-sub">
            objetivo {target} meses
            {Number(b.emergency_gap) > 0 ? ` · faltan ${money(b.emergency_gap, true)}` : ' · cubierto'}
          </span>
        </div>
      </div>
      {b.by_category.length > 0 && (
        <div className="card">
          <h2>Gastos por categoría</h2>
          <ul className="legend">
            {b.by_category.map((c) => (
              <li key={c.label}>
                <span className="grow">{c.label}</span>
                <span className="num">{money(c.monthly, true)}</span>
                <span className="num muted w-pct">{pct(c.share, 0)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

export default function Budget() {
  const choices = useChoices()
  const budget = useQuery({ queryKey: ['budget'], queryFn: () => api<BudgetData>('/budget/') })

  return (
    <CrudPage<BudgetItem>
      title="Presupuesto"
      noun="Partida"
      endpoint="/budget-items/"
      intro={
        <>
          <p className="muted small">
            Ingresos netos (después de impuestos) y gastos recurrentes. El fondo de emergencia cuenta solo el efectivo en cuentas
            accesibles frente a tus gastos esenciales. Los gastos anuales alimentan la proyección de retiro.
          </p>
          {budget.data && <Overview b={budget.data} />}
        </>
      }
      emptyText="Añade tu salario y tus gastos fijos para ver tasa de ahorro y fondo de emergencia."
      columns={[
        { label: 'Partida', render: (r) => <strong>{r.name}</strong> },
        { label: 'Tipo', render: (r) => <span className={`tag ${r.kind === 'income' ? 'buy' : ''}`}>{r.kind_label}</span> },
        { label: 'Categoría', className: 'hide-sm', render: (r) => r.category || '—' },
        { label: 'Esencial', className: 'hide-sm', render: (r) => (r.kind === 'expense' ? (r.essential ? 'Sí' : 'No') : '—') },
        { label: 'Mensual', className: 'num', render: (r) => money(r.monthly) },
      ]}
      fields={[
        { name: 'name', label: 'Nombre', required: true },
        { name: 'kind', label: 'Tipo', type: 'select', options: choices.data?.budget_kinds, required: true },
        { name: 'amount', label: 'Monto (USD)', type: 'number', required: true },
        { name: 'frequency', label: 'Frecuencia', type: 'select', options: choices.data?.frequencies, required: true },
        { name: 'category', label: 'Categoría', help: 'Ej. Vivienda, Comida, Transporte' },
        {
          name: 'essential',
          label: 'Esencial (lo seguirías pagando sin ingresos)',
          type: 'checkbox',
          show: (v) => v.kind === 'expense',
        },
        { name: 'notes', label: 'Notas' },
      ]}
      defaults={{ name: '', kind: 'expense', amount: '', frequency: 'monthly', category: '', essential: true, notes: '' }}
      toForm={(r) => formOf(r, ['name', 'kind', 'amount', 'frequency', 'category', 'essential', 'notes'])}
    />
  )
}
