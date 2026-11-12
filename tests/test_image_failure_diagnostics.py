"""Offline regression checks for safe image-failure reporting.

No provider requests, keys or paid calls are needed.
"""
from types import SimpleNamespace
from unittest.mock import patch

from image_generator import ImageGenerator, summarize_image_failure
from blog_post_graph import upload_images_node


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
    assert "quota_or_rate_limit" in " ".join(result["errors"])
