"""Attach one original frozen-fruit photograph to the existing unpublished article.
This script does not publish the article or send an email newsletter.
"""
from datetime import datetime, timezone
from html import escape
from image_generator import ImageGenerator
from imgbb_upload import upload_image_to_imgbb
from supabase_storage import get_supabase_client

POST_ID = "8f0ff0c1-9147-4845-9731-04971bf649cd"
TITLE = "Frozen fruits: The freezer staple that saves time and money"

def main():
    db = get_supabase_client()
    if db is None:
        raise RuntimeError("Supabase unavailable")
    post = db.table("blog_posts").select("id,title,status,image_url,html_content,blogger_post_id").eq("id", POST_ID).single().execute().data
    if post["title"] != TITLE or post["status"] != "draft" or post.get("blogger_post_id"):
        raise RuntimeError("Frozen-fruit draft changed; refusing edit")
    if post.get("image_url"):
        print("Image already attached: " + post["image_url"])
        return
    html = post.get("html_content") or ""
    if not html.lstrip().startswith("<div>") or "<img" in html:
        raise RuntimeError("Unexpected article markup; no image saved")
    result = ImageGenerator().generate_image(
        title=TITLE,
        theme="Realistic frost-coated frozen strawberries, blueberries, sliced peaches and mango pieces in small bowls with an unbranded resealable freezer bag in the background. No words, people, prices or logos.",
        look="Bright approachable kitchen food photography, pale natural counter, soft daylight, vivid real fruit colors, 16:9 editorial still life.",
        image_size="1K", aspect_ratio="16:9",
    )
    if not result.get("success"):
        raise RuntimeError("Gemini image generation failed")
    upload = upload_image_to_imgbb(result["image_data"], name="youdle-frozen-fruit")
    url = upload.get("url") if upload.get("success") else None
    if not url or not url.startswith("https://i.ibb.co/"):
        raise RuntimeError("ImgBB hosting failed")
    tag = '<img src="' + escape(url, quote=True) + '" alt="Frozen berries, peaches and mango on a kitchen counter" style="display:block;width:100%;height:auto;border-radius:10px;" />'
    updated_html = html.replace("<div>", "<div>\n" + tag, 1)
    saved = db.table("blog_posts").update({"image_url": url, "html_content": updated_html, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", POST_ID).eq("status", "draft").is_("image_url", "null").execute()
    if not saved.data:
        raise RuntimeError("Draft update not saved")
    check = db.table("blog_posts").select("image_url,html_content").eq("id",POST_ID).single().execute().data
    if check.get("image_url") != url or tag not in (check.get("html_content") or ""):
        raise RuntimeError("Photo was not verified in draft")
    print("SUCCESS frozen fruit photo attached: " + url, flush=True)

if __name__ == "__main__":
    main()
