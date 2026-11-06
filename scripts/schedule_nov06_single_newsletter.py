"""Schedule one November 6 morning newsletter from already published posts.

Reconcile two partial drafts after Mailchimp confirms the single scheduled
campaign. Never send immediately or create a second newsletter.
"""
from datetime import datetime, timezone
from uuid import uuid4
import re

from supabase_storage import get_supabase_client
from mailchimp_campaign import MailchimpCampaign
from api.routes.newsletters import generate_newsletter_html

PRIMARY = "1b3d132a-6095-4666-897b-3a260cd72654"
SECONDARY = "7a128ad2-1889-4caa-ba8f-2f7310ff0327"
TARGET = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)
SUBJECT = "Salmonella and thallium: 4 foods to check"
PREVIEW = "Plus Aldi's $6 finds, holiday-shopping savings and Thanksgiving meal ideas."
TITLE = "GrocerySOS Grocery News - November 6, 2026"
POSTS = [
    "fdde7835-0ac9-4415-acd8-3c402aa05f41",  # recall
    "19c56725-a548-4a27-b6ae-a062ab53a0a9",  # holiday savings
    "5382ef55-9e1f-4615-bcdf-67ba1691de8d",  # Aldi
    "c497f1a5-2518-4f76-ba73-1d4e7c661abb",  # turkey alternatives
    "734ce211-c0d6-4386-98ee-f4df9e161d5a",  # candy
    "b2220594-7390-4291-9807-bcc1a98ca01b",  # pretzel buns
    "3e9065e9-765a-44d1-98d8-dbcdfc47d684",  # mac and cheese
]


def verify_body(body):
    for expected in ("Food Recall Alerts", "Top Grocery Stories", "Salmonella", "Aldi"):
        if expected not in body:
            raise RuntimeError("Email missing " + expected)
    if body.count('<li style="margin:0 0 24px') != 7 or body.count("<img ") < 7:
        raise RuntimeError("Email must contain seven story cards with photos")
    if "{IMAGE_HERE}" in body:
        raise RuntimeError("Email contains obsolete content")


