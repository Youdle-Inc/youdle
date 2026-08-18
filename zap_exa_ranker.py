# zap_exa_ranker.py
# Exa-based article fetcher for RECALL and SHOPPERS articles
# Replaces RSS feed parsing with Exa AI-powered search

import os
import re
import time
from datetime import datetime, timezone, timedelta
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will rely on system environment variables

from exa_py import Exa

# ============================================================================
# CONFIGURATION
# ============================================================================

# Scoring weights (preserved from RSS script)
KEYWORD_BOOST_WEIGHT = 3.0
FIRST_ENTRY_BOOST_PRIMARY = 10.0
FIRST_ENTRY_BOOST_OTHER = 5.0
LENGTH_SCORE_WEIGHT = 2.0
AGE_SCORE_WEIGHT = 1.0

# Limits
MAX_TOTAL_ITEMS = 300
MAX_RECALL_ITEMS = 50
RECENT_WINDOW_DAYS = 10
PROCESSING_SOFT_LIMIT_SEC = 22

# Exa-specific configuration
def _positive_int_setting(name, default):
    """Read an optional positive integer setting without breaking startup."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


EXA_MAX_RESULTS_PER_QUERY = 15
EXA_CONTENT_MAX_CHARS = _positive_int_setting(
    "EXA_DISCOVERY_CONTENT_MAX_CHARS",
    2000,
)
EXA_GENERATION_CONTENT_MAX_CHARS = _positive_int_setting(
    "EXA_GENERATION_CONTENT_MAX_CHARS",
    6000,
)
EXA_SEARCH_DAYS_BACK = 30

SOURCE_OMISSION_MARKER = "\n\n[... source text omitted ...]\n\n"
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}

# Domains for filtering
RECALL_DOMAINS = ["fda.gov", "fsis.usda.gov"]
EXCLUDE_DOMAINS_FOR_SHOPPERS_SAFETY = ["fda.gov", "fsis.usda.gov", "usda.gov"]

# US-based domains for shoppers content (major US grocery/food news sources)
US_SHOPPERS_DOMAINS = [
    # Major US news sites
    "usatoday.com",
    "washingtonpost.com",
    "nytimes.com",
    "cnn.com",
    "nbcnews.com",
    "cbsnews.com",
    "abcnews.go.com",
    "foxnews.com",
    "npr.org",
    # US food/grocery focused
    "foodnetwork.com",
    "eater.com",
    "chowhound.com",
    "thekitchn.com",
    "seriouseats.com",
    "delish.com",
    "tastingtable.com",
    "allrecipes.com",
    "epicurious.com",
    "bonappetit.com",
    # US retail/business news
    "cnbc.com",
    "bloomberg.com",
    "businessinsider.com",
    "forbes.com",
    "marketwatch.com",
    "retaildive.com",
    "grocerydive.com",
    "supermarketnews.com",
    "progressivegrocer.com",
    # US consumer advocacy / personal finance
    "consumerreports.org",
    "nerdwallet.com",
    # US government/health
    "cdc.gov",
    "nih.gov",
    "health.gov",
]

# Non-US domains to exclude
EXCLUDE_NON_US_DOMAINS = [
    # UK
    "bbc.co.uk",
    "bbc.com",
    "theguardian.com",
    "telegraph.co.uk",
    "dailymail.co.uk",
    "mirror.co.uk",
    "independent.co.uk",
    "tesco.com",
    "sainsburys.co.uk",
    # Canada
    "cbc.ca",
    "globalnews.ca",
    "thestar.com",
    "loblaws.ca",
    # Australia
    "abc.net.au",
    "smh.com.au",
    "news.com.au",
    "9news.com.au",
    "woolworths.com.au",
    "coles.com.au",
    # Europe
    "euronews.com",
    "dw.com",
    "france24.com",
    "reuters.com",  # International
]

# Recall signal keywords for scoring
RECALL_SIGNAL_KEYWORDS = [
    "recall",
    "recalled",
    "contamination",
    "salmonella",
    "listeria",
    "e. coli",
    "e.coli",
    "undeclared",
    "allergen",
    "foreign material",
    "outbreak",
]

# ============================================================================
# SEARCH QUERIES
# ============================================================================

# RECALL queries - targeting FDA and USDA official sources
RECALL_QUERIES = [
    {
        "query": "FDA food recall safety alert",
        "include_domains": ["fda.gov"],
        "category": "RECALL",
    },
    {
        "query": "USDA FSIS food recall alert",
        "include_domains": ["fsis.usda.gov"],
        "category": "RECALL",
    },
    {
        "query": "food recall contamination salmonella listeria e.coli",
        "include_domains": ["fda.gov", "fsis.usda.gov"],
        "category": "RECALL",
    },
]

# SHOPPERS queries - 5 categories of US consumer/grocery content
# Note: Exa only allows either include_domains OR exclude_domains, not both
# We use exclude_domains to filter non-US + US keywords in queries
SHOPPERS_QUERIES = [
    # 1. US Grocery news and retail coverage
    {
        "query": "US grocery store opening American retail pricing changes grocery inflation Walmart Kroger Target Costco",
        "category": "SHOPPERS",
        "subcategory": "grocery_retail",
        "exclude_domains": EXCLUDE_NON_US_DOMAINS,
    },
    {
        "query": "American supermarket news US grocery store brands retailer mergers United States",
        "category": "SHOPPERS",
        "subcategory": "grocery_retail",
        "exclude_domains": EXCLUDE_NON_US_DOMAINS,
    },
    # 2. US grocery prices and consumer impact
    {
        "query": "US grocery prices rising food inflation impact American consumers shrinkflation",
        "category": "SHOPPERS",
        "subcategory": "prices",
        "exclude_domains": EXCLUDE_NON_US_DOMAINS,
    },
    {
        "query": "food ingredient changes US labeling transparency hidden additives consumer health",
        "category": "SHOPPERS",
        "subcategory": "health",
        "exclude_domains": EXCLUDE_NON_US_DOMAINS,
    },
    # 3. US Shopping advice and consumer guidance
    {
        "query": "best value grocery items US shopping comparison American consumer recommendations buying guide",
        "category": "SHOPPERS",
        "subcategory": "shopping_advice",
        "exclude_domains": EXCLUDE_NON_US_DOMAINS,
    },
    {
        "query": "US holiday shopping tips American budget grocery strategies store tips savings",
        "category": "SHOPPERS",
        "subcategory": "shopping_advice",
        "exclude_domains": EXCLUDE_NON_US_DOMAINS,
    },
    # 4. US Food trends and lifestyle content
    {
        "query": "trending foods America viral grocery items US seasonal recipes health food American",
        "category": "SHOPPERS",
        "subcategory": "food_trends",
        "exclude_domains": EXCLUDE_NON_US_DOMAINS,
    },
    {
        "query": "US convenience foods American shopper behavior food lifestyle trends United States",
        "category": "SHOPPERS",
        "subcategory": "food_trends",
        "exclude_domains": EXCLUDE_NON_US_DOMAINS,
    },
    # 5. US General food safety/health news (non-recall)
    {
        "query": "US food safety tips American foodborne illness prevention CDC food handling",
        "category": "SHOPPERS",
        "subcategory": "food_safety_general",
        "exclude_domains": EXCLUDE_DOMAINS_FOR_SHOPPERS_SAFETY + EXCLUDE_NON_US_DOMAINS,
    },
]

# ============================================================================
# UTILITY FUNCTIONS (preserved from RSS script)
# ============================================================================

def html_to_text(s):
    """Convert HTML to plain text."""
    if not s:
        return ""
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_exa_date(date_str):
    """Parse Exa's published_date string to datetime."""
    if not date_str:
        return None
    try:
        # Exa returns dates in ISO format like "2025-12-15T00:00:00.000Z"
        # Handle various ISO formats
        date_str = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(date_str.replace(".000", ""))
    except Exception:
        pass
    # Try other common formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None


