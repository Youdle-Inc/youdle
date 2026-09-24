"""Utilities for keeping generation job state transitions consistent.

Supabase stores the status of a generation run, but it is not itself a worker
queue.  These helpers provide compare-and-set transitions and reconcile jobs
whose Vercel invocation disappeared before it could write a terminal status.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from uuid import uuid4


logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = ("pending", "running")
TERMINAL_JOB_STATUSES = ("completed", "failed", "cancelled")

# Shared with the CLI so a dashboard run and a scheduled run report an empty
# batch identically.
NO_USABLE_POSTS_MESSAGE = "Generation completed without producing any usable blog posts"


# The Vercel deployment gives generation functions a 30-minute window. Stale
# reconciliation must run *after* that window, otherwise normal dashboard
# polling can fail a job that still has time left to finish. Keep a five-minute
# buffer for cold starts and delayed completion writes.
GENERATION_FUNCTION_MAX_SECONDS = 30 * 60
DEFAULT_STALE_AFTER_SECONDS = 35 * 60
MIN_STALE_AFTER_SECONDS = GENERATION_FUNCTION_MAX_SECONDS + (5 * 60)


class ActiveJobConflict(RuntimeError):
    """Raised when another generation run already holds the active-job slot."""


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def isoformat_utc(value: Optional[datetime] = None) -> str:
    """Serialize a datetime as an ISO-8601 UTC value."""
    current = value or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a Supabase timestamp, returning ``None`` for invalid values."""
    if not value or not isinstance(value, str):
        return None

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_stale_after_seconds() -> int:
    """Read the stale-job window, with a safe lower bound and fallback."""
    raw_value = os.getenv(
        "GENERATION_STALE_AFTER_SECONDS",
        str(DEFAULT_STALE_AFTER_SECONDS),
    )
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid GENERATION_STALE_AFTER_SECONDS=%r; using %s",
            raw_value,
            DEFAULT_STALE_AFTER_SECONDS,
        )
        return DEFAULT_STALE_AFTER_SECONDS

    if value < MIN_STALE_AFTER_SECONDS:
        logger.warning(
            "GENERATION_STALE_AFTER_SECONDS=%s is too low; using %s",
            value,
            MIN_STALE_AFTER_SECONDS,
        )
        return MIN_STALE_AFTER_SECONDS
    return value


def transition_job(
    supabase: Any,
    job_id: str,
    from_statuses: Iterable[str],
    updates: dict[str, Any],
) -> bool:
    """Update a job only when it is still in one of ``from_statuses``.

    Returning ``False`` means another request won the state transition, such
    as a cancellation racing with task completion.
    """
    statuses = tuple(from_statuses)
    if not statuses:
        raise ValueError("from_statuses must not be empty")

    query = supabase.table("job_queue").update(updates).eq("id", job_id)
    if len(statuses) == 1:
        query = query.eq("status", statuses[0])
    else:
        query = query.in_("status", list(statuses))

    result = query.execute()
    return bool(getattr(result, "data", None))


