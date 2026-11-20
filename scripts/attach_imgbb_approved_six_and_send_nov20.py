"""One-time, date-gated attachment of six preapproved images via existing ImgBB.

Works against original published Blogger entries, existing weekly newsletter
and existing Mailchimp account. Never generates, rewrites, or duplicates posts.
Uses only approved images from temporary Canva staging. Inserting thumbnail
fallbacks into ImgBB is a compromise to make this Friday's deadline; never
place expiring Canva links in the live newsletter. Run through cron once.
"""
import asyncio
import base64
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from imgbb_upload import upload_image_to_imgbb
from supabase_storage import get_supabase_client
from api.blogger_client import get_blogger_client
from newsletter_edition import sync_weekly_draft
from api.routes.newsletters import generate_newsletter_html, send_newsletter
from mailchimp_campaign import MailchimpCampaign
from scripts.repair_nov17_newsletter_photos import _insert_photo

ISSUE_ID = "3901a1ee-21a9-44fe-b687-a9a990d22132"
PHOTOS = [{"postId":"27e4976c-4c0e-47da-b482-1f47b6796bd5","alt":"Roasted cabbage wedges on a Thanksgiving table","sourceUrl":"https://media.canva.com/v2/image-resize/format:JPG/height:133/quality:75/uri:ifs%3A%2F%2FM%2F78c556ef-5765-468a-a58a-07c358537895/watermark:F/width:200?csig=AAAAAAAAAAAAAAAAAAAAAN1eXeWoITlpItQFihCcYW789UE4P38EugpebD0fIUGB&exp=1795211959&osig=AAAAAAAAAAAAAAAAAAAAAMJ8WR4paeoVietRcHnjLhFN7EqmGTpEznj1WH95ikU1&signer=media-rpc&token=AAIAAU0AJDc4YzU1NmVmLTU3NjUtNDY4YS1hNThhLTA3YzM1ODUzNzg5NQAAAAABofr4mtg46pLXT0KWDGV7k69y4xu3z4ptXZMUKTNuKMlU12TRSQ&x-canva-quality=thumbnail","width":640},{"postId":"862d4c8a-4098-4da0-a963-926133596866","alt":"Roast turkey and vegetables for Thanksgiving","sourceUrl":"https://media.canva.com/v2/image-resize/format:JPG/height:133/quality:75/uri:ifs%3A%2F%2FM%2Fbb20b358-8804-420e-b212-8b616ace145c/watermark:F/width:200?csig=AAAAAAAAAAAAAAAAAAAAAIDJ5SLn8aFcXK9QpJ9CuDDoaV9JzdGoUTThlf6LUrV0&exp=1795210287&osig=AAAAAAAAAAAAAAAAAAAAAEsh9tAcLndAIQLkRD6R6SfvuqYXb2RSdGPEAyfRkE3B&signer=media-rpc&token=AAIAAU0AJGJiMjBiMzU4LTg4MDQtNDIwZS1iMjEyLThiNjE2YWNlMTQ1YwAAAAABofrfF5g1hRRycRhweyj-zz0pct8LoisuEoBBo8_UcBY0g0HIHw&x-canva-quality=thumbnail","width":640},{"postId":"3157b3ce-6ba2-4ef9-8cf5-1acd585b3598","alt":"Hot dog and drink on a food-court tray","sourceUrl":"https://media.canva.com/v2/image-resize/format:JPG/height:133/quality:75/uri:ifs%3A%2F%2FM%2F7b17e4de-25a9-4f56-a567-6f0f0d85539d/watermark:F/width:200?csig=AAAAAAAAAAAAAAAAAAAAAGeMP6GdSypUwqYN9_QHEhyiU61cEuaDQaUCeIIpMI-V&exp=1795212424&osig=AAAAAAAAAAAAAAAAAAAAAFhZz9FHnjsMQ_Nu2nQlYd-aVG20cWKgmwqVeVzN63vU&signer=media-rpc&token=AAIAAU0AJDdiMTdlNGRlLTI1YTktNGY1Ni1hNTY3LTZmMGYwZDg1NTM5ZAAAAAABofr_s0DaHBL61V1asxUP3MaYMu_qfD21gpr5amX0t6abiajT3A&x-canva-quality=thumbnail","width":640},{"postId":"c8379401-aa45-412e-b30a-1a69a3c94aed","alt":"Grocery shopper examining ingredients on a package","sourceUrl":"https://media.canva.com/v2/image-resize/format:JPG/height:133/quality:75/uri:ifs%3A%2F%2FM%2F113dd6b9-5a0d-4fa2-bdcb-05b7a0a4b4ca/watermark:F/width:200?csig=AAAAAAAAAAAAAAAAAAAAAGv2A1dMyH9zNx5Lrpt_NDxdul5CBHrOIvumIV9GeAg6&exp=1795211059&osig=AAAAAAAAAAAAAAAAAAAAALc-jzob70zIEtNMH83jI63BtEuP4FidOixhU5xxDx8B&signer=media-rpc&token=AAIAAU0AJDExM2RkNmI5LTVhMGQtNGZhMi1iZGNiLTA1YjdhMGE0YjRjYQAAAAABofrq3zjzANcvvskopSQjHGVt4SolorHEVgs0oaGJrOc07tImyg&x-canva-quality=thumbnail","width":640},{"postId":"0c7a4eab-0f95-44b4-b061-38dd7cca95eb","alt":"Food delivery bags and takeout containers","sourceUrl":"https://media.canva.com/v2/image-resize/format:JPG/height:133/quality:75/uri:ifs%3A%2F%2FM%2Fbe3d386c-822f-4576-942a-e50cb5776838/watermark:F/width:200?csig=AAAAAAAAAAAAAAAAAAAAACuGqGTBP0INZjzPTuoOgmxABQJvCKFwSJ61kuepVQye&exp=1795209757&osig=AAAAAAAAAAAAAAAAAAAAACUuLUmLloNg9R4Meq45GB7yyJHTWZMgmJhvoNaZ5Uxu&signer=media-rpc&token=AAIAAU0AJGJlM2QzODZjLTgyMmYtNDU3Ni05NDJhLWU1MGNiNTc3NjgzOAAAAAABofrXAUhpoqrH7GEFrqjzde0nlZDybzi20kWt-Pmmz0H_R9HdQA&x-canva-quality=thumbnail","width":640},{"postId":"2360c0a2-1b1f-483f-b19e-52f520cf15b9","alt":"Shopper comparing groceries in a supermarket","sourceUrl":"https://media.canva.com/v2/image-resize/format:JPG/height:133/quality:75/uri:ifs%3A%2F%2FM%2F3daf484b-ce09-4c14-8969-1f20afd96077/watermark:F/width:200?csig=AAAAAAAAAAAAAAAAAAAAAMzp-U_Tu_Nhc0653mmIpAs2rKFjOfp7nhmqwuV97SnD&exp=1795212745&osig=AAAAAAAAAAAAAAAAAAAAAAZKRlRdXAfBQeFZHqeqPgL-lDFQT0T0NTJTA5cc2UKL&signer=media-rpc&token=AAIAAU0AJDNkYWY0ODRiLWNlMDktNGMxNC04OTY5LTFmMjBhZmQ5NjA3NwAAAAABofsEmSgtrJ-yowAAvqKykbZ8YUPc5lnldt7_eqlATIWYLvYS3Q&x-canva-quality=thumbnail","width":640}]
COMPANY_PHOTO_HOST = "https://i.ibb.co/"
JOB_ID = "f0b86d72-f5e9-437d-85ef-760fc3405d11"


