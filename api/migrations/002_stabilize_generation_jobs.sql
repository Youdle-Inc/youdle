-- Stabilization migration: allow only one dashboard generation job at a time.
--
-- Apply this file once in the Supabase SQL editor. Do not re-run api/schema.sql;
-- that file drops existing tables and data.

BEGIN;

-- Preserve the newest active row and close older abandoned/overlapping rows so
-- the unique index can be created safely on an existing production database.
WITH ranked_active_jobs AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            ORDER BY COALESCE(started_at, created_at) DESC, id DESC
        ) AS active_rank
    FROM public.job_queue
    WHERE status IN ('pending', 'running')
)
UPDATE public.job_queue AS jobs
SET
    status = 'failed',
    completed_at = NOW(),
    error = 'Closed during generation-job stabilization because another active job was retained.'
FROM ranked_active_jobs
WHERE jobs.id = ranked_active_jobs.id
  AND ranked_active_jobs.active_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS job_queue_one_active
    ON public.job_queue ((1))
    WHERE status IN ('pending', 'running');

COMMIT;
