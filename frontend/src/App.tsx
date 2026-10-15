import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api } from './api'
import type { User } from './api'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Holdings from './pages/Holdings'
import Transactions from './pages/Transactions'
import Accounts from './pages/Accounts'
import Assets from './pages/Assets'
import Equity from './pages/Equity'
import History from './pages/History'
import Projection from './pages/Projection'
import SettingsPage from './pages/Settings'

const NAV = [
  { to: '/', label: 'Resumen', end: true },
  { to: '/posiciones', label: 'Posiciones' },
  { to: '/movimientos', label: 'Movimientos' },
  { to: '/cuentas', label: 'Cuentas' },
  { to: '/activos', label: 'Activos' },
  { to: '/equity', label: 'Equity' },
  { to: '/historial', label: 'Historial' },
  { to: '/proyeccion', label: 'Proyección' },
  { to: '/ajustes', label: 'Ajustes' },
]

export default function App() {
  const qc = useQueryClient()
  const session = useQuery({
    queryKey: ['session'],
    queryFn: () => api<{ user: User | null }>('/auth/session/'),
    staleTime: Infinity,
  })

  if (session.isLoading) return <div className="center muted">Cargando…</div>
  if (session.error) return <div className="center error">No se pudo conectar con el servidor.</div>
  if (!session.data?.user) return <Login onLogin={() => qc.invalidateQueries({ queryKey: ['session'] })} />

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
          <Route path="/movimientos" element={<Transactions />} />
          <Route path="/cuentas" element={<Accounts />} />
          <Route path="/activos" element={<Assets />} />
          <Route path="/equity" element={<Equity />} />
          <Route path="/historial" element={<History />} />
          <Route path="/proyeccion" element={<Projection />} />
          <Route path="/ajustes" element={<SettingsPage user={session.data.user} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
