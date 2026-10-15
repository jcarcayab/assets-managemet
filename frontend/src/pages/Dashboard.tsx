import { Link } from 'react-router-dom'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { api } from '../api'
import { useRefreshPrices, useSummary, useWrite } from '../hooks'
import { dateTime, money, pct, signed, tone } from '../format'
import { PALETTE } from '../palette'

function Kpi({ label, value, sub, subTone }: { label: string; value: string; sub?: string; subTone?: string }) {
  return (
    <div className="card kpi">
      <span className="kpi-label">{label}</span>
      <strong className="kpi-value">{value}</strong>
      {sub && <span className={`kpi-sub ${subTone ?? ''}`}>{sub}</span>}
    </div>
  )
}

export default function Dashboard() {
  const summary = useSummary()
  const refresh = useRefreshPrices()
  const snapshot = useWrite(() => api('/snapshots/', { method: 'POST', body: {} }))

  if (summary.isLoading) return <p className="muted">Cargando…</p>
  if (summary.error || !summary.data) return <p className="error">{String(summary.error)}</p>
  const s = summary.data

  if (!s.by_account.length) {
    return (
      <section>
        <h1>Resumen</h1>
        <div className="card empty">
          <p>Todavía no hay datos.</p>
          <p>
            Crea una <Link to="/cuentas">cuenta</Link>, añade <Link to="/activos">activos</Link> y registra{' '}
            <Link to="/movimientos">movimientos</Link>. O importa tu Excel con <code>manage.py import_excel</code>.
          </p>
        </div>
      </section>
    )
  }

  const classes = s.by_class.filter((c) => c.value > 0)

  return (
    <section>
      <div className="page-head">
        <h1>Resumen</h1>
        <div className="actions">
          <button className="btn" onClick={() => refresh.mutate(undefined)} disabled={refresh.isPending}>
            {refresh.isPending ? 'Actualizando…' : 'Actualizar precios'}
          </button>
          <button className="btn" onClick={() => snapshot.mutate(undefined)} disabled={snapshot.isPending}>
            Guardar foto
          </button>
        </div>
      </div>
      <p className="muted small">
        Precios en vivo al {dateTime(s.prices_as_of)}
        {refresh.data?.failed.length ? ` · sin precio: ${refresh.data.failed.join(', ')}` : ''}
        {snapshot.isSuccess && ' · Foto guardada en Historial'}
      </p>

      <div className="kpis">
        <Kpi label="Patrimonio total" value={money(s.net_worth, true)} />
        <Kpi label="Sin equity privada" value={money(s.net_worth_ex_private, true)} />
        <Kpi
          label="Líquido (accesible)"
          value={money(s.liquid, true)}
          sub={`${pct(s.net_worth ? (s.liquid / s.net_worth) * 100 : null, 0)} del total`}
        />
        <Kpi
          label="Ganancia no realizada"
          value={signed(s.unrealized)}
          sub={`${pct(s.unrealized_pct)} sobre costo ${money(s.cost, true)}`}
          subTone={tone(s.unrealized)}
        />
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Por clase de activo</h2>
          <div className="donut">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={classes} dataKey="value" nameKey="label" innerRadius="58%" outerRadius="90%" paddingAngle={2} stroke="none">
                  {classes.map((c, i) => (
                    <Cell key={c.key} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => money(Number(v), true)} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="legend">
            {classes.map((c, i) => (
              <li key={c.key}>
                <span className="swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
                <span className="grow">{c.label}</span>
                <span className="num">{money(c.value, true)}</span>
                <span className="num muted w-pct">{pct(c.weight, 0)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2>Crypto vs. depositado</h2>
          <dl className="stats">
            <dt>Depósitos totales</dt>
            <dd>{money(s.crypto.deposits)}</dd>
            <dt>Valor hoy</dt>
            <dd>{money(s.crypto.value)}</dd>
            <dt>Ganancia neta</dt>
            <dd className={tone(s.crypto.gain)}>
              {signed(s.crypto.gain)} <small>({pct(s.crypto.gain_pct)})</small>
            </dd>
          </dl>
          <h2 className="mt">Accesibilidad</h2>
          <div className="bar-split" role="img" aria-label="Líquido vs. no líquido">
            <span style={{ flex: Math.max(s.liquid, 0) }} className="liquid" />
            <span style={{ flex: Math.max(s.illiquid, 0) }} className="illiquid" />
          </div>
          <div className="split-legend">
            <span>
              <i className="liquid" /> Líquido {money(s.liquid, true)}
            </span>
            <span>
              <i className="illiquid" /> Retiro / no accesible {money(s.illiquid, true)}
            </span>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Por cuenta</h2>
        <div className="table-wrap flush">
          <table>
            <thead>
              <tr>
                <th>Cuenta</th>
                <th className="hide-sm">Institución</th>
                <th className="num hide-sm">Costo</th>
                <th className="num">Valor</th>
                <th className="num">Ganancia</th>
                <th className="num hide-sm">% total</th>
              </tr>
            </thead>
            <tbody>
              {s.by_account.map((a) => (
                <tr key={a.key}>
                  <td>
                    {a.label} {!a.is_liquid && <span className="tag">retiro</span>}
                  </td>
                  <td className="hide-sm muted">{a.institution}</td>
                  <td className="num hide-sm">{money(a.cost, true)}</td>
                  <td className="num">{money(a.value, true)}</td>
                  <td className={`num ${tone(a.gain)}`}>
                    {signed(a.gain)}
                    <small className="block">{pct(a.gain_pct)}</small>
                  </td>
                  <td className="num hide-sm">{pct(a.weight)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>Total</td>
                <td className="hide-sm" />
                <td className="num hide-sm">{money(s.cost, true)}</td>
                <td className="num">{money(s.net_worth, true)}</td>
                <td className={`num ${tone(s.unrealized)}`}>{signed(s.unrealized)}</td>
                <td className="num hide-sm">100%</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </section>
  )
}
