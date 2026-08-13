"""Focused tests for newsletter query batching, scoping, and ordering."""

import asyncio
from copy import deepcopy
from datetime import timezone
from unittest.mock import patch

import create_draft_newsletter as draft_newsletter
from api.routes.newsletters import (
    _attach_posts_to_newsletters,
    _parse_utc_datetime,
    generate_newsletter_html,
    get_published_posts_for_newsletter,
)


class Result:
    def __init__(self, data):
        self.data = data


class RecordingQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.columns = "*"
        self.filters = []
        self.filter_descriptions = []
        self.ordering = None
        self.row_limit = None
        self.row_range = None
        self.negate_next = False

    def select(self, columns="*", **_kwargs):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append(lambda row, c=column, v=value: row.get(c) == v)
        self.filter_descriptions.append(("eq", column, value))
        return self

    def in_(self, column, values):
        values = tuple(values)
        allowed = set(values)
        self.filters.append(lambda row, c=column, a=allowed: row.get(c) in a)
        self.filter_descriptions.append(("in", column, values))
        return self

    def gte(self, column, value):
        self.filters.append(
            lambda row, c=column, v=value: row.get(c) is not None and row.get(c) >= v
        )
        self.filter_descriptions.append(("gte", column, value))
        return self

    @property
    def not_(self):
        self.negate_next = True
        return self

    def is_(self, column, value):
        assert value == "null"
        if self.negate_next:
            self.filters.append(lambda row, c=column: row.get(c) is not None)
            operation = "not_is"
        else:
            self.filters.append(lambda row, c=column: row.get(c) is None)
            operation = "is"
        self.negate_next = False
        self.filter_descriptions.append((operation, column, value))
        return self

    def order(self, column, desc=False):
        self.ordering = (column, desc)
        return self

    def limit(self, limit):
        self.row_limit = limit
        return self

    def range(self, start, end):
        self.row_range = (start, end)
        return self

    def execute(self):
        self.client.executions.append({
            "table": self.table_name,
            "columns": self.columns,
            "filters": list(self.filter_descriptions),
        })

        rows = [
            deepcopy(row)
            for row in self.client.tables.get(self.table_name, [])
            if all(row_filter(row) for row_filter in self.filters)
        ]
        if self.ordering:
            column, descending = self.ordering
            rows.sort(key=lambda row: row.get(column) or "", reverse=descending)
        if self.row_limit is not None:
            rows = rows[:self.row_limit]
        if self.row_range is not None:
            start, end = self.row_range
            rows = rows[start:end + 1]

        if self.columns != "*":
            selected_columns = [column.strip() for column in self.columns.split(",")]
            rows = [
                {column: row.get(column) for column in selected_columns}
                for row in rows
            ]
        return Result(rows)


class RecordingClient:
    def __init__(self, tables):
        self.tables = tables
        self.executions = []

    def table(self, table_name):
        return RecordingQuery(self, table_name)


def test_list_attachment_batches_queries_and_preserves_position():
    client = RecordingClient({
        "newsletter_posts": [
            {"newsletter_id": "nl-1", "blog_post_id": "post-2", "position": 1},
            {"newsletter_id": "nl-2", "blog_post_id": "post-3", "position": 0},
            {"newsletter_id": "nl-1", "blog_post_id": "post-1", "position": 0},
        ],
        "blog_posts": [
            {"id": "post-3", "title": "Third", "category": "RECALL", "blogger_url": "u3"},
            {"id": "post-2", "title": "Second", "category": "SHOPPERS", "blogger_url": "u2"},
            {"id": "post-1", "title": "First", "category": "SHOPPERS", "blogger_url": "u1"},
        ],
    })
    newsletters = [{"id": "nl-1"}, {"id": "nl-2"}]

    result = _attach_posts_to_newsletters(client, newsletters)

    assert [post["id"] for post in result[0]["posts"]] == ["post-1", "post-2"]
    assert [post["id"] for post in result[1]["posts"]] == ["post-3"]
    assert [execution["table"] for execution in client.executions] == [
        "newsletter_posts",
        "blog_posts",
    ]
    assert ("in", "newsletter_id", ("nl-1", "nl-2")) in client.executions[0]["filters"]


def test_list_attachment_pages_links_without_truncation():
    client = RecordingClient({
        "newsletter_posts": [
            {"newsletter_id": "nl-1", "blog_post_id": f"post-{index}", "position": index}
            for index in range(3)
        ],
        "blog_posts": [
            {
                "id": f"post-{index}",
                "title": str(index),
                "category": "SHOPPERS",
                "blogger_url": f"u{index}",
            }
            for index in range(3)
        ],
    })

    with patch("api.routes.newsletters.POSTGREST_PAGE_SIZE", 2):
        result = _attach_posts_to_newsletters(client, [{"id": "nl-1"}])

    assert [post["id"] for post in result[0]["posts"]] == [
        "post-0", "post-1", "post-2"
    ]
    assert [call["table"] for call in client.executions].count("newsletter_posts") == 2


