# Youdle homepage — news.youdle.io

A full redesign of the **news.youdle.io** homepage, implementing
`Youdle_Homepage_Developer_Package/Youdle_Homepage_Developer_Handoff.docx`
against `Youdle_Homepage_Approved_Mockup.png`.

Only the homepage view changes. Post, archive, label, search and page views
render exactly as they do today — every addition is gated on
`data:view.isHomepage`, and the homepage stylesheet is not even loaded on other
views.

---

## Quick start

```bash
# See it, with live stories from the real news.youdle.io feed
python blogger/homepage/preview.py                 # http://localhost:5173

# Offline, with the fixture in mock_posts.json
python blogger/homepage/preview.py --source mock

# Build the theme file to upload
python blogger/homepage/build_theme.py             # -> theme-youdle-homepage.xml

# Check it still holds together
python blogger/homepage/test_homepage.py           # 108 checks
```

Then in Blogger: **Theme → ⋮ → Restore → Upload** `theme-youdle-homepage.xml`.
(Take a backup first: **Theme → ⋮ → Backup**.)

No dependencies beyond the Python standard library.

---

## How the local preview works

`preview.py` is not a mockup of the homepage — it renders the homepage **out of
the generated Blogger theme**. On every request it:

1. runs the real `build_theme.build()`,
2. pulls the generated `<style>`, header, `youdleHomepage` includable, footer
   and script straight out of the resulting XML,
3. evaluates the Blogger template language in them (`b:if`, `b:loop`, `b:with`,
   `b:eval`, `expr:`, `data:` references, `snippet()`, `format()`,
   `resizeImage()`) with `bloggerlite.py`,
4. resolves the stock theme's own `b:skin` CSS — including Blogger's
   `$(variable)` syntax and its arithmetic — and includes it, so the layout
   overrides are tested against the same cascade Blogger applies,
5. reproduces the exact wrapper chain Blogger emits around the Blog widget.

So the preview exercises the artifact you upload. Edit anything in `src/` and
refresh; there is no build step to remember and nothing that can drift.

Story cards come from `https://news.youdle.io/feeds/posts/default` by default
and fall back to `mock_posts.json` if the feed is unreachable.

Useful flags:

| Flag | Effect |
|---|---|
| `--source mock` | offline fixture instead of the live feed |
| `--images none` | show the CSS placeholders you get before images are hosted |
| `--snapshot out.html` | write one rendered page and exit |
| `--port 5173` | change the port |

---

## Tests

`python blogger/homepage/test_homepage.py` runs 108 checks in three tiers.

**Tooling** (the build itself): the template engine pairs nested `{{#if}}`
blocks correctly and rejects an unknown key rather than silently taking the
else branch; no source file contains a control byte (a literal `0x08` inside a
regex is indistinguishable from `\b` in any editor and silently disables the
guard around it — that exact bug happened here and this check now catches it);
and the XML validator accepts what Blogger accepts (a `>` inside an attribute,
an `&` inside a comment, numeric entities, `&&` inside CDATA) while still
rejecting what it rejects (unclosed void elements, named entities, bare
ampersands, `--` inside a comment).

**Static** (no browser, no network): the theme parses as strict XML and is
entity-clean; the stock post chrome and the non-homepage Blog markup are
untouched; exactly one `<h1>`; no `#` links; every string in the handoff's copy
map is on the page; every URL in the link map is on the page; every analytics
event is wired; Accent Yellow appears only on the hero stroke; every image has
alt text, intrinsic dimensions and lazy-loading below the fold; all JSON-LD
parses and contains Organization + WebSite + ItemList with no SearchAction; and
the page degrades to styled placeholders — not broken images — when no image
URLs are configured.

**Browser** (headless Chrome or Edge, skipped with a notice if neither is
installed): the menu opens, moves focus, closes on Escape and on an outside
click, and restores focus; the newsletter field is programmatically labelled,
rejects an invalid address without a network call, sets and clears
`aria-invalid`, and announces through a polite live region; analytics fire with
placement data; the stock theme's chrome is computed-hidden and its width
constraints are actually flattened; the primary button keeps its fill and the H1
renders at display size in Newsreader (both regression guards for CSS
specificity); the hero photograph is contained rather than cropped, fits its
box whole and still reaches the viewport's right edge; and there is no
horizontal overflow.

---

## Files

