"""
Youdle Blog Agent API
FastAPI server that wraps the Python blog generation pipeline.
"""
import sys
import os
from uuid import uuid4
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add parent directory to path so we can import existing modules (for supabase_storage, etc.)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Add current directory to path so we can import routes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from job_lifecycle import reconcile_stale_jobs

app = FastAPI(
    title="Youdle Blog Agent API",
    description="API for managing blog post generation, article search, and content review",
    version="1.0.0"
)

# CORS for Next.js frontend
cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://youdle.vercel.app",
    "https://youdle-agent-dashboard.vercel.app",
    "https://youdle.io",
    "https://www.youdle.io",
]

# Match the dashboard's stable Vercel domain and every generated preview
# deployment for that project, without allowing unrelated *.vercel.app sites.
VERCEL_DASHBOARD_ORIGIN_REGEX = (
    r"^https://youdle-agent-dashboard(?:-[a-z0-9-]+)?\.vercel\.app$"
)

# Add additional origins from environment variable if set
extra_origins = os.getenv("CORS_ORIGINS", "")
if extra_origins:
    cors_origins.extend([o.strip() for o in extra_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=VERCEL_DASHBOARD_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import routes
from routes import search, generate, jobs, newsletters, media, actions

# Include routers
app.include_router(search.router, prefix="/api/search", tags=["Search"])
app.include_router(generate.router, prefix="/api/generate", tags=["Generate"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(newsletters.router, prefix="/api/newsletters", tags=["Newsletters"])
app.include_router(media.router, prefix="/api/media", tags=["Media"])
app.include_router(actions.router, prefix="/api/actions", tags=["Actions"])


@app.get("/")
async def root():
    """API root - health check"""
    return {
        "status": "healthy",
        "service": "Youdle Blog Agent API",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/health")
async def health_check():
    """Report live API/database health and provider configuration."""
    checks = {
        "api": {
            "status": "available",
            "message": "FastAPI is responding",
        }
    }

    try:
        from supabase_storage import get_supabase_client

        supabase = get_supabase_client()
        if supabase is None:
            raise RuntimeError("Supabase is not configured")
        supabase.table("job_queue").select("id").limit(1).execute()
        checks["supabase"] = {
            "status": "available",
            "message": "Database query succeeded",
        }
    except Exception as error:
        checks["supabase"] = {
            "status": "unavailable",
            "message": f"Database check failed ({type(error).__name__})",
        }

    provider_variables = {
        "openai": ("OPENAI_API_KEY",),
        "exa": ("EXA_API_KEY",),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "imgbb": ("IMGBB_API_KEY",),
        "blogger": (
            "BLOGGER_BLOG_ID",
            "BLOGGER_CLIENT_ID",
            "BLOGGER_CLIENT_SECRET",
            "BLOGGER_REFRESH_TOKEN",
        ),
        "mailchimp": ("MAILCHIMP_API_KEY", "MAILCHIMP_LIST_ID"),
        "github": ("GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO"),
    }
    for provider, variables in provider_variables.items():
        configured = all(os.getenv(variable) for variable in variables)
        if provider == "gemini":
            configured = any(os.getenv(variable) for variable in variables)
        checks[provider] = {
            "status": "configured" if configured else "not_configured",
            "message": "Credentials present" if configured else "Credentials missing",
        }

    overall_status = (
        "healthy"
        if checks["supabase"]["status"] == "available"
        else "degraded"
    )
    return {
        "status": overall_status,
        "service": "Youdle Blog Agent API",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/stats")
async def get_stats():
    """Get overall system statistics"""
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise RuntimeError("Supabase is not configured")
        reconcile_stale_jobs(supabase)
        
        # Get counts from database
        jobs_result = supabase.table("job_queue").select("id, status").execute()
        posts_result = supabase.table("blog_posts").select("id, status, category").execute()
        
        jobs_data = jobs_result.data if jobs_result.data else []
        posts_data = posts_result.data if posts_result.data else []
        
        # Calculate stats
        total_jobs = len(jobs_data)
        running_jobs = len([j for j in jobs_data if j.get("status") == "running"])
        completed_jobs = len([j for j in jobs_data if j.get("status") == "completed"])
        failed_jobs = len([j for j in jobs_data if j.get("status") == "failed"])
        
        total_posts = len(posts_data)
        draft_posts = len([p for p in posts_data if p.get("status") == "draft"])
        reviewed_posts = len([p for p in posts_data if p.get("status") == "reviewed"])
        published_posts = len([p for p in posts_data if p.get("status") == "published"])
        shoppers_posts = len([p for p in posts_data if p.get("category") == "SHOPPERS"])
        recall_posts = len([p for p in posts_data if p.get("category") == "RECALL"])
        
        # Get newsletter counts
        newsletters_result = supabase.table("newsletters").select("id, status").execute()
        newsletters_data = newsletters_result.data if newsletters_result.data else []

        total_newsletters = len(newsletters_data)
        draft_newsletters = len([n for n in newsletters_data if n.get("status") == "draft"])
        scheduled_newsletters = len([n for n in newsletters_data if n.get("status") == "scheduled"])
        sent_newsletters = len([n for n in newsletters_data if n.get("status") == "sent"])

        return {
            "jobs": {
                "total": total_jobs,
                "running": running_jobs,
                "completed": completed_jobs,
                "failed": failed_jobs
            },
            "posts": {
                "total": total_posts,
                "draft": draft_posts,
                "reviewed": reviewed_posts,
                "published": published_posts,
                "by_category": {
                    "shoppers": shoppers_posts,
                    "recall": recall_posts
                }
            },
            "newsletters": {
                "total": total_newsletters,
                "draft": draft_newsletters,
                "scheduled": scheduled_newsletters,
                "sent": sent_newsletters
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        # Return empty stats if database not configured
        return {
            "jobs": {"total": 0, "running": 0, "completed": 0, "failed": 0},
            "posts": {
                "total": 0, "draft": 0, "reviewed": 0, "published": 0,
                "by_category": {"shoppers": 0, "recall": 0}
            },
            "newsletters": {"total": 0, "draft": 0, "scheduled": 0, "sent": 0},
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@app.get("/api/newsletter-readiness")
async def get_newsletter_readiness():
    """
    Get current newsletter readiness status for this week.

    Returns published article counts vs requirements and next newsletter date.
    """
    try:
        # Import check_blog_status module
        from check_blog_status import (
            check_publish_status,
            REQUIRED_SHOPPERS,
            REQUIRED_RECALL,
            REQUIRED_TOTAL
        )
        import pytz
        from datetime import timedelta

        # Get current publish status
        status = check_publish_status()

        if not status.get("success"):
            return status

        # Calculate next Thursday 9 AM CST
        tz = pytz.timezone('America/Chicago')
        now = datetime.now(tz)

        # Find days until Thursday (Thursday = 3 in weekday())
        days_until_thursday = (3 - now.weekday()) % 7

        # If it's Thursday and past 9 AM, use next Thursday
        if days_until_thursday == 0 and now.hour >= 9:
            days_until_thursday = 7

        next_thursday = now + timedelta(days=days_until_thursday)
        next_thursday = next_thursday.replace(hour=9, minute=0, second=0, microsecond=0)

        # Calculate what's still needed
        shoppers_needed = max(0, REQUIRED_SHOPPERS - status["shoppers_published"])
        recall_needed = max(0, REQUIRED_RECALL - status["recall_published"])

        return {
            "success": True,
            "week_start": status["week_start"],
            "shoppers_published": status["shoppers_published"],
            "shoppers_required": REQUIRED_SHOPPERS,
            "recall_published": status["recall_published"],
            "recall_required": REQUIRED_RECALL,
            "total_published": status["published_posts"],
            "total_required": REQUIRED_TOTAL,
            "meets_requirement": status["meets_requirement"],
            "shoppers_needed": shoppers_needed,
            "recall_needed": recall_needed,
            "next_newsletter": next_thursday.isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)



