import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { Settings, User } from '../api'
import { FormModal } from '../components/FormModal'
import type { Field } from '../components/FormModal'
import { useChoices, useSettings, useWrite } from '../hooks'
import { pct } from '../format'

type Section = { key: string; title: string; fields: Field[] }

export default function SettingsPage({ user }: { user: User }) {
  const qc = useQueryClient()
  const settings = useSettings()
  const choices = useChoices()
  const [editing, setEditing] = useState<Section | null>(null)
  const save = useWrite((body: Record<string, unknown>) => api('/settings/', { method: 'PATCH', body }))

  const logout = async () => {
    await api('/auth/logout/', { method: 'POST' })
    qc.clear()
    window.location.assign('/')
  }

  const s = settings.data
  const benchmarkLabel = choices.data?.benchmarks.find((b) => b.value === s?.benchmark)?.label ?? s?.benchmark

  const sections: Section[] = [
    {
      key: 'trading',
      title: 'Niveles de trading (crypto)',
      fields: [
        { name: 'take_profit_1_pct', label: 'Take profit 1 (%)', type: 'number', required: true },
        { name: 'take_profit_2_pct', label: 'Take profit 2 (%)', type: 'number', required: true },
        { name: 'stop_loss_pct', label: 'Stop loss (%)', type: 'number', required: true, help: 'Negativo, p.ej. −5' },
      ],
    },
    {
      key: 'risk',
      title: 'Riesgo y comparación',
      fields: [
        { name: 'benchmark', label: 'Benchmark por defecto', type: 'select', options: choices.data?.benchmarks, required: true },
        {
          name: 'concentration_limit_pct',
          label: 'Límite de concentración (%)',
          type: 'number',
          required: true,
          help: 'Alerta si una posición o sector supera este % de tus activos',
        },
        {
          name: 'emergency_fund_months',
          label: 'Fondo de emergencia objetivo (meses)',
          type: 'number',
          required: true,
          help: 'Meses de gastos esenciales en efectivo',
        },
      ],
    },
    {
      key: 'tax',
      title: 'Tasas para impuestos estimados',
      fields: [
        { name: 'capital_gains_tax_pct', label: 'Ganancias de capital (%)', type: 'number', required: true, help: 'Cuentas gravables' },
        { name: 'retirement_tax_pct', label: 'Retiro de 401k / IRA (%)', type: 'number', required: true, help: 'Tasa esperada al jubilarte' },
        { name: 'ordinary_income_tax_pct', label: 'Ingreso ordinario (%)', type: 'number', required: true, help: 'Spread de opciones' },
      ],
    },
  ]

  const card = (section: Section, rows: [string, string][]) => (
    <div className="card" key={section.key}>
      <div className="card-head">
        <h2>{section.title}</h2>
        <button className="btn" onClick={() => setEditing(section)} disabled={!s}>
          Editar
        </button>
      </div>
      {s && (
        <dl className="stats">
          {rows.map(([label, value]) => (
            <div key={label} style={{ display: 'contents' }}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )

  return (
    <section>
      <div className="page-head">
        <h1>Ajustes</h1>
      </div>

      {s && (
        <>
          {card(sections[0], [
            ['Take profit 1', pct(s.take_profit_1_pct)],
            ['Take profit 2', pct(s.take_profit_2_pct)],
            ['Stop loss', pct(s.stop_loss_pct)],
          ])}
          {card(sections[1], [
            ['Benchmark', benchmarkLabel ?? '—'],
            ['Límite de concentración', pct(s.concentration_limit_pct, 0)],
            ['Fondo de emergencia', `${s.emergency_fund_months} meses`],
          ])}
          {card(sections[2], [
            ['Ganancias de capital', pct(s.capital_gains_tax_pct, 0)],
            ['Retiro 401k / IRA', pct(s.retirement_tax_pct, 0)],
            ['Ingreso ordinario', pct(s.ordinary_income_tax_pct, 0)],
          ])}
          <p className="muted small">Los supuestos de retiro se editan en Proyección. Las tasas fiscales son estimaciones planas.</p>
        </>
      )}

      <div className="card">
        <div className="card-head">
          <h2>Sesión</h2>
          <button className="btn danger" onClick={logout}>
            Cerrar sesión
          </button>
        </div>
        <p className="muted">
          Conectado como <strong>{user.username}</strong>. Cambia la contraseña o gestiona usuarios en{' '}
          <a href="/admin/" target="_blank" rel="noreferrer">
            /admin
          </a>
          .
        </p>
      </div>

      {editing && s && (
        <FormModal
          title={editing.title}
          fields={editing.fields}
          initial={Object.fromEntries(editing.fields.map((f) => [f.name, String(s[f.name as keyof Settings])]))}
          onSubmit={(body) => save.mutateAsync(body)}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  )
}
