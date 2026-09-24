"""Focused tests for generation job stabilization helpers."""

import os
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from api.job_lifecycle import (
    DEFAULT_STALE_AFTER_SECONDS,
    MIN_STALE_AFTER_SECONDS,
    ActiveJobConflict,
    describe_missing_posts,
    finish_generation_job,
    get_stale_after_seconds,
    is_active_job_conflict,
    list_active_jobs,
    reconcile_stale_jobs,
    start_generation_job,
    transition_job,
)


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows, action="select", updates=None):
        self.rows = rows
        self.action = action
        self.updates = updates or {}
        self.filters = []
        self.ordering = None

    def select(self, *_args, **_kwargs):
        return self

    def update(self, updates):
        self.action = "update"
        self.updates = updates
        return self

    def eq(self, column, value):
        self.filters.append(lambda row, c=column, v=value: row.get(c) == v)
        return self

    def in_(self, column, values):
        allowed = set(values)
        self.filters.append(lambda row, c=column, a=allowed: row.get(c) in a)
        return self

    def order(self, column, desc=False):
        self.ordering = (column, desc)
        return self

    def execute(self):
        matched = [row for row in self.rows if all(check(row) for check in self.filters)]
        if self.ordering:
            column, desc = self.ordering
            matched.sort(key=lambda row: row.get(column) or "", reverse=desc)
        if self.action == "update":
            for row in matched:
                row.update(deepcopy(self.updates))
        return FakeResult(deepcopy(matched))


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *args, **kwargs):
        return FakeQuery(self.rows).select(*args, **kwargs)

    def update(self, updates):
        return FakeQuery(self.rows, action="update", updates=updates)

    def insert(self, payload):
        return FakeInsert(self.rows, payload)


class FakeInsert:
    def __init__(self, rows, payload):
        self.rows = rows
        self.payload = payload

    def execute(self):
        row = deepcopy(self.payload)
        row.setdefault("created_at", row.get("started_at"))
        self.rows.append(row)
        return FakeResult([deepcopy(row)])


class FakeSupabase:
    def __init__(self, jobs):
        self.jobs = jobs

    def table(self, name):
        if name != "job_queue":
            raise AssertionError(f"Unexpected table: {name}")
        return FakeTable(self.jobs)


class JobLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def test_reconcile_expires_stale_pending_and_running_jobs(self):
        old = (self.now - timedelta(minutes=20)).isoformat()
        fresh = (self.now - timedelta(minutes=2)).isoformat()
        jobs = [
            {"id": "pending-old", "status": "pending", "created_at": old, "started_at": None},
            {"id": "running-old", "status": "running", "created_at": old, "started_at": old},
            {"id": "running-fresh", "status": "running", "created_at": old, "started_at": fresh},
            {"id": "complete-old", "status": "completed", "created_at": old, "started_at": old},
        ]
        client = FakeSupabase(jobs)

        expired = reconcile_stale_jobs(
            client,
            now=self.now,
            stale_after_seconds=15 * 60,
        )

        self.assertEqual(expired, ["pending-old", "running-old"])
        self.assertEqual(jobs[0]["status"], "failed")
        self.assertEqual(jobs[1]["status"], "failed")
        self.assertEqual(jobs[2]["status"], "running")
        self.assertEqual(jobs[3]["status"], "completed")
        self.assertIn("Vercel function likely timed out", jobs[0]["error"])

    def test_reconcile_leaves_invalid_timestamps_untouched(self):
        jobs = [
            {"id": "missing", "status": "pending", "created_at": None, "started_at": None},
            {"id": "invalid", "status": "running", "created_at": "bad", "started_at": "bad"},
        ]

        expired = reconcile_stale_jobs(
            FakeSupabase(jobs),
            now=self.now,
            stale_after_seconds=60,
        )

        self.assertEqual(expired, [])
        self.assertEqual([job["status"] for job in jobs], ["pending", "running"])

    def test_compare_and_set_does_not_overwrite_cancelled_job(self):
        jobs = [{"id": "job-1", "status": "cancelled", "created_at": self.now.isoformat()}]

        changed = transition_job(
            FakeSupabase(jobs),
            "job-1",
            ("running",),
            {"status": "completed"},
        )

        self.assertFalse(changed)
        self.assertEqual(jobs[0]["status"], "cancelled")

    def test_active_jobs_are_returned_oldest_first(self):
        jobs = [
            {
                "id": "new",
                "status": "running",
                "created_at": (self.now - timedelta(minutes=1)).isoformat(),
            },
            {
                "id": "old",
                "status": "pending",
                "created_at": (self.now - timedelta(minutes=5)).isoformat(),
            },
            {"id": "done", "status": "completed", "created_at": self.now.isoformat()},
        ]

        active = list_active_jobs(FakeSupabase(jobs))

        self.assertEqual([job["id"] for job in active], ["old", "new"])

    def test_only_the_active_job_index_maps_to_an_overlap_conflict(self):
        self.assertTrue(
            is_active_job_conflict(
                RuntimeError(
                    '23505 duplicate key violates unique constraint "job_queue_one_active"'
                )
            )
        )
        self.assertFalse(
            is_active_job_conflict(
                RuntimeError('23505 duplicate key violates unique constraint "job_queue_pkey"')
            )
        )

    def test_default_stale_window_exceeds_function_duration(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GENERATION_STALE_AFTER_SECONDS", None)
            self.assertEqual(get_stale_after_seconds(), 35 * 60)
        self.assertEqual(DEFAULT_STALE_AFTER_SECONDS, MIN_STALE_AFTER_SECONDS)

    def test_stale_window_cannot_be_configured_below_safe_minimum(self):
        with patch.dict(
            os.environ,
            {"GENERATION_STALE_AFTER_SECONDS": "900"},
        ):
            self.assertEqual(get_stale_after_seconds(), 35 * 60)

class ScheduledRunRecordTests(unittest.TestCase):
    """A run started outside the dashboard still belongs in the job history."""

    def setUp(self):
        self.config = {"model": "gpt-4o", "batch_size": 6, "source": "github-actions"}

    def test_scheduled_run_is_recorded_and_completed(self):
        jobs = []
        client = FakeSupabase(jobs)

        job_id = start_generation_job(client, self.config)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "running")
        self.assertEqual(jobs[0]["config"], self.config)
        self.assertIsNotNone(jobs[0]["started_at"])

        finished = finish_generation_job(
            client,
            job_id,
            result={"posts_generated": 6, "posts_attempted": 6},
        )

        self.assertTrue(finished)
        self.assertEqual(jobs[0]["status"], "completed")
        self.assertEqual(jobs[0]["result"]["posts_generated"], 6)
        self.assertIsNotNone(jobs[0]["completed_at"])

    def test_failed_scheduled_run_records_the_reason(self):
        jobs = []
        client = FakeSupabase(jobs)
        job_id = start_generation_job(client, self.config)

        finish_generation_job(client, job_id, error="Exa credits exhausted")

        self.assertEqual(jobs[0]["status"], "failed")
        self.assertEqual(jobs[0]["error"], "Exa credits exhausted")

    def test_registration_refuses_to_run_beside_an_active_job(self):
        jobs = [{
            "id": "dashboard-job",
            "status": "running",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }]

        with self.assertRaises(ActiveJobConflict):
            start_generation_job(FakeSupabase(jobs), self.config)

        self.assertEqual(len(jobs), 1)


class MissingPostDescriptionTests(unittest.TestCase):
    def test_errors_are_preferred_over_editorial_warnings(self):
        message = describe_missing_posts(
            ["All 12 article searches failed. First failure: 402 no credits"],
            ["Editorial validation warning for 'A story'"],
        )

        self.assertIn("402 no credits", message)
        self.assertNotIn("Editorial validation", message)

    def test_warnings_are_used_when_nothing_raised_an_error(self):
        message = describe_missing_posts(
            [], ["No candidate articles were available to select from"]
        )

        self.assertIn("No candidate articles", message)

    def test_message_stays_recognizable_without_diagnostics(self):
        self.assertEqual(
            describe_missing_posts([], []),
            "Generation completed without producing any usable blog posts",
        )


if __name__ == "__main__":
    unittest.main()
