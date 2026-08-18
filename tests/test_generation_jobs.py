"""Behavior tests for the stabilized generation endpoint and task runner."""

import asyncio
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from api.routes.generate import (
    GenerationConfig,
    run_generation_endpoint,
    run_generation_task,
)


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, client, table_name, action="select", payload=None):
        self.client = client
        self.table_name = table_name
        self.action = action
        self.payload = payload
        self.filters = []
        self.single_result = False
        self.ordering = None

    @property
    def rows(self):
        return self.client.tables.setdefault(self.table_name, [])

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self.action = "insert"
        self.payload = payload
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

    def order(self, column, desc=False):
        self.ordering = (column, desc)
        return self

    def single(self):
        self.single_result = True
        return self

    def execute(self):
        if self.action == "insert":
            record = deepcopy(self.payload)
            record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            self.rows.append(record)
            return Result([deepcopy(record)])

        matched = [row for row in self.rows if all(check(row) for check in self.filters)]
        if self.ordering:
            column, desc = self.ordering
            matched.sort(key=lambda row: row.get(column) or "", reverse=desc)
        if self.action == "update":
            for row in matched:
                row.update(deepcopy(self.payload))
        copied = deepcopy(matched)
        if self.single_result:
            return Result(copied[0] if copied else None)
        return Result(copied)


class Table:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def select(self, *args, **kwargs):
        return Query(self.client, self.name).select(*args, **kwargs)

    def insert(self, payload):
        return Query(self.client, self.name, "insert", payload)

    def update(self, payload):
        return Query(self.client, self.name, "update", payload)


class Supabase:
    def __init__(self, jobs=None):
        self.tables = {"job_queue": jobs or [], "blog_posts": []}

    def table(self, name):
        return Table(self, name)


def test_generation_config_rejects_runaway_values():
    with pytest.raises(ValidationError):
        GenerationConfig(batch_size=0)
    with pytest.raises(ValidationError):
        GenerationConfig(batch_size=11)
    with pytest.raises(ValidationError):
        GenerationConfig(search_days_back=91)


def test_endpoint_rejects_an_existing_active_job():
    jobs = [{
        "id": "active-job",
        "status": "running",
        "config": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }]
    client = Supabase(jobs)
    background_tasks = BackgroundTasks()

    with patch("supabase_storage.get_supabase_client", return_value=client):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(run_generation_endpoint(background_tasks, GenerationConfig()))

    assert raised.value.status_code == 409
    assert "active-job" in raised.value.detail
    assert background_tasks.tasks == []


def test_endpoint_expires_stale_job_then_accepts_a_new_one():
    old_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    jobs = [{
        "id": "stale-job",
        "status": "running",
        "config": {},
        "created_at": old_timestamp,
        "started_at": old_timestamp,
    }]
    client = Supabase(jobs)
    background_tasks = BackgroundTasks()

    with patch("supabase_storage.get_supabase_client", return_value=client):
        response = asyncio.run(
            run_generation_endpoint(background_tasks, GenerationConfig(batch_size=2))
        )

    assert jobs[0]["status"] == "failed"
    assert response.status == "pending"
    assert len(background_tasks.tasks) == 1
    assert len(client.tables["job_queue"]) == 2


def test_cancelled_before_claim_never_calls_generator():
    jobs = [{
        "id": "cancelled-job",
        "status": "cancelled",
        "config": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }]
    client = Supabase(jobs)
    generator = MagicMock()
    fake_generator_module = SimpleNamespace(run_generation=generator)

    with patch("supabase_storage.get_supabase_client", return_value=client), patch.dict(
        sys.modules,
        {"blog_post_generator": fake_generator_module},
    ):
        run_generation_task("cancelled-job", {})

    generator.assert_not_called()
    assert jobs[0]["status"] == "cancelled"


def test_cancellation_during_generation_is_not_overwritten():
    jobs = [{
        "id": "job-1",
        "status": "pending",
        "config": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }]
    client = Supabase(jobs)

    def generate(**_kwargs):
        jobs[0]["status"] = "cancelled"
        return {
            "final_state": {
                "final_posts": [{"title": "Generated"}],
                "db_inserted": 1,
                "persistence_errors": [],
            },
            "errors": [],
        }

    fake_generator_module = SimpleNamespace(run_generation=generate)
    with patch("supabase_storage.get_supabase_client", return_value=client), patch.dict(
        sys.modules,
        {"blog_post_generator": fake_generator_module},
    ):
        run_generation_task("job-1", {})

    assert jobs[0]["status"] == "cancelled"


def test_zero_output_is_reported_as_failed():
    jobs = [{
        "id": "job-1",
        "status": "pending",
        "config": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }]
    client = Supabase(jobs)
    fake_generator_module = SimpleNamespace(
        run_generation=lambda **_kwargs: {
            "final_state": {
                "final_posts": [],
                "db_inserted": 0,
                "persistence_errors": [],
            },
            "errors": ["No safe generated HTML remained after assembly"],
        }
    )

    with patch("supabase_storage.get_supabase_client", return_value=client), patch.dict(
        sys.modules,
        {"blog_post_generator": fake_generator_module},
    ):
        run_generation_task("job-1", {})

    assert jobs[0]["status"] == "failed"
    assert "without producing any usable blog posts" in jobs[0]["error"]
    assert "No safe generated HTML remained" in jobs[0]["error"]
