"""Fix the existing October 31, 2026 Youdle Grocery News campaign only.

Edit campaign fb1c4daa5e, keep exactly seven published posts, and restore its
original Saturday 9 AM CT schedule. Never create a campaign or send now.
"""
from datetime import datetime, timezone
from html import escape
from uuid import uuid4

from supabase_storage import get_supabase_client
from mailchimp_campaign import MailchimpCampaign
from api.routes.newsletters import generate_newsletter_html

NID = "50026b07-0483-4d11-854a-834210141a22"
CID = "fb1c4daa5e"
WHEN = datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc)
SUBJECT = "Youdle Grocery News | October 31, 2026"
TITLE = "Youdle Grocery News - October 31, 2026"
RECALL = "c6703fc5-f3bc-4d9e-8243-7b83b0f48184"
FAST_CASUAL = "6a543135-42eb-47fb-a69e-7f6fbbd0ed92"
REMOVE = {
    "5c1398bc-8c42-4681-bb44-be13e9651c42",
    "910e0128-1d83-4af7-bd59-59609685a753",
}
UNWANTED_HEADLINES = (
    "Why your grocery bill might rise: Impact of immigration policies on food supply",
    "Check your Halloween budget: Are you overspending on spooky treats?",
)
FEATURES = {
    "09e4550f-093a-45bb-9ad6-fce067a93248":
        ("https://www.youdle.io/shop/budget", "Plan your grocery spending with Shop My Budget"),
    "972a26e8-aecd-4620-9102-3e475dd56fa5":
        ("https://www.youdle.io/shop/recipe", "Turn a flavor idea into a shopping list with Shop a Recipe"),
}


def utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def add_feature_links(html, posts):
    for post_id, (url, label) in FEATURES.items():
        title = escape(posts[post_id]["title"])
        marker = ">" + title + "</a>"
        index = html.find(marker)
        if index < 0 or html.find(marker, index + len(marker)) != -1:
            raise RuntimeError("Could not uniquely locate article for contextual Youdle link")
        close = html.find("</li>", index)
        if close < 0:
            raise RuntimeError("Missing end of article card")
        link = (
            '<p style="font-size:13px;line-height:1.6;margin:9px 0 0">'
            '<a href="' + escape(url, quote=True) + '" target="_blank" '
            'style="color:#15803d;font-weight:600;text-decoration:underline">'
            + escape(label) + "</a></p>"
        )
        html = html[:close] + link + html[close:]
    return html


def verify_html(html, posts, ids):
    if not isinstance(html, str) or SUBJECT not in html:
        raise RuntimeError("Newsletter content or title missing")
    if "Food Recall Alerts" not in html or "Top Grocery Stories" not in html:
        raise RuntimeError("Missing the two separate article section headings")
    if html.index("Food Recall Alerts") > html.index("Top Grocery Stories"):
        raise RuntimeError("Recall section is after shopper stories")
    for unwanted in ("Weekly Recall Roundup", "Grocery Brief", "{IMAGE_HERE}"):
        if unwanted.lower() in html.lower():
            raise RuntimeError("Obsolete text or image placeholder remains: " + unwanted)
    for title in UNWANTED_HEADLINES:
        if title in html or escape(title) in html:
            raise RuntimeError("Excluded political or Halloween article remains")
    if len(ids) != 7 or len(set(ids)) != 7 or ids[0] != RECALL:
        raise RuntimeError("Newsletter must have seven unique stories, recall first")
    if html.count('<li style="margin:0 0 24px') != 7 or html.count("<img ") < 8:
        raise RuntimeError("Expected seven story cards with photos and the logo")
    for post_id in ids:
        if escape(posts[post_id]["title"]) not in html:
            raise RuntimeError("Missing required article: " + posts[post_id]["title"])
    for url, _ in FEATURES.values():
        if html.count(url) != 1:
            raise RuntimeError("Missing or duplicated contextual Youdle feature link")


