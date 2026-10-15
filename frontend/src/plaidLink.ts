// Loads Plaid's official Link script on demand and opens it with a link token from our backend.

type LinkHandler = { open: () => void; destroy: () => void }
type PlaidFactory = {
  create: (config: {
    token: string
    onSuccess: (publicToken: string, metadata: unknown) => void
    onExit: (error: { display_message?: string; error_message?: string } | null) => void
  }) => LinkHandler
}

declare global {
  interface Window {
    Plaid?: PlaidFactory
  }
}

const SCRIPT_URL = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js'
let loading: Promise<PlaidFactory> | null = null

function loadPlaid(): Promise<PlaidFactory> {
  if (window.Plaid) return Promise.resolve(window.Plaid)
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = SCRIPT_URL
    script.async = true
    script.onload = () => (window.Plaid ? resolve(window.Plaid) : reject(new Error('Plaid Link no se cargó')))
    script.onerror = () => {
      loading = null
      reject(new Error('No se pudo cargar Plaid Link (¿bloqueador de contenido?)'))
    }
    document.head.appendChild(script)
  })
  return loading
}

/** Opens Link; resolves with the public token, or null if the user closed it. */
export async function openPlaidLink(linkToken: string): Promise<string | null> {
  const Plaid = await loadPlaid()
  return new Promise((resolve, reject) => {
    const handler = Plaid.create({
      token: linkToken,
      onSuccess: (publicToken) => {
        handler.destroy()
        resolve(publicToken)
      },
      onExit: (error) => {
        handler.destroy()
        if (error) reject(new Error(error.display_message || error.error_message || 'Plaid Link falló'))
        else resolve(null)
      },
    })
    handler.open()
  })
}
