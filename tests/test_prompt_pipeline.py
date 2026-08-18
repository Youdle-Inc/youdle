"""Regression tests for the active blog prompt and source-content pipeline."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from html_safety import find_unsafe_html_issues
from blog_post_html import (
    NEWS_BLOG_BACK_LINK_HTML,
    NEWSLETTER_EMBED_URL,
    NEWSLETTER_SIGNUP_BLOCK_HTML,
    ensure_news_blog_back_link,
    ensure_newsletter_signup_block,
)
from langchain_blog_agent import BlogPostGenerator, EDITORIAL_SYSTEM_PROMPT
from prompt_refiner import PromptRefiner
from prompts import RECALL_BLOG_PROMPT, SHOPPERS_BLOG_PROMPT
from reflection_agent import ReflectionAgent
from zap_exa_ranker import hydrate_article_contents


def _generated_post():
    return {
        "blog_post": "<div>Generated post</div>",
        "reflection": {"is_valid": True},
        "attempts": 1,
        "success": True,
    }


def _generator_call_for(*, article, shoppers_context=None):
    """Run only the generation node and return its LLM-generator call."""
    from blog_post_graph import generate_posts_node

    state = {
        "articles": [article],
        "posts_needing_regeneration": (
            [article] if article.get("regeneration_hints") else []
        ),
        "shoppers_context": shoppers_context or {},
        "recall_context": {},
        "model": "test-model",
    }

    with patch("blog_post_graph.BlogPostGenerator") as generator_class:
        generator = generator_class.return_value
        generator.generate_with_reflection.return_value = _generated_post()
        result = generate_posts_node(state)

    assert not result.get("errors")
    return generator.generate_with_reflection.call_args


def _render_messages(prompt_template, **overrides):
    """Build the real chain prompt without constructing or calling an LLM."""
    generator = object.__new__(BlogPostGenerator)
    passthrough = RunnableLambda(lambda value: value)
    chain = generator._create_chain(prompt_template, llm=passthrough)
    prompt = chain.steps[0]
    values = {
        "title": "Source title",
        "content": "Source body",
        "original_link": "https://example.com/report?id=42",
        "examples_section": "",
        "guidance_section": "",
    }
    values.update(overrides)
    return prompt.format_messages(**values)


def test_feedback_word_count_guidance_matches_the_canonical_prompt_range():
    """Review feedback must not silently restore the obsolete 250-word target."""
    refiner = object.__new__(PromptRefiner)

    guidance = refiner._extract_improvement_suggestion(
        "The word count was inconsistent"
    )

    assert guidance is not None
    assert "400" in guidance
    assert "600" in guidance
    assert "250" not in guidance


def test_outer_regeneration_hints_reach_the_next_generation_prompt():
    """A graph-level retry must differ from the first, cacheable LLM request."""
    hint = "Add the missing source attribution and product lot numbers."
    article = {
        "title": "Recall details",
        "content": "Article source content",
        "link": "https://example.com/recall-details",
        "category": "SHOPPERS",
        "regeneration_hints": hint,
    }

    call = _generator_call_for(article=article)

    assert hint in repr(call.kwargs)


def test_graph_owns_the_retry_loop_instead_of_nesting_retries():
    call = _generator_call_for(
        article={
            "title": "Grocery update",
            "description": "A current grocery story.",
            "link": "https://example.com/grocery-update",
            "category": "SHOPPERS",
        }
    )

    assert call.kwargs["max_retries"] == 0


def test_feedback_additions_and_common_mistakes_both_reach_generation():
    """All learned guidance should be visible to the LLM, not merely loaded."""
    prompt_addition = "Attribute every pricing claim to the original source."
    common_mistake = "Do not repeat the headline in the opening paragraph."
    article = {
        "title": "Grocery pricing update",
        "content": "Article source content",
        "link": "https://example.com/grocery-pricing",
        "category": "SHOPPERS",
    }
    context = {
        "good_examples": [],
        "bad_examples": [],
        "prompt_additions": prompt_addition,
        "common_mistakes": [common_mistake],
    }

    call = _generator_call_for(article=article, shoppers_context=context)
    invocation = repr(call.kwargs)

    assert prompt_addition in invocation
    assert common_mistake in invocation


@pytest.mark.parametrize("prompt_template", [SHOPPERS_BLOG_PROMPT, RECALL_BLOG_PROMPT])
def test_rendered_prompt_substitutes_source_url_and_preserves_image_placeholder(
    prompt_template,
):
    source_url = "https://example.com/official-source?notice=123"

    messages = _render_messages(prompt_template, original_link=source_url)
    rendered = messages[1].content

    assert f'<a href="{source_url}">Read the full story</a>' in rendered
    assert f"<source_url>{source_url}</source_url>" in rendered
    assert "{original_link}" not in rendered
    assert '{IMAGE_HERE}' in rendered
    assert 'href="https://news.youdle.io/"' in rendered
    assert "Back to News Blog" in rendered
    assert rendered.index("Back to News Blog") < rendered.index('{IMAGE_HERE}')


def test_news_blog_back_link_is_canonical_above_image_and_idempotent():
    html = """<div>
