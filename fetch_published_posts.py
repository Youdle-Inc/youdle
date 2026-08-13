# fetch_published_posts.py
# Fetch published blog posts from Supabase and write to JSON files
# This ensures the newsletter workflow uses fresh data from the database,
# not stale artifact files from the blog generation step.

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase import create_client, Client


# ============================================================================
# DATE UTILITIES (imported from check_blog_status.py for consistency)
# ============================================================================

from check_blog_status import get_week_start_date


# ============================================================================
# SUPABASE CLIENT
# ============================================================================

def get_supabase_client() -> Optional[Client]:
    """
    Get a Supabase client instance.

    Returns:
        Supabase Client instance or None if credentials not set
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("Error: SUPABASE_URL and a server-side Supabase key must be set")
        return None

    return create_client(url, key)


# ============================================================================
# FETCH PUBLISHED POSTS
# ============================================================================

def fetch_published_posts(supabase: Client, week_start: datetime) -> List[Dict[str, Any]]:
    """
    Query Supabase for this week's published blog posts.

    A post is considered "published this week" if:
    1. status == 'published'
    2. blogger_url is set (confirmed LIVE on Blogger)
    3. blogger_published_at >= week_start (actually published this week,
       not an old import from Blogger sync)

    Args:
        supabase: Supabase client
        week_start: Start of the week (datetime)

    Returns:
        List of published blog post records
    """
    week_start_iso = week_start.isoformat()

    # Query errors intentionally propagate so callers can distinguish an
    # outage from a legitimate week with no published posts.
    result = supabase.table("blog_posts").select(
        "id, title, category, status, blogger_url, blogger_post_id, "
        "article_url, image_url, blogger_published_at, created_at, updated_at"
    ).gte(
        "blogger_published_at", week_start_iso
    ).eq(
        "status", "published"
    ).not_.is_(
        "blogger_url", "null"
    ).execute()

    return result.data or []


def write_post_json(post: Dict[str, Any], output_dir: str) -> str:
    """
    Write a blog post to a JSON file.

    Args:
        post: Blog post record from Supabase
        output_dir: Output directory path

    Returns:
        Path to the written file
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Build the JSON structure expected by mailchimp_campaign.py
    # Note: The blog_posts table doesn't have a summary column, so we leave it empty
    # The newsletter will still work - it just won't show summaries under article links
    post_data = {
        "title": post.get("title", "Article"),
        "blogger_url": post.get("blogger_url"),
        "published_url": post.get("blogger_url"),  # Alias for compatibility
        "category": post.get("category", "SHOPPERS"),
        "summary": "",  # No summary column in blog_posts table
        "description": "",  # Alias for compatibility
        "original_link": post.get("article_url", ""),
        "generated_at": post.get("created_at", ""),
        "blogger_post_id": post.get("blogger_post_id"),
        "image_url": post.get("image_url"),
        "status": post.get("status"),
        "id": post.get("id")
    }

    # Use the database ID for the filename
    post_id = post.get("id", "unknown")
    filename = f"{post_id}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(post_data, f, indent=2, ensure_ascii=False)

    return filepath


def fetch_and_write_posts(output_dir: str = "blog_posts") -> Dict[str, Any]:
    """
    Main function to fetch published posts and write them to JSON files.

    Args:
        output_dir: Directory to write JSON files

    Returns:
        Result dictionary with counts and status
    """
    supabase = get_supabase_client()
    if supabase is None:
        return {
            "success": False,
            "error": "Could not connect to Supabase"
        }

    week_start = get_week_start_date()
    print(f"Fetching posts published since: {week_start.isoformat()}")

    try:
        posts = fetch_published_posts(supabase, week_start)
    except Exception as error:
        return {
            "success": False,
            "error": f"Could not query published posts: {error}",
            "week_start": week_start.isoformat(),
        }

    if not posts:
        return {
            "success": True,
            "week_start": week_start.isoformat(),
            "posts_fetched": 0,
            "shoppers_count": 0,
            "recall_count": 0,
            "files_written": [],
            "warning": "No published posts found for this week"
        }

    # Count by category
    shoppers_count = sum(1 for p in posts if (p.get("category") or "").upper() == "SHOPPERS")
    recall_count = sum(1 for p in posts if (p.get("category") or "").upper() == "RECALL")

    # Write each post to a JSON file
    files_written = []
    for post in posts:
        filepath = write_post_json(post, output_dir)
        files_written.append(filepath)
        print(f"  Wrote: {filepath} - {post.get('title', 'Untitled')[:50]}")

    return {
        "success": True,
        "week_start": week_start.isoformat(),
        "posts_fetched": len(posts),
        "shoppers_count": shoppers_count,
        "recall_count": recall_count,
        "files_written": files_written
    }


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Fetch published blog posts from Supabase and write to JSON files"
    )
    parser.add_argument(
        "--output", "-o",
        default="blog_posts",
        help="Output directory for JSON files (default: blog_posts)"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output result as JSON"
    )

    args = parser.parse_args()

    result = fetch_and_write_posts(args.output)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print()
        print("=" * 50)
        print("FETCH PUBLISHED POSTS RESULT")
        print("=" * 50)
        print(f"Week Start: {result.get('week_start', 'N/A')}")
        print(f"Posts Fetched: {result.get('posts_fetched', 0)}")
        print(f"  SHOPPERS: {result.get('shoppers_count', 0)}")
        print(f"  RECALL: {result.get('recall_count', 0)}")
        print()

        if result.get("warning"):
            print(f"Warning: {result['warning']}")
        elif result.get("error"):
            print(f"Error: {result['error']}")
        else:
            print(f"Files written to: {args.output}/")

        print("=" * 50)

    # Exit with error if failed
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