```
blogger/homepage/
  src/
    homepage.xml      markup: head block, header, sections 02-06, footer, script
    homepage.css      all styling (theme overrides, tokens, components, responsive)
    homepage.js       menu, analytics, newsletter submit with success/error states
    config.json       URLs, copy, image URLs, Mailchimp endpoint
  assets/img/         starter placeholder images cropped from the approved comp
  build_theme.py      splices src/ into the live theme + validates the XML
  preview.py          local server
  bloggerlite.py      the small Blogger template evaluator preview.py runs on
  test_homepage.py    the test suite
  mock_posts.json     offline story fixture
```

Generated, at the repo root: **`theme-youdle-homepage.xml`** (the upload file).
`theme-2263602681587126671.xml` is the untouched base downloaded from Blogger.

---

## What the build changes in the theme

Nine splices, each anchored on an exact string. If Blogger has rewritten the
base theme, an anchor stops matching and the build fails loudly rather than
producing a half-patched file.

| # | Where | Change |
|---|---|---|
| 1 | `<head>` | Google Fonts (Newsreader + Inter), `theme-color`, Twitter Card tags, Organization + WebSite JSON-LD, and the homepage `<style>` — all inside `<b:if cond='data:view.isHomepage'>` |
| 2 | `<body>` | adds the `yd-home` class on the homepage, so the header (outside `<main>`) and the sections (inside it) share one CSS scope |
| 3 | after `skipNavigation` | the header — a direct child of `<body>`, which keeps it out of `<main>` and out of a `b:section` (those may only contain `b:widget` children) |
| 4 | `Blog1`'s `main` includable | on the homepage, calls a new `youdleHomepage` includable holding sections 02–06; otherwise runs the stock markup unchanged |
| 5 | after `.page` | the footer, before the off-canvas drawer |
| 6 | before `</body>` | `homepage.js`, wrapped in `//<![CDATA[` |
| 7 | `main-heading` | the stock screen-reader "Posts" `<h2>` is skipped on the homepage, which has its own headings |
| 8 | `Header1` | the stock Header widget emits `<h1>{blog title}</h1>`. CSS hid it, but crawlers still read it and handoff §7 requires exactly one H1 — so the widget is skipped on the homepage, the same way the theme already skips `FeaturedPost1` |
| 9 | third-party scripts | masonry, imagesLoaded and clipboard.js drive the stock feed and post views only, so they are skipped on the homepage (handoff §8, "keep third-party scripts minimal") |

Sections 02–06 have to live inside `Blog1` because that is the only scope where
`data:posts` exists. Adding a custom includable to the locked stock `Blog`
widget is the same pattern the theme already uses for `youdleNewsletterSignup`.

`build_theme.py` validates the output before writing: strict XML parse, no bare
`&`, no named entities (Blogger's doctype declares none — `&nbsp;` is a parse
error), every void element self-closed, no `--` inside an XML comment. That
catches every "Error parsing XML" Blogger would report at upload.

---

## Configuration

### Images

Blogger cannot host theme assets, so the four static images need absolute URLs.
Set them in `src/config.json` and rebuild:

```json
"images":  { "hero": "https://…", "grocery": "https://…" },
"community_posts": { "one": { "image": "https://…" }, … }
```

**Any URL left empty renders a styled CSS placeholder, not a broken image** — so
the page is presentable the moment it goes up.

The hero photo is displayed with `object-fit: contain`, not `cover`, so it is
never cropped at any window width — the shot's own white background matches the
page, so the slack that leaves is invisible rather than letterboxed. If your
photograph has different proportions, update `--yd-hero-ratio` in
`homepage.css` (it only affects how much blank space appears when the hero
stacks; a mismatch can never crop the image).

`assets/img/` holds starter crops taken from the approved comp, in PNG and
WebP. They are good enough to ship a v1, but they came out of a 1024×1536
comp: **replace them with real photography** (hero ≥1200×1100, community cards
≥600×400, grocery visual ≥780×580). Upload them anywhere with a stable URL —
Blogger's own image hosting works — and paste the URLs into `config.json`.

The phone mock in the Grocery List section is real HTML/CSS, not an image, so
"Milk / Eggs / Bread / Bananas / Spinach" stays crawlable (handoff §7: do not
render essential meaning only inside images).

### Story cards

The three cards come from the three most recent Blogger posts — image, category,
date, headline and dek, all live. Nothing to maintain.

The live blog's labels are the raw pipeline constants (`SHOPPERS`, `RECALL`,
`recall`, `GROCERS`, `EMERGENCY`, `deals`), which are not what the comp shows,
so the template maps them to reader-facing names:

