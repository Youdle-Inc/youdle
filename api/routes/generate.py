"""
Generate API Routes
Endpoints for blog post generation.
"""
import sys
import os
import re
import logging
from html import unescape
from difflib import SequenceMatcher
from uuid import uuid4
from typing import Optional, List
from datetime import datetime
from dateutil.parser import isoparse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

# Add the repository and api directories before importing shared API helpers.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from job_lifecycle import (
    ACTIVE_JOB_STATUSES,
    is_active_job_conflict,
    isoformat_utc,
    list_active_jobs,
    reconcile_stale_jobs,
    transition_job,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class GenerationConfig(BaseModel):
    """Configuration for blog post generation"""
    batch_size: int = Field(default=10, ge=1, le=10)
    search_days_back: int = Field(default=30, ge=1, le=90)
    model: str = "gpt-4"
    use_placeholder_images: bool = False
    use_legacy_orchestrator: bool = False


class GenerationResponse(BaseModel):
    """Response after starting generation"""
    job_id: str
    status: str
    message: str
    config: GenerationConfig


class BlogPost(BaseModel):
    """Blog post model"""
    id: str
    title: str
    html_content: str
    image_url: Optional[str] = None
    category: str
    status: str
    article_url: Optional[str] = None
    created_at: str
    blogger_post_id: Optional[str] = None
    blogger_url: Optional[str] = None
    blogger_published_at: Optional[str] = None
    last_synced_at: Optional[str] = None


def run_generation_task(job_id: str, config: dict):
    """
    Background task to run blog generation.
    Updates job status in Supabase as it progresses.
    """
    from supabase_storage import get_supabase_client

    supabase = get_supabase_client()
    if supabase is None:
        logger.error("Cannot run generation job %s: Supabase is not configured", job_id)
        return

    claimed = transition_job(
        supabase,
        job_id,
        ("pending",),
        {
            "status": "running",
            "started_at": isoformat_utc(),
            "error": None,
        },
    )
    if not claimed:
        logger.info("Generation job %s was no longer pending; skipping execution", job_id)
        return

    try:
        from blog_post_generator import run_generation

        use_langgraph = not config.get("use_legacy_orchestrator", False)
        result = run_generation(
            model=config.get("model", "gpt-4"),
            use_placeholder_images=config.get("use_placeholder_images", False),
            batch_size=config.get("batch_size", 10),
            search_days_back=config.get("search_days_back", 30),
            use_langgraph=use_langgraph,
            job_id=job_id,
        )

        final_state = result.get("final_state") or {}
        if final_state:
            final_posts = final_state.get("final_posts", [])
            # LangGraph owns persistence so posts are written exactly once.
            inserted_count = int(final_state.get("db_inserted", 0) or 0)
            persistence_errors = list(final_state.get("persistence_errors", []) or [])
        else:
            # The legacy orchestrator does not write blog_posts to Supabase.
            final_posts = [
                post for post in (result.get("results") or [])
                if post.get("success", True)
            ]
            inserted_count = 0
            persistence_errors = []

        configured_batch_size = config.get("batch_size", 10)
        final_posts = final_posts[:configured_batch_size]

        if not final_state:
            for post in final_posts:
                current_job = (
                    supabase.table("job_queue")
                    .select("status")
                    .eq("id", job_id)
                    .single()
                    .execute()
                )
                if not current_job.data or current_job.data.get("status") != "running":
                    logger.info("Generation job %s was cancelled before persistence", job_id)
                    return

                try:
                    html_content = post.get("html", "")
                    if not html_content and post.get("file_path"):
                        with open(post["file_path"], "r", encoding="utf-8") as post_file:
                            html_content = post_file.read()

                    article_url = post.get("original_link", "") or post.get("source_url", "")
                    supabase.table("blog_posts").insert({
                        "id": str(uuid4()),
                        "title": post.get("title", ""),
                        "html_content": html_content,
                        "image_url": post.get("image_url", ""),
                        "category": post.get("category", "SHOPPERS").upper(),
                        "status": "draft",
                        "article_url": article_url,
                        "job_id": job_id,
                        "created_at": isoformat_utc(),
                    }).execute()
                    inserted_count += 1
                except Exception as insert_error:
                    message = f"Failed to persist '{post.get('title', 'untitled')}': {insert_error}"
                    persistence_errors.append(message)
                    logger.exception(message)

        if not final_posts:
            raise RuntimeError("Generation completed without producing any blog posts")
        if inserted_count == 0:
            details = "; ".join(persistence_errors[:3])
            raise RuntimeError(
                "Generation produced posts but none were saved to Supabase"
                + (f": {details}" if details else "")
            )

        generation_errors = list(result.get("errors", []) or [])
        if result.get("error"):
            generation_errors.append(str(result["error"]))
        generation_errors.extend(persistence_errors)

        completed = transition_job(
            supabase,
            job_id,
            ("running",),
            {
                "status": "completed",
                "completed_at": isoformat_utc(),
                "result": {
                    "posts_generated": inserted_count,
                    "posts_attempted": len(final_posts),
                    "errors": generation_errors,
                },
                "error": None,
            },
        )
        if not completed:
            logger.info("Generation job %s finished after it was cancelled", job_id)

    except Exception as error:
        logger.exception("Generation job %s failed", job_id)
        try:
            transition_job(
                supabase,
                job_id,
                ACTIVE_JOB_STATUSES,
                {
                    "status": "failed",
                    "completed_at": isoformat_utc(),
                    "error": str(error)[:4000],
                },
            )
        except Exception:
            logger.exception("Could not persist failure state for generation job %s", job_id)


