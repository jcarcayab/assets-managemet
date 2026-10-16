import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { Settings, TwoFactorStatus, User } from '../api'
import { FormModal } from '../components/FormModal'
import { TwoFactorSetup } from '../components/TwoFactorSetup'
import type { Field } from '../components/FormModal'
import { useChoices, useSettings, useWrite } from '../hooks'
import { pct } from '../format'

type Section = { key: string; title: string; fields: Field[] }

function SecurityCard() {
  const qc = useQueryClient()
  const status = useQuery({ queryKey: ['2fa'], queryFn: () => api<TwoFactorStatus>('/auth/2fa/') })
  const [mode, setMode] = useState<'setup' | 'disable' | 'codes' | null>(null)
  const [newCodes, setNewCodes] = useState<string[] | null>(null)
  const s = status.data
  const close = () => {
    setMode(null)
    qc.invalidateQueries()
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>Verificación en dos pasos (2FA)</h2>
        {s && !s.enabled && (
          <button className="btn primary" onClick={() => setMode('setup')}>
            Activar
          </button>
        )}
      </div>
      {s?.enabled ? (
        <>
          <p className="pos">
            Activa desde {s.confirmed_at?.slice(0, 10)} · {s.recovery_codes_left} códigos de recuperación sin usar
          </p>
          <div className="actions">
            <button className="btn" onClick={() => setMode('codes')}>
              Generar nuevos códigos de recuperación
            </button>
            {!s.required && (
              <button className="btn danger" onClick={() => setMode('disable')}>
                Desactivar
              </button>
            )}
          </div>
        </>
      ) : (
        <p className="muted small">
          Protege tu cuenta con un código de una app de autenticación además de la contraseña. Muy recomendado si la app está
          publicada en internet.
        </p>
      )}

      {mode === 'setup' && (
        <div className="modal-backdrop">
          <div className="modal">
            <header className="modal-head">
              <h2>Activar verificación en dos pasos</h2>
              <button className="icon-btn" onClick={() => setMode(null)} aria-label="Cerrar">
                ×
              </button>
            </header>
            <TwoFactorSetup onDone={close} />
          </div>
        </div>
      )}
      {mode === 'disable' && (
        <FormModal
          title="Desactivar verificación en dos pasos"
          fields={[
            { name: 'password', label: 'Contraseña', type: 'password', required: true },
            { name: 'code', label: 'Código de la app o de recuperación', required: true },
          ]}
          initial={{ password: '', code: '' }}
          onSubmit={(body) => api('/auth/2fa/disable/', { body })}
          onClose={close}
        />
      )}
      {mode === 'codes' && (
        <FormModal
          title="Nuevos códigos de recuperación"
          fields={[{ name: 'code', label: 'Código actual de la app', required: true, help: 'Los códigos anteriores dejarán de servir' }]}
          initial={{ code: '' }}
          onSubmit={async (body) => {
            const res = await api<{ recovery_codes: string[] }>('/auth/2fa/recovery-codes/', { body })
            setNewCodes(res.recovery_codes)
          }}
          onClose={close}
        />
      )}
      {newCodes && (
        <div className="modal-backdrop">
          <div className="modal twofa">
            <h2>Tus nuevos códigos de recuperación</h2>
            <p className="muted small">Guárdalos ahora: no se volverán a mostrar.</p>
            <ul className="recovery-codes">
              {newCodes.map((c) => (
                <li key={c}>
                  <code>{c}</code>
                </li>
              ))}
            </ul>
            <div className="row-end">
              <button className="btn" onClick={() => navigator.clipboard?.writeText(newCodes.join('\n'))}>
                Copiar
              </button>
              <button className="btn primary" onClick={() => setNewCodes(null)}>
                Ya los guardé
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

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
            ['Benchmark', benchmarkLabel ?? '—'],
            ['Límite de concentración', pct(s.concentration_limit_pct, 0)],
            ['Fondo de emergencia', `${s.emergency_fund_months} meses`],
          ])}
          {card(sections[1], [
            ['Ganancias de capital', pct(s.capital_gains_tax_pct, 0)],
            ['Retiro 401k / IRA', pct(s.retirement_tax_pct, 0)],
            ['Ingreso ordinario', pct(s.ordinary_income_tax_pct, 0)],
          ])}
          <p className="muted small">Los supuestos de retiro se editan en Proyección. Las tasas fiscales son estimaciones planas.</p>
        </>
      )}

      <SecurityCard />

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
