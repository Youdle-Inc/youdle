"""Contract tests for the learning-system Supabase integration."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from example_store import ExampleStore
from feedback_collector import FeedbackCollector
from learning_memory import LearningMemory
from supabase_storage import SupabaseStorage


class RecordingQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.payload = None
        self.filters = []

    def insert(self, payload):
        self.payload = payload
        self.client.inserts.append((self.table_name, payload))
        return self

    def select(self, *_args, **_kwargs):
        self.client.selects.append(self.table_name)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        self.client.filters.append((self.table_name, column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self.payload is not None:
            if self.client.empty_writes:
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=[{"id": "saved-row", **self.payload}])
        rows = list(self.client.rows.get(self.table_name, []))
        rows = [
            row for row in rows
            if all(row.get(column) == value for column, value in self.filters)
        ]
        return SimpleNamespace(data=rows)


class RecordingClient:
    def __init__(self, rows=None, *, empty_writes=False):
        self.rows = rows or {}
        self.empty_writes = empty_writes
        self.inserts = []
        self.selects = []
        self.filters = []

    def table(self, table_name):
        return RecordingQuery(self, table_name)


def make_storage(client):
    storage = object.__new__(SupabaseStorage)
    storage.client = client
    return storage


def test_detailed_feedback_uses_blog_feedback_and_normalizes_overall():
    client = RecordingClient()
    storage = make_storage(client)

    result = storage.save_feedback(
        blog_post_id="local-post-id",
        feedback_type="overall",
        score=4,
        comments="Useful",
        approved=True,
    )

    assert result["success"] is True
    table_name, payload = client.inserts[0]
    assert table_name == "blog_feedback"
    assert payload["feedback_type"] == "general"


def test_feedback_patterns_combine_detailed_and_dashboard_feedback():
    client = RecordingClient(rows={
        "blog_feedback": [
            {"feedback_type": "overall", "score": 4, "comments": "One"},
        ],
        "feedback": [
            {"feedback_type": "general", "rating": 2, "comment": "Two"},
        ],
    })
    storage = make_storage(client)

    patterns = storage.get_feedback_patterns(min_count=2)

    assert client.selects == ["blog_feedback", "feedback"]
    assert patterns == [{
        "type": "general",
        "count": 2,
        "avg_score": 3,
        "comments": ["One", "Two"],
    }]


def test_feedback_patterns_are_scoped_by_category():
    client = RecordingClient(rows={
        "blog_feedback": [
            {"category": "recall", "feedback_type": "tone", "score": 2},
            {"category": "shoppers", "feedback_type": "tone", "score": 5},
        ],
        "feedback": [
            {"category": "recall", "feedback_type": "tone", "rating": 4},
        ],
    })
    storage = make_storage(client)

    patterns = storage.get_feedback_patterns(category="RECALL", min_count=2)

    assert client.filters == [
        ("blog_feedback", "category", "recall"),
        ("feedback", "category", "recall"),
    ]
    assert patterns[0]["count"] == 2
    assert patterns[0]["avg_score"] == 3


def test_feedback_pattern_database_outage_is_not_reported_as_no_feedback():
    class BrokenClient:
        def table(self, _table_name):
            raise RuntimeError("database unavailable")

    storage = make_storage(BrokenClient())

    with pytest.raises(RuntimeError, match="Could not load feedback patterns"):
        storage.get_feedback_patterns()


def test_learning_insight_alias_and_unknown_values_are_schema_safe():
    client = RecordingClient()
    storage = make_storage(client)

    problem_result = storage.save_learning_insight("problem", "Low approval")
    unknown_result = storage.save_learning_insight("new_kind", "Unclassified")

    assert problem_result["success"] is True
    assert unknown_result["success"] is True
    assert client.inserts[0][1]["insight_type"] == "common_mistake"
    assert client.inserts[1][1]["insight_type"] == "general"


def test_empty_write_response_is_reported_as_failure():
    storage = make_storage(RecordingClient(empty_writes=True))

    feedback_result = storage.save_feedback("post", "general", 3)
    example_result = storage.save_blog_example(
        "https://example.com",
        "Example",
        "<p>Example</p>",
        "shoppers",
    )
    insight_result = storage.save_learning_insight("general", "Example")

    assert feedback_result["success"] is False
    assert example_result["success"] is False
    assert insight_result["success"] is False


def test_example_store_and_learning_memory_default_to_storage_wrapper():
    wrapper = object()

    with patch("example_store.get_supabase_storage", return_value=wrapper):
        assert ExampleStore().client is wrapper
    with patch("learning_memory.get_supabase_storage", return_value=wrapper):
        assert LearningMemory().client is wrapper


def test_feedback_collector_propagates_partial_persistence_failure():
    wrapper = MagicMock()
    wrapper.save_feedback.return_value = {"success": False, "error": "feedback failed"}
    collector = FeedbackCollector(wrapper)
    collector.example_store.store_example = MagicMock(return_value={"success": True})

    result = collector.collect_feedback(
        blog_post_id="post",
        blog_post_html="<p>Post</p>",
        article_data={"category": "SHOPPERS"},
        score=4,
        approved=True,
        feedback_type="overall",
    )

    assert result["success"] is False
    assert result["feedback_stored"] is False
    assert result["example_stored"] is True
    assert result["errors"] == ["feedback failed"]
    assert wrapper.save_feedback.call_args.kwargs["feedback_type"] == "general"
    assert wrapper.save_feedback.call_args.kwargs["category"] == "shoppers"


def test_learning_memory_uses_valid_low_score_insight_and_reports_failure():
    wrapper = MagicMock()
    wrapper.save_learning_insight.return_value = {
        "success": False,
        "error": "insight failed",
    }
    memory = LearningMemory(wrapper)

    result = memory.save_session_memory(
        "shoppers",
        {
            "approval_rate": 25,
            "new_insights": [{"type": "unexpected", "description": "New"}],
        },
    )

    assert result["success"] is False
    assert result["errors"] == ["insight failed", "insight failed"]
    insight_types = [
        call.kwargs["insight_type"]
        for call in wrapper.save_learning_insight.call_args_list
    ]
    assert insight_types == ["common_mistake", "general"]


def test_legacy_orchestrator_shares_one_storage_wrapper():
    wrapper = object()

    with patch("blog_post_generator.get_supabase_storage", return_value=wrapper), \
         patch("blog_post_generator.BlogPostGenerator"), \
         patch("blog_post_generator.get_image_generator"), \
         patch("blog_post_generator.ReflectionAgent"), \
         patch("blog_post_generator.ExampleStore") as example_store, \
         patch("blog_post_generator.PromptRefiner") as prompt_refiner, \
         patch("blog_post_generator.LearningMemory") as learning_memory, \
         patch("blog_post_generator.os.makedirs"):
        from blog_post_generator import BlogPostOrchestrator

        orchestrator = BlogPostOrchestrator()

    assert orchestrator.supabase is wrapper
    example_store.assert_called_once_with(wrapper)
    prompt_refiner.assert_called_once_with(wrapper)
    learning_memory.assert_called_once_with(wrapper)
