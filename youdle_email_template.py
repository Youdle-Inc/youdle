"""Youdle Grocery News email, using the GrocerySOS color palette."""
from datetime import datetime, timedelta
from html import escape, unescape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


CREAM = "#FFF9EE"
GREEN = "#175237"
DARK = "#123B29"
GOLD = "#D5A73B"
RED = "#AF2923"
INK = "#19372C"
RULE = "#E6D9C2"
SITE = "https://www.youdle.io"
NEWS = f"{SITE}/news"
LOGO = "https://mcusercontent.com/a8e33153b11c8b750221ce4aa/images/5f2d9977-bf45-cdb6-23dd-0c18573407e4.png"
SANS = "Montserrat,Arial,sans-serif"
SERIF = "Georgia,'Times New Roman',serif"


def _https(value):
    value = str(value or "").strip()
    try:
        parts = urlsplit(value)
        if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
            return escape(value, quote=True)
    except ValueError:
        pass
    return ""


def _story(article, compact=False):
    raw_title = str(article.get("title") or "Grocery story")
    title = escape(raw_title)
    url = _https(article.get("url") or article.get("link")) or NEWS
    summary = escape(" ".join(unescape(str(article.get("summary") or article.get("description") or "")).split()))
    image_url = _https(article.get("image_url"))
    width = 112 if compact else 568
    image = (
        f'<a href="{url}" style="text-decoration:none;"><img src="{image_url}" alt="" width="{width}" '
        f'style="display:block;width:100%;max-width:{width}px;height:auto;border:0;border-radius:6px;"></a>'
        if image_url else ""
    )
    size = 21 if compact else 32
    headline = (
        f'<h3 style="margin:0 0 8px;font:700 {size}px/1.18 {SERIF};">'
        f'<a href="{url}" style="color:{DARK};text-decoration:none;">{title}</a></h3>'
    )
    body = (
        (f'<p style="margin:0 0 9px;font:15px/1.55 {SANS};color:{INK};">{summary}</p>' if summary else "")
        + f'<a href="{url}" style="font:700 13px/1.4 {SANS};color:{GREEN};text-decoration:underline;">Read the story →</a>'
    )
    content = headline + body
    if not compact:
        return f'<div style="padding:20px 0 24px;border-bottom:1px solid {RULE};">{headline}{image}<div style="margin-top:14px;">{body}</div></div>'
    if not image:
        return f'<div style="padding:16px 0;border-bottom:1px solid {RULE};">{content}</div>'
    return (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-bottom:1px solid {RULE};"><tr>'
        f'<td class="thumb" width="112" valign="top" style="padding:16px 14px 16px 0;">{image}</td>'
        f'<td valign="top" style="padding:16px 0;">{content}</td></tr></table>'
    )


def _section(label, contents, color=GREEN):
    if not contents:
        return ""
    return (
        f'<tr><td class="gutter" style="padding:16px 26px 0;">'
        f'<h2 style="margin:0;padding:9px 12px;background:{color};color:white;'
        f'font:700 13px/1.35 {SANS};letter-spacing:0.07em;text-transform:uppercase;">{label}</h2>'
        f'{contents}</td></tr>'
    )


