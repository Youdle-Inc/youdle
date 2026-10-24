"""Fill six approved Grocery Brief drafts with GEMINI images and Supabase media.

Strict scope: the six Oct 24, 2026 articles that currently have no image. Does
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
        "45fa315c-13c1-4769-a393-c4e5245513c2",
        "Hands cooking three family dinners in an inviting lived-in home kitchen "
        "with vegetables, grains, pasta and a grocery list in view; one adult "
        "working at the counter, captured candidly from the side, never looking "
        "at the camera. Do not suggest the dinners have been taste-tested.",
        "Warm documentary lifestyle photography, one candid preparation moment, "
        "wide 16:9 composition with natural sunlight and authentic home detail.",
        "A home cook using one grocery list for three dinners",
    ),
    (
        "88c65fa4-d1e9-44bb-993e-182355fb0fda",
        "Ready-made dinners in plain unbranded supermarket trays, showing "
        "different portion sizes and serving options. No Aldi logos, products, "
        "store promises, or real menu claims. A customer's hands, if present, "
        "compare two meal sizes without facing the camera.",
        "Natural shelf-side documentary photograph, overhead three-quarter "
        "angle, realistic refrigeration and varied food textures.",
        "Illustration of prepared meals in different serving sizes",
    ),
    (
        "a12cde02-7620-463c-8565-5b8c8669651a",
        "A colorful spread of everyday high-fiber foods: sweet potatoes, "
        "edamame, beans, oats, greens and prunes. Show distinct edible foods "
        "accurately, without claims about precise nutrition amounts.",
        "Quiet editorial food still life, overhead view, textured neutral "
        "tabletop, modest styling, diverse ingredients and clear space.",
        "Everyday foods that can contribute dietary fiber",
    ),
    (
        "b8d665bb-29d2-4e2c-9d28-726ecc7f0a7d",
        "Trick-or-treat candy in generic unbranded wrappers, an adult's hands "
        "carefully checking the ingredient panel. The ingredient text is "
        "unreadable, no fake allergen guidance, no real package or brand logos. "
        "Seasonal Halloween context but not frightening.",
        "Intimate candid editorial macro photograph, orange and purple "
        "autumn accents, hands in focus, no faces and no readable text.",
        "An adult checking ingredients on Halloween candy",
    ),
    (
        "b150c5b6-fe15-4b0a-96b0-c54b458504a4",
        "A grocery shelf fitted with realistic electronic shelf labels and "
        "generic groceries. Labels show no invented prices, UPCs, promotions "
        "or specific brands. Clearly show that labels are small electronic "
        "displays rather than paper stickers.",
        "Documentary close-up at shelf level, clean neutral light and "
        "credible supermarket details. No people, no readable text.",
        "Electronic shelf labels on a supermarket shelf",
    ),
    (
        "228ca4c8-ea09-4d21-a22a-9440c46d47e5",
        "Food safety editorial illustration showing an official-looking but "
        "unbranded checklist, dry beans and rolls as broad food categories. "
        "Do not suggest these are actual recalled items, show broken glass "
        "inside food, invent safety identifiers, or fabricate agency seals.",
        "Restrained newsroom still life with checklist and magnifying glass, "
        "blue neutral background, no readable text, no people.",
        "Illustration of checking food safety alerts, not recalled packaging",
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
        raise RuntimeError("Expected exactly six approved drafts in dashboard")

    eligible = []
    for post_id, theme, look, alt in APPROVED:
        post = found[post_id]
        if post["status"] != "draft" or post.get("blogger_post_id"):
            raise RuntimeError(f"Refusing image update to non-draft: {post_id}")
        if post.get("image_url"):
            print(f"SKIP: image already exists for {post['title']}", flush=True)
            continue
        if not post.get("html_content") or "pexels" in post["html_content"].lower():
            raise RuntimeError(f"Post has missing HTML or leftover stock photo: {post_id}")
        eligible.append((post, theme, look, alt))

    print(f"Approved draft images missing: {len(eligible)} of 6", flush=True)
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
            if html.startswith('<div class="youdle-brief-article">'):
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
                .is_("image_url", "null")
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
