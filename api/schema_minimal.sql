-- MINIMAL Schema - Run this in Supabase SQL Editor
-- This is the bare minimum needed for the dashboard to work

-- Step 1: Create job_queue table
CREATE TABLE IF NOT EXISTS job_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'pending',
    config JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS job_queue_one_active ON job_queue ((1))
    WHERE status IN ('pending', 'running');

-- Step 2: Create blog_posts table
CREATE TABLE IF NOT EXISTS blog_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    html_content TEXT NOT NULL,
    image_url TEXT,
    category TEXT NOT NULL DEFAULT 'SHOPPERS',
    status TEXT NOT NULL DEFAULT 'draft',
    article_url TEXT,
    job_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Step 3: Create feedback table
CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id UUID NOT NULL,
    rating INT NOT NULL,
    comment TEXT,
    feedback_type TEXT DEFAULT 'general',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Step 4: Enable Row Level Security with open policies
ALTER TABLE job_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE blog_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Enable all for job_queue" ON job_queue FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all for blog_posts" ON blog_posts FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all for feedback" ON feedback FOR ALL USING (true) WITH CHECK (true);