| Label | Chip |
|---|---|
| `RECALL`, `recall`, `Recall`, `consumer warning` | Recalls & Warnings |
| `deals`, `Deals`, `DEALS` | Prices & Deals |
| `SHOPPERS`, `shoppers`, `Shoppers` | Grocery News |
| `GROCERS`, `grocers` | For Grocers |
| `EMERGENCY`, `emergency` | Emergency Prep |
| anything else | the label as written |

Edit the mapping in `src/homepage.xml` (search for `ydLabel`).

> Worth fixing separately: `recall` (7 posts) and `RECALL` (6 posts) are two
> different Blogger labels, so 13 recall posts are split across two archive URLs.

### Newsletter

Reuses the existing Mailchimp list — same endpoint, same audience, same honeypot
as the theme's `youdleNewsletterSignup`. `homepage.js` upgrades the form to
Mailchimp's JSONP endpoint so success and error states render inline instead of
navigating away; with JavaScript off it posts normally.

### Analytics

Every event from handoff §8 fires with `placement` data, pushed to `dataLayer`
and `gtag` when present, and always emitted as a `youdle:analytics` DOM event:

`hero_news_click`, `hero_community_click`, `homepage_story_click`,
`view_all_stories_click`, `community_cta_click`, `grocery_list_click`,
`newsletter_form_start`, `newsletter_signup_success`, `newsletter_signup_error`
(plus `nav_*_click` and `newsletter_cta_click` for the header).

---

## Link map

Every URL was fetched and confirmed live on 2026-08-31. No `#` placeholders
anywhere on the page.

| Element | Destination |
|---|---|
| Logo, Grocery Today nav, footer Grocery Today | `data:blog.homepageUrl` (news.youdle.io) |
| Hero primary CTA ("See What's Happening") | `#yd-stories` — see decision 12 |
| View all stories | `data:blog.homepageUrl + "search"` — see decision 12 |
| Community nav / hero secondary / community CTAs | `https://www.youdle.io/community` |
| Grocery List nav + CTA | `https://www.youdle.io/grocery` |
| About Youdle | `https://www.youdle.io/about-us` |
| Contact | `https://forms.gle/mmFXxZwx71bjnKta8` (the feedback form Youdle's own footer links) |
| Advertise With Us | `mailto:info@getyoudle.com?subject=Advertising with Youdle` |
| Privacy Policy | `https://www.youdle.io/privacy-policy` |
| Terms of Use | `https://www.youdle.io/terms` |
| Community Guidelines | `https://www.youdle.io/terms#acceptable-use-policy` |
| Social | Facebook group, Instagram, TikTok, `mailto:info@getyoudle.com` |

---

## Blogger settings to update

`<title>`, the meta description and the Open Graph tags are emitted by Blogger
from **Settings**, not by the theme, so the theme does not duplicate them.
Update them there so all three stay consistent:

- **Blog title** — currently "Youdle grocery news to save time and money."
- **Settings → Meta tags → Search description** — currently "in stock groceries,
  near me, recalls, shortages, consumer news, shopping, deals." A sentence reads
  better for answer engines, e.g. *"Grocery Today from Youdle: recalls, price
  changes, shopper finds and the grocery news worth knowing."*
- **Settings → Formatting → Date header format** does not affect the cards — they
  use `format(data:post.date, "MMMM d, YYYY")` explicitly.

The canonical URL Blogger emits for this page is `https://news.youdle.io/`. The
handoff's `https://youdle.io/` canonical applies to the main site, not here.

---

## Do these before launch

Two things are not right in the underlying content, and both show on the
homepage.

**1. Post bodies still contain the old back-link.** 16 of the 150 most recent
posts — including all three currently newest, so all three story cards — begin
with a `← Back to Youdle` link baked into the body by the old generator. Blogger
builds `data:post.snippets.long` from the body, so it leaks into the dek. The
same stale markup is why every article page currently renders the back link
**twice**. The fix is already in this repo:

```bash
python backfill_strip_post_chrome.py            # dry run
python backfill_strip_post_chrome.py --apply --push-blogger
```

`homepage.js` strips the known prefix client-side so the page looks right in the
meantime, but crawlers and answer engines still see the raw text. Delete that
block (it is clearly marked) once the backfill has run.

**2. The three community posts are invented.** "Tina M. found these for $2.49"
and the other two are placeholder content from the comp, and the handoff scopes
them as preview only ("No required link for V1"). On a live page they read as
real shoppers. Before launch, either wire them to real Community posts, label
the block as sample content, or drop it. This is a judgement call, not something
to leave to the developer.

---

## Decisions that need your sign-off

The handoff says to flag conflicts rather than guess (§1, §10). These are the
ones found:

0. **Heading colour.** Sampled from the comp: only the hero H1 is Deep Green
   (`#053219` there). The nav, all eyebrows, the story headlines and both panel
   H2s are pure black. The handoff's palette table instead assigns Deep Green to
   "headings". Built to the comp, using the palette's Charcoal `#222222` — so
   the visual direction is the comp's and every colour is still a specified
   token. Say the word if you want green headings back.
1. **Section spacing — RESOLVED, built to the comp.** The handoff asked for
   ~96–120px separation and "premium whitespace"; the comp measures ~24px
   between panels, 8px between Grocery List and The Youdle Brief, and one
   ~82px break between the hero and the story row. Built to the comp at the
   client's direction: the page went from 2924px to 2630px at 1440 (3.6 → 3.3
   screens). Three tokens at the top of `homepage.css` control it —
   `--yd-section-gap`, `--yd-hero-gap`, `--yd-pair-gap`. Note this is a
   deliberate departure from the handoff's stated numbers.

   For reference if you want to go further: at 1440 only ~160px of the page is
   now inter-section spacing. The other ~2470px is section content (hero 547,
   stories 525, community 445, grocery 342, brief 175, footer 346, header 88),
   so more reduction means trimming panel padding or cutting content, not
   spacing.
