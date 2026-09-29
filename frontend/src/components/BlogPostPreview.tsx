'use client'

import { useState } from 'react'
import { ExternalLink, Eye, Code, Copy, Check, Trash2, Edit2, Loader2, Globe } from 'lucide-react'
import { cn, formatDate, getStatusColor, getCategoryColor, truncate, stripHtml } from '@/lib/utils'
import { EditBlogPostModal } from './EditBlogPostModal'
import type { BlogPostUpdate } from '@/lib/api'

interface BlogPost {
  id: string
  title: string
  html_content: string
  image_url: string | null
  category: string
  status: string
  article_url: string
  created_at: string
  blogger_post_id?: string | null
  blogger_url?: string | null
  blogger_published_at?: string | null
}

interface BlogPostPreviewProps {
  post: BlogPost
  onStatusChange?: (postId: string, status: string) => void
  onDelete?: (postId: string) => void
  onEdit?: (postId: string, updates: BlogPostUpdate) => Promise<void>
  onPublish?: (postId: string) => Promise<void>
  onUnpublish?: (postId: string) => Promise<void>
  className?: string
}

// Helper function to determine sync status
function getSyncStatus(post: BlogPost): { status: 'synced' | 'issue' | 'not_published', label: string, color: string } {
  const hasPublishedStatus = post.status === 'published'
  const hasBloggerUrl = !!post.blogger_url
  const hasBloggerId = !!post.blogger_post_id

  if (hasBloggerUrl || (hasPublishedStatus && hasBloggerId)) {
    return {
      status: 'synced',
      label: 'Synced',
      color: 'bg-emerald-100 text-emerald-700 border-emerald-200'
    }
  }

  if (hasPublishedStatus && !hasBloggerId) {
    return {
      status: 'issue',
      label: 'Sync Issue',
      color: 'bg-amber-100 text-amber-700 border-amber-200'
    }
  }

  return {
    status: 'not_published',
    label: 'Not Published',
    color: 'bg-stone-100 text-stone-600 border-stone-200'
  }
}

