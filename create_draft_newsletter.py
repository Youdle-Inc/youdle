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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase_storage import get_supabase_client

# Import subject line generator from the API routes
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api', 'routes'))
from newsletters import generate_newsletter_html


def create_draft_newsletter(custom_subject: str = None) -> dict:
    """Build or refresh the same unsent weekly issue, without sending it."""
    from newsletter_edition import sync_weekly_draft
    db = get_supabase_client()
    if db is None:
        return {"success": False, "error": "Database not configured"}
    result = sync_weekly_draft(db, generate_newsletter_html, subject=custom_subject, require_complete=True)
    if not result:
        return {"success": False, "error": "Waiting for six shopper stories and one recall"}
    newsletter = result['newsletter']
    links = db.table('newsletter_posts').select('blog_post_id').eq('newsletter_id', newsletter['id']).order('position').execute().data or []
    posts = db.table('blog_posts').select('id,title,category').in_('id', [p['blog_post_id'] for p in links]).execute().data or []
    shopper_count = sum(p.get('category') != 'RECALL' for p in posts)
    recall_count = len(posts) - shopper_count
    if result['created']:
        try:
            from email_notifier import EmailNotifier
            EmailNotifier().send_newsletter_draft_ready_notification(newsletter_id=newsletter['id'], subject=newsletter['subject'], post_count=len(posts), shoppers_count=shopper_count, recall_count=recall_count, post_titles=[p['title'] for p in posts][:10])
        except Exception as error:
            print(f"Warning: Could not send draft-ready notification: {error}", file=sys.stderr)
    return {"success": True, "newsletter_id": newsletter['id'], "title": newsletter['title'], "subject": newsletter['subject'], "status": newsletter['status'], "post_count": len(posts), "shoppers_count": shopper_count, "recall_count": recall_count, "message": "Existing weekly edition refreshed. Review it on the dashboard."}


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
