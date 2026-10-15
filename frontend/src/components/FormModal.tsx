import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import type { Choice } from '../api'

export type Field = {
  name: string
  label: string
  type?: 'text' | 'number' | 'date' | 'select' | 'checkbox' | 'textarea'
  options?: Choice[]
  required?: boolean
  /** Empty input is sent as null instead of "" */
  nullable?: boolean
  help?: string
  step?: string
}

export type FormValues = Record<string, string | boolean>

type Props = {
  title: string
  fields: Field[]
  initial: FormValues
  onSubmit: (values: Record<string, unknown>) => Promise<unknown>
  onDelete?: () => Promise<unknown>
  onClose: () => void
  footer?: ReactNode
}

function toPayload(fields: Field[], values: FormValues) {
  const out: Record<string, unknown> = {}
  for (const f of fields) {
    const v = values[f.name]
    if (f.type === 'checkbox') out[f.name] = Boolean(v)
    else if (v === '' || v === undefined) out[f.name] = f.nullable ? null : ''
    else out[f.name] = v
  }
  return out
}

export function FormModal({ title, fields, initial, onSubmit, onDelete, onClose, footer }: Props) {
  const [values, setValues] = useState<FormValues>(initial)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    run(() => onSubmit(toPayload(fields, values)))
  }

  const set = (name: string, v: string | boolean) => setValues((prev) => ({ ...prev, [name]: v }))

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal" onSubmit={submit} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Cerrar">
            ×
          </button>
        </header>
        <div className="form-grid">
          {fields.map((f) => {
            const id = `f-${f.name}`
            const value = values[f.name]
            if (f.type === 'checkbox') {
              return (
                <label key={f.name} className="check full">
                  <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => set(f.name, e.target.checked)} />
                  {f.label}
                </label>
              )
            }
            return (
              <label key={f.name} className={f.type === 'textarea' ? 'full' : ''}>
                <span>
                  {f.label}
                  {f.required && ' *'}
                </span>
                {f.type === 'select' ? (
                  <select id={id} value={String(value ?? '')} required={f.required} onChange={(e) => set(f.name, e.target.value)}>
                    <option value="">—</option>
                    {f.options?.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : f.type === 'textarea' ? (
                  <textarea id={id} rows={2} value={String(value ?? '')} onChange={(e) => set(f.name, e.target.value)} />
                ) : (
                  <input
                    id={id}
                    type={f.type ?? 'text'}
                    inputMode={f.type === 'number' ? 'decimal' : undefined}
                    step={f.type === 'number' ? (f.step ?? 'any') : undefined}
                    required={f.required}
                    value={String(value ?? '')}
                    onChange={(e) => set(f.name, e.target.value)}
                  />
                )}
                {f.help && <small>{f.help}</small>}
              </label>
            )
          })}
        </div>
        {footer}
        {error && <p className="error">{error}</p>}
        <footer className="modal-foot">
          {onDelete && (
            <button
              type="button"
              className="btn danger"
              disabled={busy}
              onClick={() => window.confirm('¿Borrar este registro?') && run(onDelete)}
            >
              Borrar
            </button>
          )}
          <span className="spacer" />
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? 'Guardando…' : 'Guardar'}
          </button>
        </footer>
      </form>
    </div>
  )
}