def age_score(dt):
    """Calculate recency score (0-100, higher = more recent)."""
    if not dt:
        return 0
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return max(0, 1 - age / (7 * 86400)) * 100


def length_score(text):
    """Score based on content length."""
    ln = len(html_to_text(text))
    if ln < 40:
        return 5
    if ln < 200:
        return 40
    if ln < 600:
        return 80
    if ln < 1200:
        return 65
    return 30


def keyword_boost(title, desc):
    """Boost score for recall-related keywords."""
    t = f"{html_to_text(title)} {html_to_text(desc)}".lower()
    return min(sum(10 for k in RECALL_SIGNAL_KEYWORDS if k in t), 60)


def within_days(pub_iso, days):
    """Check if date is within the specified number of days."""
    if not pub_iso:
        return False
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(pub_iso) <= timedelta(days=days)
    except Exception:
        return False


def get_date_range(days_back):
    """Get start and end dates for Exa search."""
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days_back)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


# ============================================================================
# EXA SEARCH FUNCTIONS
# ============================================================================

def init_exa_client():
    """Initialize Exa client with API key from environment."""
    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        raise ValueError("EXA_API_KEY environment variable is not set")
    return Exa(api_key=api_key)


def canonicalize_article_url(url):
    """Return a stable HTTP(S) URL for content-response matching."""
    if not isinstance(url, str):
        return ""

    candidate = url.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""

    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path or "/",
        urlencode(filtered_query),
        "",
    ))


