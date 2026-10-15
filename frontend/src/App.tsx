import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { AUTH_CHANGED, api } from './api'
import type { SessionInfo } from './api'
import { TwoFactorSetup } from './components/TwoFactorSetup'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Holdings from './pages/Holdings'
import Performance from './pages/Performance'
import Exposure from './pages/Exposure'
import Risk from './pages/Risk'
import Taxes from './pages/Taxes'
import Transactions from './pages/Transactions'
import Accounts from './pages/Accounts'
import Assets from './pages/Assets'
import Equity from './pages/Equity'
import History from './pages/History'
import Budget from './pages/Budget'
import Debts from './pages/Debts'
import Connections from './pages/Connections'
import Projection from './pages/Projection'
import SettingsPage from './pages/Settings'

const NAV = [
  { to: '/', label: 'Resumen', end: true },
  { to: '/posiciones', label: 'Posiciones' },
  { to: '/rendimiento', label: 'Rendimiento' },
  { to: '/exposicion', label: 'Exposición' },
  { to: '/riesgo', label: 'Riesgo' },
  { to: '/impuestos', label: 'Impuestos' },
  { to: '/movimientos', label: 'Movimientos' },
  { to: '/cuentas', label: 'Cuentas' },
  { to: '/activos', label: 'Activos' },
  { to: '/equity', label: 'Equity' },
  { to: '/presupuesto', label: 'Presupuesto' },
  { to: '/deudas', label: 'Deudas' },
  { to: '/historial', label: 'Historial' },
  { to: '/conexiones', label: 'Conexiones' },
  { to: '/proyeccion', label: 'Proyección' },
  { to: '/ajustes', label: 'Ajustes' },
]

export default function App() {
  const qc = useQueryClient()
  const session = useQuery({
    queryKey: ['session'],
    queryFn: () => api<SessionInfo>('/auth/session/'),
    staleTime: Infinity,
  })

  useEffect(() => {
    const recheck = () => qc.invalidateQueries({ queryKey: ['session'] })
    window.addEventListener(AUTH_CHANGED, recheck)
    return () => window.removeEventListener(AUTH_CHANGED, recheck)
  }, [qc])

  if (session.isLoading) return <div className="center muted">Cargando…</div>
  if (session.error) return <div className="center error">No se pudo conectar con el servidor.</div>
  if (!session.data?.user) return <Login onLogin={() => qc.invalidateQueries({ queryKey: ['session'] })} />
  if (session.data.mfa_setup_required) {
    return (
      <div className="login">
        <div className="card login-card wide">
          <div className="brand">
            <span className="logo" aria-hidden>
              ◢
            </span>
            Activa la verificación en dos pasos
          </div>
          <p className="muted small">Es obligatoria para usar la app.</p>
          <TwoFactorSetup onDone={() => qc.invalidateQueries()} />
        </div>
      </div>
    )
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo" aria-hidden>
            ◢
          </span>
          Patrimonio
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}>
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/posiciones" element={<Holdings />} />
          <Route path="/rendimiento" element={<Performance />} />
          <Route path="/exposicion" element={<Exposure />} />
          <Route path="/riesgo" element={<Risk />} />
          <Route path="/impuestos" element={<Taxes />} />
          <Route path="/movimientos" element={<Transactions />} />
          <Route path="/cuentas" element={<Accounts />} />
          <Route path="/activos" element={<Assets />} />
          <Route path="/equity" element={<Equity />} />
          <Route path="/presupuesto" element={<Budget />} />
          <Route path="/deudas" element={<Debts />} />
          <Route path="/historial" element={<History />} />
          <Route path="/conexiones" element={<Connections />} />
          <Route path="/proyeccion" element={<Projection />} />
          <Route path="/ajustes" element={<SettingsPage user={session.data.user} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
