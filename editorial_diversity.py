"""Editorial topic balancing for Grocery Brief.

No new Exa requests or model calls. Classify already-discovered items and
select a diverse set without repeating essentially the same pricing story.
"""

import re
from collections import Counter


TOPIC_PRIORITY = (
    "meals", "discovery", "health", "life_events",
    "convenience", "store_experience", "value",
)
TOPIC_TERMS = {
    "life_events": (
        "halloween", "thanksgiving", "christmas", "hanukkah", "kwanzaa",
        "easter", "holiday", "storm", "hurricane", "emergency", "back-to-school",
        "back to school", "graduation", "new year",
    ),
    "health": (
        "nutrition", "healthy", "health", "fiber", "protein", "allergen",
        "ingredients", "ingredient", "gluten", "sugar", "sodium", "dietary",
        "additives", "ultra-processed", "labeling", "label changes",
    ),
    "convenience": (
        "ready-made", "ready to eat", "ready-to-eat", "prepared meal",
        "meal kit", "delivery", "pickup", "curbside", "quick", "convenience",
        "time-saving", "time saving", "ready to heat",
    ),
    "meals": (
        "recipe", "recipes", "dinner", "breakfast", "lunch", "cooking",
        "cook at home", "comfort food", "meal planning", "weeknight",
        "family meals", "leftovers", "soup", "casserole",
    ),
    "discovery": (
        "new flavor", "flavors", "flavor", "new product", "cookie", "cookies",
        "chips", "snack", "snacks", "pastry", "candy", "taste", "launch",
        "launches", "new arrival", "viral", "trending", "trend",
        "limited edition", "limited-edition", "new foods",
    ),
    "store_experience": (
        "self-checkout", "self checkout", "digital price tags",
        "electronic shelf labels", "digital shelf labels", "smart carts",
        "checkout", "grocery stores", "supermarket", "store opening",
        "stores", "store closures", "retailer", "shopping experience",
    ),
    "value": (
        "grocery prices", "price", "prices", "inflation", "grocery bill",
        "grocery bills", "cost", "costs", "expensive", "budget", "coupons",
        "discounts", "savings", "save money", "tariffs", "shrinkflation",
        "affordability", "clearance", "deals",
    ),
}
SUBCATEGORY_FALLBACK = {
    "prices": "value", "shopping_advice": "value", "health": "health",
    "food_trends": "discovery", "grocery_retail": "store_experience",
    "grocery_news": "store_experience", "seasonal": "life_events",
    "convenience": "convenience",
}
CHECK_ORDER = (
    "life_events", "health", "convenience", "meals",
    "discovery", "store_experience", "value",
)


def _contains(text, expressions):
    subject = str(text or "").lower()
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(expr) + r"(?![a-z0-9])", subject)
        for expr in expressions
    )


def classify_shopper_story(article):
    """Use the actual subject, never infer interest from publication rank."""
    existing = article.get("editorial_topic")
    if existing in TOPIC_PRIORITY:
        return existing
    title = article.get("title") or ""
    # These themes can otherwise be misclassified as prices or recipes.
    if _contains(title, ("digital price tag", "electronic shelf label",
                         "digital shelf label", "self-checkout", "smart cart")):
        return "store_experience"
    if _contains(title, ("ready-made", "ready to eat", "ready-to-eat",
                         "prepared meal", "meal kit", "delivery")):
        return "convenience"
    for topic in CHECK_ORDER:
        if _contains(title, TOPIC_TERMS[topic]):
            return topic
    excerpt = str(article.get("description") or "")[:400]
    for topic in CHECK_ORDER:
        if _contains(excerpt, TOPIC_TERMS[topic]):
            return topic
    return SUBCATEGORY_FALLBACK.get(
        article.get("source_subcategory"), "store_experience"
    )


def select_diverse_shopper_stories(articles, limit):
    """Preserve rank within topics and restrict cost-heavy repetition.

    If too few non-cost candidates exist, return fewer stories rather than
    padding the edition with near-identical headlines about prices.
    """
    limit = max(0, int(limit))
    if not limit:
        return []
    ranked = list(articles or [])
    topics = [classify_shopper_story(a) for a in ranked]
    chosen = set()
    counts = Counter()
    # Up to one price story for a six-story slate; up to two for ten.
    max_value = max(1, limit // 5)

    for topic in TOPIC_PRIORITY:
        if len(chosen) >= limit:
            break
        ix = next((i for i, cat in enumerate(topics)
                   if cat == topic and i not in chosen), None)
        if ix is not None:
            chosen.add(ix)
            counts[topic] += 1

    while len(chosen) < limit:
        options = [
            i for i, cat in enumerate(topics)
            if i not in chosen
            and (cat != "value" or counts["value"] < max_value)
        ]
        if not options:
            break
        ix = min(options, key=lambda i: (counts[topics[i]], i))
        chosen.add(ix)
        counts[topics[ix]] += 1

    return [
        {**ranked[i], "editorial_topic": topics[i]}
        for i in sorted(chosen)
    ]
