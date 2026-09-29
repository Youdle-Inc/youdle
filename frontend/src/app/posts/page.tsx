'use client'

import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, Filter, RefreshCw, ShoppingCart, AlertOctagon, Trash2, Globe, Search } from 'lucide-react'
import { api, type BlogPostUpdate } from '@/lib/api'
import { BlogPostPreview } from '@/components/BlogPostPreview'
import { cn, getStatusColor } from '@/lib/utils'

export default function PostsPage() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const [showSyncIssuesOnly, setShowSyncIssuesOnly] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null)
  const [lastSyncTime, setLastSyncTime] = useState<Date | null>(null)
  const [isAutoSyncing, setIsAutoSyncing] = useState(true)

  const { data: posts, isLoading, error } = useQuery({
    queryKey: ['posts', statusFilter, categoryFilter],
    queryFn: () => api.getPosts({ 
      status: statusFilter || undefined, 
      category: categoryFilter || undefined,
      limit: 50 
    }),
  })

  const updateStatusMutation = useMutation({
    mutationFn: ({ postId, status }: { postId: string; status: string }) =>
      api.updatePostStatus(postId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
    },
  })

  const deletePostMutation = useMutation({
    mutationFn: (postId: string) => api.deletePost(postId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
    },
  })

  const updatePostMutation = useMutation({
    mutationFn: ({ postId, updates }: { postId: string; updates: BlogPostUpdate }) =>
      api.updatePost(postId, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
    },
  })

  const publishToBloggerMutation = useMutation({
    mutationFn: (postId: string) => api.publishToBlogger(postId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
    },
  })

  const unpublishFromBloggerMutation = useMutation({
    mutationFn: (postId: string) => api.unpublishFromBlogger(postId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
    },
  })

  const deleteAllPostsMutation = useMutation({
    mutationFn: async () => {
      if (!posts || posts.length === 0) return
      await Promise.all(posts.map(post => api.deletePost(post.id)))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
    },
  })

  const syncWithBloggerMutation = useMutation({
    mutationFn: () => api.syncWithBlogger(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
      setLastSyncTime(new Date())

      // Show success toast with summary (only if there were changes)
      if (data.synced_count > 0 || data.issues_fixed > 0 || data.imported_count > 0 || data.pushed_count > 0) {
        const parts = []
        if (data.synced_count > 0) parts.push(`Synced ${data.synced_count} posts`)
        if (data.issues_fixed > 0) parts.push(`fixed ${data.issues_fixed} issues`)
        if (data.imported_count > 0) parts.push(`imported ${data.imported_count} from Blogger`)
        if (data.pushed_count > 0) parts.push(`pushed ${data.pushed_count} to Blogger`)
        const summary = parts.join(', ')

        setToast({ message: summary, type: 'success' })
        setTimeout(() => setToast(null), 5000)
      }
    },
    onError: (error) => {
      setToast({
        message: error instanceof Error ? error.message : 'Failed to sync with Blogger',
        type: 'error'
      })
      setTimeout(() => setToast(null), 5000)
    }
  })

  // Auto-sync with Blogger on page load - temporarily disabled
  // Dashboard is now the source of truth; drafts auto-create on Blogger, publish/delete still sync
  /*
  const hasAutoSynced = useRef(false)
  useEffect(() => {
    if (!hasAutoSynced.current) {
      hasAutoSynced.current = true
      api.syncWithBloggerLight()
        .then((data) => {
          queryClient.invalidateQueries({ queryKey: ['posts'] })
          setLastSyncTime(new Date())
          if (data.synced_count > 0) {
            setToast({ message: `Synced ${data.synced_count} posts from Blogger`, type: 'success' })
            setTimeout(() => setToast(null), 5000)
          }
        })
        .catch(() => {
          // Silent fail for auto-sync
        })
        .finally(() => {
          setIsAutoSyncing(false)
        })
    }
  }, [queryClient]) // eslint-disable-line react-hooks/exhaustive-deps
  */

  const handleStatusChange = (postId: string, status: string) => {
    updateStatusMutation.mutate({ postId, status })
  }

  const handleDelete = (postId: string) => {
    if (confirm('Are you sure you want to delete this post?')) {
      deletePostMutation.mutate(postId)
    }
  }

  const handleEdit = async (postId: string, updates: BlogPostUpdate) => {
    await updatePostMutation.mutateAsync({ postId, updates })
  }

  const handlePublish = async (postId: string) => {
    await publishToBloggerMutation.mutateAsync(postId)
  }

  const handleUnpublish = async (postId: string) => {
    await unpublishFromBloggerMutation.mutateAsync(postId)
  }

  const handleDeleteAll = () => {
    if (confirm(`Are you sure you want to delete all ${posts?.length || 0} posts? This action cannot be undone.`)) {
      deleteAllPostsMutation.mutate()
    }
  }

  // Count posts by status
  const statusCounts = posts?.reduce((acc, post) => {
    acc[post.status] = (acc[post.status] || 0) + 1
    return acc
  }, {} as Record<string, number>) || {}

  // Filter posts with sync issues and search query
  const filteredPosts = posts?.filter(post => {
    // Filter by sync issues
    if (showSyncIssuesOnly && !(post.status === 'published' && !post.blogger_url)) {
      return false
    }
    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      return post.title.toLowerCase().includes(query)
    }
    return true
  })

  const syncIssueCount = posts?.filter(p => p.status === 'published' && !p.blogger_url).length || 0

  return (
    <div className="space-y-5 sm:space-y-8 animate-fade-in">
      {/* Toast Notification */}
      {toast && (
        <div className={cn(
          'fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-lg border animate-fade-in',
          toast.type === 'success'
            ? 'bg-green-50 border-green-200 text-green-800'
            : 'bg-red-50 border-red-200 text-red-800'
        )}>
          <p className="font-medium">{toast.message}</p>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-display font-light text-stone-900 tracking-tight">
            Blog Posts
          </h1>
          <p className="mt-2 max-w-3xl text-sm sm:text-base md:text-lg text-stone-500 font-light">
            View and manage generated blog posts. Update status and copy HTML for publishing.
          </p>
          {lastSyncTime && (
            <p className="mt-1 text-sm text-stone-400">
              Last synced: {lastSyncTime.toLocaleTimeString()}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Sync with Blogger button - temporarily disabled
          <button
            onClick={() => syncWithBloggerMutation.mutate()}
            disabled={syncWithBloggerMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 rounded-xl font-medium text-sm transition-all bg-blue-100 text-blue-700 hover:bg-blue-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {syncWithBloggerMutation.isPending ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Globe className="w-4 h-4" />
            )}
            {syncWithBloggerMutation.isPending ? 'Syncing...' : 'Sync with Blogger'}
          </button>
          */}
          {/* Delete All button - temporarily disabled
          {posts && posts.length > 0 && (
            <button
              onClick={handleDeleteAll}
              disabled={deleteAllPostsMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 rounded-xl font-medium text-sm transition-all bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {deleteAllPostsMutation.isPending ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
              Delete All
            </button>
          )}
          */}
        </div>
      </div>

      {/* Filters */}
      <div className="rounded-2xl bg-stone-50/50 border border-stone-200 p-4 sm:p-6 md:p-8">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_auto_auto_auto] xl:items-end">
          {/* Search */}
          <div className="min-w-0 sm:col-span-2 xl:col-span-1 xl:max-w-md">
            <label className="block text-xs font-medium text-stone-500 mb-2">
              Search
            </label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-400" />
              <input
                type="text"
                placeholder="Search posts by title..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 rounded-lg border border-stone-200 bg-white text-sm placeholder-stone-400 focus:outline-none focus:ring-2 focus:ring-accent-500 focus:border-transparent"
              />
            </div>
          </div>

          {/* Status Filter */}
          <div>
            <label className="block text-xs font-medium text-stone-500 mb-2">
              Status
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => setStatusFilter(null)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-sm font-medium transition-all',
                  !statusFilter
                    ? 'bg-accent-100 text-accent-700'
                    : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
                )}
              >
                All
              </button>
              {['draft', 'reviewed', 'published'].map(status => (
                <button
                  key={status}
                  onClick={() => setStatusFilter(status)}
                  className={cn(
                    'px-3 py-1.5 rounded-lg text-sm font-medium transition-all flex items-center gap-1',
                    statusFilter === status
                      ? getStatusColor(status)
                      : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
                  )}
                >
                  {status.charAt(0).toUpperCase() + status.slice(1)}
                  {statusCounts[status] && (
                    <span className="text-xs opacity-75">({statusCounts[status]})</span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Category Filter */}
          <div>
            <label className="block text-xs font-medium text-stone-500 mb-2">
              Category
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => setCategoryFilter(null)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-sm font-medium transition-all',
                  !categoryFilter
                    ? 'bg-accent-100 text-accent-700'
                    : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
                )}
              >
                All
              </button>
              <button
                onClick={() => setCategoryFilter('SHOPPERS')}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-sm font-medium transition-all flex items-center gap-1',
                  categoryFilter === 'SHOPPERS'
                    ? 'bg-green-100 text-green-700'
                    : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
                )}
              >
                <ShoppingCart className="w-4 h-4" />
                Shoppers
              </button>
              <button
                onClick={() => setCategoryFilter('RECALL')}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-sm font-medium transition-all flex items-center gap-1',
                  categoryFilter === 'RECALL'
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
                )}
              >
                <AlertOctagon className="w-4 h-4" />
                Recall
              </button>
            </div>
          </div>

          {/* Sync Issues Filter */}
          <div>
            <label className="block text-xs font-medium text-stone-500 mb-2">
              Sync Status
            </label>
            <button
              onClick={() => setShowSyncIssuesOnly(!showSyncIssuesOnly)}
              className={cn(
                'px-3 py-1.5 rounded-lg text-sm font-medium transition-all flex items-center gap-1',
                showSyncIssuesOnly
                  ? 'bg-amber-100 text-amber-700'
                  : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
              )}
            >
              Sync Issues Only
              {syncIssueCount > 0 && (
                <span className="text-xs opacity-75">({syncIssueCount})</span>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <RefreshCw className="w-8 h-8 text-accent-500 animate-spin" />
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200">
          <p className="text-red-800">
            Error: {error instanceof Error ? error.message : 'Failed to load posts'}
          </p>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && filteredPosts?.length === 0 && (
        <div className="text-center py-16 rounded-2xl bg-stone-50/50 border border-stone-200">
          <FileText className="w-12 h-12 text-stone-400 mx-auto mb-4" />
          <h3 className="text-xl font-display font-semibold text-stone-900 mb-2">
            No Posts Found
          </h3>
          <p className="text-stone-500 max-w-md mx-auto">
            {showSyncIssuesOnly
              ? 'No posts with sync issues found.'
              : 'No blog posts match your current filters. Try adjusting the filters or generate new posts.'}
          </p>
        </div>
      )}

      {/* Posts Grid */}
      {filteredPosts && filteredPosts.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:gap-6 xl:grid-cols-2 stagger-children">
          {filteredPosts.map((post) => (
            <BlogPostPreview
              key={post.id}
              post={post}
              onStatusChange={handleStatusChange}
              onDelete={handleDelete}
              onEdit={handleEdit}
              onPublish={handlePublish}
              onUnpublish={handleUnpublish}
            />
          ))}
        </div>
      )}
    </div>
  )
}



