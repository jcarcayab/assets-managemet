import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { useWrite } from '../hooks'
import { FormModal } from './FormModal'
import type { Field, FormValues } from './FormModal'

export type Column<T> = { label: string; render: (row: T) => ReactNode; className?: string }

type Props<T extends { id: number }> = {
  title: string
  /** e.g. "/accounts/" */
  endpoint: string
  /** extra query string for the list, e.g. "?account=3" */
  query?: string
  columns: Column<T>[]
  fields: Field[]
  defaults: FormValues
  toForm: (row: T) => FormValues
  noun: string
  emptyText?: string
  actions?: ReactNode
  intro?: ReactNode
}

export function CrudPage<T extends { id: number }>(props: Props<T>) {
  const { title, endpoint, query = '', columns, fields, defaults, toForm, noun, emptyText, actions, intro } = props
  const list = useQuery({ queryKey: [endpoint, query], queryFn: () => api<T[]>(`${endpoint}${query}`) })
  const [editing, setEditing] = useState<T | 'new' | null>(null)

  const save = useWrite((body: Record<string, unknown>) =>
    editing && editing !== 'new'
      ? api(`${endpoint}${editing.id}/`, { method: 'PATCH', body })
      : api(endpoint, { method: 'POST', body }),
  )
  const remove = useWrite((id: number) => api(`${endpoint}${id}/`, { method: 'DELETE' }))

  return (
    <section>
      <div className="page-head">
        <h1>{title}</h1>
        <div className="actions">
          {actions}
          <button className="btn primary" onClick={() => setEditing('new')}>
            + {noun}
          </button>
        </div>
      </div>
      {intro}
      {list.isLoading ? (
        <p className="muted">Cargando…</p>
      ) : list.error ? (
        <p className="error">{String(list.error)}</p>
      ) : !list.data?.length ? (
        <p className="empty">{emptyText ?? 'Todavía no hay registros.'}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.label} className={c.className}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.data.map((row) => (
                <tr key={row.id} className="clickable" onClick={() => setEditing(row)}>
                  {columns.map((c) => (
                    <td key={c.label} className={c.className}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <FormModal
          title={editing === 'new' ? `Nuevo: ${noun}` : `Editar: ${noun}`}
          fields={fields}
          initial={editing === 'new' ? defaults : toForm(editing)}
          onSubmit={(body) => save.mutateAsync(body)}
          onDelete={editing !== 'new' ? () => remove.mutateAsync(editing.id) : undefined}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  )
}
