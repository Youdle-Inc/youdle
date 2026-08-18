"""Regression tests for the weekly grocery-news/recall output contract."""

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


def test_ranker_keeps_recall_subjects_out_of_regular_grocery_results():
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    grocery_results = [
        _exa_result(
            "Kroger announces new stores and lower grocery prices",
            "https://news.example.com/kroger-stores",
            "The supermarket announced store openings and price changes.",
            recent,
        ),
        _exa_result(
            "A new snack flavor arrives in supermarkets",
            "https://news.example.com/new-snack",
            "The packaged food launch reaches grocery shelves this week.",
            recent,
        ),
        _exa_result(
            "Families change how they budget for groceries",
            "https://news.example.com/grocery-budget",
            "Shoppers compare prices at several supermarket chains.",
            recent,
        ),
        _exa_result(
            "Cyclospora outbreak linked to contaminated produce",
            "https://news.example.com/cyclospora-outbreak",
            "The foodborne illness investigation includes recall information.",
            recent,
        ),
        _exa_result(
            "An old grocery shopping guide",
            "https://news.example.com/old-guide",
            "This evergreen guide is outside the requested news window.",
            old,
        ),
        _exa_result(
            "Facebook",
            "https://facebook.com/post/1",
            "A social media result without a usable article headline.",
            recent,
        ),
    ]
    recall_results = [
        _exa_result(
            "FDA announces a prepared-food recall",
            "https://fda.gov/safety/recall-1",
            "The recalled product may contain an undeclared allergen.",
            recent,
        ),
        _exa_result(
            "Public Health Information System",
            "https://fsis.usda.gov/inspection/phis",
            "A general agency information page, not a product recall.",
            recent,
        ),
    ]

    def fake_search(_client, query_config, _start_date, _end_date):
        category = query_config["category"]
        results = grocery_results if category == "SHOPPERS" else recall_results
        return results, category, query_config.get("subcategory")

    with patch("zap_exa_ranker.init_exa_client", return_value=object()), patch(
        "zap_exa_ranker.execute_search", side_effect=fake_search
    ):
        result = rank_articles({"batch_size": 10, "search_days_back": 7})

    regular_items = [
        item for item in result["items"] if item["category"] == "SHOPPERS"
    ]
    assert [item["title"] for item in regular_items] == [
        "Kroger announces new stores and lower grocery prices",
        "A new snack flavor arrives in supermarkets",
        "Families change how they budget for groceries",
    ]
    assert sum(item["category"] == "RECALL" for item in result["items"]) == 1
    assert [item["title"] for item in result["recall_items"]] == [
        "FDA announces a prepared-food recall"
    ]


def test_selection_reserves_exactly_one_output_slot_for_recall_roundup():
    from blog_post_graph import generate_posts_node, select_articles_node

    shoppers = [
        {
            "title": f"Grocery story {index}",
            "description": "Current grocery reporting",
            "link": f"https://news.example.com/grocery-{index}",
            "category": "SHOPPERS",
        }
        for index in range(12)
    ]
    recalls = [
        {
            "title": f"Official recall {index}",
            "description": "Official recall details",
            "link": f"https://fda.gov/recall-{index}",
            "category": "RECALL",
        }
        for index in range(8)
    ]
    state = {
        "search_results": {
            "items": shoppers[:10],
            "shoppers_items": shoppers,
            "recall_items": recalls,
        },
        "processed_urls": {},
        "batch_size": 10,
    }

    with patch("blog_post_graph.get_supabase_client", return_value=None):
        selected = select_articles_node(state)

    assert len(selected["shoppers_articles"]) == 9
    assert len(selected["recall_articles"]) == 5

    generation_state = {
        "articles": selected["articles"],
        "posts_needing_regeneration": [],
        "shoppers_context": {},
        "recall_context": {},
        "model": "test-model",
    }

    with patch("blog_post_graph.BlogPostGenerator") as generator_class:
        generator_class.return_value.generate_with_reflection.side_effect = lambda **_: {
            "blog_post": "<div>Generated post</div>",
            "reflection": {"is_valid": True},
            "attempts": 1,
            "success": True,
        }
        generated = generate_posts_node(generation_state)["generated_posts"]

    assert sum(post["category"] == "shoppers" for post in generated) == 9
    assert sum(post["category"] == "recall" for post in generated) == 1
    roundup = next(post for post in generated if post["category"] == "recall")
    assert roundup["article"]["is_roundup"] is True
    assert len(roundup["article"]["source_articles"]) == 5


def test_generation_configuration_enforces_a_seven_day_maximum():
    from pydantic import ValidationError
    from api.routes.generate import GenerationConfig

    assert GenerationConfig().search_days_back == 7
    assert GenerationConfig(search_days_back=7).search_days_back == 7

    try:
        GenerationConfig(search_days_back=8)
    except ValidationError:
        pass
    else:
        raise AssertionError("Generation accepted articles older than seven days")
