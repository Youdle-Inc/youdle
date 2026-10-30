"""Safely revise the ONE scheduled October 31, 2026 Mailchimp newsletter.

Never create another campaign, send immediately, or publish blog articles.
Unschedule existing campaign, update same campaign, then restore 9 AM Central.
"""
from datetime import datetime, timezone
from html import escape
from uuid import UUID

from supabase_storage import get_supabase_client
from mailchimp_campaign import MailchimpCampaign
from api.routes.newsletters import generate_newsletter_html

NEWSLETTER_ID = "50026b07-0483-4d11-854a-834210141a22"
CAMPAIGN_ID = "fb1c4daa5e"
SCHEDULED_UTC = datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc)
SUBJECT = "Youdle Grocery News | October 31, 2026"
TITLE = "Youdle Grocery News - October 31, 2026"
REMOVE = {
    "5c1398bc-8c42-4681-bb44-be13e9651c42": "Why your grocery bill might rise: Impact of immigration policies on food supply",
    "910e0128-1d83-4af7-bd59-59609685a753": "Check your Halloween budget: Are you overspending on spooky treats?",
}


def utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_clean(html, keep_titles):
    if not isinstance(html, str):
        raise RuntimeError("Missing newsletter HTML")
    if "Youdle Grocery News" not in html:
        raise RuntimeError("New branding is missing")
    if "Grocery Brief" in html or "{IMAGE_HERE}" in html:
        raise RuntimeError("Newsletter contains old branding or an image placeholder")
    for headline in REMOVE.values():
        if headline in html or escape(headline) in html:
            raise RuntimeError("Removed article is still in newsletter")
    for headline in keep_titles:
        if escape(headline) not in html:
            raise RuntimeError("One of the six expected article headlines is missing")
    if html.count("<img ") < 7:
        raise RuntimeError("Expected logo and six article photos")


