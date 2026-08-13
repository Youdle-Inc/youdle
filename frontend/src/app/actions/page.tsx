'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  PlayCircle,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
  ExternalLink,
  Calendar,
  Play,
  Ban,
  Power,
  PowerOff
} from 'lucide-react'
import { api, API_BASE_URL, Workflow, WorkflowRun } from '@/lib/api'
import { cn, formatRelativeTime } from '@/lib/utils'
import { TriggerWorkflowModal } from '@/components/TriggerWorkflowModal'

const conclusionColors: Record<string, string> = {
  success: 'bg-green-100 text-green-700',
  failure: 'bg-red-100 text-red-700',
  cancelled: 'bg-stone-100 text-stone-600',
  skipped: 'bg-stone-100 text-stone-500',
}

const statusIcons: Record<string, typeof Clock> = {
  queued: Clock,
  in_progress: RefreshCw,
  completed: CheckCircle2,
}

export default function ActionsPage() {
  const queryClient = useQueryClient()
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(null)
  const [triggerModalOpen, setTriggerModalOpen] = useState(false)
  const [workflowToTrigger, setWorkflowToTrigger] = useState<Workflow | null>(null)

  // Check if GitHub Actions is configured
  const {
    data: status,
    isLoading: statusLoading,
    isError: statusFailed,
    error: statusError,
    refetch: refetchStatus,
  } = useQuery({
    queryKey: ['actionsStatus'],
    queryFn: () => api.getActionsStatus(),
  })

  // Fetch workflows
  const {
    data: workflowsData,
    isLoading: workflowsLoading,
    isError: workflowsFailed,
    error: workflowsError,
    refetch: refetchWorkflows,
  } = useQuery({
    queryKey: ['workflows'],
    queryFn: () => api.listWorkflows(),
    enabled: status?.configured === true,
  })

  // Fetch runs for selected workflow
  const {
    data: runsData,
    isLoading: runsLoading,
    isError: runsFailed,
    error: runsError,
    refetch: refetchRuns,
  } = useQuery({
    queryKey: ['workflowRuns', selectedWorkflow?.id],
    queryFn: () =>
      selectedWorkflow ? api.listWorkflowRuns(selectedWorkflow.id, { limit: 20 }) : null,
    enabled: !!selectedWorkflow,
    refetchInterval: 30000,
  })

  // Cancel mutation
  const cancelMutation = useMutation({
    mutationFn: (runId: number) => api.cancelWorkflowRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflowRuns'] })
    },
  })

  // Trigger mutation
  const triggerMutation = useMutation({
    mutationFn: ({ workflowId, data }: { workflowId: number; data: { ref?: string; inputs?: Record<string, string | boolean> } }) =>
      api.triggerWorkflow(workflowId, data),
    onSuccess: () => {
      setTriggerModalOpen(false)
      setWorkflowToTrigger(null)
      queryClient.invalidateQueries({ queryKey: ['workflowRuns'] })
    },
  })

  // Enable/disable mutations
  const enableMutation = useMutation({
    mutationFn: (workflowId: number) => api.enableWorkflow(workflowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })

  const disableMutation = useMutation({
    mutationFn: (workflowId: number) => api.disableWorkflow(workflowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })

  const workflows = workflowsData?.workflows || []
  const runs = runsData?.runs || []

  // Loading state
  if (statusLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 text-youdle-500 animate-spin" />
      </div>
    )
  }

  // A network, CORS, or API URL error previously rendered an empty Actions page.
  if (statusFailed) {
    return (
      <div className="space-y-8 animate-fade-in">
        <div>
          <h1 className="text-3xl font-bold text-stone-900">Actions</h1>
          <p className="mt-2 text-stone-500">Manage GitHub Actions workflows</p>
        </div>
        <div role="alert" className="rounded-2xl bg-red-50 border border-red-200 p-6">
          <div className="flex items-start gap-4">
            <AlertCircle className="w-6 h-6 text-red-600 flex-shrink-0" />
            <div className="min-w-0">
              <h3 className="font-semibold text-red-900">Could not reach the Actions API</h3>
              <p className="mt-1 text-sm text-red-700">
                {statusError?.message || 'The Actions status request failed.'}
              </p>
              <p className="mt-2 break-all text-xs text-red-600">
                API: {API_BASE_URL}/api/actions/status
              </p>
              <button
                type="button"
                onClick={() => refetchStatus()}
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-red-100 px-3 py-2 text-sm font-medium text-red-800 hover:bg-red-200"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Not configured state
  if (status && !status.configured) {
    return (
      <div className="space-y-8 animate-fade-in">
        <div>
          <h1 className="text-3xl font-bold text-stone-900">Actions</h1>
          <p className="mt-2 text-stone-500">Manage GitHub Actions workflows</p>
        </div>
        <div className="rounded-2xl bg-amber-50 border border-amber-200 p-6">
          <div className="flex items-start gap-4">
            <AlertCircle className="w-6 h-6 text-amber-600 flex-shrink-0" />
            <div>
              <h3 className="font-semibold text-amber-900">GitHub Actions Not Configured</h3>
              <p className="mt-1 text-amber-700">
                Add the following environment variables to enable this feature:
              </p>
              <ul className="mt-2 text-sm text-amber-700 list-disc list-inside space-y-1">
                <li><code className="bg-amber-100 px-1 rounded">GITHUB_TOKEN</code> - Personal access token with actions permissions</li>
                <li><code className="bg-amber-100 px-1 rounded">GITHUB_OWNER</code> - Repository owner (username or org)</li>
                <li><code className="bg-amber-100 px-1 rounded">GITHUB_REPO</code> - Repository name</li>
              </ul>
              {status.error && (
                <p className="mt-3 text-sm text-amber-600 bg-amber-100 px-2 py-1 rounded">{status.error}</p>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-stone-900">Actions</h1>
          <p className="mt-2 text-stone-500">
            Manage GitHub Actions workflows. View runs, trigger new ones, or cancel in-progress.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => refetchWorkflows()}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-stone-600 hover:text-stone-900 hover:bg-stone-100 rounded-lg transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          {status?.configured && (
            <a
              href={`https://github.com/${status.owner}/${status.repo}/actions`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-stone-600 hover:text-stone-900 hover:bg-stone-100 rounded-lg transition-colors"
            >
              <ExternalLink className="w-4 h-4" />
              Open in GitHub
            </a>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Workflows List */}
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-stone-900">Workflows</h2>

          {workflowsLoading && (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="w-6 h-6 text-youdle-500 animate-spin" />
            </div>
          )}

          {workflowsFailed && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              <p className="font-medium">Workflows could not be loaded.</p>
              <p className="mt-1">{workflowsError?.message || 'The GitHub workflows request failed.'}</p>
              <button
                type="button"
                onClick={() => refetchWorkflows()}
                className="mt-3 inline-flex items-center gap-2 rounded-lg bg-red-100 px-3 py-2 font-medium hover:bg-red-200"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </button>
            </div>
          )}

          {!workflowsLoading && !workflowsFailed && workflows.length === 0 && (
            <div className="rounded-xl border border-stone-200 bg-white p-4 text-sm text-stone-600">
              No workflows were returned for {status?.owner}/{status?.repo}.
            </div>
          )}

          {workflows.map((workflow) => {
            const isDisabled = workflow.state === 'disabled_manually'
            return (
              <div
                key={workflow.id}
                className={cn(
                  'p-4 rounded-xl border transition-all',
                  selectedWorkflow?.id === workflow.id
                    ? 'bg-youdle-50 border-youdle-300'
                    : 'bg-white border-stone-200 hover:border-stone-300'
                )}
              >
                <button
                  onClick={() => setSelectedWorkflow(workflow)}
                  className="w-full text-left"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className={cn(
                          'font-medium truncate',
                          isDisabled ? 'text-stone-400' : 'text-stone-900'
                        )}>
                          {workflow.name}
                        </p>
                        {isDisabled && (
                          <span className="px-1.5 py-0.5 text-xs font-medium bg-stone-100 text-stone-500 rounded">
                            Disabled
                          </span>
                        )}
                      </div>
                      {workflow.schedule && (
                        <p className="text-xs text-stone-500 flex items-center gap-1 mt-1">
                          <Calendar className="w-3 h-3" />
                          {workflow.schedule}
                        </p>
                      )}
                    </div>
                  </div>
                </button>

                {/* Action buttons */}
                <div className="flex items-center gap-1 mt-3 pt-3 border-t border-stone-100">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setWorkflowToTrigger(workflow)
                      setTriggerModalOpen(true)
                    }}
                    disabled={isDisabled}
                    className={cn(
                      'flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors',
                      isDisabled
                        ? 'text-stone-400 cursor-not-allowed'
                        : 'text-youdle-600 hover:bg-youdle-100'
                    )}
                    title="Run workflow"
                  >
                    <Play className="w-3.5 h-3.5" />
                    Run
                  </button>

                  {workflow.schedule && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (isDisabled) {
                          enableMutation.mutate(workflow.id)
                        } else {
                          disableMutation.mutate(workflow.id)
                        }
                      }}
                      disabled={enableMutation.isPending || disableMutation.isPending}
                      className={cn(
                        'flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg transition-colors',
                        isDisabled
                          ? 'text-green-600 hover:bg-green-100'
                          : 'text-stone-500 hover:bg-stone-100'
                      )}
                      title={isDisabled ? 'Enable scheduled runs' : 'Disable scheduled runs'}
                    >
                      {isDisabled ? (
                        <>
                          <Power className="w-3.5 h-3.5" />
                          Enable
                        </>
                      ) : (
                        <>
                          <PowerOff className="w-3.5 h-3.5" />
                          Disable
                        </>
                      )}
                    </button>
                  )}

                  <a
                    href={workflow.html_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-stone-400 hover:text-stone-600 hover:bg-stone-100 rounded-lg transition-colors ml-auto"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>
              </div>
            )
          })}
        </div>

        {/* Workflow Runs */}
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-lg font-semibold text-stone-900">
            {selectedWorkflow ? `${selectedWorkflow.name} Runs` : 'Select a Workflow'}
          </h2>

          {!selectedWorkflow && (
            <div className="text-center py-16 rounded-2xl bg-white border border-stone-200">
              <PlayCircle className="w-12 h-12 text-stone-400 mx-auto mb-4" />
              <p className="text-stone-500">Select a workflow to view its runs</p>
            </div>
          )}

          {selectedWorkflow && runsLoading && (
            <div className="flex items-center justify-center py-8">
              <RefreshCw className="w-6 h-6 text-youdle-500 animate-spin" />
            </div>
          )}

          {selectedWorkflow && runsFailed && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              <p className="font-medium">Workflow runs could not be loaded.</p>
              <p className="mt-1">{runsError?.message || 'The workflow runs request failed.'}</p>
              <button
                type="button"
                onClick={() => refetchRuns()}
                className="mt-3 inline-flex items-center gap-2 rounded-lg bg-red-100 px-3 py-2 font-medium hover:bg-red-200"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </button>
            </div>
          )}

          {selectedWorkflow && !runsLoading && !runsFailed && runs.length === 0 && (
            <div className="text-center py-16 rounded-2xl bg-white border border-stone-200">
              <Clock className="w-12 h-12 text-stone-400 mx-auto mb-4" />
              <p className="text-stone-500">No runs found for this workflow</p>
            </div>
          )}

          {runs.map((run) => {
            const StatusIcon = statusIcons[run.status] || Clock
            const isInProgress = run.status === 'in_progress' || run.status === 'queued'

            return (
              <div key={run.id} className="p-4 rounded-xl bg-white border border-stone-200">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        'flex items-center justify-center w-10 h-10 rounded-lg',
                        run.status === 'in_progress'
                          ? 'bg-blue-100'
                          : run.status === 'queued'
                          ? 'bg-amber-100'
                          : run.conclusion === 'success'
                          ? 'bg-green-100'
                          : run.conclusion === 'failure'
                          ? 'bg-red-100'
                          : 'bg-stone-100'
                      )}
                    >
                      <StatusIcon
                        className={cn(
                          'w-5 h-5',
                          run.status === 'in_progress' && 'animate-spin text-blue-600',
                          run.status === 'queued' && 'text-amber-600',
                          run.conclusion === 'success' && 'text-green-600',
                          run.conclusion === 'failure' && 'text-red-600',
                          !['in_progress', 'queued'].includes(run.status) &&
                            !run.conclusion &&
                            'text-stone-500'
                        )}
                      />
                    </div>

                    <div>
                      <p className="font-medium text-stone-900">#{run.run_number}</p>
                      <p className="text-sm text-stone-500">
                        {run.event === 'workflow_dispatch' ? 'Manual' : run.event}
                        {run.actor && ` by ${run.actor}`}
                        {' \u2022 '}
                        {formatRelativeTime(run.created_at)}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {run.conclusion && (
                      <span
                        className={cn(
                          'px-2.5 py-1 rounded-lg text-xs font-medium',
                          conclusionColors[run.conclusion] || 'bg-stone-100 text-stone-600'
                        )}
                      >
                        {run.conclusion}
                      </span>
                    )}

                    {isInProgress && (
                      <button
                        onClick={() => cancelMutation.mutate(run.id)}
                        disabled={cancelMutation.isPending}
                        className="p-1.5 rounded-lg text-red-500 hover:bg-red-100 transition-colors"
                        title="Cancel run"
                      >
                        <Ban className="w-4 h-4" />
                      </button>
                    )}

                    <a
                      href={run.html_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 rounded-lg text-stone-400 hover:text-stone-600 hover:bg-stone-100 transition-colors"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                  </div>
                </div>

                {run.duration_seconds != null && run.status === 'completed' && (
                  <p className="mt-2 text-xs text-stone-400">
                    Duration: {Math.floor(run.duration_seconds / 60)}m {run.duration_seconds % 60}s
                  </p>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Trigger Modal */}
      {workflowToTrigger && (
        <TriggerWorkflowModal
          workflow={workflowToTrigger}
          open={triggerModalOpen}
          onClose={() => {
            setTriggerModalOpen(false)
            setWorkflowToTrigger(null)
          }}
          onTrigger={(inputs) => {
            triggerMutation.mutate({
              workflowId: workflowToTrigger.id,
              data: { inputs },
            })
          }}
          isLoading={triggerMutation.isPending}
        />
      )}
    </div>
  )
}