export function BlogPostPreview({ post, onStatusChange, onDelete, onEdit, onPublish, onUnpublish, className }: BlogPostPreviewProps) {
  const [viewMode, setViewMode] = useState<'preview' | 'code'>('preview')
  const [copied, setCopied] = useState(false)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [isPublishing, setIsPublishing] = useState(false)
  const [isUnpublishing, setIsUnpublishing] = useState(false)
  const [publishError, setPublishError] = useState<string | null>(null)

  const syncStatus = getSyncStatus(post)

  const handlePublish = async () => {
    if (!onPublish) return
    setIsPublishing(true)
    setPublishError(null)
    try {
      await onPublish(post.id)
    } catch (error) {
      setPublishError(error instanceof Error ? error.message : 'Failed to publish')
    } finally {
      setIsPublishing(false)
    }
  }

  const handleUnpublish = async () => {
    if (!onUnpublish) return
    setIsUnpublishing(true)
    setPublishError(null)
    try {
      await onUnpublish(post.id)
    } catch (error) {
      setPublishError(error instanceof Error ? error.message : 'Failed to unpublish')
    } finally {
      setIsUnpublishing(false)
    }
  }

  const isPublishedToBlogger = !!post.blogger_url

  const handleCopyHtml = async () => {
    await navigator.clipboard.writeText(post.html_content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className={cn(
      'rounded-2xl bg-white border border-stone-200 overflow-hidden',
      className
    )}>
      {/* Header */}
      <div className="p-4 border-b border-stone-200">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between mb-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn(
              'inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium',
              getCategoryColor(post.category)
            )}>
              {post.category}
            </span>
            <span className={cn(
              'inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium',
              getStatusColor(post.status)
            )}>
              {post.status}
            </span>
            <span className={cn(
              'inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium border',
              syncStatus.color
            )}>
              {syncStatus.label}
            </span>
          </div>

          <span className="text-xs text-stone-500">
            {formatDate(post.status === 'published' && post.blogger_published_at
              ? post.blogger_published_at
              : post.created_at)}
          </span>
        </div>

        <h3 className="text-lg font-semibold text-stone-900 line-clamp-2">
          {post.title}
        </h3>

        <p className="mt-1 text-sm text-stone-500 line-clamp-2">
          {truncate(stripHtml(post.html_content), 150)}
        </p>
      </div>

      {/* View Toggle */}
      <div className="flex flex-col gap-2 px-4 py-2 bg-stone-50 border-b border-stone-200 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1">
          <button
            onClick={() => setViewMode('preview')}
            className={cn(
              'flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
              viewMode === 'preview'
                ? 'bg-white text-stone-900 shadow-sm'
                : 'text-stone-500 hover:text-stone-700'
            )}
          >
            <Eye className="w-3 h-3" />
            Preview
          </button>
          <button
            onClick={() => setViewMode('code')}
            className={cn(
              'flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
              viewMode === 'code'
                ? 'bg-white text-stone-900 shadow-sm'
                : 'text-stone-500 hover:text-stone-700'
            )}
          >
            <Code className="w-3 h-3" />
            HTML
          </button>
          {onEdit && (
            <button
              onClick={() => setIsEditModalOpen(true)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all text-stone-500 hover:text-stone-700 hover:bg-white"
            >
              <Edit2 className="w-3 h-3" />
              Edit
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleCopyHtml}
            className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-stone-500 hover:text-stone-700 hover:bg-stone-100 transition-all"
          >
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {copied ? 'Copied!' : 'Copy HTML'}
          </button>

          {post.article_url && (
            <a
              href={post.article_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-accent-600 hover:text-accent-700 hover:bg-accent-50 transition-all"
            >
              <ExternalLink className="w-3 h-3" />
              Source
            </a>
          )}
          {post.blogger_url && (
            <a
              href={post.blogger_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-green-600 hover:text-green-700 hover:bg-green-50 transition-all"
            >
              <Globe className="w-3 h-3" />
              View on Blogger
            </a>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="p-4 max-h-[70vh] overflow-y-auto sm:max-h-96">
        {viewMode === 'preview' ? (
          <div
            className="prose prose-sm max-w-none break-words [&_img]:max-w-full [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto"
            dangerouslySetInnerHTML={{ __html: post.html_content }}
          />
        ) : (
          <pre className="text-xs font-mono text-stone-700 whitespace-pre-wrap break-words bg-stone-50 rounded-lg p-4">
            {post.html_content}
          </pre>
        )}
      </div>

      {/* Actions */}
      {(onStatusChange || onPublish) && (
        <div className="flex flex-col gap-2 p-4 border-t border-stone-200 bg-stone-50">
          {publishError && (
            <div className="px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700">
              {publishError}
            </div>
          )}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              {onStatusChange && post.status !== 'published' && (
                <>
                  <button
                    onClick={() => onStatusChange(post.id, 'draft')}
                    disabled={post.status === 'draft' || isPublishing}
                    className={cn(
                      'px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                      post.status === 'draft'
                        ? 'bg-stone-200 text-stone-500 cursor-not-allowed'
                        : 'bg-stone-100 text-stone-700 hover:bg-stone-200'
                    )}
                  >
                    Draft
                  </button>
                  <button
                    onClick={() => onStatusChange(post.id, 'reviewed')}
                    disabled={post.status === 'reviewed' || isPublishing}
                    className={cn(
                      'px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                      post.status === 'reviewed'
                        ? 'bg-purple-200 text-purple-500 cursor-not-allowed'
                        : 'bg-purple-100 text-purple-700 hover:bg-purple-200'
                    )}
                  >
                    Mark Reviewed
                  </button>
                </>
              )}
              {onUnpublish && post.status === 'published' && (
                <button
                  onClick={handleUnpublish}
                  disabled={isUnpublishing}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                    isUnpublishing
                      ? "bg-amber-100 text-amber-700 cursor-wait"
                      : "bg-amber-100 text-amber-700 hover:bg-amber-200"
                  )}
                >
                  {isUnpublishing ? (
                    <>
                      <Loader2 className="w-3 h-3 animate-spin" />
                      Unpublishing...
                    </>
                  ) : (
                    'Unpublish'
                  )}
                </button>
              )}
              {onPublish && !isPublishedToBlogger && (
                <button
                  onClick={handlePublish}
                  disabled={isPublishing}
                  className={cn(
                    'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                    isPublishing
                      ? 'bg-green-100 text-green-700 cursor-wait'
                      : 'bg-green-100 text-green-700 hover:bg-green-200'
                  )}
                >
                  {isPublishing ? (
                    <>
                      <Loader2 className="w-3 h-3 animate-spin" />
                      Publishing...
                    </>
                  ) : (
                    'Publish to Blogger'
                  )}
                </button>
              )}
            </div>
            {onDelete && (
              <button
                onClick={() => onDelete(post.id)}
                disabled={isPublishing}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all bg-red-100 text-red-700 hover:bg-red-200"
              >
                <Trash2 className="w-3 h-3" />
                Delete
              </button>
            )}
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {onEdit && (
        <EditBlogPostModal
          isOpen={isEditModalOpen}
          post={post}
          onClose={() => setIsEditModalOpen(false)}
          onSave={onEdit}
        />
      )}
    </div>
  )
}



