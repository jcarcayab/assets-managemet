import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, safeNext } from '../api'
import type { LoginResult } from '../api'

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const done = () => {
    // Coming from /admin (or another server page): go back there now that the session is complete.
    const next = safeNext(new URLSearchParams(window.location.search).get('next'))
    if (next) window.location.assign(next)
    else onLogin()
  }

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const submitPassword = (e: FormEvent) => {
    e.preventDefault()
    run(async () => {
      const res = await api<LoginResult>('/auth/login/', { body: { username, password } })
      if ('mfa_required' in res) {
        setMfaToken(res.mfa_token)
        setPassword('')
      } else {
        done()
      }
    })
  }

  const submitCode = (e: FormEvent) => {
    e.preventDefault()
    run(async () => {
      try {
        await api('/auth/login/mfa/', { body: { mfa_token: mfaToken, code } })
        done()
      } catch (err) {
        setCode('')
        if (err instanceof Error && err.message.includes('expiró')) setMfaToken(null)
        throw err
      }
    })
  }

  return (
    <div className="login">
      {mfaToken === null ? (
        <form className="card login-card" onSubmit={submitPassword}>
          <div className="brand">
            <span className="logo" aria-hidden>
              ◢
            </span>
            Patrimonio
          </div>
          <label>
            <span>Usuario</span>
            <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </label>
          <label>
            <span>Contraseña</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary block" disabled={busy}>
            {busy ? 'Entrando…' : 'Entrar'}
          </button>
        </form>
      ) : (
        <form className="card login-card" onSubmit={submitCode}>
          <div className="brand">
            <span className="logo" aria-hidden>
              ◢
            </span>
            Verificación en dos pasos
          </div>
          <label>
            <span>{useRecovery ? 'Código de recuperación' : 'Código de 6 dígitos de tu app'}</span>
            <input
              key={useRecovery ? 'recovery' : 'totp'}
              autoComplete="one-time-code"
              inputMode={useRecovery ? 'text' : 'numeric'}
              pattern={useRecovery ? undefined : '[0-9 ]{6,7}'}
              placeholder={useRecovery ? 'abc123-def456' : '123456'}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              autoFocus
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary block" disabled={busy}>
            {busy ? 'Verificando…' : 'Verificar'}
          </button>
          <button type="button" className="link" onClick={() => setUseRecovery(!useRecovery)}>
            {useRecovery ? 'Usar la app de autenticación' : 'Perdí mi teléfono: usar un código de recuperación'}
          </button>
          <button type="button" className="link" onClick={() => setMfaToken(null)}>
            Volver
          </button>
        </form>
      )}
    </div>
  )
}
