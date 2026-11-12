"""
Newsletter API Routes
Endpoints for managing Mailchimp newsletter campaigns.
"""
import sys
import os
from uuid import uuid4
from typing import Optional, List
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import pytz
except ImportError:
    pytz = None

router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================

class NewsletterCreate(BaseModel):
    """Request to create a newsletter"""
    title: Optional[str] = None
    subject: Optional[str] = None
    post_ids: List[str]


class NewsletterUpdate(BaseModel):
    """Request to update a newsletter"""
    title: Optional[str] = None
    subject: Optional[str] = None
    post_ids: Optional[List[str]] = None


class BlogPostSummary(BaseModel):
    """Summary of a blog post for newsletter"""
    id: str
    title: str
    category: str
    blogger_url: Optional[str] = None


class Newsletter(BaseModel):
    """Newsletter model"""
    id: str
    title: str
    subject: str
    html_content: str
    status: str
    mailchimp_campaign_id: Optional[str] = None
    mailchimp_web_id: Optional[str] = None
    scheduled_for: Optional[str] = None
    sent_at: Optional[str] = None
    emails_sent: int = 0
    open_rate: Optional[float] = None
    click_rate: Optional[float] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str
    posts: List[BlogPostSummary] = []


class NewsletterListResponse(BaseModel):
    """Response for listing newsletters"""
    newsletters: List[Newsletter]
    total: int


# ============================================================================
# Helper Functions
# ============================================================================

POSTGREST_PAGE_SIZE = 1000
POSTGREST_IN_CHUNK_SIZE = 50


def _chunks(values: List[str], size: int = POSTGREST_IN_CHUNK_SIZE):
    """Yield bounded lists so PostgREST URLs and result caps stay predictable."""
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _ordered_rows_by_id(rows: List[dict], ordered_ids: List[str]) -> List[dict]:
    """Restore an explicit caller-provided order after a PostgREST ``in`` query."""
    rows_by_id = {str(row["id"]): row for row in rows if row.get("id") is not None}
    return [rows_by_id[str(row_id)] for row_id in ordered_ids if str(row_id) in rows_by_id]


def _get_ordered_post_titles(supabase, post_ids: List[str]) -> List[str]:
    """Fetch post titles while preserving the order in ``post_ids``."""
    if not post_ids:
        return []

    result = supabase.table("blog_posts").select("id, title").in_("id", post_ids).execute()
    ordered_posts = _ordered_rows_by_id(result.data or [], post_ids)
    return [post["title"] for post in ordered_posts]


def _get_used_post_ids(supabase, candidate_ids: List[str]) -> set[str]:
    """Return used IDs among the supplied candidates without scanning the junction table."""
    unique_candidate_ids = list(dict.fromkeys(candidate_ids))
    if not unique_candidate_ids:
        return set()

    used_ids = set()
    for candidate_chunk in _chunks(unique_candidate_ids):
        offset = 0
        while True:
            result = (
                supabase.table("newsletter_posts")
                .select("blog_post_id")
                .in_("blog_post_id", candidate_chunk)
                .order("blog_post_id")
                .range(offset, offset + POSTGREST_PAGE_SIZE - 1)
                .execute()
            )
            rows = result.data or []
            used_ids.update(str(row["blog_post_id"]) for row in rows)
            if len(rows) < POSTGREST_PAGE_SIZE:
                break
            offset += POSTGREST_PAGE_SIZE
    return used_ids


def _attach_posts_to_newsletters(supabase, newsletters: List[dict]) -> List[dict]:
    """Attach ordered post summaries to a page of newsletters in two batch queries."""
    if not newsletters:
        return newsletters

    newsletter_ids = [str(newsletter["id"]) for newsletter in newsletters]
    links = []
    for newsletter_chunk in _chunks(newsletter_ids):
        offset = 0
        while True:
            links_result = (
                supabase.table("newsletter_posts")
                .select("newsletter_id, blog_post_id, position")
                .in_("newsletter_id", newsletter_chunk)
                .order("newsletter_id")
                .order("position")
                .order("blog_post_id")
                .range(offset, offset + POSTGREST_PAGE_SIZE - 1)
                .execute()
            )
            page = links_result.data or []
            links.extend(page)
            if len(page) < POSTGREST_PAGE_SIZE:
                break
            offset += POSTGREST_PAGE_SIZE

    links_by_newsletter: dict[str, List[dict]] = {newsletter_id: [] for newsletter_id in newsletter_ids}
    for link in links:
        newsletter_id = str(link.get("newsletter_id", ""))
        if newsletter_id in links_by_newsletter:
            links_by_newsletter[newsletter_id].append(link)

    for newsletter_links in links_by_newsletter.values():
        newsletter_links.sort(key=lambda link: (link.get("position") or 0, str(link.get("blog_post_id", ""))))

    post_ids = list(dict.fromkeys(
        str(link["blog_post_id"])
        for link in links
        if link.get("blog_post_id") is not None
    ))
    posts_by_id = {}
    for post_chunk in _chunks(post_ids):
        posts_result = (
            supabase.table("blog_posts")
            .select("id, title, category, blogger_url")
            .in_("id", post_chunk)
            .execute()
        )
        posts_by_id.update({
            str(post["id"]): post
            for post in (posts_result.data or [])
            if post.get("id") is not None
        })

    for newsletter in newsletters:
        newsletter_links = links_by_newsletter.get(str(newsletter["id"]), [])
        newsletter["posts"] = [
            posts_by_id[str(link["blog_post_id"])]
            for link in newsletter_links
            if str(link.get("blog_post_id")) in posts_by_id
        ]

    return newsletters