<img src="{IMAGE_HERE}" alt="article image"/>
<h2>Headline</h2>
<div><a href="https://news.youdle.io/">Back to News Blog</a></div>
</div>"""

    updated = ensure_news_blog_back_link(html)

    assert updated.count("https://news.youdle.io/") == 1
    assert updated.count("Back to News Blog") == 1
    assert NEWS_BLOG_BACK_LINK_HTML in updated
    assert updated.index("Back to News Blog") < updated.index("<img")
    assert ensure_news_blog_back_link(updated) == updated


def test_newsletter_signup_block_is_canonical_at_article_bottom_and_idempotent():
    html = """<div>
<img src="{IMAGE_HERE}" alt="article image"/>
<h2>Headline</h2>
<p>Closing article copy.</p>
</div>"""

    updated = ensure_newsletter_signup_block(html)

    assert updated.count(NEWSLETTER_EMBED_URL) == 1
    assert NEWSLETTER_SIGNUP_BLOCK_HTML in updated
    assert updated.index("Closing article copy") < updated.index(NEWSLETTER_EMBED_URL)
    assert updated.index(NEWSLETTER_EMBED_URL) < updated.rindex("</div>")
    assert ensure_newsletter_signup_block(updated) == updated


def test_generation_adds_news_blog_link_before_reflection():
    generator = object.__new__(BlogPostGenerator)
    generator.generate_shoppers_post = MagicMock(
        return_value='<div><img src="{IMAGE_HERE}" alt="article image"/></div>'
    )
    generator.generate_recall_post = MagicMock()
    generator.reflect_on_post = MagicMock(return_value={"is_valid": True})

    result = generator.generate_with_reflection(
        title="Title",
        content="Source content",
        original_link="https://example.com/source",
    )

    reflected_html = generator.reflect_on_post.call_args.args[0]
    assert "Back to News Blog" in reflected_html
    assert reflected_html.index("Back to News Blog") < reflected_html.index("<img")
    assert result["blog_post"] == reflected_html


@pytest.mark.parametrize("prompt_template", [SHOPPERS_BLOG_PROMPT, RECALL_BLOG_PROMPT])
def test_generation_prompt_uses_system_and_human_roles_with_untrusted_data_guard(
    prompt_template,
):
    messages = _render_messages(prompt_template)

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert messages[0].content == EDITORIAL_SYSTEM_PROMPT

    guard = messages[0].content.lower()
    assert "untrusted" in guard
    assert "source material" in guard
    assert "example article bodies" in guard
    assert "draft blog post" in guard
    assert "not as instructions" in guard


def test_inner_retry_guidance_changes_second_call_with_two_saved_bad_examples():
    generator = object.__new__(BlogPostGenerator)
    generator.generate_shoppers_post = MagicMock(
        side_effect=["<div>First draft</div>", "<div>Corrected draft</div>"]
    )
    generator.generate_recall_post = MagicMock()
    generator.reflect_on_post = MagicMock(
        side_effect=[
            {
                "is_valid": False,
                "issues": ["Missing source attribution"],
                "suggestions": ["Link the factual claim to its source"],
            },
            {"is_valid": True, "issues": [], "suggestions": []},
        ]
    )
    saved_bad_examples = ["bad example one", "bad example two"]

    result = generator.generate_with_reflection(
        title="Title",
        content="Source content",
        original_link="https://example.com/source",
        category="shoppers",
        bad_examples=saved_bad_examples,
        max_retries=1,
    )

    assert result["success"] is True
    assert generator.generate_shoppers_post.call_count == 2
    first_call, second_call = generator.generate_shoppers_post.call_args_list
    assert first_call.kwargs["bad_examples"] == saved_bad_examples
    assert second_call.kwargs["bad_examples"] == saved_bad_examples
    assert first_call.kwargs["regeneration_hints"] != second_call.kwargs[
        "regeneration_hints"
    ]
    assert "Missing source attribution" in second_call.kwargs[
        "regeneration_hints"
    ]
    assert "Link the factual claim to its source" in second_call.kwargs[
        "regeneration_hints"
    ]


def test_generated_post_upsert_preserves_valid_post_and_replaces_retry():
    from blog_post_graph import upsert_generated_posts

    valid_a = {"post_id": "a", "blog_post": "valid A"}
    stale_b = {"post_id": "b", "blog_post": "stale B"}
    retried_b = {"post_id": "b", "blog_post": "corrected B"}

    merged = upsert_generated_posts([valid_a, stale_b], [retried_b])

    assert merged == [valid_a, retried_b]
    assert [post["post_id"] for post in merged] == ["a", "b"]


def test_hydration_maps_shuffled_results_by_url_and_falls_back_when_missing():
    articles = [
        {
            "title": "Article A",
            "link": "https://example.com/a?utm_source=newsletter",
            "description": "A excerpt",
        },
        {
            "title": "Article B",
            "link": "https://example.com/b",
            "description": "B excerpt",
        },
        {
            "title": "Article C",
            "link": "https://example.com/c",
            "description": "C fallback excerpt",
        },
    ]
    exa = MagicMock()
    exa.get_contents.return_value = SimpleNamespace(
        results=[
            SimpleNamespace(url="https://example.com/b", text="Full B", title="B"),
            SimpleNamespace(url="https://example.com/a", text="Full A", title="A"),
        ]
    )

    hydrated = hydrate_article_contents(articles, exa=exa, max_chars=6000)

    assert [article["content"] for article in hydrated] == [
        "Full A",
        "Full B",
        "C fallback excerpt",
    ]
    assert exa.get_contents.call_args.kwargs["text"] == {"max_characters": 6000}


def test_hydration_skips_invalid_urls_and_blank_results_fall_back():
    articles = [
        {
            "title": "Valid",
            "link": "https://example.com/valid",
            "description": "Valid fallback",
        },
        {
            "title": "Unsafe",
            "link": "javascript:alert(1)",
            "description": "Unsafe URL fallback",
        },
        {
            "title": "Relative",
            "link": "/relative/path",
            "description": "Relative URL fallback",
        },
    ]
    exa = MagicMock()
    exa.get_contents.return_value = SimpleNamespace(
        results=[
            SimpleNamespace(
                url="https://example.com/valid",
                text="   ",
                title="Valid",
            )
        ]
    )

    hydrated = hydrate_article_contents(articles, exa=exa, max_chars=6000)

    fetched_urls = exa.get_contents.call_args.args[0]
    assert fetched_urls == ["https://example.com/valid"]
    assert [article["content"] for article in hydrated] == [
        "Valid fallback",
        "Unsafe URL fallback",
        "Relative URL fallback",
    ]
    assert hydrated[1]["link"] == ""
    assert hydrated[2]["link"] == ""


def test_hydration_api_failure_falls_back_to_discovery_excerpt():
    articles = [
        {
            "title": "Still usable",
            "link": "https://example.com/source",
            "description": "Discovery excerpt",
        }
    ]
    exa = MagicMock()
    exa.get_contents.side_effect = RuntimeError("temporary Exa outage")

    hydrated = hydrate_article_contents(articles, exa=exa, max_chars=6000)

    assert hydrated[0]["content"] == "Discovery excerpt"


def test_hydration_caps_at_6000_characters_and_preserves_head_and_tail():
    long_source = "SOURCE-BEGIN|" + ("H" * 7500) + ("T" * 2500) + "|SOURCE-END"
    exa = MagicMock()
    exa.get_contents.return_value = SimpleNamespace(
        results=[
            SimpleNamespace(
                url="https://example.com/long",
                text=long_source,
                title="Long source",
            )
        ]
    )

    hydrated = hydrate_article_contents(
        [{"link": "https://example.com/long", "description": "fallback"}],
        exa=exa,
        max_chars=6000,
    )
    content = hydrated[0]["content"]

    assert len(content) == 6000
    assert content.startswith("SOURCE-BEGIN|")
    assert content.endswith("|SOURCE-END")
    assert "source text omitted" in content


def test_recall_source_context_is_bounded_and_keeps_every_source():
    from blog_post_graph import build_recall_source_context

    articles = []
    for index in range(1, 4):
        articles.append(
            {
                "title": f"Recall {index} title",
                "link": f"https://fda.gov/recall-{index}",
                "content": (
                    f"SOURCE-{index}-BEGIN|"
                    + (str(index) * 8000)
                    + f"|SOURCE-{index}-END"
                ),
            }
        )

    context = build_recall_source_context(articles, max_chars=18000)

    assert len(context) <= 18000
    for index in range(1, 4):
        assert f"Recall {index} title" in context
        assert f"https://fda.gov/recall-{index}" in context
        assert f"SOURCE-{index}-BEGIN" in context
        assert f"SOURCE-{index}-END" in context


def test_generation_uses_description_when_hydrated_content_is_blank():
    article = {
        "title": "Fallback content",
        "content": "",
        "description": "Discovery excerpt used as fallback",
        "link": "https://example.com/fallback",
        "category": "SHOPPERS",
    }

    call = _generator_call_for(article=article)

    assert call.kwargs["content"] == "Discovery excerpt used as fallback"


@pytest.mark.parametrize(
    ("unsafe_html", "expected_issue"),
    [
        ("<div><script>alert('x')</script></div>", "Unsafe HTML tag: <script>"),
        (
            '<div><img src="image.jpg" onerror="alert(1)"/></div>',
            "Unsafe HTML attribute: onerror",
        ),
        (
            '<div><a href="javascript:alert(1)">Open</a></div>',
            "Unsafe URL in HTML attribute: href",
        ),
    ],
)
def test_generated_html_safety_detects_executable_markup(
    unsafe_html,
    expected_issue,
):
    assert expected_issue in find_unsafe_html_issues(unsafe_html)


def test_generated_html_safety_allows_normal_youdle_markup():
    normal_html = """<div>
