-- Add the learning-system tables to the numbered migration chain.
-- Safe to run when the legacy api/migration_learning_tables.sql was already
-- applied. Existing tables are supplemented with the named constraints below.

BEGIN;

-- Fail instead of waiting indefinitely behind a busy production writer.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

CREATE TABLE IF NOT EXISTS public.blog_examples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_article_url TEXT NOT NULL,
    original_article_title TEXT NOT NULL,
    generated_html TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('shoppers', 'recall')),
    feedback_score INT DEFAULT 0 CHECK (feedback_score BETWEEN 0 AND 5),
    feedback_comments TEXT DEFAULT '',
    is_good_example BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_blog_examples_category
    ON public.blog_examples(category);
CREATE INDEX IF NOT EXISTS idx_blog_examples_quality
    ON public.blog_examples(category, is_good_example, feedback_score DESC);

CREATE TABLE IF NOT EXISTS public.blog_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blog_post_id TEXT NOT NULL,
    feedback_type TEXT NOT NULL CHECK (
        feedback_type IN ('structure', 'content', 'tone', 'completeness', 'general')
    ),
    score INT NOT NULL CHECK (score BETWEEN 1 AND 5),
    comments TEXT DEFAULT '',
    approved BOOLEAN DEFAULT false,
    reviewer_notes TEXT DEFAULT '',
    category TEXT CONSTRAINT blog_feedback_category_valid
        CHECK (category IN ('shoppers', 'recall')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.blog_feedback
    ADD COLUMN IF NOT EXISTS category TEXT;

UPDATE public.blog_feedback AS feedback
SET category = LOWER(posts.category)
FROM public.blog_posts AS posts
WHERE feedback.category IS NULL
  AND posts.id::TEXT = feedback.blog_post_id;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'blog_feedback_category_valid'
          AND conrelid = 'public.blog_feedback'::regclass
    ) THEN
        ALTER TABLE public.blog_feedback
            ADD CONSTRAINT blog_feedback_category_valid
            CHECK (category IS NULL OR category IN ('shoppers', 'recall')) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.blog_feedback
        WHERE category IS NOT NULL AND category NOT IN ('shoppers', 'recall')
    ) THEN
        ALTER TABLE public.blog_feedback
            VALIDATE CONSTRAINT blog_feedback_category_valid;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_blog_feedback_post_id
    ON public.blog_feedback(blog_post_id);
CREATE INDEX IF NOT EXISTS idx_blog_feedback_type_created_at
    ON public.blog_feedback(feedback_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_blog_feedback_category_created_at
    ON public.blog_feedback(category, created_at DESC);

CREATE TABLE IF NOT EXISTS public.learning_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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

CREATE INDEX IF NOT EXISTS idx_learning_insights_lookup
    ON public.learning_insights(category, insight_type, frequency DESC);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'learning_insights_frequency_positive'
          AND conrelid = 'public.learning_insights'::regclass
    ) THEN
        ALTER TABLE public.learning_insights
            ADD CONSTRAINT learning_insights_frequency_positive
            CHECK (frequency IS NOT NULL AND frequency >= 1) NOT VALID;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.learning_insights
        WHERE frequency IS NULL OR frequency < 1
    ) THEN
        RAISE NOTICE 'learning_insights contains invalid frequencies; the new constraint remains NOT VALID.';
    ELSE
        ALTER TABLE public.learning_insights
            VALIDATE CONSTRAINT learning_insights_frequency_positive;
        ALTER TABLE public.learning_insights
            ALTER COLUMN frequency SET NOT NULL;
    END IF;
END $$;

ALTER TABLE public.blog_examples ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.blog_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.learning_insights ENABLE ROW LEVEL SECURITY;

-- These policies preserve the repository's current unauthenticated behavior.
-- Replace them together with the core-table open policies once dashboard/API
-- authentication and a server-only service role key are deployed.
DROP POLICY IF EXISTS "Enable all for blog_examples" ON public.blog_examples;
DROP POLICY IF EXISTS "Enable all for blog_feedback" ON public.blog_feedback;
DROP POLICY IF EXISTS "Enable all for learning_insights" ON public.learning_insights;
DROP POLICY IF EXISTS "Allow all for blog_examples" ON public.blog_examples;
DROP POLICY IF EXISTS "Allow all for blog_feedback" ON public.blog_feedback;
DROP POLICY IF EXISTS "Allow all for learning_insights" ON public.learning_insights;

CREATE POLICY "Allow all for blog_examples"
    ON public.blog_examples FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for blog_feedback"
    ON public.blog_feedback FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for learning_insights"
    ON public.learning_insights FOR ALL USING (true) WITH CHECK (true);

COMMIT;
