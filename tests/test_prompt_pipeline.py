"""Regression tests for the active blog prompt and source-content pipeline."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from html_safety import find_unsafe_html_issues
from ai_models import (
    DEFAULT_MAX_TOKENS,
    EXAMPLES_SECTION_MAX_CHARS,
    MIN_CONTEXT_TOKENS,
    resolve_max_tokens,
)
from langchain_blog_agent import (
    BlogPostGenerator,
    EDITORIAL_SYSTEM_PROMPT,
    create_openai_chat_model,
)
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


def test_generation_makes_exactly_one_model_call_per_article():
    """No retry loop remains, in the graph or nested inside the generator.

    Rewrites never once turned a rejected draft into a valid one across the
    observed runs, so a second attempt is pure cost.
    """
    call = _generator_call_for(
        article={
            "title": "Grocery update",
            "description": "A current grocery story.",
            "link": "https://example.com/grocery-update",
            "category": "SHOPPERS",
        }
    )

    assert call.kwargs["max_retries"] == 0


def test_workflow_graph_has_no_regeneration_cycle():
    from blog_post_graph import create_blog_post_graph

    graph = create_blog_post_graph().get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert ("generate_posts", "proofread_posts") in edges
    # load_learning_context is the only way into generation: nothing loops back.
    assert {source for source, target in edges if target == "generate_posts"} == {
        "load_learning_context"
    }
    assert all("regenerat" not in node for node in graph.nodes)


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
    # Navigation and signup chrome now live in the Blogger theme, not the post.
    assert "Back to News Blog" not in rendered
    assert "Back to Youdle" not in rendered


def test_generation_passes_model_html_to_reflection_unmodified():
    raw_html = '<div><img src="{IMAGE_HERE}" alt="article image"/></div>'
    generator = object.__new__(BlogPostGenerator)
    generator.generate_shoppers_post = MagicMock(return_value=raw_html)
    generator.generate_recall_post = MagicMock()
    generator.reflect_on_post = MagicMock(return_value={"is_valid": True})

    result = generator.generate_with_reflection(
        title="Title",
        content="Source content",
        original_link="https://example.com/source",
    )

    reflected_html = generator.reflect_on_post.call_args.args[0]
    assert reflected_html == raw_html
    assert "Back to News Blog" not in reflected_html
    assert result["blog_post"] == raw_html


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
<img src="{IMAGE_HERE}" alt="article image"/>
<h2>A grocery update worth checking</h2>
<p>MEMPHIS, Tenn. (Youdle) - You can review this grocery update.</p>
<ul><li>Compare the details before shopping.</li></ul>
<p>Check the <a href="https://www.youdle.io/community">Youdle Community</a>,
read the <a href="https://getyoudle.com/blog">Youdle Blog</a>, and
<a href="https://example.com/source">Read the full story</a>.</p>
</div>"""

    assert find_unsafe_html_issues(normal_html) == []


def test_generated_html_safety_rejects_every_iframe():
    # The signup form now lives in the Blogger theme, so no post body may frame it.
    formerly_allowed = (
        '<div id="youdle-newsletter-signup">'
        '<iframe src="https://www.youdle.io/newsletter-embed"'
        ' title="Subscribe to the Youdle Newsletter" loading="lazy"'
        ' sandbox="allow-forms allow-scripts allow-same-origin"></iframe>'
        "</div>"
    )
    assert "Unsafe HTML tag: <iframe>" in find_unsafe_html_issues(formerly_allowed)
    assert "Unsafe HTML tag: <iframe>" in find_unsafe_html_issues(
        '<iframe src="https://example.com/embed"></iframe>'
    )


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
    assert "<iframe" not in final_html
    assert "youdle-newsletter-signup" not in final_html
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


def test_word_count_alone_marks_a_structurally_valid_post_invalid():
    short_but_structurally_valid = """<div>
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
    # Structurally sound but short: reported as invalid, and saved anyway.
    assert reflection["is_valid"] is False


def test_openai_client_uses_the_server_side_key_and_bounded_output(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    with patch("langchain_blog_agent.ChatOpenAI") as client:
        create_openai_chat_model("gpt-4o")

    client.assert_called_once_with(
        model="gpt-4o",
        temperature=0.7,
        max_tokens=DEFAULT_MAX_TOKENS,
        max_retries=3,
        api_key="test-openai-key",
    )


def test_openai_client_clamps_output_to_the_model_ceiling(monkeypatch):
    """Asking for more completion tokens than a model allows is a 400."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    with patch("langchain_blog_agent.ChatOpenAI") as client:
        create_openai_chat_model("gpt-4-turbo")

    assert client.call_args.kwargs["max_tokens"] == resolve_max_tokens("gpt-4-turbo")
    assert client.call_args.kwargs["max_tokens"] < DEFAULT_MAX_TOKENS


def test_openai_client_rejects_models_too_small_for_a_full_prompt(monkeypatch):
    """gpt-4 has an 8k window; a full prompt is ~14k, so every run produced
    zero posts. The model must be rejected with an explanation instead."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    for undersized in ("gpt-4", "gpt-3.5-turbo"):
        with pytest.raises(ValueError, match="context window"):
            create_openai_chat_model(undersized)


def test_openai_client_rejects_missing_credentials(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_openai_chat_model("gpt-4o")


def test_examples_section_stays_within_its_character_budget():
    """The learning store grows without bound; the prompt section must not."""
    generator = object.__new__(BlogPostGenerator)
    huge = "<p>" + ("filler " * 5000) + "</p>"

    section = generator._format_examples_section([huge] * 3, [huge] * 2)

    assert len(section) < EXAMPLES_SECTION_MAX_CHARS * 1.1
    assert "Good Example 3" in section
    assert "Bad Example 2" in section


def test_examples_section_keeps_short_examples_intact():
    generator = object.__new__(BlogPostGenerator)
    short = "<p>A short but complete example post.</p>"

    section = generator._format_examples_section([short], [])

    assert short in section
    assert "example truncated" not in section


def test_full_recall_prompt_fits_the_default_model_context():
    """End-to-end guard on the failure that produced no blog posts."""
    import blog_post_graph as graph

    generator = object.__new__(BlogPostGenerator)
    examples = generator._format_examples_section(
        ["<p>" + ("example " * 3000) + "</p>"] * 3,
        ["<p>" + ("example " * 3000) + "</p>"] * 2,
    )
    guidance = generator._format_guidance_section(
        prompt_additions="Stay practical.",
        common_mistakes=["mistake"] * 5,
        successful_patterns=["pattern"] * 5,
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", EDITORIAL_SYSTEM_PROMPT),
        ("human", RECALL_BLOG_PROMPT),
    ])
    messages = prompt.format_messages(
        title="Weekly recall roundup",
        content="X" * graph.RECALL_CONTEXT_MAX_CHARS,
        original_link="https://example.com/a",
        examples_section=examples,
        guidance_section=guidance,
    )

    # ~4 characters per token is the conventional English estimate.
    estimated_input_tokens = sum(len(m.content) for m in messages) / 4
    assert estimated_input_tokens + DEFAULT_MAX_TOKENS < MIN_CONTEXT_TOKENS
