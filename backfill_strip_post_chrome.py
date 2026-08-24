"""Strip theme-owned chrome (back-nav links, newsletter signup) from stored posts.

The back link and newsletter signup used to be baked into every post body by
blog_post_html.py. They now live in the Blogger theme, so leaving the old copies
in the stored HTML renders them twice. This backfills existing rows.

    python backfill_strip_post_chrome.py                  # dry run (default)
    python backfill_strip_post_chrome.py --apply          # write Supabase
    python backfill_strip_post_chrome.py --apply --push-blogger
"""

import argparse
import re
import sys

from dotenv import load_dotenv


# A nav-only <div>/<p> whose sole child is a Back to Youdle / News Blog link.
# Two shapes exist in the wild: the generator's original <div> block, and the
# <p><a><strong>...</strong></a></p> that the dashboard's rich-text editor
# rewrites it into (Tailwind classes and all) once a post is edited by hand.
BACK_LINK_BLOCK = re.compile(
    r"<(div|p)\b[^>]*>\s*"
    r"<a\b[^>]*href=[\"']https?://(?:www\.)?(?:news\.)?youdle\.io/?[\"'][^>]*>\s*"
    r"(?:<(?:strong|b|em)\b[^>]*>\s*)?"
    r"(?:&larr;|&#8592;|&#x2190;|←)?\s*"
    r"Back\s+to\s+(?:News\s+Blog|Youdle)\s*"
    r"(?:</(?:strong|b|em)>\s*)?"
    r"</a>\s*"
    # tolerate empty inline wrappers the editor leaves behind, e.g. <strong> </strong>
    r"(?:<(?:strong|b|em)\b[^>]*>(?:\s|&nbsp;)*</(?:strong|b|em)>\s*)*"
    r"</\1>\s*",
    re.IGNORECASE,
)

# The iframe signup block appended at the bottom of the article body.
SIGNUP_BLOCK = re.compile(
    r"<div\b[^>]*\bid=[\"']youdle-newsletter-signup[\"'][^>]*>.*?</div>\s*",
    re.IGNORECASE | re.DOTALL,
)

# Empty paragraphs the editor leaves behind beside the removed block.
EMPTY_PARA = re.compile(r"<p>\s*</p>", re.IGNORECASE)

# Any residual mention the strict block patterns above did not catch.
RESIDUE = re.compile(r"Back\s+to\s+(?:News\s+Blog|Youdle)|youdle-newsletter-signup", re.I)


def clean(html):
    """Return (cleaned_html, blocks_removed)."""
    if not html:
        return html, 0
    cleaned, n1 = BACK_LINK_BLOCK.subn("", html)
    cleaned, n2 = SIGNUP_BLOCK.subn("", cleaned)
    if n1 or n2:
        cleaned = EMPTY_PARA.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, n1 + n2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes to Supabase")
    ap.add_argument("--push-blogger", action="store_true",
                    help="also update live Blogger posts (requires BLOGGER_* creds)")
    ap.add_argument("--limit", type=int, help="only process the first N changed posts")
    args = ap.parse_args()

    load_dotenv()
    from supabase_storage import get_supabase_client

    supabase = get_supabase_client()
    if supabase is None:
        sys.exit("Supabase is not configured (SUPABASE_URL / SUPABASE_KEY).")

    rows, start = [], 0
    while True:
        page = (supabase.table("blog_posts")
                .select("id,title,status,blogger_post_id,html_content")
                .range(start, start + 499).execute().data or [])
        rows += page
        if len(page) < 500:
            break
        start += 500

    changed, residual, unmatched = [], [], []
    for row in rows:
        html = row.get("html_content") or ""
        cleaned, removed = clean(html)
        if removed:
            changed.append((row, cleaned, removed))
            if RESIDUE.search(cleaned):
                residual.append(row["id"])
        elif RESIDUE.search(html):
            unmatched.append(row["id"])

    if args.limit:
        changed = changed[:args.limit]

    live = [c for c in changed if c[0].get("blogger_post_id")]
    print("scanned    %d posts" % len(rows))
    print("to change  %d  (%d draft-only, %d live on Blogger)"
          % (len(changed), len(changed) - len(live), len(live)))
    print("blogger pushes needed: %d" % len(live))
    if unmatched:
        print("WARNING: %d post(s) mention the chrome but matched no pattern, so they "
              "were skipped: %s" % (len(unmatched), unmatched[:5]))
    if residual:
        print("WARNING: %d post(s) still mention the chrome after cleaning "
              "(non-standard markup, review by hand): %s" % (len(residual), residual[:5]))

    if changed:
        row, cleaned, _ = changed[0]
        print("\n--- sample BEFORE ---\n" + (row["html_content"] or "")[:300])
        print("\n--- sample AFTER  ---\n" + cleaned[:300])

    if not args.apply:
        print("\nDRY RUN - no writes performed. Re-run with --apply to commit.")
        return

    blogger = None
    if args.push_blogger:
        sys.path.insert(0, "api")
        from blogger_client import get_blogger_client
        blogger = get_blogger_client()
        if not blogger.is_configured():
            sys.exit("BLOGGER_* credentials missing; cannot push. Drop --push-blogger "
                     "or run where those are set.")

    ok = failed = pushed = 0
    for row, cleaned, _ in changed:
        try:
            supabase.table("blog_posts").update(
                {"html_content": cleaned}).eq("id", row["id"]).execute()
            ok += 1
        except Exception as exc:
            failed += 1
            print("  supabase FAILED %s: %s" % (row["id"], exc))
            continue
        if blogger and row.get("blogger_post_id"):
            try:
                blogger.update_post(row["blogger_post_id"], html_content=cleaned)
                pushed += 1
            except Exception as exc:
                print("  blogger FAILED %s: %s" % (row["id"], exc))

    print("\nsupabase updated %d, failed %d, blogger pushed %d" % (ok, failed, pushed))


if __name__ == "__main__":
    main()
