#!/usr/bin/env python3
"""Build cut-down themes to find what Blogger's restore rejects.

Blogger answers a bad theme with "Could not restore theme" and no detail, so
the only way to identify the offending construct is to upload progressively
smaller variants. These are ordered by suspicion: each one removes the
constructs the stock theme never uses, most exotic first.

    python blogger/homepage/make_bisect.py

Writes theme-test-*.xml at the repo root. Upload them in order and stop at the
first one that restores; the step that fixed it names the culprit.
"""

import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import build_theme  # noqa: E402

FULL = REPO / "theme-youdle-homepage.xml"
BASE = REPO / "theme-2263602681587126671.xml"


def cut(theme: str, start: str, end: str, what: str) -> str:
    """Remove one span, anchored on exact strings, or fail loudly."""
    i = theme.find(start)
    if i == -1:
        raise SystemExit(f"anchor not found for {what}: {start[:60]}")
    j = theme.find(end, i)
    if j == -1:
        raise SystemExit(f"closing anchor not found for {what}: {end[:60]}")
    return theme[:i] + theme[j + len(end):]


def write(path: Path, theme: str, label: str) -> None:
    ET.fromstring(theme)  # namespace-aware parse; raises if broken
    build_theme.validate(theme)
    path.write_text(theme, encoding="utf-8", newline="\n")
    print(f"  {path.name:<34} {len(theme):>7,} bytes   {label}")


def main() -> None:
    if not FULL.exists():
        raise SystemExit("run build_theme.py first")
    full = FULL.read_text(encoding="utf-8")

    print("\nUpload these in order. Stop at the first one that restores.\n")

    # 0. Control: the untouched theme downloaded from Blogger. If this fails,
    #    the problem is not in anything we generate.
    shutil.copyfile(BASE, REPO / "theme-test-0-untouched-base.xml")
    print(f"  {'theme-test-0-untouched-base.xml':<34} "
          f"{BASE.stat().st_size:>7,} bytes   the file Blogger itself exported")

    # 1. Drop the pager. data:olderPageUrl and data:newerPageUrl are read
    #    inside our own includable; the stock theme only reads them inside the
    #    dedicated nextPageLink includable.
    step1 = cut(full,
                "<nav aria-label='More articles' class='yd-pager'>",
                "</nav>", "pager")
    write(REPO / "theme-test-1-no-pager.xml", step1,
          "minus the pager (data:olderPageUrl / data:newerPageUrl)")

    # 2. Also drop the ItemList JSON-LD in the list, which is the only place
    #    b:eval appears inside a script element.
    step2 = cut(step1,
                "<b:comment>GEO: the index as an ItemList.",
                "</script>", "ItemList JSON-LD")
    write(REPO / "theme-test-2-no-itemlist.xml", step2,
          "also minus the ItemList JSON-LD (b:eval inside a script)")

    # 3. Also drop the per-post snippet, date and resized image: snippet(),
    #    format(), data:post.date.iso8601 and resizeImage() with srcset are all
    #    absent from the stock theme.
    step3 = step2
    step3 = re.sub(
        r"\s*<p class='yd-item__dek'><b:eval expr='snippet\([^']*'/></p>",
        "", step3)
    step3 = re.sub(
        r"<time expr:datetime='data:post\.date\.iso8601'>"
        r"<b:eval expr='format\([^']*'/></time>",
        "<span>Published</span>", step3)
    step3 = re.sub(
        r"<img alt='' expr:loading='[^']*' expr:src='[^']*' expr:srcset='[^']*'"
        r" height='144' sizes='[^']*' width='192'/>",
        "<img alt='' expr:src='data:post.featuredImage' height='144' "
        "loading='lazy' width='192'/>", step3)
    write(REPO / "theme-test-3-plain-rows.xml", step3,
          "also minus snippet(), format(), .iso8601 and resizeImage()")

    print("\n  theme-youdle-homepage.xml          the full build, for reference\n")
    print("  If 0 fails, the upload path itself is broken, not the theme.")
    print("  Otherwise the first file that restores names the culprit.\n")


if __name__ == "__main__":
    main()
