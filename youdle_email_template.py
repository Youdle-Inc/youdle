"""Email-safe Youdle Grocery News digest in the GrocerySOS palette."""
from datetime import datetime, timedelta
from html import escape, unescape
from urllib.parse import quote, urlsplit
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
FONT = "Arial,Helvetica,sans-serif"
CARD = f"background:#FFFFFF;border:1px solid {RULE};border-radius:15px;"
BODY = f"font:16px/22px {FONT};color:{INK};"
SECTION = f"font:700 16px/22px {FONT};text-transform:uppercase;"


def _https(value):
    value = str(value or "").strip()
    try:
        parts = urlsplit(value)
        if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return ""


def _title(article):
    return escape(str(article.get("title") or "Grocery story"))


def _url(article):
    return _https(article.get("url") or article.get("link")) or NEWS


def _summary(article):
    return escape(" ".join(unescape(str(article.get("summary") or article.get("description") or "")).split()))


def _share(article_url):
    encoded = quote(article_url, safe="")
    destinations = (
        ("Facebook", "f", f"https://www.facebook.com/sharer/sharer.php?u={encoded}"),
        ("X", "𝕏", f"https://twitter.com/intent/tweet?url={encoded}"),
        ("LinkedIn", "in", f"https://www.linkedin.com/sharing/share-offsite/?url={encoded}"),
    )
    return "".join(
        f'<a href="{escape(url, quote=True)}" aria-label="Share on {label}" title="Share on {label}" '
        f'style="display:inline-block;width:25px;height:25px;text-align:center;border-radius:50%;'
        f'background:{GREEN};color:white;font:700 13px/25px {FONT};text-decoration:none;'
        f'margin-right:7px;">{glyph}</a>'
        for label, glyph, url in destinations
    )


def _story(article, label="Grocery News", accent=RED):
    article_url = _url(article)
    url = escape(article_url, quote=True)
    title = _title(article)
    photo = escape(_https(article.get("image_url")), quote=True)
    summary = _summary(article)
    image_row = (
        f'<tr><td style="padding-top:15px;"><a href="{url}">'
        f'<img src="{photo}" width="668" alt="" style="display:block;width:100%;max-width:668px;height:auto;border:0;">'
        '</a></td></tr>'
        if photo else ""
    )
    return f"""
<tr><td style="{CARD}">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
    <tr><td style="padding:15px 15px 0;">
      <p style="{SECTION}margin:0;color:{accent};">{label}</p>
      <h2 style="margin:8px 0 0;font:700 24px/26px {FONT};">
        <a href="{url}" style="text-decoration:none;color:{DARK};">{title}</a>
      </h2>
    </td></tr>
    {image_row}
    <tr><td style="padding:15px;">
      {f'<p style="{BODY}margin:0 0 15px;">{summary}</p>' if summary else ''}
      <a href="{url}" style="font:700 16px/22px {FONT};color:{DARK};
        text-decoration:none;border-bottom:2px solid {accent};">Keep reading</a>
      <div style="padding-top:12px;">{_share(article_url)}</div>
    </td></tr>
  </table>
</td></tr>
<tr><td height="7" style="font-size:0;line-height:0;">&nbsp;</td></tr>"""


def _quick_reads(articles):
    if not articles:
        return ""
    rows = []
    for article in articles:
        title, url, summary = _title(article), escape(_url(article), quote=True), _summary(article)
        link = f'<a href="{url}" style="color:{DARK};font-weight:700;text-decoration:underline;">{title}</a>'
        rows.append(f'<p style="{BODY}margin:0 0 13px;">{link}{(" " + summary) if summary else ""}</p>')
    return f"""
<tr><td style="{CARD}padding:15px;">
  <h2 style="{SECTION}margin:0 0 12px;color:{RED};">Quick Reads</h2>
  {"".join(rows)}
</td></tr>
<tr><td height="7" style="font-size:0;line-height:0;">&nbsp;</td></tr>"""


