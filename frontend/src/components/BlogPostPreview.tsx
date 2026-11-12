'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ExternalLink, Eye, Code, Copy, Check, Trash2, Edit2, Loader2, Globe } from 'lucide-react'
import { cn, formatDate, getStatusColor, getCategoryColor, truncate, stripHtml } from '@/lib/utils'
import { safeArticlePreviewHtml } from '@/lib/articleImages'
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

// Reuse the post's existing photo. Older posts may have their image stored
// only in the article HTML, so use that source when image_url is absent.
// Never fabricate a fallback image or treat placeholders as a real photo.
function getCardImageUrl(post: BlogPost): string | null {
  const savedImage = post.image_url?.trim()
  if (savedImage && /^https:\/\//i.test(savedImage)) return savedImage

  const html = safeArticlePreviewHtml(post.html_content, post.image_url)
  const imageTag = /<img\b[^>]*\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi
  let match: RegExpExecArray | null
  while ((match = imageTag.exec(html)) !== null) {
    const url = (match[1] || match[2] || match[3] || '').trim()
    if (/^https:\/\//i.test(url)) return url
  }
  return null
}

export function BlogPostPreview({ post, onStatusChange, onDelete, onEdit, onPublish, onUnpublish, className }: BlogPostPreviewProps) {
  const [viewMode, setViewMode] = useState<'preview' | 'code'>('preview')
  const [isPreviewOpen, setIsPreviewOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [isPublishing, setIsPublishing] = useState(false)
  const [isUnpublishing, setIsUnpublishing] = useState(false)
  const [publishError, setPublishError] = useState<string | null>(null)
  const [failedCardImage, setFailedCardImage] = useState<string | null>(null)
  const cardImageUrl = getCardImageUrl(post)
  const previewButtonRef = useRef<HTMLButtonElement>(null)
  const previewCloseRef = useRef<HTMLButtonElement>(null)

  // The pop-out is portaled outside animated, overflow-hidden post cards.
  useEffect(() => {
    if (!isPreviewOpen) return
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsPreviewOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    previewCloseRef.current?.focus()
    return () => {
      document.body.style.overflow = oldOverflow
      document.removeEventListener('keydown', onKeyDown)
      previewButtonRef.current?.focus()
    }
  }, [isPreviewOpen])

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

      {/* Restore the saved article photograph on the resting card. The full
          article still opens only through the separate Preview reader. */}
      {cardImageUrl && failedCardImage !== cardImageUrl && (
        <div className="border-b border-stone-200 bg-stone-50">
          <img
            src={cardImageUrl}
            alt={post.title}
            loading="lazy"
            className="aspect-video w-full object-cover"
            onError={() => setFailedCardImage(cardImageUrl)}
          />
        </div>
      )}

      {/* View Toggle */}
      <div className="flex flex-col gap-2 px-4 py-2 bg-stone-50 border-b border-stone-200 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-1">
          <button
            ref={previewButtonRef}
            onClick={() => { setViewMode('preview'); setIsPreviewOpen(true) }}
            className={cn(
              'flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
              isPreviewOpen
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

      {/* HTML remains available in-card; Preview opens a separate reader view. */}
      {viewMode === 'code' && (
        <div className="max-h-[70vh] overflow-y-auto p-4 sm:max-h-96">
          <pre className="whitespace-pre-wrap break-words rounded-lg bg-stone-50 p-4 font-mono text-xs text-stone-700">
            {post.html_content}
          </pre>
        </div>
      )}

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


      {/* Full web-style article reader, outside card clipping and animations. */}
      {isPreviewOpen && typeof document !== 'undefined' && createPortal(
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-stone-950/70 p-0 sm:p-5"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setIsPreviewOpen(false)
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby={'article-preview-title-' + post.id}
            className="flex h-[100dvh] w-full max-w-5xl flex-col overflow-hidden bg-white shadow-2xl sm:h-[94dvh] sm:rounded-2xl"
          >
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-stone-200 bg-white px-4 py-3 sm:px-6">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-wider text-green-700">
                  Article preview · {post.blogger_url ? 'Published' : 'Not published'}
                </p>
                <p id={'article-preview-title-' + post.id} className="truncate text-sm font-semibold text-stone-900">
                  {post.title}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {post.blogger_url && (
                  <a
                    href={post.blogger_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hidden rounded-lg px-3 py-2 text-sm font-medium text-green-700 hover:bg-green-50 sm:inline-flex"
                  >
                    View published page
                  </a>
                )}
                <button
                  ref={previewCloseRef}
                  type="button"
                  onClick={() => setIsPreviewOpen(false)}
                  className="rounded-lg bg-stone-100 px-4 py-2 text-sm font-semibold text-stone-900 hover:bg-stone-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-700"
                >
                  Close
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-[#f6f7f4] px-3 py-5 sm:px-8 sm:py-8">
              <article className="mx-auto w-full max-w-[780px] bg-white px-5 py-7 shadow-sm sm:rounded-xl sm:px-12 sm:py-12">
                <header className="mb-6 border-b border-stone-200 pb-5">
                  <p className="text-xs font-bold uppercase tracking-[0.16em] text-green-800">Youdle Grocery News</p>
                  <p className="mt-2 text-sm text-stone-500">
                    {formatDate(post.blogger_published_at || post.created_at)}
                  </p>
                </header>
                {!/<h[12]\b/i.test(post.html_content) && (
                  <h1 className="mb-6 text-3xl font-bold leading-tight text-stone-900">{post.title}</h1>
                )}
                <div
                  className="max-w-none break-words text-[17px] leading-[1.8] text-stone-800 [&_a]:break-words [&_a]:font-semibold [&_a]:text-green-800 [&_a]:underline [&_a]:underline-offset-2 [&_blockquote]:my-5 [&_blockquote]:border-l-4 [&_blockquote]:border-green-700 [&_blockquote]:pl-4 [&_h1]:my-6 [&_h1]:text-3xl [&_h1]:font-bold [&_h1]:leading-tight [&_h2]:my-6 [&_h2]:text-[28px] [&_h2]:font-bold [&_h2]:leading-tight [&_h3]:my-5 [&_h3]:text-xl [&_h3]:font-bold [&_img]:my-6 [&_img]:h-auto [&_img]:max-w-full [&_img]:rounded-lg [&_li]:mb-2 [&_ol]:my-5 [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:mb-5 [&_strong]:font-bold [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto [&_ul]:my-5 [&_ul]:list-disc [&_ul]:pl-6"
                  dangerouslySetInnerHTML={{ __html: safeArticlePreviewHtml(post.html_content, post.image_url) }}
                />
              </article>
            </div>
          </section>
        </div>,
        document.body
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