def main():
    db = get_supabase_client()
    if not db:
        raise RuntimeError("Supabase is not configured")
    rec = db.table("newsletters").select("*").eq("id", NEWSLETTER_ID).single().execute().data
    if (rec.get("status") != "scheduled" or rec.get("mailchimp_campaign_id") != CAMPAIGN_ID
            or rec.get("sent_at") or utc(rec.get("scheduled_for")) != SCHEDULED_UTC):
        raise RuntimeError("Newsletter is no longer the one confirmed scheduled for Saturday")
    if datetime.now(timezone.utc) >= SCHEDULED_UTC:
        raise RuntimeError("Scheduled time already passed; refusing unsafe change")

    links = (db.table("newsletter_posts")
             .select("id,blog_post_id,position")
             .eq("newsletter_id", NEWSLETTER_ID).order("position").execute().data or [])
    if len(links) not in (6, 8):
        raise RuntimeError("Unexpected newsletter story count")
    existing = {str(link["blog_post_id"]) for link in links}
    if len(existing) != len(links):
        raise RuntimeError("Duplicate newsletter story links")
    if len(links) == 8 and not set(REMOVE).issubset(existing):
        raise RuntimeError("One of the two requested removal targets does not match the draft")
    retained_links = [link for link in links if link["blog_post_id"] not in REMOVE]
    if len(retained_links) != 6:
        raise RuntimeError("Exactly six stories must remain")

    ids = [link["blog_post_id"] for link in retained_links]
    posts = db.table("blog_posts").select(
        "id,title,status,category,blogger_url,image_url,html_content"
    ).in_("id", ids).execute().data or []
    post_map = {post["id"]: post for post in posts}
    if len(post_map) != 6:
        raise RuntimeError("Some retained stories not found")
    if sum(post_map[p]["category"] == "RECALL" for p in ids) != 1 or post_map[ids[0]]["category"] != "RECALL":
        raise RuntimeError("Expected one recall at the beginning")
    for post_id in ids:
        post = post_map[post_id]
        if (post["status"] != "published" or not post.get("blogger_url")
                or not str(post.get("image_url") or "").startswith("https://")
                or "{IMAGE_HERE}" in (post.get("html_content") or "")):
            raise RuntimeError("Article, link or photograph not ready")

    new_html = generate_newsletter_html(db, ids, SUBJECT)
    keep_titles = [post_map[i]["title"] for i in ids]
    assert_clean(new_html, keep_titles)
    print("Preflight: six unique live articles, recall first, no political or Halloween article; branding updated.", flush=True)

    mc = MailchimpCampaign()
    if not mc.client:
        raise RuntimeError("Mailchimp connection unavailable")
    campaign = mc.client.campaigns.get(CAMPAIGN_ID)
    if (campaign.get("id") != CAMPAIGN_ID or
            campaign.get("recipients", {}).get("list_id") != mc.list_id or
            campaign.get("emails_sent", 0)):
        raise RuntimeError("Mailchimp campaign or audience does not match")
    send_time = campaign.get("send_time")
    if send_time and utc(send_time) != SCHEDULED_UTC:
        raise RuntimeError("Mailchimp campaign time has changed; refusing edit")
    status = campaign.get("status")
    if status not in ("schedule", "save"):
        raise RuntimeError("Mailchimp campaign no longer schedulable: " + str(status))
    actual = mc.client.campaigns.content.get(CAMPAIGN_ID).get("html", "")
    current_ready = True
    try:
        assert_clean(actual, keep_titles)
    except RuntimeError:
        current_ready = False

    if not current_ready:
        if status == "schedule":
            mc.client.campaigns.actions.unschedule(CAMPAIGN_ID)
            print("Existing Mailchimp campaign unscheduled for same-campaign content update.", flush=True)
        recheck = mc.client.campaigns.get(CAMPAIGN_ID)
        if recheck.get("status") not in ("save", "paused"):
            raise RuntimeError("Mailchimp did not return campaign to editable state")
        mc.client.campaigns.content.update(CAMPAIGN_ID, {"html": new_html})
        # The subject already says Youdle Grocery News; update the internal campaign title too.
        mc.client.campaigns.update(CAMPAIGN_ID, {"settings": {"subject_line": SUBJECT, "title": TITLE}})
        verified = mc.client.campaigns.content.get(CAMPAIGN_ID).get("html", "")
        assert_clean(verified, keep_titles)
        print("Existing Mailchimp campaign content and title replaced and checked.", flush=True)

    status = mc.client.campaigns.get(CAMPAIGN_ID).get("status")
    if status != "schedule":
        response = mc.schedule_campaign(CAMPAIGN_ID, SCHEDULED_UTC)
        if not response.get("success"):
            raise RuntimeError("Could not restore Saturday schedule: " + str(response.get("error")))
    final = mc.client.campaigns.get(CAMPAIGN_ID)
    if (final.get("id") != CAMPAIGN_ID or final.get("status") != "schedule" or
            utc(final.get("send_time")) != SCHEDULED_UTC):
        raise RuntimeError("Mailchimp has not confirmed the original Saturday 9 AM schedule")
    assert_clean(mc.client.campaigns.content.get(CAMPAIGN_ID).get("html", ""), keep_titles)
    print("Mailchimp confirmed same campaign ID, six stories and Sat 9 AM Central schedule.", flush=True)

    for post_id in REMOVE:
        db.table("newsletter_posts").delete().eq("newsletter_id", NEWSLETTER_ID).eq("blog_post_id", post_id).execute()
    for index, link in enumerate(retained_links):
        db.table("newsletter_posts").update({"position": index}).eq("id", link["id"]).eq("newsletter_id", NEWSLETTER_ID).execute()
    db.table("newsletters").update({
        "title": TITLE,
        "subject": SUBJECT,
        "html_content": new_html,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", NEWSLETTER_ID).eq("status", "scheduled").eq("mailchimp_campaign_id", CAMPAIGN_ID).execute()
    check = db.table("newsletter_posts").select("blog_post_id").eq("newsletter_id", NEWSLETTER_ID).execute().data or []
    if len(check) != 6 or {z["blog_post_id"] for z in check} != set(ids):
        raise RuntimeError("Mailchimp saved, but dashboard article links failed verification")
    print("SUCCESS: SAME Mailchimp campaign fb1c4daa5e; six stories, no Trump/immigration or Halloween piece, branded Youdle Grocery News, scheduled 2026-10-31 09:00 Central.", flush=True)


if __name__ == "__main__":
    main()