def main():
    db = get_supabase_client()
    if not db:
        raise RuntimeError("Database unavailable")
    now = datetime.now(timezone.utc)
    if not now < TARGET:
        raise RuntimeError("Requested Friday morning schedule has passed")

    issues = db.table("newsletters").select(
        "id,status,mailchimp_campaign_id,subject,sent_at"
    ).in_("id", [PRIMARY, SECONDARY]).execute().data or []
    issues = {row["id"]: row for row in issues}
    if len(issues) != 2:
        raise RuntimeError("Two original drafts not found")
    old = issues[SECONDARY]
    issue = issues[PRIMARY]
    if old["status"] != "draft" or old.get("mailchimp_campaign_id"):
        raise RuntimeError("Second draft has already been scheduled or sent")
    if issue.get("sent_at") or issue["status"] not in ("draft", "scheduled"):
        raise RuntimeError("Main issue not safely editable")

    other = db.table("newsletters").select(
        "id,status,mailchimp_campaign_id,created_at"
    ).gte("created_at", "2026-11-03T00:00:00+00:00").execute().data or []
    for row in other:
        if row["id"] not in (PRIMARY, SECONDARY) and (
            row["status"] in ("scheduled", "sent") or row.get("mailchimp_campaign_id")
        ):
            raise RuntimeError("Another November campaign exists; no duplicate send")

    stories = db.table("blog_posts").select(
        "id,title,category,status,blogger_url,image_url,blogger_published_at"
    ).in_("id", POSTS).execute().data or []
    if len(stories) != 7 or sum(s["category"] == "RECALL" for s in stories) != 1:
        raise RuntimeError("Expected six shopper stories and one recall")
    for story in stories:
        if (story["status"] != "published" or not story.get("blogger_url")
                or not story.get("image_url") or not story.get("blogger_published_at")):
            raise RuntimeError("Unready story: " + story["title"])
    existing = db.table("newsletter_posts").select("blog_post_id").in_(
        "newsletter_id", [PRIMARY, SECONDARY]).execute().data or []
    linked = {row["blog_post_id"] for row in existing}
    if len(linked) != 6 or not linked.issubset(set(POSTS)):
        raise RuntimeError("Drafts do not contain the expected six stories")

    body = generate_newsletter_html(db, POSTS, SUBJECT)
    verify_body(body)
    # Use public GrocerySOS branding in the recovery edition without changing
    # the legacy sender address, legal footer, or the general newsletter template.
    body = body.replace("MORE YOUDLE GROCERY NEWS", "MORE GROCERYSOS GROCERY NEWS")
    body = body.replace("Read more Youdle Grocery News", "Read more GrocerySOS Grocery News")
    body = body.replace("Youdle Grocery News", "GrocerySOS Grocery News")
    body = body.replace("Copyright © 2026 Youdle", "Copyright © 2026 GrocerySOS")
    body = body.replace("https://www.youdle.io/news", "https://grocerysos.com")
    body = re.sub(
        r'<img[^>]*alt="Youdle Logo"[^>]*>',
        '<span style="font-family:Montserrat,Arial,sans-serif;font-weight:bold;'
        'font-size:28px;color:#124F48;">GrocerySOS</span>',
        body,
    )
    verify_body(body)
    mail = MailchimpCampaign()
    if not mail.client or not mail.list_id:
        raise RuntimeError("Mailchimp credentials unavailable")

    cid = issue.get("mailchimp_campaign_id")
    if not cid:
        result = mail.create_campaign(
            subject=SUBJECT, html_content=body, from_name="GrocerySOS",
            reply_to="info@getyoudle.com")
        if not result.get("success"):
            raise RuntimeError("Mailchimp creation failed: " + str(result.get("error")))
        cid = result["campaign_id"]
        db.table("newsletters").update({
            "mailchimp_campaign_id":cid,
            "mailchimp_web_id":str(result.get("web_id") or ""),
            "updated_at":datetime.now(timezone.utc).isoformat()
        }).eq("id", PRIMARY).eq("status", "draft").execute()
        print("Created one Mailchimp draft: " + cid, flush=True)

    campaign = mail.client.campaigns.get(cid)
    if campaign.get("recipients", {}).get("list_id") != mail.list_id:
        raise RuntimeError("Unexpected campaign audience")
    if campaign.get("status") == "save":
        mail.client.campaigns.update(cid, {"settings": {
            "subject_line": SUBJECT, "preview_text": PREVIEW,
            "from_name": "GrocerySOS", "reply_to": "info@getyoudle.com",
            "title": TITLE,
        }})
        mail.client.campaigns.content.update(cid, {"html": body})
        verify_body(mail.client.campaigns.content.get(cid).get("html", ""))
        status = mail.schedule_campaign(cid, TARGET)
        if not status.get("success"):
            raise RuntimeError("Mailchimp schedule failed: " + str(status.get("error")))
    elif campaign.get("status") != "schedule":
        raise RuntimeError("Mailchimp campaign in unexpected state")

    fresh = mail.client.campaigns.get(cid)
    if fresh.get("status") != "schedule":
        raise RuntimeError("Mailchimp did not confirm schedule")
    verify_body(mail.client.campaigns.content.get(cid).get("html", ""))
    print("MAILCHIMP SCHEDULED: " + cid + " for Friday November 6, 9 AM Central", flush=True)

    links = db.table("newsletter_posts").select("id,blog_post_id,position").eq(
        "newsletter_id", PRIMARY).execute().data or []
    current = {row["blog_post_id"] for row in links}
    for i, row in enumerate(links):
        db.table("newsletter_posts").update({"position":100 + i}).eq("id",row["id"]).execute()
    for i, pid in enumerate(POSTS):
        if pid not in current:
            db.table("newsletter_posts").insert({
                "id":str(uuid4()), "newsletter_id":PRIMARY,
                "blog_post_id":pid, "position":100 + len(links) + i,
            }).execute()
    for i, pid in enumerate(POSTS):
        db.table("newsletter_posts").update({"position":i}).eq(
            "newsletter_id", PRIMARY).eq("blog_post_id",pid).execute()
    db.table("newsletters").update({
        "title":TITLE, "subject":SUBJECT, "html_content":body,
        "status":"scheduled", "scheduled_for":TARGET.isoformat(),
        "updated_at":datetime.now(timezone.utc).isoformat(), "error":None,
    }).eq("id",PRIMARY).eq("mailchimp_campaign_id",cid).execute()
    confirmed = db.table("newsletter_posts").select("blog_post_id").eq(
        "newsletter_id",PRIMARY).execute().data or []
    if len(confirmed) != 7 or set(x["blog_post_id"] for x in confirmed) != set(POSTS):
        raise RuntimeError("Mailchimp scheduled, but dashboard links need reconciliation")
    db.table("newsletters").delete().eq("id",SECONDARY).eq("status","draft").execute()
    print("SUCCESS: One edition, seven stories, no duplicate, and 9 AM Central schedule.",flush=True)


if __name__ == "__main__":
    main()