@router.post("/run", response_model=GenerationResponse)
async def run_generation_endpoint(
    background_tasks: BackgroundTasks,
    config: GenerationConfig = GenerationConfig()
):
    """
    Start a new blog post generation run.
    Returns immediately with a job ID that can be used to track progress.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Supabase not configured")
        
        reconcile_stale_jobs(supabase)
        active_jobs = list_active_jobs(supabase)
        if active_jobs:
            active_job = active_jobs[0]
            raise HTTPException(
                status_code=409,
                detail=(
                    "A generation job is already active "
                    f"({active_job['id']}, status: {active_job['status']}). "
                    "Wait for it to finish or mark it cancelled before starting another."
                ),
            )

        job_id = str(uuid4())
        
        # Create job record
        try:
            supabase.table("job_queue").insert({
                "id": job_id,
                "status": "pending",
                "config": config.model_dump(),
                "started_at": None,
                "completed_at": None,
                "result": None,
                "error": None,
            }).execute()
        except Exception as insert_error:
            if is_active_job_conflict(insert_error):
                raise HTTPException(
                    status_code=409,
                    detail="Another generation job started at the same time. Refresh to view it.",
                ) from insert_error
            raise
        
        # Start background task
        background_tasks.add_task(run_generation_task, job_id, config.model_dump())
        
        return GenerationResponse(
            job_id=job_id,
            status="pending",
            message="Generation accepted. Use /api/jobs/{job_id} to track progress.",
            config=config
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start generation: {str(e)}")


@router.get("/posts", response_model=List[BlogPost])
async def get_blog_posts(
    status: Optional[str] = Query(default=None, description="Filter by status: draft, reviewed, published"),
    category: Optional[str] = Query(default=None, description="Filter by category: SHOPPERS or RECALL"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0)
):
    """
    Get generated blog posts from the database.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()
        
        query = supabase.table("blog_posts").select("*").order("created_at", desc=True)
        
        if status:
            query = query.eq("status", status)
        if category:
            query = query.eq("category", category.upper())
        
        query = query.range(offset, offset + limit - 1)
        
        result = query.execute()
        
        return result.data if result.data else []
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get posts: {str(e)}")