def main():
    if datetime.now(timezone.utc) >= WHEN:
        raise RuntimeError("Saturday 9AM Central send deadline has passed; no late send")
    db = get_supabase_client()
    if db is None:
        raise RuntimeError("Supabase unavailable")
    issue = db.table("newsletters").select("*").eq("id", NID).single().execute().data
    if not issue or issue.get("mailchimp_campaign_id") != CID or issue.get("sent_at"):
        raise RuntimeError("Existing campaign ID changed or issue already sent")
    if issue["status"] not in ("scheduled", "draft") or utc(issue["scheduled_for"]) != WHEN:
        raise RuntimeError("Original newsletter schedule changed")
    other = db.table("newsletters").select("id").eq("status", "scheduled").execute().data or []
    if any(row["id"] != NID for row in other):
        raise RuntimeError("Second newsletter scheduled; refuse to create a duplicate")

    rows = db.table("newsletter_posts").select("id,blog_post_id,position").eq(
        "newsletter_id", NID).order("position").execute().data or []
    original = [row["blog_post_id"] for row in rows]
    if len(original) not in (6, 7, 8) or len(original) != len(set(original)):
        raise RuntimeError("Unexpected current newsletter story list")
    kept = [id for id in original if id not in REMOVE and id != FAST_CASUAL]
    if len(kept) != 6 or kept[0] != RECALL:
        raise RuntimeError("Expected six retained articles, including the recall")
    ids = kept + [FAST_CASUAL]
    results = db.table("blog_posts").select(
        "id,title,category,status,blogger_url,image_url,html_content"
    ).in_("id", ids).execute().data or []
    posts = {post["id"]: post for post in results}
    if len(posts) != 7 or sum(p["category"] == "RECALL" for p in results) != 1:
        raise RuntimeError("Expected one recall and six shopper stories")
    if posts[FAST_CASUAL]["title"] != "Fast-casual fatigue: Why your favorite chain might be seeing fewer customers":
        raise RuntimeError("Replacement article mismatch")
    for post_id in ids:
        p = posts[post_id]
        if (p["status"] != "published" or not str(p.get("blogger_url") or "").startswith("https://")
                or not str(p.get("image_url") or "").startswith("https://")
                or "{IMAGE_HERE}" in (p.get("html_content") or "")):
            raise RuntimeError("Article is unpublished or lacks a photo: " + p["title"])
    html = generate_newsletter_html(db, ids, SUBJECT).replace(
        "<!-- Weekly Recall Roundup -->", "<!-- Food Recall Alerts -->"
    )
    html = add_feature_links(html, posts)
    verify_html(html, posts, ids)
    print("PREFLIGHT: seven unique stories, photos, two headings and two useful feature links.", flush=True)

    mc = MailchimpCampaign()
    if not mc.client or not mc.list_id:
        raise RuntimeError("Mailchimp connection or audience missing")
    campaign = mc.client.campaigns.get(CID)
    if (campaign.get("id") != CID or
        campaign.get("recipients", {}).get("list_id") != mc.list_id or
        int(campaign.get("emails_sent") or 0)):
        raise RuntimeError("Existing Mailchimp campaign identity, audience or send count changed")
    if campaign.get("status") not in ("save", "schedule"):
        raise RuntimeError("Mailchimp campaign not safe to edit: " + str(campaign.get("status")))
    current = mc.client.campaigns.content.get(CID).get("html", "")
    try:
        verify_html(current, posts, ids)
        correct = True
    except RuntimeError:
        correct = False
    if not correct:
        if campaign["status"] == "schedule":
            mc.client.campaigns.actions.unschedule(CID)
            print("Temporarily unscheduled existing campaign for edit.", flush=True)
        state = mc.client.campaigns.get(CID)
        if state.get("status") != "save":
            raise RuntimeError("Existing campaign did not become editable")
        mc.client.campaigns.content.update(CID, {"html": html})
        settings = state.get("settings", {})
        if settings.get("subject_line") != SUBJECT or settings.get("title") != TITLE:
            if not settings.get("from_name") or not settings.get("reply_to"):
                raise RuntimeError("Mailchimp sender fields are not available")
            mc.client.campaigns.update(CID, {"settings": {
                "subject_line": SUBJECT, "title": TITLE,
                "from_name": settings["from_name"], "reply_to": settings["reply_to"],
            }})
        verify_html(mc.client.campaigns.content.get(CID).get("html", ""), posts, ids)
        print("Mailchimp: seven stories and correct headings verified in the existing campaign.", flush=True)

    if mc.client.campaigns.get(CID).get("status") != "schedule":
        outcome = mc.schedule_campaign(CID, WHEN)
        if not outcome.get("success"):
            raise RuntimeError("Mailchimp schedule failed: " + str(outcome.get("error")))
    confirmation = mc.client.campaigns.get(CID)
    if confirmation.get("id") != CID or confirmation.get("status") != "schedule":
        raise RuntimeError("Mailchimp did not confirm existing scheduled campaign")
    verify_html(mc.client.campaigns.content.get(CID).get("html", ""), posts, ids)
    print("MAILCHIMP VERIFIED: single existing campaign scheduled with seven stories.", flush=True)

    for row in rows:
        if row["blog_post_id"] in REMOVE:
            db.table("newsletter_posts").delete().eq("id", row["id"]).eq("newsletter_id", NID).execute()
    if FAST_CASUAL not in original:
        db.table("newsletter_posts").insert({
            "id": str(uuid4()), "newsletter_id": NID,
            "blog_post_id": FAST_CASUAL, "position": 6,
        }).execute()
    for i, post_id in enumerate(ids):
        db.table("newsletter_posts").update({"position": i}).eq(
            "newsletter_id", NID).eq("blog_post_id", post_id).execute()
    db.table("newsletters").update({
        "title": TITLE, "subject": SUBJECT, "html_content": html,
        "status": "scheduled", "scheduled_for": WHEN.isoformat(),
        "error": None, "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", NID).eq("mailchimp_campaign_id", CID).execute()
    check = db.table("newsletter_posts").select("blog_post_id").eq(
        "newsletter_id", NID).execute().data or []
    if len(check) != 7 or {v["blog_post_id"] for v in check} != set(ids):
        raise RuntimeError("Mailchimp corrected but database story list did not match")
    print("SUCCESS: campaign fb1c4daa5e; 1 recall + 6 shopper stories; Saturday 9AM Central.", flush=True)


if __name__ == "__main__":
    main()
