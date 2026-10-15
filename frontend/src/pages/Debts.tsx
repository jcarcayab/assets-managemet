import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Debts as DebtsData, Liability } from '../api'
import { CrudPage } from '../components/CrudPage'
import { useChoices } from '../hooks'
import { formOf, money, pct } from '../format'

const VERDICT = {
  pay_first: { label: 'Pagar antes de invertir', className: 'sell' },
  either: { label: 'Similar a invertir', className: '' },
  invest: { label: 'Mejor invertir', className: 'buy' },
}

function duration(months: number | null) {
  if (months === null) return 'nunca (el pago no cubre intereses)'
  if (months < 12) return `${months} meses`
  return `${(months / 12).toFixed(1)} años`
}

function Plan({ d }: { d: DebtsData }) {
  return (
    <>
      <div className="kpis">
        <div className="card kpi">
          <span className="kpi-label">Deuda total</span>
          <strong className="kpi-value neg">{money(d.total, true)}</strong>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Tasa promedio</span>
          <strong className="kpi-value">{pct(d.weighted_rate_pct, 2)}</strong>
          <span className="kpi-sub">vs. rendimiento esperado {pct(d.expected_return_pct, 1)}</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Intereses al año</span>
          <strong className="kpi-value neg">{money(d.annual_interest, true)}</strong>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Pagos mínimos</span>
          <strong className="kpi-value">{money(d.minimum_payments, true)}</strong>
          <span className="kpi-sub">al mes</span>
        </div>
      </div>
      <div className="card">
        <h2>Orden de pago (avalancha)</h2>
        <p className="muted small">
          Paga el mínimo en todas y todo lo extra a la de mayor tasa: es lo que menos intereses cuesta. Pagar una deuda con tasa
          mayor a lo que esperas ganar invirtiendo es un rendimiento garantizado.
        </p>
        <div className="table-wrap flush">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Deuda</th>
                <th className="num">Tasa</th>
                <th className="num">Saldo</th>
                <th className="num hide-sm">Plazo con el mínimo</th>
                <th>Recomendación</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.order}</td>
                  <td>
                    <strong>{r.name}</strong>
                    <small className="block muted">{r.kind_label}</small>
                  </td>
                  <td className="num">{pct(r.interest_rate_pct, 2)}</td>
                  <td className="num">{money(r.balance, true)}</td>
                  <td className="num hide-sm">
                    {duration(r.months_to_payoff)}
                    {r.total_interest !== null && <small className="block muted">intereses {money(r.total_interest, true)}</small>}
                  </td>
                  <td>
                    <span className={`tag ${VERDICT[r.verdict].className}`}>{VERDICT[r.verdict].label}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

export default function Debts() {
  const choices = useChoices()
  const debts = useQuery({ queryKey: ['debts'], queryFn: () => api<DebtsData>('/debts/') })

  return (
    <CrudPage<Liability>
      title="Deudas"
      noun="Deuda"
      endpoint="/liabilities/"
      intro={
        <>
          <p className="muted small">Hipoteca, tarjetas y préstamos. Se restan del patrimonio. Actualiza el saldo cuando cambie.</p>
          {debts.data && debts.data.rows.length > 0 && <Plan d={debts.data} />}
        </>
      }
      emptyText="Sin deudas registradas."
      columns={[
        { label: 'Deuda', render: (r) => <strong>{r.name}</strong> },
        { label: 'Tipo', className: 'hide-sm', render: (r) => r.kind_label },
        { label: 'Tasa', className: 'num', render: (r) => pct(r.interest_rate_pct, 2) },
        { label: 'Saldo', className: 'num', render: (r) => money(r.balance) },
        { label: 'Actualizado', className: 'hide-sm', render: (r) => r.updated_at.slice(0, 10) },
      ]}
      fields={[
        { name: 'name', label: 'Nombre', required: true },
        { name: 'kind', label: 'Tipo', type: 'select', options: choices.data?.liability_kinds, required: true },
        { name: 'balance', label: 'Saldo pendiente (USD)', type: 'number', required: true },
        { name: 'interest_rate_pct', label: 'Tasa anual / APR (%)', type: 'number' },
        { name: 'minimum_payment', label: 'Pago mínimo mensual (USD)', type: 'number' },
        { name: 'notes', label: 'Notas' },
      ]}
      defaults={{ name: '', kind: 'credit_card', balance: '', interest_rate_pct: '', minimum_payment: '', notes: '' }}
      toForm={(r) => formOf(r, ['name', 'kind', 'balance', 'interest_rate_pct', 'minimum_payment', 'notes'])}
    />
  )
}
