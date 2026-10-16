import { useState } from 'react'
import { Link } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import type { Budget as BudgetData, BudgetItem, Spending } from '../api'
import { PALETTE } from '../palette'
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

const MONTH_NAMES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
const monthLabel = (ym: string) => `${MONTH_NAMES[Number(ym.slice(5, 7)) - 1]} ${ym.slice(2, 4)}`

/** What the cards and bank accounts actually spent, against the budget mapped to each spending category. */
function ActualSpending() {
  const [month, setMonth] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['spending', month],
    queryFn: () => api<Spending>(`/spending/${month ? `?month=${month}` : ''}`),
    placeholderData: keepPreviousData,
  })
  const s = q.data
  if (!s) return null
  const missing = s.sources.filter((x) => !x.importing)
  const hasData = s.history.some((h) => Number(h.spent) !== 0)
  const pace = Number(s.budget) * s.month_progress // what the budget allows by today

  return (
    <div className="card">
      <div className="card-head">
        <h2>Gasto real vs presupuesto</h2>
        <select value={s.month} onChange={(e) => setMonth(e.target.value)} aria-label="Mes">
          {[...s.history].reverse().map((h) => (
            <option key={h.month} value={h.month}>
              {monthLabel(h.month)}
            </option>
          ))}
        </select>
      </div>
      {missing.length > 0 && (
        <p className="muted small">
          Sin movimientos de: {missing.map((x) => x.account).join(', ')}. Actívalos en <Link to="/conexiones">Conexiones</Link> con
          “Importar movimientos”.
        </p>
      )}
      {!hasData ? (
        <p className="empty">Todavía no hay movimientos importados. Activa “Importar movimientos” en tus tarjetas y cuentas.</p>
      ) : (
        <>
          <div className="kpis">
            <div className="card kpi">
              <span className="kpi-label">Gastado en {monthLabel(s.month)}</span>
              <strong className={`kpi-value ${Number(s.spent) > (s.is_current_month ? pace : Number(s.budget)) && Number(s.budget) ? 'neg' : ''}`}>
                {money(s.spent, true)}
              </strong>
              <span className="kpi-sub">
                presupuesto {money(s.budget, true)}
                {s.is_current_month && Number(s.budget) > 0 && ` · a este ritmo de mes: ${money(pace, true)}`}
              </span>
            </div>
            <div className="card kpi">
              <span className="kpi-label">{Number(s.budget) - Number(s.spent) >= 0 ? 'Te queda' : 'Te pasaste'}</span>
              <strong className={`kpi-value ${Number(s.budget) - Number(s.spent) >= 0 ? 'pos' : 'neg'}`}>
                {money(Math.abs(Number(s.budget) - Number(s.spent)), true)}
              </strong>
              <span className="kpi-sub">de lo presupuestado en categorías con gasto</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={s.history.map((h) => ({ ...h, spent: Number(h.spent), label: monthLabel(h.month) }))}>
              <XAxis dataKey="label" tick={{ fontSize: 12 }} stroke="var(--muted)" />
              <YAxis tick={{ fontSize: 12 }} stroke="var(--muted)" width={56} tickFormatter={(v) => money(v, true)} />
              <Tooltip formatter={(v) => money(Number(v), true)} />
              <Bar dataKey="spent" name="Gastado" fill={PALETTE[0]} radius={[4, 4, 0, 0]} />
              {Number(s.budget) > 0 && <ReferenceLine y={Number(s.budget)} stroke={PALETTE[2]} strokeDasharray="4 4" />}
            </BarChart>
          </ResponsiveContainer>
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th>Categoría</th>
                  <th className="num">Presupuesto</th>
                  <th className="num">Gastado</th>
                  <th className="num">Queda</th>
                  <th className="num hide-sm">Promedio 3 meses</th>
                </tr>
              </thead>
              <tbody>
                {s.categories.map((c) => (
                  <tr key={c.category}>
                    <td>{c.label}</td>
                    <td className="num">{Number(c.budget) ? money(c.budget, true) : <span className="muted">—</span>}</td>
                    <td className="num">{money(c.spent, true)}</td>
                    <td className={`num ${Number(c.budget) && Number(c.remaining) < 0 ? 'neg' : ''}`}>
                      {Number(c.budget) ? money(c.remaining, true) : <span className="muted">sin presupuesto</span>}
                    </td>
                    <td className="num hide-sm">{money(c.avg_3m, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {s.top_merchants.length > 0 && (
            <>
              <h3 className="mt">Dónde más gastaste</h3>
              <ul className="legend">
                {s.top_merchants.map((m) => (
                  <li key={m.name}>
                    <span className="grow">{m.name}</span>
                    <span className="num">{money(m.spent, true)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="muted small">
            Compras menos reembolsos de tus tarjetas y cuentas; no cuenta transferencias entre tus cuentas, ingresos ni pagos de
            tarjeta. Para comparar, asigna a cada partida de gasto su “Categoría de gasto”
            {Number(s.unmapped_budget) > 0 && ` (hay ${money(s.unmapped_budget, true)}/mes de partidas sin asignar)`}.
          </p>
        </>
      )}
    </div>
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
          <ActualSpending />
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
          name: 'spending_category',
          label: 'Categoría de gasto (tarjetas)',
          type: 'select',
          options: choices.data?.spending_categories,
          show: (v) => v.kind === 'expense',
          help: 'Con qué movimientos de tus tarjetas se compara',
        },
        {
          name: 'essential',
          label: 'Esencial (lo seguirías pagando sin ingresos)',
          type: 'checkbox',
          show: (v) => v.kind === 'expense',
        },
        { name: 'notes', label: 'Notas' },
      ]}
      defaults={{
        name: '', kind: 'expense', amount: '', frequency: 'monthly', category: '', spending_category: '', essential: true, notes: '',
      }}
      toForm={(r) => formOf(r, ['name', 'kind', 'amount', 'frequency', 'category', 'spending_category', 'essential', 'notes'])}
    />
  )
}
