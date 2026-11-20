"""Offline coverage for the approved newsletter photo hotfix."""
import base64
from types import SimpleNamespace
from unittest.mock import patch

from image_generator import ImageGenerator, summarize_image_failure
from blog_post_graph import photo_would_help, MAX_ARTICLE_PHOTO_REQUESTS


def test_every_shopper_story_is_eligible_for_an_image():
    assert photo_would_help({"category": "SHOPPERS", "title": "The grocery budget"})
    assert photo_would_help({"category": "SHOPPERS", "title": "Inflation impacts shopping"})
    assert not photo_would_help({"category": "RECALL", "title": "Turkey recall"})
    assert MAX_ARTICLE_PHOTO_REQUESTS == 10


def test_interactions_photo_success_without_paid_request():
    encoded = base64.b64encode(b"\\x89PNG" + b"x" * 3000).decode()
    client = SimpleNamespace(interactions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(
            output_image=SimpleNamespace(data=encoded, mime_type="image/png")
        )
    ))
    generator = ImageGenerator.__new__(ImageGenerator)
    generator.model_name = "gemini-nano-banana-2.1"
    generator.client = client
    result = generator.generate_image("Grocery story")
    assert result["success"] is True
    assert result["format"] == "image/png"


def test_interactions_provider_error_is_redacted():
    def fail(**kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED private-token")
    generator = ImageGenerator.__new__(ImageGenerator)
    generator.model_name = "gemini-nano-banana-2.1"
    generator.client = SimpleNamespace(interactions=SimpleNamespace(create=fail))
    result = generator.generate_image("Grocery story")
    assert result["success"] is False
    assert result["error"] == "quota_or_rate_limit"
    assert "private-token" not in str(result)


def test_selected_model_uses_existing_image_key():
    with patch("image_generator.genai_client") as sdk, patch.dict(
        "os.environ", {"GEMINI_NEWSLETTER_IMAGE_API_KEY": "offline-key"}
    ):
        generator = ImageGenerator()
    assert generator.model_name == "gemini-nano-banana-2.1"
    sdk.Client.assert_called_once_with(api_key="offline-key")
