"""One-time, idempotent photo repair for the eight Nov 17, 2026 GrocerySOS articles.

Do not regenerate text, republish, create duplicate Blogger posts, or send mail.
Published posts are updated IN PLACE by existing Blogger ID. No providers or
database mutations are called in dry run mode. Usage: python -m
scripts.repair_nov17_newsletter_photos [--execute]
"""
import argparse
import base64
from datetime import datetime, timezone
from html import escape

from image_generator import ImageGenerator, summarize_image_failure
from supabase_storage import get_supabase_client, get_supabase_storage

# Fixed production IDs, verified against the Nov 17 generation job.
JOB_ID = "f0b86d72-f5e9-437d-85ef-760fc3405d11"
STORIES = {
    "bb69b98f-d229-4d1a-82bf-e4f0914c1483":
        ("Documentary grocery photo of discount grocery shelves and a practical shopping basket, unbranded, no prices", "Discount groceries in a store aisle"),
    "862d4c8a-4098-4da0-a963-926133596866":
        ("Editorial overhead food photo of roast turkey slices, roasted vegetables and herbs on a home dining table", "Roast turkey with vegetables"),
    "0c7a4eab-0f95-44b4-b061-38dd7cca95eb":
        ("Candid editorial still life of generic food delivery bags and unpacked takeout containers in a home kitchen, no logos", "Food delivery placed on a kitchen counter"),
    "2360c0a2-1b1f-483f-b19e-52f520cf15b9":
        ("Realistic documentary photo of a shopper comparing value and premium unbranded pantry staples in grocery aisle, no prices", "Comparable everyday grocery staples on a shelf"),
    "23af1ee8-4a9c-4c82-bfc8-441946be9ec3":
        ("Editorial food photo of unbranded avocado oil poured near sliced ripe avocados on a clean kitchen counter, no brand depiction", "Avocado oil and avocados in a kitchen"),
    "c8379401-aa45-412e-b30a-1a69a3c94aed":
        ("Editorial close-up of a plain unbranded food ingredients list on a generic packaged product and kitchen ingredients; all text unreadable", "Packaged food and kitchen ingredients"),
    "27e4976c-4c0e-47da-b482-1f47b6796bd5":
        ("Realistic editorial food photograph of savory sauteed cabbage with miso in a home kitchen, no label or brands", "Savory cooked cabbage with miso"),
    "3157b3ce-6ba2-4ef9-8cf5-1acd585b3598":
        ("Editorial close-up of a plain hot dog and soda in a generic food court setting, no Costco logos or price claims", "Hot dog and drink on food court table"),
}


def _photo_html(url: str, alt: str) -> str:
    return ('<figure class="grocerysos-editorial-image">'
            '<img src="' + escape(url, quote=True) + '" alt="' +
            escape(alt, quote=True) +
            '" style="display:block;width:100%;height:auto;max-height:520px;'
            'object-fit:cover;border-radius:10px;" loading="lazy"/></figure>')


def _insert_photo(html: str, url: str, alt: str) -> str:
    if '<img' in html.lower():
        raise ValueError("Cannot safely insert: existing inline image")
    photo = _photo_html(url, alt)
    if html.lstrip().startswith("<div"):
        from re import sub
        return sub(r"(<div\\b[^>]*>)", lambda match: match.group(1) + photo,
                   html, count=1, flags=2)
    return photo + html


