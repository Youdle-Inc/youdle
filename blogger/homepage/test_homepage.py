#!/usr/bin/env python3
"""Test the news.youdle.io homepage.

    python blogger/homepage/test_homepage.py

Two tiers:

  static   builds the theme and inspects the rendered HTML. No browser, no
           network. Covers XML/Blogger safety, the handoff's copy and link map,
           semantics, structured data and image hygiene.

  browser  drives the page in headless Chrome or Edge, if one is installed.
           Covers the menu, the newsletter form's states, analytics events, and
           whether the stock theme's CSS is actually being overridden.

The browser tier is skipped with a notice when no browser is found; the static
tier always runs. Exit code is non-zero if anything fails.
"""

from __future__ import annotations

import contextlib
import io
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.dom.minidom
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_theme  # noqa: E402
import preview  # noqa: E402

REPO = HERE.parent.parent
THEME_OUT = REPO / "theme-youdle-homepage.xml"  # verified, never overwritten here

BROWSERS = [
    os.environ.get("CHROME"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser",
]

# Every string the index is required to carry. Apostrophes are typographic.
PAGE_COPY = [
    "Youdle News",
    "Grocery recalls, price moves and shopper finds \u2014 newest first.",
    "All",
    "Recalls",
    "Grocery news",
    "For grocers",
    "Emergency prep",
    "Prices & deals",
    "Older articles",
    "Get The Youdle Brief.",
    "Recalls, price moves and the week\u2019s grocery news, in one email.",
    "Subscribe",
]

ANALYTICS_EVENTS = [
    "category_filter_click", "article_click", "pager_older_click",
    "newsletter_form_start", "newsletter_signup_success", "newsletter_signup_error",
]

results: list[tuple[bool, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((bool(condition), name, detail))


# --------------------------------------------------------------------------
# Static tier
# --------------------------------------------------------------------------


def tooling_checks() -> None:
    """The build tooling itself: a validator that cries wolf, or a template
    engine that mis-pairs a nested block, silently ships a wrong theme."""

    # The template engine must pair the innermost {{#if}} with its own {{/if}}.
    for template, ctx, expected in [
        ("{{#if a}}A{{#if b}}B{{/if}}C{{/if}}", {"a": 1, "b": 0}, "AC"),
        ("{{#if a}}A{{#if b}}B{{/if}}C{{else}}D{{/if}}", {"a": 1, "b": 0}, "AC"),
        ("{{#if a}}A{{#if b}}B{{/if}}C{{else}}D{{/if}}", {"a": 0, "b": 1}, "D"),
        ("{{#if a}}X{{#if b}}Y{{#if c}}Z{{/if}}W{{/if}}V{{/if}}",
         {"a": 1, "b": 1, "c": 1}, "XYZWV"),
        ("{{#if a}}1{{/if}}{{#if b}}2{{/if}}", {"a": 1, "b": 1}, "12"),
    ]:
        got = build_theme.render(template, ctx)
        check(f"template engine: {template[:34]}", got == expected, f"got {got!r}")

    # A mistyped key must fail the build rather than take the else branch.
    try:
        build_theme.render("{{#if nope.missing}}x{{/if}}", {"a": 1})
        check("template engine rejects an unknown key", False)
    except build_theme.TemplateError:
        check("template engine rejects an unknown key", True)

    # No stray control bytes in the sources: a literal 0x08 inside a regex
    # looks identical to \b in every editor and silently disables the guard.
    for name in ("build_theme.py", "preview.py", "bloggerlite.py", "README.md",
                 "upload_assets.py",
                 "src/homepage.css", "src/homepage.js", "src/homepage.xml",
                 "src/config.json", "mock_posts.json"):
        text = (HERE / name).read_text(encoding="utf-8")
        bad = [c for c in text if ord(c) < 32 and c not in "\n\t"]
        check(f"no control bytes in {name}", not bad, repr(bad[:3]))

    # The validator must reject what Blogger rejects and accept what it accepts.
    req = (
        "<b:includable id='youdleHomepage'>x</b:includable>"
        "<b:class name='yd-home'/>"
        "<div class='yd-header'></div><div class='yd-footer'></div>"
        "<div id='the-youdle-brief'></div>"
    )
    for label, inner, should_pass in [
        ("a > inside an attribute value", "<img alt='Prices > $5' src='x'/>", True),
        ("an ampersand inside a comment", "<!-- Tom &amp; Jerry -->", True),
        ("a numeric entity", "<p>&#160;ok</p>", True),
        ("an ampersand inside CDATA", "<script>//<![CDATA[ if(a && b){} //]]></script>", True),
        ("an unclosed void element", "<img src='a'>", False),
        ("a named entity", "<p>&nbsp;</p>", False),
        ("a bare ampersand", "<p>&oops</p>", False),
        ("a double hyphen in a comment", "<!-- a -- b -->", False),
    ]:
        doc = f"<root xmlns:b='http://www.google.com/2005/gml/b'>{req}{inner}</root>"
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stderr(buffer):
                build_theme.validate(doc)
            accepted = True
        except SystemExit:
            accepted = False
        verb = "accepts" if should_pass else "rejects"
        check(f"validator {verb} {label}", accepted == should_pass)


def static_checks() -> str:
    # Build in memory: running the tests must not rewrite the committed
    # artifact. Whether the file on disk is current is checked separately.
    theme = build_theme.build(preview.BASE_THEME, None)

    try:
        xml.dom.minidom.parseString(theme.encode("utf-8"))
        check("theme parses as strict XML", True)
    except Exception as exc:  # noqa: BLE001
        check("theme parses as strict XML", False, str(exc))

    outside_cdata = build_theme.CDATA.sub("", theme)
    bad = [
        m.group(0)
        for m in re.finditer(r"&[^\s;]{0,12};?", outside_cdata)
        if not build_theme.ALLOWED_ENTITY.fullmatch(m.group(0))
    ]
    check("no illegal entities or bare ampersands", not bad, ", ".join(bad[:4]))

    check("committed theme matches its sources",
          THEME_OUT.exists() and THEME_OUT.read_text(encoding="utf-8") == theme,
          "run build_theme.py -- the checked-in artifact is stale")
    check("no Apps Script /exec endpoint in the theme", "AKfycb" not in theme)

    check("homepage includable present", "<b:includable id='youdleHomepage'>" in theme)
    check("stock post chrome untouched",
          "<b:includable id='youdleNewsletterSignup'>" in theme and "youdle-back-nav" in theme)
    check("stock Blog markup still reachable off the homepage",
          "<b:include name='super.main'/>" in theme)
    check("Header1 gated off the homepage",
          "<b:widget cond='not data:view.isHomepage' id='Header1'" in theme)

    base = preview.BASE_THEME.read_text(encoding="utf-8")
    for fragment in ("youdleNewsletterSignup", "youdle-back-nav", "Attribution1", "BlogArchive1"):
        check(f"base fragment preserved: {fragment}", fragment in base and fragment in theme)

    # Render the page the same way preview.py does.
    page = preview.render("mock", "local")

    body = page.split("<body", 1)[1]
    check("exactly one <h1> in the document", body.count("<h1") == 1, f"found {body.count('<h1')}")
    check("no placeholder # links", 'href="#"' not in page)
    check("has a banner landmark", 'class="yd-masthead" role="banner"' in page)
    check("has a contentinfo landmark", 'class="yd-footer" role="contentinfo"' in page)

    # The index lists every post Blogger gave it. The old homepage sliced the
    # feed to three cards; a news index that quietly drops articles is the bug
    # this page exists to fix, so the count is asserted against the fixture.
    mock_count = len(json.loads(
        (HERE / "mock_posts.json").read_text(encoding="utf-8"))["posts"])
    check("every post in the feed is listed",
          page.count('<li class="yd-item">') == mock_count,
          f'{page.count(chr(60) + "li class=" + chr(34) + "yd-item" + chr(34) + chr(62))} rows '
          f'for {mock_count} posts')
    check("the list is an ordered list", '<ol class="yd-list__items">' in page)
    check("category chips present", page.count('class="yd-chip') >= 6)
    check("pager renders when there is an older page", 'class="yd-pager__link' in page)

    # Strip markup first: the H1 is broken up by the accent-underline span, and
    # the newsletter headline by its two-line spans.
    visible = re.sub(r"<script\b.*?</script>", " ", page, flags=re.S)
    visible = re.sub(r"<style\b.*?</style>", " ", visible, flags=re.S)
    visible = re.sub(r"<[^>]+>", "", visible)
    visible = re.sub(r"\s+", " ", visible)
    # Entities, so copy carrying an ampersand is compared as a reader sees it.
    visible = html.unescape(visible)
    for text in PAGE_COPY:
        check(f"page copy present: {text[:44]}", text in visible)

    cfg = json.loads((HERE / "src" / "config.json").read_text(encoding="utf-8"))
    for key, url in cfg["urls"].items():
        if key.startswith("_") or key == "news":
            continue
        check(f"link map: {key}", url in page, url)

    # Each chip points at a raw Blogger label; a typo yields a label page that
    # is silently empty, which is indistinguishable from a quiet week.
    for key, chip in cfg["categories"].items():
        if key.startswith("_"):
            continue
        check(f"chip targets a label: {chip['label']}",
              f'search/label/{chip["blogger_label"]}"' in page,
              chip["blogger_label"])

    for event in ANALYTICS_EVENTS:
        check(f"analytics event wired: {event}", event in page)

    css = (HERE / "src" / "homepage.css").read_text(encoding="utf-8")

    # '.yd-home a { color: inherit }' is (0,1,1) and silently outranks any
    # component rule that colours an anchor. The active chip was invisible that
    # way -- dark text on the dark pill -- so every such rule stays scoped.
    anchor_rules = re.findall(
        r"^(\.yd-(?:chip|item__chip|item__title a|pager__link|footer__links a)[^{,]*),?$",
        css, re.M)
    check("anchor-colouring rules outrank the link reset",
          not anchor_rules,
          ", ".join(r.strip() for r in anchor_rules[:3]))

    imgs = re.findall(r"<img\b[^>]*>", page)
    check("every image has alt text", all("alt=" in i for i in imgs), f"{len(imgs)} images")
    check("every image declares width and height",
          all("width=" in i and "height=" in i for i in imgs))
    below_fold = imgs[2:]
    check("below-fold images lazy-load",
          all('loading="lazy"' in i for i in below_fold),
          f"{len(below_fold)} below-fold images")

    ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    types = []
    for block in ld:
        try:
            types.append(json.loads(block)["@type"])
        except Exception:  # noqa: BLE001
            types.append("PARSE-ERROR")
    check("all JSON-LD parses", "PARSE-ERROR" not in types, ", ".join(types))
    check("Organization + WebSite + ItemList present",
          {"Organization", "WebSite", "ItemList"} <= set(types), ", ".join(types))
    check("no SearchAction", "SearchAction" not in page)

    check("fonts load with display=swap", "display=swap" in page)

    # The index hosts no photography of its own: every image is a post's
    # featured image, so a post without one must still render a tidy row.
    no_images = preview.render("mock", "none")
    check("a post with no image renders a placeholder, not a broken image",
          'class="yd-item__thumb-fallback"' in no_images and 'src=""' not in no_images)

    return page


# --------------------------------------------------------------------------
# Browser tier
# --------------------------------------------------------------------------

BROWSER_JS = r"""
(function () {
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[href]");
    if (a) { e.preventDefault(); }
  }, true);

  var out = [], events = [];
  function ok(n, c, d) { out.push((c ? "PASS|" : "FAIL|") + n + "|" + (d || "")); }
  document.addEventListener("youdle:analytics", function (e) {
    events.push(e.detail.name + ":" + (e.detail.params.placement || ""));
  });

  var rows = [].slice.call(document.querySelectorAll(".yd-item"));
  ok("the list renders rows", rows.length > 0, rows.length + " rows");

  var tops = rows.map(function (r) { return Math.round(r.getBoundingClientRect().top); });
  var ordered = tops.every(function (t, i) { return i === 0 || t >= tops[i - 1]; });
  ok("rows stack in document order", ordered, tops.slice(0, 4).join(","));

  var times = [].slice.call(document.querySelectorAll(".yd-item time[datetime]"))
    .map(function (t) { return t.getAttribute("datetime"); });
  var newestFirst = times.every(function (t, i) { return i === 0 || t <= times[i - 1]; });
  ok("articles are listed newest first", newestFirst, times.slice(0, 3).join(" "));

  var chips = [].slice.call(document.querySelectorAll(".yd-chip"));
  ok("every chip is a real link", chips.every(function (c) {
    var href = c.getAttribute("href") || "";
    return href.length > 1 && href.indexOf("#") !== 0;
  }));

  var active = document.querySelector(".yd-chip--active");
  var activeStyle = getComputedStyle(active);
  function luminance(rgb) {
    var m = rgb.match(/\d+/g) || [255, 255, 255];
    return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
  }
  // Regression guard: '.yd-home a { color: inherit }' outranks a bare
  // '.yd-chip--active', which rendered this chip as dark text on a dark pill.
  ok("the active chip's label contrasts with its fill",
     Math.abs(luminance(activeStyle.color) - luminance(activeStyle.backgroundColor)) > 0.4,
     activeStyle.color + " on " + activeStyle.backgroundColor);

  var pager = document.querySelector(".yd-pager__link--older");
  ok("the older-articles link is present and right-aligned",
     !!pager && pager.getBoundingClientRect().right > window.innerWidth / 2);

  var firstLink = document.querySelector(".yd-item__title a");
  firstLink.click();
  ok("an article click reports its position",
     events.join(",").indexOf("article_click:news_index") !== -1, events.join(","));

  var email = document.getElementById("yd-brief-email");
  var status = document.querySelector("[data-yd-newsletter-status]");
  var form = document.querySelector("[data-yd-newsletter]");
  ok("email field is programmatically labelled", !!document.querySelector('label[for="yd-brief-email"]'));
  ok("status region is polite-live", status.getAttribute("aria-live") === "polite");
  email.value = "x";
  email.dispatchEvent(new Event("input", { bubbles: true }));
  ok("newsletter_form_start fires once on first input",
     events.filter(function (e) { return e.indexOf("newsletter_form_start") === 0; }).length === 1);
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  ok("invalid email is rejected client-side",
     status.getAttribute("data-state") === "error" && status.textContent.length > 0, status.textContent);
  ok("aria-invalid is set", email.getAttribute("aria-invalid") === "true");
  ok("newsletter_signup_error is tracked", events.join(",").indexOf("newsletter_signup_error") !== -1);
  email.value = "";
  email.dispatchEvent(new Event("input", { bubbles: true }));
  ok("aria-invalid clears on edit", email.getAttribute("aria-invalid") === null);

  ok("the masthead title is the document's only h1",
     document.querySelectorAll("h1").length === 1 &&
     document.querySelector("h1").classList.contains("yd-masthead__title"));

  var chrome = [".centered-top-container", ".hero-image", "#footer", ".sidebar-container"];
  var shown = chrome.filter(function (s) {
    var el = document.querySelector(s);
    return el && getComputedStyle(el).display !== "none";
  });
  ok("stock theme chrome is hidden", shown.length === 0, shown.join(","));

  var main = document.getElementById("main");
  ok("stock width constraints are flattened",
     Math.abs(main.getBoundingClientRect().width - document.documentElement.clientWidth) < 2,
     main.getBoundingClientRect().width + " vs " + document.documentElement.clientWidth);

  // Regression guard for CSS specificity: the stock theme styles buttons, and
  // a bare .yd-btn--primary lost its fill to it once.
  ok("primary button keeps its fill",
     getComputedStyle(document.querySelector(".yd-btn--primary")).backgroundColor === "rgb(245, 180, 60)",
     getComputedStyle(document.querySelector(".yd-btn--primary")).backgroundColor);

  var h1 = document.querySelector(".yd-masthead__title");
  // A masthead, not a hero: the index leads with articles, so the title is
  // sized to identify the page rather than to fill the screen. The guard is
  // that it stays in the display face and stays larger than a headline in the
  // list below it.
  var leadTitle = document.querySelector(".yd-item__title");
  ok("masthead title is in the display face, above the list's headlines",
     getComputedStyle(h1).fontFamily.indexOf("Newsreader") === 0 &&
     parseFloat(getComputedStyle(h1).fontSize) >
       parseFloat(getComputedStyle(leadTitle).fontSize),
     getComputedStyle(h1).fontSize + " vs " + getComputedStyle(leadTitle).fontSize +
     " " + getComputedStyle(h1).fontFamily);

  ok("no horizontal overflow",
     document.documentElement.scrollWidth <= document.documentElement.clientWidth,
     document.documentElement.scrollWidth + " > " + document.documentElement.clientWidth);

  var deks = [].slice.call(document.querySelectorAll(".yd-item__dek"));
  ok("leftover post chrome stripped from deks",
     deks.every(function (d) { return d.textContent.indexOf("Back to Youdle") === -1; }),
     deks.map(function (d) { return d.textContent.slice(0, 24); }).join(" / "));

  // The hero photograph must never be cropped: cover at some window widths
  // sliced the left edge off the tote and magnified the rest.
  var hero = document.querySelector(".yd-hero__figure img");
  if (hero) {
    var hs = getComputedStyle(hero);
    ok("hero photo is contained, never cropped", hs.objectFit === "contain", hs.objectFit);
    var hbox = hero.getBoundingClientRect();
    var painted = Math.min(hbox.width / hero.naturalWidth, hbox.height / hero.naturalHeight);
    ok("whole hero photo fits its box",
       hero.naturalWidth * painted <= hbox.width + 1 &&
       hero.naturalHeight * painted <= hbox.height + 1,
       Math.round(hero.naturalWidth * painted) + "x" + Math.round(hero.naturalHeight * painted) +
       " in " + Math.round(hbox.width) + "x" + Math.round(hbox.height));
    ok("hero photo reaches the viewport's right edge",
       hbox.right >= document.documentElement.clientWidth - 1,
       Math.round(hbox.right) + " vs " + document.documentElement.clientWidth);
  }

  var pre = document.createElement("pre");
  pre.id = "ydtestout";
  pre.textContent = out.join(String.fromCharCode(10));
  document.body.appendChild(pre);
})();
"""


def find_browser() -> str | None:
    for candidate in BROWSERS:
        if not candidate:
            continue
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def browser_checks(page: str) -> bool:
    browser = find_browser()
    if not browser:
        print("  (no Chrome or Edge found - skipping the browser tier)")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "page.html").write_text(
            page.replace('"/assets/', '"assets/')
                .replace("</body>", '<script src="t.js"></script></body>'),
            encoding="utf-8",
        )
        (root / "t.js").write_text(BROWSER_JS, encoding="utf-8")
        # Copy the assets the page references so images resolve.
        assets = root / "assets"
        shutil.copytree(HERE / "assets", assets)

        proc = subprocess.run(
            [
                browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                "--allow-file-access-from-files", "--force-device-scale-factor=1",
                "--window-size=1400,900", "--virtual-time-budget=8000", "--dump-dom",
                (root / "page.html").as_uri(),
            ],
            # Not text=True: that decodes with the locale codec, which on a
            # Windows console is cp1252 and cannot represent the page's
            # typographic punctuation or arrows.
            capture_output=True, encoding="utf-8", errors="replace", timeout=120,
        )

    match = re.search(r'<pre id="ydtestout">(.*?)</pre>', proc.stdout, re.S)
    if not match:
        check("browser tier ran", False, "no output from the page")
        return True

    import html as htmlmod

    for line in htmlmod.unescape(match.group(1)).splitlines():
        state, _, rest = line.partition("|")
        name, _, detail = rest.partition("|")
        check(name, state == "PASS", detail)
    return True


# --------------------------------------------------------------------------


def main() -> None:
    print("\nYoudle homepage tests\n")

    print("  tooling")
    tooling_checks()

    print("  static")
    page = static_checks()
    static_count = len(results)

    print("  browser")
    browser_checks(page)

    failures = [r for r in results if not r[0]]
    for passed, name, detail in results:
        if not passed:
            print(f"    FAIL  {name}" + (f"  [{detail}]" if detail else ""))

    print(
        f"\n  {len(results) - len(failures)}/{len(results)} passed "
        f"({static_count} static, {len(results) - static_count} browser)\n"
    )
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