def list_active_jobs(supabase: Any) -> list[dict[str, Any]]:
    """Return active jobs in deterministic oldest-first order."""
    result = (
        supabase.table("job_queue")
        .select("id,status,config,created_at,started_at")
        .in_("status", list(ACTIVE_JOB_STATUSES))
        .order("created_at", desc=False)
        .execute()
    )
    jobs = getattr(result, "data", None) or []
    return sorted(
        jobs,
        key=lambda job: (
            parse_timestamp(job.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(job.get("id", "")),
        ),
    )


def reconcile_stale_jobs(
    supabase: Any,
    *,
    now: Optional[datetime] = None,
    stale_after_seconds: Optional[int] = None,
) -> list[str]:
    """Mark abandoned pending/running jobs as failed.

    Pending jobs are measured from ``created_at`` and running jobs from
    ``started_at``. Invalid or absent timestamps are left untouched so a bad
    record is never destructively guessed at.
    """
    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    timeout_seconds = stale_after_seconds or get_stale_after_seconds()
    cutoff = current - timedelta(seconds=timeout_seconds)
    stale_job_ids: list[str] = []

    for job in list_active_jobs(supabase):
        status = job.get("status")
        timestamp_field = "started_at" if status == "running" else "created_at"
        reference_time = parse_timestamp(job.get(timestamp_field))
        if reference_time is None or reference_time >= cutoff:
            continue

        elapsed_minutes = max(1, round((current - reference_time).total_seconds() / 60))
        timeout_minutes = max(1, round(timeout_seconds / 60))
        transitioned = transition_job(
            supabase,
            str(job["id"]),
            (str(status),),
            {
                "status": "failed",
                "completed_at": isoformat_utc(current),
                "error": (
                    "Generation did not report completion within the configured "
                    f"{timeout_minutes}-minute window (last checked after "
                    f"{elapsed_minutes} minutes). "
                    "The Vercel function likely timed out or stopped before reporting completion."
                ),
            },
        )
        if transitioned:
            stale_job_ids.append(str(job["id"]))

    if stale_job_ids:
        logger.warning("Marked stale generation jobs as failed: %s", stale_job_ids)
    return stale_job_ids


def describe_missing_posts(
    errors: Optional[Iterable[str]] = None,
    warnings: Optional[Iterable[str]] = None,
) -> str:
    """Explain a run that finished with no usable posts.

    Errors are preferred over warnings, so the message names the failure that
    actually stopped the run rather than incidental editorial notes.
    """
    diagnostics = list(errors or []) or list(warnings or [])
    detail = "; ".join(dict.fromkeys(str(item) for item in diagnostics))[:3000]
    return NO_USABLE_POSTS_MESSAGE + (f": {detail}" if detail else "")


def start_generation_job(
    supabase: Any,
    config: dict[str, Any],
    *,
    job_id: Optional[str] = None,
) -> str:
    """Register a run that executes in-process, such as the scheduled CLI run.

    The dashboard's job history is the only record of generation activity, so a
    run started outside the API still has to appear there. Raises
    ``ActiveJobConflict`` when another run holds the single active-job slot,
    because two concurrent runs would generate duplicate posts.
    """
    reconcile_stale_jobs(supabase)

    active_jobs = list_active_jobs(supabase)
    if active_jobs:
        active_job = active_jobs[0]
        raise ActiveJobConflict(
            f"A generation job is already active ({active_job['id']}, "
            f"status: {active_job.get('status')})"
        )

    new_job_id = job_id or str(uuid4())
    try:
        supabase.table("job_queue").insert(
            {
                "id": new_job_id,
                "status": "running",
                "config": config,
                "started_at": isoformat_utc(),
                "completed_at": None,
                "result": None,
                "error": None,
            }
        ).execute()
    except Exception as insert_error:
        if is_active_job_conflict(insert_error):
            raise ActiveJobConflict(
                "Another generation job started at the same time"
            ) from insert_error
        raise

    return new_job_id


def finish_generation_job(
    supabase: Any,
    job_id: str,
    *,
    result: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> bool:
    """Write the terminal state for a job started with ``start_generation_job``.

    Always call this, including on failure: a job left active keeps the
    one-active-job slot taken until stale reconciliation releases it.
    """
    updates: dict[str, Any] = {"completed_at": isoformat_utc()}
    if error:
        updates.update({"status": "failed", "error": str(error)[:4000]})
    else:
        updates.update({"status": "completed", "result": result, "error": None})

    return transition_job(supabase, job_id, ACTIVE_JOB_STATUSES, updates)


def is_active_job_conflict(error: Exception) -> bool:
    """Identify the unique-index error used for the one-active-job lock."""
    message = str(error).lower()
    return "23505" in message and "job_queue_one_active" in message
