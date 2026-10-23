"""Regression tests for uploads to an existing Supabase storage bucket."""

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from supabase_storage import SupabaseStorage


def test_upload_does_not_require_storage_bucket_admin_privileges():
    client = MagicMock()
    client.storage.list_buckets.side_effect = PermissionError("Bucket listing forbidden")
    client.storage.from_.return_value.get_public_url.return_value = (
        "https://example.test/storage/v1/object/public/blog-images/media/test.png"
    )

    with patch("supabase_storage.create_client", return_value=client):
        storage = SupabaseStorage(
            url="https://example.supabase.co",
            key="test-server-key",
        )

    result = storage.upload_image(
        image_data=base64.b64encode(b"PNG image data").decode("ascii"),
        filename="test.png",
        folder="media",
        content_type="image/png",
    )

    assert result["success"] is True
    assert result["path"].startswith("media/")
    assert result["url"].endswith("/media/test.png")
    client.storage.list_buckets.assert_not_called()
    client.storage.create_bucket.assert_not_called()
    client.storage.from_.return_value.upload.assert_called_once()


def test_upload_returns_real_storage_error_instead_of_missing_bucket():
    client = MagicMock()
    client.storage.from_.return_value.upload.side_effect = PermissionError(
        "Storage upload forbidden"
    )

    with patch("supabase_storage.create_client", return_value=client):
        storage = SupabaseStorage(
            url="https://example.supabase.co",
            key="test-server-key",
        )

    result = storage.upload_image(
        image_data=base64.b64encode(b"PNG image data").decode("ascii"),
        filename="test.png",
        folder="media",
        content_type="image/png",
    )

    assert result["success"] is False
    assert result["error"] == "Storage upload forbidden"
