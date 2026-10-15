import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import type { User } from '../api'
import { FormModal } from '../components/FormModal'
import { useSettings, useWrite } from '../hooks'
import { pct } from '../format'

export default function SettingsPage({ user }: { user: User }) {
  const qc = useQueryClient()
  const settings = useSettings()
  const [editing, setEditing] = useState(false)
  const save = useWrite((body: Record<string, unknown>) => api('/settings/', { method: 'PATCH', body }))

  const logout = async () => {
    await api('/auth/logout/', { method: 'POST' })
    qc.clear()
    window.location.assign('/')
  }

  const s = settings.data

  return (
    <section>
      <div className="page-head">
        <h1>Ajustes</h1>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Niveles de trading (crypto)</h2>
          <button className="btn" onClick={() => setEditing(true)} disabled={!s}>
            Editar
          </button>
        </div>
        {s && (
          <dl className="stats">
            <dt>Take profit 1</dt>
            <dd>{pct(s.take_profit_1_pct)}</dd>
            <dt>Take profit 2</dt>
            <dd>{pct(s.take_profit_2_pct)}</dd>
            <dt>Stop loss</dt>
            <dd>{pct(s.stop_loss_pct)}</dd>
          </dl>
        )}
        <p className="muted small">Los supuestos de retiro se editan en Proyección.</p>
      </div>

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
          title="Niveles de trading"
          fields={[
            { name: 'take_profit_1_pct', label: 'Take profit 1 (%)', type: 'number', required: true },
            { name: 'take_profit_2_pct', label: 'Take profit 2 (%)', type: 'number', required: true },
            { name: 'stop_loss_pct', label: 'Stop loss (%)', type: 'number', required: true, help: 'Negativo, p.ej. −5' },
          ]}
          initial={{
            take_profit_1_pct: String(s.take_profit_1_pct),
            take_profit_2_pct: String(s.take_profit_2_pct),
            stop_loss_pct: String(s.stop_loss_pct),
          }}
          onSubmit={(body) => save.mutateAsync(body)}
          onClose={() => setEditing(false)}
        />
      )}
    </section>
  )
}