<div style="text-align: center; margin: 0 0 10px 0; padding: 8px; background: #f8f9fa; border-radius: 4px;">
  <a href="https://news.youdle.io/" style="color: #007c89; text-decoration: none; font-weight: 500;">&larr; Back to News Blog</a>
</div>
<img src="{IMAGE_HERE}" alt="article image"/>
<div style="text-align: center; margin: 10px 0; padding: 8px; background: #f8f9fa;">
  <a href="https://www.youdle.io/" style="color: #007c89; text-decoration: none;">Back to Youdle</a>
</div>
<h2>A grocery update worth checking</h2>
<p>MEMPHIS, Tenn. (Youdle) - You can review this grocery update.</p>
<ul><li>Compare the details before shopping.</li></ul>
<p>Check the <a href="https://www.youdle.io/community">Youdle Community</a>,
read the <a href="https://getyoudle.com/blog">Youdle Blog</a>, and
<a href="https://example.com/source">Read the full story</a>.</p>
</div>"""

    assert find_unsafe_html_issues(normal_html) == []


def test_generated_html_safety_allows_only_the_owned_newsletter_iframe():
    assert find_unsafe_html_issues(NEWSLETTER_SIGNUP_BLOCK_HTML) == []

    untrusted_iframe = NEWSLETTER_SIGNUP_BLOCK_HTML.replace(
        NEWSLETTER_EMBED_URL,
        "https://example.com/newsletter-embed",
    )
    assert "Unsafe HTML tag: <iframe>" in find_unsafe_html_issues(untrusted_iframe)

    loosened_sandbox = NEWSLETTER_SIGNUP_BLOCK_HTML.replace(
        'sandbox="allow-forms allow-scripts allow-same-origin"',
        'sandbox="allow-forms allow-scripts allow-same-origin allow-popups"',
    )
    assert "Unsafe HTML tag: <iframe>" in find_unsafe_html_issues(loosened_sandbox)


def test_final_assembly_rejects_unsafe_generated_html():
    from blog_post_graph import assemble_html_node

    state = {
        "generated_posts": [
            {
                "post_id": "unsafe-post",
                "blog_post": (
                    '<div><img src="{IMAGE_HERE}" alt="article image"/>'
                    "<script>alert('unsafe')</script></div>"
                ),
                "article": {
                    "title": "Unsafe generated post",
                    "link": "https://example.com/source",
                },
                "category": "shoppers",
            }
        ],
        "uploaded_urls": [
            {"post_id": "unsafe-post", "url": "https://images.example.com/a.jpg"}
        ],
        "proofread_corrections": {},
    }

    result = assemble_html_node(state)

    assert result["final_posts"] == []
    assert len(result["errors"]) == 1
    assert "Unsafe generated HTML rejected" in result["errors"][0]
    assert "<script>" in result["errors"][0]


def test_final_assembly_appends_the_newsletter_signup_block():
    from blog_post_graph import assemble_html_node

    state = {
        "generated_posts": [
            {
                "post_id": "safe-post",
                "blog_post": (
                    '<div><img src="{IMAGE_HERE}" alt="article image"/>'
                    "<h2>Headline</h2><p>Article closing.</p></div>"
                ),
                "article": {
                    "title": "Safe generated post",
                    "link": "https://example.com/source",
                },
                "category": "shoppers",
            }
        ],
        "uploaded_urls": [
            {"post_id": "safe-post", "url": "https://images.example.com/a.jpg"}
        ],
        "proofread_corrections": {},
    }

    with patch("blog_post_graph.ReflectionAgent") as validator_class:
        validator_class.return_value.reflect.return_value = {"is_valid": True}
        result = assemble_html_node(state)

    assert result.get("errors", []) == []
    assert len(result["final_posts"]) == 1
    final_html = result["final_posts"][0]["html"]
    assert final_html.count(NEWSLETTER_EMBED_URL) == 1
    assert "https://images.example.com/a.jpg" in final_html
    assert find_unsafe_html_issues(final_html) == []


def test_final_assembly_keeps_safe_draft_with_editorial_warning():
    from blog_post_graph import assemble_html_node

    state = {
        "generated_posts": [
            {
                "post_id": "needs-review",
                "blog_post": (
                    '<div><img src="{IMAGE_HERE}" alt="article image"/>'
                    "<h2>Short draft</h2><p>Needs editorial review.</p></div>"
                ),
                "article": {
                    "title": "Draft needing review",
                    "link": "https://example.com/source",
                },
                "category": "shoppers",
            }
        ],
        "uploaded_urls": [
            {"post_id": "needs-review", "url": "https://images.example.com/a.jpg"}
        ],
        "proofread_corrections": {},
    }

    validation = {
        "is_valid": False,
        "summary": "Word count is below the editorial target",
    }
    with patch("blog_post_graph.ReflectionAgent") as validator_class:
        validator_class.return_value.reflect.return_value = validation
        result = assemble_html_node(state)

    assert result.get("errors", []) == []
    assert len(result["final_posts"]) == 1
    assert result["final_posts"][0]["final_validation"] == validation
    assert "editorial validation warning" in result["warnings"][0].lower()


def test_word_count_only_invalid_reflection_requests_regeneration():
    short_but_structurally_valid = """<div>
