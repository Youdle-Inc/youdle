'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, RefreshCw, Clock, CheckCircle2, XCircle, Ban, Trash2, Eye } from 'lucide-react'
import { api } from '@/lib/api'
import { subscribeToJobs, Job } from '@/lib/supabase'
import { cn, formatDate, formatRelativeTime, getStatusColor } from '@/lib/utils'

const statusIcons = {
  pending: Clock,
  running: RefreshCw,
  completed: CheckCircle2,
  failed: XCircle,
  cancelled: Ban,
}

export default function JobsPage() {
  const queryClient = useQueryClient()
  const [selectedJob, setSelectedJob] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | null>(null)

  // Fetch jobs
  const { data: jobsData, isLoading, isError: jobsFailed } = useQuery({
    queryKey: ['jobs', statusFilter],
    queryFn: () => api.listJobs({ status: statusFilter || undefined, limit: 50 }),
    refetchInterval: 10000,
  })

  // Fetch selected job details
  const { data: jobDetails } = useQuery({
    queryKey: ['jobDetails', selectedJob],
    queryFn: () => selectedJob ? api.getJob(selectedJob) : null,
    enabled: !!selectedJob,
  })

  // Fetch job posts
  const { data: jobPosts } = useQuery({
    queryKey: ['jobPosts', selectedJob],
    queryFn: () => selectedJob ? api.getJobPosts(selectedJob) : null,
    enabled: !!selectedJob,
  })

  // Cancel job mutation
  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => api.cancelJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobDetails'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
  })

  // Subscribe to real-time job updates
  useEffect(() => {
    let channel: ReturnType<typeof subscribeToJobs> | null = null
    
    try {
      channel = subscribeToJobs((payload) => {
        // Invalidate queries when jobs change
        queryClient.invalidateQueries({ queryKey: ['jobs'] })
        if (selectedJob === payload.new?.id) {
          queryClient.invalidateQueries({ queryKey: ['jobDetails', selectedJob] })
        }
      })
    } catch (e) {
      // Supabase not configured - that's fine
      console.log('Realtime not available:', e)
    }

    return () => {
      channel?.unsubscribe()
    }
  }, [queryClient, selectedJob])

  const jobs = jobsData?.jobs || []

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-stone-900">
          Jobs
        </h1>
        <p className="mt-2 text-stone-500">
          Monitor generation jobs and view their results. Status refreshes automatically.
        </p>
      </div>

      {/* Status Filters */}
      <div className="flex items-center gap-2">
        {[null, 'pending', 'running', 'completed', 'failed', 'cancelled'].map((status) => (
          <button
            key={status || 'all'}
            onClick={() => setStatusFilter(status)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-sm font-medium transition-all',
              statusFilter === status
                ? status ? getStatusColor(status) : 'bg-youdle-100 dark:bg-youdle-900/30 text-youdle-700 dark:text-youdle-300'
                : 'bg-midnight-100 text-midnight-600 hover:bg-midnight-200 dark:hover:bg-midnight-700'
            )}
          >
            {status ? status.charAt(0).toUpperCase() + status.slice(1) : 'All'}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Jobs List */}
        <div className="lg:col-span-2 space-y-3">
          {isLoading && (
            <div className="flex items-center justify-center py-16">
              <RefreshCw className="w-8 h-8 text-youdle-500 animate-spin" />
            </div>
          )}

          {jobsFailed && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              Jobs could not be loaded from the API. The list below is not current.
            </div>
          )}

          {cancelMutation.isError && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              Could not mark the job cancelled: {cancelMutation.error.message}
            </div>
          )}

          {!isLoading && !jobsFailed && jobs.length === 0 && (
            <div className="text-center py-16 rounded-2xl bg-white border border-stone-200">
              <Activity className="w-12 h-12 text-stone-600 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-stone-900 mb-2">
                No Jobs Found
              </h3>
              <p className="text-stone-500">
                Start a generation to see jobs here.
              </p>
            </div>
          )}

          {jobs.map((job) => {
            const StatusIcon = statusIcons[job.status as keyof typeof statusIcons] || Clock
            const isSelected = selectedJob === job.id

            return (
              <div
                key={job.id}
                className={cn(
                  'w-full text-left p-4 rounded-xl border transition-all',
                  isSelected
                    ? 'bg-youdle-50 dark:bg-youdle-900/20 border-youdle-300 dark:border-youdle-700'
                    : 'bg-white border-stone-200 hover:border-youdle-300 dark:hover:border-youdle-700'
                )}
              >
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => setSelectedJob(job.id)}
                    className="flex min-w-0 flex-1 items-center justify-between text-left"
                    aria-pressed={isSelected}
                  >
                    <div className="flex items-center gap-3">
                      <div className={cn(
                        'flex items-center justify-center w-10 h-10 rounded-lg',
                        job.status === 'running' ? 'bg-blue-100 dark:bg-blue-900/30' :
                        job.status === 'completed' ? 'bg-green-100 dark:bg-green-900/30' :
                        job.status === 'failed' ? 'bg-red-100 dark:bg-red-900/30' :
                        'bg-midnight-100'
                      )}>
                        <StatusIcon className={cn(
                          'w-5 h-5',
                          job.status === 'running' && 'animate-spin text-blue-600 dark:text-blue-400',
                          job.status === 'completed' && 'text-green-600 dark:text-green-400',
                          job.status === 'failed' && 'text-red-600 dark:text-red-400',
                          job.status === 'pending' && 'text-yellow-600 dark:text-yellow-400',
                          job.status === 'cancelled' && 'text-stone-500'
                        )} />
                      </div>

                      <div>
                        <p className="font-medium text-stone-900">
                          {job.config?.batch_size || 10} articles • {job.config?.model || 'gpt-4'}
                        </p>
                        <p className="text-sm text-stone-500">
                          {formatRelativeTime(job.started_at || job.completed_at || job.created_at)}
                        </p>
                      </div>
                    </div>

                    <span className={cn(
                      'px-2.5 py-1 rounded-lg text-xs font-medium',
                      getStatusColor(job.status)
                    )}>
                      {job.status}
                    </span>
                  </button>

                  {(job.status === 'pending' || job.status === 'running') && (
                    <button
                      type="button"
                      onClick={() => cancelMutation.mutate(job.id)}
                      disabled={cancelMutation.isPending}
                      title="Mark job cancelled"
                      className="ml-2 p-1.5 rounded-lg text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors"
                    >
                      <Ban className="w-4 h-4" />
                    </button>
                  )}
                </div>
                
                {job.result?.posts_generated !== undefined && (
                  <p className="mt-2 text-sm text-stone-500">
                    Generated {job.result.posts_generated} posts
                  </p>
                )}
                
                {job.error && (
                  <p className="mt-2 text-sm text-red-600 dark:text-red-400 line-clamp-1">
                    Error: {job.error}
                  </p>
                )}
              </div>
            )
          })}
        </div>

        {/* Job Details Panel */}
        <div>
          {selectedJob && jobDetails ? (
            <div className="sticky top-8 rounded-2xl bg-white border border-stone-200 p-6">
              <h3 className="text-lg font-semibold text-stone-900 mb-4">
                Job Details
              </h3>
              
              <div className="space-y-4">
                <div>
                  <p className="text-xs text-stone-500 mb-1">Status</p>
                  <span className={cn(
                    'px-2.5 py-1 rounded-lg text-sm font-medium',
                    getStatusColor(jobDetails.status)
                  )}>
                    {jobDetails.status}
                  </span>
                </div>
                
                <div>
                  <p className="text-xs text-stone-500 mb-1">Started</p>
                  <p className="text-sm text-stone-900">
                    {jobDetails.started_at ? formatDate(jobDetails.started_at) : 'Not started'}
                  </p>
                </div>
                
                {jobDetails.completed_at && (
                  <div>
                    <p className="text-xs text-stone-500 mb-1">Completed</p>
                    <p className="text-sm text-stone-900">
                      {formatDate(jobDetails.completed_at)}
                    </p>
                  </div>
                )}
                
                <div>
                  <p className="text-xs text-stone-500 mb-1">Configuration</p>
                  <pre className="text-xs font-mono text-midnight-600 bg-midnight-50 rounded-lg p-3 overflow-x-auto">
                    {JSON.stringify(jobDetails.config, null, 2)}
                  </pre>
                </div>
                
                {jobPosts && jobPosts.count > 0 && (
                  <div>
                    <p className="text-xs text-stone-500 mb-1">
                      Generated Posts ({jobPosts.count})
                    </p>
                    <div className="space-y-2 max-h-48 overflow-y-auto">
                      {jobPosts.posts.map((post: any) => (
                        <a
                          key={post.id}
                          href={`/posts?id=${post.id}`}
                          className="block p-2 rounded-lg bg-midnight-50 hover:bg-midnight-100 dark:hover:bg-stone-100 transition-colors"
                        >
                          <p className="text-sm text-stone-900 line-clamp-1">
                            {post.title}
                          </p>
                        </a>
                      ))}
                    </div>
                  </div>
                )}
                
                {jobDetails.error && (
                  <div>
                    <p className="text-xs text-red-500 mb-1">Error</p>
                    <p className="text-sm text-red-600 dark:text-red-400">
                      {jobDetails.error}
                    </p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="sticky top-8 rounded-2xl bg-white border border-stone-200 p-6 text-center">
              <Eye className="w-8 h-8 text-stone-600 mx-auto mb-2" />
              <p className="text-sm text-stone-500">
                Select a job to view details
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}



