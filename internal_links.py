"""Validated, low-cost internal links for Grocery Brief articles.

Use existing published Blogger URLs from Supabase. Never invent article URLs,
fetch extra articles through Exa, or send readers to the summarized news site.
"""
import re
from html import escape
from urllib.parse import urlsplit

FEATURES = {
    "budget": {
        "url": "https://www.youdle.io/shop/budget",
        "label": "Shop My Budget on Youdle",
    },
    "recipe": {
        "url": "https://www.youdle.io/shop/recipe",
        "label": "Shop a Recipe on Youdle",
    },
    "lists": {
        "url": "https://www.youdle.io/grocery",
        "label": "Create a grocery list on Youdle",
    },
    "run": {
        "url": "https://www.youdle.io/map?mode=run",
        "label": "Map My Grocery Run on Youdle",
    },
    "community": {
        "url": "https://www.youdle.io/community",
        "label": "Share your grocery find in the Youdle Community",
    },
    "search": {
        "url": "https://www.youdle.io/",
        "label": "Search groceries on Youdle",
    },
}
ALLOWED_HOME = {"https://www.youdle.io/news", "https://news.youdle.io/"}
ALLOWED_FEATURE_URLS = {feature["url"] for feature in FEATURES.values()}
VALID_HOSTS = {"www.youdle.io", "youdle.io", "news.youdle.io"}
STOPWORDS = {
    "the", "and", "for", "are", "with", "from", "that", "this", "your",
    "you", "what", "when", "why", "how", "can", "more", "less", "than",
    "getting", "get", "where", "about", "into", "their", "new", "our",
    "grocery", "groceries", "food", "foods", "youdle", "october", "2026",
    "week", "today", "now", "still", "things", "store", "stores",
}
TOPICS = {
    "prices": {"prices", "price", "inflation", "cost", "costs", "bill",
               "budget", "expensive", "money", "spending", "affordability", "tariffs"},
    "safety": {"recall", "recalled", "salmonella", "listeria", "ecoli",
               "contamination", "allergen", "warning", "safety"},
    "savings": {"coupon", "coupons", "deals", "clearance", "rewards",
                "discounts", "savings", "save", "sale", "loyalty"},
    "meals": {"recipe", "recipes", "meal", "meals", "dinner",
              "ingredients", "cooking", "snacks", "snack"},
}
ANCHOR_PATTERN = re.compile(
    r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", re.IGNORECASE | re.DOTALL
)
HREF_PATTERN = re.compile(
    r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE
)


def is_youdle_url(url):
    try:
        parsed = urlsplit(str(url or "").strip())
        return (
            parsed.scheme == "https"
            and parsed.hostname in VALID_HOSTS
            and not parsed.username and not parsed.password
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


def _terms(text):
    return {
        term for term in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(term) > 2 and term not in STOPWORDS
    }


def choose_feature(title, category="shoppers"):
    """Choose a known, actually linked feature, not an invented landing page."""
    terms = _terms(title)
    if category.lower() == "recall" or terms & TOPICS["safety"]:
        return FEATURES["search"].copy()
    if terms & {"recipe", "recipes", "ingredients", "cooking", "dinner", "meal"}:
        return FEATURES["recipe"].copy()
    if terms & {"route", "trip", "distance", "stop", "stops", "driving"}:
        return FEATURES["run"].copy()
    if terms & (TOPICS["prices"] | TOPICS["savings"]):
        return FEATURES["budget"].copy()
    if terms & {"list", "lists", "pantry", "planning"}:
        return FEATURES["lists"].copy()
    if terms & {"community", "shelfie", "finds"}:
        return FEATURES["community"].copy()
    return FEATURES["search"].copy()


def select_related_articles(title, published_rows, max_items=2):
    """Deterministically select only topically relevant, published Youdle posts.

    The rows come from Supabase, not from a generated URL or an AI guess.
    Past recall *alerts* are excluded because their instructions may be stale.
    """
    subject_terms = _terms(title)
    subject_topics = {k for k, words in TOPICS.items() if subject_terms & words}
    candidates = []
    seen = set()
    for row in published_rows or []:
        url = str(row.get("blogger_url") or "").strip()
        old_title = str(row.get("title") or "").strip()
        if (row.get("status") != "published" or not old_title
                or not url or not is_youdle_url(url)
                or url in seen or old_title.lower() == (title or "").lower()
                or str(row.get("category") or "").upper() == "RECALL"):
            continue
        # Existing Blogger articles have a date/title path on news.youdle.io.
        # Disallow a made-up page that merely has a Youdle domain.
        u = urlsplit(url)
        if u.hostname == "news.youdle.io":
            if not re.match(r"^/\d{4}/\d{2}/[^/]+\.html$", u.path):
                continue
        elif not u.path.startswith("/news/"):
            continue
        comparison_terms = _terms(old_title)
        overlap = subject_terms & comparison_terms
        common_topics = subject_topics & {
            k for k, words in TOPICS.items() if comparison_terms & words
        }
        score = 3 * len(overlap) + 2 * len(common_topics)
        if score < 3:
            continue
        seen.add(url)
        candidates.append((score, len(overlap), {
            "url": url, "title": old_title
        }))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for _, _, entry in candidates[:max_items]]


