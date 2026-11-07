"""GrocerySOS's email-safe, responsive rendering of the approved Grocery News layout.

Presentation only: article selection, links, subject, audience and schedules
stay with the existing newsletter workflow. No fixed article headlines or photos.
"""
from datetime import datetime
from html import escape, unescape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


CREAM = "#FFF9EE"
DARK = "#123B29"
GREEN = "#175237"
GOLD = "#D5A73B"
RED = "#AF2923"
INK = "#19372C"
SITE = "https://grocerysos.com"


def _link(value: str) -> str:
    """Use actual published links. Never invent a destination for an article."""
    value = (value or "").strip()
    parts = urlsplit(value)
    if parts.scheme == "https" and parts.netloc:
        return escape(value, quote=True)
    return SITE


def _image(value: str, alt: str, width: int, style: str) -> str:
    """Only display the article's own securely hosted photo."""
    value = (value or "").strip()
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    approved = (
        host in ("i.ibb.co", "ibb.co", "blogger.googleusercontent.com")
        or (host == "wziocgpteiozbtgeoplj.supabase.co"
            and parts.path.startswith("/storage/v1/object/public/blog-images/"))
    )
    if parts.scheme != "https" or not approved:
        return ""
    return (
        f'<img src="{escape(value, quote=True)}" '
        f'alt="{escape(alt, quote=True)}" width="{width}" '
        f'style="display:block;width:100%;max-width:{width}px;'
        f'height:auto;border:0;{style}" />'
    )


