"""Current stories rendered in the owner-approved Youdle Grocery News email design."""
from datetime import datetime, timedelta
from html import escape, unescape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

PREFIX = '<!doctype html>\n<html lang="en" xmlns="http://www.w3.org/1999/xhtml"><head>\n<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>__PAGE_TITLE__</title>\n<style>\n@media screen and (max-width:620px) {\n  .shell { width:100%!important;max-width:100%!important; }\n  .gutter { padding-left:18px!important;padding-right:18px!important; }\n  .stack-col { display:block!important;box-sizing:border-box!important;width:100%!important;padding:19px 0 23px!important; }\n  .stack-col img { max-width:100%!important;height:210px!important;object-fit:cover!important; }\n  .strap-title { font-size:34px!important; }\n  .masthead-title { font-size:29px!important; }\n  .date {font-size:10px!important;}\n  .feature-image {height:230px!important;}\n}\n</style></head>\n<body style="margin:0;padding:0;background:#f6f8f6;color:#171b18;font-family:Montserrat,Arial,sans-serif;">\n<center style="background:#f6f8f6;width:100%;">\n<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;background:#f6f8f6;">\n<tr><td align="center" style="padding:16px 0 30px;">\n<table class="shell" role="presentation" cellpadding="0" cellspacing="0" width="680" style="width:680px;max-width:680px;border-collapse:collapse;background:white;text-align:left;">\n  <tr><td class="gutter" style="padding:15px 30px 8px;border-bottom:1px solid #e0e4de;">\n   <table width="100%" role="presentation" cellpadding="0" cellspacing="0"><tr>\n     <td valign="middle" width="32%" style="padding:0 12px 12px 0;"><a href="https://www.youdle.io/"> <img src="https://mcusercontent.com/a8e33153b11c8b750221ce4aa/images/5f2d9977-bf45-cdb6-23dd-0c18573407e4.png" alt="Youdle Logo" width="120" style="display:block;width:120px;max-width:100%;height:auto;border:0;"> </a></td>\n     <td valign="middle" width="45%" style="padding:0 8px 12px 14px;border-left:1px solid #82917f;"><a href="https://www.youdle.io/news" class="masthead-title" style="font:700 30px/1.1 Georgia,\'Times New Roman\',serif;color:#171b18;text-decoration:none;white-space:nowrap;">Grocery News</a></td>\n     <td valign="middle" width="23%" align="right" class="date" style="font:10px/1.5 Montserrat,Arial,sans-serif;color:#657268;padding:0 0 12px 4px;">__ISSUE_DATE__</td>\n   </tr></table>\n  </td></tr>\n  <tr><td class="gutter" style="padding:29px 30px 28px;">\n    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;background:#e7efe9;border-radius:11px;"><tr><td style="padding:28px 28px 29px;">\n       <div style="font:800 11px/1.3 Montserrat,Arial,sans-serif;letter-spacing:1.6px;color:#28543d;text-transform:uppercase;margin-bottom:8px;">THE YOUDLE NEWSLETTER</div>\n       <h1 class="strap-title" style="font:700 40px/1.08 Georgia,\'Times New Roman\',serif;letter-spacing:-1px;margin:0 0 10px;color:#181c18;">The grocery stories that matter.</h1>\n       <p style="font:14px/1.6 Montserrat,Arial,sans-serif;color:#364d3e;margin:0;">Grocery news, recalls, savings, and smart shopping tips delivered to your inbox.</p>\n    </td></tr></table>\n  </td></tr>\n  <tr><td class="gutter" style="padding:8px 30px 20px;">\n    <table role="presentation" width="100%"><tr>\n     <td valign="bottom"><h2 style="font:700 27px/1.1 Georgia,\'Times New Roman\',serif;color:#171b18;margin:0;">Top Grocery Stories</h2></td>\n     <td valign="bottom" align="right" style="font:800 10px/1.5 Montserrat,Arial,sans-serif;white-space:nowrap;"><a href="https://www.youdle.io/news" style="color:#28543d;text-decoration:none;">ALL STORIES <span style="color:#28543d;font-family:Arial,Helvetica,sans-serif;font-size:13px;font-weight:400;line-height:1;">→︎</span></a></td>\n    </tr></table>\n  </td></tr>\n  \n      '

