-- Supabase Schema for Youdle Dashboard
-- Run this SQL in your Supabase SQL Editor
-- WARNING: This bootstrap schema drops and recreates tables. Use only for a
-- new database; existing databases must use the additive migrations instead.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Learning tables do not depend on job_queue, so drop them explicitly when
-- this new-database-only bootstrap is re-run.
DROP TABLE IF EXISTS learning_insights CASCADE;
DROP TABLE IF EXISTS blog_feedback CASCADE;
DROP TABLE IF EXISTS blog_examples CASCADE;

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
CREATE INDEX idx_job_queue_status_created_at ON job_queue(status, created_at DESC);
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
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_blog_posts_status ON blog_posts(status);
CREATE INDEX idx_blog_posts_category ON blog_posts(category);
CREATE INDEX idx_blog_posts_job_id ON blog_posts(job_id);
CREATE INDEX idx_blog_posts_created_at ON blog_posts(created_at DESC);
CREATE INDEX idx_blog_posts_last_synced_at ON blog_posts(last_synced_at DESC);
CREATE INDEX idx_blog_posts_recent_article_urls
    ON blog_posts(created_at DESC) INCLUDE (article_url)
    WHERE article_url <> '';
CREATE INDEX idx_blog_posts_recent_published
    ON blog_posts(blogger_published_at DESC)
    WHERE status = 'published' AND blogger_url IS NOT NULL;

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
    submission_id UUID NOT NULL DEFAULT gen_random_uuid(),
    marked_reviewed BOOLEAN NOT NULL DEFAULT false,
    category TEXT CONSTRAINT feedback_category_valid
        CHECK (category IS NULL OR category IN ('shoppers', 'recall')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for post feedback queries
CREATE INDEX idx_feedback_post_id ON feedback(post_id);
CREATE INDEX idx_feedback_rating ON feedback(rating);
CREATE UNIQUE INDEX idx_feedback_submission_id ON feedback(submission_id);
CREATE INDEX idx_feedback_category_created_at ON feedback(category, created_at DESC);

-- ============================================================================
-- Learning Tables
-- Stores curated examples, detailed review feedback, and learned guidance
-- ============================================================================
CREATE TABLE blog_examples (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    original_article_url TEXT NOT NULL,
    original_article_title TEXT NOT NULL,
    generated_html TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('shoppers', 'recall')),
    feedback_score INT DEFAULT 0 CHECK (feedback_score BETWEEN 0 AND 5),
    feedback_comments TEXT DEFAULT '',
    is_good_example BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_blog_examples_category ON blog_examples(category);
CREATE INDEX idx_blog_examples_quality
    ON blog_examples(category, is_good_example, feedback_score DESC);

CREATE TABLE blog_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    blog_post_id TEXT NOT NULL,
    feedback_type TEXT NOT NULL CHECK (
        feedback_type IN ('structure', 'content', 'tone', 'completeness', 'general')
    ),
    score INT NOT NULL CHECK (score BETWEEN 1 AND 5),
    comments TEXT DEFAULT '',
    approved BOOLEAN DEFAULT false,
    reviewer_notes TEXT DEFAULT '',
    category TEXT CONSTRAINT blog_feedback_category_valid
        CHECK (category IS NULL OR category IN ('shoppers', 'recall')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_blog_feedback_post_id ON blog_feedback(blog_post_id);
CREATE INDEX idx_blog_feedback_type_created_at
    ON blog_feedback(feedback_type, created_at DESC);
CREATE INDEX idx_blog_feedback_category_created_at
    ON blog_feedback(category, created_at DESC);

CREATE TABLE learning_insights (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    insight_type TEXT NOT NULL CHECK (
        insight_type IN (
            'common_mistake', 'improvement_pattern', 'best_practice',
            'user_preference', 'general'
        )
    ),
    description TEXT NOT NULL,
    category TEXT DEFAULT '',
    frequency INT NOT NULL DEFAULT 1
        CONSTRAINT learning_insights_frequency_positive CHECK (frequency >= 1),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_learning_insights_lookup
    ON learning_insights(category, insight_type, frequency DESC);

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
CREATE INDEX idx_newsletters_status_created_at ON newsletters(status, created_at DESC);

-- ============================================================================
-- Newsletter Posts Junction Table
-- Links newsletters to blog posts
-- ============================================================================
CREATE TABLE newsletter_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    newsletter_id UUID NOT NULL REFERENCES newsletters(id) ON DELETE CASCADE,
    blog_post_id UUID NOT NULL REFERENCES blog_posts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(newsletter_id, blog_post_id)
);

-- Indexes for junction table
CREATE INDEX idx_newsletter_posts_newsletter ON newsletter_posts(newsletter_id);
CREATE INDEX idx_newsletter_posts_blog_post ON newsletter_posts(blog_post_id);
CREATE UNIQUE INDEX idx_newsletter_posts_position
    ON newsletter_posts(newsletter_id, position);

-- ============================================================================
-- Row Level Security (RLS)
-- Enable RLS but allow all operations for now (no auth)
-- ============================================================================
ALTER TABLE job_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE blog_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE newsletters ENABLE ROW LEVEL SECURITY;
ALTER TABLE newsletter_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE blog_examples ENABLE ROW LEVEL SECURITY;
ALTER TABLE blog_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE learning_insights ENABLE ROW LEVEL SECURITY;

-- Allow all operations (adjust for production with proper auth)
DROP POLICY IF EXISTS "Allow all for job_queue" ON job_queue;
DROP POLICY IF EXISTS "Allow all for blog_posts" ON blog_posts;
DROP POLICY IF EXISTS "Allow all for feedback" ON feedback;
DROP POLICY IF EXISTS "Allow all for newsletters" ON newsletters;
DROP POLICY IF EXISTS "Allow all for newsletter_posts" ON newsletter_posts;
DROP POLICY IF EXISTS "Allow all for blog_examples" ON blog_examples;
DROP POLICY IF EXISTS "Allow all for blog_feedback" ON blog_feedback;
DROP POLICY IF EXISTS "Allow all for learning_insights" ON learning_insights;

CREATE POLICY "Allow all for job_queue" ON job_queue FOR ALL USING (true);
CREATE POLICY "Allow all for blog_posts" ON blog_posts FOR ALL USING (true);
CREATE POLICY "Allow all for feedback" ON feedback FOR ALL USING (true);
CREATE POLICY "Allow all for newsletters" ON newsletters FOR ALL USING (true);
CREATE POLICY "Allow all for newsletter_posts" ON newsletter_posts FOR ALL USING (true);
CREATE POLICY "Allow all for blog_examples" ON blog_examples FOR ALL USING (true);
CREATE POLICY "Allow all for blog_feedback" ON blog_feedback FOR ALL USING (true);
CREATE POLICY "Allow all for learning_insights" ON learning_insights FOR ALL USING (true);

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

-- Atomically save dashboard feedback and the optional draft -> reviewed change.
CREATE OR REPLACE FUNCTION submit_post_review(
    p_post_id UUID,
    p_rating INTEGER,
    p_comment TEXT,
    p_feedback_type TEXT,
    p_mark_reviewed BOOLEAN,
    p_submission_id UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    post_row blog_posts%ROWTYPE;
    feedback_row feedback%ROWTYPE;
BEGIN
    IF p_rating < 1 OR p_rating > 5 THEN
        RAISE EXCEPTION 'rating must be between 1 and 5' USING ERRCODE = '22023';
    END IF;
    IF p_feedback_type NOT IN ('general', 'content', 'formatting', 'accuracy', 'tone') THEN
        RAISE EXCEPTION 'invalid feedback type' USING ERRCODE = '22023';
    END IF;
    IF p_submission_id IS NULL THEN
        RAISE EXCEPTION 'submission_id is required' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO post_row
    FROM blog_posts
    WHERE id = p_post_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'not_found');
    END IF;

    SELECT * INTO feedback_row
    FROM feedback
    WHERE submission_id = p_submission_id;

    IF FOUND THEN
        IF feedback_row.post_id <> p_post_id
           OR feedback_row.rating <> p_rating
           OR COALESCE(feedback_row.comment, '') <> COALESCE(p_comment, '')
           OR feedback_row.feedback_type <> p_feedback_type
           OR feedback_row.marked_reviewed <> p_mark_reviewed THEN
            RETURN jsonb_build_object('error', 'idempotency_conflict');
        END IF;

        RETURN jsonb_build_object(
            'post', to_jsonb(post_row),
            'feedback', to_jsonb(feedback_row),
            'replayed', true
        );
    END IF;

    IF p_mark_reviewed AND post_row.status <> 'draft' THEN
        RETURN jsonb_build_object(
            'error', 'status_conflict',
            'current_status', post_row.status
        );
    END IF;

    IF p_mark_reviewed THEN
        UPDATE blog_posts
        SET status = 'reviewed', updated_at = NOW()
        WHERE id = p_post_id
        RETURNING * INTO post_row;
    END IF;

    INSERT INTO feedback (
        post_id, rating, comment, feedback_type, submission_id, marked_reviewed,
        category
    ) VALUES (
        p_post_id, p_rating, NULLIF(p_comment, ''), p_feedback_type,
        p_submission_id, p_mark_reviewed, LOWER(post_row.category)
    )
    RETURNING * INTO feedback_row;

    RETURN jsonb_build_object(
        'post', to_jsonb(post_row),
        'feedback', to_jsonb(feedback_row),
        'replayed', false
    );
END;
$$;

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

-- Trigger for settings updated_at
DROP TRIGGER IF EXISTS update_settings_updated_at ON settings;
CREATE TRIGGER update_settings_updated_at
    BEFORE UPDATE ON settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

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
    RAISE NOTICE 'Schema created successfully! Core dashboard and learning tables are ready.';
END $$;
