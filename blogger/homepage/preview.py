#!/usr/bin/env python3
"""Serve the news.youdle.io homepage locally.

    python blogger/homepage/preview.py            # http://localhost:5173
    python blogger/homepage/preview.py --source mock
    python blogger/homepage/preview.py --snapshot out.html

What it actually does, and why that matters: on every request it runs the real
``build_theme.build()``, pulls the generated pieces straight out of the
resulting Blogger XML, and evaluates them with ``bloggerlite`` against real
post data from the live Atom feed. It also resolves and includes the stock
theme's own ``b:skin`` CSS, so the layout overrides are tested against the
same cascade Blogger will apply.

That means what you see here is the theme you upload -- not a parallel mockup
that can drift. Edit src/homepage.css, src/homepage.js, src/homepage.xml or
src/config.json and just refresh.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bloggerlite as bl  # noqa: E402
import build_theme  # noqa: E402

REPO = HERE.parent.parent
ASSETS = HERE / "assets"
MOCK = HERE / "mock_posts.json"
BASE_THEME = REPO / "theme-2263602681587126671.xml"

FEED = "https://news.youdle.io/feeds/posts/default?alt=json&max-results=6"
HOMEPAGE_URL = "https://news.youdle.io/"
BLOG_TITLE = "Youdle grocery news to save time and money."

XHTML = "{http://www.w3.org/1999/xhtml}"
B = bl.B

CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".svg": "image/svg+xml", ".gif": "image/gif",
}


# ==========================================================================
# Post data
# ==========================================================================


def make_post(title, url, post_id, published, labels, image, body) -> dict:
    text = re.sub(r"<[^>]+>", " ", body or "")
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "title": bl.Str(title),
        "url": bl.Str(url, canonical=bl.Str(url)),
        "id": bl.Str(post_id),
        "date": bl.Date(published),
        "labels": [
            {"name": bl.Str(name), "url": bl.Str(HOMEPAGE_URL + "search/label/" + name)}
            for name in labels
        ],
        # Blogger only resizes images it hosts. The live blog mixes Google-hosted
        # images with i.ibb.co uploads, so both paths of the template's ternary
        # get exercised here.
        "featuredImage": bl.Str(
            image or "",
            isResizable=bool(image) and ("blogspot" in image or "googleusercontent" in image),
        ),
        "snippets": {"short": bl.Str(text[:150]), "long": bl.Str(text[:1000])},
        "body": bl.Str(body or ""),
    }


def posts_from_feed(raw: dict) -> list:
    out = []
    for entry in raw.get("feed", {}).get("entry", []):
        link = next(
            (l["href"] for l in entry.get("link", []) if l.get("rel") == "alternate"),
            HOMEPAGE_URL,
        )
        published = datetime.fromisoformat(entry["published"]["$t"])
        body = entry.get("content", entry.get("summary", {})).get("$t", "")
        thumb = entry.get("media$thumbnail", {}).get("url", "")
        # Blogger serves feed thumbnails at s72-c; ask for something usable.
        thumb = re.sub(r"/s\d+(-c)?/", "/s1600/", thumb)
        if not thumb:
            # Two thirds of the live posts have no feed thumbnail, but Blogger
            # derives data:post.featuredImage from the first image in the body.
            # Do the same, so the preview shows what the theme will show.
            first = re.search(r'<img[^>]+src="([^"]+)"', body) or re.search(
                r"<img[^>]+src='([^']+)'", body
            )
            thumb = first.group(1) if first else ""
        out.append(
            make_post(
                entry["title"]["$t"],
                link,
                entry["id"]["$t"].rsplit(".post-", 1)[-1],
                published,
                [c["term"] for c in entry.get("category", [])],
                thumb,
                body,
            )
        )
    return out


def posts_from_mock() -> list:
    raw = json.loads(MOCK.read_text(encoding="utf-8"))
    return [
        make_post(
            p["title"], p["url"], p["id"],
            datetime.fromisoformat(p["published"]),
            p.get("labels", []), p.get("image", ""), p.get("body", ""),
        )
        for p in raw["posts"]
    ]


@lru_cache(maxsize=1)
def load_posts(source: str) -> tuple:
    if source == "mock":
        return tuple(posts_from_mock())
    try:
        request = urllib.request.Request(FEED, headers={"User-Agent": "youdle-homepage-preview"})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        posts = posts_from_feed(data)
        if posts:
            print(f"    posts: {len(posts)} from the live news.youdle.io feed")
            return tuple(posts)
        print("    posts: live feed was empty, falling back to mock_posts.json")
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        print(f"    posts: live feed unavailable ({exc}); using mock_posts.json")
    return tuple(posts_from_mock())


# ==========================================================================
# Stock theme skin: resolve Blogger's $(variable) syntax
# ==========================================================================

LENGTH_RE = re.compile(r"^-?\d+(?:\.\d+)?(px|em|rem|%|vw|vh)?$")


def skin_variables(skin: str) -> dict:
    out = {}
    for attrs in re.findall(r"<Variable\s+([^>]*?)/>", skin):
        found = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        name = found.get("name")
        if name:
            out[name] = found.get("value") or found.get("default") or ""
    return out


def font_part(value: str, part: str) -> str:
    # "normal 400 20px EB Garamond, serif"
    match = re.search(r"(\d+(?:\.\d+)?)(px|em|rem|pt)", value)
    if part == "size":
        return match.group(0) if match else "16px"
    if part == "family":
        return value[match.end():].strip() if match else value
    return value


def hex_channel(value: str, channel: str) -> str:
    match = re.fullmatch(r"#([0-9a-fA-F]{6})", value.strip())
    if not match:
        return "0"
    r, g, b = (int(match.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return str({"red": r, "green": g, "blue": b}[channel])


ARITH_TOKEN = re.compile(r"[-+*/]|[^-+*/\s]+")
UNIT_RE = re.compile(r"(px|em|rem|%|vw|vh)$")


def arithmetic(expression: str, resolve) -> str | None:
    """Evaluate the skin's `$(...)` maths: `content.width + 240px`,
    `sidebar.width * -1`, `content.width / 2 - 10px`, `x * 1.7 * 12`."""
    tokens = ARITH_TOKEN.findall(expression)
    if not any(t in "+-*/" and len(t) == 1 for t in tokens):
        return None

    values: list[float] = []
    ops: list[str] = []
    unit = ""
    negate = False
    expect_operand = True

    for token in tokens:
        if token in ("+", "-", "*", "/") and not expect_operand:
            ops.append(token)
            expect_operand = True
            continue
        if token in ("+", "-") and expect_operand:
            # Unary sign, e.g. the theme's own `sidebar.width * -1`.
            negate = negate ^ (token == "-")
            continue
        if not expect_operand:
            return None  # two operands in a row

        text = token.strip()
        if not LENGTH_RE.match(text):
            resolved = resolve(text)
            if resolved is None or not LENGTH_RE.match(resolved.strip()):
                return None
            text = resolved.strip()

        found = UNIT_RE.search(text)
        if found and not unit:
            # Take the unit from whichever operand carries one; an expression
            # of pure variables has no literal unit in its own text.
            unit = found.group(1)
        number = float(UNIT_RE.sub("", text))
        values.append(-number if negate else number)
        negate = False
        expect_operand = False

    if expect_operand or not values:
        return None

    # Multiplication and division first, then left to right.
    i = 0
    while i < len(ops):
        if ops[i] in ("*", "/"):
            right = values.pop(i + 1)
            if ops[i] == "/" and right == 0:
                return None
            values[i] = values[i] * right if ops[i] == "*" else values[i] / right
            ops.pop(i)
        else:
            i += 1

    total = values[0]
    for op, value in zip(ops, values[1:]):
        total = total + value if op == "+" else total - value

    if total == int(total):
        total = int(total)
    return f"{total}{unit}"


def resolve_skin(skin: str) -> str:
    variables = skin_variables(skin)
    # The <Variable> declarations live inside a CSS comment, so the browser
    # ignores them already. Do not try to strip that comment: it begins at the
    # skin's first /*, which is normalize.css's own banner, and taking it out
    # removed 2KB of real reset CSS from every preview.
    css = skin

    def resolve(name: str):
        name = name.strip()
        if name in variables:
            return variables[name]
        for suffix, handler in (
            (".family", lambda base: font_part(base, "family")),
            (".size", lambda base: font_part(base, "size")),
            (".small", lambda base: base),
            (".large", lambda base: base),
        ):
            if name.endswith(suffix):
                base = resolve(name[: -len(suffix)])
                if base is not None:
                    return handler(base)
        if name.endswith(".transparent"):
            base = resolve(name[: -len(".transparent")])
            return "rgba(0,0,0,0)" if base is not None else None
        for channel in ("red", "green", "blue"):
            if name.endswith("." + channel):
                base = resolve(name[: -len(channel) - 1])
                if base is not None:
                    return hex_channel(base, channel)
        return arithmetic(name, resolve)

    def substitute(match: re.Match) -> str:
        value = resolve(match.group(1))
        return value if value is not None else "inherit"

    for _ in range(4):  # variables can reference other variables
        css, count = re.subn(r"\$\(([^)]*)\)", substitute, css)
        if not count:
            break
    return css


# ==========================================================================
# Pull the generated pieces out of the built theme
# ==========================================================================


def find_homepage_blocks(theme_xml: str) -> dict:
    root = ET.fromstring(theme_xml)
    head = root.find(XHTML + "head")
    body = root.find(XHTML + "body")

    pieces: dict = {"head": None, "header": None, "footer": None, "script": None}

    for node in head:
        if node.tag == B + "if" and node.find(XHTML + "style") is not None:
            if pieces["head"] is not None:
                raise SystemExit("ERROR: more than one homepage <style> block in <head>")
            pieces["head"] = node

    for node in body:
        if node.tag != B + "if":
            continue
        if node.find(XHTML + "header") is not None:
            pieces["header"] = node
        elif node.find(XHTML + "footer") is not None:
            pieces["footer"] = node
        elif node.find(XHTML + "script") is not None:
            pieces["script"] = node

    pieces["main"] = next(
        (n for n in root.iter(B + "includable") if n.get("id") == "youdleHomepage"), None
    )

    skin = re.search(r"<b:skin[^>]*><!\[CDATA\[(.*?)\]\]></b:skin>", theme_xml, re.DOTALL)
    pieces["skin"] = resolve_skin(skin.group(1)) if skin else ""

    # The theme's own second <style> block (post chrome), for cascade fidelity.
    extra = [n for n in head if n.tag == XHTML + "style"]
    pieces["theme_style"] = extra[0].text if extra else ""

    missing = [k for k, v in pieces.items() if v is None]
    if missing:
        raise SystemExit(f"ERROR: could not locate {missing} in the built theme")
    return pieces


def build_scope(posts: tuple) -> dict:
    return {
        "view": {
            "isHomepage": True, "isMultipleItems": True, "isSingleItem": False,
            "isPost": False, "isPage": False, "isArchive": False,
            "isSearch": False, "isLabelSearch": False, "isError": False,
            "isPreview": False, "isLayoutMode": False,
            "url": bl.Str(HOMEPAGE_URL),
        },
        "blog": {
            "homepageUrl": bl.Str(HOMEPAGE_URL),
            "title": bl.Str(BLOG_TITLE),
            "url": bl.Str(HOMEPAGE_URL),
        },
        "posts": list(posts),
    }


def render_page(pieces: dict, scope: dict) -> str:
    head = bl.render_element(pieces["head"], scope)
    header = bl.render_element(pieces["header"], scope)
    main = bl.render_element(pieces["main"], scope)
    footer = bl.render_element(pieces["footer"], scope)
    script = bl.render_element(pieces["script"], scope)

    # Reproduce the exact wrapper chain Blogger emits around the Blog widget,
    # so the flattening overrides in homepage.css are genuinely exercised.
    return f"""<!DOCTYPE html>
