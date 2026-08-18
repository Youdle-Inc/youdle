"""
Tests for Blogger sync endpoints.
Covers: lightweight sync, full sync timestamp logic, PATCH last_synced_at fix,
and push_drafts_to_blogger LangGraph node.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

# Add paths so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))

from tests.conftest import MockSupabaseClient, MockBloggerClient


# ---------------------------------------------------------------------------
# Timestamps used across tests
# ---------------------------------------------------------------------------
NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
ONE_HOUR_AGO = NOW - timedelta(hours=1)
TWO_HOURS_AGO = NOW - timedelta(hours=2)


# ---------------------------------------------------------------------------
# Fixture: patched TestClient that keeps mocks active during requests
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_app():
    """
    Returns a factory that creates (TestClient, MockSupabaseClient, MockBloggerClient)
    as a context manager, keeping patches active for the duration of requests.
    """
    from contextlib import contextmanager

    @contextmanager
    def _make(supabase_data=None, blogger_responses=None, blogger_configured=True):
        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=blogger_configured)

        if supabase_data is not None:
            mock_sb.table("blog_posts").configure_select(supabase_data)

        if blogger_responses:
            for bid, resp in blogger_responses.items():
                mock_bl.configure_get_post(bid, resp)

        with patch("supabase_storage.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from api.main import app
            client = TestClient(app)
            yield client, mock_sb, mock_bl

    return _make


# ===========================================================================
# LIGHTWEIGHT SYNC TESTS (/api/generate/blogger/sync-light)
# ===========================================================================

class TestSyncLight:
    """Tests for POST /api/generate/blogger/sync-light"""

    def test_returns_zero_when_blogger_not_configured(self, patched_app):
        """When Blogger is not configured, returns synced_count=0."""
        with patched_app(blogger_configured=False) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            assert resp.status_code == 200
            data = resp.json()
            assert data["synced_count"] == 0
            assert "not configured" in data["message"].lower()

    def test_returns_zero_when_no_linked_posts(self, patched_app):
        """When no local posts have a blogger_post_id, nothing to sync."""
        with patched_app(supabase_data=[]) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            assert resp.status_code == 200
            data = resp.json()
            assert data["synced_count"] == 0
            assert data["posts_checked"] == 0

    def test_deleted_on_blogger_reverts_published_to_reviewed(self, patched_app):
        """If a published post was deleted on Blogger, revert it to reviewed."""
        db_posts = [{
            "id": "post-1",
            "title": "Test Post",
            "html_content": "<p>Hello</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "blogger_published_at": ONE_HOUR_AGO.isoformat(),
            "updated_at": ONE_HOUR_AGO.isoformat(),
        }]
        # get_post_by_id returns None = deleted
        with patched_app(supabase_data=db_posts, blogger_responses={"bp-1": None}) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            assert resp.status_code == 200
            data = resp.json()
            assert data["synced_count"] == 1

            # Verify the update was called with status reverted
            updates = sb.get_table("blog_posts").updates
            assert len(updates) >= 1
            revert_update = updates[0]
            assert revert_update["data"]["status"] == "reviewed"
            assert revert_update["data"]["blogger_post_id"] is None
            assert revert_update["data"]["blogger_url"] is None

    def test_deleted_on_blogger_skips_non_published_post(self, patched_app):
        """If a draft post was deleted on Blogger, don't count as synced."""
        db_posts = [{
            "id": "post-1",
            "title": "Draft Post",
            "html_content": "<p>Draft</p>",
            "status": "draft",
            "blogger_post_id": "bp-1",
            "blogger_url": None,
            "updated_at": ONE_HOUR_AGO.isoformat(),
        }]
        with patched_app(supabase_data=db_posts, blogger_responses={"bp-1": None}) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            data = resp.json()
            assert data["synced_count"] == 0

    def test_status_mismatch_blogger_live_local_draft_updates_to_published(self, patched_app):
        """If Blogger says LIVE but local says draft, update local to published."""
        db_posts = [{
            "id": "post-1",
            "title": "My Post",
            "html_content": "<p>Content</p>",
            "status": "draft",
            "blogger_post_id": "bp-1",
            "blogger_url": None,
            "updated_at": NOW.isoformat(),
        }]
        blogger_post = {
            "id": "bp-1",
            "title": "My Post",
            "content": "<p>Content</p>",
            "status": "LIVE",
            "url": "https://blog.example.com/bp-1",
            "published": NOW.isoformat(),
            "updated": NOW.isoformat(),
        }
        with patched_app(supabase_data=db_posts, blogger_responses={"bp-1": blogger_post}) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            data = resp.json()
            assert data["synced_count"] == 1

            updates = sb.get_table("blog_posts").updates
            assert any(u["data"].get("status") == "published" for u in updates)

    def test_status_mismatch_blogger_draft_local_published_preserves_url(self, patched_app):
        """If Blogger says DRAFT but local says published, preserve the URL (non-destructive sync)."""
        db_posts = [{
            "id": "post-1",
            "title": "My Post",
            "html_content": "<p>Content</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "blogger_published_at": ONE_HOUR_AGO.isoformat(),
            "updated_at": NOW.isoformat(),
        }]
        blogger_post = {
            "id": "bp-1",
            "title": "My Post",
            "content": "<p>Content</p>",
            "status": "DRAFT",
            "url": None,
            "updated": NOW.isoformat(),
        }
        with patched_app(supabase_data=db_posts, blogger_responses={"bp-1": blogger_post}) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            data = resp.json()

            # Sync-light should not clear blogger_url/blogger_published_at
            # to avoid destroying data from successful publishes
            updates = sb.get_table("blog_posts").updates
            for u in updates:
                assert u["data"].get("blogger_url") != None or "blogger_url" not in u["data"]

    def test_blogger_newer_pulls_content_to_local(self, patched_app):
        """When Blogger content is newer than local, pull it to local DB."""
        db_posts = [{
            "id": "post-1",
            "title": "Old Title",
            "html_content": "<p>Old content</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "updated_at": TWO_HOURS_AGO.isoformat(),
        }]
        blogger_post = {
            "id": "bp-1",
            "title": "New Title From Blogger",
            "content": "<p>New content from Blogger</p>",
            "status": "LIVE",
            "url": "https://blog.example.com/bp-1",
            "published": TWO_HOURS_AGO.isoformat(),
            "updated": NOW.isoformat(),  # Blogger is newer
        }
        with patched_app(supabase_data=db_posts, blogger_responses={"bp-1": blogger_post}) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            data = resp.json()
            assert data["synced_count"] == 1

            updates = sb.get_table("blog_posts").updates
            content_update = next(
                (u for u in updates if "title" in u["data"] or "html_content" in u["data"]),
                None
            )
            assert content_update is not None
            assert content_update["data"].get("title") == "New Title From Blogger"
            assert content_update["data"].get("html_content") == "<p>New content from Blogger</p>"

    def test_local_newer_pushes_content_to_blogger(self, patched_app):
        """When local content is newer than Blogger, push it to Blogger."""
        db_posts = [{
            "id": "post-1",
            "title": "Updated Locally",
            "html_content": "<p>Edited on dashboard</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "updated_at": NOW.isoformat(),  # Local is newer
        }]
        blogger_post = {
            "id": "bp-1",
            "title": "Old Blogger Title",
            "content": "<p>Old Blogger content</p>",
            "status": "LIVE",
            "url": "https://blog.example.com/bp-1",
            "published": TWO_HOURS_AGO.isoformat(),
            "updated": TWO_HOURS_AGO.isoformat(),  # Blogger is older
        }
        with patched_app(supabase_data=db_posts, blogger_responses={"bp-1": blogger_post}) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            assert resp.status_code == 200

            # Should have pushed to Blogger
            assert len(bl.update_post_calls) == 1
            push_call = bl.update_post_calls[0]
            assert push_call["blogger_post_id"] == "bp-1"
            assert push_call["title"] == "Updated Locally"
            assert push_call["html_content"] == "<p>Edited on dashboard</p>"

            # Should NOT have overwritten local content
            updates = sb.get_table("blog_posts").updates
            for u in updates:
                assert u["data"].get("title") != "Old Blogger Title"

    def test_equal_timestamps_no_content_sync(self, patched_app):
        """When timestamps are equal, no content sync in either direction."""
        ts = NOW.isoformat()
        db_posts = [{
            "id": "post-1",
            "title": "Same Title",
            "html_content": "<p>Same content</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "updated_at": ts,
        }]
        blogger_post = {
            "id": "bp-1",
            "title": "Same Title",
            "content": "<p>Same content</p>",
            "status": "LIVE",
            "url": "https://blog.example.com/bp-1",
            "published": ts,
            "updated": ts,
        }
        with patched_app(supabase_data=db_posts, blogger_responses={"bp-1": blogger_post}) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            assert resp.status_code == 200

            # No pushes to Blogger
            assert len(bl.update_post_calls) == 0
            # No content changes in local updates
            updates = sb.get_table("blog_posts").updates
            for u in updates:
                assert "title" not in u["data"]
                assert "html_content" not in u["data"]

    def test_unparseable_timestamps_skip_content_sync(self, patched_app):
        """If timestamps can't be parsed, skip content sync (safe default)."""
        db_posts = [{
            "id": "post-1",
            "title": "Local Title",
            "html_content": "<p>Local</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "updated_at": "not-a-date",
        }]
        blogger_post = {
            "id": "bp-1",
            "title": "Blogger Title",
            "content": "<p>Blogger</p>",
            "status": "LIVE",
            "url": "https://blog.example.com/bp-1",
            "updated": "also-not-a-date",
        }
        with patched_app(supabase_data=db_posts, blogger_responses={"bp-1": blogger_post}) as (client, sb, bl):
            resp = client.post("/api/generate/blogger/sync-light")
            assert resp.status_code == 200

            # No pushes or pulls
            assert len(bl.update_post_calls) == 0
            updates = sb.get_table("blog_posts").updates
            for u in updates:
                assert "title" not in u["data"]
                assert "html_content" not in u["data"]

    def test_api_error_on_individual_post_skips_gracefully(self, patched_app):
        """If Blogger API errors on one post, it skips it and continues."""
        db_posts = [
            {
                "id": "post-1",
                "title": "Post 1",
                "html_content": "<p>1</p>",
                "status": "published",
                "blogger_post_id": "bp-1",
                "blogger_url": "https://blog.example.com/bp-1",
                "updated_at": NOW.isoformat(),
            },
            {
                "id": "post-2",
                "title": "Post 2",
                "html_content": "<p>2</p>",
                "status": "published",
                "blogger_post_id": "bp-2",
                "blogger_url": "https://blog.example.com/bp-2",
                "updated_at": NOW.isoformat(),
            },
        ]

        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select(db_posts)

        # bp-1 raises an error, bp-2 returns normally
        def flaky_get(bid):
            if bid == "bp-1":
                raise Exception("API timeout")
            return {
                "id": bid,
                "title": "Post 2",
                "content": "<p>2</p>",
                "status": "LIVE",
                "url": "https://blog.example.com/bp-2",
                "updated": NOW.isoformat(),
            }

        mock_bl.get_post_by_id = flaky_get

        with patch("supabase_storage.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/generate/blogger/sync-light")

        assert resp.status_code == 200
        # Should not have crashed


