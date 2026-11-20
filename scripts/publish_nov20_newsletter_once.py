"""Publish the existing Nov 20 Grocery News issue once after all photos exist.

Explicitly authorized 2026-11-20 catch-up. Reuses three existing reviewed-source
November 17 drafts and current published posts. Does not regenerate text,
send a second campaign, or invent a newsletter. Fail closed on uncertain
Mailchimp status. Never rerun provider calls for images.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from supabase_storage import get_supabase_client
from newsletter_edition import sync_weekly_draft, week_bounds
from mailchimp_campaign import MailchimpCampaign
from api.blogger_client import get_blogger_client

# The three previously drafted shopper pieces selected for a six-shopper
# plus one-recall issue; their sources were independently cross-checked.
DRAFT_IDS = (
    "57b7943f-b42f-4081-bf16-cade31fefe2a",  # Christmas Tree Cake hacks
    "862d4c8a-4098-4da0-a963-926133596866",  # Thanksgiving turkey
    "bb69b98f-d229-4d1a-82bf-e4f0914c1483",  # Aldi's October openings
)
EXPECTED_JOB = "f0b86d72-f5e9-437d-85ef-760fc3405d11"
DAY = "2026-11-20"


def _has_real_photo(post):
    url = str(post.get("image_url") or "")
    html = str(post.get("html_content") or "")
    return url.startswith("https://") and "<img" in html.lower() and "IMAGE_HERE" not in html


def _campaigns_today(mailchimp, expected_subject):
    """Inspect existing Mailchimp campaigns rather than trusting stale DB flags."""
    if not mailchimp.client or not mailchimp.list_id:
        raise RuntimeError("Mailchimp is not configured")
    campaigns = mailchimp.client.campaigns.all(get_all=True).get("campaigns", [])
    this_week_start, _ = week_bounds()
    for campaign in campaigns:
        settings = campaign.get("settings") or {}
        recipients = campaign.get("recipients") or {}
        if recipients.get("list_id") != mailchimp.list_id:
            continue
        status = str(campaign.get("status") or "")
        subject = str(settings.get("subject_line") or "")
        title = str(settings.get("title") or "")
        send_date = str(campaign.get("send_time") or "")[:10]
        same_issue = (subject == expected_subject or
            (title.startswith("Youdle Newsletter - 2026-11-20") and send_date >= DAY))
        if same_issue and status in ("sent", "sending", "schedule", "sending_paused"):
            return True
    return False


def run():
    if datetime.now(ZoneInfo("America/Chicago")).date().isoformat() != DAY:
        return {"status": "disabled_outside_approved_date"}

    db = get_supabase_client()
    if db is None:
        raise RuntimeError("Supabase unavailable")

    # Require every targeted photo repair to have completed, including the
    # three previously published pages.
    from scripts.repair_nov17_newsletter_photos import STORIES
    rows = db.table("blog_posts").select(
        "id,job_id,title,status,category,html_content,image_url,blogger_post_id,blogger_url"
    ).in_("id", list(STORIES) + list(DRAFT_IDS)).execute().data or []
    by_id = {str(row["id"]): row for row in rows}
    if len(by_id) != len(set(STORIES) | set(DRAFT_IDS)):
        raise RuntimeError("Exact original posts missing; abort publication")
    if any(not _has_real_photo(by_id[i]) for i in STORIES):
        raise RuntimeError("Image repair not complete; no new article or email published")
    for i in DRAFT_IDS:
        post = by_id[i]
        if str(post.get("job_id")) != EXPECTED_JOB or not _has_real_photo(post):
            raise RuntimeError("Draft identity or photo not verified: " + i)
        if post["status"] not in ("draft", "published"):
            raise RuntimeError("Unexpected draft status")

    mailchimp = MailchimpCampaign()
    if not mailchimp.client or not mailchimp.list_id:
        raise RuntimeError("Mailchimp unavailable; no publication attempted")
    # Existing issue wins, and a sent or scheduled issue cannot be overwritten.
    start, end = week_bounds()
    editions = (db.table("newsletters").select("id,status,mailchimp_campaign_id")
                .gte("created_at", start.isoformat())
                .lt("created_at", end.isoformat()).execute().data or [])
    if any(n.get("status") in ("sent", "scheduled") for n in editions):
        return {"status": "already_sent_or_scheduled", "newsletter_count": len(editions)}

    # Publish only three existing drafts, never a fresh generation batch.
    blogger = get_blogger_client()
    if not blogger.is_configured():
        raise RuntimeError("Blogger unavailable")
    newly_published = 0
    for identifier in DRAFT_IDS:
        post = by_id[identifier]
        if post["status"] == "published" and post.get("blogger_url"):
            continue
        if post["status"] != "draft" or post.get("blogger_url"):
            raise RuntimeError("Draft changed concurrently: " + identifier)
        if post.get("blogger_post_id"):
            blogger.update_post(
                blogger_post_id=post["blogger_post_id"], html_content=post["html_content"],
                title=post["title"], labels=["SHOPPERS"])
            result = blogger.publish_draft(post["blogger_post_id"])
        else:
            result = blogger.publish_post(
                title=post["title"], html_content=post["html_content"],
                labels=["SHOPPERS"], is_draft=False)
        if not result.get("blogger_post_id") or not result.get("blogger_url"):
            raise RuntimeError("Blogger did not confirm publication")
        saved = (db.table("blog_posts").update({
            "status": "published",
            "blogger_post_id": result["blogger_post_id"],
            "blogger_url": result["blogger_url"],
            "blogger_published_at": result.get("published_at") or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", identifier).eq("status", "draft").execute().data or [])
        if not saved:
            raise RuntimeError("Published post did not save: " + identifier)
        newly_published += 1

    # Use this week's original edition and require the editorial 6+1 shape.
    all_published = (db.table("blog_posts").select(
        "id,title,category,image_url,html_content,blogger_url"
    ).eq("status", "published")
     .gte("blogger_published_at", start.isoformat())
     .lt("blogger_published_at", end.isoformat()).execute().data or [])
    shopper = [p for p in all_published if p["category"] == "SHOPPERS"]
    recalls = [p for p in all_published if p["category"] == "RECALL"]
    if len(shopper) < 6 or len(recalls) < 1 or any(
        not _has_real_photo(p) for p in shopper[:6]
    ):
        raise RuntimeError("Six illustrated shopper posts and one recall are required")

    from api.routes.newsletters import generate_newsletter_html
    edition = sync_weekly_draft(db, generate_newsletter_html, require_complete=True)
    if not edition or not edition.get("newsletter"):
        raise RuntimeError("Existing weekly edition could not be generated")
    nl = edition["newsletter"]
    if nl["status"] != "draft":
        return {"status": "already_sent_or_scheduled", "newsletter_id": nl["id"]}
    if _campaigns_today(mailchimp, str(nl["subject"])):
        raise RuntimeError("Existing Mailchimp campaign already sent or scheduled; no duplicate")

    # Existing API will save campaign ID before sending, reuse it on retries,
    # and update status only after Mailchimp accepts the send.
    import asyncio
    from api.routes.newsletters import send_newsletter
    sent = asyncio.run(send_newsletter(nl["id"]))
    updated = (db.table("newsletters").select("id,status,mailchimp_campaign_id")
               .eq("id", nl["id"]).single().execute().data or {})
    campaign_id = updated.get("mailchimp_campaign_id")
    if not campaign_id:
        raise RuntimeError("No Mailchimp campaign ID after send")
    remote = mailchimp.client.campaigns.get(campaign_id)
    if updated.get("status") != "sent" or remote.get("status") != "sent":
        raise RuntimeError("Send status not confirmed in both systems")
    return {
        "status": "sent_verified", "newsletter_id": nl["id"],
        "campaign_id": campaign_id, "newly_published_posts": newly_published
    }
