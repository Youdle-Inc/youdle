"""Deterministic HTML additions shared by every blog-generation path."""

import re


NEWS_BLOG_URL = "https://news.youdle.io/"
NEWSLETTER_EMBED_URL = "https://www.youdle.io/newsletter-embed"
NEWS_BLOG_BACK_LINK_HTML = f"""<div style="text-align: center; margin: 0 0 10px 0; padding: 8px; background: #f8f9fa; border-radius: 4px;">
  <a href="{NEWS_BLOG_URL}" style="color: #007c89; text-decoration: none; font-weight: 500;">&larr; Back to News Blog</a>
</div>"""
NEWSLETTER_SIGNUP_BLOCK_HTML = f"""<div id="youdle-newsletter-signup" style="margin: 32px 0 0; padding-top: 24px; border-top: 1px solid #e5e7eb;">
  <iframe src="{NEWSLETTER_EMBED_URL}" title="Subscribe to the Youdle Newsletter" loading="lazy" sandbox="allow-forms allow-scripts allow-same-origin" style="display: block; width: 100%; height: 540px; border: 0; border-radius: 16px; background: #f9fafb;"></iframe>
  <p style="margin: 8px 0 0; text-align: center; font-size: 14px;">
    <a href="https://www.youdle.io/newsletter" style="color: #007c89; text-decoration: underline;">Open the newsletter signup page</a>
  </p>
</div>"""

_IMAGE_TAG_PATTERN = re.compile(r"<img\b", re.IGNORECASE)
_NEWS_BLOG_BLOCK_PATTERN = re.compile(
    r"<div\b[^>]*>\s*"
    r"<a\b[^>]*href=[\"']https://news\.youdle\.io/?[\"'][^>]*>"
    r"\s*(?:(?:&larr;|&#8592;|←)\s*)?Back\s+to\s+News\s+Blog\s*"
    r"</a>\s*</div>\s*",
    re.IGNORECASE,
)
_NEWSLETTER_SIGNUP_BLOCK_PATTERN = re.compile(
    r"<div\b[^>]*\bid=[\"']youdle-newsletter-signup[\"'][^>]*>.*?</div>\s*",
    re.IGNORECASE | re.DOTALL,
)
_CLOSING_DIV_PATTERN = re.compile(r"</div\s*>", re.IGNORECASE)


def ensure_news_blog_back_link(html_content: str) -> str:
    """Place one canonical back-to-news link immediately before the lead image."""
    if not html_content or not _IMAGE_TAG_PATTERN.search(html_content):
        return html_content

    # The prompt asks the model for this block, while this post-processor makes
    # the result reliable and idempotent if the model omits or restyles it.
    normalized_html = _NEWS_BLOG_BLOCK_PATTERN.sub("", html_content)
    image_match = _IMAGE_TAG_PATTERN.search(normalized_html)
    if image_match is None:
        return html_content

    before_image = normalized_html[:image_match.start()]
    after_image = normalized_html[image_match.start():]
    separator = "" if before_image.endswith(("\n", "\r")) else "\n"
    return f"{before_image}{separator}{NEWS_BLOG_BACK_LINK_HTML}\n{after_image}"


def ensure_newsletter_signup_block(html_content: str) -> str:
    """Place one canonical signup block at the bottom of the article body."""
    if not html_content:
        return html_content

    normalized_html = _NEWSLETTER_SIGNUP_BLOCK_PATTERN.sub("", html_content).rstrip()
    closing_divs = list(_CLOSING_DIV_PATTERN.finditer(normalized_html))
    if not closing_divs:
        return f"{normalized_html}\n{NEWSLETTER_SIGNUP_BLOCK_HTML}"

    # Generated posts use one outer wrapper div, whose closing tag is last.
    outer_close = closing_divs[-1]
    before_close = normalized_html[:outer_close.start()].rstrip()
    after_close = normalized_html[outer_close.start():]
    return f"{before_close}\n{NEWSLETTER_SIGNUP_BLOCK_HTML}\n{after_close}"