def _description(text: str, limit: int = 148) -> str:
    value = " ".join(unescape(text or "").split())
    if len(value) > limit:
        value = value[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
    return escape(value)


def _recall(article: dict) -> str:
    title = escape(str(article.get("title") or "Food recall"))
    url = _link(str(article.get("url") or article.get("link") or ""))
    image = _image(
        str(article.get("image_url") or ""), str(article.get("title") or "Food recall"),
        255, "border-radius:10px;"
    )
    summary = _description(str(article.get("summary") or article.get("description") or ""), 210)
    image_cell = (
        f'<td class="stack-column" width="44%" valign="top" style="padding:12px 6px 12px 12px;">'
        f'<a href="{url}" style="text-decoration:none;">{image}</a></td>'
        if image else ""
    )
    return f"""
      <tr>
        <td style="padding:0 14px 14px 14px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="border-collapse:separate;background:#FFFFFF;border-radius:12px;
                        border:1px solid #ECDCC3;">
            <tr>
              {image_cell}
              <td class="stack-column" valign="middle"
                  style="padding:18px 15px 18px 17px;">
                <a href="{url}" style="font-family:Montserrat,Arial,sans-serif;
                   font-size:21px;line-height:1.3;font-weight:800;color:{DARK};
                   text-decoration:none;">{title}</a>
                {f'<p style="font-size:14px;line-height:1.5;color:#43554B;margin:10px 0;">{summary}</p>' if summary else ''}
                <p style="margin:12px 0 0;">
                  <a href="{url}" style="font-size:13px;color:{RED};
                     font-weight:700;text-decoration:underline;">Check recall details</a>
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    """


def _tile(article: dict) -> str:
    raw_title = str(article.get("title") or "Grocery story")
    title = escape(raw_title)
    url = _link(str(article.get("url") or article.get("link") or ""))
    image = _image(
        str(article.get("image_url") or ""), raw_title,
        260, "border-radius:9px 9px 0 0;"
    )
    summary = _description(str(article.get("summary") or article.get("description") or ""), 115)
    image_row = (
        f'<tr><td style="padding:0;"><a href="{url}" style="display:block;'
        f'text-decoration:none;">{image}</a></td></tr>'
        if image else ""
    )
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:separate;background:#FFFFFF;border:1px solid #E6D9C2;
                    border-radius:10px;">
        {image_row}
        <tr>
          <td valign="top" style="padding:16px 15px 18px;">
            <a href="{url}" style="font-family:Montserrat,Arial,sans-serif;
               color:{DARK};font-size:16px;line-height:1.38;font-weight:800;
               text-decoration:none;">{title}</a>
            {f'<p style="font-family:Montserrat,Arial,sans-serif;margin:9px 0 0;line-height:1.45;font-size:12px;color:#53665A;">{summary}</p>' if summary else ''}
            <p style="margin:12px 0 0;">
              <a href="{url}" style="font-size:13px;color:{GREEN};font-weight:700;
                 text-decoration:underline;">Read story</a>
            </p>
          </td>
        </tr>
      </table>
    """


def _stories(articles: list[dict]) -> str:
    rows = []
    for index in range(0, len(articles), 2):
        first = _tile(articles[index])
        second = _tile(articles[index + 1]) if index + 1 < len(articles) else ""
        rows.append(
            '<tr>'
            '<td class="stack-column" width="50%" valign="top" '
            'style="width:50%;padding:7px;">' + first + '</td>'
            '<td class="stack-column" width="50%" valign="top" '
            'style="width:50%;padding:7px;">' + second + '</td>'
            '</tr>'
        )
    return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' + "".join(rows) + '</table>'


def render_grocerysos_newsletter_html(
    articles: list[dict],
    recall_articles: list[dict] | None = None,
    dynamic_headline: str | None = None
) -> str:
    """Render actual selected stories using the green/cream GrocerySOS layout."""
    articles = (articles or [])[:12]
    recalls = (recall_articles or [])[:3]
    now = datetime.now(ZoneInfo("America/Chicago"))
    week_label = escape(now.strftime("%B %d, %Y").replace(" 0", " "))
    headline = escape(dynamic_headline or "Your weekly grocery news")
    # Keep recalls inside the same story grid, always after grocery stories.
    story_grid = _stories(articles + recalls) if articles or recalls else ""
    story_section = (
        f'''
        <tr><td style="padding:12px 16px 9px;">
          <div style="background:{GREEN};color:#FFFFFF;border-radius:9px;
                      padding:14px 12px;text-align:center;
                      font:800 20px/1.25 Montserrat,Arial,sans-serif;">
            Top Grocery Stories
          </div>
        </td></tr>
        <tr><td style="padding:0 14px 8px;">{story_grid}</td></tr>
        ''' if articles or recalls else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="color-scheme" content="light" />
<title>GrocerySOS Grocery News</title>
<style>
  body {{margin:0;padding:0;background:{CREAM};}}
  table {{border-collapse:collapse;}}
  @media only screen and (max-width:620px) {{
    .mail-shell {{width:100% !important;max-width:100% !important;}}
    .stack-column {{display:block !important;width:100% !important;
                    box-sizing:border-box !important;padding:10px !important;}}
    .email-h1 {{font-size:30px !important;line-height:1.12 !important;}}
    .email-gutter {{padding-left:16px !important;padding-right:16px !important;}}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:{CREAM};">
<center style="width:100%;background:{CREAM};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{CREAM};">
<tr><td align="center" style="padding:12px 0 22px;">
<table role="presentation" class="mail-shell" width="620" cellpadding="0" cellspacing="0"
       style="width:620px;max-width:620px;background:{CREAM};">
  <tr><td align="center" style="padding:20px 16px 13px;">
    <a href="{SITE}" style="text-decoration:none;white-space:nowrap;
       font-family:Montserrat,Arial,sans-serif;font-size:32px;font-weight:800;
       letter-spacing:-1.2px;color:{DARK};">Grocery<span style="color:#72A12A;">SOS</span></a>
    <div style="margin:5px 0 0;color:{GREEN};font:12px/1.5 Montserrat,Arial,sans-serif;">
      Groceries, made easier for real life.
    </div>
  </td></tr>
  <tr><td align="center" style="padding:7px 18px 1px;">
    <div style="font:800 30px/1.1 Montserrat,Arial,sans-serif;
                letter-spacing:1px;color:{DARK};">THIS WEEK'S</div>
    <div class="email-h1" style="font:800 38px/1.12 Montserrat,Arial,sans-serif;
         color:#FFFFFF;background:{GREEN};padding:11px 12px;
         margin:5px 0 0;border-radius:8px;">GROCERY NEWS</div>
  </td></tr>
  <tr><td align="center" class="email-gutter" style="padding:17px 28px 11px;">
    <p style="font:15px/1.5 Montserrat,Arial,sans-serif;color:{INK};margin:0;">
      Recalls, price changes, useful finds, and smart shopping tips before your next grocery run.
    </p>
    <p style="font:700 13px/1.5 Montserrat,Arial,sans-serif;
              color:{INK};margin:11px 0 0;padding:6px 12px;
              border:1px solid {GOLD};border-radius:25px;display:inline-block;">
      Week of {week_label}
    </p>
    <p style="font:600 15px/1.45 Montserrat,Arial,sans-serif;color:{INK};
              margin:13px 0 0;">{headline}</p>
  </td></tr>
  {story_section}
  <tr><td align="center" style="padding:24px 20px 30px;">
    <a href="{SITE}" target="_blank"
       style="display:inline-block;background:{GREEN};border:3px solid {GOLD};
              border-radius:36px;text-decoration:none;color:#FFFFFF;
              padding:14px 28px;font:800 18px/1.3 Montserrat,Arial,sans-serif;">
      Read more at GrocerySOS.com
    </a>
  </td></tr>
  <tr><td align="center" style="padding:20px;background:{DARK};color:#FFFFFF;
       font:12px/1.7 Montserrat,Arial,sans-serif;">
    <p style="margin:0 0 7px;">&copy; {now.year} GrocerySOS. All rights reserved.</p>
    <p style="margin:0 0 7px;"><a href="mailto:info@getyoudle.com"
       style="color:#FFFFFF;text-decoration:underline;">Contact us</a></p>
    <p style="margin:0 0 7px;">*|LIST:ADDRESSLINE|*</p>
    <p style="margin:0;"><a href="*|UNSUB|*"
       style="color:#FFFFFF;text-decoration:underline;">Unsubscribe</a></p>
  </td></tr>
</table></td></tr></table>
</center>
</body>
</html>"""
