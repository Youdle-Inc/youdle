"""Schedule the already-merged, single November 7 Youdle catch-up edition.

This script never creates a second newsletter or sends immediately.
Intended one-time delivery: Saturday, Nov 7 2026, 09:00 CST (15:00 UTC).
"""
from datetime import datetime, timezone
from html import escape

from mailchimp_campaign import MailchimpCampaign
from supabase_storage import get_supabase_client


NEWSLETTER_ID = "1b3d132a-6095-4666-897b-3a260cd72654"
TARGET = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)
SUBJECT = "Salmonella and thallium: 4 foods to check"
PREVIEW = "Plus Aldi's $6 finds, holiday-shopping savings and Thanksgiving meal ideas."
TITLE = "Youdle Grocery News - November 7, 2026"


def main():
    if datetime.now(timezone.utc) >= TARGET:
        raise RuntimeError("November 7, 9 AM Central has passed; no late or immediate send")

    db = get_supabase_client()
    if db is None:
        raise RuntimeError("Supabase not available")

    editions = (
        db.table("newsletters")
        .select("*")
        .gte("created_at", "2026-11-01T00:00:00+00:00")
        .execute()
    ).data or []
    if len(editions) != 1 or str(editions[0]["id"]) != NEWSLETTER_ID:
        raise RuntimeError("Expected one November newsletter; refusing duplicate campaign")

    newsletter = editions[0]
    if newsletter.get("sent_at") is not None or newsletter["status"] == "sent":
        raise RuntimeError("Newsletter already sent")
    if newsletter["status"] not in ("draft", "scheduled"):
        raise RuntimeError("Newsletter must be a clean draft or existing schedule")
    if newsletter["subject"] != SUBJECT:
        raise RuntimeError("Newsletter subject changed unexpectedly")

    links = (
        db.table("newsletter_posts")
        .select("blog_post_id,position")
        .eq("newsletter_id", NEWSLETTER_ID)
        .order("position")
        .execute()
    ).data or []
    if len(links) != 7 or len({str(row["blog_post_id"]) for row in links}) != 7:
        raise RuntimeError("The merged edition needs seven unique story links")

    ids = [str(row["blog_post_id"]) for row in links]
    posts = (
        db.table("blog_posts")
        .select("id,title,category,status,blogger_url,image_url")
        .in_("id", ids)
        .execute()
    ).data or []
    if len(posts) != 7:
        raise RuntimeError("Published stories missing from Supabase")
    by_id = {str(row["id"]): row for row in posts}
    ordered = [by_id[post_id] for post_id in ids]
    if ordered[0]["category"] != "RECALL":
        raise RuntimeError("Food safety story must come first")
    if sum(row["category"] == "RECALL" for row in ordered) != 1:
        raise RuntimeError("Expected one recall")
    if sum(row["category"] == "SHOPPERS" for row in ordered) != 6:
        raise RuntimeError("Expected six grocery stories")

    body = newsletter["html_content"]
    for story in ordered:
        if story["status"] != "published" or not story.get("blogger_url") or not story.get("image_url"):
            raise RuntimeError("Incomplete published story: " + story["title"])
        if escape(story["blogger_url"], quote=True) not in body:
            raise RuntimeError("Newsletter HTML missing article link: " + story["title"])
        if escape(story["image_url"], quote=True) not in body:
            raise RuntimeError("Newsletter HTML missing image: " + story["title"])
    if body.count("<li style=\"margin:0 0 24px") != 7 or body.count('<img src=') < 7:
        raise RuntimeError("Newsletter must have seven image-backed article cards")
    if "Food Safety Alerts" not in body or "Top Grocery Stories" not in body:
        raise RuntimeError("Newsletter sections missing")

    mail = MailchimpCampaign()
    if not mail.client or not mail.list_id:
        raise RuntimeError("Mailchimp credentials or audience not configured")

    cid = newsletter.get("mailchimp_campaign_id")
    if cid:
        campaign = mail.client.campaigns.get(cid)
        state = campaign.get("status")
        if state in ("schedule", "scheduled"):
            # This campaign was scheduled with the unlaunched GrocerySOS name.
            # Safely unschedule the SAME campaign, change only its branding,
            # and restore the same Saturday 9 AM CST send time.
            settings = campaign.get("settings") or {}
            remote_html = mail.client.campaigns.content.get(cid).get("html", "")
            branding_ok = (
                settings.get("from_name") == "Youdle"
                and settings.get("title") == TITLE
                and settings.get("subject_line") == SUBJECT
                and "GrocerySOS" not in remote_html
                and "grocerysos.com" not in remote_html
                and "Youdle Logo" in remote_html
            )
            if branding_ok:
                print("Mailchimp already scheduled with Youdle branding: " + cid, flush=True)
                return

            if datetime.now(timezone.utc) >= TARGET:
                raise RuntimeError("Scheduled send has started; cannot safely modify it")
            print("Unscheduling same campaign temporarily for Youdle prelaunch branding", flush=True)
            mail.client.campaigns.actions.unschedule(cid)
            unscheduled = mail.client.campaigns.get(cid)
            state_after_unschedule = unscheduled.get("status")
            print("Campaign status after unschedule: " + str(state_after_unschedule), flush=True)
            if state_after_unschedule not in ("save", "paused"):
                raise RuntimeError("Unexpected Mailchimp state after unschedule: " + str(state_after_unschedule))
            print("Campaign unscheduled for safe content edit", flush=True)
        elif state not in ("save", "paused"):
            raise RuntimeError("Existing Mailchimp campaign is not a safe unsent draft: " + str(state))
    else:
        if newsletter["status"] != "draft":
            raise RuntimeError("A scheduled newsletter must already have a campaign ID")
        result = mail.create_campaign(
            subject=SUBJECT, html_content=body,
            from_name="Youdle", reply_to="info@getyoudle.com"
        )
        if not result.get("success"):
            raise RuntimeError("Creating Mailchimp campaign failed: " + str(result.get("error")))
        cid = result["campaign_id"]
        update = (
            db.table("newsletters")
            .update({
                "mailchimp_campaign_id": cid,
                "mailchimp_web_id": str(result.get("web_id") or ""),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", NEWSLETTER_ID)
            .eq("status", "draft")
            .execute()
        )
        if not update.data:
            raise RuntimeError("Mailchimp draft created, but its ID could not be saved")
        print("One Mailchimp campaign created: " + cid, flush=True)

    mail.client.campaigns.update(cid, {"settings": {
        "subject_line": SUBJECT,
        "preview_text": PREVIEW,
        "from_name": "Youdle",
        "reply_to": "info@getyoudle.com",
        "title": TITLE,
    }})
    if "GrocerySOS" in body or "grocerysos.com" in body:
        raise RuntimeError("Prelaunch newsletter still exposes GrocerySOS")
    mail.client.campaigns.content.update(cid, {"html": body})

    verified_campaign = mail.client.campaigns.get(cid)
    verified_content = mail.client.campaigns.content.get(cid).get("html", "")
    if verified_campaign.get("settings", {}).get("from_name") != "Youdle":
        raise RuntimeError("Mailchimp sender name did not change to Youdle")
    if "GrocerySOS" in verified_content or "grocerysos.com" in verified_content:
        raise RuntimeError("Mailchimp email still contains unreleased GrocerySOS brand")
    if "Youdle Logo" not in verified_content or "Food Safety Alerts" not in verified_content:
        raise RuntimeError("Mailchimp content did not retain expected Youdle logo and food-safety section")

    result = mail.schedule_campaign(cid, TARGET)
    if not result.get("success"):
        raise RuntimeError("Mailchimp scheduling failed: " + str(result.get("error")))

    remote = mail.client.campaigns.get(cid)
    if remote.get("status") not in ("schedule", "scheduled"):
        raise RuntimeError("Mailchimp did not confirm the schedule: " + str(remote.get("status")))

    update = (
        db.table("newsletters")
        .update({
            "title": TITLE,
            "subject": SUBJECT,
            "status": "scheduled",
            "scheduled_for": TARGET.isoformat(),
            "error": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", NEWSLETTER_ID)
        .eq("mailchimp_campaign_id", cid)
        .execute()
    )
    if not update.data:
        raise RuntimeError("Mailchimp scheduled, but newsletter dashboard needs synchronization")

    print("Confirmed: ONE Youdle newsletter, scheduled for Saturday Nov 7, 09:00 CST", flush=True)


if __name__ == "__main__":
    main()