def _live_img(post_id, blogger, db, record, alt):
    remote = blogger.get_post(record["blogger_post_id"])
    content = str(remote.get("content") or "")
    urls = re.findall(r'<img\\b[^>]*\\bsrc=["\\\']([^"\\\']+)', content, flags=re.I)
    existing = [x for x in urls if x.startswith(COMPANY_PHOTO_HOST)]
    if existing and not record.get("image_url"):
        url = existing[0]
        updated = _insert_photo(record["html_content"], url, alt)
        result = db.table("blog_posts").update({
            "image_url": url,
            "html_content": updated,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", post_id).eq("status", "published").eq("image_url", "").execute().data or []
        if not result:
            raise RuntimeError("Existing Blogger image could not sync to database")
        return url
    if urls:
        raise RuntimeError("Blogger already contains an unexpected image; do not overwrite")
    return None


def _fetch_staged(source_url):
    if not source_url.startswith("https://media.canva.com/v2/image-resize/"):
        raise RuntimeError("Staging source is not a verified Canva image")
    # Canvas returns a signed view URL. Try the 640px rendering if accepted.
    # When the signature is variant-specific, use the unmodified signed URL.
    bigger = (source_url.replace("/height:133/", "/height:427/")
                        .replace("/width:200?", "/width:640?"))
    urls = [bigger, source_url] if bigger != source_url else [source_url]
    for url in urls:
        try:
            response = requests.get(url, timeout=17, allow_redirects=False)
            if response.status_code != 200:
                continue
            blob = response.content
            if not 2500 <= len(blob) <= 5*1024*1024:
                continue
            if not blob.startswith(bytes.fromhex("ffd8")):
                continue
            return blob
        except requests.RequestException:
            continue
    raise RuntimeError("Approved Canva image could not be downloaded")


def run():
    if datetime.now(ZoneInfo("America/Chicago")).date().isoformat() != "2026-11-20":
        return {"status": "disabled_outside_friday"}
    db = get_supabase_client()
    blogger = get_blogger_client()
    if db is None or not blogger.is_configured():
        raise RuntimeError("Existing Supabase/Blogger service not configured")
    issue = db.table("newsletters").select("*").eq("id", ISSUE_ID).single().execute().data or {}
    if issue.get("status") == "sent":
        return {"status": "already_sent", "campaign_id": issue.get("mailchimp_campaign_id")}
    if issue.get("status") != "draft" or issue.get("mailchimp_campaign_id"):
        raise RuntimeError("Existing newsletter not in safe unsent state")
    ids = [p["postId"] for p in PHOTOS]
    records = db.table("blog_posts").select(
        "id,job_id,category,status,title,image_url,html_content,blogger_post_id,blogger_url"
    ).in_("id", ids).execute().data or []
    by_id = {str(r["id"]): r for r in records}
    if len(by_id) != 6:
        raise RuntimeError("Six original posts were not found")
    count = 0
    for item in PHOTOS:
        post_id,alt = item["postId"],item["alt"]
        p = by_id[post_id]
        if p.get("job_id") != JOB_ID or p.get("status") != "published" or p.get("category") != "SHOPPERS" or not p.get("blogger_post_id"):
            raise RuntimeError("Article identity mismatch: " + post_id)
        if p.get("image_url") and "<img" in (p.get("html_content") or "").lower():
            count += 1
            print("ALREADY COMPLETE "+post_id, flush=True)
            continue
        if p.get("image_url") or "<img" in (p.get("html_content") or "").lower():
            raise RuntimeError("Article has inconsistent partial photo state: " + post_id)
        remote_url = _live_img(post_id, blogger, db, p, alt)
        if remote_url:
            count += 1
            print("RECONCILED "+post_id, flush=True)
            continue
        # No regeneration and no unnecessary external service: ImgBB key
        # is already configured in this same Vercel production project.
        jpeg = _fetch_staged(item["sourceUrl"])
        result = upload_image_to_imgbb(
            image_data=base64.b64encode(jpeg).decode("ascii"),
            name="grocerysos-approved-nov20-"+post_id,
        )
        url = result.get("url") if result.get("success") else None
        if not isinstance(url,str) or not url.startswith(COMPANY_PHOTO_HOST):
            raise RuntimeError("ImgBB upload failed, original unchanged: " + post_id)
        image_response = requests.get(url,timeout=18)
        if image_response.status_code!=200 or not image_response.headers.get("content-type","").startswith("image/"):
            raise RuntimeError("ImgBB hosted photo could not be verified")
        article = _insert_photo(p["html_content"],url,alt)
        updated = blogger.update_post(
            blogger_post_id=p["blogger_post_id"],html_content=article)
        if str(updated.get("blogger_post_id"))!=str(p["blogger_post_id"]):
            raise RuntimeError("Original Blogger post update not confirmed")
        remote = blogger.get_post(p["blogger_post_id"])
        if url not in (remote.get("content") or ""):
            raise RuntimeError("Blogger did not retain ImgBB image URL")
        saved = db.table("blog_posts").update({
            "image_url":url,"html_content":article,
            "updated_at":datetime.now(timezone.utc).isoformat(),
        }).eq("id",post_id).eq("job_id",JOB_ID).eq("status","published").eq("image_url","").execute().data or []
        if not saved:
            raise RuntimeError("Database photo sync failed: " + post_id)
        print("IMG VERIFIED "+post_id,flush=True)
        count += 1
    if count != 6:
        raise RuntimeError("All six photos must be verified before mail")
    edited = sync_weekly_draft(db,generate_newsletter_html,require_complete=True)
    if not edited or not edited.get("newsletter") or str(edited["newsletter"]["id"])!=ISSUE_ID:
        raise RuntimeError("Existing weekly issue could not be rebuilt")
    latest = db.table("newsletters").select("*").eq("id",ISSUE_ID).single().execute().data or {}
    if latest.get("status")!="draft" or latest.get("mailchimp_campaign_id"):
        raise RuntimeError("Issue state changed; no duplicate newsletter")
    membership = db.table("newsletter_posts").select("blog_post_id").eq("newsletter_id",ISSUE_ID).execute().data or []
    if len(membership)!=7:
        raise RuntimeError("Existing issue must contain exactly seven posts")
    articles = db.table("blog_posts").select("id,category,image_url").in_("id",[m["blog_post_id"] for m in membership]).execute().data or []
    shoppers = [x for x in articles if x["category"]=="SHOPPERS"]
    recalls = [x for x in articles if x["category"]=="RECALL"]
    if len(shoppers)!=6 or len(recalls)!=1 or any(not x.get("image_url","").startswith(COMPANY_PHOTO_HOST) for x in shoppers):
        raise RuntimeError("Issue content/photo verification failed")
    html = latest.get("html_content") or ""
    if any(x["image_url"] not in html for x in shoppers):
        raise RuntimeError("Newsletter HTML does not include every image")
    mail = MailchimpCampaign()
    if not mail.client or not mail.list_id:
        raise RuntimeError("Existing Mailchimp credentials unavailable")
    for campaign in mail.client.campaigns.all(get_all=True).get("campaigns", []):
        if (campaign.get("recipients") or {}).get("list_id")!=mail.list_id:
            continue
        if (campaign.get("settings") or {}).get("subject_line")!=latest.get("subject"):
            continue
        if campaign.get("status") in ("sent","sending","schedule"):
            raise RuntimeError("Matching newsletter already sent or scheduled in Mailchimp")
    asyncio.run(send_newsletter(ISSUE_ID))
    final = db.table("newsletters").select("status,mailchimp_campaign_id,sent_at").eq("id",ISSUE_ID).single().execute().data or {}
    if final.get("status")!="sent" or not final.get("mailchimp_campaign_id"):
        raise RuntimeError("Mailchimp send not verified in local database")
    remote = mail.client.campaigns.get(final["mailchimp_campaign_id"])
    if remote.get("status") not in ("sent","sending"):
        raise RuntimeError("Mailchimp send not verified by provider")
    return {"status":"sent_verified","images":count,"campaign_id":final["mailchimp_campaign_id"]}