FEATURE = '<tr><td style="padding:0 30px 0;" class="gutter">\n        <a href="__ARTICLE_URL__"><img src="__ARTICLE_IMAGE__" alt="__ARTICLE_TITLE__" width="620" height="300" style="display:block;width:100%;max-width:620px;height:300px;object-fit:cover;border:0;"></a>\n      </td></tr>\n      <tr><td style="padding:21px 30px 29px;border-bottom:1px solid #d9dfda;" class="gutter">\n        <div style="font:800 10px/1.4 Montserrat,Arial,sans-serif;letter-spacing:1.1px;color:#28543d;text-transform:uppercase;">__ARTICLE_CATEGORY__</div>\n        <h2 style="font:700 33px/1.11 Georgia,\'Times New Roman\',serif;letter-spacing:-.7px;margin:8px 0 10px;color:#171b18;"><a href="__ARTICLE_URL__" style="text-decoration:none;color:#171b18;">__ARTICLE_TITLE__</a></h2>\n        <p style="margin:0 0 13px;font:14px/1.65 Montserrat,Arial,sans-serif;color:#4d5b51;">__ARTICLE_SUMMARY__</p>\n        <a href="__ARTICLE_URL__" target="_blank" style="color:#28543d;text-decoration:none;font:700 12px/1.5 Montserrat,Arial,sans-serif;">Read article <span style="color:#28543d;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:400;line-height:1;">↗︎</span></a>\n      </td></tr>\n  '

LEFT_CARD = '<td class="stack-col" valign="top" width="50%" style="width:50%;padding:22px 13px 26px 0;border-bottom:1px solid #d9dfda;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">\n      <tr><td><a href="__ARTICLE_URL__"><img src="__ARTICLE_IMAGE__" alt="__ARTICLE_TITLE__" width="296" height="166" style="display:block;width:100%;max-width:296px;height:166px;object-fit:cover;border:0;"></a></td></tr>\n      <tr><td style="padding:16px 0 0;">\n        <div style="font:800 10px/1.35 Montserrat,Arial,sans-serif;color:#28543d;letter-spacing:.8px;text-transform:uppercase;">__ARTICLE_CATEGORY__</div>\n        <h3 style="font:700 23px/1.19 Georgia,\'Times New Roman\',serif;letter-spacing:-.25px;margin:7px 0 8px;color:#161b17;"><a href="__ARTICLE_URL__" style="text-decoration:none;color:#161b17;">__ARTICLE_TITLE__</a></h3>\n        <p style="margin:0 0 13px;font:13px/1.52 Montserrat,Arial,sans-serif;color:#566159;">__ARTICLE_SUMMARY__</p>\n        <a href="__ARTICLE_URL__" target="_blank" style="color:#28543d;text-decoration:none;font:700 12px/1.5 Montserrat,Arial,sans-serif;">Read article <span style="color:#28543d;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:400;line-height:1;">↗︎</span></a>\n      </td></tr>\n    </table></td>'

RIGHT_CARD = '<td class="stack-col" valign="top" width="50%" style="width:50%;padding:22px 0 26px 13px;border-bottom:1px solid #d9dfda;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">\n      <tr><td><a href="__ARTICLE_URL__"><img src="__ARTICLE_IMAGE__" alt="__ARTICLE_TITLE__" width="296" height="166" style="display:block;width:100%;max-width:296px;height:166px;object-fit:cover;border:0;"></a></td></tr>\n      <tr><td style="padding:16px 0 0;">\n        <div style="font:800 10px/1.35 Montserrat,Arial,sans-serif;color:#28543d;letter-spacing:.8px;text-transform:uppercase;">__ARTICLE_CATEGORY__</div>\n        <h3 style="font:700 23px/1.19 Georgia,\'Times New Roman\',serif;letter-spacing:-.25px;margin:7px 0 8px;color:#161b17;"><a href="__ARTICLE_URL__" style="text-decoration:none;color:#161b17;">__ARTICLE_TITLE__</a></h3>\n        <p style="margin:0 0 13px;font:13px/1.52 Montserrat,Arial,sans-serif;color:#566159;">__ARTICLE_SUMMARY__</p>\n        <a href="__ARTICLE_URL__" target="_blank" style="color:#28543d;text-decoration:none;font:700 12px/1.5 Montserrat,Arial,sans-serif;">Read article <span style="color:#28543d;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:400;line-height:1;">↗︎</span></a>\n      </td></tr>\n    </table></td>'

