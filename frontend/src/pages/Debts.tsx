import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Debts as DebtsData, Liability, SavingsPlan } from '../api'
import { CrudPage } from '../components/CrudPage'
import type { FormValues } from '../components/FormModal'
import { useChoices } from '../hooks'
import { formOf, money, pct } from '../format'

type Row = DebtsData['rows'][number]

const VERDICT = {
  pay_first: { label: 'Pagar antes de invertir', className: 'sell' },
  either: { label: 'Similar a invertir', className: '' },
  invest: { label: 'Mejor invertir', className: 'buy' },
  promo: { label: 'Promoción', className: 'buy' },
}

function duration(months: number | null) {
  if (months === null) return 'nunca (el pago no cubre intereses)'
  if (months < 12) return `${months} meses`
  return `${(months / 12).toFixed(1)} años`
}

function Rate({ r }: { r: Row }) {
  if (!r.in_promo) return <>{pct(r.interest_rate_pct, 2)}</>
  return (
    <>
      {pct(r.promo_rate_pct, 2)}
      <small className="block muted">
        hasta {r.promo_end_date}, luego {pct(r.interest_rate_pct, 2)}
      </small>
    </>
  )
}

function Advice({ r }: { r: Row }) {
  const v = VERDICT[r.verdict]
  return (
    <>
      <span className={`tag ${v.className}`}>{v.label}</span>
      {r.in_promo && (
        <small className={`block ${r.clears_in_promo ? 'muted' : 'neg'}`}>
          {r.clears_in_promo
            ? 'con el mínimo la liquidas a tiempo; no adelantes pagos'
            : `paga ${money(r.payment_to_clear_promo)}/mes para liquidarla antes del fin`}
        </small>
      )}
    </>
  )
}

