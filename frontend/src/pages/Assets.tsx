import type { Asset } from '../api'
import { CrudPage } from '../components/CrudPage'
import { useChoices, useRefreshPrices } from '../hooks'
import { dateTime, money, formOf } from '../format'

export default function Assets() {
  const choices = useChoices()
  const refresh = useRefreshPrices()
  return (
    <CrudPage<Asset>
      title="Activos"
      noun="Activo"
      endpoint="/assets/"
      actions={
        <button className="btn" onClick={() => refresh.mutate(undefined)} disabled={refresh.isPending}>
          {refresh.isPending ? 'Actualizando…' : 'Actualizar precios'}
        </button>
      }
      intro={
        <p className="muted small">
          Yahoo: tickers de acciones/ETF/fondos (VOO, FXAIX) o futuros de metales (GC=F oro, SI=F plata). CoinGecko: el id de la
          moneda (bitcoin, solana). Un precio manual siempre tiene prioridad.
          {refresh.data?.failed.length ? <strong> Sin precio: {refresh.data.failed.join(', ')}</strong> : null}
        </p>
      }
      columns={[
        {
          label: 'Símbolo',
          render: (r) => (
            <>
              <strong>{r.symbol}</strong>
              <small className="block muted">{r.name}</small>
            </>
          ),
        },
        { label: 'Clase', className: 'hide-sm', render: (r) => r.asset_class_label },
        {
          label: 'Fuente',
          render: (r) => (r.manual_price !== null ? 'Manual' : `${r.price_source}${r.source_id ? ` · ${r.source_id}` : ''}`),
        },
        { label: 'Precio', className: 'num', render: (r) => money(r.price) },
        { label: 'Actualizado', className: 'hide-sm', render: (r) => (r.manual_price !== null ? '—' : dateTime(r.last_price_at)) },
      ]}
      fields={[
        { name: 'symbol', label: 'Símbolo', required: true },
        { name: 'name', label: 'Nombre' },
        { name: 'asset_class', label: 'Clase', type: 'select', options: choices.data?.asset_classes, required: true },
        { name: 'price_source', label: 'Fuente de precio', type: 'select', options: choices.data?.price_sources, required: true },
        { name: 'source_id', label: 'ID en la fuente', help: 'Vacío = usar el símbolo' },
        { name: 'manual_price', label: 'Precio manual (USD)', type: 'number', nullable: true, help: 'Vacío = usar precio en vivo' },
      ]}
      defaults={{ symbol: '', name: '', asset_class: 'stock', price_source: 'yahoo', source_id: '', manual_price: '' }}
      toForm={(r) => formOf(r, ['symbol', 'name', 'asset_class', 'price_source', 'source_id', 'manual_price'])}
    />
  )
}
