"""Cheap, deterministic Grocery Brief headline checks and weekly variety cues.

The factual click-promise/lead payoff is also reviewed by the existing LLM
reflection step; keyword checks alone cannot establish semantic truth.
"""
from __future__ import annotations

import html
import re
from collections.abc import Sequence

HEADLINE_SHAPES: tuple[str, ...] = (
    "Lead with a common grocery item and a verified change; hold back the reason.",
    "Lead with an unexpected, sourced discovery about an everyday choice.",
    "Use a verified contrast between two prices, options, or outcomes.",
    "Frame one specific why-or-what question the first paragraph can answer.",
    "Lead with a practical check a shopper can make before their next trip.",
    "Show a confirmed change and one relevant implication for the cart or pantry.",
)

# These are editorial rotation cues, NOT templates that justify adding facts.
def pattern_for_shopper(index: int) -> str:
    return HEADLINE_SHAPES[index % len(HEADLINE_SHAPES)]


def extract_headline(article_html: str) -> str:
    """The generated H2 is the actual reader-facing article title."""
    match = re.search(r"<h2\b[^>]*>(.*?)</h2\s*>", article_html or "", re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", match.group(1)))).strip()


_US_STATES = (
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming",
)
_PLACES = _US_STATES + (
    "Memphis", "Nashville", "Chicago", "Houston", "Dallas", "Austin",
    "Boston", "Atlanta", "Seattle", "Denver", "Phoenix", "Philadelphia",
    "Los Angeles", "San Francisco", "San Diego", "Miami", "Detroit",
    "Minneapolis", "Portland", "St. Louis", "New Orleans", "Baltimore",
    "Las Vegas", "United States", "U.S.", "USA", "East Coast",
    "West Coast", "Midwest", "Northeast", "Northwest", "Southeast",
    "Southwest", "the South", "the North",
)
_STORE_NAMES = (
    "Walmart", "Kroger", "Target", "Costco", "Aldi", "Publix",
    "Whole Foods", "Trader Joe's", "Safeway", "Albertsons", "Giant Eagle",
    "Sprouts", "Wegmans", "Sam's Club", "Dollar General",
)
_BAIT = (
    (r"you[’']?\s+won[’']?t\s+believe", "Banned: you won't believe"),
    (r"\bshocking\b", "Banned: shocking"),
    (r"\bthis one trick\b", "Banned: this one trick"),
    (r"\bdoctors hate\b", "Banned: doctors hate"),
    (r"\bwalks? out\b", "Ambiguous dramatic bait: walks out"),
    (r"\bslams?\b", "Ambiguous dramatic bait: slams"),
    (r"\bfired up\b", "Ambiguous dramatic bait: fired up"),
    (r"\bshuts? down\b", "Ambiguous dramatic bait: shuts down"),
    (r"\bsays? goodbye\b", "Ambiguous dramatic bait: says goodbye"),
)
# Common words are not proper nouns. Catch repeated Title Case while allowing
# legitimate proper names and new sentences after a period.
_COMMON_WORDS = frozenset((
    "the", "a", "an", "are", "is", "was", "were", "of", "for", "to",
    "with", "and", "or", "but", "in", "on", "at", "by", "from",
    "your", "you", "this", "that", "these", "those", "what",
    "which", "why", "when", "where", "how", "most", "more",
    "into", "about", "after", "before", "again", "here",
))


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])", text, re.I) is not None


def validate_headline(
    headline: str,
    *,
    source_title: str = "",
) -> list[str]:
    """Return concrete formatting issues; semantic accuracy still needs review.

    Store names are allowed only where the source is specifically about the
    store. This lightweight source-title check errs on the side of review;
    an editor can confirm the actual subject of a store article.
    """
    heading = (headline or "").strip()
    if not heading:
        return ["Missing generated article headline"]

    issues: list[str] = []
    words = re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*", heading)
    if len(words) >= 14:
        issues.append(f"Headline has {len(words)} words; maximum is 13")
    if "—" in heading or "–" in heading:
        issues.append("Headline uses an em or en dash; use periods, commas, or a colon")
    if "!" in heading:
        issues.append("Headline uses an exclamation point")
    if re.search(r"\b[A-Z]{2,}\b", heading):
        issues.append("Headline uses an all-caps word")
    first_letter = re.search(r"[A-Za-z]", heading)
    if first_letter and not first_letter.group().isupper():
        issues.append("Headline must start in sentence case")

    for match in re.finditer(r"\b[A-Za-z][A-Za-z'’]*\b", heading):
        token = match.group()
        if token.lower() in _COMMON_WORDS and token.istitle():
            preceding = heading[:match.start()].rstrip()
            if preceding and preceding[-1] not in ".?!":
                issues.append(f"Headline uses title case on a common word: {token}")
                break

    places = [name for name in _PLACES if _contains_phrase(heading, name)]
    if places:
        issues.append("Headline has a geographic reference: " + ", ".join(places[:3]))

    for pattern, problem in _BAIT:
        if re.search(pattern, heading, re.I):
            issues.append(problem)

    for store in _STORE_NAMES:
        if _contains_phrase(heading, store) and source_title and not _contains_phrase(source_title, store):
            issues.append(f"Store name {store} not supported as the story's main company")
    return issues
