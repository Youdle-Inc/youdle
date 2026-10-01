# news.youdle.io — the article index

The homepage of **news.youdle.io**: every published article, newest first, with
category chips across the top and the newsletter signup at the end.

It replaces an earlier build of this directory, which implemented a *youdle.io
homepage* handoff — hero, community preview, grocery-list promo — against the
wrong site. news.youdle.io is a blog; its homepage is a list of what has been
published. That page's header, drawer, footer columns and promo sections are
gone; its newsletter block, its build pipeline, its preview server and its test
suite are kept.

Only the homepage view changes. Post, archive, label, search and page views
render exactly as they do today — every addition is gated on
`data:view.isHomepage`, and the homepage stylesheet is not even loaded on other
views.

---

## Quick start

```bash
# See it, with live articles from the real news.youdle.io feed
python blogger/homepage/preview.py                 # http://localhost:5173

# Offline, with the fixture in mock_posts.json
python blogger/homepage/preview.py --source mock

# Build the theme file to upload
python blogger/homepage/build_theme.py             # -> theme-youdle-homepage.xml

# Check it still holds together
python blogger/homepage/test_homepage.py           # 100 checks
```

Then in Blogger: **Theme → ⋮ → Restore → Upload** `theme-youdle-homepage.xml`.
(Take a backup first: **Theme → ⋮ → Backup**.)

No dependencies beyond the Python standard library.

---

## What the page is

```
masthead          Youdle wordmark, "Youdle News", one line of description
chips             All · Recalls · Grocery news · For grocers · Emergency prep · Prices & deals
list              every post Blogger put on this page, newest first:
                    thumbnail · category · date · headline · snippet
pager             Newer / Older articles, Blogger's own index paging
newsletter        The Youdle Brief, same Mailchimp list as before
footer            one line: copyright, Youdle, Privacy, Terms
```

Three rules the list follows, each of which has a test:

- **Nothing is dropped.** Every post in `data:posts` is listed. A post with no
  label, or with a label the chips do not name, still appears — it simply has
  no category shown. Six posts on the live blog have no label at all.
- **Newest first**, by `data:post.date`, which is Blogger's own index order.
- **A post without a featured image** gets a styled placeholder tile, not a
  broken image. The index hosts no photography of its own; every image on it is
  a post's own.

---

## Label hygiene

The chips point at raw Blogger labels, because that is what `/search/label/…`
URLs match. They are **case sensitive and accept one label at a time**, which
the live blog's labelling does not respect:

| Label | Posts | Chip |
|---|---|---|
| `SHOPPERS` | 109 | Grocery news |
| `RECALL` | 9 | Recalls |
| `GROCERS` | 9 | For grocers |
| `recall` | 7 | — **not reachable** |
| `EMERGENCY` | 7 | Emergency prep |
| `deals` | 2 | Prices & deals |
| `holidays`, `announcement` | 1 each | — |
| *(none)* | 6 | — |

`RECALL` and `recall` are two different labels to Blogger, so the Recalls chip
reaches only the nine. **The fix is in Blogger, not here**: edit those seven
posts and change the label to `RECALL`. Until then they still appear in the
main list, which is chronological and label-blind.

`build_theme.py` prints the labels the chips target on every build, so a typo
in `config.json` is visible rather than producing a silently empty label page.

---

## How the local preview works

`preview.py` is not a mockup — it renders the page **out of the generated
Blogger theme**. On every request it:

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

Articles come from `https://news.youdle.io/feeds/posts/default` by default and
fall back to `mock_posts.json` if the feed is unreachable. The preview models
the **newest** index page: `data:newerPageUrl` is empty and `data:olderPageUrl`
is set, so the pager renders as it does on the page a reader lands on.

Useful flags:

| Flag | Effect |
|---|---|
| `--source mock` | offline fixture instead of the live feed |
| `--images none` | every post without an image, to see the placeholder tiles |
| `--snapshot out.html` | write one rendered page and exit |
| `--port 5173` | change the port |

---

## Tests

`python blogger/homepage/test_homepage.py` runs three tiers (100 checks).

**Tooling** (the build itself): the template engine pairs nested `{{#if}}`
blocks correctly and rejects an unknown key rather than silently taking the
else branch; no source file contains a control byte (a literal `0x08` inside a
regex is indistinguishable from `\b` in any editor and silently disables the
guard around it — that exact bug happened here, twice, and this check catches
it); and the XML validator accepts what Blogger accepts (a `>` inside an
attribute, an `&` inside a comment, numeric entities, `&&` inside CDATA) while
still rejecting what it rejects (unclosed void elements, named entities, bare
ampersands, `--` inside a comment).

