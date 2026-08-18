'use client'

import { useQuery } from '@tanstack/react-query'
import {
  api,
  HealthResponse,
  ServiceHealthCheck,
  SystemStats,
} from '@/lib/api'

export type OverallSystemStatus =
  | 'available'
  | 'degraded'
  | 'unavailable'
  | 'checking'
  | 'unknown'

/**
 * Provides one status contract for both current and legacy backend responses.
 * The stats endpoint doubles as a real database check only when the deployed
 * backend does not report Supabase health itself.
 */
export function useSystemHealth(options: { includeStats?: boolean } = {}) {
  const healthQuery = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => api.healthCheck(),
    refetchInterval: 30000,
    retry: 1,
  })

  const shouldFetchStats = Boolean(options.includeStats) || (
    !healthQuery.isLoading
    && (healthQuery.isError || !healthQuery.data?.checks?.supabase)
  )

  const statsQuery = useQuery<SystemStats>({
    queryKey: ['stats'],
    queryFn: () => api.getStats(),
    refetchInterval: 30000,
    retry: 1,
    enabled: shouldFetchStats,
  })

  const statsUnavailable = statsQuery.isError || Boolean(statsQuery.data?.error)
  const statsAvailability = statsUnavailable
    ? false
    : statsQuery.data
      ? true
      : undefined

  let apiCheck: ServiceHealthCheck | undefined = healthQuery.data?.checks?.api
  if (!apiCheck && statsAvailability === true) {
    apiCheck = {
      status: 'available',
      message: 'API request succeeded through the statistics endpoint',
    }
  } else if (!apiCheck && healthQuery.isError && statsAvailability === false) {
    apiCheck = {
      status: 'unavailable',
      message: 'API requests failed',
    }
  }

  let supabaseCheck: ServiceHealthCheck | undefined =
    healthQuery.data?.checks?.supabase
  if (!supabaseCheck && statsAvailability === true) {
    supabaseCheck = {
      status: 'available',
      message: 'Database query succeeded',
    }
  } else if (!supabaseCheck && statsAvailability === false) {
    supabaseCheck = {
      status: 'unavailable',
      message: 'Database-backed statistics request failed',
    }
  }

  let overallStatus: OverallSystemStatus = 'unknown'
  if ((!apiCheck || !supabaseCheck) && (healthQuery.isLoading || statsQuery.isLoading)) {
    overallStatus = 'checking'
  } else if (apiCheck?.status === 'unavailable') {
    overallStatus = 'unavailable'
  } else if (
    apiCheck?.status === 'available'
    && supabaseCheck?.status === 'unavailable'
  ) {
    overallStatus = 'degraded'
  } else if (
    apiCheck?.status === 'available'
    && supabaseCheck?.status === 'available'
  ) {
    overallStatus = 'available'
  }

  return {
    health: healthQuery.data,
    healthLoading: healthQuery.isLoading,
    healthRequestFailed: healthQuery.isError,
    stats: statsQuery.data,
    statsLoading: statsQuery.isLoading,
    statsUnavailable,
    refetchStats: statsQuery.refetch,
    apiCheck,
    supabaseCheck,
    overallStatus,
  }
}
