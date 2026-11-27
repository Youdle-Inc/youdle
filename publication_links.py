"""Check public editorial URLs from the same contexts readers use."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx


IMAGE_HOSTS = {"i.ibb.co", "ibb.co"}
STORY_HOSTS = {"news.youdle.io", "www.youdle.io", "youdle.io", "grocerysos.com", "www.grocerysos.com"}
BLOG_ORIGIN = "https://news.youdle.io/"


def _parts(url):
    try:
        parts = urlsplit(url)
        if parts.scheme in ("https", "http") and not parts.username and not parts.password and not parts.port:
            return parts
    except ValueError:
        pass
    return None


def _is_photo(url):
    parts = _parts(url)
    return parts is not None and parts.hostname in IMAGE_HOSTS


def _is_story(url):
    parts = _parts(url)
    if parts is None or parts.hostname not in STORY_HOSTS:
        return False
    if parts.hostname == "news.youdle.io":
        return parts.path.endswith(".html") and not parts.path.startswith("/p/")
    return parts.path.startswith("/news/")


class _Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.photos = set()
        self.stories = set()
        self.feed(html)

    def handle_starttag(self, tag, values):
        attrs = dict(values)
        if tag == "a":
            href = (attrs.get("href") or "").strip()
            if _is_story(href):
                self.stories.add(href)
        elif tag in ("img", "source"):
            src = (attrs.get("src") or "").strip()
            candidates = [source.split()[0] for source in (attrs.get("srcset") or "").split(",") if source.strip()]
            for url in [src] + candidates:
                url = "https:" + url if url.startswith("//") else url
                if _is_photo(url):
                    self.photos.add(url)


def _check_url(url, referer, is_photo):
    allowed = _is_photo if is_photo else _is_story
    kind = "photo" if is_photo else "story"
    expected = "image/" if is_photo else "text/html"
    try:
        for _ in range(4):
            with httpx.stream("GET", url, timeout=5, follow_redirects=False,
                              headers={"Referer": referer, "User-Agent": "Mozilla/5.0"}) as response:
                if response.status_code == 200 and response.headers.get("Content-Type", "").lower().startswith(expected):
                    return
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                destination = urljoin(url, response.headers.get("Location", ""))
                if not allowed(destination) or destination == url:
                    break
                url = destination
    except httpx.HTTPError:
        pass
    raise ValueError(f"The {kind} link did not load: {url}. Check the public URL and try again.")


def check_article_photos(html, previous_html="", image_url=""):
    photos = _Links(html).photos - _Links(previous_html).photos
    if image_url and _is_photo(image_url):
        photos.add(image_url)
    for url in sorted(photos):
        _check_url(url, BLOG_ORIGIN, is_photo=True)


def check_newsletter_links(html, referer):
    links = _Links(html)
    for url in sorted(links.photos):
        _check_url(url, referer, is_photo=True)
    for url in sorted(links.stories):
        _check_url(url, referer, is_photo=False)