**Static** (no browser, no network): the theme parses as strict XML and is
entity-clean; the stock post chrome and the non-homepage Blog markup are
untouched; exactly one `<h1>`; no `#` links; **every post in the fixture is
listed** (the page's whole purpose); the list is an `<ol>`; every chip targets a
label that exists in `config.json`; every string of page copy is present; every
analytics event is wired; every image has alt text, intrinsic dimensions and
lazy-loading below the fold; all JSON-LD parses and contains Organization +
WebSite + ItemList with no SearchAction; and a post with no image renders a
placeholder rather than `src=""`.

It also asserts that **no rule which colours an anchor is left unscoped**.
`.yd-home a { color: inherit }` has specificity (0,1,1) and silently outranks a
bare `.yd-chip--active` (0,1,0) — which rendered the active chip as dark text
on a dark pill. Every such rule carries a `.yd-home ` prefix, and the test fails
if one loses it.

**Browser** (headless Chrome or Edge, skipped with a notice if neither is
installed): rows stack in document order and are listed newest first by their
`datetime` attributes; every chip is a real link; the active chip's label
contrasts with its fill; the older-articles link is present and right-aligned;
an article click reports its position; the newsletter field is programmatically
labelled, rejects an invalid address without a network call, sets and clears
`aria-invalid`, and announces through a polite live region; the stock theme's
chrome is computed-hidden and its width constraints are actually flattened; the
primary button keeps its fill; the masthead title stays in the display face and
larger than the headlines below it; the "Back to Youdle" chrome many post
bodies open with is stripped from the snippets; and there is no horizontal
overflow.

**Known gap:** the browser tier runs at one viewport (1400×900). Narrow-width
regressions are not covered. Headless Chrome on Windows will not open a window
below roughly 500px, so a "390px" screenshot is a crop of a 485px render, not a
phone-width layout — check narrow layouts by measuring `scrollWidth` against
`clientWidth` in the page rather than by eye.

---

## Files

```
blogger/homepage/
  src/
    homepage.xml      markup: head, masthead, chips + list + pager + newsletter, footer, script
    homepage.css      all styling (theme overrides, tokens, components, responsive)
    homepage.js       analytics, snippet chrome stripping, newsletter submit
    config.json       URLs, copy, category chips, Mailchimp endpoint
  assets/img/         starter images from the earlier build; the index uses none
  build_theme.py      splices src/ into the live theme + validates the XML
  preview.py          local server
  bloggerlite.py      the small Blogger template evaluator preview.py runs on
  test_homepage.py    the test suite
  upload_assets.py    uploads images to Supabase and records their URLs
  mock_posts.json     offline article fixture
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
| 2 | `<body>` | adds the `yd-home` class on the homepage, so the masthead (outside `<main>`) and the list (inside it) share one CSS scope |
| 3 | after `skipNavigation` | the masthead — a direct child of `<body>`, which keeps it out of `<main>` and out of a `b:section` (those may only contain `b:widget` children) |
| 4 | `Blog1`'s `main` includable | on the homepage, calls a new `youdleHomepage` includable holding the chips, the list, the pager and the newsletter; otherwise runs the stock markup unchanged |
| 5 | after `.page` | the footer, before the off-canvas drawer |
| 6 | before `</body>` | `homepage.js`, wrapped in `//<![CDATA[` |
| 7 | `main-heading` | the stock screen-reader "Posts" `<h2>` is skipped on the homepage, which has its own headings |
| 8 | `Header1` | the stock Header widget emits `<h1>{blog title}</h1>`. CSS hid it, but crawlers still read it and the page needs exactly one H1 — so the widget is skipped on the homepage, the same way the theme already skips `FeaturedPost1` |
| 9 | third-party scripts | masonry, imagesLoaded and clipboard.js drive the stock feed and post views only, so they are skipped on the homepage |

The list has to live inside `Blog1` because that is the only scope where
`data:posts`, `data:olderPageUrl` and `data:newerPageUrl` exist. Adding a custom
includable to the locked stock `Blog` widget is the same pattern the theme
already uses for `youdleNewsletterSignup`.

`build_theme.py` validates the output before writing: strict XML parse, no bare
`&`, no named entities (Blogger's doctype declares none — `&nbsp;` is a parse
error), every void element self-closed, no `--` inside an XML comment. That
catches every "Error parsing XML" Blogger would report at upload. It then checks
that every section the page cannot render without is present in the output.

---

## Configuration

Everything editable lives in `src/config.json`:

- **`site`** — the masthead title and tagline, the newsletter name, the
  copyright line.
- **`urls`** — where the wordmark, Privacy and Terms point.
- **`categories`** — the chips. `label` is what a reader sees; `blogger_label`
  is the raw label the chip's URL matches. Add, remove or reorder freely; the
  tests check each one against the page.
- **`newsletter`** — the Mailchimp endpoint and honeypot field name, carried
  over verbatim from the theme's `youdleNewsletterSignup` includable so
  existing subscribers are unaffected.
- **`seo`** — Twitter handle, logo URL and the `sameAs` profile list for
  JSON-LD. Blogger emits `<title>`, meta description and Open Graph tags from
  Settings, so those are not duplicated here.

Run `build_theme.py` after any edit.

---

## Rolling back

Blogger keeps no theme history, so the backup you took before uploading is the
only way back. `theme-2263602681587126671.xml` at the repo root is the untouched
base: upload it to return the blog to its stock appearance, including its stock
homepage.
