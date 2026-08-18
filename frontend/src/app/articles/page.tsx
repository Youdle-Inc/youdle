'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Filter, RefreshCw, ShoppingCart, AlertOctagon } from 'lucide-react'
import { api, SearchResponse } from '@/lib/api'
import { ArticleCard } from '@/components/ArticleCard'
import { cn } from '@/lib/utils'

export default function ArticlesPage() {
  const [batchSize, setBatchSize] = useState(10)
  const [daysBack, setDaysBack] = useState(7)
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const [searchTrigger, setSearchTrigger] = useState(0)

  const { data, isLoading, error, refetch } = useQuery<SearchResponse>({
    queryKey: ['searchPreview', batchSize, daysBack, searchTrigger],
    queryFn: () => api.previewSearch({ batch_size: batchSize, days_back: daysBack }),
    enabled: searchTrigger > 0,
  })

  const handleSearch = () => {
    setSearchTrigger(prev => prev + 1)
  }

  // Filter articles by category
  const filteredItems = data?.items?.filter(item => 
    !categoryFilter || item.category === categoryFilter
  ) || []

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-stone-900">
          Article Search
        </h1>
        <p className="mt-2 text-stone-500">
          Preview article search results and see what content would be selected for blog generation.
        </p>
      </div>

      {/* Search Controls */}
      <div className="rounded-2xl bg-white border border-stone-200 p-6">
        <h3 className="text-lg font-semibold text-stone-900 mb-4">
          Search Parameters
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-midnight-700 mb-2">
              Batch Size
            </label>
            <input
              type="number"
              min={1}
              max={50}
              value={batchSize}
              onChange={(e) => setBatchSize(parseInt(e.target.value) || 10)}
              className="w-full px-3 py-2 rounded-lg border border-midnight-300 bg-white text-stone-900 focus:ring-2 focus:ring-youdle-500 focus:border-transparent"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-midnight-700 mb-2">
              Days Back
            </label>
            <input
              type="number"
              min={1}
              max={7}
              value={daysBack}
              onChange={(e) => setDaysBack(parseInt(e.target.value) || 7)}
              className="w-full px-3 py-2 rounded-lg border border-midnight-300 bg-white text-stone-900 focus:ring-2 focus:ring-youdle-500 focus:border-transparent"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-midnight-700 mb-2">
              Category Filter
            </label>
            <select
              value={categoryFilter || ''}
              onChange={(e) => setCategoryFilter(e.target.value || null)}
              className="w-full px-3 py-2 rounded-lg border border-midnight-300 bg-white text-stone-900 focus:ring-2 focus:ring-youdle-500 focus:border-transparent"
            >
              <option value="">All Categories</option>
              <option value="SHOPPERS">Shoppers Only</option>
              <option value="RECALL">Recall Only</option>
            </select>
          </div>
          
          <div className="flex items-end">
            <button
              onClick={handleSearch}
              disabled={isLoading}
              className={cn(
                'w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg font-medium transition-all',
                'bg-gradient-to-r from-youdle-500 to-youdle-600 text-white',
                'hover:from-youdle-600 hover:to-youdle-700 hover:shadow-lg hover:shadow-youdle-500/25',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              {isLoading ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Search className="w-4 h-4" />
              )}
              Search
            </button>
          </div>
        </div>
      </div>

      {/* Results Summary */}
      {data && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="flex items-center gap-3 p-4 rounded-xl bg-white border border-stone-200">
            <div className="w-10 h-10 rounded-lg bg-youdle-100 dark:bg-youdle-900/30 flex items-center justify-center">
              <Filter className="w-5 h-5 text-youdle-600 dark:text-youdle-400" />
            </div>
            <div>
              <p className="text-sm text-stone-500">Processed</p>
              <p className="text-xl font-bold text-stone-900">{data.processed_count}</p>
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-4 rounded-xl bg-white border border-stone-200">
            <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
              <Search className="w-5 h-5 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-sm text-stone-500">Total Found</p>
              <p className="text-xl font-bold text-stone-900">{data.total_ranked_count}</p>
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-4 rounded-xl bg-white border border-stone-200">
            <div className="w-10 h-10 rounded-lg bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
              <ShoppingCart className="w-5 h-5 text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-sm text-stone-500">Shoppers</p>
              <p className="text-xl font-bold text-stone-900">{data.shoppers_count}</p>
            </div>
          </div>
          
          <div className="flex items-center gap-3 p-4 rounded-xl bg-white border border-stone-200">
            <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
              <AlertOctagon className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <p className="text-sm text-stone-500">Recall</p>
              <p className="text-xl font-bold text-stone-900">{data.recall_count}</p>
            </div>
          </div>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
          <p className="text-red-800 dark:text-red-200">
            Error: {error instanceof Error ? error.message : 'Failed to search articles'}
          </p>
        </div>
      )}

      {/* Empty State */}
      {!data && !isLoading && searchTrigger === 0 && (
        <div className="text-center py-16 rounded-2xl bg-white border border-stone-200">
          <Search className="w-12 h-12 text-stone-600 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-stone-900 mb-2">
            Ready to Search
          </h3>
          <p className="text-stone-500 max-w-md mx-auto">
            Configure your search parameters above and click "Search" to preview the articles that would be selected for blog generation.
          </p>
        </div>
      )}

      {/* Results Grid */}
      {filteredItems.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold text-stone-900 mb-4">
            Search Results ({filteredItems.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 stagger-children">
            {filteredItems.map((article, index) => (
              <ArticleCard key={`${article.link}-${index}`} article={article} />
            ))}
          </div>
        </div>
      )}

      {/* Recall Items Section */}
      {data?.recall_items && data.recall_items.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold text-stone-900 mb-4 flex items-center gap-2">
            <AlertOctagon className="w-5 h-5 text-amber-500" />
            Recent Recall Alerts ({data.recall_items.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.recall_items.slice(0, 6).map((article, index) => (
              <ArticleCard key={`recall-${article.link}-${index}`} article={article} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}



