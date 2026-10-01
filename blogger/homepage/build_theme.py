#!/usr/bin/env python3
"""Build the Youdle homepage into the live Blogger theme.

    python blogger/homepage/build_theme.py

Reads the theme Blogger currently serves (``theme-2263602681587126671.xml``),
splices in the homepage from ``src/``, validates the result as strict XML and
writes ``theme-youdle-homepage.xml`` for upload.

The base theme is never modified. If someone edits the theme inside Blogger,
re-download it over the base file and run this again.

Why a build step rather than hand-editing the 3,700-line theme: the CSS,
JavaScript and markup stay in real ``.css`` / ``.js`` / ``.xml`` files that are
readable, diffable and shared verbatim with ``preview.py`` -- so what you see
locally is what Blogger renders.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.dom.minidom
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SRC = HERE / "src"

DEFAULT_BASE = REPO / "theme-2263602681587126671.xml"
DEFAULT_OUT = REPO / "theme-youdle-homepage.xml"
LOGO_SVG = REPO / "frontend" / "public" / "img" / "youdle-logo-brand.svg"
NEWLINE = chr(10)


# --------------------------------------------------------------------------
# Minimal template engine
#
# Three directives only, so the .xml source stays readable as XML:
#   {{a.b}}                        escaped value
#   {{raw a.b}}                    verbatim value (CSS, JS, SVG, JSON-LD)
#   {{#if a.b}} .. {{else}} .. {{/if}}   presence test
#   {{#each name}} .. {{item.x}} .. {{/each}}
# --------------------------------------------------------------------------

VAR_RE = re.compile(r"\{\{\s*(raw\s+)?([a-zA-Z0-9_.]+)\s*\}\}")
# The body patterns forbid a nested {{#if}}, so this only ever matches the
# innermost block; expand_if loops until none are left.
IF_RE = re.compile(
    # The body patterns forbid a nested {{#if}}, so this only ever matches the
    # innermost block and expand_if loops until none are left. The lookahead is
    # written [\s}] rather than \b on purpose: it stays printable, so a stray
    # control byte cannot silently disable the guard.
    r"\{\{#if\s+([a-zA-Z0-9_.]+)\s*\}\}"
    r"((?:(?!\{\{#if[\s}]).)*?)"
    r"(?:\{\{else\}\}((?:(?!\{\{#if[\s}]).)*?))?"
    r"\{\{/if\}\}",
    re.DOTALL,
)
EACH_RE = re.compile(r"\{\{#each\s+([a-zA-Z0-9_.]+)\s*\}\}(.*?)\{\{/each\}\}", re.DOTALL)


class TemplateError(RuntimeError):
    pass


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def lookup(ctx: dict, path: str):
    node = ctx
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise TemplateError(f"unknown template key: {path}")
    return node


def expand_vars(text: str, ctx: dict) -> str:
    def sub(match: re.Match) -> str:
        is_raw, path = match.group(1), match.group(2)
        value = lookup(ctx, path)
        if value is None:
            value = ""
        if not isinstance(value, str):
            value = str(value)
        return value if is_raw else xml_escape(value)

    return VAR_RE.sub(sub, text)


def expand_if(text: str, ctx: dict) -> str:
    def sub(match: re.Match) -> str:
        path, yes, no = match.group(1), match.group(2), match.group(3) or ""
        # lookup() raises on an unknown path. That is deliberate: a mistyped
        # key should fail loudly rather than quietly render the else branch.
        return yes if lookup(ctx, path) else no

    # Innermost-first so nested blocks resolve correctly.
    previous = None
    while previous != text:
        previous = text
        text = IF_RE.sub(sub, text)
    return text


def expand_each(text: str, ctx: dict) -> str:
    def sub(match: re.Match) -> str:
        name, body = match.group(1), match.group(2)
        collection = lookup(ctx, name)
        if not isinstance(collection, dict):
            raise TemplateError(f"{name} must be an object of items")
        rendered = []
        for key, item in collection.items():
            if key.startswith("_"):
                continue
            child = dict(ctx)
            child["item"] = item
            rendered.append(expand_vars(expand_if(body, child), child))
        return "".join(rendered)

    return EACH_RE.sub(sub, text)


def render(text: str, ctx: dict) -> str:
    text = expand_each(text, ctx)
    text = expand_if(text, ctx)
    text = expand_vars(text, ctx)
    leftover = re.search(r"\{\{[^}]*\}\}", text)
    if leftover:
        raise TemplateError(f"unresolved template directive: {leftover.group(0)}")
    return text


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


def read_parts(path: Path) -> dict:
    """Split src/homepage.xml on its @@PART:name@@ markers."""
    parts, name, buf = {}, None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        marker = re.fullmatch(r"@@PART:([a-z]+)@@", line.strip())
        if marker:
            if name:
                parts[name] = "\n".join(buf).strip("\n")
            name, buf = marker.group(1), []
        else:
            buf.append(line)
    if name:
        parts[name] = "\n".join(buf).strip("\n")
    missing = {"head", "header", "main", "footer", "script"} - parts.keys()
    if missing:
        raise TemplateError(f"homepage.xml is missing parts: {sorted(missing)}")
    return parts


def load_logo() -> str:
    """Inline the existing Youdle logo. Never redrawn -- handoff section 1."""
    if not LOGO_SVG.exists():
        return (
            "<svg aria-hidden='true' focusable='false' viewBox='0 0 114 34' "
            "xmlns='http://www.w3.org/2000/svg'><text fill='#173e2f' "
            "font-family='serif' font-size='24' x='0' y='26'>Youdle</text></svg>"
        )
    svg = LOGO_SVG.read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    # Strip ids: the file uses generic ones (Layer_1-2, Vector, Group) that
    # would collide with anything else on the page.
    svg = re.sub(r'\s+id="[^"]*"', "", svg)
    svg = re.sub(r'(<svg\b)', r"\1 aria-hidden='true' focusable='false'", svg, count=1)
    return svg.replace('"', "'").strip()


def json_ld(cfg: dict) -> tuple[str, str]:
    urls = cfg["urls"]
    org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": "https://youdle.io/#organization",
        "name": "Youdle",
        "url": "https://youdle.io/",
        "logo": cfg["seo"]["logo_url"],
        "description": cfg["site"]["definition"],
        "sameAs": cfg["seo"]["same_as"],
    }
    site = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": "https://news.youdle.io/#website",
        "name": cfg["site"]["title"],
        "url": urls["news"],
        "description": cfg["site"]["definition"],
        "inLanguage": "en-US",
        "publisher": {"@id": "https://youdle.io/#organization"},
    }
    # No SearchAction -- handoff section 7 forbids it until site search exists.
    def dump(obj: dict) -> str:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        return text.replace("&", "&amp;").replace("<", "&lt;")

    return dump(org), dump(site)


# --------------------------------------------------------------------------
# Splices
# --------------------------------------------------------------------------


def splice(theme: str, anchor: str, replacement: str, what: str) -> str:
    count = theme.count(anchor)
    if count != 1:
        raise SystemExit(
            f"ERROR: anchor for {what!r} matched {count} times, expected 1.\n"
            f"       The base theme has changed. Anchor:\n{anchor[:200]}"
        )
    return theme.replace(anchor, replacement, 1)


BLOG1_MAIN_ANCHOR = """                <b:includable id='main'>
          <b:include name='noContentPlaceholder'/>

          <!-- Display title on homepage -->
          <b:if cond='data:posts.any and data:view.isHomepage'>
            <h3 class='title'><data:messages.latestPosts/></h3>
          </b:if>
          <!-- Filter out the featured post, but only on the homepage. -->
          <b:with value='(data:widgets.FeaturedPost filter w =&gt; w.sectionId == &quot;page_body&quot;) map (w =&gt; w.postId)' var='featuredPostIds'>
            <b:with value='data:view.isHomepage ? data:posts filter (post =&gt; post.id not in data:featuredPostIds) : data:posts' var='posts'>
              <b:include name='super.main'/>
            </b:with>
          </b:with>
        </b:includable>"""


def blog1_main_replacement(main_part: str) -> str:
    return (
        """                <b:includable id='main'>
          <b:if cond='data:view.isHomepage'>
            <b:include name='youdleHomepage'/>
          <b:else/>
            <b:include name='noContentPlaceholder'/>
            <b:with value='(data:widgets.FeaturedPost filter w =&gt; w.sectionId == &quot;page_body&quot;) map (w =&gt; w.postId)' var='featuredPostIds'>
              <b:with value='data:view.isHomepage ? data:posts filter (post =&gt; post.id not in data:featuredPostIds) : data:posts' var='posts'>
                <b:include name='super.main'/>
              </b:with>
            </b:with>
          </b:if>
        </b:includable>
                <b:includable id='youdleHomepage'>
