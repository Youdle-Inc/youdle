"""Send generation notices from verified database rows, never default counts.

Only GitHub Actions calls this script. Missing or inconsistent records result
in a warning, never a fabricated "articles generated" success notice.
"""
import os
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_notifier import EmailNotifier
from supabase_storage import get_supabase_client

DASHBOARD_JOBS_URL = "https://youdle-agent-dashboard.vercel.app/jobs"
DASHBOARD_POSTS_URL = "https://youdle-agent-dashboard.vercel.app/posts"


def generation_notice(job, rows):
    """Return (subject, HTML) built exclusively from saved job/post records."""
    status = (job or {}).get("status")
    if not job:
        return (
            "Youdle alert: generation result could not be verified",
            "GitHub finished a generation workflow, but no matching job record was found.",
        )
    if status not in {"completed", "failed", "cancelled"}:
        return (
            "Youdle alert: generation status requires attention",
            f"Job status is {escape(str(status or 'unknown'))}; no completion was confirmed.",
        )
    if status != "completed":
        error = str(job.get("error") or "See Jobs for the recorded failure.")
        # Do not forward untrusted/provider error dumps or secrets into email.
        if "model_unavailable" in error:
            reason = "Gemini image model unavailable"
        elif "quota_or_rate_limit" in error:
            reason = "Image-service quota or rate limit"
        elif "authentication_or_permission" in error:
            reason = "Image-service authentication or permissions"
        else:
            reason = "Generation failed. Open Jobs for details."
        return (
            f"Youdle alert: article generation {status}",
            f"Article generation {status}. {reason}. No success was claimed.",
        )

    actual = len(rows or [])
    reported = (job.get("result") or {}).get("posts_generated")
    if actual == 0 or reported is None or int(reported) != actual:
        return (
            "Youdle alert: generation count mismatch",
            f"Job marked completed, but saved post count does not match: "
            f"job reported {escape(str(reported))}; database has {actual}. "
            "Inspect Jobs before sending the newsletter.",
        )
    shoppers = sum(str(p.get("category", "")).upper() == "SHOPPERS" for p in rows)
    recalls = sum(str(p.get("category", "")).upper() == "RECALL" for p in rows)
    without_photo = sum(not str(p.get("image_url") or "").startswith("https://") for p in rows)
    headline = f"{actual} saved draft{'s' if actual != 1 else ''}"
    return (
        f"Youdle: {headline} ready for review",
        f"<strong>{actual}</strong> actual saved drafts: {shoppers} shopper, "
        f"{recalls} recall. <strong>{without_photo}</strong> without photos. "
        "Review text and attach photos where relevant before publishing.",
    )


def main():
    run_id = str(os.getenv("SOURCE_GITHUB_RUN_ID", "")).strip()
    if not run_id.isdigit():
        raise SystemExit("SOURCE_GITHUB_RUN_ID must identify an actual workflow run")

    client = get_supabase_client()
    if client is None:
        raise SystemExit("Cannot verify database results; no notification sent")

    matches = (
        client.table("job_queue")
        .select("id,status,error,result,config")
        .contains("config", {"github_run_id": run_id})
        .limit(2).execute()
    )
    jobs = matches.data or []
    if len(jobs) != 1:
        job, posts = None, []
    else:
        job = jobs[0]
        saved = client.table("blog_posts").select("id,category,image_url").eq(
            "job_id", job["id"]
        ).execute()
        posts = saved.data or []

    subject, details = generation_notice(job, posts)
    html = (
        f"<h2>{escape(subject)}</h2><p>{details}</p>"
        f'<p><a href="{DASHBOARD_JOBS_URL}">View Jobs</a> '
        f'&middot; <a href="{DASHBOARD_POSTS_URL}">Review saved drafts</a></p>'
    )
    sent = EmailNotifier().send_notification(subject, html)
    if not sent.get("success"):
        raise SystemExit("Could not deliver verified generation notification")
    print("Generation notification delivered using verified database data.")


if __name__ == "__main__":
    main()
