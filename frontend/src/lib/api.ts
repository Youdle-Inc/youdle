/**
 * FastAPI Client
 * Utilities for communicating with the Python backend.
 */

const configuredApiUrl = process.env.NEXT_PUBLIC_API_URL?.trim()
const defaultApiUrl = process.env.NODE_ENV === 'development'
  ? 'http://localhost:8000'
  : 'https://youdle.vercel.app'

export const API_BASE_URL = (configuredApiUrl || defaultApiUrl).replace(/\/+$/, '')

// Types
export interface SearchResult {
  title: string
  description: string
  link: string
  pubDate: string
  category: 'SHOPPERS' | 'RECALL'
  subcategory?: string
  score: number
  feedIndex: number
}

export interface SearchResponse {
  items: SearchResult[]
  recall_items: SearchResult[]
  processed_count: number
  total_ranked_count: number
  shoppers_count: number
  recall_count: number
  timestamp: string
}

export interface GenerationConfig {
  batch_size: number
  search_days_back: number
  model: string
  use_placeholder_images: boolean
  use_legacy_orchestrator: boolean
}

export interface GenerationResponse {
  job_id: string
  status: string
  message: string
  config: GenerationConfig
}

export interface ServiceHealthCheck {
  status: 'available' | 'unavailable' | 'configured' | 'not_configured'
  message: string
}

export interface HealthResponse {
  status: 'healthy' | 'degraded'
  service: string
  checks: Record<string, ServiceHealthCheck>
  timestamp: string
}

export interface SystemStats {
  jobs: {
    total: number
    running: number
    completed: number
    failed: number
  }
  posts: {
    total: number
    draft: number
    reviewed: number
    published: number
    by_category: {
      shoppers: number
      recall: number
    }
  }
  newsletters: {
    total: number
    draft: number
    scheduled: number
    sent: number
  }
  timestamp: string
  error?: string
}

// Newsletter types
export interface BlogPostSummary {
  id: string
  title: string
  category: string
  blogger_url: string | null
}

export interface Newsletter {
  id: string
  title: string
  subject: string
  html_content: string
  status: 'draft' | 'scheduled' | 'sent' | 'failed'
  mailchimp_campaign_id: string | null
  mailchimp_web_id: string | null
  scheduled_for: string | null
  sent_at: string | null
  emails_sent: number
  open_rate: number | null
  click_rate: number | null
  error: string | null
  created_at: string
  updated_at: string
  posts: BlogPostSummary[]
}

export interface NewsletterCreate {
  title?: string
  subject?: string
  post_ids: string[]
}

export interface NewsletterUpdate {
  title?: string
  subject?: string
  post_ids?: string[]
}

export interface NewsletterListResponse {
  newsletters: Newsletter[]
  total: number
}

export interface BlogPostUpdate {
  title?: string
  html_content?: string
  image_url?: string | null
  category?: 'SHOPPERS' | 'RECALL'
}

export interface BloggerStatus {
  configured: boolean
  blog_id: string | null
  message: string
}

export interface PublishResponse {
  message: string
  blogger_post_id: string
  blogger_url: string
  post: any
}

export interface MailchimpAudience {
  id: string
  name: string
  member_count: number
}

export interface AudiencesResponse {
  audiences: MailchimpAudience[]
  current: string | null
}

export interface NewsletterReadiness {
  success: boolean
  week_start: string
  shoppers_published: number
  shoppers_required: number
  recall_published: number
  recall_required: number
  total_published: number
  total_required: number
  meets_requirement: boolean
  shoppers_needed: number
  recall_needed: number
  next_newsletter: string
  timestamp: string
  error?: string
}

// Media types
export interface MediaItem {
  id: string
  filename: string
  original_filename: string
  public_url: string
  mime_type: string
  file_size: number
  width: number | null
  height: number | null
  alt_text: string | null
  created_at: string
}

export interface MediaListResponse {
  items: MediaItem[]
  total: number
}

// GitHub Actions types
export interface WorkflowInput {
  name: string
  description: string | null
  required: boolean
  default: string | null
  type: 'string' | 'boolean' | 'choice'
  options: string[] | null
}

export interface Workflow {
  id: number
  name: string
  path: string
  state: string
  created_at: string
  updated_at: string
  html_url: string
  badge_url: string
  schedule: string | null
  inputs: WorkflowInput[]
}

