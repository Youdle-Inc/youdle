'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { 
  FileText, 
  Activity, 
  CheckCircle2, 
  AlertTriangle,
  ShoppingCart,
  AlertOctagon
} from 'lucide-react'
import { API_BASE_URL, api } from '@/lib/api'
import { useSystemHealth } from '@/lib/hooks/useSystemHealth'
import { StatsCard } from '@/components/StatsCard'
import { RunStatus } from '@/components/RunStatus'
import { QuickActions } from '@/components/QuickActions'
import { ScheduleBanner } from '@/components/ScheduleBanner'
import { NewsletterReadinessCard } from '@/components/NewsletterReadinessCard'
import { formatNumber } from '@/lib/utils'

export default function DashboardPage() {
  const queryClient = useQueryClient()

  const {
    stats,
    statsLoading,
    statsUnavailable,
    refetchStats,
    healthLoading,
    healthRequestFailed,
    apiCheck,
    supabaseCheck,
  } = useSystemHealth({ includeStats: true })

  // Cancel job mutation
  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => api.cancelJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recentJobs'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
  })

  // Fetch recent jobs
  const {
    data: jobsData,
    isError: jobsRequestFailed,
    refetch: refetchJobs,
  } = useQuery({
    queryKey: ['recentJobs'],
    queryFn: async () => {
      const data = await api.listJobs({ limit: 5 })
      // Sort jobs by started_at or completed_at, latest first
      const sortedJobs = [...(data.jobs || [])].sort((a, b) => {
        const aDate = new Date(a.started_at || a.completed_at || a.created_at || 0).getTime()
        const bDate = new Date(b.started_at || b.completed_at || b.created_at || 0).getTime()
        return bDate - aDate
      })
      return { ...data, jobs: sortedJobs }
    },
    refetchInterval: 10000, // Refresh every 10 seconds
  })

  const activeJob = jobsData?.jobs?.find(
    (job) => job.status === 'pending' || job.status === 'running'
  )
  const apiAvailable = apiCheck?.status === 'available'
  const supabaseAvailable = supabaseCheck?.status === 'available'
  const apiChecking = !apiCheck && healthLoading
  const supabaseChecking = !supabaseCheck && (healthLoading || statsLoading)

  const handleSearchPreview = () => {
    window.location.href = '/articles'
  }

  const handleStartGeneration = (jobId: string) => {
    refetchJobs()
    refetchStats()
  }

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-stone-900">
          Dashboard
        </h1>
        <p className="mt-2 text-stone-500">
          Monitor your blog generation pipeline and manage content.
        </p>
      </div>

      {/* Schedule Banner */}
      <ScheduleBanner
        lastCompletedAt={
          jobsData?.jobs?.find(j => j.status === 'completed')?.completed_at
        }
      />

      {/* Newsletter Readiness */}
      <NewsletterReadinessCard />

      {/* Stats Grid */}
      {(statsUnavailable || jobsRequestFailed || cancelMutation.isError) && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          {cancelMutation.isError
            ? `Could not mark the job cancelled: ${cancelMutation.error.message}`
            : 'Some dashboard data is unavailable. No missing data has been treated as zero.'}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 stagger-children">
        <StatsCard
          title="Total Posts"
          value={statsLoading ? '...' : statsUnavailable ? '—' : formatNumber(stats?.posts.total || 0)}
          subtitle={statsUnavailable ? 'Unavailable' : `${stats?.posts.draft || 0} drafts`}
          icon={FileText}
        />
        <StatsCard
          title="Running Jobs"
          value={statsLoading ? '...' : statsUnavailable ? '—' : stats?.jobs.running || 0}
          subtitle={statsUnavailable ? 'Unavailable' : `${stats?.jobs.completed || 0} completed`}
          icon={Activity}
        />
        <StatsCard
          title="Shoppers Articles"
          value={statsLoading ? '...' : statsUnavailable ? '—' : formatNumber(stats?.posts.by_category?.shoppers || 0)}
          icon={ShoppingCart}
        />
        <StatsCard
          title="Recall Alerts"
          value={statsLoading ? '...' : statsUnavailable ? '—' : formatNumber(stats?.posts.by_category?.recall || 0)}
          icon={AlertOctagon}
        />
      </div>

      {/* Status breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="flex items-center gap-4 p-4 rounded-xl bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800">
          <CheckCircle2 className="w-8 h-8 text-green-700 dark:text-green-400" />
          <div>
            <p className="text-sm text-black  font-medium">Published</p>
            <p className="text-2xl font-bold text-black ">
              {statsUnavailable ? '—' : stats?.posts.published || 0}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 p-4 rounded-xl bg-purple-50  border border-purple-200 dark:border-purple-800">
          <Activity className="w-8 h-8 text-black" />
          <div>
            <p className="text-sm text-black font-medium">Reviewed</p>
            <p className="text-2xl font-bold text-black ">
              {statsUnavailable ? '—' : stats?.posts.reviewed || 0}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 p-4 rounded-xl bg-amber-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
          <AlertTriangle className="w-8 h-8 text-red-700 dark:text-black-400" />
          <div>
            <p className="text-sm text-black  font-medium">Failed Jobs</p>
            <p className="text-2xl font-bold text-black ">
              {statsUnavailable ? '—' : stats?.jobs.failed || 0}
            </p>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <QuickActions 
        onSearchPreview={handleSearchPreview}
        onStartGeneration={handleStartGeneration}
        hasActiveJob={Boolean(activeJob)}
      />

      {/* Recent Jobs */}
      {jobsRequestFailed ? (
        <div className="rounded-2xl bg-white border border-stone-200 p-6">
          <h3 className="text-lg font-semibold text-stone-900 mb-2">Recent Runs</h3>
          <p className="text-sm text-red-700">Jobs could not be loaded from the API.</p>
        </div>
      ) : (
        <RunStatus
          jobs={jobsData?.jobs || []}
          onCancel={(jobId) => cancelMutation.mutate(jobId)}
        />
      )}

      {/* API Status */}
      <div className="rounded-2xl bg-white border border-stone-200 p-6">
        <h3 className="text-lg font-semibold text-stone-900 mb-4">System Status</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="flex items-center gap-3 p-3 rounded-xl bg-midnight-50">
            <div className={`w-3 h-3 rounded-full ${
              apiChecking
                ? 'bg-yellow-500'
                : apiAvailable
                  ? 'bg-green-500'
                  : apiCheck?.status === 'unavailable'
                    ? 'bg-red-500'
                    : 'bg-stone-400'
            }`} />
            <div>
              <p className="text-sm font-medium text-stone-900">FastAPI Backend</p>
              <p className="text-xs text-stone-500">
                {apiChecking
                  ? 'Checking…'
                  : apiAvailable
                    ? API_BASE_URL
                    : apiCheck?.message || (healthRequestFailed ? 'Unavailable' : 'Status not reported')}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 p-3 rounded-xl bg-midnight-50">
            <div className={`w-3 h-3 rounded-full ${
              supabaseChecking
                ? 'bg-yellow-500'
                : supabaseAvailable
                  ? 'bg-green-500'
                  : supabaseCheck?.status === 'unavailable'
                    ? 'bg-red-500'
                    : 'bg-stone-400'
            }`} />
            <div>
              <p className="text-sm font-medium text-stone-900">Supabase</p>
              <p className="text-xs text-stone-500">
                {supabaseChecking
                  ? 'Checking…'
                  : supabaseCheck?.message || 'Status not reported'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}



