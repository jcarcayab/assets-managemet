import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../api'
import type { TwoFactorSetup as SetupData } from '../api'

/** Enrollment: scan the QR, confirm with a code, then save the recovery codes (shown only once). */
export function TwoFactorSetup({ onDone }: { onDone: () => void }) {
  const [setup, setSetup] = useState<SetupData | null>(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const started = useRef(false)

  useEffect(() => {
    // Each call replaces the pending secret, so StrictMode's double effect must not run it twice.
    if (started.current) return
    started.current = true
    api<SetupData>('/auth/2fa/setup/', { method: 'POST' })
      .then(setSetup)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const confirm = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await api<{ recovery_codes: string[] }>('/auth/2fa/confirm/', { body: { code } })
      setCodes(res.recovery_codes)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  if (codes) {
    return (
      <div className="twofa">
        <h2>Guarda tus códigos de recuperación</h2>
        <p className="muted small">
          Cada código sirve una sola vez si pierdes el teléfono. Guárdalos en tu gestor de contraseñas: no se volverán a mostrar.
        </p>
        <ul className="recovery-codes">
          {codes.map((c) => (
            <li key={c}>
              <code>{c}</code>
            </li>
          ))}
        </ul>
        <div className="row-end">
          <button className="btn" onClick={() => navigator.clipboard?.writeText(codes.join('\n'))}>
            Copiar
          </button>
          <button className="btn primary" onClick={onDone}>
            Ya los guardé
          </button>
        </div>
      </div>
    )
  }

  return (
    <form className="twofa" onSubmit={confirm}>
      <ol className="steps">
        <li>Abre tu app de autenticación (Google Authenticator, 1Password, Authy…) y escanea el código.</li>
        <li>Escribe el código de 6 dígitos que muestra.</li>
      </ol>
      {setup ? (
        <>
          {/* SVG generated server-side by segno from our own otpauth URI. */}
          <div className="qr" dangerouslySetInnerHTML={{ __html: setup.qr_svg }} />
          <details>
            <summary className="small">¿No puedes escanear? Escribe la clave a mano</summary>
            <code className="secret">{setup.secret.match(/.{1,4}/g)?.join(' ')}</code>
          </details>
          <label className="code-input">
            <span>Código</span>
            <input
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9 ]{6,7}"
              placeholder="123456"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              autoFocus
            />
          </label>
        </>
      ) : (
        !error && <p className="muted">Generando…</p>
      )}
      {error && <p className="error">{error}</p>}
      <div className="row-end">
        <button className="btn primary" disabled={busy || !setup}>
          {busy ? 'Verificando…' : 'Activar'}
        </button>
      </div>
    </form>
  )
}
