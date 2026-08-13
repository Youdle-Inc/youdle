#!/usr/bin/env python3
"""
create_draft_newsletter.py

Creates a draft newsletter in Supabase from published blog posts,
instead of immediately sending via Mailchimp. The team can then
review the subject line and preview on the dashboard before approving.

This script is called by the create-newsletter GitHub Action workflow.
It replaces the old flow of directly calling mailchimp_campaign.py --send.

Usage:
    python create_draft_newsletter.py [--subject "Custom subject"] [--json]
"""

import os
import sys
import json
import argparse
from uuid import uuid4
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase_storage import get_supabase_client
from mailchimp_campaign import MailchimpCampaign
from check_blog_status import get_week_start_date

# Import subject line generator from the API routes
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api', 'routes'))
from newsletters import generate_content_driven_subject, generate_newsletter_html


def create_draft_newsletter(custom_subject: str = None) -> dict:
    """
    Create a draft newsletter from this week's published posts that have not
    already been used in a newsletter.
    
    Returns a dict with newsletter info or error details.
    """
    supabase = get_supabase_client()
    if supabase is None:
        return {"success": False, "error": "Database not configured"}

    # Match the workflow's publish gate: use actual Blogger publication time
    # since the most recent Tuesday, not the database row creation time.
    week_start = get_week_start_date().isoformat()
    all_posts = supabase.table("blog_posts").select(
        "id, title, category, blogger_url"
    ).eq("status", "published").not_.is_("blogger_url", "null").gte(
        "blogger_published_at", week_start
    ).order(
        "blogger_published_at", desc=True
    ).limit(50).execute()

    if not all_posts.data:
        return {"success": False, "error": "No posts were published this week"}

    all_post_ids = [p["id"] for p in all_posts.data]

    # Exclude posts already in newsletters
    used_posts = supabase.table("newsletter_posts").select("blog_post_id").in_(
        "blog_post_id", all_post_ids
    ).execute()
    used_post_ids = set(p["blog_post_id"] for p in (used_posts.data or []))
    available_posts = [p for p in all_posts.data if p["id"] not in used_post_ids]

    if not available_posts:
        return {"success": False, "error": "All published posts are already in newsletters"}

    available_post_ids = [p["id"] for p in available_posts]
    post_titles = [p["title"] for p in available_posts]

    # Generate subject line (or use custom one)
    if custom_subject:
        subject = custom_subject
    else:
        subject = generate_content_driven_subject(post_titles)

    # Generate HTML
    html_content = generate_newsletter_html(supabase, available_post_ids, subject)

    # Create the newsletter as a draft
    newsletter_id = str(uuid4())
    now = datetime.utcnow().isoformat()
    date_str = datetime.now().strftime("%B %d, %Y")
    title = f"Weekly Newsletter - {date_str}"

    newsletter_result = supabase.table("newsletters").insert({
        "id": newsletter_id,
        "title": title,
        "subject": subject,
        "html_content": html_content,
        "status": "draft",
        "created_at": now,
        "updated_at": now
    }).execute()

    if not newsletter_result.data:
        return {"success": False, "error": "Failed to create newsletter in database"}

    # Link posts
    newsletter_posts_data = []
    for i, post_id in enumerate(available_post_ids):
        newsletter_posts_data.append({
            "id": str(uuid4()),
            "newsletter_id": newsletter_id,
            "blog_post_id": post_id,
            "position": i
        })

    posts_result = supabase.table("newsletter_posts").insert(newsletter_posts_data).execute()
    if not posts_result.data:
        # Clean up
        supabase.table("newsletters").delete().eq("id", newsletter_id).execute()
        return {"success": False, "error": "Failed to link posts to newsletter"}

    # Categorize posts for the summary
    shoppers = [p for p in available_posts if p.get("category", "").upper() != "RECALL"]
    recalls = [p for p in available_posts if p.get("category", "").upper() == "RECALL"]

    # Send notification email
    try:
        from sendgrid_notifier import SendGridNotifier
        notifier = SendGridNotifier()
        notifier.send_newsletter_draft_ready_notification(
            newsletter_id=newsletter_id,
            subject=subject,
            post_count=len(available_posts),
            shoppers_count=len(shoppers),
            recall_count=len(recalls),
            post_titles=post_titles[:10]  # First 10 titles for the email
        )
    except Exception as e:
        print(f"Warning: Could not send notification email: {e}", file=sys.stderr)

    return {
        "success": True,
        "newsletter_id": newsletter_id,
        "title": title,
        "subject": subject,
        "status": "draft",
        "post_count": len(available_posts),
        "shoppers_count": len(shoppers),
        "recall_count": len(recalls),
        "message": "Draft newsletter created. Review and edit the subject line on the dashboard, then schedule or send."
    }


def main():
    parser = argparse.ArgumentParser(description="Create a draft newsletter for review")
    parser.add_argument("-s", "--subject", help="Custom subject line (optional)")
    parser.add_argument("--json", action="store_true", help="Output JSON result")
    args = parser.parse_args()

    result = create_draft_newsletter(custom_subject=args.subject)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"✅ Draft newsletter created: {result['title']}")
            print(f"   Subject: {result['subject']}")
            print(f"   Posts: {result['post_count']} ({result['shoppers_count']} shoppers, {result['recall_count']} recall)")
            print(f"   ID: {result['newsletter_id']}")
            print(f"\n👉 Review and edit the subject line at:")
            print(f"   https://youdle-agent-dashboard.vercel.app/newsletters")
        else:
            print(f"❌ Failed: {result['error']}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
