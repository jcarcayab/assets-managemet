import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { EquityGrant, EquitySummary } from '../api'
import { CrudPage } from '../components/CrudPage'
import type { FormValues } from '../components/FormModal'
import { useAccounts, useChoices } from '../hooks'
import { formOf, money, pct, qty } from '../format'

const isOption = (v: FormValues) => v.grant_type !== 'shares'
const hasVesting = (v: FormValues) => Boolean(v.vesting_start)

function GrantCards({ data }: { data: EquitySummary }) {
  return (
    <>
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
              {g.is_option && (
                <>
                  <dt>Costo de ejercer lo adquirido</dt>
                  <dd>{money(g.exercise_cost, true)}</dd>
                  <dt>{g.grant_type === 'iso' ? 'Preferencia AMT (spread)' : 'Impuesto al ejercer (NSO)'}</dt>
                  <dd>{money(g.grant_type === 'iso' ? g.amt_preference : g.exercise_tax, true)}</dd>
                  <dt>Efectivo necesario</dt>
                  <dd>{money(g.cash_to_exercise, true)}</dd>
                  <dt>Vencimiento</dt>
                  <dd>{g.expiration_date ? `${g.expiration_date} (${g.days_to_expiration} d)` : 'sin definir'}</dd>
                  <dt>Plazo si dejas la empresa</dt>
                  <dd>{g.post_termination_days} días</dd>
                </>
              )}
              {Number(g.liquidity_discount_pct) > 0 && (
                <>
                  <dt>Sin descuento de liquidez</dt>
                  <dd>{money(g.value_without_discount, true)}</dd>
                </>
              )}
            </dl>
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
            Solo cuenta lo adquirido (vested). Opciones sin ejercer = (FMV − strike) × opciones; acciones = FMV. El descuento de
            liquidez refleja que no puedes vender a FMV hoy. NSO: el spread paga impuesto como ingreso al ejercer. ISO: sin impuesto
            regular al ejercer, pero el spread cuenta para AMT. Confirma con tu CPA antes de ejercer.
            {!accountOptions.length && ' Primero crea una cuenta de tipo “Equity privada”.'}
          </p>
          {summary.data && summary.data.grants.length > 0 && <GrantCards data={summary.data} />}
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
        { name: 'exercised', label: 'Ya ejercidas', type: 'checkbox', show: isOption },
        { name: 'grant_date', label: 'Fecha de grant', type: 'date', nullable: true },
        { name: 'vesting_start', label: 'Inicio de vesting', type: 'date', nullable: true, help: 'Vacío = todo adquirido' },
        { name: 'vesting_months', label: 'Vesting total (meses)', type: 'number', show: hasVesting },
        { name: 'cliff_months', label: 'Cliff (meses)', type: 'number', show: hasVesting },
        { name: 'expiration_date', label: 'Vencimiento de las opciones', type: 'date', nullable: true, show: isOption },
        { name: 'post_termination_days', label: 'Días para ejercer si te vas', type: 'number', show: isOption },
        { name: 'liquidity_discount_pct', label: 'Descuento de liquidez (%)', type: 'number', help: 'Ej. 20–30 para startups' },
        { name: 'sector', label: 'Sector', help: 'Para medir concentración, ej. Crypto' },
        { name: 'notes', label: 'Notas', type: 'textarea' },
      ]}
      defaults={{
        account: accountOptions[0]?.value ?? '', company: '', grant_type: 'nso', quantity: '', strike: '', fmv: '',
        exercised: false, grant_date: '', vesting_start: '', vesting_months: '48', cliff_months: '12', expiration_date: '',
        post_termination_days: '90', liquidity_discount_pct: '0', sector: '', notes: '',
      }}
      toForm={(r) =>
        formOf(r, [
          'account', 'company', 'grant_type', 'quantity', 'strike', 'fmv', 'exercised', 'grant_date', 'vesting_start',
          'vesting_months', 'cliff_months', 'expiration_date', 'post_termination_days', 'liquidity_discount_pct', 'sector',
          'notes',
        ])
      }
    />
  )
}