<html dir="ltr" lang="en">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1" name="viewport"/>
<title>{BLOG_TITLE}</title>
<style type="text/css">{pieces["skin"]}</style>
<style type="text/css">{pieces["theme_style"]}</style>
{head}
</head>
<body class="homepage-view feed-view yd-home version-1-3-3">
<a class="skip-navigation" href="#main">Skip to main content</a>
{header}
<div class="page">
  <div class="page_body">
    <div class="main-page-body-content">
      <div class="centered-top-placeholder"></div>
      <header class="centered-top-container" role="banner"><div class="centered-top">
        <div class="hamburger-menu-container"></div>
        <div class="blog-name">
          <!-- Header1 carries cond='not data:view.isHomepage', so on the
               homepage Blogger emits no widget here at all. -->
          <nav role="navigation"><div class="section" id="page_list_top"></div></nav>
        </div>
      </div></header>
      <div class="hero-image"></div>
      <main class="centered-bottom" id="main" role="main" tabindex="-1">
        <div class="main section" id="page_body" name="Page Body">
          <div class="widget Blog" data-version="2" id="Blog1">
{main}
          </div>
        </div>
      </main>
    </div>
    <footer class="footer section" id="footer"><div class="widget Attribution" id="Attribution1">
      <div class="widget-content"><div class="copyright">youdle.io</div></div>
    </div></footer>
  </div>
