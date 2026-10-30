"""One-time, idempotent Saturday consolidation. No immediate sending."""
from datetime import datetime, timezone
from uuid import uuid4
from html import escape
from supabase_storage import get_supabase_client
from mailchimp_campaign import MailchimpCampaign
from api.routes.newsletters import generate_newsletter_html

PRIMARY = "50026b07-0483-4d11-854a-834210141a22"
SECONDARY = "96ee50b7-04f8-4ce2-8aa6-843f673e87e5"
SEND_AT = datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc)
SUBJECT = "Youdle Grocery News | October 31, 2026"
TITLE = "Weekly Newsletter - October 31, 2026"

def main():
    db = get_supabase_client()
    if db is None:
        raise RuntimeError("Database unavailable")
    rows = db.table("newsletters").select("*").in_("id", [PRIMARY, SECONDARY]).execute().data or []
    if len(rows) != 2:
        raise RuntimeError("Expected exactly two original newsletter records")
    by_id = {n["id"]: n for n in rows}
    if any(n["status"] not in ("draft", "scheduled") for n in rows):
        raise RuntimeError("Newsletter is no longer in expected state")
    if any(n.get("sent_at") for n in rows):
        raise RuntimeError("One newsletter already sent; stopping")
    primary = by_id[PRIMARY]
    if primary["status"] == "scheduled" and primary.get("mailchimp_campaign_id"):
        print("Already scheduled; no duplicate campaign")
        return
    if by_id[SECONDARY]["status"] != "draft" or by_id[SECONDARY].get("mailchimp_campaign_id"):
        raise RuntimeError("Second newsletter no longer clean draft")
    if primary.get("mailchimp_campaign_id"):
        raise RuntimeError("Primary has an existing Mailchimp campaign: inspect before retry")
    existing = db.table("newsletters").select("id,status,mailchimp_campaign_id").eq("status","scheduled").execute().data or []
    if existing:
        raise RuntimeError("Another newsletter scheduled; refusing possible duplicate")
    if datetime.now(timezone.utc) >= SEND_AT:
        raise RuntimeError("Saturday send time has passed")
    posts = db.table("blog_posts").select("id,title,status,category,blogger_url,blogger_published_at,image_url,html_content").eq("status","published").gte("blogger_published_at","2026-10-27T00:00:00+00:00").lt("blogger_published_at","2026-10-31T00:00:00+00:00").execute().data or []
    posts = [p for p in posts if p.get("blogger_url")]
    shoppers = [p for p in posts if p["category"]=="SHOPPERS"]
    recalls = [p for p in posts if p["category"]=="RECALL"]
    if len(posts)!=8 or len(shoppers)!=7 or len(recalls)!=1:
        raise RuntimeError(f"Expected 7 shopper + 1 recall, got {len(shoppers)} + {len(recalls)}")
    for p in posts:
        if not str(p.get("image_url") or "").startswith("https://") or "{IMAGE_HERE}" in (p.get("html_content") or ""):
            raise RuntimeError(f"Missing image: {p['id']}")
    ordered = recalls + sorted(shoppers,key=lambda x:x["blogger_published_at"])
    ids = [p["id"] for p in ordered]
    html = generate_newsletter_html(db,ids,SUBJECT)
    if "{IMAGE_HERE}" in html or html.count("<img ")<9:
        raise RuntimeError("Newsletter HTML image validation failed")
    for p in ordered:
        if escape(p["title"]) not in html:
            raise RuntimeError(f"Missing headline in email: {p['title']}")
    print("Verified one edition with 8 unique articles and recall first.",flush=True)
    # Consolidate existing two drafts BEFORE creating a Mailchimp campaign.
    # Do not delete the source records until the schedule is confirmed.
    db.table("newsletter_posts").delete().eq("newsletter_id",PRIMARY).execute()
    db.table("newsletter_posts").insert([{"id":str(uuid4()),"newsletter_id":PRIMARY,"blog_post_id":post_id,"position":i} for i,post_id in enumerate(ids)]).execute()
    db.table("newsletters").update({"title":TITLE,"subject":SUBJECT,"html_content":html,"updated_at":datetime.now(timezone.utc).isoformat()}).eq("id",PRIMARY).eq("status","draft").execute()
    mc = MailchimpCampaign()
    if not mc.client or not mc.list_id:
        raise RuntimeError("Mailchimp credentials or audience unavailable")
    audiences = mc.get_audiences()
    selected = next((a for a in audiences if a["id"]==mc.list_id),None)
    if not selected or selected.get("member_count",0)<1:
        raise RuntimeError("Mailchimp audience not verified")
    print(f"Validated Mailchimp audience: {selected['name']} ({selected['member_count']} contacts)",flush=True)
    result = mc.create_campaign(SUBJECT,html)
    if not result.get("success"):
        raise RuntimeError("Mailchimp creation failed: "+str(result.get("error")))
    campaign_id = result["campaign_id"]
    # Persist campaign ID before scheduling, so retries never create duplicates.
    db.table("newsletters").update({"mailchimp_campaign_id":campaign_id,"mailchimp_web_id":result.get("web_id"),"updated_at":datetime.now(timezone.utc).isoformat()}).eq("id",PRIMARY).eq("status","draft").execute()
    result = mc.schedule_campaign(campaign_id,SEND_AT)
    if not result.get("success"):
        db.table("newsletters").update({"status":"failed","error":str(result.get("error"))}).eq("id",PRIMARY).execute()
        raise RuntimeError("Mailchimp schedule failed: "+str(result.get("error")))
    status = mc.get_campaign_status(campaign_id)
    if not status.get("success") or status.get("status")!="schedule":
        # Different Mailchimp SDK versions may use status scheduled or schedule
        if status.get("status") not in ("scheduled","schedule"):
            raise RuntimeError("Campaign scheduling not confirmed by Mailchimp: "+str(status))
    db.table("newsletters").update({"status":"scheduled","scheduled_for":SEND_AT.isoformat(),"error":None,"updated_at":datetime.now(timezone.utc).isoformat()}).eq("id",PRIMARY).execute()
    # Only now discard second unscheduled draft; its stories are in primary.
    db.table("newsletter_posts").delete().eq("newsletter_id",SECONDARY).execute()
    db.table("newsletters").delete().eq("id",SECONDARY).eq("status","draft").execute()
    print(f"SUCCESS: exactly one Mailchimp campaign {campaign_id} scheduled 2026-10-31 14:00 UTC / 09:00 Central with 8 stories",flush=True)

if __name__=="__main__":
    main()