<div style="text-align: center; margin: 0 0 10px 0; padding: 8px; background: #f8f9fa; border-radius: 4px;">
  <a href="https://news.youdle.io/" style="color: #007c89; text-decoration: none; font-weight: 500;">&larr; Back to News Blog</a>
</div>
<img src="{IMAGE_HERE}" alt="article image"/>
<h2>A grocery update worth checking</h2>
<p>MEMPHIS, Tenn. (Youdle) - You can use these facts before shopping.</p>
<ul><li>Review the product details.</li></ul>
<p>Use <a href="https://www.youdle.io/">Youdle</a>, check the
<a href="https://www.youdle.io/community">Youdle Community</a>, read the
<a href="https://getyoudle.com/blog">Youdle Blog</a>, and
<a href="https://example.com/source">Read the full story</a>.</p>
</div>"""
    agent = ReflectionAgent()
    agent._spell = False

    reflection = agent.reflect(short_but_structurally_valid)

    assert reflection["structure"]["is_valid"] is True
    assert reflection["word_count"]["is_valid"] is False
    assert reflection["common_mistakes"] == []
    assert reflection["spelling_issues"] == []
    assert reflection["issues"] == [
        f"Word count issue: {reflection['word_count']['word_count']} words"
    ]
    assert agent.should_regenerate(reflection) is True