2. **Deep Green.** The comp's pixels sample `#04301A`; the handoff specifies
   `#173E2F` and the acceptance checklist says the palette must match the
   specified hex values. Built to `#173E2F`.
3. **Light Sage and Accent Yellow** differ the same way (comp `#F4F7F4` /
   `#FAC912` vs handoff `#EDF5EF` / `#F2C100`). Built to the handoff.
4. **"3 min read"** is in the comp but is not renderable in Blogger's template
   language — there is no word-count, rounding or plain-text-length operator,
   and `data:post.body.length` counts markup. The card meta shows the date
   only. If read time matters, the workable options are a bucketed estimate
   from body length, or moving it to the article pages where the body is in the
   DOM.
5. **Container width.** The comp's content band is ~89% of the artboard
   (≈1283px at 1440); the handoff says ~1200px. Built to 1200px.
6. **Card borders.** The handoff lists a `#E6E3DB` border token; the comp uses
   no borders, only a soft shadow. Story cards are built shadow-only to match
   the comp.
7. **Community timestamps.** The comp's light gray (~`#8A8A8A`) is about 3.5:1
   on white and fails WCAG AA, which the handoff requires. Built with
   `#676767` (5.4:1).
8. **`https://www.youdle.io/grocery`** is the URL the handoff gives for Grocery
   List, and it is used. Note it currently serves the **Sign In** page to
   logged-out visitors and is absent from youdle.io's sitemap — presumably the
   list is behind auth. Worth confirming that is the intended landing
   experience.
9. **No Advertise With Us page exists** (`/advertise`, `/partners`, `/press` all
   404). The footer link is a `mailto:` so it works today; swap it for a real
   page when there is one.
10. **Copyright line.** The comp says "© 2025 Youdle, Inc."; the live site says
    "Copyright © Youdle 2026" and the legal entity is Product Sightings, Inc.
    DBA Youdle. Built as "© 2026 Youdle. All rights reserved." in
    `config.json` — change if legal prefers the full entity name.
12. **Two links in the handoff point at this page.** The handoff routes the
    hero's primary CTA and "View all stories" to Grocery Today
    (`https://news.youdle.io/`) — which, on this site, is the page the reader is
    already on. It was written for youdle.io, where Grocery Today is a separate
    destination. Adapted rather than left circular:
    - **"See What's Happening"** → `#yd-stories`, an in-page jump to the story
      row directly below.
    - **"View all stories"** → `/search`, Blogger's full reverse-chronological
      post list with paging. It is the only real archive this blog has, since
      the redesigned homepage shows three stories and no pager. Note Blogger
      marks search pages `noindex`, so this is a reader path, not an SEO one.

    If you would rather the homepage keep a pager, or show more than three
    stories, that is a different shape and worth deciding now.
