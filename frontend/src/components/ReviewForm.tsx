'use client'

import { useRef, useState } from 'react'
import { Star, Send, Loader2, CheckCircle, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ReviewFormProps {
  postId: string
  postTitle: string
  onSubmit: (rating: number, comment: string, feedbackType: string, submissionId: string) => Promise<boolean>
  onApprove?: (rating: number, comment: string, feedbackType: string, submissionId: string) => Promise<boolean>
  onReject?: (rating: number, comment: string, feedbackType: string, submissionId: string) => Promise<boolean>
  onSkip: () => void
  className?: string
}

const feedbackTypes = [
  { id: 'general', label: 'General' },
  { id: 'content', label: 'Content Quality' },
  { id: 'formatting', label: 'Formatting' },
  { id: 'accuracy', label: 'Accuracy' },
  { id: 'tone', label: 'Tone/Voice' },
]

export function ReviewForm({ postId, postTitle, onSubmit, onApprove, onReject, onSkip, className }: ReviewFormProps) {
  const [rating, setRating] = useState(0)
  const [hoverRating, setHoverRating] = useState(0)
  const [comment, setComment] = useState('')
  const [feedbackType, setFeedbackType] = useState('general')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isApproving, setIsApproving] = useState(false)
  const [isRejecting, setIsRejecting] = useState(false)
  const submissionId = useRef<string | null>(null)

  const getSubmissionId = () => {
    if (!submissionId.current) {
      submissionId.current = crypto.randomUUID()
    }
    return submissionId.current
  }

  const resetForm = () => {
    setRating(0)
    setComment('')
    setFeedbackType('general')
    submissionId.current = null
  }

  const handleSubmit = async () => {
    if (rating === 0) return
    
    setIsSubmitting(true)
    try {
      if (await onSubmit(rating, comment, feedbackType, getSubmissionId())) {
        resetForm()
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleApprove = async () => {
    if (!onApprove || rating === 0) return
    
    setIsApproving(true)
    try {
      if (await onApprove(rating, comment, feedbackType, getSubmissionId())) {
        resetForm()
      }
    } finally {
      setIsApproving(false)
    }
  }

  const handleReject = async () => {
    if (!onReject || rating === 0) return
    
    setIsRejecting(true)
    try {
      if (await onReject(rating, comment, feedbackType, getSubmissionId())) {
        resetForm()
      }
    } finally {
      setIsRejecting(false)
    }
  }

  const isAnyActionPending = isSubmitting || isApproving || isRejecting

  return (
    <div className={cn(
      'rounded-2xl bg-white  border border-stone-200  p-6',
      className
    )}>
      <h3 className="text-lg font-semibold text-stone-900  mb-1">
        Review Post
      </h3>
      <p className="text-sm text-stone-500  mb-6 line-clamp-1">
        {postTitle}
      </p>

      {/* Star Rating */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-midnight-700  mb-3">
          Quality Rating
        </label>
        <div className="flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              type="button"
              onClick={() => setRating(star)}
              onMouseEnter={() => setHoverRating(star)}
              onMouseLeave={() => setHoverRating(0)}
              className="p-1 rounded-lg hover:bg-midnight-100 dark:hover:bg-stone-100 transition-colors"
            >
              <Star
                className={cn(
                  'w-8 h-8 transition-colors',
                  (hoverRating || rating) >= star
                    ? 'fill-yellow-400 text-yellow-400'
                    : 'text-midnight-300 '
                )}
              />
            </button>
          ))}
          <span className="ml-2 text-sm text-stone-500 ">
            {rating > 0 ? `${rating}/5` : 'Select rating'}
          </span>
        </div>
      </div>

      {/* Feedback Type */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-midnight-700  mb-3">
          Feedback Category
        </label>
        <div className="flex flex-wrap gap-2">
          {feedbackTypes.map((type) => (
            <button
              key={type.id}
              type="button"
              onClick={() => setFeedbackType(type.id)}
              className={cn(
                'px-3 py-1.5 rounded-lg text-sm font-medium transition-all',
                feedbackType === type.id
                  ? 'bg-youdle-100 dark:bg-youdle-900/30 text-youdle-700'
                  : 'bg-midnight-100  text-midnight-600  hover:bg-midnight-200 dark:hover:bg-midnight-700'
              )}
            >
              {type.label}
            </button>
          ))}
        </div>
      </div>

      {/* Comment */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-midnight-700  mb-2">
          Comment (Optional)
        </label>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="What could be improved? Any specific issues?"
          rows={3}
          className="w-full px-3 py-2 rounded-lg border border-midnight-300  bg-white  text-stone-900  placeholder-midnight-400 focus:ring-2 focus:ring-youdle-500 focus:border-transparent resize-none"
        />
      </div>

      {/* Actions */}
      <div className="space-y-3">
        {/* Primary Actions: Approve/Reject (Issue #858 fix) */}
        {(onApprove || onReject) && (
          <div className="flex items-center gap-3">
            {onApprove && (
              <button
                type="button"
                onClick={handleApprove}
                disabled={rating === 0 || isAnyActionPending}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
                  'bg-green-600 text-white hover:bg-green-700',
                  'disabled:opacity-50 disabled:cursor-not-allowed'
                )}
              >
                {isApproving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <CheckCircle className="w-4 h-4" />
                )}
                Mark Reviewed
              </button>
            )}
            
            {onReject && (
              <button
                type="button"
                onClick={handleReject}
                disabled={rating === 0 || isAnyActionPending}
                className={cn(
                  'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
                  'bg-red-600 text-white hover:bg-red-700',
                  'disabled:opacity-50 disabled:cursor-not-allowed'
                )}
              >
                {isRejecting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <XCircle className="w-4 h-4" />
                )}
                Reject & Review
              </button>
            )}
          </div>
        )}

        {/* Secondary Actions */}
        <div className="flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onSkip}
            disabled={isAnyActionPending}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-all",
              "text-midnight-600 hover:text-midnight-800 hover:bg-midnight-100",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            Skip
          </button>
          
          <button
            type="button"
            onClick={handleSubmit}
            disabled={rating === 0 || isAnyActionPending}
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              'bg-gradient-to-r from-youdle-500 to-youdle-600 text-stone-900',
              'hover:from-youdle-600 hover:to-youdle-700 hover:shadow-lg hover:shadow-youdle-500/25',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {isSubmitting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
            Review Only
          </button>
        </div>
      </div>
    </div>
  )
}



