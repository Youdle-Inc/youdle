"""Fill nine Oct 27 shopper drafts with GEMINI images and Supabase media.

Strict scope: the nine Oct 27, 2026 articles that currently have no image. Does
not search the web, rewrite stories, use Exa, publish to Blogger, or send mail.
One Gemini request per missing image, no retry loop.
"""
import argparse
import base64
import hashlib
import sys
from datetime import datetime, timezone
from html import escape
from uuid import uuid4

from image_generator import ImageGenerator
from supabase_storage import get_supabase_client, get_supabase_storage


# Immutable, human-approved draft IDs. No arbitrary IDs from workflow inputs.
APPROVED = (
    (
        "58e3a3b8-1f31-45b7-88ea-fe58024b7171",
        "Pumpkin spices and recognizable autumn foods arranged on a kitchen table; editorial photograph, not branded retail packages",
        "Warm natural light, overhead food photo, no people or text",
        "Pumpkin spice ingredients arranged on a kitchen table",
    ),
    (
        "5c1398bc-8c42-4681-bb44-be13e9651c42",
        "Grocery cart with everyday produce and paper price receipts, without imaginary figures or political symbols",
        "Candid real supermarket checkout documentary image, no readable text",
        "A cart of everyday groceries at checkout",
    ),
    (
        "972a26e8-aecd-4620-9102-3e475dd56fa5",
        "Fresh green pandan leaves and pandan-inspired Southeast Asian dessert, natural recognizable green color",
        "Food editorial still-life, close-up in natural daylight, no brands or text",
        "Pandan leaves beside green pandan dessert",
    ),
    (
        "09e4550f-093a-45bb-9ad6-fce067a93248",
        "A person comparing a grocery shopping list and seasonal retail displays, do not depict real Walmart promotions or logos",
        "Natural documentary photo, bright retail aisles, no readable text",
        "Shopper checking a holiday grocery list",
    ),
    (
        "910e0128-1d83-4af7-bd59-59609685a753",
        "Colorful Halloween candy and household budget notes laid out at home without legible prices",
        "Seasonal editorial overhead flat lay, orange and purple accents",
        "Halloween candy and a simple household budget",
    ),
    (
        "d1ecf868-fe29-49f1-b864-fac111d40769",
        "Modern community grocery setting with café seating and people shopping, no fabricated retail brand claims",
        "Candid wide documentary photograph, warm welcoming color",
        "Shoppers in a grocery store with a cafe",
    ),
    (
        "4a3f6a63-e57e-48fd-9f1c-60a6618a59ab",
        "School cafeteria tray with whole foods, fruit and simple unbranded lunch items, no diet or policy text",
        "Authentic institutional food photography, midday light",
        "Balanced foods arranged on a school cafeteria tray",
    ),
    (
        "a688aed1-9712-413e-ad93-c660f51bb429",
        "Two unbranded comparable pantry products side by side on a grocery shelf, no implication of proven shared manufacturing",
        "Shelf-level documentary still life, no fake brands or labels",
        "Two store-brand and national-style pantry items",
    ),
    (
        "82064a28-0199-4956-beb1-0c03fd46aeef",
        "Grocery bags and a smartphone delivery app with no brand logos and no readable claims",
        "Candid kitchen countertop editorial photo, no readable screen",
        "Groceries beside a smartphone showing a generic delivery screen",
    ),
)

def _utcnow():
    return datetime.now(timezone.utc).isoformat()