@router.get("/posts/{post_id}")
async def get_blog_post(post_id: str):
    """
    Get a specific blog post by ID.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()
        
        result = supabase.table("blog_posts").select("*").eq("id", post_id).single().execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Post not found")
        
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get post: {str(e)}")


@router.patch("/posts/{post_id}/status")
async def update_post_status(
    post_id: str,
    status: str = Query(..., description="New status: draft, reviewed, published")
):
    """
    Update the status of a blog post.
    """
    if status not in ["draft", "reviewed", "published"]:
        raise HTTPException(status_code=400, detail="Invalid status. Must be: draft, reviewed, or published")
    
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()
        
        result = supabase.table("blog_posts").update({
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", post_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Post not found")
        
        return {"message": f"Post status updated to {status}", "post": result.data[0]}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update post: {str(e)}")


@router.delete("/posts/{post_id}")
async def delete_blog_post(post_id: str):
    """
    Delete a blog post.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        result = supabase.table("blog_posts").delete().eq("id", post_id).execute()

        return {"message": "Post deleted", "id": post_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete post: {str(e)}")


class BlogPostUpdate(BaseModel):
    """Blog post update model"""
    title: Optional[str] = None
    html_content: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None


@router.patch("/posts/{post_id}")
async def update_blog_post(post_id: str, updates: BlogPostUpdate):
    """
    Update blog post content (html_content, image_url, category).
    If the post is published to Blogger (has blogger_post_id), also updates Blogger.
    """
    if updates.category and updates.category.upper() not in ["SHOPPERS", "RECALL"]:
        raise HTTPException(status_code=400, detail="Invalid category. Must be: SHOPPERS or RECALL")

    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        # First, get the current post to check if it has blogger_post_id
        current_post = supabase.table("blog_posts").select("*").eq("id", post_id).single().execute()
        if not current_post.data:
            raise HTTPException(status_code=404, detail="Post not found")

        post_data = current_post.data
        blogger_post_id = post_data.get("blogger_post_id")

        # Build update dict from provided fields only
        update_data = {}
        if updates.title is not None:
            update_data["title"] = updates.title
        if updates.html_content is not None:
            update_data["html_content"] = updates.html_content
        if updates.image_url is not None:
            update_data["image_url"] = updates.image_url
        if updates.category is not None:
            update_data["category"] = updates.category.upper()

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        # Always update the updated_at timestamp
        update_data["updated_at"] = datetime.utcnow().isoformat()

        # Update local database
        result = supabase.table("blog_posts").update(update_data).eq("id", post_id).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Post not found")

        updated_post = result.data[0]

        # If post is published to Blogger, sync the changes
        blogger_sync_result = None
        if blogger_post_id:
            try:
                from blogger_client import get_blogger_client
                blogger = get_blogger_client()

                if blogger.is_configured():
                    # Prepare update for Blogger
                    blogger_update_kwargs = {}
                    if updates.title is not None:
                        blogger_update_kwargs["title"] = updates.title
                    if updates.html_content is not None:
                        blogger_update_kwargs["html_content"] = updates.html_content
                    if updates.category is not None:
                        blogger_update_kwargs["labels"] = [updates.category.upper()]

                    if blogger_update_kwargs:
                        blogger_sync_result = blogger.update_post(
                            blogger_post_id=blogger_post_id,
                            **blogger_update_kwargs
                        )
                        # Mark that Blogger is now up to date
                        if blogger_sync_result and "error" not in blogger_sync_result:
                            supabase.table("blog_posts").update({
                                "last_synced_at": datetime.utcnow().isoformat()
                            }).eq("id", post_id).execute()
            except Exception as blogger_err:
                # Don't fail the whole request if Blogger sync fails
                blogger_sync_result = {"error": str(blogger_err)}

        response = {
            "message": "Post updated successfully",
            "post": updated_post
        }

        if blogger_post_id:
            response["blogger_synced"] = blogger_sync_result is not None and "error" not in (blogger_sync_result or {})
            if blogger_sync_result and "error" in blogger_sync_result:
                response["blogger_sync_error"] = blogger_sync_result["error"]

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update post: {str(e)}")


@router.get("/blogger/status")
async def get_blogger_status():
    """
    Check if Blogger API is configured and ready.
    """
    try:
        from blogger_client import get_blogger_client
        client = get_blogger_client()

        return {
            "configured": client.is_configured(),
            "blog_id": client.blog_id if client.is_configured() else None,
            "message": "Blogger API is configured" if client.is_configured() else "Blogger API not configured. Set BLOGGER_BLOG_ID, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, and BLOGGER_REFRESH_TOKEN environment variables."
        }
    except Exception as e:
        return {
            "configured": False,
            "blog_id": None,
            "message": f"Error checking Blogger status: {str(e)}"
        }


@router.post("/posts/{post_id}/publish")
async def publish_post_to_blogger(post_id: str):
    """
    Publish a blog post to Blogger.
    This actually publishes the post to the connected Blogger blog.
    """
    try:
        from supabase_storage import get_supabase_client
        from blogger_client import get_blogger_client

        supabase = get_supabase_client()
        blogger = get_blogger_client()

        # Check if Blogger is configured
        if not blogger.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Blogger API not configured. Please set BLOGGER_BLOG_ID, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, and BLOGGER_REFRESH_TOKEN environment variables."
            )

        # Get the post from database
        result = supabase.table("blog_posts").select("*").eq("id", post_id).single().execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Post not found")

        post = result.data

        # Check if already published to Blogger (has both ID and URL)
        if post.get("blogger_post_id") and post.get("blogger_url"):
            raise HTTPException(
                status_code=400,
                detail=f"Post already published to Blogger. URL: {post.get('blogger_url')}"
            )

        # Publish to Blogger
        labels = [post.get("category", "SHOPPERS")]

        # If post has blogger_post_id but no URL, it's a draft - re-publish it
        if post.get("blogger_post_id"):
            try:
                # First update the draft with current content, then publish
                blogger.update_post(
                    blogger_post_id=post["blogger_post_id"],
                    title=post["title"],
                    html_content=post["html_content"],
                    labels=labels
                )
                blogger_result = blogger.publish_draft(post["blogger_post_id"])
            except Exception as draft_err:
                # If the Blogger post no longer exists (404), create a new one
                if "404" in str(draft_err) or "Not Found" in str(draft_err):
                    blogger_result = blogger.publish_post(
                        title=post["title"],
                        html_content=post["html_content"],
                        labels=labels,
                        is_draft=False
                    )
                else:
                    raise
        else:
            # Create new post on Blogger
            blogger_result = blogger.publish_post(
                title=post["title"],
                html_content=post["html_content"],
                labels=labels,
                is_draft=False
            )

        # Update the database with Blogger info
        update_result = supabase.table("blog_posts").update({
            "status": "published",
            "blogger_post_id": blogger_result["blogger_post_id"],
            "blogger_url": blogger_result["blogger_url"],
            "blogger_published_at": blogger_result.get("published_at") or datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", post_id).execute()

        # Trigger newsletter auto-create check
        try:
            from routes.newsletters import check_auto_create_newsletter
            import asyncio
            asyncio.create_task(check_auto_create_newsletter())
        except Exception as e:
            # Don't fail the publish if newsletter creation fails
            print(f"Warning: Newsletter auto-create check failed: {e}")

        return {
            "message": "Post published to Blogger successfully",
            "blogger_post_id": blogger_result["blogger_post_id"],
            "blogger_url": blogger_result["blogger_url"],
            "post": update_result.data[0] if update_result.data else None
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish to Blogger: {str(e)}")


@router.post("/posts/{post_id}/unpublish")
async def unpublish_post_from_blogger(post_id: str):
    """
    Unpublish a blog post from Blogger.
    Reverts the post to draft status on Blogger and resets local status to reviewed.
    The post remains on Blogger as a draft so it can be re-published later.
    """
    try:
        from supabase_storage import get_supabase_client
        from blogger_client import get_blogger_client

        supabase = get_supabase_client()
        blogger = get_blogger_client()

        # Get the post from database
        result = supabase.table("blog_posts").select("*").eq("id", post_id).single().execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Post not found")

        post = result.data

        # Revert to draft on Blogger if it has a blogger_post_id and Blogger is configured
        blogger_result = None
        if post.get("blogger_post_id") and blogger.is_configured():
            try:
                blogger_result = blogger.revert_to_draft(post["blogger_post_id"])
            except Exception as e:
                # Log but don't fail - post might already be a draft or deleted
                print(f"Warning: Could not revert to draft on Blogger: {e}")

        # Update the database - keep blogger_post_id so we can re-publish, clear URL and published time
        update_result = supabase.table("blog_posts").update({
            "status": "reviewed",
            "blogger_url": None,
            "blogger_published_at": None,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", post_id).execute()

        return {
            "message": "Post reverted to draft on Blogger successfully",
            "blogger_status": blogger_result.get("status") if blogger_result else None,
            "post": update_result.data[0] if update_result.data else None
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unpublish from Blogger: {str(e)}")


def normalize_title(title: str) -> str:
    """Normalize title for comparison: strip HTML, decode entities, lowercase, normalize whitespace."""
    if not title:
        return ""
    # Strip HTML tags
    title = re.sub(r'<[^>]+>', '', title)
    # Decode HTML entities
    title = unescape(title)
    # Lowercase and strip
    title = title.lower().strip()
    # Normalize whitespace
    title = re.sub(r'\s+', ' ', title)
    return title


def title_similarity(title1: str, title2: str) -> float:
    """Calculate similarity ratio between two normalized titles."""
    norm1 = normalize_title(title1)
    norm2 = normalize_title(title2)
    if not norm1 or not norm2:
        return 0.0
    return SequenceMatcher(None, norm1, norm2).ratio()


@router.post("/blogger/sync")
async def sync_with_blogger():
    """
    Enhanced sync with comprehensive four-phase detection and auto-fix:
    Phase 1: Discovery - Fetch all LIVE and DRAFT posts from Blogger
    Phase 2: Verification - Detect status mismatches between local DB and Blogger
    Phase 3: Auto-Fix - Fix detected issues (update local posts)
    Phase 4: Import - Import posts from Blogger that don't exist locally
    """
    try:
        from supabase_storage import get_supabase_client
        from blogger_client import get_blogger_client

        supabase = get_supabase_client()
        blogger = get_blogger_client()

        if not blogger.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Blogger API not configured"
            )

        # === PHASE 1: DISCOVERY ===
        # Fetch all posts from Blogger (both LIVE and DRAFT)
        live_posts = blogger.list_posts(status='LIVE')
        draft_posts = blogger.list_posts(status='DRAFT')

        # Combine and create lookup maps
        all_blogger_posts = live_posts + draft_posts
        blogger_by_id = {bp.get('id'): bp for bp in all_blogger_posts}
        live_post_ids = {bp.get('id') for bp in live_posts}
        draft_post_ids = {bp.get('id') for bp in draft_posts}

        # Get all posts from database
        db_result = supabase.table("blog_posts").select("*").execute()
        db_posts = db_result.data or []

        synced_count = 0
        issues_found = 0
        issues_fixed = 0
        imported_count = 0
        details = []

        # Track which Blogger posts have been matched to local posts
        matched_blogger_ids = set()

        # === PHASE 2 & 3: VERIFICATION AND AUTO-FIX ===
        for db_post in db_posts:
            db_id = db_post['id']
            db_title = db_post.get('title', '')
            db_status = db_post.get('status')
            existing_blogger_id = db_post.get('blogger_post_id')
            existing_blogger_url = db_post.get('blogger_url')

            # Find matching Blogger post using multi-tier matching
            blogger_post = None
            match_type = None

            # Tier 1: Match by blogger_post_id if we have one
            if existing_blogger_id:
                if existing_blogger_id in blogger_by_id:
                    blogger_post = blogger_by_id[existing_blogger_id]
                    match_type = "id_match"
                else:
                    # Blogger post ID exists locally but not found on Blogger (deleted)
                    issues_found += 1
                    if db_status == 'published':
                        # Revert to reviewed, clear all blogger fields
                        update_data = {
                            "status": "reviewed",
                            "blogger_post_id": None,
                            "blogger_url": None,
                            "blogger_published_at": None,
                            "updated_at": datetime.utcnow().isoformat(),
                            "last_synced_at": datetime.utcnow().isoformat()
                        }
                        supabase.table("blog_posts").update(update_data).eq("id", db_id).execute()
                        issues_fixed += 1
                        details.append({
                            "post_id": db_id,
                            "title": db_title,
                            "issue_type": "deleted_on_blogger",
                            "local_status": db_status,
                            "blogger_status": "DELETED",
                            "action_taken": "reverted_to_reviewed_cleared_fields"
                        })
                    continue

            # Tier 2: Fuzzy title match (if no ID match found)
            if not blogger_post:
                best_match = None
                best_score = 0.0

                for bp in all_blogger_posts:
                    score = title_similarity(db_title, bp.get('title', ''))
                    if score > best_score and score >= 0.85:
                        best_score = score
                        best_match = bp

                if best_match:
                    blogger_post = best_match
                    match_type = f"title_match_{best_score:.2f}"

            # Handle posts marked published but never actually published to Blogger
            if not blogger_post and db_status == 'published' and not existing_blogger_url:
                issues_found += 1
                issues_fixed += 1
                update_data = {
                    "status": "reviewed",
                    "blogger_post_id": None,
                    "blogger_url": None,
                    "blogger_published_at": None,
                    "updated_at": datetime.utcnow().isoformat(),
                    "last_synced_at": datetime.utcnow().isoformat()
                }
                supabase.table("blog_posts").update(update_data).eq("id", db_id).execute()
                synced_count += 1
                details.append({
                    "post_id": db_id,
                    "title": db_title,
                    "issue_type": "published_but_not_on_blogger",
                    "local_status": db_status,
                    "blogger_status": "NOT_FOUND",
                    "action_taken": "reverted_to_reviewed"
                })
                continue

            # Process matched posts
            if blogger_post:
                blogger_id = blogger_post.get('id')
                matched_blogger_ids.add(blogger_id)  # Track matched posts
                blogger_url = blogger_post.get('url')
                blogger_status = 'LIVE' if blogger_id in live_post_ids else 'DRAFT'
                blogger_title = blogger_post.get('title', '')
                blogger_content = blogger_post.get('content', '')

                update_data = {
                    "blogger_post_id": blogger_id,
                    "updated_at": datetime.utcnow().isoformat(),
                    "last_synced_at": datetime.utcnow().isoformat()
                }

                issue_detected = False
                issue_type = None
                action_taken = None

                # Case 1: Local published + Blogger DRAFT
                if db_status == 'published' and blogger_status == 'DRAFT':
                    issue_detected = True
                    issue_type = "status_mismatch_local_published_blogger_draft"
                    # Clear URL but keep ID (post exists but not live)
                    update_data["blogger_url"] = None
                    update_data["blogger_published_at"] = None
                    action_taken = "cleared_blogger_url"

                # Case 2: Local published + No blogger_url (incomplete publish)
                elif db_status == 'published' and not existing_blogger_url and blogger_status == 'LIVE':
                    issue_detected = True
                    issue_type = "missing_blogger_url"
                    # Update with correct URL
                    update_data["blogger_url"] = blogger_url
                    update_data["blogger_published_at"] = blogger_post.get('published')
                    update_data["status"] = "published"
                    action_taken = "added_missing_url"

                # Case 3: Local draft/reviewed + Blogger LIVE
                elif db_status in ['draft', 'reviewed'] and blogger_status == 'LIVE':
                    issue_detected = True
                    issue_type = "status_mismatch_local_draft_blogger_live"
                    # Update to published
                    update_data["status"] = "published"
                    update_data["blogger_url"] = blogger_url
                    update_data["blogger_published_at"] = blogger_post.get('published')
                    action_taken = "updated_to_published"

                # Case 4: Normal sync for published posts
                elif blogger_status == 'LIVE':
                    update_data["status"] = "published"
                    update_data["blogger_url"] = blogger_url
                    update_data["blogger_published_at"] = blogger_post.get('published')

                # Timestamp-aware content sync: compare updated times to decide direction
                content_synced = False
                title_synced = False

                blogger_updated_str = blogger_post.get('updated')
                local_updated_str = db_post.get('updated_at')

                blogger_updated_ts = None
                local_updated_ts = None
                try:
                    if blogger_updated_str:
                        blogger_updated_ts = isoparse(blogger_updated_str)
                    if local_updated_str:
                        local_updated_ts = isoparse(local_updated_str)
                except Exception:
                    pass  # If parsing fails, skip content sync

                if blogger_updated_ts and local_updated_ts:
                    if blogger_updated_ts > local_updated_ts:
                        # Blogger is newer — pull content from Blogger to local
                        if blogger_title and blogger_title != db_post.get('title', ''):
                            update_data['title'] = blogger_title
                            title_synced = True

                        if blogger_content:
                            db_content = db_post.get('html_content', '')
                            if blogger_content != db_content:
                                update_data['html_content'] = blogger_content
                                content_synced = True
                    elif local_updated_ts > blogger_updated_ts:
                        # Local is newer — push content from local to Blogger
                        try:
                            push_kwargs = {}
                            local_title = db_post.get('title', '')
                            local_content = db_post.get('html_content', '')

                            if local_title and local_title != blogger_title:
                                push_kwargs['title'] = local_title
                            if local_content and local_content != blogger_content:
                                push_kwargs['html_content'] = local_content

                            if push_kwargs:
                                blogger.update_post(
                                    blogger_post_id=blogger_id,
                                    **push_kwargs
                                )
                        except Exception:
                            pass  # Best-effort push; don't fail the sync

                # Check if update is needed
                needs_update = (
                    db_post.get('status') != update_data.get('status', db_status) or
                    db_post.get('blogger_post_id') != blogger_id or
                    db_post.get('blogger_url') != update_data.get('blogger_url', existing_blogger_url) or
                    db_post.get('blogger_published_at') != update_data.get('blogger_published_at') or
                    content_synced or
                    title_synced
                )

                if needs_update:
                    supabase.table("blog_posts").update(update_data).eq("id", db_id).execute()
                    synced_count += 1

                    if issue_detected:
                        issues_found += 1
                        issues_fixed += 1
                        details.append({
                            "post_id": db_id,
                            "title": blogger_title or db_title,
                            "issue_type": issue_type,
                            "local_status": db_status,
                            "blogger_status": blogger_status,
                            "action_taken": action_taken
                        })

        # === PHASE 4: IMPORT NEW POSTS FROM BLOGGER ===
        # Import posts that exist on Blogger but not in the local database
        for blogger_post in all_blogger_posts:
            blogger_id = blogger_post.get('id')

            # Skip posts that were already matched to local posts
            if blogger_id in matched_blogger_ids:
                continue

            blogger_title = blogger_post.get('title', '')
            blogger_content = blogger_post.get('content', '')
            blogger_url = blogger_post.get('url')
            blogger_status = 'LIVE' if blogger_id in live_post_ids else 'DRAFT'
            blogger_published_at = blogger_post.get('published')

            # Determine local status based on Blogger status
            local_status = 'published' if blogger_status == 'LIVE' else 'draft'

            # Create new post in database
            new_post_id = str(uuid4())
            insert_data = {
                "id": new_post_id,
                "title": blogger_title,
                "html_content": blogger_content,
                "status": local_status,
                "blogger_post_id": blogger_id,
                "blogger_url": blogger_url if blogger_status == 'LIVE' else None,
                "blogger_published_at": blogger_published_at if blogger_status == 'LIVE' else None,
                "category": "SHOPPERS",  # Default category for imported posts
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "last_synced_at": datetime.utcnow().isoformat()
            }

            try:
                supabase.table("blog_posts").insert(insert_data).execute()
                imported_count += 1
                details.append({
                    "post_id": new_post_id,
                    "title": blogger_title,
                    "issue_type": "imported_from_blogger",
                    "local_status": local_status,
                    "blogger_status": blogger_status,
                    "action_taken": "created_new_post"
                })
            except Exception as import_err:
                details.append({
                    "post_id": None,
                    "title": blogger_title,
                    "issue_type": "import_failed",
                    "local_status": None,
                    "blogger_status": blogger_status,
                    "action_taken": f"error: {str(import_err)}"
                })

        # === PHASE 5: PUSH LOCAL DRAFTS TO BLOGGER ===
        # Create drafts on Blogger for local posts that don't have a blogger_post_id
        pushed_count = 0
        for db_post in db_posts:
            # Skip posts that already have a blogger_post_id
            if db_post.get('blogger_post_id'):
                continue

            # Only push drafts and reviewed posts (not published without blogger link)
            if db_post.get('status') not in ['draft', 'reviewed']:
                continue

            try:
                # Create as draft on Blogger
                blogger_result = blogger.publish_post(
                    title=db_post.get('title', 'Untitled'),
                    html_content=db_post.get('html_content', ''),
                    labels=[db_post.get('category', 'SHOPPERS')],
                    is_draft=True  # Create as draft, not published
                )

                # Update local post with blogger_post_id
                supabase.table("blog_posts").update({
                    "blogger_post_id": blogger_result['blogger_post_id'],
                    "last_synced_at": datetime.utcnow().isoformat()
                }).eq("id", db_post['id']).execute()

                pushed_count += 1
                details.append({
                    "post_id": db_post['id'],
                    "title": db_post.get('title', ''),
                    "issue_type": "pushed_draft_to_blogger",
                    "local_status": db_post.get('status'),
                    "blogger_status": "DRAFT",
                    "action_taken": "created_blogger_draft"
                })
            except Exception as push_err:
                details.append({
                    "post_id": db_post['id'],
                    "title": db_post.get('title', ''),
                    "issue_type": "push_failed",
                    "local_status": db_post.get('status'),
                    "blogger_status": None,
                    "action_taken": f"error: {str(push_err)}"
                })

        return {
            "message": f"Sync completed. {synced_count} synced, {issues_fixed} fixed, {imported_count} imported, {pushed_count} pushed to Blogger.",
            "synced_count": synced_count,
            "issues_found": issues_found,
            "issues_fixed": issues_fixed,
            "imported_count": imported_count,
            "pushed_count": pushed_count,
            "blogger_live_posts": len(live_posts),
            "blogger_draft_posts": len(draft_posts),
            "database_posts_checked": len(db_posts),
            "details": details
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync with Blogger: {str(e)}")


@router.post("/blogger/sync-light")
async def sync_with_blogger_light():
    """
    Lightweight sync for page-load use. Only checks local posts that already
    have a blogger_post_id by fetching each individually from Blogger.
    Uses timestamp comparison to avoid overwriting recent local edits.
    """
    try:
        from supabase_storage import get_supabase_client
        from blogger_client import get_blogger_client

        supabase = get_supabase_client()
        blogger = get_blogger_client()

        if not blogger.is_configured():
            return {"message": "Blogger not configured", "synced_count": 0, "posts_checked": 0}

        # Only fetch local posts that already have a blogger_post_id
        db_result = supabase.table("blog_posts") \
            .select("*") \
            .not_.is_("blogger_post_id", "null") \
            .execute()
        db_posts = db_result.data or []

        synced_count = 0

        for db_post in db_posts:
            blogger_post_id = db_post.get("blogger_post_id")
            if not blogger_post_id:
                continue

            try:
                blogger_post = blogger.get_post_by_id(blogger_post_id)
            except Exception:
                continue  # Skip on API error

            if blogger_post is None:
                # Post was deleted on Blogger
                if db_post.get("status") == "published":
                    supabase.table("blog_posts").update({
                        "status": "reviewed",
                        "blogger_post_id": None,
                        "blogger_url": None,
                        "blogger_published_at": None,
                        "updated_at": datetime.utcnow().isoformat(),
                        "last_synced_at": datetime.utcnow().isoformat()
                    }).eq("id", db_post["id"]).execute()
                    synced_count += 1
                continue

            # Determine Blogger status
            blogger_status_raw = blogger_post.get("status", "").upper()
            is_live = blogger_status_raw == "LIVE"

            update_data = {
                "last_synced_at": datetime.utcnow().isoformat()
            }

            # Sync status from Blogger to local
            if is_live:
                update_data["blogger_url"] = blogger_post.get("url")
                update_data["blogger_published_at"] = blogger_post.get("published")
                if db_post.get("status") != "published":
                    update_data["status"] = "published"

            # Timestamp-aware content sync
            blogger_updated_str = blogger_post.get("updated")
            local_updated_str = db_post.get("updated_at")

            blogger_updated_ts = None
            local_updated_ts = None
            try:
                if blogger_updated_str:
                    blogger_updated_ts = isoparse(blogger_updated_str)
                if local_updated_str:
                    local_updated_ts = isoparse(local_updated_str)
            except Exception:
                pass

            if blogger_updated_ts and local_updated_ts:
                blogger_title = blogger_post.get("title", "")
                blogger_content = blogger_post.get("content", "")

                if blogger_updated_ts > local_updated_ts:
                    # Blogger is newer — pull content to local
                    if blogger_title and blogger_title != db_post.get("title", ""):
                        update_data["title"] = blogger_title
                    if blogger_content and blogger_content != db_post.get("html_content", ""):
                        update_data["html_content"] = blogger_content
                elif local_updated_ts > blogger_updated_ts:
                    # Local is newer — push content to Blogger
                    try:
                        push_kwargs = {}
                        local_title = db_post.get("title", "")
                        local_content = db_post.get("html_content", "")

                        if local_title and local_title != blogger_title:
                            push_kwargs["title"] = local_title
                        if local_content and local_content != blogger_content:
                            push_kwargs["html_content"] = local_content

                        if push_kwargs:
                            blogger.update_post(
                                blogger_post_id=blogger_post_id,
                                **push_kwargs
                            )
                    except Exception:
                        pass  # Best-effort push

            # Only write if there are meaningful changes beyond last_synced_at
            if len(update_data) > 1:
                update_data["updated_at"] = datetime.utcnow().isoformat()
                supabase.table("blog_posts").update(update_data).eq("id", db_post["id"]).execute()
                synced_count += 1
            else:
                # Still update last_synced_at
                supabase.table("blog_posts").update(update_data).eq("id", db_post["id"]).execute()

        return {
            "message": f"Light sync completed. {synced_count} posts updated.",
            "synced_count": synced_count,
            "posts_checked": len(db_posts)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Light sync failed: {str(e)}")