"""
        + main_part
        + "\n</b:includable>"
    )


def deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def build(base_path: Path, out_path: Path | None, overrides: dict | None = None) -> str:
    """Splice the homepage into the base theme. Returns the theme XML.

    ``overrides`` is deep-merged over config.json; preview.py uses it to point
    image URLs at the local asset server without touching the checked-in
    config.
    """
    cfg = json.loads((SRC / "config.json").read_text(encoding="utf-8"))
    if overrides:
        cfg = deep_merge(cfg, overrides)
    parts = read_parts(SRC / "homepage.xml")

    css = (SRC / "homepage.css").read_text(encoding="utf-8")
    js = (SRC / "homepage.js").read_text(encoding="utf-8")

    # <style> content is ordinary character data: & and < must be escaped.
    css_xml = css.replace("&", "&amp;").replace("<", "&lt;")
    # <script> content is wrapped in CDATA, which only forbids the terminator.
    if "]]>" in js:
        raise SystemExit("ERROR: homepage.js contains ']]>', which closes the CDATA block.")

    org_ld, site_ld = json_ld(cfg)
    ctx = dict(cfg)
    ctx.update(
        {
            "css": css_xml,
            "js": js,
            "logo_svg": load_logo(),
            "jsonld_org": org_ld,
            "jsonld_site": site_ld,
        }
    )

    rendered = {name: render(text, ctx) for name, text in parts.items()}

    theme = base_path.read_text(encoding="utf-8")

    # blogger/theme.original.xml predates the Youdle post chrome. Building from
    # it would silently produce a theme that strips the newsletter signup and
    # the back link from every article page.
    for fragment, what in (
        ("<b:includable id='youdleNewsletterSignup'>", "the post-page newsletter signup"),
        ("youdle-back-nav", "the article back link"),
    ):
        if fragment not in theme:
            raise SystemExit(
                f"ERROR: {base_path.name} is missing {what}." + NEWLINE
                + "       That is an older theme, not the one Blogger is serving."
                + NEWLINE
                + "       Re-download the live theme (Blogger -> Theme -> Backup)."
            )

    if "youdleHomepage" in theme:
        raise SystemExit(
            "ERROR: the base theme already contains the homepage build.\n"
            "       Point --base at the pristine theme downloaded from Blogger."
        )

    # 1. <head>: fonts, Twitter Card, JSON-LD, homepage stylesheet.
    theme = splice(theme, "\n  </head>", "\n" + rendered["head"] + "\n  </head>", "head block")

    # 2. Scope hook on <body> so the header (outside .page) and the sections
    #    (inside <main>) share one CSS scope.
    theme = splice(
        theme,
        "    <b:class cond='data:view.isHomepage' name='homepage-view'/>",
        "    <b:class cond='data:view.isHomepage' name='homepage-view'/>\n"
        "    <b:class cond='data:view.isHomepage' name='yd-home'/>",
        "body class hook",
    )

    # 3. Header: a direct child of <body>, so it sits outside <main> and is not
    #    inside a b:section (which may only contain b:widget children).
    theme = splice(
        theme,
        "    <b:include name='skipNavigation'/>",
        "    <b:include name='skipNavigation'/>\n" + rendered["header"],
        "header",
    )

    # 4. Sections 02-06 inside the Blog1 widget, the only scope with data:posts.
    theme = splice(
        theme, BLOG1_MAIN_ANCHOR, blog1_main_replacement(rendered["main"]), "Blog1 main includable"
    )

    # 5. Footer: after .page closes, before the off-canvas drawer.
    theme = splice(
        theme,
        "    <aside class='sidebar-container container sidebar-invisible' role='complementary'>",
        rendered["footer"]
        + "\n    <aside class='sidebar-container container sidebar-invisible' role='complementary'>",
        "footer",
    )

    # 6. Behaviour script, last thing before </body>.
    theme = splice(theme, "\n  </body>", "\n" + rendered["script"] + "\n  </body>", "script")

    # 7. The stock screen-reader "Posts" heading is meaningless on the new
    #    homepage, which has its own H1 and section headings.
    theme = splice(
        theme,
        """            <b:if cond='data:view.isMultipleItems'>
              <h2 class='main-heading'><data:messages.posts/></h2>
            </b:if>""",
        """            <b:if cond='data:view.isMultipleItems and not data:view.isHomepage'>
              <h2 class='main-heading'><data:messages.posts/></h2>
            </b:if>""",
        "main-heading gate",
    )

    # 8. The stock Header widget emits <h1>{blog title}</h1>. CSS hides it, but
    #    crawlers still read it, and handoff section 7 requires exactly one H1.
    #    Skip the widget on the homepage the same way the theme already skips
    #    FeaturedPost1 -- with cond on b:widget.
    theme = splice(
        theme,
        "<b:widget id='Header1' locked='true' title='Youdle grocery news to save time and money. (Header)' type='Header' visible='true'>",
        "<b:widget cond='not data:view.isHomepage' id='Header1' locked='true' title='Youdle grocery news to save time and money. (Header)' type='Header' visible='true'>",
        "Header1 homepage gate",
    )

    # 9. Masonry, imagesLoaded and clipboard drive the stock feed and post
    #    views only. Skip them on the homepage -- handoff section 8, "keep
    #    third-party scripts minimal".
    theme = splice(
        theme,
        """    <script async='async' src='https://www.gstatic.com/external_hosted/imagesloaded/imagesloaded-3.1.8.min.js'/>
    <script async='async' src='https://www.gstatic.com/external_hosted/vanillamasonry-v3_1_5/masonry.pkgd.min.js'/>
    <script async='async' src='https://www.gstatic.com/external_hosted/clipboardjs/clipboard.min.js'/>""",
        """    <b:if cond='not data:view.isHomepage'>
      <script async='async' src='https://www.gstatic.com/external_hosted/imagesloaded/imagesloaded-3.1.8.min.js'/>
      <script async='async' src='https://www.gstatic.com/external_hosted/vanillamasonry-v3_1_5/masonry.pkgd.min.js'/>
      <script async='async' src='https://www.gstatic.com/external_hosted/clipboardjs/clipboard.min.js'/>
    </b:if>""",
        "third-party scripts gate",
    )

    validate(theme)
    missing = [fragment for fragment in REQUIRED_FRAGMENTS if fragment not in theme]
    if missing:
        print("\nBUILD FAILED\n", file=sys.stderr)
        for fragment in missing:
            print(f"  - expected fragment missing from output: {fragment}", file=sys.stderr)
        raise SystemExit(1)
    if out_path is not None:
        # newline="" keeps LF: write_text would translate to CRLF on Windows,
        # so the bytes on disk would differ from the string just validated.
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(theme)
    return theme


# --------------------------------------------------------------------------
# Validation -- catches every "Error parsing XML" Blogger would report
# --------------------------------------------------------------------------

ALLOWED_ENTITY = re.compile(r"&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
CDATA = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)



COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _blank(match: re.Match) -> str:
    return "".join(c if c == NEWLINE else " " for c in match.group(0))


def blank_cdata(theme: str) -> str:
    """Blank out CDATA content while preserving its length and its newlines,
    so byte offsets after it still map to real line numbers."""
    return CDATA.sub(_blank, theme)


def blank_comments(theme: str) -> str:
    """Same trick for XML comments, whose contents follow different rules."""
    return COMMENT.sub(_blank, theme)


VOID = ("br", "img", "input", "meta", "hr", "link", "source", "area", "col", "embed", "wbr")


# Every one of these is a section the index cannot render without. They are
# checked after a full build, not inside validate(), which also runs against
# small synthetic documents in the test suite.
REQUIRED_FRAGMENTS = (
    "<b:includable id='youdleHomepage'>",
    "name='yd-home'",
    "class='yd-masthead'",
    "class='yd-filters'",
    "class='yd-list'",
    "class='yd-footer'",
    "id='the-youdle-brief'",
)


def validate(theme: str) -> None:
    problems = []

    try:
        xml.dom.minidom.parseString(theme.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - we want the parser's own message
        problems.append(f"not well-formed XML: {exc}")

    # Everything below reports line numbers against the real file, so CDATA and
    # comments are blanked in place rather than removed.
    outside_cdata = blank_cdata(theme)

    def line_of(text: str, offset: int) -> int:
        return text[:offset].count(NEWLINE) + 1

    # Blogger's doctype declares no entity set, so only the five XML built-ins
    # and numeric references are legal. Comments are exempt: an ampersand
    # inside one is legal XML, and the stock theme has 33 comments.
    scannable = blank_comments(outside_cdata)
    for match in re.finditer(r"&[^\s;]{0,12};?", scannable):
        token = match.group(0)
        if not ALLOWED_ENTITY.fullmatch(token):
            problems.append(
                f"line {line_of(scannable, match.start())}: "
                f"illegal entity or bare ampersand {token!r}"
            )

    # A void element must be self-closed. The attribute pattern is quote-aware,
    # so a legal `>` inside an attribute value is not mistaken for the tag end.
    for tag in VOID:
        pattern = rf"""<{tag}\b(?:[^>"']|"[^"]*"|'[^']*')*?(?<!/)>"""
        for match in re.finditer(pattern, outside_cdata):
            problems.append(
                f"line {line_of(outside_cdata, match.start())}: <{tag}> is not self-closed"
            )

    for match in re.finditer(r"<!--(.*?)-->", outside_cdata, re.DOTALL):
        if "--" in match.group(1):
            problems.append(
                f"line {line_of(outside_cdata, match.start())}: "
                "'--' inside an XML comment"
            )

    if problems:
        print("\nBUILD FAILED\n", file=sys.stderr)
        for problem in problems[:40]:
            print(f"  - {problem}", file=sys.stderr)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="theme downloaded from Blogger")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="theme to write")
    args = parser.parse_args()

    if not args.base.exists():
        raise SystemExit(f"ERROR: base theme not found: {args.base}")
    if args.out.resolve() == args.base.resolve():
        raise SystemExit(
            "ERROR: --out is the same file as --base. The base theme is the "
            "pristine copy downloaded from Blogger and must not be overwritten."
        )

    build(args.base, args.out)
    out = args.out
    size = out.stat().st_size
    print(f"OK  {out}  ({size:,} bytes)")
    print("    XML is well-formed and entity-clean.")

    # The index carries no theme-hosted photography: every image on the page is
    # a post's own featured image, which Blogger resolves at render time. What
    # is worth reporting instead is the category chips, since each one points at
    # a raw Blogger label and a typo there yields a silently empty label page.
    cfg = json.loads((SRC / "config.json").read_text(encoding="utf-8"))
    chips = [v["blogger_label"] for k, v in cfg["categories"].items()
             if not k.startswith("_")]
    print()
    print(f"    {len(chips)} category chip(s) -> labels: " + ", ".join(chips))
    print("    Each must match a label on the blog exactly; Blogger label URLs")
    print("    are case sensitive. See README 'Label hygiene'.")

    print()
    print("    Upload in Blogger: Theme -> ... -> Restore -> Upload")


if __name__ == "__main__":
    main()
