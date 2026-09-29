'use client'

import { useState, useEffect, useCallback } from 'react'
import { Save, X, AlertCircle, Globe, Eye, Code, Image as ImageIcon, Loader2, Check } from 'lucide-react'
import { Modal } from './Modal'
import { RichTextEditor } from './RichTextEditor'
import { MediaPickerModal } from './MediaPickerModal'
import { useAutosave } from '@/hooks/useAutosave'
import type { BlogPostUpdate, MediaItem } from '@/lib/api'

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
}

interface EditBlogPostModalProps {
  isOpen: boolean
  post: BlogPost
  onClose: () => void
  onSave: (postId: string, updates: BlogPostUpdate) => Promise<void>
}

export function EditBlogPostModal({ isOpen, post, onClose, onSave }: EditBlogPostModalProps) {
  const [formData, setFormData] = useState<BlogPostUpdate>({
    title: post.title,
    html_content: post.html_content,
    image_url: post.image_url || '',
    category: post.category as 'SHOPPERS' | 'RECALL',
  })
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editorMode, setEditorMode] = useState<'visual' | 'html'>('visual')
  const [showMediaPicker, setShowMediaPicker] = useState(false)

  // Autosave callback - saves without closing modal
  const handleAutosave = useCallback(async (data: BlogPostUpdate) => {
    await onSave(post.id, data)
  }, [onSave, post.id])

  // Validation for autosave
  const validateFormData = useCallback((data: BlogPostUpdate): string | null => {
    if (!data.title?.trim()) return 'Title is required'
    if (!data.html_content?.trim()) return 'Content is required'
    if (!data.category) return 'Category is required'
    return null
  }, [])

  // Autosave hook
  const { status: autosaveStatus, error: autosaveError } = useAutosave({
    data: formData,
    onSave: handleAutosave,
    validate: validateFormData,
    delay: 2000,
    enabled: isOpen,
    savedDisplayDuration: 2000,
  })

  // Reset form when modal opens with new post data
  useEffect(() => {
    if (isOpen) {
      setFormData({
        title: post.title,
        html_content: post.html_content,
        image_url: post.image_url || '',
        category: post.category as 'SHOPPERS' | 'RECALL',
      })
      setError(null)
      setEditorMode('visual')
    }
  }, [isOpen, post])

  const handleSave = async () => {
    // Validate
    if (!formData.title?.trim()) {
      setError('Title is required')
      return
    }

    if (!formData.html_content?.trim()) {
      setError('Content is required')
      return
    }

    if (!formData.category) {
      setError('Category is required')
      return
    }

    setIsSaving(true)
    setError(null)

    try {
      await onSave(post.id, formData)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save changes')
    } finally {
      setIsSaving(false)
    }
  }

  const handleCancel = () => {
    if (!isSaving) {
      onClose()
    }
  }

  const handleMediaSelect = (media: MediaItem) => {
    setFormData({ ...formData, image_url: media.public_url })
    setShowMediaPicker(false)
  }

  const isPublishedToBlogger = !!post.blogger_post_id

  // Render autosave status indicator
  const renderAutosaveStatus = () => {
    switch (autosaveStatus) {
      case 'saving':
        return (
          <div className="flex items-center gap-1.5 text-xs text-stone-500">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            <span>Saving...</span>
          </div>
        )
      case 'saved':
        return (
          <div className="flex items-center gap-1.5 text-xs text-green-600">
            <Check className="w-3.5 h-3.5" />
            <span>Saved</span>
          </div>
        )
      case 'error':
        return (
          <div className="flex items-center gap-1.5 text-xs text-red-600">
            <AlertCircle className="w-3.5 h-3.5" />
            <span>{autosaveError || 'Save failed'}</span>
          </div>
        )
      default:
        return null
    }
  }

  const footerContent = (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      {/* Left side: Blogger sync indicator and autosave status */}
      <div className="flex flex-wrap items-center gap-3">
        {isPublishedToBlogger && (
          <div className="flex items-center gap-1.5 text-xs text-blue-600">
            <Globe className="w-3.5 h-3.5" />
            <span>Changes will sync to Blogger</span>
          </div>
        )}
        {renderAutosaveStatus()}
      </div>

      <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
        <button
          onClick={handleCancel}
          disabled={isSaving}
          className="flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-medium transition-all bg-stone-100 text-stone-700 hover:bg-stone-200 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <X className="w-4 h-4" />
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={isSaving || !formData.title?.trim() || !formData.html_content?.trim()}
          className="flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-medium transition-all bg-youdle-500 text-white hover:bg-youdle-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Save className="w-4 h-4" />
          {isSaving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </div>
  )

  return (
    <Modal isOpen={isOpen} onClose={handleCancel} title="Edit Post" footer={footerContent}>
      <div className="p-4 space-y-4 sm:p-6">
        {/* Error Message */}
        {error && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Title Field */}
        <div>
          <label htmlFor="title" className="block text-xs font-medium text-stone-700 mb-1">
            Title
          </label>
          <input
            id="title"
            type="text"
            value={formData.title || ''}
            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
            disabled={isSaving}
            className="w-full px-3 py-2 rounded-lg border border-stone-300 text-sm focus:ring-2 focus:ring-accent-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
            placeholder="Enter post title..."
          />
        </div>

        {/* Category Field */}
        <div>
          <label htmlFor="category" className="block text-xs font-medium text-stone-700 mb-1">
            Category
          </label>
          <select
            id="category"
            value={formData.category}
            onChange={(e) => setFormData({ ...formData, category: e.target.value as 'SHOPPERS' | 'RECALL' })}
            disabled={isSaving}
            className="w-full px-3 py-2 rounded-lg border border-stone-300 text-sm focus:ring-2 focus:ring-accent-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <option value="SHOPPERS">SHOPPERS</option>
            <option value="RECALL">RECALL</option>
          </select>
        </div>

        {/* Image URL Field */}
        <div>
          <label htmlFor="image_url" className="block text-xs font-medium text-stone-700 mb-1">
            Image URL (optional)
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="image_url"
              type="url"
              value={formData.image_url || ''}
              onChange={(e) => setFormData({ ...formData, image_url: e.target.value })}
              placeholder="https://example.com/image.jpg"
              disabled={isSaving}
              className="min-w-0 flex-1 px-3 py-2 rounded-lg border border-stone-300 text-sm focus:ring-2 focus:ring-accent-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <button
              type="button"
              onClick={() => setShowMediaPicker(true)}
              disabled={isSaving}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-stone-300 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Browse Media Library"
            >
              <ImageIcon className="w-4 h-4" />
              Browse
            </button>
          </div>
        </div>

        {/* Content Editor */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-xs font-medium text-stone-700">
              Content
            </label>
            <div className="flex items-center gap-1 bg-stone-100 rounded-lg p-0.5">
              <button
                type="button"
                onClick={() => setEditorMode('visual')}
                className={`flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md transition-colors ${
                  editorMode === 'visual'
                    ? 'bg-white text-stone-900 shadow-sm'
                    : 'text-stone-600 hover:text-stone-900'
                }`}
              >
                <Eye className="w-3 h-3" />
                Visual
              </button>
              <button
                type="button"
                onClick={() => setEditorMode('html')}
                className={`flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md transition-colors ${
                  editorMode === 'html'
                    ? 'bg-white text-stone-900 shadow-sm'
                    : 'text-stone-600 hover:text-stone-900'
                }`}
              >
                <Code className="w-3 h-3" />
                HTML
              </button>
            </div>
          </div>

          {editorMode === 'visual' ? (
            <RichTextEditor
              content={formData.html_content || ''}
              onChange={(html) => setFormData({ ...formData, html_content: html })}
              disabled={isSaving}
            />
          ) : (
            <textarea
              value={formData.html_content}
              onChange={(e) => setFormData({ ...formData, html_content: e.target.value })}
              rows={16}
              disabled={isSaving}
              className="w-full px-3 py-2 rounded-lg border border-stone-300 text-xs font-mono focus:ring-2 focus:ring-accent-500 focus:border-transparent resize-none disabled:opacity-50 disabled:cursor-not-allowed"
              placeholder="Enter HTML content..."
            />
          )}
          <p className="mt-1 text-xs text-stone-500">
            {formData.html_content?.length || 0} characters
          </p>
        </div>
      </div>

      {/* Media Picker Modal */}
      <MediaPickerModal
        isOpen={showMediaPicker}
        onClose={() => setShowMediaPicker(false)}
        onSelect={handleMediaSelect}
        title="Select Featured Image"
      />
    </Modal>
  )
}
