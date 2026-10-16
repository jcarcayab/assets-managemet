import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { EquityExerciseRow, EquityGrant, EquitySummary } from '../api'
import { CrudPage } from '../components/CrudPage'
import { FormModal } from '../components/FormModal'
import type { Field, FormValues } from '../components/FormModal'
import { useAccounts, useChoices, useWrite } from '../hooks'
import { formOf, money, pct, qty, today } from '../format'

type GrantRow = EquitySummary['grants'][number]

const EXERCISE_FIELDS: Field[] = [
  { name: 'date', label: 'Fecha del ejercicio', type: 'date', required: true },
  { name: 'quantity', label: 'Opciones ejercidas', type: 'number', required: true },
  { name: 'fmv', label: 'FMV por acción ese día (USD)', type: 'number', required: true, help: 'El 409A vigente ese día' },
  { name: 'notes', label: 'Notas' },
]

/** Record (or edit) one exercise of a grant's options. */
function ExerciseModal({ grant, row, onClose }: { grant: GrantRow; row: EquityExerciseRow | null; onClose: () => void }) {
  const save = useWrite((body: Record<string, unknown>) =>
    row
      ? api(`/equity-exercises/${row.id}/`, { method: 'PATCH', body })
      : api('/equity-exercises/', { body: { ...body, grant: grant.id } }),
  )
  const remove = useWrite((id: number) => api(`/equity-exercises/${id}/`, { method: 'DELETE' }))
  return (
    <FormModal
      title={`${row ? 'Editar' : 'Registrar'} ejercicio: ${grant.company} (strike ${money(grant.strike)})`}
      fields={EXERCISE_FIELDS}
      initial={
        row
          ? { date: row.date, quantity: String(row.quantity), fmv: String(row.fmv), notes: row.notes }
          : { date: today(), quantity: '', fmv: String(grant.fmv), notes: '' }
      }
      onSubmit={(body) => save.mutateAsync(body)}
      onDelete={row ? () => remove.mutateAsync(row.id) : undefined}
      onClose={onClose}
    />
  )
}