13. **Logo.** The comp leaves the header's left third empty. The existing
    `frontend/public/img/youdle-logo-brand.svg` is inlined at 114×34; it is not
    redrawn or restyled. Swap the file if there is a newer master. Per the
    handoff's link map it points at `https://youdle.io/`, not at this blog.
14. **The homepage loses the blog search box and the archive/labels drawer.**
    The stock header carried a search field, and the off-canvas drawer held
    Past Articles and Labels. Neither is in the comp, and the handoff puts
    search out of scope and says not to add one — but this is still existing
    functionality going away. Partly restored: the hamburger menu now has an
    "All stories" link to the full archive. Search and label browsing remain
    reachable from any article page, just not from the homepage. Flagging per
    §10 rather than silently changing the IA.
15. **Story thumbnails use `alt=""`.** The headline is announced immediately
    after and is the link, so a description here would only repeat it. Blogger
    has no per-image alt to draw on. The handoff asks for descriptive alt on
    meaningful images; this is the standard treatment for an editorial
    thumbnail paired with its own headline.
16. **The whole story card is the click target**, via an overlay on the
    headline link. Handoff §10 lists "the whole card vs the headline only" as a
    question for you. Whole-card is the better touch target, but the overlay
    means the dek and date cannot be selected with the mouse. Say if you would
    rather only the headline and image were clickable.
17. **YouTube featured images are not special-cased.** The stock theme swaps in
    `youtubeMaxResDefaultUrl` for YouTube thumbnails. None of the 150 most
    recent posts use one (they are all Blogger- or imgbb-hosted stills), so the
    branch was left out to keep the template expression simple. Add it if
    video-led posts start appearing.

---

## Acceptance checklist (handoff §9)

| Item | Status |
|---|---|
| Matches approved visual direction and section order | Yes — 01 header, 02 hero, 03 stories, 04 community, 05 grocery list, 06 brief, 07 footer |
| Existing logo used, not recreated | Yes — inlined from the repo's SVG |
| Newsreader + Inter implemented | Yes, `display=swap`, with the handoff's fallback stacks |
| Palette matches specified hex; community/list backgrounds distinct | Yes — sage `#EDF5EF` vs cream `#FBF3E5` |
| Yellow accent used sparingly, incl. the grocery-run underline | Yes — `#F2C100` appears once, on the hero stroke |
| All navigation/CTA URLs correct | Yes, all fetched and verified |
| Story cards can receive dynamic article URLs | Yes — live from `data:posts` |
| Community preview neat and card-based, not a collage | Yes — 3 equal cards |
| Desktop, tablet and mobile intentionally responsive | Yes — 1080 / 900 / 640 / 380 breakpoints; mobile type sizes defined, not scaled |
| Newsletter submits with success/error states | Yes — JSONP for inline states, a live region that stays in the accessibility tree, `aria-describedby` tying the field to its message, focus kept on the button while submitting, and a plain POST fallback with JS off |
| Semantic HTML and heading hierarchy | Yes — one `<h1>`, `<h2>` per section, `<article>` per story |
| Title / meta / canonical / Open Graph | Emitted by Blogger from Settings (see above); Twitter Card added by the theme |
| Organization + WebSite structured data valid | Yes, plus an `ItemList` for the three previews |
| No unsupported SearchAction | Correct — none added |
| Entity language explicit enough for AEO/GEO | Yes — the footer definition is crawlable text |
| Images optimized, no major layout shift | WebP available; every image has width/height or a CSS `aspect-ratio` |
| Keyboard / focus / contrast / alt text | Yes. Every text pair measured: the lowest is the muted gray at 5.66:1, well over the 4.5:1 minimum. The focus ring is #0b5cd8 (5.4-5.9:1) on light surfaces and switches to white (11.9:1) inside the green band. Skip link restyled and its target given a visible ring; all controls labelled; 44px targets on touch. |
| No broken links or placeholder `#` URLs | Yes — zero `href="#"` |

---

## Rolling back

The base theme is never modified. To revert, upload
`theme-2263602681587126671.xml` (or your Blogger backup) the same way.

## If Blogger rejects the upload

Blogger reports `Error parsing XML, line N, column M`. `build_theme.py` already
rules out every well-formedness cause, so a failure there means the *base* theme
changed. Re-download it from Blogger over
`theme-2263602681587126671.xml` and rebuild — the build will name whichever
anchor no longer matches.

To re-validate a file by hand:

```bash
python -c "import xml.dom.minidom;xml.dom.minidom.parse(r'theme-youdle-homepage.xml');print('OK')"
```
