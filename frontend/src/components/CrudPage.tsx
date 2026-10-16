import { useState } from 'react'
import type { ReactNode } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Page } from '../api'
import { useWrite } from '../hooks'
import { FormModal } from './FormModal'
import type { Field, FormValues } from './FormModal'

const PAGE_SIZE = 100 // the backend's OptionalPagination.page_size

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
  /** Reshape the form payload before sending (e.g. fold several inputs into one JSON field) */
  toPayload?: (body: Record<string, unknown>, values: FormValues) => Record<string, unknown>
  /** Load the list a page at a time (the endpoint must support `?page=`) */
  paginated?: boolean
}

export function CrudPage<T extends { id: number }>(props: Props<T>) {
  const { title, endpoint, query = '', columns, fields, defaults, toForm, noun, emptyText, actions, intro, paginated } = props
  const [page, setPage] = useState({ query, n: 1 })
  const pageNum = page.query === query ? page.n : 1 // a new filter starts over at page 1
  const url = paginated ? `${endpoint}${query}${query ? '&' : '?'}page=${pageNum}` : `${endpoint}${query}`
  const list = useQuery({
    queryKey: [endpoint, query, paginated ? pageNum : null],
    queryFn: async () => {
      if (!paginated) return { count: null, rows: await api<T[]>(url) }
      const data = await api<Page<T>>(url)
      return { count: data.count, rows: data.results }
    },
    placeholderData: keepPreviousData,
  })
  const rows = list.data?.rows
  const pages = list.data?.count ? Math.ceil(list.data.count / PAGE_SIZE) : 1
  const goTo = (n: number) => setPage({ query, n })
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
      ) : !rows?.length ? (
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
              {rows.map((row) => (
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
      {paginated && pages > 1 && (
        <nav className="pager" aria-label="Paginación">
          <button className="btn" disabled={pageNum <= 1} onClick={() => goTo(pageNum - 1)}>
            ← Anterior
          </button>
          <span className="muted small">
            Página {pageNum} de {pages} · {list.data?.count?.toLocaleString()} registros
            {list.isPlaceholderData && ' · cargando…'}
          </span>
          <button className="btn" disabled={pageNum >= pages} onClick={() => goTo(pageNum + 1)}>
            Siguiente →
          </button>
        </nav>
      )}
      {editing && (
        <FormModal
          title={editing === 'new' ? `Nuevo: ${noun}` : `Editar: ${noun}`}
          fields={fields}
          initial={editing === 'new' ? defaults : toForm(editing)}
          onSubmit={(body, values) => save.mutateAsync(props.toPayload ? props.toPayload(body, values) : body)}
          onDelete={editing !== 'new' ? () => remove.mutateAsync(editing.id) : undefined}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  )
}