/** Park each chosen debt's balance in a savings account and pay only the minimum from it: what does it earn? */
function SavingsPlanCard({ d }: { d: DebtsData }) {
  const open = d.rows.filter((r) => r.balance > 0)
  const [apy, setApy] = useState('3.1')
  const [chosen, setChosen] = useState<Set<number>>(() => new Set(open.filter((r) => Number(r.current_rate_pct) === 0).map((r) => r.id)))
  const ids = [...chosen].sort((a, b) => a - b).join(',')
  const plan = useQuery({
    queryKey: ['savings-plan', apy, ids],
    queryFn: () => api<SavingsPlan>(`/debts/savings-plan/?apy=${encodeURIComponent(apy || '0')}&ids=${ids}`),
    placeholderData: keepPreviousData,
  })
  const toggle = (id: number) => {
    const next = new Set(chosen)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setChosen(next)
  }
  const p = plan.data

  return (
    <div className="card">
      <h2>¿Y si guardas el dinero en una cuenta de ahorro?</h2>
      <p className="muted small">
        Pones hoy el saldo de las deudas elegidas en una cuenta de ahorro (high-yield) y pagas solo el mínimo desde ella. Cada mes la
        cuenta genera intereses; si una promoción termina antes de liquidar la deuda, ese mes pagas el resto desde la cuenta, para que no
        te cobren la tasa normal ni intereses diferidos. Lo que queda al final es tu ganancia.
      </p>
      <div className="form-grid">
        <label>
          <span>Rendimiento de la cuenta (APY %)</span>
          <input type="number" inputMode="decimal" step="0.1" min="0" max="25" value={apy} onChange={(e) => setApy(e.target.value)} />
        </label>
      </div>
      <div className="check-list mt">
        {open.map((r) => (
          <label key={r.id} className="check">
            <input type="checkbox" checked={chosen.has(r.id)} onChange={() => toggle(r.id)} />
            {r.name} <span className="muted small">· {money(r.balance, true)} al {pct(Number(r.current_rate_pct), 2)}</span>
          </label>
        ))}
      </div>
      {plan.error && <p className="error">{String(plan.error)}</p>}
      {p && p.rows.length > 0 && (
        <>
          <div className="kpis">
            <div className="card kpi">
              <span className="kpi-label">Dinero a apartar hoy</span>
              <strong className="kpi-value">{money(p.totals.balance, true)}</strong>
              <span className="kpi-sub">{p.rows.length} deudas</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">Intereses ganados</span>
              <strong className="kpi-value pos">{money(p.totals.interest_earned)}</strong>
              <span className="kpi-sub">al {pct(Number(p.apy_pct), 2)} hasta liquidarlas{p.totals.months ? ` (${duration(p.totals.months)})` : ''}</span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">Ganancia neta</span>
              <strong className={`kpi-value ${p.totals.net_after_tax >= 0 ? 'pos' : 'neg'}`}>{money(p.totals.net_after_tax)}</strong>
              <span className="kpi-sub">tras impuesto del {pct(Number(p.tax_pct), 0)} e intereses de la deuda</span>
            </div>
          </div>
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th>Deuda</th>
                  <th className="num">Apartar</th>
                  <th className="num hide-sm">Pago</th>
                  <th className="num">Plazo</th>
                  <th className="num">Intereses ganados</th>
                  <th className="num">Neto</th>
                </tr>
              </thead>
              <tbody>
                {p.rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <strong>{r.name}</strong>
                      {r.note && <small className="block muted">{r.note}</small>}
                      {r.debt_interest > 0 && <small className="block neg">La deuda cobra {money(r.debt_interest)} de intereses.</small>}
                    </td>
                    <td className="num">{money(r.balance, true)}</td>
                    <td className="num hide-sm">{money(r.minimum_payment)}</td>
                    <td className="num">{r.months ? duration(r.months) : '—'}</td>
                    <td className="num">{money(r.interest_earned)}</td>
                    <td className={`num ${r.net_after_tax !== null && r.net_after_tax < 0 ? 'neg' : ''}`}>
                      {r.net_after_tax === null ? '—' : money(r.net_after_tax)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            Supone el APY fijo; en cuentas de ahorro la tasa puede bajar. Los intereses de la cuenta pagan impuesto como ingreso ordinario
            (tu tasa en Ajustes).
          </p>
        </>
      )}
    </div>
  )
}

function Plan({ d }: { d: DebtsData }) {
  const paidOff = d.rows.filter((r) => r.balance <= 0).length
  return (
    <>
      {d.alerts.map((a) => (
        <div key={a.name} className="card warn">
          <strong>{a.name}:</strong> {a.message}
        </div>
      ))}
      <div className="kpis">
        <div className="card kpi">
          <span className="kpi-label">Deuda total</span>
          <strong className="kpi-value neg">{money(d.total, true)}</strong>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Tasa promedio hoy</span>
          <strong className="kpi-value">{pct(d.weighted_rate_pct, 2)}</strong>
          <span className="kpi-sub">vs. rendimiento esperado {pct(d.expected_return_pct, 1)}</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Intereses próximos 12 meses</span>
          <strong className="kpi-value neg">{money(d.annual_interest, true)}</strong>
          <span className="kpi-sub">pagando el mínimo</span>
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
          Paga el mínimo en todas y todo lo extra a la de mayor tasa actual. Una deuda en promoción al 0% no se adelanta (ese dinero
          rinde más en otro lado), pero hay que liquidarla antes de que termine la promoción.
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
              {d.rows.filter((r) => r.balance > 0).map((r) => (
                <tr key={r.id}>
                  <td>{r.order}</td>
                  <td>
                    <strong>{r.name}</strong>
                    <small className="block muted">
                      {r.kind_label}
                      {r.deferred_interest && ' · intereses diferidos'}
                    </small>
                  </td>
                  <td className="num">
                    <Rate r={r} />
                  </td>
                  <td className="num">{money(r.balance, true)}</td>
                  <td className="num hide-sm">
                    {duration(r.months_to_payoff)}
                    {r.total_interest !== null && <small className="block muted">intereses {money(r.total_interest, true)}</small>}
                  </td>
                  <td>
                    <Advice r={r} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {paidOff > 0 && (
          <p className="muted small">
            {paidOff === 1 ? 'Una deuda con saldo $0 no aparece' : `${paidOff} deudas con saldo $0 no aparecen`} en el orden de pago; siguen
            en la lista de abajo.
          </p>
        )}
      </div>
    </>
  )
}

const hasPromo = (v: FormValues) => Boolean(v.has_promo)

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
          {debts.data && debts.data.rows.length > 0 && (
            <>
              <Plan d={debts.data} />
              <SavingsPlanCard d={debts.data} />
            </>
          )}
        </>
      }
      emptyText="Sin deudas registradas."
      columns={[
        { label: 'Deuda', render: (r) => <strong>{r.name}</strong> },
        { label: 'Tipo', className: 'hide-sm', render: (r) => r.kind_label },
        {
          label: 'Tasa',
          className: 'num',
          render: (r) =>
            r.promo_end_date ? `${pct(r.promo_rate_pct, 2)} → ${pct(r.interest_rate_pct, 2)}` : pct(r.interest_rate_pct, 2),
        },
        { label: 'Saldo', className: 'num', render: (r) => money(r.balance) },
        { label: 'Actualizado', className: 'hide-sm', render: (r) => r.updated_at.slice(0, 10) },
      ]}
      fields={[
        { name: 'name', label: 'Nombre', required: true },
        { name: 'kind', label: 'Tipo', type: 'select', options: choices.data?.liability_kinds, required: true },
        { name: 'balance', label: 'Saldo pendiente (USD)', type: 'number', required: true },
        { name: 'interest_rate_pct', label: 'Tasa anual normal / APR (%)', type: 'number', help: 'La que aplica sin promoción' },
        { name: 'minimum_payment', label: 'Pago mínimo mensual (USD)', type: 'number' },
        { name: 'has_promo', label: 'Tiene tasa promocional (p.ej. 0% el primer año)', type: 'checkbox', local: true },
        { name: 'promo_rate_pct', label: 'Tasa promocional (%)', type: 'number', nullable: true, show: hasPromo },
        { name: 'promo_end_date', label: 'Fin de la promoción', type: 'date', nullable: true, show: hasPromo },
        {
          name: 'deferred_interest',
          label: 'Intereses diferidos (si no la liquido a tiempo me cobran todo el interés)',
          type: 'checkbox',
          show: hasPromo,
        },
        { name: 'notes', label: 'Notas' },
      ]}
      defaults={{
        name: '', kind: 'credit_card', balance: '', interest_rate_pct: '', minimum_payment: '', has_promo: false,
        promo_rate_pct: '0', promo_end_date: '', deferred_interest: false, notes: '',
      }}
      toForm={(r) => ({
        ...formOf(r, [
          'name', 'kind', 'balance', 'interest_rate_pct', 'minimum_payment', 'promo_rate_pct', 'promo_end_date',
          'deferred_interest', 'notes',
        ]),
        has_promo: Boolean(r.promo_end_date),
      })}
      toPayload={(body, values) =>
        values.has_promo ? body : { ...body, promo_rate_pct: null, promo_end_date: null, deferred_interest: false }
      }
    />
  )
}