def repair(execute: bool = False) -> None:
    db = get_supabase_client()
    if db is None:
        raise RuntimeError("Newsletter Supabase client unavailable")
    rows = db.table("blog_posts").select(
        "id,job_id,title,status,image_url,html_content,blogger_post_id,blogger_url,archived_at"
    ).in_("id", list(STORIES)).execute().data or []
    found = {str(item["id"]): item for item in rows}
    if len(found) != len(STORIES):
        raise RuntimeError("Expected all eight exact Nov 17 posts")
    eligible = []
    for identifier, (scene, alt) in STORIES.items():
        post = found[identifier]
        if str(post.get("job_id")) != JOB_ID:
            raise RuntimeError("Generation job mismatch: " + identifier)
        if post.get("archived_at"):
            print("SKIP archived: " + identifier, flush=True)
            continue
        if post.get("image_url"):
            print("SKIP already illustrated: " + identifier, flush=True)
            continue
        if post.get("status") not in ("draft", "published"):
            raise RuntimeError("Unexpected status: " + identifier)
        if post["status"] == "published" and not post.get("blogger_post_id"):
            raise RuntimeError("Published post lacks Blogger ID: " + identifier)
        if not post.get("html_content") or "<img" in post["html_content"].lower():
            raise RuntimeError("Unrecognized HTML: " + identifier)
        eligible.append((post, scene, alt))
    print(f"Eligible: {len(eligible)} existing image-less posts, "
          f"{len(STORIES) - len(eligible)} skipped", flush=True)
    if not execute or not eligible:
        print("DRY RUN: no image generation, changes or publication", flush=True)
        return
    storage = get_supabase_storage()
    if storage is None:
        raise RuntimeError("Supabase image storage unavailable")
    generator = ImageGenerator()
    from api.blogger_client import get_blogger_client
    blogger = get_blogger_client()
    errors = []
    for post, scene, alt in eligible:
        post_id = post["id"]
        print("GENERATE " + post_id, flush=True)
        generated = generator.generate_image(
            title=post["title"], theme=scene,
            aspect_ratio="16:9", image_size="1K")
        if not generated.get("success"):
            reason = summarize_image_failure(generated.get("error"))
            errors.append(post_id + ": " + reason)
            if reason in ("model_unavailable", "authentication_or_permission", "quota_or_rate_limit"):
                print("STOP provider unavailable: " + reason, flush=True)
                break
            continue
        mime = generated.get("format")
        if mime not in ("image/png", "image/jpeg", "image/webp"):
            errors.append(post_id + ": bad format")
            continue
        try:
            raw = base64.b64decode(generated["image_data"], validate=True)
        except Exception:
            errors.append(post_id + ": invalid base64")
            continue
        if not 2000 <= len(raw) <= 10 * 1024 * 1024:
            errors.append(post_id + ": invalid size")
            continue
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
        hosted = storage.upload_image(
            image_data=generated["image_data"],
            filename=f"nov17_{post_id}.{extension}", folder="media", content_type=mime,
        )
        url = hosted.get("url") if hosted.get("success") else None
        if not isinstance(url, str) or not url.startswith(
                "https://wziocgpteiozbtgeoplj.supabase.co/storage/v1/object/public/blog-images/"):
            errors.append(post_id + ": storage upload not verified")
            continue
        html = _insert_photo(post["html_content"], url, alt)
        if post.get("blogger_post_id"):
            if not blogger.is_configured():
                errors.append(post_id + ": Blogger credentials missing; left post unchanged")
                continue
            try:
                remote = blogger.get_post(post["blogger_post_id"])
                if remote.get("id") != post["blogger_post_id"]:
                    raise RuntimeError("Remote Blogger identity mismatch")
                if "<img" in str(remote.get("content", "")).lower():
                    raise RuntimeError("Blogger already has an image: avoid overwrite")
                blogger.update_post(
                    blogger_post_id=post["blogger_post_id"], html_content=html,
                )
            except Exception as exc:
                errors.append(post_id + ": Blogger update failed (" + type(exc).__name__ + ")")
                continue
        # Concurrency guard: update only the same, still image-less row.
        query = (db.table("blog_posts").update({
            "image_url": url,
            "html_content": html,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", post_id).eq("job_id", JOB_ID)
            .eq("status", post["status"]))
        # Exact Nov 17 records use empty strings rather than NULLs.
        query = query.eq("image_url", "") if post.get("image_url") == "" else query.is_("image_url", "null")
        saved = query.execute().data or []
        if not saved:
            errors.append(post_id + ": DB compare-and-set failed; inspect Blogger sync")
            continue
        print("SAVED " + post_id, flush=True)
    if errors:
        print("REPAIR INCOMPLETE: " + "; ".join(errors), flush=True)
        raise RuntimeError(f"{len(errors)} post(s) not repaired")
    print("All eligible Nov 17 post image repairs verified in database", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    repair(execute=args.execute)
