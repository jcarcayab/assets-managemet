// Loads Plaid's official Link script on demand and opens it with a link token from our backend.

type LinkHandler = { open: () => void; destroy: () => void }
type PlaidFactory = {
  create: (config: {
    token: string
    receivedRedirectUri?: string
    onSuccess: (publicToken: string, metadata: unknown) => void
    onExit: (error: { display_message?: string; error_message?: string } | null) => void
  }) => LinkHandler
}

// OAuth banks send the browser away and back to PLAID_REDIRECT_URI (?oauth_state_id=…). Link must then be
// reopened with the same token, so remember what we were doing across that round trip.
const PENDING_KEY = 'plaid-link-pending'
export type PendingLink = { linkToken: string; itemId: number | null }

function rememberPending(pending: PendingLink) {
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending))
  } catch {
    // storage blocked: OAuth banks won't resume, the rest still works
  }
}

export function takePendingOAuth(): PendingLink | null {
  if (!new URLSearchParams(window.location.search).has('oauth_state_id')) return null
  try {
    const raw = sessionStorage.getItem(PENDING_KEY)
    sessionStorage.removeItem(PENDING_KEY)
    return raw ? (JSON.parse(raw) as PendingLink) : null
  } catch {
    return null
  }
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

/**
 * Opens Link; resolves with the public token, or null if the user closed it.
 * `itemId` marks a reconnection (update mode); `resumeOAuth` finishes a flow coming back from an OAuth bank.
 */
export async function openPlaidLink(
  linkToken: string,
  { itemId = null, resumeOAuth = false }: { itemId?: number | null; resumeOAuth?: boolean } = {},
): Promise<string | null> {
  const Plaid = await loadPlaid()
  if (!resumeOAuth) rememberPending({ linkToken, itemId })
  return new Promise((resolve, reject) => {
    const handler = Plaid.create({
      token: linkToken,
      ...(resumeOAuth ? { receivedRedirectUri: window.location.href } : {}),
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
