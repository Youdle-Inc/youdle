"""Offline regression checks for safe image-failure reporting.

No provider requests, keys or paid calls are needed.
"""
from types import SimpleNamespace
from unittest.mock import patch

from image_generator import ImageGenerator, summarize_image_failure
from blog_post_graph import upload_images_node, generate_images_node, photo_would_help, assemble_html_node


def test_image_generation_uses_supported_stable_model_without_provider_call():
    # Construct the client with a dummy key; do not contact Gemini or bill.
    with patch("image_generator.genai_client") as sdk, patch.dict(
        "os.environ", {"GEMINI_NEWSLETTER_IMAGE_API_KEY": "offline-test-key"}
    ):
        generator = ImageGenerator()
    assert generator.model_name == "gemini-3.1-flash-image"
    sdk.Client.assert_called_once_with(api_key="offline-test-key")


def test_failure_categories_do_not_expose_provider_details():
    assert summarize_image_failure("429 RESOURCE_EXHAUSTED api-key redacted") == "quota_or_rate_limit"
    assert summarize_image_failure("403 PERMISSION_DENIED credentials rejected") == "authentication_or_permission"
    assert summarize_image_failure("404 model not found") == "model_unavailable"
    assert summarize_image_failure("503 service unavailable") == "provider_temporarily_unavailable"
    assert summarize_image_failure("safety blocked") == "generation_blocked"
    assert summarize_image_failure("generation_blocked") == "generation_blocked"


def test_text_only_gemini_response_is_not_a_fake_success():
    generator = ImageGenerator.__new__(ImageGenerator)
    generator.model_name = "test-image-model"
    generator.client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(
        parts=[SimpleNamespace(text="No image generated", inline_data=None)],
        candidates=[SimpleNamespace(finish_reason="STOP")],
        prompt_feedback=None,
    )))
    with patch("image_generator.genai_types") as types:
        types.GenerateContentConfig.return_value = object()
        types.ImageConfig.return_value = object()
        result = generator.generate_image("A product photo")
    assert result["success"] is False
    assert result["image_data"] is None
    assert result["error"] == "no_image_returned_or_unknown"


def test_gemini_exception_is_categorized_without_raw_secret():
    generator = ImageGenerator.__new__(ImageGenerator)
    generator.model_name = "test-image-model"
    def fail(**kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED sensitive-token-should-not-appear")
    generator.client = SimpleNamespace(models=SimpleNamespace(generate_content=fail))
    with patch("image_generator.genai_types") as types:
        types.GenerateContentConfig.return_value = object()
        types.ImageConfig.return_value = object()
        result = generator.generate_image("A product photo")
    assert result["error"] == "quota_or_rate_limit"
    assert "sensitive-token" not in str(result)


def test_missing_photo_carries_reason_but_never_creates_url():
    result = upload_images_node({
        "images": [{
            "post_id": "sample-post",
            "success": False,
            "is_recall": False,
            "error": "quota_or_rate_limit",
        }],
    })
    assert result["uploaded_urls"] == [{
        "post_id": "sample-post", "url": "", "success": False
    }]
    assert "quota_or_rate_limit" in " ".join(result["warnings"])
    assert not result.get("errors")


def test_photo_relevance_excludes_statistics_and_recalls():
    assert photo_would_help({"title": "How to make a Thanksgiving turkey dinner", "category": "SHOPPERS"})
    assert not photo_would_help({"title": "Consumer price index climbs", "category": "SHOPPERS"})
    assert not photo_would_help({"title": "Turkey recall notice", "category": "RECALL"})


def test_missing_photo_saves_clean_text_and_warns():
    from unittest.mock import patch
    state = {
        "generated_posts": [{
            "post_id": "text-draft-1",
            "blog_post": (
                '<div><img src="{IMAGE_HERE}" alt="article photo"/>'
                '<h2>Turkey recipes for smaller families</h2><p>Shopper advice.</p></div>'
            ),
            "article": {"title": "Turkey recipes", "link": "https://example.com/turkey"},
            "category": "SHOPPERS",
        }],
        "uploaded_urls": [],
        "proofread_corrections": {},
    }
    with patch("blog_post_graph.ReflectionAgent") as validation:
        validation.return_value.reflect.return_value = {"is_valid": True}
        result = assemble_html_node(state)
    assert len(result["final_posts"]) == 1
    draft = result["final_posts"][0]
    assert draft["image_url"] == ""
    assert "<img" not in draft["html"]
    assert "IMAGE_HERE" not in draft["html"]
    assert "Shopper advice" in draft["html"]
    assert any("without a photograph" in warning for warning in result["warnings"])


def test_image_quota_and_model_failure_short_circuit_extra_calls():
    article = {"title": "Roast turkey recipe", "category": "SHOPPERS"}
    state = {"generated_posts": [
        {"post_id": str(i), "success": True, "blog_post": "<p>text</p>", "category": "SHOPPERS",
         "article": article}
        for i in range(8)
    ]}
    from unittest.mock import patch
    with patch("blog_post_graph.get_image_generator") as client, patch(
        "blog_post_graph.describe_image_subject", return_value="turkey"
    ) as subject:
        mock = client.return_value
        mock.look_for.return_value = "daylight"
        mock.generate_image_for_article.return_value = {
            "success": False, "error": "model_unavailable", "image_data": None
        }
        result = generate_images_node(state)
    assert len(result["images"]) == 8
    assert mock.generate_image_for_article.call_count == 1
    assert subject.call_count == 1
    assert any("Stopped additional" in w for w in result["warnings"])


def test_nonvisual_stories_generate_no_images_and_no_provider_call():
    state = {"generated_posts": [{
        "post_id": "economic-story", "success": True,
        "blog_post": "<p>News</p>", "category": "SHOPPERS",
        "article": {"title": "Consumer price index rises", "category": "SHOPPERS"}
    }]}
    with patch("blog_post_graph.get_image_generator") as client:
        result = generate_images_node(state)
    client.assert_not_called()
    assert result["images"][0]["image_skipped"] is True
    uploaded = upload_images_node({"images": result["images"]})
    assert not uploaded.get("errors")
    assert not uploaded.get("warnings")
