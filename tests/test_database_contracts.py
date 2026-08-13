"""Regression tests for database column and failure-reporting contracts."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import MockBloggerClient, MockSupabaseClient


class _RecentPostQuery:
    def __init__(self, rows):
        self.rows = rows
        self.selected_column = None
        self.cutoff = None

    def select(self, column):
        self.selected_column = column
        return self

    def gte(self, column, cutoff):
        assert column == "created_at"
        self.cutoff = cutoff
        return self

    def neq(self, column, value):
        assert column == "article_url"
        assert value == ""
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _RecentPostClient:
    def __init__(self, rows):
        self.query = _RecentPostQuery(rows)

    def table(self, table_name):
        assert table_name == "blog_posts"
        return self.query


def test_cross_run_dedup_uses_article_url_and_skips_recent_source():
    from blog_post_graph import select_articles_node

    recent_url = "https://example.com/already-used"
    fresh_url = "https://example.com/fresh"
    client = _RecentPostClient([{"article_url": recent_url}])
    state = {
        "search_results": {
            "items": [
                {"link": recent_url, "category": "SHOPPERS"},
                {"link": fresh_url, "category": "SHOPPERS"},
            ],
            "recall_items": [],
        },
        "processed_urls": {},
        "batch_size": 2,
    }

    with patch("blog_post_graph.get_supabase_client", return_value=client):
        result = select_articles_node(state)

    assert client.query.selected_column == "article_url"
    assert [post["link"] for post in result["articles"]] == [fresh_url]


def test_blogger_draft_updates_exact_saved_database_row():
    from blog_post_graph import push_drafts_to_blogger_node

    supabase = MockSupabaseClient()
    # If the implementation falls back to a title lookup, it would choose this
    # wrong older row. saved_post_ids must take precedence.
    supabase.table("blog_posts").configure_select([{"id": "old-row"}])
    blogger = MockBloggerClient(configured=True)
    state = {
        "job_id": "job-1",
        "db_inserted": 1,
        "saved_post_ids": ["new-row"],
        "final_posts": [
            {
                "title": "A title that already exists",
                "html": "<p>New content</p>",
                "category": "SHOPPERS",
            }
        ],
    }

    with patch("blog_post_graph.get_supabase_client", return_value=supabase), patch(
        "blogger_client.get_blogger_client", return_value=blogger
    ):
        push_drafts_to_blogger_node(state)

    updates = supabase.get_table("blog_posts").updates
    assert len(updates) == 1
    assert updates[0]["filters"] == {"id": "new-row"}


def test_publish_status_reports_database_errors_as_failure():
    from check_blog_status import check_publish_status

    class BrokenClient:
        def table(self, _name):
            raise RuntimeError("database unavailable")

    result = check_publish_status(supabase=BrokenClient())

    assert result["success"] is False
    assert "database unavailable" in result["error"]


def test_fetch_published_posts_does_not_turn_query_error_into_empty_list():
    from datetime import datetime, timezone

    from fetch_published_posts import fetch_published_posts

    class BrokenClient:
        def table(self, _name):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        fetch_published_posts(BrokenClient(), datetime.now(timezone.utc))


def test_stats_returns_503_when_database_query_fails():
    from api.main import app

    class BrokenClient:
        def table(self, _name):
            raise RuntimeError("database unavailable")

    with patch("supabase_storage.get_supabase_client", return_value=BrokenClient()), patch(
        "api.main.reconcile_stale_jobs", return_value=[]
    ):
        response = TestClient(app).get("/api/stats")

    assert response.status_code == 503
    assert response.json()["detail"] == "Database statistics are temporarily unavailable"


def test_review_endpoint_delegates_one_atomic_idempotent_rpc():
    from api.main import app

    class RpcCall:
        def __init__(self, data):
            self.data = data

        def execute(self):
            return SimpleNamespace(data=self.data)

    class RpcClient:
        def __init__(self):
            self.calls = []

        def rpc(self, name, parameters):
            self.calls.append((name, parameters))
            return RpcCall({
                "post": {"id": "00000000-0000-0000-0000-000000000001", "status": "reviewed"},
                "feedback": {"rating": 4, "feedback_type": "content"},
                "replayed": False,
            })

    supabase = RpcClient()
    submission_id = "00000000-0000-0000-0000-000000000002"

    with patch("supabase_storage.get_supabase_client", return_value=supabase):
        response = TestClient(app).post(
            "/api/generate/posts/00000000-0000-0000-0000-000000000001/review",
            json={
                "rating": 4,
                "comment": "Clear and useful",
                "feedback_type": "content",
                "mark_reviewed": True,
                "submission_id": submission_id,
            },
        )

    assert response.status_code == 200
    assert len(supabase.calls) == 1
    name, parameters = supabase.calls[0]
    assert name == "submit_post_review"
    assert parameters == {
        "p_post_id": "00000000-0000-0000-0000-000000000001",
        "p_rating": 4,
        "p_comment": "Clear and useful",
        "p_feedback_type": "content",
        "p_mark_reviewed": True,
        "p_submission_id": submission_id,
    }
    assert response.json()["post"]["status"] == "reviewed"


def test_missing_maybe_single_row_returns_404_instead_of_500():
    from api.main import app

    class MissingQuery:
        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def maybe_single(self):
            return self

        def execute(self):
            return None

    class MissingClient:
        def table(self, _name):
            return MissingQuery()

    with patch("supabase_storage.get_supabase_client", return_value=MissingClient()):
        response = TestClient(app).get(
            "/api/generate/posts/00000000-0000-0000-0000-000000000001"
        )

    assert response.status_code == 404


def test_review_endpoint_rejects_invalid_feedback_before_database_access():
    from api.main import app

    with patch("supabase_storage.get_supabase_client") as get_client:
        response = TestClient(app).post(
            "/api/generate/posts/post-1/review",
            json={
                "rating": 9,
                "feedback_type": "not-a-real-type",
                "mark_reviewed": True,
            },
        )

    assert response.status_code == 422
    get_client.assert_not_called()
