"""Behavior tests for learning metrics that are not available until review."""

from unittest.mock import MagicMock

from learning_memory import LearningMemory


def test_unknown_approval_rate_does_not_create_false_low_score_insight():
    storage = MagicMock()
    memory = LearningMemory(storage)

    result = memory.store_session_metrics(
        "shoppers",
        {"posts_generated": 5, "approval_rate": None},
    )

    assert result["success"] is True
    assert result["insight_stored"] is False
    storage.save_learning_insight.assert_not_called()


def test_performance_summary_ignores_sessions_without_review_data():
    memory = LearningMemory(MagicMock())
    memory._local_memory["metrics"] = [
        {"category": "shoppers", "metrics": {"approval_rate": None}},
        {"category": "shoppers", "metrics": {"approval_rate": 80}},
    ]

    summary = memory.get_performance_summary("shoppers")

    assert summary["sessions"] == 1
    assert summary["avg_approval_rate"] == 80