export interface WorkflowRun {
  id: number
  name: string
  workflow_id: number
  status: 'queued' | 'in_progress' | 'completed'
  conclusion: 'success' | 'failure' | 'cancelled' | 'skipped' | null
  event: string
  created_at: string
  updated_at: string
  run_started_at: string | null
  html_url: string
  actor: string | null
  run_number: number
  duration_seconds: number | null
}

export interface WorkflowListResponse {
  workflows: Workflow[]
}

export interface WorkflowRunListResponse {
  runs: WorkflowRun[]
  total_count: number
}

export interface TriggerWorkflowRequest {
  ref?: string
  inputs?: Record<string, string | boolean>
}

export interface ActionsStatus {
  configured: boolean
  owner?: string
  repo?: string
  workflow_count?: number
  error?: string
}

// API Client class
class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 30000)

    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
        },
      })

      const responseText = await response.text()
      let responseBody: any = null
      if (responseText) {
        try {
          responseBody = JSON.parse(responseText)
        } catch {
          responseBody = responseText
        }
      }

      if (!response.ok) {
        const detail = typeof responseBody === 'object' && responseBody?.detail
          ? responseBody.detail
          : responseBody
        const message = typeof detail === 'string'
          ? detail
          : `API request failed with HTTP ${response.status}`
        throw new Error(message)
      }

      return responseBody as T
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error('The API request timed out after 30 seconds')
      }
      throw error
    } finally {
      clearTimeout(timeoutId)
    }
  }

  // Health check
  async healthCheck(): Promise<HealthResponse> {
    return this.request('/api/health')
  }

  // Stats
  async getStats(): Promise<SystemStats> {
    return this.request('/api/stats')
  }

  // Newsletter Readiness
  async getNewsletterReadiness(): Promise<NewsletterReadiness> {
    return this.request('/api/newsletter-readiness')
  }

  // Search
  async previewSearch(params: {
    batch_size?: number
    days_back?: number
    category?: string
  } = {}): Promise<SearchResponse> {
    const queryParams = new URLSearchParams()
    if (params.batch_size) queryParams.set('batch_size', String(params.batch_size))
    if (params.days_back) queryParams.set('days_back', String(params.days_back))
    if (params.category) queryParams.set('category', params.category)

    const query = queryParams.toString()
    return this.request(`/api/search/preview${query ? `?${query}` : ''}`)
  }

  async testSearchQuery(query: string, numResults = 5): Promise<any> {
    const params = new URLSearchParams({ query, num_results: String(numResults) })
    return this.request(`/api/search/test-query?${params}`, { method: 'POST' })
  }

  // Generation
  async startGeneration(config: Partial<GenerationConfig> = {}): Promise<GenerationResponse> {
    return this.request('/api/generate/run', {
      method: 'POST',
      body: JSON.stringify({
        batch_size: config.batch_size ?? 10,
        search_days_back: config.search_days_back ?? 30,
        model: config.model ?? 'gpt-4',
        use_placeholder_images: config.use_placeholder_images ?? false,
        use_legacy_orchestrator: config.use_legacy_orchestrator ?? false,
      }),
    })
  }

  async getPosts(params: {
    status?: string
    category?: string
    limit?: number
    offset?: number
  } = {}): Promise<any[]> {
    const queryParams = new URLSearchParams()
    if (params.status) queryParams.set('status', params.status)
    if (params.category) queryParams.set('category', params.category)
    if (params.limit) queryParams.set('limit', String(params.limit))
    if (params.offset) queryParams.set('offset', String(params.offset))

    const query = queryParams.toString()
    return this.request(`/api/generate/posts${query ? `?${query}` : ''}`)
  }

  async getPost(postId: string): Promise<any> {
    return this.request(`/api/generate/posts/${postId}`)
  }

  async updatePostStatus(postId: string, status: string): Promise<any> {
    return this.request(`/api/generate/posts/${postId}/status?status=${status}`, {
      method: 'PATCH',
    })
  }

  async deletePost(postId: string): Promise<any> {
    return this.request(`/api/generate/posts/${postId}`, { method: 'DELETE' })
  }

  async updatePost(postId: string, updates: BlogPostUpdate): Promise<any> {
    return this.request(`/api/generate/posts/${postId}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    })
  }

  // Blogger Integration
  async getBloggerStatus(): Promise<BloggerStatus> {
    return this.request('/api/generate/blogger/status')
  }

  async publishToBlogger(postId: string): Promise<PublishResponse> {
    return this.request(`/api/generate/posts/${postId}/publish`, {
      method: 'POST',
    })
  }

  async unpublishFromBlogger(postId: string): Promise<{ message: string; post: any }> {
    return this.request(`/api/generate/posts/${postId}/unpublish`, {
      method: 'POST',
    })
  }

  async syncWithBlogger(): Promise<{
    message: string
    synced_count: number
    issues_found: number
    issues_fixed: number
    imported_count: number
    pushed_count: number
    blogger_live_posts: number
    blogger_draft_posts: number
    database_posts_checked: number
    details: Array<{
      post_id: string
      title: string
      issue_type: string
      local_status: string
      blogger_status: string
      action_taken: string
    }>
  }> {
    return this.request('/api/generate/blogger/sync', {
      method: 'POST',
    })
  }

  async syncWithBloggerLight(): Promise<{
    message: string
    synced_count: number
    posts_checked: number
  }> {
    return this.request('/api/generate/blogger/sync-light', {
      method: 'POST',
    })
  }

  // Jobs
  async listJobs(params: {
    status?: string
    limit?: number
    offset?: number
  } = {}): Promise<{ jobs: any[]; total: number }> {
    const queryParams = new URLSearchParams()
    if (params.status) queryParams.set('status', params.status)
    if (params.limit) queryParams.set('limit', String(params.limit))
    if (params.offset) queryParams.set('offset', String(params.offset))

    const query = queryParams.toString()
    return this.request(`/api/jobs${query ? `?${query}` : ''}`)
  }

  async getJob(jobId: string): Promise<any> {
    return this.request(`/api/jobs/${jobId}`)
  }

  async getJobPosts(jobId: string): Promise<{ job_id: string; posts: any[]; count: number }> {
    return this.request(`/api/jobs/${jobId}/posts`)
  }

  async getJobLogs(jobId: string): Promise<{ job_id: string; status: string; logs: string[]; error: string | null }> {
    return this.request(`/api/jobs/${jobId}/logs`)
  }

  async cancelJob(jobId: string): Promise<any> {
    return this.request(`/api/jobs/${jobId}`, { method: 'DELETE' })
  }

  async cleanupOldJobs(daysOld = 30): Promise<{ message: string; deleted_count: number }> {
    return this.request(`/api/jobs/cleanup?days_old=${daysOld}`, { method: 'POST' })
  }

  // Newsletters
  async listNewsletters(params: {
    status?: string
    limit?: number
    offset?: number
  } = {}): Promise<NewsletterListResponse> {
    const queryParams = new URLSearchParams()
    if (params.status) queryParams.set('status', params.status)
    if (params.limit) queryParams.set('limit', String(params.limit))
    if (params.offset) queryParams.set('offset', String(params.offset))

    const query = queryParams.toString()
    return this.request(`/api/newsletters${query ? `?${query}` : ''}`)
  }

  async getNewsletter(id: string): Promise<Newsletter> {
    return this.request(`/api/newsletters/${id}`)
  }

  async createNewsletter(data: NewsletterCreate): Promise<Newsletter> {
    return this.request('/api/newsletters', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async updateNewsletter(id: string, data: NewsletterUpdate): Promise<Newsletter> {
    return this.request(`/api/newsletters/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    })
  }

  async deleteNewsletter(id: string): Promise<{ message: string; id: string }> {
    return this.request(`/api/newsletters/${id}`, { method: 'DELETE' })
  }

  async previewNewsletter(id: string): Promise<{ html: string }> {
    return this.request(`/api/newsletters/${id}/preview`)
  }

  async scheduleNewsletter(id: string): Promise<Newsletter> {
    return this.request(`/api/newsletters/${id}/schedule`, { method: 'POST' })
  }

  async sendNewsletter(id: string): Promise<Newsletter> {
    return this.request(`/api/newsletters/${id}/send`, { method: 'POST' })
  }

  async unscheduleNewsletter(id: string): Promise<Newsletter> {
    return this.request(`/api/newsletters/${id}/unschedule`, { method: 'POST' })
  }

  async retryNewsletter(id: string): Promise<Newsletter> {
    return this.request(`/api/newsletters/${id}/retry`, { method: 'POST' })
  }

  async getPublishedPostsForNewsletter(): Promise<BlogPostSummary[]> {
    return this.request('/api/newsletters/published-posts')
  }

  async autoCreateNewsletter(): Promise<Newsletter> {
    return this.request('/api/newsletters/auto-create', { method: 'POST' })
  }

  async queueArticles(): Promise<Newsletter> {
    return this.request('/api/newsletters/queue-articles', { method: 'POST' })
  }

  async publishNowAuto(): Promise<Newsletter> {
    return this.request('/api/newsletters/publish-now', { method: 'POST' })
  }

  async syncNewsletterStats(id: string): Promise<Newsletter> {
    return this.request(`/api/newsletters/${id}/sync-stats`, { method: 'POST' })
  }

  // Mailchimp Audiences
  async getMailchimpAudiences(): Promise<AudiencesResponse> {
    return this.request('/api/newsletters/audiences')
  }

  async setMailchimpAudience(audienceId: string): Promise<{ success: boolean; audience_id: string; message: string }> {
    return this.request(`/api/newsletters/audiences/set?audience_id=${audienceId}`, { method: 'POST' })
  }

  // Media Library
  async listMedia(params: { limit?: number; offset?: number } = {}): Promise<MediaListResponse> {
    const queryParams = new URLSearchParams()
    if (params.limit) queryParams.set('limit', String(params.limit))
    if (params.offset) queryParams.set('offset', String(params.offset))
    const query = queryParams.toString()
    return this.request(`/api/media${query ? `?${query}` : ''}`)
  }

  async uploadMedia(file: File, altText?: string): Promise<MediaItem> {
    const formData = new FormData()
    formData.append('file', file)
    if (altText) formData.append('alt_text', altText)

    const response = await fetch(`${this.baseUrl}/api/media/upload`, {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }

    return response.json()
  }

  async deleteMedia(mediaId: string): Promise<{ message: string; id: string }> {
    return this.request(`/api/media/${mediaId}`, { method: 'DELETE' })
  }

  async getMedia(mediaId: string): Promise<MediaItem> {
    return this.request(`/api/media/${mediaId}`)
  }

  // GitHub Actions
  async getActionsStatus(): Promise<ActionsStatus> {
    return this.request('/api/actions/status')
  }

  async listWorkflows(): Promise<WorkflowListResponse> {
    return this.request('/api/actions/workflows')
  }

  async listWorkflowRuns(
    workflowId: number,
    params: { status?: string; limit?: number } = {}
  ): Promise<WorkflowRunListResponse> {
    const queryParams = new URLSearchParams()
    if (params.status) queryParams.set('status', params.status)
    if (params.limit) queryParams.set('limit', String(params.limit))
    const query = queryParams.toString()
    return this.request(`/api/actions/workflows/${workflowId}/runs${query ? `?${query}` : ''}`)
  }

  async listAllWorkflowRuns(params: { status?: string; limit?: number } = {}): Promise<WorkflowRunListResponse> {
    const queryParams = new URLSearchParams()
    if (params.status) queryParams.set('status', params.status)
    if (params.limit) queryParams.set('limit', String(params.limit))
    const query = queryParams.toString()
    return this.request(`/api/actions/runs${query ? `?${query}` : ''}`)
  }

  async triggerWorkflow(workflowId: number, data: TriggerWorkflowRequest = {}): Promise<{ message: string; workflow_id: number; ref: string }> {
    return this.request(`/api/actions/workflows/${workflowId}/dispatch`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async cancelWorkflowRun(runId: number): Promise<{ message: string; run_id: number }> {
    return this.request(`/api/actions/runs/${runId}/cancel`, {
      method: 'POST',
    })
  }

  async enableWorkflow(workflowId: number): Promise<{ message: string; workflow_id: number }> {
    return this.request(`/api/actions/workflows/${workflowId}/enable`, {
      method: 'PUT',
    })
  }

  async disableWorkflow(workflowId: number): Promise<{ message: string; workflow_id: number }> {
    return this.request(`/api/actions/workflows/${workflowId}/disable`, {
      method: 'PUT',
    })
  }
}

// Export singleton instance
export const api = new ApiClient()

// Export class for custom instances
export { ApiClient }



