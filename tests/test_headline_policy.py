"""Headline rule regressions: no paid model or image calls."""
from collections import Counter
from unittest.mock import patch

import pytest

from headline_policy import (
    extract_headline,
    pattern_for_shopper,
    validate_headline,
)
from prompts import RECALL_BLOG_PROMPT, SHOPPERS_BLOG_PROMPT


def test_headline_is_under_fourteen_words_and_pays_off_in_prompt():
    assert "Under 14 words" in SHOPPERS_BLOG_PROMPT
    assert "first" in SHOPPERS_BLOG_PROMPT.lower()
    assert "second" in SHOPPERS_BLOG_PROMPT.lower()
    assert "under 14 words" in RECALL_BLOG_PROMPT.lower()
    assert "Never invent a" in RECALL_BLOG_PROMPT


def test_twelve_word_recall_headline_is_allowed():
    headline = "Listeria alert. Undeclared peanuts. Six foods to check in your fridge tonight."
    assert validate_headline(headline) == []


@pytest.mark.parametrize(
    ("headline", "error"),
    [
        ("The cost of food has changed for a lot of families this year and everyone is worried", "maximum is 13"),
        ("Beef prices rose — but here's what's next", "em or en dash"),
        ("Grocery bills are rising!", "exclamation"),
        ("USDA predicts food prices will rise", "all-caps"),
        ("Prices in Memphis are rising again", "geographic reference"),
        ("Prices are rising across New York", "geographic reference"),
        ("You won't believe what this food costs", "Banned"),
        ("This one trick changes grocery bills", "Banned"),
        ("Grocery workers SLAM store changes", "all-caps"),
        ("The Cart Is Getting More Expensive", "title case"),
    ],
)
def test_invalid_headlines_receive_specific_warnings(headline, error):
    assert error.lower() in " ".join(validate_headline(headline)).lower()


def test_store_names_allowed_only_when_source_is_about_the_company():
    assert validate_headline(
        "Walmart changes its checkout rules. Here's what happens next",
        source_title="Walmart changes its checkout rules nationwide",
    ) == []
    assert "not supported" in " ".join(
        validate_headline(
            "Walmart changes its checkout rules. Here's what happens next",
            source_title="Food prices grew over the summer",
        )
    )


def test_six_weekly_shopper_slots_get_six_distinct_structures():
    six = [pattern_for_shopper(i) for i in range(6)]
    assert len(set(six)) == 6
    assert max(Counter(six).values()) <= 2
    assert pattern_for_shopper(6) == pattern_for_shopper(0)


def test_generated_h2_extracts_entities_and_ignores_formatting():
    html = '<div><h2>Beef prices rose. Here&#39;s the <strong>cut</strong> holding steady</h2></div>'
    assert extract_headline(html) == "Beef prices rose. Here's the cut holding steady"


def test_final_published_title_matches_actual_h2_not_outside_source_title():
    from blog_post_graph import assemble_html_node

    data = {
        "generated_posts": [
            {
                "post_id": "published-headline-test",
                "blog_post": (
                    '<div><img src="{IMAGE_HERE}" alt="article image"/>'
                    "<h2>Beef prices are rising. Here's the cut holding steady</h2>"
                    "<p>Here's the cut, in the first paragraph.</p>"
                    "<ul><li>Shopper tip</li></ul>"
                    "</div>"
                ),
                "article": {
                    "title": "Original AP wire headline that is not suitable for shoppers",
                    "link": "https://example.com/pricing",
                    "category": "SHOPPERS",
                },
                "category": "shoppers",
            }
        ],
        "uploaded_urls": [
            {"post_id": "published-headline-test", "url": "https://i.ibb.co/photos/photo.jpg"}
        ],
        "proofread_corrections": {},
    }

    with patch("blog_post_graph.ReflectionAgent") as validator:
        validator.return_value.reflect.return_value = {"is_valid": True}
        result = assemble_html_node(data)

    assert len(result["final_posts"]) == 1
    assert result["final_posts"][0]["title"] == (
        "Beef prices are rising. Here's the cut holding steady"
    )
    assert result["final_posts"][0]["article"]["title"].startswith("Original AP")


