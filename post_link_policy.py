"""Reader-first link rules for Youdle grocery articles.

External reporting sources are credited by name in prose and retained in
editorial metadata, not linked as a "read the full story" exit. Exact,
verified Youdle feature destinations can be used selectively (zero or one).
Official food-safety notices may remain linked when needed for recall safety.
"""
from html.parser import HTMLParser
from urllib.parse import urlsplit

FEATURE_URLS = frozenset({
    "https://www.youdle.io/",
    "https://www.youdle.io/shop/budget",
    "https://www.youdle.io/shop/recipe",
    "https://www.youdle.io/grocery",
    "https://www.youdle.io/map?mode=run",
    "https://www.youdle.io/community",
    "https://www.youdle.io/specials",
})
SAFETY_AGENCIES = ("fda.gov", "usda.gov", "cdc.gov", "foodsafety.gov")


def _hostname_is(hostname: str, base: str) -> bool:
    """Match exact domain or subdomain, never suffix-spoofed domains."""
    return hostname == base or hostname.endswith("." + base)


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._active = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href", "")
        self._active = {"href": (href or "").strip(), "text": ""}
        self.anchors.append(self._active)

    def handle_data(self, data):
        if self._active is not None:
            self._active["text"] += data

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            self._active = None


def article_link_issues(html: str, *, is_recall: bool = False) -> list[str]:
    """Return concrete publishing errors; articles without CTAs are valid."""
    parser = _AnchorParser()
    try:
        parser.feed(html or "")
    except (ValueError, TypeError) as exc:
        return [f"Invalid HTML link: {exc}"]

    issues = []
    feature_links = 0
    for anchor in parser.anchors:
        href, text = anchor["href"], anchor["text"].strip().lower()
        parsed = urlsplit(href)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            issues.append("Article contains an invalid or non-HTTPS link")
            continue
        if _hostname_is(host, "youdle.io"):
            normalized = "https://www.youdle.io" + (parsed.path or "/")
            if parsed.query:
                normalized += "?" + parsed.query
            if normalized not in FEATURE_URLS:
                issues.append("Article links to a generic or unverified Youdle destination")
            else:
                feature_links += 1
        elif is_recall and any(_hostname_is(host, base) for base in SAFETY_AGENCIES):
            # Official government recall notices are useful for identifying
            # affected products and verifying any lot numbers or health actions.
            pass
        else:
            issues.append("Article links away to an outside publisher/source")
        if "grocery brief" in text or "read the full story" in text:
            issues.append("Article contains old branding or a source-article call to action")

    if feature_links > 1:
        issues.append("Use at most one contextual Youdle feature link per article")
    return sorted(set(issues))