# ===========================================================================
# PATCH ENDPOINT TESTS (/api/generate/posts/{post_id})
# ===========================================================================

class TestPatchEndpoint:
    """Tests for PATCH /api/generate/posts/{post_id} — last_synced_at fix."""

    def test_sets_last_synced_at_after_successful_blogger_push(self):
        """After successfully pushing to Blogger, last_synced_at should be set."""
        post_data = {
            "id": "post-1",
            "title": "Original",
            "html_content": "<p>Original</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "updated_at": ONE_HOUR_AGO.isoformat(),
        }

        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select(post_data)

        with patch("supabase_storage.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from api.main import app
            client = TestClient(app)
            resp = client.patch(
                "/api/generate/posts/post-1",
                json={"title": "Updated Title"}
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data.get("blogger_synced") is True

            # Verify last_synced_at was set (second update call)
            updates = mock_sb.get_table("blog_posts").updates
            synced_update = next(
                (u for u in updates if "last_synced_at" in u["data"]),
                None
            )
            assert synced_update is not None, "last_synced_at should be set after successful Blogger push"

    def test_no_last_synced_at_when_blogger_push_fails(self):
        """If Blogger push fails, last_synced_at should NOT be set."""
        post_data = {
            "id": "post-1",
            "title": "Original",
            "html_content": "<p>Original</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "updated_at": ONE_HOUR_AGO.isoformat(),
        }

        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select(post_data)
        mock_bl.update_post = MagicMock(side_effect=Exception("Blogger API down"))

        with patch("supabase_storage.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from api.main import app
            client = TestClient(app)
            resp = client.patch(
                "/api/generate/posts/post-1",
                json={"title": "Updated Title"}
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data.get("blogger_synced") is False

            updates = mock_sb.get_table("blog_posts").updates
            synced_update = next(
                (u for u in updates if "last_synced_at" in u["data"]),
                None
            )
            assert synced_update is None, "last_synced_at should NOT be set when Blogger push fails"

    def test_no_blogger_push_for_post_without_blogger_id(self):
        """Posts without blogger_post_id should not attempt Blogger sync."""
        post_data = {
            "id": "post-1",
            "title": "Draft Post",
            "html_content": "<p>Draft</p>",
            "status": "draft",
            "blogger_post_id": None,
            "updated_at": ONE_HOUR_AGO.isoformat(),
        }

        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select(post_data)

        with patch("supabase_storage.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from api.main import app
            client = TestClient(app)
            resp = client.patch(
                "/api/generate/posts/post-1",
                json={"title": "New Title"}
            )

            assert resp.status_code == 200
            assert len(mock_bl.update_post_calls) == 0
            assert "blogger_synced" not in resp.json()


# ===========================================================================
# FULL SYNC TIMESTAMP TESTS (/api/generate/blogger/sync)
# ===========================================================================

class TestFullSyncTimestamp:
    """Tests for the timestamp-aware logic in the full sync endpoint."""

    def test_blogger_newer_pulls_content(self):
        """Full sync: Blogger newer -> pulls title/content to local."""
        db_posts = [{
            "id": "post-1",
            "title": "Old Local Title",
            "html_content": "<p>Old local</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "blogger_published_at": TWO_HOURS_AGO.isoformat(),
            "updated_at": TWO_HOURS_AGO.isoformat(),
        }]
        live_posts = [{
            "id": "bp-1",
            "title": "New Blogger Title",
            "content": "<p>New Blogger content</p>",
            "url": "https://blog.example.com/bp-1",
            "published": TWO_HOURS_AGO.isoformat(),
            "updated": NOW.isoformat(),
        }]

        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select(db_posts)
        mock_bl.list_posts = MagicMock(
            side_effect=lambda status='LIVE', max_results=500:
            live_posts if status == 'LIVE' else []
        )

        with patch("supabase_storage.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/generate/blogger/sync")

            assert resp.status_code == 200
            updates = mock_sb.get_table("blog_posts").updates
            content_update = next(
                (u for u in updates if u["data"].get("title") == "New Blogger Title"),
                None
            )
            assert content_update is not None, "Should have pulled new title from Blogger"

    def test_local_newer_pushes_content(self):
        """Full sync: local newer -> pushes content to Blogger, does NOT overwrite local."""
        db_posts = [{
            "id": "post-1",
            "title": "Freshly Edited",
            "html_content": "<p>Dashboard edit</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "blogger_published_at": TWO_HOURS_AGO.isoformat(),
            "updated_at": NOW.isoformat(),  # Local is newer
        }]
        live_posts = [{
            "id": "bp-1",
            "title": "Stale Blogger Title",
            "content": "<p>Stale content</p>",
            "url": "https://blog.example.com/bp-1",
            "published": TWO_HOURS_AGO.isoformat(),
            "updated": TWO_HOURS_AGO.isoformat(),  # Blogger is older
        }]

        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select(db_posts)
        mock_bl.list_posts = MagicMock(
            side_effect=lambda status='LIVE', max_results=500:
            live_posts if status == 'LIVE' else []
        )

        with patch("supabase_storage.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/generate/blogger/sync")

            assert resp.status_code == 200

            # Should have pushed to Blogger
            assert len(mock_bl.update_post_calls) == 1
            push = mock_bl.update_post_calls[0]
            assert push["title"] == "Freshly Edited"
            assert push["html_content"] == "<p>Dashboard edit</p>"

            # Should NOT have overwritten local with Blogger content
            updates = mock_sb.get_table("blog_posts").updates
            for u in updates:
                assert u["data"].get("title") != "Stale Blogger Title"
                assert u["data"].get("html_content") != "<p>Stale content</p>"

    def test_no_timestamps_skips_content_sync(self):
        """Full sync: missing timestamps -> no content sync."""
        db_posts = [{
            "id": "post-1",
            "title": "Local Title",
            "html_content": "<p>Local</p>",
            "status": "published",
            "blogger_post_id": "bp-1",
            "blogger_url": "https://blog.example.com/bp-1",
            "updated_at": None,
        }]
        live_posts = [{
            "id": "bp-1",
            "title": "Blogger Title",
            "content": "<p>Blogger</p>",
            "url": "https://blog.example.com/bp-1",
            "published": TWO_HOURS_AGO.isoformat(),
            "updated": None,
        }]

        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select(db_posts)
        mock_bl.list_posts = MagicMock(
            side_effect=lambda status='LIVE', max_results=500:
            live_posts if status == 'LIVE' else []
        )

        with patch("supabase_storage.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from api.main import app
            client = TestClient(app)
            resp = client.post("/api/generate/blogger/sync")

            assert resp.status_code == 200
            assert len(mock_bl.update_post_calls) == 0
            updates = mock_sb.get_table("blog_posts").updates
            for u in updates:
                assert "html_content" not in u["data"]


# ===========================================================================
# PUSH DRAFTS TO BLOGGER NODE TESTS
# ===========================================================================

class TestPushDraftsToBloggerNode:
    """Tests for push_drafts_to_blogger_node in blog_post_graph.py."""

    def test_creates_blogger_drafts_for_generated_posts(self):
        """Node should create Blogger drafts and update Supabase with blogger_post_id."""
        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select([{"id": "db-1"}])

        state = {
            "final_posts": [
                {
                    "title": "Test Post",
                    "html": "<p>Generated content</p>",
                    "category": "SHOPPERS",
                }
            ],
            "logs": [],
        }

        with patch("blog_post_graph.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from blog_post_graph import push_drafts_to_blogger_node
            result = push_drafts_to_blogger_node(state)

        # Should have called publish_post with is_draft=True
        assert len(mock_bl.publish_post_calls) == 1
        call = mock_bl.publish_post_calls[0]
        assert call["title"] == "Test Post"
        assert call["is_draft"] is True
        assert call["labels"] == ["SHOPPERS"]

        # Should have updated Supabase with blogger_post_id
        updates = mock_sb.get_table("blog_posts").updates
        assert len(updates) == 1
        assert "blogger_post_id" in updates[0]["data"]
        assert "last_synced_at" in updates[0]["data"]

        # Logs should report success
        assert any("Created Blogger draft" in log for log in result["logs"])

    def test_handles_blogger_not_configured(self):
        """Node should skip gracefully when Blogger is not configured."""
        mock_bl = MockBloggerClient(configured=False)

        state = {
            "final_posts": [{"title": "Test", "html": "<p>Test</p>", "category": "SHOPPERS"}],
            "logs": [],
        }

        with patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from blog_post_graph import push_drafts_to_blogger_node
            result = push_drafts_to_blogger_node(state)

        assert any("not configured" in log.lower() for log in result["logs"])
        assert len(mock_bl.publish_post_calls) == 0

    def test_handles_blogger_api_failure_gracefully(self):
        """Node should not crash if Blogger API fails for a post."""
        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_bl.publish_post = MagicMock(side_effect=Exception("API error"))

        state = {
            "final_posts": [
                {"title": "Post 1", "html": "<p>1</p>", "category": "SHOPPERS"},
                {"title": "Post 2", "html": "<p>2</p>", "category": "RECALL"},
            ],
            "logs": [],
        }

        with patch("blog_post_graph.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from blog_post_graph import push_drafts_to_blogger_node
            result = push_drafts_to_blogger_node(state)

        assert any("Failed to push" in log for log in result["logs"])
        assert any("0/2" in log for log in result["logs"])

    def test_handles_empty_final_posts(self):
        """Node should handle empty final_posts gracefully."""
        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)

        state = {"final_posts": [], "logs": []}

        with patch("blog_post_graph.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from blog_post_graph import push_drafts_to_blogger_node
            result = push_drafts_to_blogger_node(state)

        assert len(mock_bl.publish_post_calls) == 0
        assert any("0/0" in log for log in result["logs"])

    def test_handles_supabase_connection_failure(self):
        """Node should skip gracefully if Supabase is unavailable."""
        mock_bl = MockBloggerClient(configured=True)

        state = {
            "final_posts": [{"title": "Test", "html": "<p>Test</p>", "category": "SHOPPERS"}],
            "logs": [],
        }

        # Patch at the module where it was imported (blog_post_graph imports get_supabase_client at top level)
        with patch("blog_post_graph.get_supabase_client", side_effect=Exception("Connection refused")), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from blog_post_graph import push_drafts_to_blogger_node
            result = push_drafts_to_blogger_node(state)

        assert any("Could not connect to Supabase" in log for log in result["logs"])

    def test_multiple_posts_all_pushed(self):
        """Node should push all posts in final_posts list."""
        mock_sb = MockSupabaseClient()
        mock_bl = MockBloggerClient(configured=True)
        mock_sb.table("blog_posts").configure_select([{"id": "db-1"}])

        state = {
            "final_posts": [
                {"title": "Post A", "html": "<p>A</p>", "category": "SHOPPERS"},
                {"title": "Post B", "html": "<p>B</p>", "category": "RECALL"},
                {"title": "Post C", "html": "<p>C</p>", "category": "SHOPPERS"},
            ],
            "logs": [],
        }

        with patch("blog_post_graph.get_supabase_client", return_value=mock_sb), \
             patch("blogger_client.get_blogger_client", return_value=mock_bl):
            from blog_post_graph import push_drafts_to_blogger_node
            result = push_drafts_to_blogger_node(state)

        assert len(mock_bl.publish_post_calls) == 3
        assert any("3/3" in log for log in result["logs"])