def truncate_source_text(text, max_chars=EXA_GENERATION_CONTENT_MAX_CHARS):
    """Clean and bound source text while preserving its beginning and ending."""
    if not text or max_chars <= 0:
        return ""

    cleaned = str(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if len(cleaned) <= max_chars:
        return cleaned

    if max_chars <= len(SOURCE_OMISSION_MARKER):
        return cleaned[:max_chars]

    remaining = max_chars - len(SOURCE_OMISSION_MARKER)
    head_chars = int(remaining * 0.8)
    tail_chars = remaining - head_chars
    return (
        cleaned[:head_chars].rstrip()
        + SOURCE_OMISSION_MARKER
        + cleaned[-tail_chars:].lstrip()
    )


def hydrate_article_contents(
    articles,
    exa=None,
    max_chars=EXA_GENERATION_CONTENT_MAX_CHARS,
):
    """Hydrate selected articles with fuller Exa text.

    Discovery excerpts remain untouched in ``description``. Missing or blank
    content falls back to that excerpt so generation can continue.
    """
    hydrated = [dict(article) for article in articles]
    url_by_key = {}
    for article in hydrated:
        original_url = article.get("link", "")
        canonical_url = canonicalize_article_url(original_url)
        if not canonical_url:
            # An invalid source URL must never be interpolated into generated
            # HTML, even though its discovery excerpt can remain available.
            article["link"] = ""
        elif canonical_url not in url_by_key:
            url_by_key[canonical_url] = original_url.strip()

    if not url_by_key:
        for article in hydrated:
            article["content"] = (
                article.get("content") or article.get("description") or ""
            )
        return hydrated

    client = exa or init_exa_client()
    try:
        response = client.get_contents(
            list(url_by_key.values()),
            text={"max_characters": max_chars},
        )
    except Exception:
        for article in hydrated:
            article["content"] = truncate_source_text(
                article.get("content") or article.get("description") or "",
                max_chars,
            )
        return hydrated

    fetched_by_key = {}
    for result in getattr(response, "results", []) or []:
        canonical_url = canonicalize_article_url(getattr(result, "url", ""))
        if canonical_url:
            fetched_by_key[canonical_url] = result

    for article in hydrated:
        canonical_url = canonicalize_article_url(article.get("link", ""))
        fetched = fetched_by_key.get(canonical_url)
        fetched_text = getattr(fetched, "text", "") if fetched else ""
        bounded_fetched_text = truncate_source_text(fetched_text, max_chars)
        article["content"] = bounded_fetched_text or truncate_source_text(
            article.get("content") or article.get("description") or "",
            max_chars,
        )
        if not article.get("title") and fetched:
            article["title"] = html_to_text(getattr(fetched, "title", "") or "")

    return hydrated


def execute_search(exa, query_config, start_date, end_date):
    """Execute a single Exa search query and return results."""
    query = query_config["query"]
    category = query_config["category"]
    
    search_params = {
        "query": query,
        "type": "auto",
        "num_results": EXA_MAX_RESULTS_PER_QUERY,
        "start_published_date": start_date,
        "end_published_date": end_date,
        "text": {"max_characters": EXA_CONTENT_MAX_CHARS},
    }
    
    # Add domain filters if specified
    if "include_domains" in query_config:
        search_params["include_domains"] = query_config["include_domains"]
    
    if "exclude_domains" in query_config:
        search_params["exclude_domains"] = query_config["exclude_domains"]
    
    try:
        results = exa.search_and_contents(**search_params)
        return results.results, category, query_config.get("subcategory")
    except Exception as e:
        print(f"Error searching for '{query}': {e}")
        return [], category, query_config.get("subcategory")


def process_exa_result(result, category, query_index, result_index):
    """Convert an Exa result to our standard item format."""
    title = result.title or ""
    url = result.url or ""
    text = getattr(result, "text", "") or ""
    published_date = getattr(result, "published_date", None)
    
    # Parse the date
    pub_dt = parse_exa_date(published_date)
    
    # Calculate score using existing scoring logic
    score = (
        KEYWORD_BOOST_WEIGHT * keyword_boost(title, text)
        + (FIRST_ENTRY_BOOST_PRIMARY if result_index == 0 else FIRST_ENTRY_BOOST_OTHER)
        + LENGTH_SCORE_WEIGHT * length_score(text)
        + AGE_SCORE_WEIGHT * age_score(pub_dt)
    )
    
    # Add category boost for RECALL items
    if category == "RECALL":
        score += 50
    
    return {
        "feedIndex": query_index,
        "category": category,
        "title": html_to_text(title),
        "description": text[:EXA_CONTENT_MAX_CHARS] if text else "",
        "link": url,
        "pubDate": pub_dt.isoformat() if pub_dt else None,
        "score": score,
    }


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main(input_data):
    """
    Main entry point - fetches articles using Exa API.
    
    Args:
        input_data: dict with optional keys:
            - batch_size: int (default 30)
            - batch_index: int (default 0)
            - recent_window_days: int (default 14)
            - search_days_back: int (default 30)
    
    Returns:
        dict with keys:
            - items: list of ranked items for the current batch
            - recall_items: list of recent recall items
            - processed_count: number of items in current batch
            - total_ranked_count: total number of ranked items
    """
    batch_size = int(input_data.get("batch_size", 30))
    batch_index = int(input_data.get("batch_index", 0))
    recent_days = int(input_data.get("recent_window_days", RECENT_WINDOW_DAYS))
    search_days = int(input_data.get("search_days_back", EXA_SEARCH_DAYS_BACK))
    
    items = []
    start_ts = time.time()
    
    # Initialize Exa client
    try:
        exa = init_exa_client()
    except ValueError as e:
        return {
            "items": [],
            "recall_items": [],
            "processed_count": 0,
            "total_ranked_count": 0,
            "error": str(e),
        }
    
    # Get date range for searches
    start_date, end_date = get_date_range(search_days)
    
    # Combine all queries
    all_queries = RECALL_QUERIES + SHOPPERS_QUERIES
    
    # Execute searches
    for query_index, query_config in enumerate(all_queries):
        # Check time limit
        if time.time() - start_ts > PROCESSING_SOFT_LIMIT_SEC:
            break
        
        # Execute search
        results, category, subcategory = execute_search(
            exa, query_config, start_date, end_date
        )
        
        # Process results
        for result_index, result in enumerate(results):
            item = process_exa_result(result, category, query_index, result_index)
            items.append(item)
            
            if len(items) >= MAX_TOTAL_ITEMS:
                break
        
        if len(items) >= MAX_TOTAL_ITEMS:
            break
    
    # Deduplicate by URL
    seen_urls = set()
    unique_items = []
    for item in items:
        if item["link"] and item["link"] not in seen_urls:
            seen_urls.add(item["link"])
            unique_items.append(item)
    items = unique_items
    
    # =========================================================================
    # SEPARATE BY CATEGORY - Rank shoppers and recall separately
    # =========================================================================
    shoppers_items = [item for item in items if item["category"] != "RECALL"]
    recall_only_items = [item for item in items if item["category"] == "RECALL"]
    
    # Rank each category separately by score (descending)
    shoppers_items.sort(key=lambda x: -x["score"])
    recall_only_items.sort(key=lambda x: -x["score"])
    
    # =========================================================================
    # BALANCED SELECTION - Ensure both categories are represented
    # =========================================================================
    # Target: ~80% shoppers, ~20% recall (but ensure at least 1 recall if available)
    recall_count = min(len(recall_only_items), max(1, batch_size // 5))
    shoppers_count = min(len(shoppers_items), batch_size - recall_count)
    
    # Adjust if we don't have enough shoppers
    if shoppers_count < (batch_size - recall_count):
        # Fill remaining with more recall items
        recall_count = min(len(recall_only_items), batch_size - shoppers_count)
    
    # Merge top results: shoppers first, then recall
    # Explicitly limit to batch_size to prevent over-selection
    balanced_items = (shoppers_items[:shoppers_count] + recall_only_items[:recall_count])[:batch_size]

    # =========================================================================
    # BATCH SLICE - Get the requested batch
    # =========================================================================
    start = batch_index * batch_size
    end = start + batch_size

    # For batch_index 0, use balanced_items directly
    # For later batches, fall back to remaining items from full sorted list
    if batch_index == 0:
        batch_items = balanced_items[:batch_size]  # Extra safety limit
    else:
        # Merge all items for pagination of later batches
        all_sorted = shoppers_items + recall_only_items
        batch_items = all_sorted[start:end]
    
    # =========================================================================
    # EXTRACT RECALL ITEMS - Recent recalls for dedicated recall section
    # =========================================================================
    recall_items = []
    seen_recall = set()
    for item in recall_only_items:
        if within_days(item["pubDate"], recent_days):
            key = (item["link"], item["title"].lower())
            if key not in seen_recall:
                seen_recall.add(key)
                recall_items.append(item)
        if len(recall_items) >= MAX_RECALL_ITEMS:
            break
    
    return {
        "items": batch_items,
        "recall_items": recall_items,
        "processed_count": len(batch_items),
        "total_ranked_count": len(items),
        "shoppers_count": len(shoppers_items),
        "recall_count": len(recall_only_items),
    }


# For Zapier code step compatibility
if __name__ != "__main__":
    # When run as a Zapier code step, input_data is provided
    try:
        result = main(input_data)
    except NameError:
        # Not running in Zapier context
        pass


# For local testing
if __name__ == "__main__":
    import json
    
    # Test with sample input
    test_input = {
        "batch_size": 10,
        "batch_index": 0,
        "recent_window_days": 14,
    }
    
    result = main(test_input)
    print(json.dumps(result, indent=2, default=str))

