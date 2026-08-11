import { createClient, SupabaseClient, RealtimeChannel } from '@supabase/supabase-js'

// Types for database tables
export interface Job {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  config: {
    batch_size: number
    search_days_back: number
    model: string
    use_placeholder_images: boolean
  }
  created_at: string
  started_at: string | null
  completed_at: string | null
  result: {
    posts_generated?: number
    errors?: string[]
    logs?: string[]
  } | null
  error: string | null
}

export interface BlogPost {
  id: string
  title: string
  html_content: string
  image_url: string | null
  category: 'SHOPPERS' | 'RECALL'
  status: 'draft' | 'reviewed' | 'published'
  article_url: string
  job_id: string | null
  created_at: string
  updated_at?: string
}

export interface Feedback {
  id: string
  post_id: string
  rating: number
  comment: string | null
  created_at: string
}

// Singleton Supabase client
let supabaseClient: SupabaseClient | null = null

export function getSupabase(): SupabaseClient {
  if (!supabaseClient) {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
    const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

    if (!supabaseUrl || !supabaseKey) {
      throw new Error('Missing Supabase configuration. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.')
    }

    supabaseClient = createClient(supabaseUrl, supabaseKey, {
      realtime: {
        params: {
          eventsPerSecond: 10
        }
      }
    })
  }

  return supabaseClient
}

// Real-time subscription helpers
export function subscribeToJobs(
  callback: (payload: { eventType: string; new: Job; old: Job | null }) => void
): RealtimeChannel {
  const supabase = getSupabase()
  
  return supabase
    .channel('job_updates')
    .on(
      'postgres_changes',
      { event: '*', schema: 'public', table: 'job_queue' },
      (payload) => {
        callback({
          eventType: payload.eventType,
          new: payload.new as Job,
          old: payload.old as Job | null
        })
      }
    )
    .subscribe()
}

export function subscribeToPosts(
  callback: (payload: { eventType: string; new: BlogPost; old: BlogPost | null }) => void
): RealtimeChannel {
  const supabase = getSupabase()
  
  return supabase
    .channel('post_updates')
    .on(
      'postgres_changes',
      { event: '*', schema: 'public', table: 'blog_posts' },
      (payload) => {
        callback({
          eventType: payload.eventType,
          new: payload.new as BlogPost,
          old: payload.old as BlogPost | null
        })
      }
    )
    .subscribe()
}

// Database query helpers
export async function getRecentJobs(limit = 10): Promise<Job[]> {
  const supabase = getSupabase()
  const { data, error } = await supabase
    .from('job_queue')
    .select('*')
    .order('started_at', { ascending: false })
    .limit(limit)

  if (error) throw error
  return data as Job[]
}

export async function getRecentPosts(limit = 20): Promise<BlogPost[]> {
  const supabase = getSupabase()
  const { data, error } = await supabase
    .from('blog_posts')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(limit)

  if (error) throw error
  return data as BlogPost[]
}

export async function updatePostStatus(
  postId: string, 
  status: 'draft' | 'reviewed' | 'published'
): Promise<BlogPost> {
  const supabase = getSupabase()
  const { data, error } = await supabase
    .from('blog_posts')
    .update({ status, updated_at: new Date().toISOString() })
    .eq('id', postId)
    .select()
    .single()

  if (error) throw error
  return data as BlogPost
}

export async function addFeedback(
  postId: string,
  rating: number,
  comment?: string
): Promise<Feedback> {
  const supabase = getSupabase()
  const { data, error } = await supabase
    .from('feedback')
    .insert({
      post_id: postId,
      rating,
      comment: comment || null,
      created_at: new Date().toISOString()
    })
    .select()
    .single()

  if (error) throw error
  return data as Feedback
}



