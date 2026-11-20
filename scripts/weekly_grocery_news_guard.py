"""Friday Grocery News release gate with Thursday readiness alert.

No image generation, no automatic editorial publication, and no new sends unless
six previously published shopper articles and a recall have real images.
Idempotent: current week's existing newsletter and Mailchimp campaign take priority.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from html import escape

from supabase_storage import get_supabase_client
from newsletter_edition import week_bounds, sync_weekly_draft
from mailchimp_campaign import MailchimpCampaign


def _illustrated(post):
    url = str(post.get("image_url") or "").strip()
    body = str(post.get("html_content") or "")
    return url.startswith("https://") and "<img" in body.lower() and "IMAGE_HERE" not in body


def send_alert(reason):
    try:
        from email_notifier import EmailNotifier
        n = EmailNotifier()
        n.send_notification(
            "Grocery News deadline: attention required",
            "<p>Friday Grocery News is not ready for automatic publication.</p>"
            "<p>" + escape(str(reason)[:850]) + "</p>"
            "<p>Review existing articles and photo status in the Youdle newsletter agent. "
            "No duplicate email has been sent.</p>",
            to_emails=["info@getyoudle.com", "kontji@getyoudle.com", "johnita@getyoudle.com"],
        )
    except Exception as error:
        print("ALERT ERROR: " + type(error).__name__, flush=True)


def run(send=False):
    db = get_supabase_client()
    if db is None:
        raise RuntimeError("Newsletter database unavailable")
    start, end = week_bounds()
    posts = (db.table("blog_posts").select(
        "id,title,status,category,blogger_url,image_url,html_content,blogger_published_at"
    ).eq("status", "published").not_.is_("blogger_url", "null")
     .gte("blogger_published_at", start.isoformat())
     .lt("blogger_published_at", end.isoformat()).execute().data or [])
    shoppers = [p for p in posts if p.get("category") == "SHOPPERS"]
    recalls = [p for p in posts if p.get("category") == "RECALL"]
    missing_photos = [p["title"] for p in shoppers if not _illustrated(p)]
    print(f"CURRENT WEEK: {len(shoppers)} shopper, {len(recalls)} recall, "
          f"{len(missing_photos)} shopper missing photo", flush=True)
    if len(shoppers) < 6 or len(recalls) < 1:
        raise RuntimeError(
            f"Need 6 published shoppers and 1 published recall. "
            f"Have {len(shoppers)} shopper and {len(recalls)} recall.")
    if missing_photos:
        raise RuntimeError(
            f"Shopper articles are missing verified photos: "
            + "; ".join(missing_photos[:10]))
    if not send:
        print("READY: published articles, hero images, and recall requirements met.", flush=True)
        return {"status": "ready", "shoppers": len(shoppers), "recalls": len(recalls)}

    # Existing single weekly issue wins. A previously sent/scheduled campaign
    # is never duplicated or rescheduled.
    prior = (db.table("newsletters").select(
        "id,status,mailchimp_campaign_id"
    ).gte("created_at", start.isoformat())
     .lt("created_at", end.isoformat()).order("created_at").limit(1).execute().data or [])
    if prior and prior[0]["status"] in ("sent", "scheduled"):
        return {"status": "already_sent_or_scheduled", "newsletter_id": prior[0]["id"]}

    from api.routes.newsletters import generate_newsletter_html, send_newsletter
    edition = sync_weekly_draft(db, generate_newsletter_html, require_complete=True)
    if not edition or not edition.get("newsletter"):
        raise RuntimeError("Seven-story issue was not created")
    nl = edition["newsletter"]
    if nl.get("status") != "draft":
        return {"status": "already_processed", "newsletter_id": nl["id"]}

    mail = MailchimpCampaign()
    if not mail.client or not mail.list_id:
        raise RuntimeError("Mailchimp credentials missing; no send attempted")
    remote_id = nl.get("mailchimp_campaign_id")
    if remote_id:
        remote = mail.client.campaigns.get(remote_id)
        if remote.get("status") in ("sent", "sending", "schedule"):
            raise RuntimeError("Existing Mailchimp campaign is already sent or scheduled")

    # Also check if the same subject was sent through Mailchimp outside the
    # agent's database before creating a campaign.
    for item in (mail.client.campaigns.all(get_all=True).get("campaigns") or []):
        if (item.get("recipients") or {}).get("list_id") != mail.list_id:
            continue
        if (item.get("settings") or {}).get("subject_line") != nl.get("subject"):
            continue
        if item.get("status") in ("sent", "sending", "schedule"):
            raise RuntimeError("Duplicate Mailchimp subject already sent or scheduled")

    asyncio.run(send_newsletter(nl["id"]))
    fresh = (db.table("newsletters").select("status,mailchimp_campaign_id")
             .eq("id", nl["id"]).single().execute().data)
    if not fresh or fresh.get("status") != "sent" or not fresh.get("mailchimp_campaign_id"):
        raise RuntimeError("Newsletter send not confirmed in database")
    remote = mail.client.campaigns.get(fresh["mailchimp_campaign_id"])
    if remote.get("status") not in ("sent", "sending"):
        raise RuntimeError("Mailchimp did not confirm sending")
    print("VERIFIED: one newsletter sent; campaign=" + fresh["mailchimp_campaign_id"], flush=True)
    return {"status": "sent_verified", "newsletter_id": nl["id"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Send complete Friday issue exactly once")
    args = parser.parse_args()
    try:
        result = run(send=args.send)
        print(result, flush=True)
    except Exception as error:
        print("NOT READY: " + str(error)[:850], flush=True)
        send_alert(error)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
