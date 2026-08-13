"""Tests for storage/database compensation in the media API."""

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from api.routes.media import delete_media, upload_media


class _StorageWrapper:
    def __init__(self, *, remove_error=None):
        self.bucket = "blog-images"
        self.upload_image = MagicMock(return_value={
            "success": True,
            "path": "media/generated.png",
            "url": "https://example.test/generated.png",
        })
        self.remove = MagicMock(side_effect=remove_error)
        bucket_api = MagicMock()
        bucket_api.remove = self.remove
        storage_api = MagicMock()
        storage_api.from_.return_value = bucket_api
        self.client = SimpleNamespace(storage=storage_api)


class _Query:
    def __init__(self, result_data):
        self.result_data = result_data

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, _payload):
        return self

    def delete(self):
        return self

    def eq(self, *_args):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.result_data)


class _Database:
    def __init__(self, result_data):
        self.result_data = result_data
        self.deleted = False

    def table(self, _name):
        query = _Query(self.result_data)
        original_delete = query.delete

        def tracked_delete():
            self.deleted = True
            return original_delete()

        query.delete = tracked_delete
        return query


def test_failed_metadata_insert_removes_uploaded_object_and_uses_mime_extension():
    storage = _StorageWrapper()
    database = _Database([])
    upload = UploadFile(
        file=BytesIO(b"png bytes"),
        filename="misleading.exe",
        headers=Headers({"content-type": "image/png"}),
    )

    with patch("supabase_storage.get_supabase_storage", return_value=storage), patch(
        "supabase_storage.get_supabase_client", return_value=database
    ):
        with pytest.raises(HTTPException) as error:
            asyncio.run(upload_media(upload))

    assert error.value.status_code == 500
    assert storage.upload_image.call_args.kwargs["filename"].endswith(".png")
    storage.remove.assert_called_once_with(["media/generated.png"])


def test_storage_delete_failure_retains_metadata_for_retry():
    storage = _StorageWrapper(remove_error=RuntimeError("storage unavailable"))
    database = _Database({"id": "media-1", "file_path": "media/file.png"})

    with patch("supabase_storage.get_supabase_storage", return_value=storage), patch(
        "supabase_storage.get_supabase_client", return_value=database
    ):
        with pytest.raises(HTTPException) as error:
            asyncio.run(delete_media("media-1"))

    assert error.value.status_code == 502
    assert database.deleted is False