def prompt_link_guidance(feature, related):
    """Small text addition to the *existing* generation prompt, no LLM calls."""
    lines = [
        "MANDATORY YOUDLE LINK POLICY: All clickable links in the published article",
        "must point to a relevant, existing Youdle feature or previously published",
        "Youdle article. Credit reporting publications in plain text, without links.",
        "Never link the outside reporting URL or official website in this article.",
        f'Feature to reference naturally: {feature["label"]} = {feature["url"]}.',
    ]
    if related:
        lines.append("Relevant previously published Youdle articles (choose only if useful):")
        lines.extend(f'- {item["title"]}: {item["url"]}' for item in related)
    else:
        lines.append("No verified related Youdle article is available. Never invent one.")
    lines.append("Keep all article URLs exact. Avoid generic or repetitive link blocks.")
    return "\n".join(lines)


def extract_anchor_urls(html):
    urls = []
    for match in ANCHOR_PATTERN.finditer(html or ""):
        attrs = HREF_PATTERN.search(match.group("attrs"))
        if attrs:
            urls.append(attrs.group(1) if attrs.group(1) is not None else attrs.group(2))
    return urls


def apply_internal_links(html, feature, related):
    """Enforce internal-only URLs and insert meaningful in-network links.

    Returns (new_html, list_of_removed_destinations). Does not rewrite
    unrelated text, and never changes source attribution to a false claim.
    """
    allowed = ALLOWED_FEATURE_URLS | ALLOWED_HOME | {
        item["url"] for item in (related or [])
    }
    removed = []

    def clean(match):
        href = HREF_PATTERN.search(match.group("attrs"))
        url = ((href.group(1) if href.group(1) is not None else href.group(2))
               if href else "")
        if url in allowed and is_youdle_url(url):
            return match.group(0)
        removed.append(url or "(missing href)")
        return match.group("body")

    result = ANCHOR_PATTERN.sub(clean, html or "")
    existing = set(extract_anchor_urls(result))
    additions = []
    if not (existing & ALLOWED_FEATURE_URLS):
        additions.append(
            '<p>For your next shopping trip, '
            f'<a href="{escape(feature["url"], quote=True)}">'
            f'{escape(feature["label"])}</a>.</p>'
        )
    missing_related = [
        item for item in (related or [])
        if item["url"] not in existing
    ]
    if missing_related:
        links = " and ".join(
            f'<a href="{escape(item["url"], quote=True)}">'
            f'{escape(item["title"])}</a>'
            for item in missing_related
        )
        additions.append(f"<p>Related Youdle coverage: {links}.</p>")

    if additions:
        result = re.sub(
            r"</div>\s*$", "\n" + "\n".join(additions) + "\n</div>",
            result, flags=re.IGNORECASE, count=1
        )
    return result, removed
