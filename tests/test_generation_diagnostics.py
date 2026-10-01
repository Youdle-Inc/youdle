"""Tests that a run producing no posts reports why it produced none."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from zap_exa_ranker import main as rank_articles


def _exa_result(title, url, text, published_date):
    return SimpleNamespace(
        title=title,
        url=url,
        text=text,
        published_date=published_date,
    )


def test_provider_failure_is_reported_instead_of_an_empty_batch():
    """An exhausted or invalid Exa key must not look like a quiet news week."""

    def failing_search(*_args, **_kwargs):
        raise RuntimeError(
            "Request failed with status code 402: You have exceeded your credits limit"
        )

    with patch("zap_exa_ranker.init_exa_client", return_value=object()), patch(
        "zap_exa_ranker.execute_search", side_effect=failing_search
    ):
        result = rank_articles({"batch_size": 6, "search_days_back": 7})

    assert result["items"] == []
    assert "402" in result["error"]
    assert "exceeded your credits limit" in result["error"]
    assert len(result["search_errors"]) > 1


def test_partial_search_failure_still_returns_articles_and_records_the_gap():
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    grocery_results = [
        _exa_result(
            "Kroger announces new stores and lower grocery prices",
            "https://news.example.com/kroger-stores",
            "The supermarket announced store openings and price changes.",
            recent,
        )
    ]

    def flaky_search(_client, query_config, _start, _end):
        if query_config["category"] == "RECALL":
            raise RuntimeError("Request failed with status code 500")
        return grocery_results, query_config["category"], query_config.get("subcategory")

    with patch("zap_exa_ranker.init_exa_client", return_value=object()), patch(
        "zap_exa_ranker.execute_search", side_effect=flaky_search
    ):
        result = rank_articles({"batch_size": 6, "search_days_back": 7})

    assert result["items"], "usable grocery results must survive a failed recall query"
    assert "error" not in result
    assert any("status code 500" in message for message in result["search_errors"])


def test_search_node_warns_when_some_queries_failed():
    from blog_post_graph import search_articles_node

    search_results = {
        "items": [{"title": "A grocery story", "link": "https://news.example.com/a"}],
        "shoppers_items": [{"title": "A grocery story", "link": "https://news.example.com/a"}],
        "recall_items": [],
        "search_errors": ["Exa search failed for 'recalls': status code 500"],
    }

    with patch("blog_post_graph.search_articles_exa", return_value=search_results):
        result = search_articles_node({"batch_size": 6, "search_days_back": 7})

    assert "errors" not in result
    assert any("status code 500" in warning for warning in result["warnings"])


def test_search_node_warns_when_the_window_returned_nothing():
    from blog_post_graph import search_articles_node

    with patch(
        "blog_post_graph.search_articles_exa",
        return_value={"items": [], "shoppers_items": [], "recall_items": []},
    ):
        result = search_articles_node({"batch_size": 6, "search_days_back": 7})

    assert any("no candidates" in warning for warning in result["warnings"])


def test_selection_explains_an_empty_batch_after_deduplication():
    from blog_post_graph import select_articles_node

    used_url = "https://news.example.com/grocery-1"
    state = {
        "search_results": {
            "items": [{"title": "Reused story", "link": used_url, "category": "SHOPPERS"}],
            "shoppers_items": [
                {"title": "Reused story", "link": used_url, "category": "SHOPPERS"}
            ],
            "recall_items": [],
        },
        "processed_urls": {},
        "batch_size": 6,
    }

    class RecentPosts:
        def select(self, *_args, **_kwargs):
            return self

        def neq(self, *_args, **_kwargs):
            return self

        def gte(self, *_args, **_kwargs):
            return self

        def execute(self):
            return SimpleNamespace(data=[{"article_url": used_url}])

    supabase = SimpleNamespace(table=lambda _name: RecentPosts())

    with patch("blog_post_graph.get_supabase_client", return_value=supabase):
        result = select_articles_node(state)

    assert result["articles"] == []
    assert any("already used" in warning for warning in result["warnings"])


def test_assembly_reports_posts_the_model_returned_empty():
    from blog_post_graph import assemble_html_node

    state = {
        "generated_posts": [
            {
                "post_id": "abc123",
                "blog_post": "",
                "article": {"title": "Grocery prices keep climbing"},
            }
        ],
        "uploaded_urls": [],
        "proofread_corrections": {},
    }

    result = assemble_html_node(state)

    assert result["final_posts"] == []
    assert any(
        "returned no HTML" in error and "Grocery prices" in error
        for error in result["errors"]
    )