FOOTER = '<tr><td class="gutter" style="background:#e7efe9;padding:28px 30px 31px;">\n    <div style="font:700 30px/1.1 Georgia,\'Times New Roman\',serif;color:#244c36;">Youdle <span style="font:700 17px/1.1 Georgia,\'Times New Roman\',serif;color:#244c36;">Grocery News</span></div>\n    <p style="font:13px/1.8 Montserrat,Arial,sans-serif;color:#30513e;margin:12px 0 12px;">Groceries, made easier for real life.</p>\n    <p style="font:12px/1.8 Montserrat,Arial,sans-serif;margin:0 0 20px;"><a href="https://www.youdle.io/news" style="color:#244c36;">Stories</a> \xa0|\xa0 <a href="https://www.youdle.io/news?category=recalls-warnings" style="color:#244c36;">Recalls</a></p>\n    <p style="border-top:1px solid #b8c9bc;padding-top:16px;margin:0;font:11px/1.7 Montserrat,Arial,sans-serif;color:#526657;">You’re receiving the Youdle grocery newsletter.<br>\n      <a href="*|UPDATE_PROFILE|*" style="color:#244c36;">Update preferences</a> \xa0|\xa0 <a href="*|UNSUB|*" style="color:#244c36;">Unsubscribe</a><br>\n      © 2026 Youdle. All rights reserved.<br>*|LIST:ADDRESSLINE|*</p>\n  </td></tr>\n</table></td></tr></table>\n</center></body></html>'


def _story_html(template, article):
    title = str(article.get("title") or "Grocery story")
    url = str(article.get("url") or article.get("link") or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("A published article URL is required for each newsletter story")
    image = str(article.get("image_url") or "").strip()
    valid_image = urlsplit(image).scheme == "https" and bool(urlsplit(image).netloc)
    summary = " ".join(unescape(str(article.get("summary") or article.get("description") or "")).split())
    if len(summary) > 235:
        summary = summary[:235].rsplit(" ", 1)[0].rstrip(" ,;:.") + "..."
    if not valid_image:
        template = re.sub(r"<img\b[^>]*>", "", template, flags=re.I)
    values = {
        "__ARTICLE_TITLE__": title,
        "__ARTICLE_URL__": url,
        "__ARTICLE_IMAGE__": image if valid_image else "",
        "__ARTICLE_SUMMARY__": summary,
        "__ARTICLE_CATEGORY__": "Food Recall Alerts" if str(article.get("category", "")).upper() == "RECALL" else "Grocery News",
    }
    for key, value in values.items():
        template = template.replace(key, escape(value, quote=True))
    return template


def render_youdle_newsletter_html(articles, recall_articles=None, dynamic_headline=None):
    """Reuse the owner-approved November 7 design with the current stories.

    Preserve the approved Youdle masthead, sage colors, serif headlines,
    image-led feature, paired photo cards, refined arrows, and legal footer.
    Keep recalls at the end of the same story grid. Never cap or split an issue.
    """
    stories = list(articles or []) + list(recall_articles or [])
    stories = [p for p in stories if str(p.get("category", "")).upper() != "RECALL"] + [p for p in stories if str(p.get("category", "")).upper() == "RECALL"]
    now = datetime.now(ZoneInfo("America/Chicago"))
    monday = now.date() - timedelta(days=now.weekday())
    date_label = "WEEK OF<br/>" + monday.strftime("%b. %d, %Y").replace(" 0", " ").upper()
    prefix = PREFIX.replace("__ISSUE_DATE__", date_label).replace("__PAGE_TITLE__", "Youdle Grocery News | Week of " + monday.strftime("%B %d, %Y").replace(" 0", " "))
    if dynamic_headline:
        prefix = prefix.replace("The grocery stories that matter.", escape(str(dynamic_headline)))
    feature = _story_html(FEATURE, stories[0]) if stories else ""
    pairs = []
    for index in range(1, len(stories), 2):
        left = _story_html(LEFT_CARD, stories[index])
        right = _story_html(RIGHT_CARD, stories[index + 1]) if index + 1 < len(stories) else '<td width="50%"></td>'
        pairs.append('<tr><td style="padding:0 30px;" class="gutter"><table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>' + left + right + '</tr></table></td></tr>')
    return prefix + feature + "".join(pairs) + FOOTER
