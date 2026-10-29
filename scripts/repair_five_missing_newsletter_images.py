"""Repair five Oct 28 local-time shopper drafts with Gemini photos hosted on ImgBB.

Strict scope: five newly generated Oct 29 UTC articles with missing image placeholders. Does
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
from imgbb_upload import upload_image_to_imgbb
from supabase_storage import get_supabase_client, get_supabase_storage


# Immutable, human-approved draft IDs. No arbitrary IDs from workflow inputs.
APPROVED = (
    (
        "7ecec519-62c5-43cf-a606-680c14f2cd5c",
        "A shopper doing a careful grocery price comparison, two similar unbranded shelf items, shopping list and calculator visible, no invented numbers or legible receipts",
        "Natural candid supermarket documentary photograph, aisle view with practical everyday groceries, no logos or text",
        "Shopper comparing prices and checking a grocery list",
    ),
    (
        "803af121-b84a-452d-8e21-bec0805e1fff",
        "Variety of naturally and artificially colored candy pieces in shallow bowls alongside fruits and plants used for natural colors, no scientific or taste test claims",
        "Bright, accurate food editorial still life photographed from above in natural daylight, no packaging or text",
        "Colorful candies and ingredients for natural food dyes",
    ),
    (
        "567e0825-eba3-48c3-be1a-0e1b972441ce",
        "A modest Thanksgiving meal grocery basket with turkey, potatoes, sweet potatoes, green beans and cranberry ingredients displayed on a kitchen table, without any retailer or price claims",
        "Warm, authentic family kitchen food photography, daylight, budget conscious, no Walmart logos or price tags",
        "Thanksgiving groceries arranged together for a home meal",
    ),
    (
        "48a88fb7-93ef-4677-ac1a-d4d21b6857d7",
        "Close up of imported fresh produce at a wholesale market quality-check station, gloved hands examining citrus and leafy vegetables, no fake government seal or implication of actual contamination",
        "Credible documentary food handling photo with bright clean neutral light, no brands or text",
        "Gloved hands examining fresh produce at a market",
    ),
    (
        "6a543135-42eb-47fb-a69e-7f6fbbd0ed92",
        "A quiet, clean unbranded fast casual restaurant dining room with a counter and a few customers, no identifiable chain logos, no fabricated closure signs",
        "Candid wide angle lifestyle photograph in realistic midday light, neutral tones, no readable text",
        "An unbranded fast casual restaurant dining area",
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
        "id,title,status,image_url,html_content,blogger_post_id,blogger_url,blogger_published_at"
    ).in_("id", ids).execute()
    found = {row["id"]: row for row in (result.data or [])}
    if len(found) != len(ids):
        raise RuntimeError("Expected exactly five approved drafts in dashboard")

    eligible = []
    for post_id, theme, look, alt in APPROVED:
        post = found[post_id]
        # Blogger draft IDs are assigned before publication. Do not mistake an
        # unpublished Blogger draft for a live article. Reject publication markers.
        if (post["status"] != "draft" or post.get("blogger_url") or post.get("blogger_published_at")):
            raise RuntimeError(f"Refusing image update to published article: {post_id}")
        if post.get("image_url") and post.get("image_url") != "{IMAGE_HERE}":
            print(f"SKIP: image already exists for {post['title']}", flush=True)
            continue
        if not post.get("html_content") or "pexels" in post["html_content"].lower():
            raise RuntimeError(f"Post has missing HTML or leftover stock photo: {post_id}")
        eligible.append((post, theme, look, alt))

    print(f"Approved draft images missing: {len(eligible)} of {len(APPROVED)}", flush=True)
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
        # ImgBB hosts the image shown in the article and in Mailchimp.
        # Do not store a placeholder or an unverified URL if upload fails.
        hosted = upload_image_to_imgbb(
            generated["image_data"],
            name=f"youdle-grocerybrief-{post_id[:8]}",
        )
        public_image_url = hosted.get("url") if hosted.get("success") else ""
        if not isinstance(public_image_url, str) or not public_image_url.startswith("https://i.ibb.co/"):
            print(f"FAIL: ImgBB did not return an image URL for {title}", flush=True)
            continue

        # Preserve a separate copy of the image in the Youdle media library.
        backup = storage.upload_image(
            image_data=generated["image_data"],
            filename=filename, folder="media", content_type=mime,
        )
        if not backup.get("success"):
            print(f"WARN: Supabase media backup upload failed for {title}", flush=True)

        try:
            if backup.get("success"):
                media_row = {
                    "filename": filename,
                    "original_filename": f"Gemini - {title[:60]}.{ext}",
                    "file_path": backup["path"],
                    "public_url": backup["url"],
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
                except Exception as media_exc:
                    print(f"WARN: Supabase media index failed for {title}: {type(media_exc).__name__}", flush=True)

            # The hero image must be the same for the dashboard, saved HTML,
            # Blogger articles, and the newsletter campaign.
            img = (
                f'<img src="{escape(public_image_url, quote=True)}" '
                f'alt="{escape(alt, quote=True)}" '
                'style="display:block;width:100%;height:auto;'
                'max-height:520px;object-fit:cover;border-radius:10px;" '
                'loading="lazy"/>'
            )
            html = post["html_content"]
            if '{IMAGE_HERE}' in html:
                html = html.replace('{IMAGE_HERE}', escape(public_image_url, quote=True))
            elif html.startswith('<div class="youdle-brief-article">'):
                html = html.replace(
                    '<div class="youdle-brief-article">',
                    '<div class="youdle-brief-article">' + img, 1
                )
            else:
                html = img + html
            updated = (
                db.table("blog_posts")
                .update({"image_url": public_image_url, "html_content": html, "updated_at": _utcnow()})
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
