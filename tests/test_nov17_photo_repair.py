"""Offline regression coverage for the idempotent Nov 17 image repair."""
from unittest.mock import MagicMock, patch
import pytest
from scripts.repair_nov17_newsletter_photos import STORIES, JOB_ID, _insert_photo, repair


def test_each_missing_post_has_a_fixed_unique_target():
    assert len(STORIES) == 8
    assert all(len(identifier) == 36 for identifier in STORIES)


def test_inject_photo_without_rewriting_existing_text():
    body = "<div class=\"post\"><h2>Existing headline</h2><p>Original text</p></div>"
    updated = _insert_photo(body, "https://example.com/photo.png", "Groceries")
    assert updated.startswith('<div class="post"><figure')
    assert '<h2>Existing headline</h2><p>Original text</p>' in updated
    assert 'alt="Groceries"' in updated


def test_never_insert_over_existing_photo():
    with pytest.raises(ValueError):
        _insert_photo("<div><img src='old.png'/><p>Keep me</p></div>",
                      "https://example.com/new.png", "Photo")


def test_dry_run_cannot_call_provider_upload_or_publish():
    rows = [
        {"id": identifier, "job_id": JOB_ID, "title": f"News {index}",
         "status": "draft", "image_url": "", "html_content": "<div><p>Text</p></div>",
         "blogger_post_id": None, "blogger_url": None, "archived_at": None}
        for index, identifier in enumerate(STORIES)
    ]
    db = MagicMock()
    db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = rows
    with patch("scripts.repair_nov17_newsletter_photos.get_supabase_client", return_value=db), \
         patch("scripts.repair_nov17_newsletter_photos.get_supabase_storage") as store, \
         patch("scripts.repair_nov17_newsletter_photos.ImageGenerator") as generator:
        repair(execute=False)
    store.assert_not_called()
    generator.assert_not_called()
    db.table.return_value.update.assert_not_called()
