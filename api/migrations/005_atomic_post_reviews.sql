-- Make dashboard review submissions atomic and safe to retry.
-- Apply this migration before deploying code that calls submit_post_review().

BEGIN;

-- Fail instead of waiting indefinitely behind a busy production writer.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';

ALTER TABLE public.feedback
    ADD COLUMN IF NOT EXISTS submission_id UUID,
    ADD COLUMN IF NOT EXISTS marked_reviewed BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS category TEXT;

UPDATE public.feedback AS feedback
SET category = LOWER(posts.category)
FROM public.blog_posts AS posts
WHERE feedback.category IS NULL
  AND posts.id = feedback.post_id;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'feedback_category_valid'
          AND conrelid = 'public.feedback'::regclass
    ) THEN
        ALTER TABLE public.feedback
            ADD CONSTRAINT feedback_category_valid
            CHECK (category IS NULL OR category IN ('shoppers', 'recall')) NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.feedback
        WHERE category IS NOT NULL AND category NOT IN ('shoppers', 'recall')
    ) THEN
        ALTER TABLE public.feedback
            VALIDATE CONSTRAINT feedback_category_valid;
    END IF;
END $$;

UPDATE public.feedback
SET submission_id = gen_random_uuid()
WHERE submission_id IS NULL;

ALTER TABLE public.feedback
    ALTER COLUMN submission_id SET DEFAULT gen_random_uuid(),
    ALTER COLUMN submission_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_submission_id
    ON public.feedback(submission_id);
CREATE INDEX IF NOT EXISTS idx_feedback_category_created_at
    ON public.feedback(category, created_at DESC);

CREATE OR REPLACE FUNCTION public.submit_post_review(
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
    post_row public.blog_posts%ROWTYPE;
    feedback_row public.feedback%ROWTYPE;
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

    -- Serialize review attempts for this post. All changes in this function are
    -- committed or rolled back together by PostgreSQL.
    SELECT *
    INTO post_row
    FROM public.blog_posts
    WHERE id = p_post_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'not_found');
    END IF;

    SELECT *
    INTO feedback_row
    FROM public.feedback
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
        UPDATE public.blog_posts
        SET status = 'reviewed', updated_at = NOW()
        WHERE id = p_post_id
        RETURNING * INTO post_row;
    END IF;

    INSERT INTO public.feedback (
        post_id,
        rating,
        comment,
        feedback_type,
        submission_id,
        marked_reviewed,
        category
    ) VALUES (
        p_post_id,
        p_rating,
        NULLIF(p_comment, ''),
        p_feedback_type,
        p_submission_id,
        p_mark_reviewed,
        LOWER(post_row.category)
    )
    RETURNING * INTO feedback_row;

    RETURN jsonb_build_object(
        'post', to_jsonb(post_row),
        'feedback', to_jsonb(feedback_row),
        'replayed', false
    );
END;
$$;

COMMIT;
