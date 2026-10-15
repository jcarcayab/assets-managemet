import type { Asset } from '../api'
import { CrudPage } from '../components/CrudPage'
import type { Field, FormValues } from '../components/FormModal'
import { useChoices, useRefreshPrices } from '../hooks'
import { dateTime, formOf, money } from '../format'

const EXP = 'exp_' // form-field prefix for each exposure category

export default function Assets() {
  const choices = useChoices()
  const refresh = useRefreshPrices()
  const categories = choices.data?.exposure_categories ?? []

  const exposureFields: Field[] = [
    { name: 'custom_exposure', label: 'Fondo multi-activo: definir desglose por categoría', type: 'checkbox', local: true },
    ...categories.map<Field>((c) => ({
      name: `${EXP}${c.value}`,
      label: `${c.label} %`,
      type: 'number',
      local: true,
      show: (v) => Boolean(v.custom_exposure),
    })),
  ]

  const toPayload = (body: Record<string, unknown>, values: FormValues) => {
    const exposures: Record<string, number> = {}
    if (values.custom_exposure) {
      for (const c of categories) {
        const n = Number(values[`${EXP}${c.value}`] || 0)
        if (n) exposures[c.value] = n
      }
    }
    return { ...body, exposures }
  }

  const toForm = (r: Asset): FormValues => ({
    ...formOf(r, ['symbol', 'name', 'asset_class', 'price_source', 'source_id', 'manual_price', 'underlying', 'sector']),
    custom_exposure: Object.keys(r.exposures ?? {}).length > 0,
    ...Object.fromEntries(categories.map((c) => [`${EXP}${c.value}`, r.exposures?.[c.value] ? String(r.exposures[c.value]) : ''])),
  })

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
          moneda (bitcoin, solana). Un precio manual siempre tiene prioridad. “Subyacente” agrupa fondos que replican lo mismo
          (VOO y FXAIX → S&amp;P 500) para medir concentración real.
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
          label: 'Subyacente / sector',
          className: 'hide-sm',
          render: (r) => [r.underlying, r.sector].filter(Boolean).join(' · ') || '—',
        },
        {
          label: 'Fuente',
          className: 'hide-sm',
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
        { name: 'underlying', label: 'Subyacente', help: 'Ej. S&P 500' },
        { name: 'sector', label: 'Sector', help: 'Ej. Crypto, Tecnología' },
        ...exposureFields,
      ]}
      defaults={{
        symbol: '', name: '', asset_class: 'stock', price_source: 'yahoo', source_id: '', manual_price: '', underlying: '',
        sector: '', custom_exposure: false,
      }}
      toForm={toForm}
      toPayload={toPayload}
    />
  )
}