def render_youdle_newsletter_html(articles, recall_articles=None, dynamic_headline=None):
    """Render the current edition without changing its story selections or destinations."""
    stories, recalls = [], []
    for article in articles or []:
        (recalls if str(article.get("category", "")).upper() == "RECALL" else stories).append(article)
    for article in recall_articles or []:
        if article not in recalls:
            recalls.append(article)
    stories = [article for article in stories if article not in recalls]

    now = datetime.now(ZoneInfo("America/Chicago"))
    monday = now.date() - timedelta(days=now.weekday())
    week = monday.strftime("%B %d, %Y").replace(" 0", " ")
    headline = escape(str(dynamic_headline or "Here’s what’s happening at the grocery store this week."))
    agenda_articles = stories[:2] + recalls[:1] if recalls else stories[:3]
    agenda = "".join(
        f'<li style="margin:0 0 4px;"><a href="{escape(_url(article), quote=True)}" '
        f'style="color:{GREEN};text-decoration:underline;">{_title(article)}</a></li>'
        for article in agenda_articles
    )
    intro = f'<p style="{BODY}margin:0 0 8px;"><strong>In this edition</strong></p><ul style="{BODY}margin:0;padding-left:22px;">{agenda}</ul>' if agenda else ""
    features = "".join(_story(article) for article in stories[:3])
    quick_reads = _quick_reads(stories[3:])
    roundup = "".join(_story(article, "Recall Roundup", RED) for article in recalls)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Youdle Grocery News</title>
<style>
@media screen and (max-width:480px) {{
  .frame {{padding:5px!important;}}
  .masthead-text {{font-size:34px!important;}}
  .masthead-logo {{width:90px!important;}}
}}
</style>
</head>
<body style="margin:0;padding:0;background:{CREAM};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{CREAM};">
<tr><td align="center" class="frame" style="padding:10px 8px 25px;">
<!--[if mso]><table role="presentation" width="670" cellspacing="0" cellpadding="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;max-width:670px;">
<tr><td style="{CARD}padding:15px;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font:12px/1.5 {FONT};color:{DARK};">
    <tr>
      <td valign="top">Week of {week}</td>
      <td valign="top" align="right">
        <a href="*|ARCHIVE|*" style="color:{DARK};text-decoration:none;">View online</a> &nbsp;|&nbsp;
        <a href="*|LIST:SUBSCRIBE|*" style="color:{GREEN};font-weight:700;text-decoration:none;">Sign up</a> &nbsp;|&nbsp;
        <a href="{NEWS}" style="color:{DARK};text-decoration:none;">Grocery news</a>
      </td>
    </tr>
  </table>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:25px;margin-bottom:18px;">
    <tr><td align="center" style="background:{GREEN};border-radius:8px;border-bottom:4px solid {GOLD};padding:18px 10px;">
      <a href="{SITE}" style="display:inline-block;text-decoration:none;">
        <img class="masthead-logo" src="{LOGO}" alt="Youdle" width="114" style="display:block;width:114px;height:auto;border:0;background:white;border-radius:6px;">
      </a>
      <div class="masthead-text" style="margin-top:5px;color:white;font:800 48px/1.04 Montserrat,{FONT};letter-spacing:-0.035em;">Grocery News</div>
    </td></tr>
  </table>
  <p style="{BODY}margin:0 0 15px;"><strong style="color:{DARK};">Hey, shoppers.</strong> {headline}</p>
  {intro}
  <p style="margin:17px 0 0;">
    <a href="*|LIST:SUBSCRIBE|*" style="display:inline-block;background:{GREEN};color:white;border-radius:6px;
      padding:9px 14px;font:700 14px/1.4 {FONT};text-decoration:none;">Subscribe to the newsletter</a>
  </p>
</td></tr>
<tr><td height="7" style="font-size:0;line-height:0;">&nbsp;</td></tr>
{features}
{quick_reads}
{roundup}
<tr><td align="center" style="{CARD}padding:22px 15px;">
  <h2 style="margin:0 0 9px;font:700 24px/26px {FONT};color:{DARK};">Share Youdle Grocery News</h2>
  <a href="*|FORWARD|*" style="display:inline-block;background:{GREEN};color:white;border-radius:6px;
    padding:9px 14px;font:700 14px/1.4 {FONT};text-decoration:none;">Forward to a friend</a>
</td></tr>
<tr><td align="center" style="padding:19px 15px 0;font:12px/18px {FONT};color:{INK};">
  <a href="*|UPDATE_PROFILE|*" style="color:{GREEN};">Update preferences</a> &nbsp;·&nbsp;
  <a href="*|UNSUB|*" style="color:{GREEN};">Unsubscribe</a><br>
  © {now.year} Youdle. All rights reserved.<br>*|LIST:ADDRESSLINE|*
</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body>
</html>"""