</div>
{footer}
<aside class="sidebar-container container sidebar-invisible" role="complementary">
  <div class="section" id="sidebar"><div class="widget BlogArchive" id="BlogArchive1">Past Articles</div></div>
</aside>
{script}
</body>
</html>
"""


def render(source: str, images: str) -> str:
    overrides = {}
    if images == "local":
        overrides = {
            "images": {
                "hero": "/assets/img/hero-tote.webp",
                "grocery": "/assets/img/grocery-visual.webp",
            },
            "community_posts": {
                "one": {"image": "/assets/img/community-1.webp"},
                "two": {"image": "/assets/img/community-2.webp"},
                "three": {"image": "/assets/img/community-3.webp"},
            },
        }
    theme = build_theme.build(BASE_THEME, None, overrides)
    return render_page(find_homepage_blocks(theme), build_scope(load_posts(source)))


# ==========================================================================
# Server
# ==========================================================================


class Handler(BaseHTTPRequestHandler):
    source = "live"
    images = "local"

    def do_GET(self):  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]

        if path.startswith("/assets/"):
            return self.serve_asset(path[len("/assets/"):])
        if path not in ("/", "/index.html"):
            return self.send_error(404)

        try:
            page = render(self.source, self.images)
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - show it in the browser
            import traceback

            body = (
                "<pre style='padding:24px;font:13px ui-monospace,monospace;"
                "color:#b00020;white-space:pre-wrap'>"
                + bl.esc_text(traceback.format_exc())
                + "</pre>"
            )
            print(f"!! render failed: {exc}", file=sys.stderr)
            return self.reply(body.encode("utf-8"), "text/html; charset=utf-8", 500)

        return self.reply(page.encode("utf-8"), "text/html; charset=utf-8")

    def serve_asset(self, relative: str):
        target = (ASSETS / relative).resolve()
        if not target.is_relative_to(ASSETS.resolve()) or not target.is_file():
            return self.send_error(404)
        kind = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        return self.reply(target.read_bytes(), kind)

    def reply(self, payload: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        # http.server calls this with ints for status codes, so indexing args
        # and testing it as a string raises on every error response.
        line = fmt % args
        if "/assets/" not in line:
            sys.stderr.write("    %s\n" % line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--source", choices=("live", "mock"), default="live",
                        help="story cards from the real Atom feed, or mock_posts.json")
    parser.add_argument("--images", choices=("local", "none"), default="local",
                        help="'local' serves the comp crops in assets/img; 'none' shows "
                             "the CSS placeholders you get before images are hosted")
    parser.add_argument("--snapshot", type=Path,
                        help="write one rendered page to this file and exit")
    args = parser.parse_args()

    if args.snapshot:
        args.snapshot.write_text(render(args.source, args.images), encoding="utf-8")
        print(f"OK  wrote {args.snapshot}")
        return

    Handler.source = args.source
    Handler.images = args.images
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\n  Youdle homepage preview  ->  http://localhost:{args.port}/")
    print(f"    stories: {args.source}   images: {args.images}")
    print("    rebuilds the theme on every request; edit src/ and refresh")
    print("    Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")


if __name__ == "__main__":
    main()
