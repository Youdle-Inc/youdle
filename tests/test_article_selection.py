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


def test_topical_shoppers_queries_use_the_us_allowlist():
    """Exa takes include_domains or exclude_domains, never both.

    The split is therefore per query: the topical searches are restricted to
    curated US newsrooms, and two broad searches stay open so a source the
    allowlist does not name can still be found.
    """
    from zap_exa_ranker import SHOPPERS_QUERIES, US_SHOPPERS_DOMAINS

    allowlisted = [q for q in SHOPPERS_QUERIES if "include_domains" in q]
    open_web = [q for q in SHOPPERS_QUERIES if "include_domains" not in q]

    assert len(allowlisted) == 7
    assert len(open_web) == 2
    for query in allowlisted:
        assert query["include_domains"] == US_SHOPPERS_DOMAINS
        assert "exclude_domains" not in query, "Exa rejects both filters together"
    for query in open_web:
        assert query["exclude_domains"], "an open query still blocks non-US outlets"


def test_recall_queries_stay_locked_to_official_sources():
    from zap_exa_ranker import RECALL_QUERIES

    for query in RECALL_QUERIES:
        assert set(query["include_domains"]) <= {"fda.gov", "fsis.usda.gov"}


def test_trusted_domain_test_matches_subdomains_but_not_lookalikes():
    from zap_exa_ranker import is_trusted_us_domain

    assert is_trusted_us_domain("https://www.usatoday.com/story/1")
    assert is_trusted_us_domain("https://markets.businessinsider.com/news/x")
    assert is_trusted_us_domain("http://CNBC.COM/2026/09/30/groceries")
    assert not is_trusted_us_domain("https://akm.ru/eng/news/kroger")
    assert not is_trusted_us_domain("https://usatoday.com.content-farm.net/x")
    assert not is_trusted_us_domain("")
    assert not is_trusted_us_domain(None)


def test_a_curated_newsroom_is_ranked_above_an_unlisted_aggregator():
    """Ranking must not hand a slot to a content farm because it wrote less.

    length_score peaks at 200-600 characters, so a thin rewrite scores ~100
    points above full reporting. Trust is therefore a tier, not a bonus.
    """
    recent = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    grocery_results = [
        _exa_result(
            "Kroger acquires Giant Eagle supermarket chain",
            "https://akm.ru/eng/news/kroger-giant-eagle",
            "A short rewrite of someone else's reporting. " * 6,
            recent,
        ),
        _exa_result(
            "Kroger acquires Giant Eagle in a $2.3B deal",
            "https://www.usatoday.com/story/money/2026/09/30/kroger-giant-eagle",
            "Full original reporting running well past the length the scorer rewards. " * 30,
            recent,
        ),
    ]

    def fake_search(_client, query_config, _start_date, _end_date):
        category = query_config["category"]
        results = grocery_results if category == "SHOPPERS" else []
        return results, category, query_config.get("subcategory")

    with patch("zap_exa_ranker.init_exa_client", return_value=object()), patch(
        "zap_exa_ranker.execute_search", side_effect=fake_search
    ):
        result = rank_articles({"batch_size": 10, "search_days_back": 7})

    ranked = result["shoppers_items"]
    assert [item["trusted_source"] for item in ranked] == [True, False]
    assert "usatoday.com" in ranked[0]["link"]
    # The aggregator still scores higher; it is ranked below on trust alone.
    assert ranked[1]["score"] > ranked[0]["score"]


def test_sponsored_placements_on_trusted_domains_are_rejected():
    """A domain allowlist cannot catch advertising a real newsroom carries."""
    from zap_exa_ranker import is_sponsored_placement

    advertorial = {
        "link": "https://www.usatoday.com/press-release/story/45414/"
                "extenze-reviews-leading-edge-health-publishes-2026-label-literacy-guide/"
    }
    editorial = {
        "link": "https://www.usatoday.com/story/money/personal-finance/2026/09/27/"
                "snap-changes-october-cola-cuts/91938378007/"
    }

    assert is_sponsored_placement(advertorial)
    assert not is_sponsored_placement(editorial)
    assert not is_sponsored_placement({"link": ""})


def test_ranked_pool_excludes_advertorials_from_curated_domains():
    recent = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    grocery_results = [
        _exa_result(
            "ExtenZe Reviews: Leading Edge Health Publishes 2026 Label-Literacy Guide",
            "https://www.usatoday.com/press-release/story/45414/extenze-reviews/",
            "A supplement advertorial syndicated under a newsroom domain. " * 5,
            recent,
        ),
        _exa_result(
            "SNAP checks rise Oct 1, but new rules may mean benefit cuts ahead",
            "https://www.usatoday.com/story/money/personal-finance/2026/09/27/snap-changes/",
            "Reporting on benefit changes that affect grocery budgets. " * 8,
            recent,
        ),
    ]

    def fake_search(_client, query_config, _start_date, _end_date):
        category = query_config["category"]
        return (grocery_results if category == "SHOPPERS" else []), category, None

    with patch("zap_exa_ranker.init_exa_client", return_value=object()), patch(
        "zap_exa_ranker.execute_search", side_effect=fake_search
    ):
        result = rank_articles({"batch_size": 10, "search_days_back": 7})

    links = [item["link"] for item in result["shoppers_items"]]
    assert len(links) == 1
    assert "press-release" not in links[0]
