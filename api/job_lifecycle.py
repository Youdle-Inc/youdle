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


logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = ("pending", "running")
TERMINAL_JOB_STATUSES = ("completed", "failed", "cancelled")

# The Vercel deployment gives generation functions a 30-minute window. Stale
# reconciliation must run *after* that window, otherwise normal dashboard
# polling can fail a job that still has time left to finish. Keep a five-minute
# buffer for cold starts and delayed completion writes.
GENERATION_FUNCTION_MAX_SECONDS = 30 * 60
DEFAULT_STALE_AFTER_SECONDS = 35 * 60
MIN_STALE_AFTER_SECONDS = GENERATION_FUNCTION_MAX_SECONDS + (5 * 60)


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


def is_active_job_conflict(error: Exception) -> bool:
    """Identify the unique-index error used for the one-active-job lock."""
    message = str(error).lower()
    return "23505" in message and "job_queue_one_active" in message
