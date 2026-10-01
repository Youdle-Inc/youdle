"""Tests that scheduled (GitHub Actions / CLI) runs appear in the job history."""

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch

from generate_blog_posts import finish_job_record, start_job_record


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, rows, action="select", payload=None):
        self.rows = rows
        self.action = action
        self.payload = payload
        self.filters = []

    def select(self, *_args, **_kwargs):
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append(lambda row, c=column, v=value: row.get(c) == v)
        return self

    def in_(self, column, values):
        allowed = set(values)
        self.filters.append(lambda row, c=column, a=allowed: row.get(c) in a)
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        matched = [row for row in self.rows if all(check(row) for check in self.filters)]
        if self.action == "update":
            for row in matched:
                row.update(deepcopy(self.payload))
        return Result(deepcopy(matched))


class Table:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *args, **kwargs):
        return Query(self.rows).select(*args, **kwargs)

    def update(self, payload):
        return Query(self.rows, action="update", payload=payload)

    def insert(self, payload):
        row = deepcopy(payload)
        row.setdefault("created_at", row.get("started_at"))
        self.rows.append(row)
        return Query([row])


class Supabase:
    def __init__(self, jobs):
        self.jobs = jobs

    def table(self, name):
        assert name == "job_queue", name
        return Table(self.jobs)


def test_scheduled_run_creates_a_job_row_the_dashboard_can_show():
    jobs = []
    client = Supabase(jobs)
    config = {"model": "gpt-4o", "batch_size": 10, "source": "github-actions"}

    with patch("supabase_storage.get_supabase_client", return_value=client):
        supabase, job_id, conflict = start_job_record(config)

    assert conflict is None
    assert supabase is client
    assert jobs[0]["id"] == job_id
    assert jobs[0]["status"] == "running"
    assert jobs[0]["config"]["source"] == "github-actions"

    finish_job_record(
        client,
        job_id,
        result={
            "posts_generated": 6,
            "errors": [],
            "warnings": [],
            "final_state": {"db_inserted": 6, "persistence_errors": []},
        },
    )

    assert jobs[0]["status"] == "completed"
    assert jobs[0]["result"] == {
        "posts_generated": 6,
        "posts_attempted": 6,
        "errors": [],
        "warnings": [],
    }


def test_scheduled_run_that_generated_nothing_is_recorded_as_failed():
    jobs = []
    client = Supabase(jobs)

    with patch("supabase_storage.get_supabase_client", return_value=client):
        _, job_id, _ = start_job_record({"model": "gpt-4o", "batch_size": 10})

    finish_job_record(
        client,
        job_id,
        result={
            "posts_generated": 0,
            "errors": ["All 12 article searches failed. First failure: 402 no credits"],
            "warnings": [],
            "final_state": {"final_posts": [], "db_inserted": 0},
        },
    )

    assert jobs[0]["status"] == "failed"
    assert "without producing any usable blog posts" in jobs[0]["error"]
    assert "402 no credits" in jobs[0]["error"]


def test_scheduled_run_defers_to_an_active_dashboard_job():
    started = datetime.now(timezone.utc).isoformat()
    jobs = [{
        "id": "dashboard-job",
        "status": "running",
        "created_at": started,
        "started_at": started,
    }]

    with patch("supabase_storage.get_supabase_client", return_value=Supabase(jobs)):
        supabase, job_id, conflict = start_job_record({"model": "gpt-4o"})

    assert supabase is None and job_id is None
    assert "already active" in conflict
    assert len(jobs) == 1


def test_untracked_run_proceeds_when_supabase_is_not_configured():
    with patch("supabase_storage.get_supabase_client", return_value=None):
        supabase, job_id, conflict = start_job_record({"model": "gpt-4o"})

    assert (supabase, job_id, conflict) == (None, None, None)
    # Must be a no-op rather than an error, so an untracked run still finishes.
    finish_job_record(None, None, result={"posts_generated": 3})
