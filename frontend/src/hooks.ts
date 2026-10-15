import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type { Account, Asset, Choices, Settings, Summary } from './api'

export const useChoices = () => useQuery({ queryKey: ['choices'], queryFn: () => api<Choices>('/choices/'), staleTime: Infinity })
export const useAccounts = () => useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts/') })
export const useAssets = () => useQuery({ queryKey: ['assets'], queryFn: () => api<Asset[]>('/assets/') })
export const useSummary = () => useQuery({ queryKey: ['summary'], queryFn: () => api<Summary>('/summary/') })
export const useSettings = () => useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/settings/') })

/** Any write can change positions/summary, so refetch everything after it. */
export function useWrite<TArgs, TResult = unknown>(fn: (args: TArgs) => Promise<TResult>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries() })
}

export function useRefreshPrices() {
  return useWrite(() => api<{ updated: string[]; failed: string[] }>('/prices/refresh/', { method: 'POST' }))
}
