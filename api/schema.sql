-- Supabase Schema for Youdle Dashboard
-- Run this SQL in your Supabase SQL Editor
-- WARNING: This bootstrap schema drops and recreates tables. Use only for a
-- new database; existing databases must use the additive migrations instead.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- Job Queue Table (REQUIRED for dashboard)
-- Tracks generation jobs and their status
-- ============================================================================
DROP TABLE IF EXISTS job_queue CASCADE;
CREATE TABLE job_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    config JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for faster status queries
CREATE INDEX idx_job_queue_status ON job_queue(status);
CREATE INDEX idx_job_queue_started_at ON job_queue(started_at DESC);
CREATE UNIQUE INDEX job_queue_one_active ON job_queue ((1))
    WHERE status IN ('pending', 'running');

-- ============================================================================
-- Blog Posts Table (REQUIRED for dashboard)
-- Stores generated blog posts
-- ============================================================================
DROP TABLE IF EXISTS blog_posts CASCADE;
CREATE TABLE blog_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    html_content TEXT NOT NULL,
    image_url TEXT,
    category TEXT NOT NULL DEFAULT 'SHOPPERS' CHECK (category IN ('SHOPPERS', 'RECALL')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'reviewed', 'published')),
    article_url TEXT,
    job_id UUID REFERENCES job_queue(id) ON DELETE SET NULL,
    -- Blogger integration fields
    blogger_post_id TEXT,
    blogger_url TEXT,
    blogger_published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_blog_posts_status ON blog_posts(status);
CREATE INDEX idx_blog_posts_category ON blog_posts(category);
CREATE INDEX idx_blog_posts_job_id ON blog_posts(job_id);
CREATE INDEX idx_blog_posts_created_at ON blog_posts(created_at DESC);

-- ============================================================================
-- Feedback Table (REQUIRED for review workflow)
-- Stores human feedback on generated posts
-- ============================================================================
DROP TABLE IF EXISTS feedback CASCADE;
CREATE TABLE feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id UUID NOT NULL REFERENCES blog_posts(id) ON DELETE CASCADE,
    rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    feedback_type TEXT DEFAULT 'general' CHECK (feedback_type IN ('general', 'content', 'formatting', 'accuracy', 'tone')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for post feedback queries
CREATE INDEX idx_feedback_post_id ON feedback(post_id);
CREATE INDEX idx_feedback_rating ON feedback(rating);

-- ============================================================================
-- Newsletters Table (for email campaigns)
-- Tracks Mailchimp newsletter campaigns
-- ============================================================================
DROP TABLE IF EXISTS newsletter_posts CASCADE;
DROP TABLE IF EXISTS newsletters CASCADE;
CREATE TABLE newsletters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    subject TEXT NOT NULL,
    html_content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'scheduled', 'sent', 'failed')),
    mailchimp_campaign_id TEXT,
    mailchimp_web_id TEXT,
    scheduled_for TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    emails_sent INTEGER DEFAULT 0,
    open_rate DECIMAL(5,2),
    click_rate DECIMAL(5,2),
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for faster status queries
CREATE INDEX idx_newsletters_status ON newsletters(status);
CREATE INDEX idx_newsletters_created_at ON newsletters(created_at DESC);

-- ============================================================================
-- Newsletter Posts Junction Table
-- Links newsletters to blog posts
-- ============================================================================
CREATE TABLE newsletter_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    newsletter_id UUID NOT NULL REFERENCES newsletters(id) ON DELETE CASCADE,
    blog_post_id UUID NOT NULL REFERENCES blog_posts(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(newsletter_id, blog_post_id)
);

-- Indexes for junction table
CREATE INDEX idx_newsletter_posts_newsletter ON newsletter_posts(newsletter_id);
CREATE INDEX idx_newsletter_posts_blog_post ON newsletter_posts(blog_post_id);

-- ============================================================================
-- Row Level Security (RLS)
-- Enable RLS but allow all operations for now (no auth)
-- ============================================================================
ALTER TABLE job_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE blog_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE newsletters ENABLE ROW LEVEL SECURITY;
ALTER TABLE newsletter_posts ENABLE ROW LEVEL SECURITY;

-- Allow all operations (adjust for production with proper auth)
DROP POLICY IF EXISTS "Allow all for job_queue" ON job_queue;
DROP POLICY IF EXISTS "Allow all for blog_posts" ON blog_posts;
DROP POLICY IF EXISTS "Allow all for feedback" ON feedback;
DROP POLICY IF EXISTS "Allow all for newsletters" ON newsletters;
DROP POLICY IF EXISTS "Allow all for newsletter_posts" ON newsletter_posts;

CREATE POLICY "Allow all for job_queue" ON job_queue FOR ALL USING (true);
CREATE POLICY "Allow all for blog_posts" ON blog_posts FOR ALL USING (true);
CREATE POLICY "Allow all for feedback" ON feedback FOR ALL USING (true);
CREATE POLICY "Allow all for newsletters" ON newsletters FOR ALL USING (true);
CREATE POLICY "Allow all for newsletter_posts" ON newsletter_posts FOR ALL USING (true);

-- ============================================================================
-- Functions and Triggers
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for newsletters updated_at
DROP TRIGGER IF EXISTS update_newsletters_updated_at ON newsletters;
CREATE TRIGGER update_newsletters_updated_at
    BEFORE UPDATE ON newsletters
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger for blog_posts updated_at
DROP TRIGGER IF EXISTS update_blog_posts_updated_at ON blog_posts;
CREATE TRIGGER update_blog_posts_updated_at
    BEFORE UPDATE ON blog_posts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Enable Realtime (optional - comment out if you get errors)
-- ============================================================================
-- Note: If these fail, your Supabase project may not have realtime enabled
-- You can safely skip these lines

DO $$
BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE job_queue;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not add job_queue to realtime: %', SQLERRM;
END $$;

DO $$
BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE blog_posts;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not add blog_posts to realtime: %', SQLERRM;
END $$;

DO $$
BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE feedback;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not add feedback to realtime: %', SQLERRM;
END $$;

DO $$
BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE newsletters;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not add newsletters to realtime: %', SQLERRM;
END $$;

-- ============================================================================
-- Settings Table (for app configuration)
-- Stores key-value settings like active Mailchimp audience
-- ============================================================================
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS for settings
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all for settings" ON settings;
CREATE POLICY "Allow all for settings" ON settings FOR ALL USING (true);

-- ============================================================================
-- Media Library Table (for uploaded images)
-- Stores metadata for user-uploaded media files
-- ============================================================================
CREATE TABLE IF NOT EXISTS media (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    public_url TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    width INTEGER,
    height INTEGER,
    alt_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for listing media by date
CREATE INDEX IF NOT EXISTS idx_media_created_at ON media(created_at DESC);

-- RLS for media
ALTER TABLE media ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all for media" ON media;
CREATE POLICY "Allow all for media" ON media FOR ALL USING (true);

-- Trigger for media updated_at
DROP TRIGGER IF EXISTS update_media_updated_at ON media;
CREATE TRIGGER update_media_updated_at
    BEFORE UPDATE ON media
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Success message
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE 'Schema created successfully! Tables: job_queue, blog_posts, feedback, newsletters, newsletter_posts, settings, media';
END $$;
