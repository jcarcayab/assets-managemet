import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { TaxLots } from '../api'
import { money, pct, qty, signed, tone } from '../format'

export default function Taxes() {
  const lots = useQuery({ queryKey: ['tax-lots'], queryFn: () => api<TaxLots>('/tax-lots/') })
  if (lots.isLoading || !lots.data) return <p className="muted">Cargando…</p>
  const t = lots.data

  return (
    <section>
      <div className="page-head">
        <h1>Impuestos</h1>
      </div>
      <p className="muted small">
        Lotes de cuentas gravables, método FIFO (el predeterminado de los brokers en EE.UU.). Corto plazo (≤1 año) al{' '}
        {pct(t.rates.short, 0)}, largo plazo al {pct(t.rates.long, 0)} — cámbialo en Ajustes. Estimaciones planas para planear, no
        asesoría fiscal: confirma con tu CPA antes de vender.
      </p>

      <div className="kpis">
        <div className="card kpi">
          <span className="kpi-label">Ganancia corto plazo</span>
          <strong className={`kpi-value ${tone(t.short_gain)}`}>{signed(t.short_gain)}</strong>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Ganancia largo plazo</span>
          <strong className={`kpi-value ${tone(t.long_gain)}`}>{signed(t.long_gain)}</strong>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Impuesto si vendieras todo</span>
          <strong className="kpi-value">{money(t.estimated_tax, true)}</strong>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Ahorro por cosechar pérdidas</span>
          <strong className="kpi-value pos">{money(t.harvest_total_saving, true)}</strong>
          <span className="kpi-sub">pérdidas disponibles {money(t.harvest_total_loss, true)}</span>
        </div>
      </div>

      <div className="card">
        <h2>Candidatos a tax-loss harvesting</h2>
        {!t.harvest.length ? (
          <p className="muted small">No hay lotes con pérdida en cuentas gravables.</p>
        ) : (
          <>
            <p className="muted small">
              Vender un lote con pérdida la realiza: compensa ganancias y hasta $3,000 al año de ingreso ordinario; el resto se
              arrastra a años siguientes. En valores (acciones, ETFs) no recompres lo mismo 30 días antes o después (wash sale). Hoy
              en EE.UU. esa regla no se aplica a crypto — verifica que siga vigente.
            </p>
            <div className="table-wrap flush">
              <table>
                <thead>
                  <tr>
                    <th>Activo</th>
                    <th className="hide-sm">Comprado</th>
                    <th>Plazo</th>
                    <th className="num">Pérdida</th>
                    <th className="num">Ahorro est.</th>
                    <th>Wash sale</th>
                  </tr>
                </thead>
                <tbody>
                  {t.harvest.map((h, i) => (
                    <tr key={i}>
                      <td>
                        <strong>{h.symbol}</strong>
                        <small className="block muted">{h.account}</small>
                      </td>
                      <td className="hide-sm">{h.date}</td>
                      <td>{h.term === 'long' ? 'Largo' : 'Corto'}</td>
                      <td className="num neg">{money(h.loss)}</td>
                      <td className="num pos">{money(h.tax_saving)}</td>
                      <td>
                        {!h.wash_sale_rule ? (
                          <span className="tag">no aplica</span>
                        ) : h.wash_sale_risk ? (
                          <span className="tag sell">compraste hace &lt;30 días</span>
                        ) : (
                          <span className="tag">no recomprar 30 días</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {t.soon_long_term.length > 0 && (
        <div className="card">
          <h2>Espera antes de vender</h2>
          <p className="muted small">Lotes con ganancia que pasan a largo plazo pronto: vender después paga menos impuesto.</p>
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th>Activo</th>
                  <th className="num">Ganancia</th>
                  <th className="num">Días para largo plazo</th>
                  <th className="num">Ahorro si esperas</th>
                </tr>
              </thead>
              <tbody>
                {t.soon_long_term.map((r, i) => (
                  <tr key={i}>
                    <td>
                      <strong>{r.symbol}</strong>
                      <small className="block muted">
                        {r.account} · {r.date}
                      </small>
                    </td>
                    <td className="num pos">{money(r.gain)}</td>
                    <td className="num">{r.days_to_long_term}</td>
                    <td className="num pos">{money(r.saving_if_wait)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {t.positions.map((p) => (
        <details className="card" key={`${p.account}-${p.symbol}`}>
          <summary>
            {p.symbol} <span className="muted">· {p.account}</span> <span className={tone(p.gain)}>{signed(p.gain)}</span>{' '}
            <span className="muted small">({p.lots.length} lotes)</span>
          </summary>
          <div className="table-wrap flush">
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th className="num">Cantidad</th>
                  <th className="num hide-sm">Costo unit.</th>
                  <th className="num hide-sm">Valor</th>
                  <th className="num">Ganancia</th>
                  <th>Plazo</th>
                </tr>
              </thead>
              <tbody>
                {p.lots.map((l, i) => (
                  <tr key={i}>
                    <td>{l.date}</td>
                    <td className="num">{qty(l.quantity)}</td>
                    <td className="num hide-sm">{money(l.unit_cost)}</td>
                    <td className="num hide-sm">{money(l.value)}</td>
                    <td className={`num ${tone(l.gain)}`}>{signed(l.gain)}</td>
                    <td>{l.term === 'long' ? 'Largo' : `Corto (${l.days_to_long_term} d)`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}
    </section>
  )
}