def test_reflection_includes_deterministic_headline_mistakes():
    from reflection_agent import ReflectionAgent

    article = (
        '<div><img src="{IMAGE_HERE}" alt="article image"/>'
        "<h2>Prices in Memphis are SCARY!</h2>"
        "<p>Grocery information.</p><ul><li>Compare packages.</li></ul></div>"
    )
    issues = ReflectionAgent().check_common_mistakes(article)
    assert any("geographic reference" in issue for issue in issues)
    assert any("exclamation" in issue for issue in issues)


def test_six_generated_shopper_prompts_receive_distinct_headline_shapes():
    from blog_post_graph import generate_posts_node

    state = {
        "model": "test-model",
        "shoppers_context": {"prompt_additions": "Use the official price report."},
        "recall_context": {},
        "articles": [
            {
                "title": f"Everyday grocery story {number}",
                "content": "Verified consumer grocery source reporting.",
                "link": f"https://example.com/story-{number}",
                "category": "SHOPPERS",
            }
            for number in range(6)
        ],
    }

    generated = {
        "blog_post": '<div><img src="{IMAGE_HERE}" alt="article image"/>'
                     "<h2>Food prices are changing. Here's what matters next</h2></div>",
        "reflection": {"is_valid": True},
        "attempts": 1,
        "success": True,
    }

    with patch("blog_post_graph.BlogPostGenerator") as generator_class:
        generator = generator_class.return_value
        generator.generate_with_reflection.side_effect = lambda **kwargs: generated.copy()
        result = generate_posts_node(state)
        calls = generator.generate_with_reflection.call_args_list

    assert len(result["generated_posts"]) == 6
    assert len(calls) == 6
    prompts = [call.kwargs["prompt_additions"] for call in calls]
    assert len(set(prompts)) == 6
    assert all("Use the official price report." in prompt for prompt in prompts)


def test_model_reflection_rejects_headline_without_early_payoff():
    from unittest.mock import MagicMock
    from langchain_blog_agent import BlogPostGenerator

    generator = object.__new__(BlogPostGenerator)
    generator.reflection_chain = MagicMock()
    generator.reflection_chain.invoke.return_value = (
        '{"is_valid":true,"headline_payoff_in_first_two_paragraphs":false,'
        '"headline_truthful_and_compliant":true,"issues":[],"suggestions":[]}'
    )

    result = generator.reflect_on_post("<div><h2>Example</h2></div>")
    assert result["is_valid"] is False
    assert any("first two paragraphs" in issue for issue in result["issues"])



def test_model_reflection_rejects_missing_headline_payoff_keys():
    from unittest.mock import MagicMock
    from langchain_blog_agent import BlogPostGenerator

    generator = object.__new__(BlogPostGenerator)
    generator.reflection_chain = MagicMock()
    generator.reflection_chain.invoke.return_value = (
        '{"is_valid":true,"issues":[],"suggestions":[]}'
    )

    result = generator.reflect_on_post("<div><h2>Example</h2></div>")
    assert result["is_valid"] is False
    assert any("first two paragraphs" in issue for issue in result["issues"])


def test_final_draft_flags_failed_payoff_review_even_if_structure_passes():
    from blog_post_graph import assemble_html_node

    state = {
        "generated_posts": [{
            "post_id": "held-back-detail",
            "blog_post": (
                '<div><img src="{IMAGE_HERE}" alt="article image"/>'
                "<h2>Egg prices are rising. Here's what changed</h2>"
                "<p>Price update without explaining the promised detail.</p>"
                "<ul><li>Compare prices</li></ul></div>"
            ),
            "article": {
                "title": "Source report on grocery prices",
                "link": "https://example.com/report",
            },
            "category": "shoppers",
            "reflection": {
                "is_valid": False,
                "headline_payoff_in_first_two_paragraphs": False,
                "headline_truthful_and_compliant": True,
            },
        }],
        "uploaded_urls": [{
            "post_id": "held-back-detail",
            "url": "https://i.ibb.co/test/eggs.jpg",
        }],
        "proofread_corrections": {},
    }
    with patch("blog_post_graph.ReflectionAgent") as validator:
        validator.return_value.reflect.return_value = {"is_valid": True}
        outcome = assemble_html_node(state)

    assert len(outcome["final_posts"]) == 1
    review = outcome["final_posts"][0]["final_validation"]
    assert review["is_valid"] is False
    assert any("payoff" in issue for issue in review["issues"])
    assert any("editorial validation warning" in msg.lower() for msg in outcome["warnings"])
