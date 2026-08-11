'use client'

import { cn, getStatusColor, formatDate, formatElapsedTime } from '@/lib/utils'
import { Loader2, CheckCircle2, XCircle, Clock, Ban, Timer } from 'lucide-react'

interface Job {
  id: string
  status: string
  config: {
    batch_size?: number
    model?: string
  }
  created_at?: string | null
  started_at: string | null
  completed_at: string | null
  result?: {
    posts_generated?: number
  } | null
  error?: string | null
}

interface RunStatusProps {
  jobs: Job[]
  className?: string
  onCancel?: (jobId: string) => void
}

const statusIcons = {
  pending: Clock,
  running: Loader2,
  completed: CheckCircle2,
  failed: XCircle,
  cancelled: Ban,
}

export function RunStatus({ jobs, className, onCancel }: RunStatusProps) {
  if (jobs.length === 0) {
    return (
      <div className={cn('rounded-2xl bg-white  border border-stone-200  p-6', className)}>
        <h3 className="text-lg font-semibold text-stone-900  mb-4">Recent Runs</h3>
        <p className="text-stone-500  text-sm">No recent jobs found.</p>
      </div>
    )
  }

  return (
    <div className={cn('rounded-2xl bg-white  border border-stone-200  p-6', className)}>
      <h3 className="text-lg font-semibold text-stone-900  mb-4">Recent Runs</h3>
      
      <div className="space-y-3">
        {jobs.map((job) => {
          const StatusIcon = statusIcons[job.status as keyof typeof statusIcons] || Clock
          const elapsedTime = formatElapsedTime(job.started_at, job.completed_at)

          return (
            <div
              key={job.id}
              className="flex items-center justify-between p-4 rounded-xl bg-midnight-50  border border-midnight-100 "
            >
              <div className="flex items-center gap-3 flex-1">
                <div className={cn(
                  'flex items-center justify-center w-10 h-10 rounded-lg',
                  job.status === 'running' ? 'bg-blue-100 dark:bg-blue-900/30' :
                  job.status === 'completed' ? 'bg-green-100 dark:bg-green-900/30' :
                  job.status === 'failed' ? 'bg-red-100 dark:bg-red-900/30' :
                  'bg-midnight-100 '
                )}>
                  <StatusIcon className={cn(
                    'w-5 h-5',
                    job.status === 'running' && 'animate-spin text-blue-600 dark:text-blue-400',
                    job.status === 'completed' && 'text-green-600',
                    job.status === 'failed' && 'text-red-600',
                    job.status === 'pending' && 'text-yellow-600 dark:text-yellow-400',
                    job.status === 'cancelled' && 'text-stone-500'
                  )} />
                </div>

                <div className="flex-1">
                  <p className="text-sm font-medium text-stone-900 ">
                    {job.config?.batch_size || 10} articles • {job.config?.model || 'gpt-4'}
                  </p>
                  <div className="flex items-center gap-3 mt-1">
                    <p className="text-xs text-stone-500 ">
                      {formatDate(job.started_at || job.completed_at || job.created_at || null)}
                    </p>
                    {job.started_at && (
                      <div className="flex items-center gap-1 text-xs text-stone-500 ">
                        <Timer className="w-3 h-3" />
                        <span>{elapsedTime}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <div className="text-right">
                  <span className={cn(
                    'inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium',
                    getStatusColor(job.status)
                  )}>
                    {job.status}
                  </span>
                  {job.result?.posts_generated !== undefined && (
                    <p className="text-xs text-stone-500  mt-1">
                      {job.result.posts_generated} posts
                    </p>
                  )}
                  {job.error && (
                    <p className="mt-1 max-w-md text-xs text-red-700" title={job.error}>
                      {job.error}
                    </p>
                  )}
                </div>
                {(job.status === 'pending' || job.status === 'running') && onCancel && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onCancel(job.id)
                    }}
                    className="p-2 rounded-lg text-red-500 hover:bg-red-100 transition-colors"
                    title="Mark job cancelled"
                  >
                    <Ban className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}



