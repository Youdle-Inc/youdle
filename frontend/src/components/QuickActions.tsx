'use client'

import { useState } from 'react'
import { Play, Search, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'

interface QuickActionsProps {
  onSearchPreview?: () => void
  onStartGeneration?: (jobId: string) => void
  hasActiveJob?: boolean
  className?: string
}

interface SavedGenerationConfig {
  batchSize?: number
  searchDaysBack?: number
  model?: string
  usePlaceholderImages?: boolean
  useLegacyOrchestrator?: boolean
}

export function QuickActions({
  onSearchPreview,
  onStartGeneration,
  hasActiveJob = false,
  className,
}: QuickActionsProps) {
  const [isGenerating, setIsGenerating] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [generationMessage, setGenerationMessage] = useState<string | null>(null)
  const [generationError, setGenerationError] = useState<string | null>(null)

  const handleStartGeneration = async () => {
    if (hasActiveJob) return

    setIsGenerating(true)
    setGenerationMessage(null)
    setGenerationError(null)
    try {
      const savedConfig = localStorage.getItem('youdle_config')
      let preferences: SavedGenerationConfig = {}
      if (savedConfig) {
        try {
          preferences = JSON.parse(savedConfig)
        } catch {
          preferences = {}
        }
      }
      const batchSize = Math.min(10, Math.max(1, Number(preferences.batchSize) || 6))
      const searchDaysBack = Math.min(90, Math.max(1, Number(preferences.searchDaysBack) || 3))
      const response = await api.startGeneration({
        batch_size: batchSize,
        search_days_back: searchDaysBack,
        model: preferences.model ?? 'gpt-4',
        use_placeholder_images: preferences.usePlaceholderImages ?? false,
        use_legacy_orchestrator: preferences.useLegacyOrchestrator ?? false,
      })
      setGenerationMessage(`Generation accepted as job ${response.job_id.slice(0, 8)}.`)
      onStartGeneration?.(response.job_id)
    } catch (error) {
      console.error('Failed to start generation:', error)
      setGenerationError(error instanceof Error ? error.message : 'Failed to start generation')
    } finally {
      setIsGenerating(false)
    }
  }

  const handleSearchPreview = async () => {
    setIsSearching(true)
    try {
      onSearchPreview?.()
    } finally {
      setIsSearching(false)
    }
  }

  return (
    <div className={cn('rounded-2xl bg-white border border-stone-200 p-6', className)}>
      <h3 className="text-lg font-semibold text-stone-900 mb-4">Quick Actions</h3>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <button
          onClick={handleStartGeneration}
          disabled={isGenerating || hasActiveJob}
          className={cn(
            'group relative flex items-center justify-center gap-3 px-6 py-4 rounded-xl font-semibold text-sm transition-all duration-200',
            'bg-white text-youdle-700',
            'border-2 border-youdle-500 shadow-lg shadow-youdle-500/20',
            'hover:bg-youdle-50 hover:shadow-xl hover:shadow-youdle-500/30 hover:scale-[1.02] hover:-translate-y-0.5',
            'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 disabled:hover:translate-y-0'
          )}
        >
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-youdle-100">
            {isGenerating ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
          </div>
          <span>{hasActiveJob ? 'Generation in progress' : 'Start Generation'}</span>
        </button>

        <button
          onClick={handleSearchPreview}
          disabled={isSearching}
          className={cn(
            'group relative flex items-center justify-center gap-3 px-6 py-4 rounded-xl font-semibold text-sm transition-all duration-200',
            'bg-white text-blue-700',
            'border-2 border-blue-500 shadow-lg shadow-blue-500/20',
            'hover:bg-blue-50 hover:shadow-xl hover:shadow-blue-500/30 hover:scale-[1.02] hover:-translate-y-0.5',
            'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 disabled:hover:translate-y-0'
          )}
        >
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-blue-100">
            <Search className="w-4 h-4" />
          </div>
          <span>Preview Search</span>
        </button>

        <a
          href="/review"
          className={cn(
            'group relative flex items-center justify-center gap-3 px-6 py-4 rounded-xl font-semibold text-sm transition-all duration-200',
            'bg-white text-purple-700',
            'border-2 border-purple-500 shadow-lg shadow-purple-500/20',
            'hover:bg-purple-50 hover:shadow-xl hover:shadow-purple-500/30 hover:scale-[1.02] hover:-translate-y-0.5'
          )}
        >
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-purple-100">
            <RefreshCw className="w-4 h-4" />
          </div>
          <span>Review Posts</span>
        </a>
      </div>

      {generationMessage && (
        <p className="mt-4 text-sm text-green-700">{generationMessage}</p>
      )}
      {generationError && (
        <p role="alert" className="mt-4 text-sm text-red-700">{generationError}</p>
      )}
    </div>
  )
}