def _parse_utc_datetime(value: str) -> datetime:
    """Parse a database timestamp into an aware UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def get_next_thursday_9am_cst() -> datetime:
    """
    Calculate the next Thursday at 9 AM CST (Central Time), returned as UTC for Mailchimp.
    """
    if pytz is None:
        # Fallback: approximate CST as UTC-6
        utc_now = datetime.utcnow()
        cst_now = utc_now - timedelta(hours=6)

        days_until_thursday = (3 - cst_now.weekday()) % 7
        if days_until_thursday == 0 and cst_now.hour >= 9:
            days_until_thursday = 7

        next_thursday_cst = cst_now.replace(hour=9, minute=0, second=0, microsecond=0)
        next_thursday_cst += timedelta(days=days_until_thursday)

        # Convert back to UTC
        return next_thursday_cst + timedelta(hours=6)

    cst = pytz.timezone('America/Chicago')
    utc = pytz.UTC

    now = datetime.now(cst)
    days_until_thursday = (3 - now.weekday()) % 7

    # If today is Thursday but past 9 AM, get next week
    if days_until_thursday == 0 and now.hour >= 9:
        days_until_thursday = 7

    next_thursday = now.replace(hour=9, minute=0, second=0, microsecond=0)
    next_thursday += timedelta(days=days_until_thursday)

    # Convert to UTC for Mailchimp API
    return next_thursday.astimezone(utc).replace(tzinfo=None)


def get_newsletter_with_posts(supabase, newsletter_id: str) -> Optional[dict]:
    """
    Get a newsletter with its associated posts.
    """
    # Get newsletter
    result = supabase.table("newsletters").select("*").eq("id", newsletter_id).maybe_single().execute()
    if result is None or not result.data:
        return None

    newsletter = result.data

    # Get associated posts
    posts_result = supabase.table("newsletter_posts").select(
        "blog_post_id, position"
    ).eq("newsletter_id", newsletter_id).order("position").execute()

    posts = []
    if posts_result.data:
        post_ids = [p["blog_post_id"] for p in posts_result.data]
        if post_ids:
            blog_posts_result = supabase.table("blog_posts").select(
                "id, title, category, blogger_url"
            ).in_("id", post_ids).execute()

            if blog_posts_result.data:
                # Maintain order from newsletter_posts
                post_map = {p["id"]: p for p in blog_posts_result.data}
                posts = [post_map[pid] for pid in post_ids if pid in post_map]

    newsletter["posts"] = posts
    return newsletter


def _spellcheck_subject(subject: str) -> str:
    """
    Auto-correct spelling errors in newsletter subject lines.
    Preserves proper nouns, brands, numbers, and common abbreviations.
    """
    try:
        from spellchecker import SpellChecker
    except ImportError:
        # If spellchecker not installed, return unchanged
        return subject

    spell = SpellChecker()

    # Words to never correct (brands, proper nouns, abbreviations)
    preserve_words = {
        # Brands
        'walmart', 'target', 'kroger', 'costco', 'aldi', 'publix', 'safeway',
        'albertsons', 'wegmans', 'heb', 'meijer', 'trader', "joe's", 'joes',
        'whole', 'foods', 'amazon', 'instacart', 'doordash', 'uber', 'eats',
        'grubhub', 'shipt', 'gopuff', 'youdle',
        # Government/organizations
        'fda', 'usda', 'cdc', 'epa', 'snap', 'wic',
        # Common abbreviations
        'gmo', 'vs', 'etc', 'inc', 'llc', 'co',
        # Time-related
        "week's", 'weekly', "today's", "tomorrow's",
        # Common grocery terms
        'probiotic', 'probiotics', 'prebiotic', 'prebiotics', 'keto',
        'gluten', 'vegan', 'organic', 'non-gmo', 'superfood', 'superfoods',
    }

    words = subject.split()
    corrected_words = []

    for word in words:
        # Skip if it's a number, has numbers, or is very short
        if any(c.isdigit() for c in word) or len(word) <= 2:
            corrected_words.append(word)
            continue

        # Strip punctuation for checking but preserve it
        stripped = word.lower().strip('.,;:!?()[]"\'—-–…')

        # Skip if it's in our preserve list
        if stripped in preserve_words:
            corrected_words.append(word)
            continue

        # Skip if starts with capital (likely proper noun) and word is known
        if word[0].isupper() and stripped in spell:
            corrected_words.append(word)
            continue

        # Check if word is misspelled
        if stripped and stripped not in spell:
            correction = spell.correction(stripped)
            # Only correct if we have a suggestion and it's different
            if correction and correction != stripped:
                # Preserve original casing pattern
                if word[0].isupper():
                    correction = correction.capitalize()
                # Preserve punctuation
                if word != stripped:
                    prefix = ''
                    suffix = ''
                    for i, c in enumerate(word):
                        if c.isalpha():
                            prefix = word[:i]
                            break
                    for i, c in enumerate(reversed(word)):
                        if c.isalpha():
                            suffix = word[len(word)-i:] if i > 0 else ''
                            break
                    correction = prefix + correction + suffix
                corrected_words.append(correction)
            else:
                corrected_words.append(word)
        else:
            corrected_words.append(word)

    return ' '.join(corrected_words)


def generate_content_driven_subject(post_titles: list) -> str:
    """Preview actual stories instead of a generic weekly label or story count."""
    from newsletter_edition import preview_subject
    return preview_subject([{"title": title} for title in post_titles])


def clean_title_for_subject(title: str) -> str:
    """Clean and optimize article title for subject line use."""
    import re

    # Remove common article prefixes
    cleaned = re.sub(r'^(Breaking|News|Update|Alert|Latest):\s*', '', title, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Convert to sentence case (proper for subject lines)
    cleaned = cleaned.lower()
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]

    # Restore proper nouns and brands
    proper_nouns = {
        r'\buber\b': 'Uber',
        r'\bwhole foods\b': 'Whole Foods',
        r'\bwalmart\b': 'Walmart',
        r'\btarget\b': 'Target',
        r'\bkroger\b': 'Kroger',
        r'\bcostco\b': 'Costco',
        r'\baldi\b': 'Aldi',
        r'\bfda\b': 'FDA',
        r'\busda\b': 'USDA',
        r'\bsnap\b': 'SNAP',
        r'\bgmo\b': 'GMO'
    }

    for pattern, replacement in proper_nouns.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    # Words that should never end a truncated title (incomplete phrases)
    bad_ending_words = {
        'the', 'a', 'an',  # articles
        'to', 'of', 'for', 'with', 'in', 'on', 'at', 'by', 'from',  # prepositions
        'and', 'or', 'but', 'nor',  # conjunctions
        'is', 'are', 'was', 'were', 'be', 'been', 'being',  # be verbs
        'has', 'have', 'had',  # have verbs
        'will', 'would', 'could', 'should', 'may', 'might', 'must',  # modals
        'this', 'that', 'these', 'those',  # demonstratives
        'here\'s', 'there\'s', 'it\'s', 'what\'s', 'who\'s',  # contractions
    }

    # Shorten if needed (target ~45 chars to leave room for pattern suffix)
    if len(cleaned) > 45:
        words = cleaned.split(' ')
        shortened = ''
        last_good_shortened = ''

        for word in words:
            test_len = len(shortened + ' ' + word) if shortened else len(word)
            if test_len <= 42:
                shortened = (shortened + ' ' + word) if shortened else word
                # Track last "good" ending (not an incomplete word)
                if word.lower().rstrip('.,;:!?') not in bad_ending_words:
                    last_good_shortened = shortened
            else:
                break

        # Use the last semantically complete phrase, or fall back to shortened
        final = last_good_shortened if last_good_shortened else shortened

        # Only add ellipsis if we actually truncated
        if final and len(final) < len(cleaned):
            return final.rstrip('.,;:!?') + '...'
        return final if final else cleaned[:42] + '...'

    return cleaned


def generate_newsletter_html(supabase, post_ids: List[str], subject: str = None, image_overrides: dict = None) -> str:
    """
    Generate newsletter HTML from blog post IDs.
    
    Args:
        supabase: Supabase client
        post_ids: List of blog post IDs
        subject: Newsletter subject line to use as dynamic headline (Issue #857 fix)
    """
    from mailchimp_campaign import MailchimpCampaign

    # Fetch article-specific images and body copy for informative summaries.
    posts_result = supabase.table("blog_posts").select(
        "id, title, category, blogger_url, image_url, html_content"
    ).in_("id", post_ids).execute()

    posts = _ordered_rows_by_id(posts_result.data or [], post_ids)

    # Separate by category
    from html import unescape
    import re
    shoppers = []
    recalls = []

    for post in posts:
        body = post.get("html_content") or ""
        body = re.sub(r"<(script|style|h2|h3)\b[^>]*>.*?</\1>", " ", body, flags=re.I | re.S)
        paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", body, flags=re.I | re.S)
        summary = ""
        for paragraph in paragraphs:
            candidate = unescape(re.sub(r"<[^>]+>", " ", paragraph))
            candidate = re.sub(r"\s+", " ", candidate).strip()
            if candidate and len(candidate) >= 50 :
                summary = candidate[:235].rsplit(" ", 1)[0] + ("..." if len(candidate) > 235 else "")
                break
        article = {
            "title": post.get("title", "Article"),
            "url": post.get("blogger_url") or "https://www.youdle.io/news",
            "category": post.get("category", "SHOPPERS"),
            "image_url": post.get("image_url") or (image_overrides or {}).get(post.get("blogger_url"), ""),
            "summary": summary,
        }

        if post.get("category", "").upper() == "RECALL":
            recalls.append(article)
        else:
            shoppers.append(article)

    # Create HTML with dynamic headline (Issue #857 fix)
    mailchimp = MailchimpCampaign()
    return mailchimp.create_newsletter_html(shoppers, recalls, dynamic_headline=subject)


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("", response_model=NewsletterListResponse)
async def list_newsletters(
    status: Optional[str] = Query(default=None, description="Filter by status: draft, scheduled, sent, failed"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0)
):
    """
    List all newsletters with optional status filter.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get count
        count_query = supabase.table("newsletters").select(
            "id", count="exact", head=True
        )
        if status:
            count_query = count_query.eq("status", status)
        count_result = count_query.execute()
        total = count_result.count if hasattr(count_result, 'count') else len(count_result.data or [])

        # Get newsletters
        query = supabase.table("newsletters").select("*").order("created_at", desc=True)
        if status:
            query = query.eq("status", status)
        query = query.range(offset, offset + limit - 1)
        result = query.execute()

        newsletters = _attach_posts_to_newsletters(supabase, result.data or [])

        return NewsletterListResponse(newsletters=newsletters, total=total)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list newsletters: {str(e)}")


@router.get("/published-posts", response_model=List[BlogPostSummary])
async def get_published_posts_for_newsletter():
    """
    Get published blog posts that can be added to a newsletter.
    Returns posts with blogger_url (published to Blogger) from the last 3 days.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Calculate 3-day cutoff
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

        # Get published posts with blogger_url from last 3 days
        result = supabase.table("blog_posts").select(
            "id, title, category, blogger_url"
        ).eq("status", "published").not_.is_("blogger_url", "null").gte(
            "blogger_published_at", cutoff
        ).order(
            "blogger_published_at", desc=True
        ).limit(50).execute()

        all_posts = result.data if result.data else []

        # Filter out posts already in a newsletter (Bug #861 - prevent duplicates)
        if all_posts:
            used_post_ids = _get_used_post_ids(supabase, [post["id"] for post in all_posts])
            all_posts = [p for p in all_posts if p["id"] not in used_post_ids]

        return all_posts

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get published posts: {str(e)}")


@router.get("/status")
async def get_mailchimp_status():
    """
    Check if Mailchimp is configured and ready.
    """
    try:
        from mailchimp_campaign import MailchimpCampaign

        mailchimp = MailchimpCampaign()

        configured = bool(mailchimp.api_key and mailchimp.list_id)

        return {
            "configured": configured,
            "has_api_key": bool(mailchimp.api_key),
            "has_list_id": bool(mailchimp.list_id),
            "server_prefix": mailchimp.server_prefix,
            "message": "Mailchimp is configured" if configured else "Mailchimp not fully configured. Check MAILCHIMP_API_KEY and MAILCHIMP_LIST_ID environment variables."
        }
    except Exception as e:
        return {
            "configured": False,
            "has_api_key": False,
            "has_list_id": False,
            "server_prefix": None,
            "message": f"Error checking Mailchimp status: {str(e)}"
        }


@router.get("/audiences")
async def get_mailchimp_audiences():
    """
    Get all available Mailchimp audiences/lists.
    Returns the list of audiences and the currently active one.
    """
    try:
        from supabase_storage import get_supabase_client
        from mailchimp_campaign import MailchimpCampaign

        mailchimp = MailchimpCampaign()
        audiences = mailchimp.get_audiences()

        # Get current audience from settings or fall back to env var
        current_audience_id = mailchimp.list_id
        supabase = get_supabase_client()
        if supabase:
            try:
                setting = supabase.table("settings").select("value").eq("key", "mailchimp_audience_id").maybe_single().execute()
                if setting is not None and setting.data:
                    current_audience_id = setting.data["value"]
            except:
                pass  # Use default from env

        return {
            "audiences": audiences,
            "current": current_audience_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get audiences: {str(e)}")


@router.post("/audiences/set")
async def set_active_audience(audience_id: str = Query(..., description="The Mailchimp audience/list ID to set as active")):
    """
    Set the active Mailchimp audience for sending newsletters.
    """
    try:
        from supabase_storage import get_supabase_client

        supabase = get_supabase_client()
        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Upsert the setting
        supabase.table("settings").upsert({
            "key": "mailchimp_audience_id",
            "value": audience_id,
            "updated_at": datetime.utcnow().isoformat()
        }, on_conflict="key").execute()

        return {
            "success": True,
            "audience_id": audience_id,
            "message": f"Active audience set to {audience_id}"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set audience: {str(e)}")


@router.get("/{newsletter_id}", response_model=Newsletter)
async def get_newsletter(newsletter_id: str):
    """
    Get a specific newsletter by ID.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        newsletter = get_newsletter_with_posts(supabase, newsletter_id)

        if not newsletter:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        return newsletter

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get newsletter: {str(e)}")


@router.post("", response_model=Newsletter)
async def create_newsletter(data: NewsletterCreate):
    from supabase_storage import get_supabase_client
    from newsletter_edition import sync_weekly_draft
    db = get_supabase_client()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    if not data.post_ids:
        raise HTTPException(status_code=400, detail="At least one published article is required")
    result = sync_weekly_draft(db, generate_newsletter_html, post_ids=data.post_ids, title=data.title, subject=data.subject)
    if not result:
        raise HTTPException(status_code=400, detail="No current published articles are available")
    return get_newsletter_with_posts(db, result['newsletter']['id'])


@router.patch("/{newsletter_id}", response_model=Newsletter)
async def update_newsletter(newsletter_id: str, data: NewsletterUpdate):
    """
    Update a newsletter (only draft newsletters can be updated).
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get existing newsletter
        existing = supabase.table("newsletters").select("*").eq("id", newsletter_id).maybe_single().execute()
        if existing is None or not existing.data:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        if existing.data["status"] != "draft":
            raise HTTPException(status_code=400, detail="Only draft newsletters can be updated")

        # Build update data
        update_data = {"updated_at": datetime.utcnow().isoformat()}

        if data.title is not None:
            update_data["title"] = data.title
        if data.subject is not None:
            update_data["subject"] = data.subject

        # Update posts if provided
        if data.post_ids is not None:
            # Delete existing links
            supabase.table("newsletter_posts").delete().eq("newsletter_id", newsletter_id).execute()

            # Add new links
            for i, post_id in enumerate(data.post_ids):
                supabase.table("newsletter_posts").insert({
                    "id": str(uuid4()),
                    "newsletter_id": newsletter_id,
                    "blog_post_id": post_id,
                    "position": i
                }).execute()

            # Regenerate HTML with updated subject (Issue #857 fix)
            current_subject = data.subject if data.subject is not None else existing.data.get("subject", "")
            from newsletter_edition import existing_images
            update_data["html_content"] = generate_newsletter_html(supabase, data.post_ids, current_subject, image_overrides=existing_images(existing.data.get("html_content")))

        elif data.subject is not None:
            # A subject edit also updates the visible headline without replacing
            # the selected stories or their approved newsletter photos.
            from newsletter_edition import existing_images
            links = supabase.table("newsletter_posts").select("blog_post_id").eq("newsletter_id", newsletter_id).order("position").execute().data or []
            update_data["html_content"] = generate_newsletter_html(
                supabase, [link["blog_post_id"] for link in links], data.subject,
                image_overrides=existing_images(existing.data.get("html_content")))

        # Update newsletter
        supabase.table("newsletters").update(update_data).eq("id", newsletter_id).execute()

        return get_newsletter_with_posts(supabase, newsletter_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update newsletter: {str(e)}")


@router.delete("/{newsletter_id}")
async def delete_newsletter(newsletter_id: str):
    """
    Delete a newsletter (only draft newsletters can be deleted).
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get existing newsletter
        existing = supabase.table("newsletters").select("status").eq("id", newsletter_id).maybe_single().execute()
        if existing is None or not existing.data:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        if existing.data["status"] not in ["draft", "failed"]:
            raise HTTPException(status_code=400, detail="Only draft or failed newsletters can be deleted")

        # Delete newsletter (cascade will delete newsletter_posts)
        supabase.table("newsletters").delete().eq("id", newsletter_id).execute()

        return {"message": "Newsletter deleted", "id": newsletter_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete newsletter: {str(e)}")


@router.get("/{newsletter_id}/preview")
async def preview_newsletter(newsletter_id: str):
    """
    Get the rendered HTML preview of a newsletter.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        result = supabase.table("newsletters").select("html_content").eq("id", newsletter_id).maybe_single().execute()

        if result is None or not result.data:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        return {"html": result.data["html_content"]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get preview: {str(e)}")


def _prepare_newsletter_campaign(db, mailchimp, newsletter):
    """Reuse the same unsent Mailchimp campaign; never send or schedule here."""
    campaign_id = newsletter.get("mailchimp_campaign_id")
    if campaign_id:
        if not mailchimp.client:
            raise HTTPException(status_code=503, detail="Mailchimp is not configured")
        remote = mailchimp.client.campaigns.get(campaign_id)
        if remote.get("status") not in ("save", "paused"):
            raise HTTPException(status_code=409, detail="The existing Mailchimp campaign is already scheduled or sent; no second campaign was created")
        settings = remote.get("settings", {})
        if not settings.get("from_name") or not settings.get("reply_to"):
            raise HTTPException(status_code=409, detail="The existing campaign sender settings are missing; no second campaign was created")
        mailchimp.client.campaigns.content.update(campaign_id, {"html": newsletter["html_content"]})
        mailchimp.client.campaigns.update(campaign_id, {"settings": {
            "subject_line": newsletter["subject"],
            "from_name": settings["from_name"],
            "reply_to": settings["reply_to"],
        }})
        verified = mailchimp.client.campaigns.get(campaign_id)
        verified_html = mailchimp.client.campaigns.content.get(campaign_id).get("html", "")
        from html import unescape
        import re
        expected_urls = re.findall(r'(?:href|src)=["\'](https://[^"\']+)', newsletter["html_content"])
        if (verified.get("settings", {}).get("subject_line") != newsletter["subject"]
                or any(unescape(url) not in unescape(verified_html) for url in expected_urls)):
            raise HTTPException(status_code=502, detail="The existing Mailchimp campaign did not confirm the updated subject, links and images")
        return {"success": True, "campaign_id": campaign_id, "web_id": newsletter.get("mailchimp_web_id")}
    result = mailchimp.create_campaign(subject=newsletter["subject"], html_content=newsletter["html_content"])
    if result.get("success"):
        db.table("newsletters").update({"mailchimp_campaign_id": result["campaign_id"], "mailchimp_web_id": str(result.get("web_id") or ""), "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", newsletter["id"]).execute()
    return result


@router.post("/{newsletter_id}/schedule", response_model=Newsletter)
async def schedule_newsletter(newsletter_id: str):
    """
    Schedule a newsletter for the next Thursday at 9 AM Central.
    Reuse its existing unsent Mailchimp campaign when present.
    """
    try:
        from supabase_storage import get_supabase_client
        from mailchimp_campaign import MailchimpCampaign

        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get newsletter
        newsletter = supabase.table("newsletters").select("*").eq("id", newsletter_id).maybe_single().execute()
        if newsletter is None or not newsletter.data:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        nl = newsletter.data

        if nl["status"] not in ("draft", "failed"):
            raise HTTPException(status_code=400, detail="Only draft or failed newsletters can be scheduled")

        # Create Mailchimp campaign
        mailchimp = MailchimpCampaign()

        campaign_result = _prepare_newsletter_campaign(supabase, mailchimp, nl)

        if not campaign_result.get("success"):
            supabase.table("newsletters").update({
                "status": "failed",
                "error": campaign_result.get("error", "Failed to create campaign"),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", newsletter_id).execute()
            raise HTTPException(status_code=500, detail=campaign_result.get("error", "Failed to create Mailchimp campaign"))

        campaign_id = campaign_result["campaign_id"]

        # Schedule for Thursday 9 AM CST
        schedule_time = get_next_thursday_9am_cst()

        schedule_result = mailchimp.schedule_campaign(campaign_id, schedule_time)

        if not schedule_result.get("success"):
            supabase.table("newsletters").update({
                "status": "failed",
                "mailchimp_campaign_id": campaign_id,
                "error": schedule_result.get("error", "Failed to schedule campaign"),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", newsletter_id).execute()
            raise HTTPException(status_code=500, detail=schedule_result.get("error", "Failed to schedule campaign"))

        # Update newsletter status
        supabase.table("newsletters").update({
            "status": "scheduled",
            "mailchimp_campaign_id": campaign_id,
            "mailchimp_web_id": campaign_result.get("web_id"),
            "scheduled_for": schedule_time.isoformat(),
            "error": None,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", newsletter_id).execute()

        return get_newsletter_with_posts(supabase, newsletter_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to schedule newsletter: {str(e)}")


@router.post("/{newsletter_id}/send", response_model=Newsletter)
async def send_newsletter(newsletter_id: str):
    """
    Send a newsletter immediately.
    Creates a Mailchimp campaign and sends it right away.
    """
    try:
        from supabase_storage import get_supabase_client
        from mailchimp_campaign import MailchimpCampaign

        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get newsletter
        newsletter = supabase.table("newsletters").select("*").eq("id", newsletter_id).maybe_single().execute()
        if newsletter is None or not newsletter.data:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        nl = newsletter.data

        if nl["status"] not in ["draft", "scheduled"]:
            raise HTTPException(status_code=400, detail="Newsletter cannot be sent (already sent or failed)")

        mailchimp = MailchimpCampaign()

        # Use existing campaign or create new one
        campaign_id = nl.get("mailchimp_campaign_id")

        if not campaign_id:
            # Create new campaign
            campaign_result = _prepare_newsletter_campaign(supabase, mailchimp, nl)

            if not campaign_result.get("success"):
                supabase.table("newsletters").update({
                    "status": "failed",
                    "error": campaign_result.get("error", "Failed to create campaign"),
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", newsletter_id).execute()
                raise HTTPException(status_code=500, detail=campaign_result.get("error", "Failed to create Mailchimp campaign"))

            campaign_id = campaign_result["campaign_id"]

        if campaign_id and nl["status"] == "draft" and nl.get("mailchimp_campaign_id"):
            _prepare_newsletter_campaign(supabase, mailchimp, nl)

        # Send campaign
        send_result = mailchimp.send_campaign(campaign_id)

        if not send_result.get("success"):
            supabase.table("newsletters").update({
                "status": "failed",
                "mailchimp_campaign_id": campaign_id,
                "error": send_result.get("error", "Failed to send campaign"),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", newsletter_id).execute()
            raise HTTPException(status_code=500, detail=send_result.get("error", "Failed to send campaign"))

        # Update newsletter status
        supabase.table("newsletters").update({
            "status": "sent",
            "mailchimp_campaign_id": campaign_id,
            "sent_at": datetime.utcnow().isoformat(),
            "scheduled_for": None,
            "error": None,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", newsletter_id).execute()

        return get_newsletter_with_posts(supabase, newsletter_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send newsletter: {str(e)}")


@router.post("/{newsletter_id}/unschedule", response_model=Newsletter)
async def unschedule_newsletter(newsletter_id: str):
    """
    Cancel a scheduled newsletter.
    """
    try:
        from supabase_storage import get_supabase_client
        from mailchimp_campaign import MailchimpCampaign

        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get newsletter
        newsletter = supabase.table("newsletters").select("*").eq("id", newsletter_id).maybe_single().execute()
        if newsletter is None or not newsletter.data:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        nl = newsletter.data

        if nl["status"] != "scheduled":
            raise HTTPException(status_code=400, detail="Newsletter is not scheduled")

        campaign_id = nl.get("mailchimp_campaign_id")

        if campaign_id:
            mailchimp = MailchimpCampaign()
            if not mailchimp.client:
                raise HTTPException(status_code=503, detail="Mailchimp is not configured; the newsletter remains scheduled")
            remote = mailchimp.client.campaigns.get(campaign_id)
            if remote.get("status") == "schedule":
                mailchimp.client.campaigns.actions.unschedule(campaign_id)
                remote = mailchimp.client.campaigns.get(campaign_id)
            if remote.get("status") not in ("save", "paused"):
                raise HTTPException(status_code=409, detail="Mailchimp did not confirm cancellation; the newsletter status was preserved")

        # Update newsletter status back to draft
        supabase.table("newsletters").update({
            "status": "draft",
            "scheduled_for": None,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", newsletter_id).execute()

        return get_newsletter_with_posts(supabase, newsletter_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unschedule newsletter: {str(e)}")


@router.post("/{newsletter_id}/retry", response_model=Newsletter)
async def retry_newsletter(newsletter_id: str):
    """
    Retry a failed newsletter by resetting it to draft status.
    Clears the error while retaining the existing campaign to prevent duplicates.
    """
    try:
        from supabase_storage import get_supabase_client

        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get newsletter
        newsletter = supabase.table("newsletters").select("*").eq("id", newsletter_id).maybe_single().execute()
        if newsletter is None or not newsletter.data:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        nl = newsletter.data

        if nl["status"] != "failed":
            raise HTTPException(status_code=400, detail="Only failed newsletters can be retried")

        # Return to draft while preserving its existing unsent campaign identity
        supabase.table("newsletters").update({
            "status": "draft",
            "error": None,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", newsletter_id).execute()

        return get_newsletter_with_posts(supabase, newsletter_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retry newsletter: {str(e)}")


@router.post("/queue-articles", response_model=Newsletter)
async def queue_articles():
    draft = await auto_create_newsletter()
    if draft['status'] != 'draft':
        raise HTTPException(status_code=409, detail="This week's edition is already scheduled or sent; no second newsletter was created")
    return await schedule_newsletter(draft['id'])


@router.post("/publish-now", response_model=Newsletter)
async def publish_now_auto():
    draft = await auto_create_newsletter()
    if draft['status'] != 'draft':
        raise HTTPException(status_code=409, detail="This week's edition is already scheduled or sent; no second newsletter was created")
    return await send_newsletter(draft['id'])


@router.post("/auto-create", response_model=Newsletter)
async def auto_create_newsletter():
    from supabase_storage import get_supabase_client
    from newsletter_edition import sync_weekly_draft
    db = get_supabase_client()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    result = sync_weekly_draft(db, generate_newsletter_html)
    if not result:
        raise HTTPException(status_code=400, detail="No current published articles are available")
    return get_newsletter_with_posts(db, result['newsletter']['id'])


@router.post("/{newsletter_id}/sync-stats", response_model=Newsletter)
async def sync_newsletter_stats(newsletter_id: str):
    """
    Sync campaign statistics from Mailchimp for a sent newsletter.
    """
    try:
        from supabase_storage import get_supabase_client
        from mailchimp_campaign import MailchimpCampaign

        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get newsletter
        newsletter = supabase.table("newsletters").select("*").eq("id", newsletter_id).maybe_single().execute()
        if newsletter is None or not newsletter.data:
            raise HTTPException(status_code=404, detail="Newsletter not found")

        nl = newsletter.data
        campaign_id = nl.get("mailchimp_campaign_id")

        if not campaign_id:
            raise HTTPException(status_code=400, detail="Newsletter has no Mailchimp campaign")

        mailchimp = MailchimpCampaign()
        status_result = mailchimp.get_campaign_status(campaign_id)

        if not status_result.get("success"):
            raise HTTPException(status_code=500, detail=status_result.get("error", "Failed to get campaign status"))

        # Update stats
        update_data = {
            "emails_sent": status_result.get("emails_sent", 0),
            "updated_at": datetime.utcnow().isoformat()
        }

        # Try to get report for open/click rates
        if mailchimp.client:
            try:
                report = mailchimp.client.reports.get(campaign_id)
                update_data["open_rate"] = report.get("opens", {}).get("open_rate", 0)
                update_data["click_rate"] = report.get("clicks", {}).get("click_rate", 0)
            except Exception:
                pass

        supabase.table("newsletters").update(update_data).eq("id", newsletter_id).execute()

        return get_newsletter_with_posts(supabase, newsletter_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync stats: {str(e)}")


# ============================================================================
# Helper for auto-create trigger
# ============================================================================

async def check_auto_create_newsletter():
    """Append later publications to the same weekly draft; never send here."""
    try:
        from supabase_storage import get_supabase_client
        from newsletter_edition import sync_weekly_draft
        db = get_supabase_client()
        if db is not None:
            sync_weekly_draft(db, generate_newsletter_html, require_complete=True)
    except Exception as error:
        print(f"Weekly newsletter draft refresh failed: {error}")