def test_generate_html_restores_the_callers_post_order():
    client = RecordingClient({
        "blog_posts": [
            {"id": "post-3", "title": "Third", "category": "SHOPPERS", "blogger_url": "u3"},
            {"id": "post-1", "title": "First", "category": "SHOPPERS", "blogger_url": "u1"},
            {"id": "post-2", "title": "Second", "category": "SHOPPERS", "blogger_url": "u2"},
        ]
    })

    with patch("mailchimp_campaign.MailchimpCampaign") as campaign_class:
        campaign = campaign_class.return_value
        campaign.create_newsletter_html.return_value = "<html>ordered</html>"

        html = generate_newsletter_html(
            client,
            ["post-2", "post-1", "post-3"],
            "Subject",
        )

    assert html == "<html>ordered</html>"
    shoppers = campaign.create_newsletter_html.call_args.args[0]
    assert [article["title"] for article in shoppers] == ["Second", "First", "Third"]


def test_recent_published_query_uses_publish_time_and_scopes_used_ids():
    client = RecordingClient({
        "blog_posts": [
            {
                "id": "available",
                "title": "Published today",
                "category": "SHOPPERS",
                "blogger_url": "available-url",
                "status": "published",
                "created_at": "2020-01-01T00:00:00+00:00",
                "blogger_published_at": "2999-01-01T00:00:00+00:00",
            },
            {
                "id": "used",
                "title": "Already used",
                "category": "SHOPPERS",
                "blogger_url": "used-url",
                "status": "published",
                "created_at": "2020-01-01T00:00:00+00:00",
                "blogger_published_at": "2998-01-01T00:00:00+00:00",
            },
            {
                "id": "old-publication",
                "title": "Created recently but published long ago",
                "category": "SHOPPERS",
                "blogger_url": "old-url",
                "status": "published",
                "created_at": "2999-01-01T00:00:00+00:00",
                "blogger_published_at": "2020-01-01T00:00:00+00:00",
            },
        ],
        "newsletter_posts": [
            {"newsletter_id": "nl-1", "blog_post_id": "used", "position": 0},
            {"newsletter_id": "nl-old", "blog_post_id": "unrelated", "position": 0},
        ],
    })

    with patch("supabase_storage.get_supabase_client", return_value=client):
        result = asyncio.run(get_published_posts_for_newsletter())

    assert [post["id"] for post in result] == ["available"]
    blog_query = next(call for call in client.executions if call["table"] == "blog_posts")
    assert any(
        operation == "gte" and column == "blogger_published_at"
        for operation, column, _value in blog_query["filters"]
    )
    used_query = next(call for call in client.executions if call["table"] == "newsletter_posts")
    assert ("in", "blog_post_id", ("available", "used")) in used_query["filters"]


def test_create_draft_limits_used_post_lookup_to_candidates():
    client = RecordingClient({
        "blog_posts": [
            {
                "id": "post-1",
                "title": "One",
                "category": "SHOPPERS",
                "blogger_url": "u1",
                "status": "published",
                "created_at": "2026-01-02T00:00:00+00:00",
                "blogger_published_at": "2999-01-02T00:00:00+00:00",
            },
            {
                "id": "post-2",
                "title": "Two",
                "category": "RECALL",
                "blogger_url": "u2",
                "status": "published",
                "created_at": "2026-01-01T00:00:00+00:00",
                "blogger_published_at": "2999-01-01T00:00:00+00:00",
            },
        ],
        "newsletter_posts": [
            {"newsletter_id": "nl-1", "blog_post_id": "post-1", "position": 0},
            {"newsletter_id": "nl-1", "blog_post_id": "post-2", "position": 1},
            {"newsletter_id": "nl-old", "blog_post_id": "unrelated", "position": 0},
        ],
    })

    with patch.object(draft_newsletter, "get_supabase_client", return_value=client), patch.object(
        draft_newsletter,
        "get_week_start_date",
        return_value=_parse_utc_datetime("2026-01-01T00:00:00Z"),
    ):
        result = draft_newsletter.create_draft_newsletter()

    assert result["success"] is False
    used_query = next(call for call in client.executions if call["table"] == "newsletter_posts")
    assert ("in", "blog_post_id", ("post-1", "post-2")) in used_query["filters"]
    posts_query = next(call for call in client.executions if call["table"] == "blog_posts")
    assert any(
        operation == "gte" and column == "blogger_published_at"
        for operation, column, _value in posts_query["filters"]
    )


def test_database_timestamps_are_normalized_to_aware_utc():
    from_zulu = _parse_utc_datetime("2026-08-13T12:00:00Z")
    from_naive = _parse_utc_datetime("2026-08-13T12:00:00")

    assert from_zulu.tzinfo == timezone.utc
    assert from_naive.tzinfo == timezone.utc
    assert from_zulu == from_naive