def render_youdle_newsletter_html(articles, recall_articles=None, dynamic_headline=None):
    """Use the selected Youdle stories, retaining their order inside each section."""
    stories, recalls = [], []
    for article in articles or []:
        if str(article.get("category", "")).upper() == "RECALL":
            recalls.append(article)
        else:
            stories.append(article)
    for article in recall_articles or []:
        if article not in recalls:
            recalls.append(article)
    stories = [article for article in stories if article not in recalls]

    now = datetime.now(ZoneInfo("America/Chicago"))
    monday = now.date() - timedelta(days=now.weekday())
    week = escape(monday.strftime("%B %d, %Y").replace(" 0", " "))
    headline = escape(str(dynamic_headline or "Your weekly grocery news"))
    agenda_items = stories[:2] + recalls[:1] if recalls else stories[:3]
    agenda = "".join(
        f'<li style="margin:0 0 5px;"><a href="{_https(item.get("url") or item.get("link")) or NEWS}" '
        f'style="color:{GREEN};">{escape(str(item.get("title") or "Grocery story"))}</a></li>'
        for item in agenda_items
    )
    preview = (
        f'<p style="margin:15px 0 5px;font:700 14px/1.4 {SANS};color:{DARK};">In this edition</p>'
        f'<ul style="margin:0;padding-left:19px;font:14px/1.5 {SANS};color:{INK};">{agenda}</ul>'
        if agenda else ""
    )
    feature = _section("Top Grocery Stories", "".join(_story(article) for article in stories[:2]))
    quick_reads = _section("Quick Reads", "".join(_story(article, compact=True) for article in stories[2:]))
    roundup = _section("Recall Roundup", "".join(_story(article, compact=True) for article in recalls), RED)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Youdle Grocery News</title>
<style>
@media screen and (max-width:540px) {{
  .gutter {{ padding-left:16px!important; padding-right:16px!important; }}
  .masthead {{ font-size:38px!important; }}
  .thumb {{ width:76px!important; }}
}}
</style>
</head>
<body style="margin:0;padding:0;background:{CREAM};color:{INK};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{CREAM};">
<tr><td align="center" style="padding:12px 0 24px;">
<!--[if mso]><table role="presentation" width="620" cellspacing="0" cellpadding="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;max-width:620px;background:white;">
<tr><td class="gutter" style="padding:11px 26px;border-top:5px solid {GOLD};border-bottom:1px solid {RULE};">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font:12px/1.5 {SANS};color:{INK};">
    <tr><td>Week of {week}</td><td align="right"><a href="*|ARCHIVE|*" style="color:{GREEN};">View online</a></td></tr>
  </table>
</td></tr>
<tr><td align="center" class="gutter" style="padding:12px 26px 15px;background:{CREAM};border-bottom:1px solid {RULE};">
  <a href="{SITE}"><img src="{LOGO}" alt="Youdle" width="100" style="display:block;width:100px;height:auto;border:0;"></a>
  <p class="masthead" style="margin:0 0 13px;font:700 48px/1 {SERIF};color:{DARK};">Grocery News</p>
  <a href="*|LIST:SUBSCRIBE|*" style="display:inline-block;background:{GREEN};border-radius:6px;color:white;
     padding:12px 17px;font:700 14px/1.4 {SANS};text-decoration:none;">Subscribe to the newsletter</a>
</td></tr>
<tr><td class="gutter" style="padding:22px 26px 9px;">
  <h1 style="margin:0 0 9px;font:700 29px/1.15 {SERIF};color:{DARK};">{headline}</h1>
  <p style="margin:0;font:15px/1.55 {SANS};color:{INK};">Here’s what’s worth knowing before your next grocery run.</p>
  {preview}
</td></tr>
{feature}
{quick_reads}
{roundup}
<tr><td align="center" class="gutter" style="padding:20px 26px;border-top:1px solid {RULE};background:{CREAM};">
  <a href="*|FORWARD|*" style="font:700 15px/1.4 {SANS};color:{GREEN};">Forward to a friend</a>
  &nbsp; · &nbsp;
  <a href="{NEWS}" style="font:700 15px/1.4 {SANS};color:{GREEN};">More grocery news</a>
</td></tr>
<tr><td align="center" class="gutter" style="padding:20px 26px;background:{DARK};color:white;font:12px/1.65 {SANS};">
  <strong>Youdle Grocery News</strong><br>
  <a href="*|UPDATE_PROFILE|*" style="color:white;">Update preferences</a> &nbsp;·&nbsp;
  <a href="*|UNSUB|*" style="color:white;">Unsubscribe</a><br>
  © {now.year} Youdle. All rights reserved.<br>*|LIST:ADDRESSLINE|*
</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body>
</html>"""