function Exercises({ g, onEdit }: { g: GrantRow; onEdit: (row: EquityExerciseRow) => void }) {
  if (!g.exercises.length) return null
  const nso = g.grant_type === 'nso'
  return (
    <div className="table-wrap flush mt">
      <table>
        <thead>
          <tr>
            <th>Ejercicio</th>
            <th className="num">Acciones</th>
            <th className="num hide-sm">FMV</th>
            <th className="num">Pagado</th>
            <th className="num">{nso ? 'Impuesto (NSO)' : 'Spread (AMT)'}</th>
          </tr>
        </thead>
        <tbody>
          {g.exercises.map((e) => (
            <tr key={e.id} className="clickable" onClick={() => onEdit(e)}>
              <td>{e.date}</td>
              <td className="num">{qty(e.quantity)}</td>
              <td className="num hide-sm">{money(e.fmv)}</td>
              <td className="num">{money(e.cost)}</td>
              <td className="num">{money(nso ? e.income_tax : e.amt_preference)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const isOption = (v: FormValues) => v.grant_type !== 'shares'
const hasVesting = (v: FormValues) => Boolean(v.vesting_start)

function Scenarios({ data }: { data: EquitySummary }) {
  return (
    <>
      {data.scenarios.map((c) => (
        <div className="card" key={c.company}>
          <div className="card-head">
            <h2>
              {c.company}: si la empresa se vende a… <span className="muted small">· FMV hoy {money(c.fmv)}</span>
            </h2>
          </div>
          <p className="muted small">
            Valor si vendieras todo en una salida (sin descuento de liquidez), antes y después de impuestos: el spread de las NSO
            tributa como ingreso; las acciones e ISO, como ganancia de capital. “Con todo adquirido” suma lo que aún no ha vestido.
          </p>
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th>Escenario</th>
                  <th className="num">Precio</th>
                  <th className="num hide-sm">Adquirido</th>
                  <th className="num">Adquirido, neto</th>
                  <th className="num">Con todo adquirido, neto</th>
                </tr>
              </thead>
              <tbody>
                {c.rows.map((r) => (
                  <tr key={r.multiple}>
                    <td>{Number(r.multiple) === 0 ? 'Quiebra' : `${Number(r.multiple)}× FMV`}</td>
                    <td className="num">{money(r.price)}</td>
                    <td className="num hide-sm">{money(r.gross, true)}</td>
                    <td className="num">
                      <strong>{money(r.net, true)}</strong>
                    </td>
                    <td className="num">{money(r.full_net, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  )
}

function GrantCards({ data }: { data: EquitySummary }) {
  const [exercising, setExercising] = useState<{ grant: GrantRow; row: EquityExerciseRow | null } | null>(null)
  return (
    <>
      {exercising && <ExerciseModal {...exercising} onClose={() => setExercising(null)} />}
      {data.alerts.map((a, i) => (
        <div key={i} className="card warn">
          <strong>{a.company}:</strong> {a.message}
        </div>
      ))}
      <div className="grid-2">
        {data.grants.map((g) => (
          <div className="card" key={g.id}>
            <div className="card-head">
              <h2>
                {g.company} <span className="muted small">· {g.grant_type_label}</span>
              </h2>
              <strong className="num">{money(g.value, true)}</strong>
            </div>
            <div className="bar-split" role="img" aria-label={`${pct(g.vested_pct, 0)} adquirido`}>
              <span style={{ flex: Number(g.vested) }} className="liquid" />
              <span style={{ flex: Number(g.unvested) }} className="illiquid" />
            </div>
            <div className="split-legend">
              <span>
                <i className="liquid" /> Adquirido {qty(g.vested)} ({pct(g.vested_pct, 0)})
              </span>
              <span>
                <i className="illiquid" /> Por adquirir {qty(g.unvested)} · {money(g.unvested_value, true)}
              </span>
            </div>
            <dl className="stats mt">
              {g.next_vest_date && (
                <>
                  <dt>Próximo vesting</dt>
                  <dd>{g.next_vest_date}</dd>
                  <dt>Todo adquirido</dt>
                  <dd>{g.fully_vested_date}</dd>
                </>
              )}
              {g.is_option && g.exercised > 0 && (
                <>
                  <dt>Acciones ya ejercidas</dt>
                  <dd>
                    {qty(g.shares)} · {money(g.shares_value, true)}
                  </dd>
                  <dt>Opciones adquiridas sin ejercer</dt>
                  <dd>{qty(g.open_options)}</dd>
                </>
              )}
              {g.is_option && (
                <>
                  <dt>Costo de ejercer lo pendiente</dt>
                  <dd>{money(g.exercise_cost, true)}</dd>
                  <dt>{g.grant_type === 'iso' ? 'Preferencia AMT (spread)' : 'Impuesto al ejercer (NSO)'}</dt>
                  <dd>{money(g.grant_type === 'iso' ? g.amt_preference : g.exercise_tax, true)}</dd>
                  <dt>Efectivo necesario</dt>
                  <dd>{money(g.cash_to_exercise, true)}</dd>
                  <dt>Vencimiento</dt>
                  <dd>{g.expiration_date ? `${g.expiration_date} (${g.days_to_expiration} d)` : 'sin definir'}</dd>
                  {g.termination_date ? (
                    <>
                      <dt>Dejaste la empresa</dt>
                      <dd>{g.termination_date}</dd>
                      <dt>Último día para ejercer</dt>
                      <dd className={g.options_lost ? 'neg' : ''}>
                        {g.exercise_deadline}
                        {g.options_lost && ' (vencido: opciones perdidas)'}
                      </dd>
                    </>
                  ) : (
                    g.open_options > 0 && (
                      <>
                        <dt>Si te vas hoy</dt>
                        <dd>
                          {g.post_termination_days} días para reunir {money(g.cash_to_exercise, true)}
                        </dd>
                      </>
                    )
                  )}
                </>
              )}
              {Number(g.liquidity_discount_pct) > 0 && (
                <>
                  <dt>Sin descuento de liquidez</dt>
                  <dd>{money(g.value_without_discount, true)}</dd>
                </>
              )}
            </dl>
            {g.is_option && <Exercises g={g} onEdit={(row) => setExercising({ grant: g, row })} />}
            {g.is_option && g.exercised < g.quantity && (
              <div className="actions mt">
                <button className="btn" onClick={() => setExercising({ grant: g, row: null })}>
                  + Registrar ejercicio
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

export default function Equity() {
  const accounts = useAccounts()
  const choices = useChoices()
  const summary = useQuery({ queryKey: ['equity-summary'], queryFn: () => api<EquitySummary>('/equity/') })
  const accountOptions = (accounts.data ?? [])
    .filter((a) => a.account_type === 'private_equity')
    .map((a) => ({ value: String(a.id), label: a.name }))

  return (
    <CrudPage<EquityGrant>
      title="Equity privada"
      noun="Grant"
      endpoint="/equity-grants/"
      intro={
        <>
          <p className="muted small">
            Solo cuenta lo adquirido (vested). Opciones sin ejercer = (FMV − strike) × opciones; acciones = FMV. Puedes ejercer
            por partes: registra cada ejercicio en su grant. El descuento de
            liquidez refleja que no puedes vender a FMV hoy. NSO: el spread paga impuesto como ingreso al ejercer. ISO: sin impuesto
            regular al ejercer, pero el spread cuenta para AMT. Confirma con tu CPA antes de ejercer.
            {!accountOptions.length && ' Primero crea una cuenta de tipo “Equity privada”.'}
          </p>
          {summary.data && summary.data.grants.length > 0 && (
            <>
              <GrantCards data={summary.data} />
              <Scenarios data={summary.data} />
            </>
          )}
        </>
      }
      columns={[
        { label: 'Empresa', render: (r) => <strong>{r.company}</strong> },
        { label: 'Tipo', className: 'hide-sm', render: (r) => r.grant_type_label },
        { label: 'Cantidad', className: 'num', render: (r) => qty(r.quantity) },
        { label: 'Strike', className: 'num hide-sm', render: (r) => money(r.strike) },
        { label: 'FMV', className: 'num', render: (r) => money(r.fmv) },
        { label: 'Valor', className: 'num', render: (r) => money(r.market_value, true) },
      ]}
      fields={[
        { name: 'account', label: 'Cuenta', type: 'select', options: accountOptions, required: true },
        { name: 'company', label: 'Empresa', required: true },
        { name: 'grant_type', label: 'Tipo', type: 'select', options: choices.data?.grant_types, required: true },
        { name: 'quantity', label: 'Número de opciones / acciones', type: 'number', required: true },
        { name: 'strike', label: 'Strike / precio pagado (USD)', type: 'number', required: true },
        { name: 'fmv', label: 'FMV por acción (USD)', type: 'number', required: true, help: 'Último 409A o ronda' },
        { name: 'grant_date', label: 'Fecha de grant', type: 'date', nullable: true },
        { name: 'vesting_start', label: 'Inicio de vesting', type: 'date', nullable: true, help: 'Vacío = todo adquirido' },
        { name: 'vesting_months', label: 'Vesting total (meses)', type: 'number', show: hasVesting },
        { name: 'cliff_months', label: 'Cliff (meses)', type: 'number', show: hasVesting },
        { name: 'expiration_date', label: 'Vencimiento de las opciones', type: 'date', nullable: true, show: isOption },
        { name: 'post_termination_days', label: 'Días para ejercer si te vas', type: 'number', show: isOption },
        {
          name: 'termination_date',
          label: 'Fecha en que dejaste la empresa',
          type: 'date',
          nullable: true,
          help: 'Solo si ya te fuiste: detiene el vesting y empieza el plazo para ejercer',
        },
        { name: 'liquidity_discount_pct', label: 'Descuento de liquidez (%)', type: 'number', help: 'Ej. 20–30 para startups' },
        { name: 'sector', label: 'Sector', help: 'Para medir concentración, ej. Crypto' },
        { name: 'notes', label: 'Notas', type: 'textarea' },
      ]}
      defaults={{
        account: accountOptions[0]?.value ?? '', company: '', grant_type: 'nso', quantity: '', strike: '', fmv: '',
        grant_date: '', vesting_start: '', vesting_months: '48', cliff_months: '12', expiration_date: '',
        post_termination_days: '90', termination_date: '', liquidity_discount_pct: '0', sector: '', notes: '',
      }}
      toForm={(r) =>
        formOf(r, [
          'account', 'company', 'grant_type', 'quantity', 'strike', 'fmv', 'grant_date', 'vesting_start',
          'vesting_months', 'cliff_months', 'expiration_date', 'post_termination_days', 'termination_date', 'liquidity_discount_pct', 'sector',
          'notes',
        ])
      }
    />
  )
}