def run(execute: bool):
    db = get_supabase_client()
    if db is None:
        raise RuntimeError("Supabase client not configured")
    ids = [row[0] for row in APPROVED]
    result = db.table("blog_posts").select(
        "id,title,status,image_url,html_content,blogger_post_id"
    ).in_("id", ids).execute()
    found = {row["id"]: row for row in (result.data or [])}
    if len(found) != len(ids):
        raise RuntimeError("Expected exactly nine approved drafts in dashboard")

    eligible = []
    for post_id, theme, look, alt in APPROVED:
        post = found[post_id]
        if post["status"] != "draft" or post.get("blogger_post_id"):
            raise RuntimeError(f"Refusing image update to non-draft: {post_id}")
        if post.get("image_url") and post.get("image_url") != "{IMAGE_HERE}":
            print(f"SKIP: image already exists for {post['title']}", flush=True)
            continue
        if not post.get("html_content") or "pexels" in post["html_content"].lower():
            raise RuntimeError(f"Post has missing HTML or leftover stock photo: {post_id}")
        eligible.append((post, theme, look, alt))

    print(f"Approved draft images missing: {len(eligible)} of 9", flush=True)
    if not execute:
        print("DRY RUN: no generation, upload or database updates", flush=True)
        return
    if not eligible:
        return

    storage = get_supabase_storage()
    if storage is None:
        raise RuntimeError("Supabase storage not configured")
    generator = ImageGenerator()
    print("Generator: Gemini, one 1K image per missing draft, no retries", flush=True)

    success = 0
    for post, theme, look, alt in eligible:
        post_id, title = post["id"], post["title"]
        print(f"Generating: {title}", flush=True)
        generated = generator.generate_image(
            title=title, theme=theme, look=look, image_size="1K",
            aspect_ratio="16:9"
        )
        if not generated.get("success"):
            print(f"FAIL: Gemini did not return image for {title}", flush=True)
            continue
        mime = generated.get("format", "image/png")
        if mime not in ("image/png", "image/jpeg"):
            print(f"FAIL: unsupported Gemini content type for {title}", flush=True)
            continue
        raw = base64.b64decode(generated["image_data"], validate=True)
        if len(raw) < 5000 or len(raw) > 10 * 1024 * 1024:
            print(f"FAIL: invalid image size for {title}", flush=True)
            continue

        ext = "png" if mime == "image/png" else "jpg"
        filename = f"grocerybrief_{post_id[:8]}_{uuid4().hex[:8]}.{ext}"
        upload = storage.upload_image(
            image_data=generated["image_data"],
            filename=filename, folder="media", content_type=mime,
        )
        if not upload.get("success"):
            print(f"FAIL: permanent storage upload for {title}", flush=True)
            continue

        # Put the image in the existing Dashboard Media Library as well as
        # the article. A failure leaves the article a draft without an image.
        media_row = {
            "filename": filename,
            "original_filename": f"Gemini - {title[:60]}.{ext}",
            "file_path": upload["path"],
            "public_url": upload["url"],
            "mime_type": mime,
            "file_size": len(raw),
            "alt_text": alt,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        try:
            stored_media = db.table("media").insert(media_row).execute()
            if not stored_media.data:
                raise RuntimeError("No media row returned")
            # Existing readers expect the article itself to show the hero
            # image. This is not a source-photo attribution or a product claim.
            img = (
                f'<img src="{escape(upload["url"], quote=True)}" '
                f'alt="{escape(alt, quote=True)}" '
                'style="display:block;width:100%;height:auto;'
                'max-height:520px;object-fit:cover;border-radius:10px;" '
                'loading="lazy"/>'
            )
            html = post["html_content"]
            if '{IMAGE_HERE}' in html:
                html = html.replace('{IMAGE_HERE}', escape(upload["url"], quote=True))
            elif html.startswith('<div class="youdle-brief-article">'):
                html = html.replace(
                    '<div class="youdle-brief-article">',
                    '<div class="youdle-brief-article">' + img, 1
                )
            else:
                html = img + html
            updated = (
                db.table("blog_posts")
                .update({"image_url": upload["url"], "html_content": html, "updated_at": _utcnow()})
                .eq("id", post_id)
                .eq("status", "draft")
                .eq("image_url", "{IMAGE_HERE}")
                .execute()
            )
            if not updated.data:
                raise RuntimeError("Draft update did not save; avoiding incorrect success")
        except Exception as exc:
            # Do not falsely report success; leave an audit trail in logs
            # rather than deleting an image that may have been saved.
            print(f"FAIL: final metadata or article save for {title}: {type(exc).__name__}", flush=True)
            continue
        success += 1
        print(f"SAVED: {title}", flush=True)
    print(f"Image repair finished: {success} saved; {len(eligible)-success} not saved", flush=True)
    if success != len(eligible):
        sys.exit(2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    run(execute=args.execute)
