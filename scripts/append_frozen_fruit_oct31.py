"""Append frozen fruit to existing Mailchimp newsletter; no other story changes."""
from datetime import datetime,timezone
from uuid import uuid4
from supabase_storage import get_supabase_client
from mailchimp_campaign import MailchimpCampaign
from api.routes.newsletters import generate_newsletter_html

N="50026b07-0483-4d11-854a-834210141a22"
C="fb1c4daa5e"
F="8f0ff0c1-9147-4845-9731-04971bf649cd"
T=datetime(2026,10,31,14,tzinfo=timezone.utc)

def main():
    if datetime.now(timezone.utc)>=T: raise RuntimeError("Send time passed")
    db=get_supabase_client()
    issue=db.table("newsletters").select("*").eq("id",N).single().execute().data
    if issue["status"]!="scheduled" or issue["mailchimp_campaign_id"]!=C: raise RuntimeError("Campaign changed")
    links=db.table("newsletter_posts").select("blog_post_id").eq("newsletter_id",N).order("position").execute().data
    ids=[p["blog_post_id"] for p in links]
    if len(ids)!=7 or F in ids: raise RuntimeError("Unexpected existing story list")
    fruit=db.table("blog_posts").select("id,title,status,image_url,blogger_url").eq("id",F).single().execute().data
    if fruit["status"]!="published" or not fruit["image_url"] or not fruit["blogger_url"]: raise RuntimeError("Fruit not ready")
    mc=MailchimpCampaign()
    camp=mc.client.campaigns.get(C)
    if camp["status"] not in ("schedule","paused","save") or camp.get("emails_sent"): raise RuntimeError("Cannot edit")
    original=mc.client.campaigns.content.get(C)["html"]
    if fruit["title"] in original: raise RuntimeError("Already attached")
    story=mc._format_article_link(fruit["title"],fruit["blogger_url"],"SHOPPERS","Frozen fruit keeps longer, makes meal prep easier, and can help control grocery spending.",fruit["image_url"])
    marker="<!-- Youdle discovery -->"
    if original.count(marker)!=1 or original.count('<li style="margin:0 0 24px')!=7: raise RuntimeError("Unexpected email markup")
    updated=original.replace(marker,story+"\n"+marker)
    if camp["status"]=="schedule": mc.client.campaigns.actions.unschedule(C)
    mc.client.campaigns.content.update(C,{"html":updated})
    verified=mc.client.campaigns.content.get(C)["html"]
    if fruit["title"] not in verified or verified.count('<li style="margin:0 0 24px')!=8: raise RuntimeError("Email update unverified")
    result=mc.schedule_campaign(C,T)
    if not result.get("success"): raise RuntimeError("Schedule failed: "+str(result))
    if mc.client.campaigns.get(C)["status"]!="schedule": raise RuntimeError("Schedule unverified")
    db.table("newsletter_posts").insert({"id":str(uuid4()),"newsletter_id":N,"blog_post_id":F,"position":7}).execute()
    db.table("newsletters").update({"html_content":updated}).eq("id",N).execute()
    print("SUCCESS: eight articles, frozen fruit added, same Mailchimp campaign scheduled",flush=True)

if __name__=="__main__": main()
