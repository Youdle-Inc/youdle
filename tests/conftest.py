"""
Shared test fixtures for Youdle tests.
Provides mock Supabase and Blogger clients.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Ensure api/ and root are on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))


# ---------------------------------------------------------------------------
# Mock Supabase helpers
# ---------------------------------------------------------------------------

class MockSupabaseQuery:
    """Chainable mock that mimics supabase.table(...).select(...).eq(...).execute()"""

    def __init__(self, data=None):
        self._data = data if data is not None else []
        self._filters = {}

    def select(self, *args, **kwargs):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    @property
    def not_(self):
        return self

    def is_(self, col, val):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def single(self):
        self._single = True
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        if getattr(self, '_single', False) and not self._data:
            # postgrest-py 2.x returns None for a missing maybe_single row.
            return None
        result = MagicMock()
        if getattr(self, '_single', False) and self._data:
            result.data = self._data[0] if isinstance(self._data, list) else self._data
        else:
            result.data = self._data
        return result

    def insert(self, data):
        self._data = [data] if isinstance(data, dict) else data
        return self

    def update(self, data):
        self._update_data = data
        return self


class MockSupabaseTable:
    """Mock for supabase.table() that tracks calls for assertion."""

    def __init__(self):
        self.updates = []  # Track all update calls: (data, filters)
        self.inserts = []
        self._select_data = []

    def configure_select(self, data):
        """Set what select().execute() will return."""
        self._select_data = data

    def select(self, *args, **kwargs):
        q = MockSupabaseQuery(self._select_data)
        return q

    def update(self, data):
        call = {"data": data, "filters": {}}
        self.updates.append(call)
        q = MockSupabaseQuery([{**data}])
        # Override eq to capture filter
        original_eq = q.eq

        def tracking_eq(col, val):
            call["filters"][col] = val
            return original_eq(col, val)

        q.eq = tracking_eq
        return q

    def insert(self, data):
        self.inserts.append(data)
        q = MockSupabaseQuery([data] if isinstance(data, dict) else data)
        return q


class MockSupabaseClient:
    """Mock supabase client with table tracking."""

    def __init__(self):
        self._tables = {}

    def table(self, name):
        if name not in self._tables:
            self._tables[name] = MockSupabaseTable()
        return self._tables[name]

    def get_table(self, name):
        """Helper: get the mock table object for assertions."""
        return self._tables.get(name)


# ---------------------------------------------------------------------------
# Mock Blogger client
# ---------------------------------------------------------------------------

class MockBloggerClient:
    """Mock BloggerClient that tracks calls."""

    def __init__(self, configured=True):
        self._configured = configured
        self.update_post_calls = []
        self.publish_post_calls = []
        self.get_post_by_id_responses = {}  # blogger_post_id -> response or None

    def is_configured(self):
        return self._configured

    def update_post(self, blogger_post_id, **kwargs):
        call = {"blogger_post_id": blogger_post_id, **kwargs}
        self.update_post_calls.append(call)
        return {
            "blogger_post_id": blogger_post_id,
            "blogger_url": f"https://blog.example.com/{blogger_post_id}",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

    def publish_post(self, title, html_content, labels=None, is_draft=False):
        call = {
            "title": title,
            "html_content": html_content,
            "labels": labels,
            "is_draft": is_draft
        }
        self.publish_post_calls.append(call)
        post_id = f"blogger-{len(self.publish_post_calls)}"
        return {
            "blogger_post_id": post_id,
            "blogger_url": f"https://blog.example.com/{post_id}" if not is_draft else None,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "draft" if is_draft else "live"
        }

    def get_post_by_id(self, blogger_post_id):
        return self.get_post_by_id_responses.get(blogger_post_id, None)

    def list_posts(self, status='LIVE', max_results=500):
        return []

    def publish_draft(self, blogger_post_id):
        return {
            "blogger_post_id": blogger_post_id,
            "blogger_url": f"https://blog.example.com/{blogger_post_id}",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "LIVE"
        }

    def configure_get_post(self, blogger_post_id, response):
        """Helper: set what get_post_by_id returns for a given ID."""
        self.get_post_by_id_responses[blogger_post_id] = response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase():
    return MockSupabaseClient()


@pytest.fixture
def mock_blogger():
    return MockBloggerClient(configured=True)


@pytest.fixture
def mock_blogger_unconfigured():
    return MockBloggerClient(configured=False)
