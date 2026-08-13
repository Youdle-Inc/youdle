-- Database contract/index stabilization.
--
-- This migration does not delete application rows and is idempotent. Ordinary
-- CREATE INDEX/ALTER TABLE statements can briefly lock writes, so run it during
-- a quiet deployment window and apply it before deploying the matching code.

BEGIN;

-- Fail instead of waiting indefinitely behind a busy production writer.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE public.blog_posts
    ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_blog_posts_last_synced_at
    ON public.blog_posts(last_synced_at DESC);

-- Supports the generation workflow's 60-day source URL deduplication lookup.
-- This is deliberately non-unique because production contains legacy
-- duplicates that require a separate, reviewed cleanup.
CREATE INDEX IF NOT EXISTS idx_blog_posts_recent_article_urls
    ON public.blog_posts(created_at DESC) INCLUDE (article_url)
    WHERE article_url <> '';

-- Supports weekly/recent newsletter candidate queries by actual Blogger
-- publication time rather than the row's original creation time.
CREATE INDEX IF NOT EXISTS idx_blog_posts_recent_published
    ON public.blog_posts(blogger_published_at DESC)
    WHERE status = 'published' AND blogger_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_job_queue_status_created_at
    ON public.job_queue(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_newsletters_status_created_at
    ON public.newsletters(status, created_at DESC);

-- Enforce deterministic positions only when existing data is already clean.
-- If legacy rows need repair, the migration continues and prints a notice;
-- application-side ordering remains deterministic in the meantime.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.newsletter_posts
        WHERE position IS NULL OR position < 0
    ) OR EXISTS (
        SELECT 1
        FROM public.newsletter_posts
        WHERE position IS NOT NULL
        GROUP BY newsletter_id, position
        HAVING COUNT(*) > 1
    ) THEN
        RAISE NOTICE 'Skipped unique newsletter position index: repair NULL, negative, or duplicate legacy positions first.';
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS idx_newsletter_posts_position
            ON public.newsletter_posts(newsletter_id, position);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'newsletter_posts_position_nonnegative'
          AND conrelid = 'public.newsletter_posts'::regclass
    ) THEN
        ALTER TABLE public.newsletter_posts
            ADD CONSTRAINT newsletter_posts_position_nonnegative
            CHECK (position IS NOT NULL AND position >= 0) NOT VALID;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.newsletter_posts
        WHERE position IS NULL OR position < 0
    ) THEN
        RAISE NOTICE 'Newsletter positions still contain invalid rows; constraint remains NOT VALID and the column remains nullable.';
    ELSE
        ALTER TABLE public.newsletter_posts
            VALIDATE CONSTRAINT newsletter_posts_position_nonnegative;
        ALTER TABLE public.newsletter_posts
            ALTER COLUMN position SET NOT NULL;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Keep settings.updated_at truthful on database-side updates.
DROP TRIGGER IF EXISTS update_settings_updated_at ON public.settings;
CREATE TRIGGER update_settings_updated_at
    BEFORE UPDATE ON public.settings
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

COMMIT;
