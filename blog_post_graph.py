# blog_post_graph.py
# LangGraph StateGraph for blog post generation workflow orchestration

import os
import sys
import hashlib

# Allow importing blogger_client from api/ directory
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api'))
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, TypedDict, Annotated
import operator

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from langgraph.graph import StateGraph, START, END

# Import existing components
from zap_exa_ranker import (
    canonicalize_article_url,
    hydrate_article_contents,
    main as search_articles_exa,
    truncate_source_text,
)
from langchain_blog_agent import BlogPostGenerator
from image_generator import get_image_generator
from supabase_storage import get_supabase_client, get_supabase_storage
from example_store import ExampleStore
from reflection_agent import ReflectionAgent
from prompt_refiner import PromptRefiner
from learning_memory import LearningMemory
from html_safety import find_unsafe_html_issues
from blog_post_html import ensure_news_blog_back_link, ensure_newsletter_signup_block
from imgbb_upload import upload_image_to_imgbb, DEFAULT_RECALL_IMAGE_URL


# ============================================================================
# STATE DEFINITION
# ============================================================================

def upsert_generated_posts(
    existing: List[Dict[str, Any]],
    incoming: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge graph results while replacing retries with the same post ID."""
    merged = list(existing or [])
    positions = {
        post.get("post_id"): index
        for index, post in enumerate(merged)
        if post.get("post_id")
    }

    for post in incoming or []:
        post_id = post.get("post_id")
        if post_id and post_id in positions:
            merged[positions[post_id]] = post
        else:
            if post_id:
                positions[post_id] = len(merged)
            merged.append(post)

    return merged


class BlogPostState(TypedDict):
    """
    State schema for the blog post generation workflow.
    
    Annotated fields with operator.add will accumulate values across nodes.
    """
    # Input parameters
    batch_size: int
    search_days_back: int
    model: str
    use_placeholder_images: bool
    job_id: Optional[str]
    
    # Search results
    search_results: Dict[str, Any]
    
    # Selected articles
    articles: List[Dict[str, Any]]
    shoppers_articles: List[Dict[str, Any]]
    recall_articles: List[Dict[str, Any]]
    
    # Learning context
    learning_context: Dict[str, Any]
    shoppers_context: Dict[str, Any]
    recall_context: Dict[str, Any]
    
    # Current generated posts; a retry replaces the prior result by post ID.
    generated_posts: Annotated[List[Dict[str, Any]], upsert_generated_posts]
    
    # Reflection results
    reflection_results: List[Dict[str, Any]]
    posts_needing_regeneration: List[Dict[str, Any]]
    regeneration_count: int
    max_regenerations: int
    
    # Image generation results
    images: List[Dict[str, Any]]
    
    # Upload results
    uploaded_urls: List[Dict[str, Any]]
    
    # Proofread corrections (post_id → corrected HTML)
    proofread_corrections: Dict[str, str]

    # Final assembled posts
    final_posts: List[Dict[str, Any]]
    
    # Saved file paths
    saved_files: List[str]
    saved_post_ids: List[Optional[str]]
    db_inserted: int
    persistence_errors: List[str]
    
    # Processing cache (for deduplication)
    processed_urls: Dict[str, str]
    
    # Errors and logging
    errors: Annotated[List[str], operator.add]
    logs: Annotated[List[str], operator.add]
    
    # Workflow metadata
    start_time: str
    end_time: str


# ============================================================================
# CONFIGURATION
# ============================================================================

BLOG_POSTS_DIR = os.getenv(
    "BLOG_POSTS_DIR",
    "/tmp/blog_posts" if os.getenv("VERCEL") else "blog_posts",
)
MAX_REGENERATIONS = 2
MAX_WORKERS = 4
MAX_RECALL_ROUNDUP_SOURCES = 5
RECALL_CONTEXT_MAX_CHARS = 18000


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_url_hash(url: str) -> str:
    """Generate a hash for a URL."""
    stable_url = canonicalize_article_url(url) or str(url).strip()
    return hashlib.md5(stable_url.encode()).hexdigest()[:12]


def build_recall_source_context(
    articles: List[Dict[str, Any]],
    max_chars: int = RECALL_CONTEXT_MAX_CHARS,
) -> str:
    """Build bounded, balanced context for a multi-source recall roundup."""
    if not articles or max_chars <= 0:
        return ""

    separator = "\n\n---\n\n"
    wrappers = []
    for index, article in enumerate(articles, 1):
        wrappers.append((
            f"RECALL {index}: {article.get('title', 'Unknown')}\n",
            f"\nSource: {article.get('link', '')}",
        ))

    wrapper_chars = sum(len(prefix) + len(suffix) for prefix, suffix in wrappers)
    separator_chars = len(separator) * max(0, len(articles) - 1)
    available_content_chars = max(0, max_chars - wrapper_chars - separator_chars)
    per_source_chars = available_content_chars // len(articles)

    parts = []
    for article, (prefix, suffix) in zip(articles, wrappers):
        source_text = article.get("content") or article.get("description") or ""
        bounded_text = truncate_source_text(source_text, per_source_chars)
        parts.append(f"{prefix}{bounded_text}{suffix}")

    return separator.join(parts)[:max_chars]


def create_initial_state(
    batch_size: int = 30,
    search_days_back: int = 7,
    model: str = "gpt-4",
    use_placeholder_images: bool = False,
    job_id: Optional[str] = None,
) -> BlogPostState:
    """Create the initial state for the workflow."""
    return BlogPostState(
        batch_size=batch_size,
        search_days_back=search_days_back,
        model=model,
        use_placeholder_images=use_placeholder_images,
        job_id=job_id,
        search_results={},
        articles=[],
        shoppers_articles=[],
        recall_articles=[],
        learning_context={},
        shoppers_context={},
        recall_context={},
        generated_posts=[],
        reflection_results=[],
        posts_needing_regeneration=[],
        regeneration_count=0,
        max_regenerations=MAX_REGENERATIONS,
        images=[],
        uploaded_urls=[],
        final_posts=[],
        saved_files=[],
        saved_post_ids=[],
        db_inserted=0,
        persistence_errors=[],
        processed_urls={},
        errors=[],
        logs=[],
        start_time=datetime.now().isoformat(),
        end_time=""
    )


# ============================================================================
# NODE IMPLEMENTATIONS
# ============================================================================

def search_articles_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Search for articles using Exa API.
    
    Calls the existing zap_exa_ranker.py functionality.
    """
    logs = [f"[{datetime.now().isoformat()}] Searching for articles..."]
    
    try:
        input_data = {
            "batch_size": state["batch_size"],
            "batch_index": 0,
            "search_days_back": state["search_days_back"]
        }
        
        search_results = search_articles_exa(input_data)
        
        if search_results.get("error"):
            return {
                "search_results": {},
                "errors": [f"Search error: {search_results['error']}"],
                "logs": logs + [f"Search failed: {search_results['error']}"]
            }
        
        logs.append(f"Found {len(search_results.get('items', []))} articles")
        
        return {
            "search_results": search_results,
            "logs": logs
        }
        
    except Exception as e:
        return {
            "search_results": {},
            "errors": [f"Search exception: {str(e)}"],
            "logs": logs + [f"Search exception: {str(e)}"]
        }


def select_articles_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Select top articles for blog post generation.

    Filters out already-processed articles and selects articles based on batch_size.
    Allocates 1 recall article and remaining slots for shoppers articles.
    """
    logs = [f"[{datetime.now().isoformat()}] Selecting top articles..."]

    search_results = state.get("search_results", {})
    processed_urls = state.get("processed_urls", {})
    batch_size = state.get("batch_size", 6)

    # Use the full grocery candidate pool when available. ``items`` is the
    # paginated preview, while shoppers_items lets cross-run dedup skip used
    # URLs without reducing the requested number of regular posts.
    items = search_results.get("shoppers_items") or search_results.get("items", [])
    recall_items = search_results.get("recall_items", [])

    # Cross-run dedup: check Supabase blog_posts for URLs used in the last 60 days
    recently_used_urls = set()
    try:
        supabase = get_supabase_client()
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=60)).isoformat()
        if supabase is None:
            raise RuntimeError("Supabase is not configured")
        recent_posts = supabase.table("blog_posts").select("article_url").neq(
            "article_url", ""
        ).gte("created_at", cutoff).execute()
        for row in (recent_posts.data or []):
            if row.get("article_url"):
                recently_used_urls.add(
                    canonicalize_article_url(row["article_url"])
                    or row["article_url"]
                )
        logs.append(f"Cross-run dedup: {len(recently_used_urls)} URLs from last 60 days")
    except Exception as e:
        logs.append(f"Cross-run dedup check failed (continuing): {str(e)}")

    # Filter out already cached articles (session) AND recently used articles (cross-run)
    today = datetime.now().strftime("%Y-%m-%d")

    def is_not_cached(item):
        url = item.get("link", "")
        canonical_url = canonicalize_article_url(url)
        if not canonical_url:
            return False
        # Cross-run check: skip if URL was used in last 60 days (shoppers only, not recalls)
        if (
            item.get("category", "").upper() != "RECALL"
            and canonical_url in recently_used_urls
        ):
            return False
        url_hash = get_url_hash(canonical_url)
        cached = processed_urls.get(url_hash, {})
        return cached.get("date") != today if isinstance(cached, dict) else True

    # Recall sources are consolidated into one output post. Filter them first
    # so a slot is reserved only when a usable roundup source actually exists.
    recall_articles = [
        item for item in recall_items
        if is_not_cached(item)
    ][:MAX_RECALL_ROUNDUP_SOURCES if batch_size > 0 else 0]

    max_shoppers = max(0, batch_size - 1) if recall_articles else batch_size
    shoppers_articles = [
        item for item in items
        if item.get("category", "").upper() != "RECALL"
        and is_not_cached(item)
    ][:max_shoppers]

    # batch_size counts output posts: each shopper article is one output and
    # all recall sources below become one roundup output.
    all_articles = shoppers_articles + recall_articles

    logs.append(f"Selected {len(shoppers_articles)} shoppers + {len(recall_articles)} recall articles (batch_size={batch_size}, total={len(all_articles)})")

    return {
        "shoppers_articles": shoppers_articles,
        "recall_articles": recall_articles,
        "articles": all_articles,
        "logs": logs
    }


def load_learning_context_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Load learning context (examples, memory, patterns) for generation.
    """
    logs = [f"[{datetime.now().isoformat()}] Loading learning context..."]
    
    try:
        storage = get_supabase_storage()
        example_store = ExampleStore(storage)
        prompt_refiner = PromptRefiner(storage)
        learning_memory = LearningMemory(storage)
        
        def load_context_for_category(category: str) -> Dict[str, Any]:
            memory = learning_memory.load_session_memory(category)
            examples = example_store.get_examples_for_generation(category)
            prompt_additions = prompt_refiner.get_refined_prompt_section(category)
            
            return {
                "memory": memory,
                "good_examples": examples.get("good", []),
                "bad_examples": examples.get("bad", []),
                "prompt_additions": prompt_additions,
                "common_mistakes": memory.get("common_mistakes", []),
                "successful_patterns": memory.get("successful_patterns", []),
            }
        
        shoppers_context = load_context_for_category("shoppers")
        recall_context = load_context_for_category("recall")
        
        logs.append(f"Loaded {len(shoppers_context['good_examples'])} good examples")
        logs.append(f"Found {len(shoppers_context['common_mistakes'])} common mistakes to avoid")
        
        return {
            "shoppers_context": shoppers_context,
            "recall_context": recall_context,
            "learning_context": {
                "shoppers": shoppers_context,
                "recall": recall_context
            },
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"Learning context load error (continuing with empty): {str(e)}")
        empty_context = {
            "memory": {},
            "good_examples": [],
            "bad_examples": [],
            "prompt_additions": "",
            "common_mistakes": [],
            "successful_patterns": [],
        }
        return {
            "shoppers_context": empty_context,
            "recall_context": empty_context,
            "learning_context": {"shoppers": empty_context, "recall": empty_context},
            "logs": logs
        }


def generate_posts_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Generate blog posts using LangChain batch processing.
    
    Uses the BlogPostGenerator.batch_generate() for parallel generation.
    """
    logs = [f"[{datetime.now().isoformat()}] Generating blog posts..."]
    
    articles = state.get("articles", [])
    
    if not articles:
        return {
            "generated_posts": [],
            "logs": logs + ["No articles to process"]
        }
    
    # Check if we're regenerating specific posts
    posts_needing_regeneration = state.get("posts_needing_regeneration", [])
    if posts_needing_regeneration:
        articles_to_process = posts_needing_regeneration
        logs.append(f"Regenerating {len(articles_to_process)} posts...")
    else:
        articles_to_process = articles
    
    try:
        generator = BlogPostGenerator(model=state.get("model", "gpt-4"))
        
        # Prepare articles with learning context
        shoppers_context = state.get("shoppers_context", {})
        recall_context = state.get("recall_context", {})
        
        generated_posts = []
        
        # Separate recall and shoppers articles (Issue #860 - consolidate recalls into roundup)
        # Fixed: use consistent case checking with uppercase "RECALL" like in select_articles_node
        recall_articles_to_process = [a for a in articles_to_process if a.get("category", "").upper() == "RECALL"]
        shoppers_articles_to_process = [a for a in articles_to_process if a.get("category", "").upper() != "RECALL"]
        
        # Debug logging
        logs.append(f"  📊 Found {len(recall_articles_to_process)} recall articles and {len(shoppers_articles_to_process)} shoppers articles")
        
        # Generate individual shoppers posts
        for article in shoppers_articles_to_process:
            context = shoppers_context

            result = generator.generate_with_reflection(
                title=article.get("title", ""),
                content=article.get("content") or article.get("description") or "",
                original_link=article.get("link", ""),
                category="shoppers",
                good_examples=context.get("good_examples"),
                bad_examples=context.get("bad_examples"),
                prompt_additions=context.get("prompt_additions"),
                common_mistakes=context.get("common_mistakes"),
                successful_patterns=context.get("successful_patterns"),
                regeneration_hints=article.get("regeneration_hints"),
            )
            
            result["article"] = article
            result["category"] = "shoppers"
            result["post_id"] = get_url_hash(article.get("link", ""))
            
            generated_posts.append(result)
            
            status = "✓" if result.get("success") else "✗"
            logs.append(f"  {status} {article.get('title', 'Unknown')[:50]}...")
        
        # Consolidate recall articles into a single weekly roundup (Issue #860 - Fix)
        if recall_articles_to_process:
            logs.append(f"  🔄 Consolidating {len(recall_articles_to_process)} recall articles into weekly roundup...")
            
            # A graph retry already carries the assembled roundup. Reuse it
            # directly instead of nesting it as a one-item roundup.
            existing_roundup = (
                recall_articles_to_process[0]
                if len(recall_articles_to_process) == 1
                and recall_articles_to_process[0].get("is_roundup")
                else None
            )
            if existing_roundup:
                merged_article = dict(existing_roundup)
                combined_title = merged_article.get("title", "Weekly recall roundup")
                combined_content = (
                    merged_article.get("content")
                    or merged_article.get("description")
                    or ""
                )
                primary_link = merged_article.get("link", "")
                source_count = len(merged_article.get("source_articles") or []) or 1
            else:
                source_count = len(recall_articles_to_process)
                combined_title = (
                    f"Weekly recall roundup: {source_count} food safety alerts you need to know"
                )
                combined_content = build_recall_source_context(recall_articles_to_process)
                primary_link = recall_articles_to_process[0].get("link", "")
                merged_article = {
                    "title": combined_title,
                    "content": combined_content,
                    "link": primary_link,
                    "category": "RECALL",
                    "is_roundup": True,
                    "source_articles": recall_articles_to_process,
                }

            result = generator.generate_with_reflection(
                title=combined_title,
                content=combined_content,
                original_link=primary_link,
                category="recall",
                good_examples=recall_context.get("good_examples"),
                bad_examples=recall_context.get("bad_examples"),
                prompt_additions=recall_context.get("prompt_additions"),
                common_mistakes=recall_context.get("common_mistakes"),
                successful_patterns=recall_context.get("successful_patterns"),
                regeneration_hints=merged_article.get("regeneration_hints"),
            )
            
            result["article"] = merged_article
            result["category"] = "recall"
            result["post_id"] = get_url_hash(f"recall-roundup-{datetime.now().strftime('%Y-%W')}")
            
            generated_posts.append(result)
            
            status = "✓" if result.get("success") else "✗"
            logs.append(f"  {status} Weekly Recall Roundup ({source_count} recalls)")
        
        logs.append(f"Generated {len(generated_posts)} blog posts")
        
        return {
            "generated_posts": generated_posts,
            "logs": logs
        }
        
    except Exception as e:
        return {
            "generated_posts": [],
            "errors": [f"Generation error: {str(e)}"],
            "logs": logs + [f"Generation exception: {str(e)}"]
        }


def reflect_posts_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Run reflection agent on generated posts to validate quality.
    """
    logs = [f"[{datetime.now().isoformat()}] Reflecting on generated posts..."]
    
    generated_posts = state.get("generated_posts", [])
    
    if not generated_posts:
        return {
            "reflection_results": [],
            "posts_needing_regeneration": [],
            "logs": logs + ["No posts to reflect on"]
        }
    
    try:
        reflection_agent = ReflectionAgent()
        learning_context = state.get("learning_context", {})
        
        reflection_results = []
        posts_needing_regeneration = []
        
        for post in generated_posts:
            blog_post = post.get("blog_post", "")
            category = post.get("category", "shoppers")
            bad_examples = learning_context.get(category, {}).get("bad_examples", [])
            
            reflection = reflection_agent.reflect(blog_post, bad_examples)
            
            result = {
                "post_id": post.get("post_id"),
                "reflection": reflection,
                "is_valid": reflection.get("is_valid", False),
                "should_regenerate": reflection_agent.should_regenerate(reflection)
            }
            
            reflection_results.append(result)
            
            if result["should_regenerate"]:
                # Include reflection hints for regeneration
                post_with_hints = post.get("article", {}).copy()
                post_with_hints["regeneration_hints"] = reflection_agent.get_regeneration_hints(reflection)
                posts_needing_regeneration.append(post_with_hints)
                logs.append(f"  ⚠ Post {post.get('post_id')} needs regeneration")
        
        valid_count = sum(1 for r in reflection_results if r["is_valid"])
        logs.append(f"Reflection complete: {valid_count}/{len(reflection_results)} valid")
        
        return {
            "reflection_results": reflection_results,
            "posts_needing_regeneration": posts_needing_regeneration,
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"Reflection error (continuing): {str(e)}")
        return {
            "reflection_results": [],
            "posts_needing_regeneration": [],
            "logs": logs
        }


def should_regenerate(state: BlogPostState) -> str:
    """
    Conditional edge function: Determine if regeneration is needed.
    
    Returns:
        "regenerate" - if posts need regeneration and we haven't exceeded max
        "continue" - if all posts are valid or we've hit max regenerations
    """
    posts_needing_regeneration = state.get("posts_needing_regeneration", [])
    regeneration_count = state.get("regeneration_count", 0)
    max_regenerations = state.get("max_regenerations", MAX_REGENERATIONS)
    
    if posts_needing_regeneration and regeneration_count < max_regenerations:
        return "regenerate"
    
    return "continue"


def increment_regeneration_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Increment regeneration counter before looping back.
    """
    return {
        "regeneration_count": state.get("regeneration_count", 0) + 1,
        "logs": [f"[{datetime.now().isoformat()}] Regeneration attempt {state.get('regeneration_count', 0) + 1}"]
    }


PROOFREAD_PROMPT = """You are a professional copy editor. Proofread the following HTML blog post and fix ONLY:
- Spelling errors
- Grammar mistakes (subject-verb agreement, tense consistency, missing articles)
- Repeated words within the same sentence
- Missing or incorrect punctuation
- Awkward phrasing that sounds AI-generated

Do NOT change:
- The HTML structure or tags
- The meaning or tone of the content
- Proper nouns, brand names, or URLs
- The four-part close section links

Return ONLY the corrected HTML with no explanation. If there are no errors, return the original HTML unchanged."""


def proofread_posts_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Run a final proofreading pass on all generated posts to fix typos and grammar.
    Uses the LLM as a copy editor before image generation.
    """
    logs = [f"[{datetime.now().isoformat()}] Proofreading posts for typos and grammar..."]

    generated_posts = state.get("generated_posts", [])

    if not generated_posts:
        return {"proofread_corrections": {}, "logs": logs + ["No posts to proofread"]}

    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        model = state.get("model", "gpt-4")
        llm = ChatOpenAI(
            model=model,
            temperature=0,  # Deterministic for proofreading
            api_key=os.getenv("OPENAI_API_KEY")
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", PROOFREAD_PROMPT),
            ("human", "{blog_post}")
        ])
        chain = prompt | llm | StrOutputParser()

        corrections = {}
        fixes_count = 0

        for post in generated_posts:
            blog_post = post.get("blog_post", "")
            post_id = post.get("post_id", "")
            if not blog_post or not post_id:
                continue

            try:
                corrected = chain.invoke({"blog_post": blog_post})

                # Only accept correction if it preserves the HTML structure
                if corrected.strip().startswith("<div") and corrected.strip().endswith("</div>"):
                    if corrected.strip() != blog_post.strip():
                        fixes_count += 1
                        corrections[post_id] = corrected
                        logs.append(f"  ✓ Fixed typos in: {post.get('article', {}).get('title', 'Unknown')[:50]}")
                else:
                    logs.append(f"  ⚠ Proofread output invalid for: {post.get('article', {}).get('title', 'Unknown')[:50]}, keeping original")
            except Exception as e:
                logs.append(f"  ⚠ Proofread failed for post: {str(e)[:80]}, keeping original")

        logs.append(f"Proofreading complete: {fixes_count} post(s) corrected out of {len(generated_posts)}")

        return {
            "proofread_corrections": corrections,
            "logs": logs
        }

    except Exception as e:
        logs.append(f"Proofreading error (continuing with originals): {str(e)}")
        return {
            "proofread_corrections": {},
            "logs": logs
        }


def generate_images_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Generate images for all blog posts in parallel.
    """
    logs = [f"[{datetime.now().isoformat()}] Generating images..."]
    
    generated_posts = state.get("generated_posts", [])
    
    if not generated_posts:
        return {"images": [], "logs": logs + ["No posts for image generation"]}
    
    try:
        image_generator = get_image_generator(
            use_placeholder=state.get("use_placeholder_images", False)
        )
        
        images = []
        
        for post in generated_posts:
            if not post.get("success") and not post.get("blog_post"):
                continue

            article = post.get("article", {})
            category = post.get("category", "").upper()

            # Skip RECALL articles - they use a default image instead of generated
            if category == "RECALL":
                logs.append(f"  ⊘ Skipping image for RECALL: {article.get('title', 'Unknown')[:40]}...")
                # Add placeholder entry so upload_images_node knows about this post
                images.append({
                    "post_id": post.get("post_id"),
                    "success": False,
                    "is_recall": True
                })
                continue

            image_result = image_generator.generate_image_for_article(article)
            image_result["post_id"] = post.get("post_id")
            image_result["is_recall"] = False

            images.append(image_result)

            status = "✓" if image_result.get("success") else "✗"
            error_msg = f" ({image_result.get('error', 'unknown error')})" if not image_result.get("success") else ""
            logs.append(f"  {status} Image for {article.get('title', 'Unknown')[:40]}...{error_msg}")
        
        logs.append(f"Generated {len([i for i in images if i.get('success')])} images")
        
        return {
            "images": images,
            "logs": logs
        }
        
    except Exception as e:
        return {
            "images": [],
            "errors": [f"Image generation error: {str(e)}"],
            "logs": logs + [f"Image generation exception: {str(e)}"]
        }


def upload_images_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Upload generated images to imgBB.
    RECALL articles get a default image URL instead.
    """
    logs = [f"[{datetime.now().isoformat()}] Uploading images to imgBB..."]

    images = state.get("images", [])

    if not images:
        return {"uploaded_urls": [], "logs": logs + ["No images to upload"]}

    try:
        uploaded_urls = []

        for image in images:
            post_id = image.get("post_id", "unknown")

            # RECALL articles use default image
            if image.get("is_recall"):
                uploaded_urls.append({
                    "post_id": post_id,
                    "url": DEFAULT_RECALL_IMAGE_URL,
                    "success": True
                })
                logs.append(f"  ✓ Using default image for RECALL post {post_id}")
                continue

            # Failed image generation - use placeholder
            if not image.get("success"):
                uploaded_urls.append({
                    "post_id": post_id,
                    "url": "{IMAGE_HERE}",
                    "success": False
                })
                logs.append(f"  ✗ No image data for {post_id}")
                continue

            # Upload to imgBB
            upload_result = upload_image_to_imgbb(
                image_data=image.get("image_data", ""),
                name=post_id
            )

            uploaded_urls.append({
                "post_id": post_id,
                "url": upload_result.get("url", "{IMAGE_HERE}"),
                "success": upload_result.get("success", False)
            })

            status = "✓" if upload_result.get("success") else "✗"
            logs.append(f"  {status} Uploaded {post_id} to imgBB")

        success_count = sum(1 for u in uploaded_urls if u.get("success"))
        logs.append(f"Uploaded {success_count}/{len(uploaded_urls)} images")

        return {
            "uploaded_urls": uploaded_urls,
            "logs": logs
        }

    except Exception as e:
        return {
            "uploaded_urls": [],
            "errors": [f"Upload error: {str(e)}"],
            "logs": logs + [f"Upload exception: {str(e)}"]
        }


def assemble_html_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Assemble final HTML by replacing placeholders with image URLs.
    """
    logs = [f"[{datetime.now().isoformat()}] Assembling final HTML..."]

    generated_posts = state.get("generated_posts", [])
    uploaded_urls = state.get("uploaded_urls", [])
    proofread_corrections = state.get("proofread_corrections", {})

    # Create URL lookup
    url_lookup = {u["post_id"]: u["url"] for u in uploaded_urls}

    # Deduplicate posts by post_id, keeping only the latest version
    # (since regeneration cycles can create duplicates with operator.add)
    posts_by_id = {}
    for post in generated_posts:
        if not post.get("blog_post"):
            continue
        post_id = post.get("post_id", "")
        # Keep the latest version (last one in list)
        posts_by_id[post_id] = post

    logs.append(f"Deduplicated {len(generated_posts)} posts down to {len(posts_by_id)} unique posts")
    if proofread_corrections:
        logs.append(f"Applying {len(proofread_corrections)} proofread correction(s)")

    final_posts = []
    assembly_errors = []
    final_validator = ReflectionAgent()

    for post_id, post in posts_by_id.items():
        # Use proofread version if available, otherwise original
        blog_post = proofread_corrections.get(post_id, post.get("blog_post", ""))
        blog_post = ensure_news_blog_back_link(blog_post)
        article = post.get("article", {})
        original_link = article.get("link", "")

        unsafe_issues = find_unsafe_html_issues(blog_post)
        if unsafe_issues:
            title = article.get("title", "Unknown")
            assembly_errors.append(
                f"Unsafe generated HTML rejected for '{title}': "
                + "; ".join(unsafe_issues)
            )
            logs.append(f"Rejected unsafe generated HTML for: {title[:50]}")
            continue

        final_validation = final_validator.reflect(blog_post)
        if not final_validation.get("is_valid", False):
            title = article.get("title", "Unknown")
            summary = final_validation.get("summary", "Validation failed")
            assembly_errors.append(
                f"Generated HTML failed final validation for '{title}': {summary}"
            )
            logs.append(f"Rejected invalid generated HTML for: {title[:50]}")
            continue

        # Get image URL
        image_url = url_lookup.get(post_id, "{IMAGE_HERE}")

        # Replace placeholders
        final_html = ensure_newsletter_signup_block(blog_post)
        final_html = final_html.replace("{IMAGE_HERE}", image_url)
        final_html = final_html.replace("{{IMAGE_HERE}}", image_url)
        final_html = final_html.replace("{original_link}", original_link)

        final_unsafe_issues = find_unsafe_html_issues(final_html)
        if final_unsafe_issues:
            title = article.get("title", "Unknown")
            assembly_errors.append(
                f"Unsafe assembled HTML rejected for '{title}': "
                + "; ".join(final_unsafe_issues)
            )
            logs.append(f"Rejected unsafe assembled HTML for: {title[:50]}")
            continue

        final_post = {
            "post_id": post_id,
            "html": final_html,
            "title": article.get("title", ""),
            "category": post.get("category", "shoppers"),
            "original_link": original_link,
            "image_url": image_url,
            "article": article,
            "reflection": post.get("reflection", {}),
            "attempts": post.get("attempts", 1)
        }

        final_posts.append(final_post)

    logs.append(f"Assembled {len(final_posts)} final blog posts")

    return {
        "final_posts": final_posts,
        "errors": assembly_errors,
        "logs": logs
    }


def save_posts_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Save final blog posts to filesystem and Supabase database.
    """
    logs = [f"[{datetime.now().isoformat()}] Saving blog posts..."]

    final_posts = state.get("final_posts", [])

    if not final_posts:
        return {
            "saved_files": [],
            "saved_post_ids": [],
            "logs": logs + ["No posts to save"],
        }

    # Ensure output directory exists
    os.makedirs(BLOG_POSTS_DIR, exist_ok=True)

    # Get Supabase client for database insertion
    try:
        supabase = get_supabase_client()
    except Exception as e:
        supabase = None
        logs.append(f"  ⚠ Could not connect to Supabase: {str(e)}")

    saved_files = []
    saved_post_ids = []
    db_inserted = 0
    persistence_errors = []
    processed_urls = state.get("processed_urls", {}).copy()
    job_id = state.get("job_id")
    if supabase is None and job_id:
        persistence_errors.append("Supabase was unavailable while saving generated posts")

    for post in final_posts:
        # Keep this list aligned with final_posts so the Blogger step can update
        # the exact row created here, even when titles are duplicated.
        saved_post_ids.append(None)
        try:
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(
                c for c in post.get("title", "post")[:30] 
                if c.isalnum() or c in " -_"
            ).strip().replace(" ", "_")
            
            post_id = post.get("post_id", "unknown")
            filename = f"{timestamp}_{safe_title}_{post_id}"
            
            # Save HTML
            html_path = os.path.join(BLOG_POSTS_DIR, f"{filename}.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(post["html"])
            
            # Save metadata
            import json
            metadata = {
                "title": post.get("title", ""),
                "category": post.get("category", ""),
                "original_link": post.get("original_link", ""),
                "image_url": post.get("image_url", ""),
                "generated_at": datetime.now().isoformat(),
                "article": post.get("article", {}),
                "reflection": post.get("reflection", {}),
                "attempts": post.get("attempts", 1)
            }
            
            metadata_path = os.path.join(BLOG_POSTS_DIR, f"{filename}.json")
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, default=str)
            
            saved_files.append(html_path)

            # Update processed URLs cache
            processed_urls[post_id] = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "blog_post_id": post_id
            }

            # Insert into Supabase database
            if supabase:
                try:
                    from uuid import uuid4
                    database_post_id = str(uuid4())
                    supabase.table("blog_posts").insert({
                        "id": database_post_id,
                        "title": post.get("title", ""),
                        "html_content": post.get("html", ""),
                        "image_url": post.get("image_url", ""),
                        "category": post.get("category", "SHOPPERS").upper(),
                        "status": "draft",
                        "article_url": post.get("original_link", ""),
                        "job_id": job_id,
                        "created_at": datetime.now().isoformat()
                    }).execute()
                    saved_post_ids[-1] = database_post_id
                    db_inserted += 1
                except Exception as db_err:
                    persistence_errors.append(str(db_err))
                    logs.append(f"  ⚠ DB insert failed for {post.get('title', 'unknown')[:30]}: {str(db_err)}")

            logs.append(f"  ✓ Saved {filename}.html")

        except Exception as e:
            logs.append(f"  ✗ Error saving post: {str(e)}")
    
    if job_id and db_inserted < len(final_posts) and not persistence_errors:
        persistence_errors.append("One or more generated posts were not persisted")

    logs.append(f"Saved {len(saved_files)} blog posts to {BLOG_POSTS_DIR}/")
    if supabase:
        logs.append(f"Inserted {db_inserted} posts into Supabase database")
    
    return {
        "saved_files": saved_files,
        "saved_post_ids": saved_post_ids,
        "db_inserted": db_inserted,
        "persistence_errors": persistence_errors,
        "processed_urls": processed_urls,
        "end_time": datetime.now().isoformat(),
        "logs": logs
    }


def hydrate_articles_node(state: BlogPostState) -> Dict[str, Any]:
    """Fetch fuller text for selected articles while failing open to excerpts."""
    logs = [f"[{datetime.now().isoformat()}] Hydrating selected article content..."]
    articles = state.get("articles", [])

    if not articles:
        return {
            "articles": [],
            "shoppers_articles": [],
            "recall_articles": [],
            "logs": logs + ["No selected articles to hydrate"],
        }

    try:
        hydrated = hydrate_article_contents(articles)
        hydrated_count = sum(
            1 for article in hydrated
            if article.get("content") and article.get("content") != article.get("description")
        )
        logs.append(f"Hydrated {hydrated_count}/{len(hydrated)} selected articles")
        if hydrated_count < len(hydrated):
            logs.append(
                f"Using discovery excerpts for {len(hydrated) - hydrated_count} article(s)"
            )
    except Exception as exc:
        # Search excerpts remain usable if the follow-up contents request fails.
        hydrated = []
        for article in articles:
            fallback = dict(article)
            fallback["content"] = (
                fallback.get("content") or fallback.get("description") or ""
            )
            hydrated.append(fallback)
        logs.append(f"Content hydration failed; using search excerpts: {exc}")

    return {
        "articles": hydrated,
        "shoppers_articles": [
            article for article in hydrated
            if article.get("category", "").upper() != "RECALL"
        ],
        "recall_articles": [
            article for article in hydrated
            if article.get("category", "").upper() == "RECALL"
        ],
        "logs": logs,
    }


def push_drafts_to_blogger_node(state: BlogPostState) -> Dict[str, Any]:
    """
    Node: Push newly saved posts to Blogger as drafts.
    Runs after save_posts_node. Best-effort — failures do not block the workflow.
    """
    logs = [f"[{datetime.now().isoformat()}] Pushing drafts to Blogger..."]

    try:
        from blogger_client import get_blogger_client
        blogger = get_blogger_client()

        if not blogger.is_configured():
            logs.append("  Blogger not configured, skipping draft push")
            return {"logs": logs}
    except Exception as e:
        logs.append(f"  Could not initialize Blogger client: {str(e)}")
        return {"logs": logs}

    try:
        supabase = get_supabase_client()
    except Exception:
        logs.append("  Could not connect to Supabase, skipping draft push")
        return {"logs": logs}

    final_posts = state.get("final_posts", [])
    if state.get("job_id") and state.get("db_inserted", 0) < len(final_posts):
        logs.append("  Skipping Blogger draft push because not all posts were persisted")
        return {"logs": logs}

    pushed = 0
    saved_post_ids = state.get("saved_post_ids", [])
    job_id = state.get("job_id")

    for post_index, post in enumerate(final_posts):
        title = post.get("title", "Untitled")
        html = post.get("html", "")
        category = post.get("category", "SHOPPERS")

        try:
            result = blogger.publish_post(
                title=title,
                html_content=html,
                labels=[category.upper()],
                is_draft=True
            )
            blogger_post_id = result.get("blogger_post_id")

            if blogger_post_id:
                database_post_id = (
                    saved_post_ids[post_index]
                    if post_index < len(saved_post_ids)
                    else None
                )

                # Legacy callers may not provide saved_post_ids. Limit that
                # fallback to this generation job before matching by title.
                if not database_post_id:
                    query = supabase.table("blog_posts").select("id")
                    if job_id:
                        query = query.eq("job_id", job_id)
                    db_result = query.eq("title", title).order(
                        "created_at", desc=True
                    ).limit(1).execute()
                    if db_result.data:
                        database_post_id = db_result.data[0]["id"]

                if database_post_id:
                    supabase.table("blog_posts").update({
                        "blogger_post_id": blogger_post_id,
                        "last_synced_at": datetime.now().isoformat()
                    }).eq("id", database_post_id).execute()

            pushed += 1
            logs.append(f"  Created Blogger draft for: {title[:40]}")
        except Exception as e:
            logs.append(f"  Failed to push '{title[:40]}' to Blogger: {str(e)}")

    logs.append(f"Pushed {pushed}/{len(final_posts)} drafts to Blogger")
    return {"logs": logs}


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================

def create_blog_post_graph() -> StateGraph:
    """
    Create the LangGraph StateGraph for blog post generation.
    
    Returns:
        Compiled StateGraph workflow
    """
    # Create the graph
    workflow = StateGraph(BlogPostState)
    
    # Add nodes
    workflow.add_node("search_articles", search_articles_node)
    workflow.add_node("select_articles", select_articles_node)
    workflow.add_node("hydrate_articles", hydrate_articles_node)
    workflow.add_node("load_learning_context", load_learning_context_node)
    workflow.add_node("generate_posts", generate_posts_node)
    workflow.add_node("reflect_posts", reflect_posts_node)
    workflow.add_node("increment_regeneration", increment_regeneration_node)
    workflow.add_node("proofread_posts", proofread_posts_node)
    workflow.add_node("generate_images", generate_images_node)
    workflow.add_node("upload_images", upload_images_node)
    workflow.add_node("assemble_html", assemble_html_node)
    workflow.add_node("save_posts", save_posts_node)
    workflow.add_node("push_drafts_to_blogger", push_drafts_to_blogger_node)

    # Add edges
    workflow.add_edge(START, "search_articles")
    workflow.add_edge("search_articles", "select_articles")
    workflow.add_edge("select_articles", "hydrate_articles")
    workflow.add_edge("hydrate_articles", "load_learning_context")
    workflow.add_edge("load_learning_context", "generate_posts")
    workflow.add_edge("generate_posts", "reflect_posts")
    
    # Conditional edge: regenerate or continue
    workflow.add_conditional_edges(
        "reflect_posts",
        should_regenerate,
        {
            "regenerate": "increment_regeneration",
            "continue": "proofread_posts"
        }
    )

    # Proofread → image generation
    workflow.add_edge("proofread_posts", "generate_images")
    
    # Regeneration loop
    workflow.add_edge("increment_regeneration", "generate_posts")
    
    # Continue to image generation
    workflow.add_edge("generate_images", "upload_images")
    workflow.add_edge("upload_images", "assemble_html")
    workflow.add_edge("assemble_html", "save_posts")
    workflow.add_edge("save_posts", "push_drafts_to_blogger")
    workflow.add_edge("push_drafts_to_blogger", END)
    
    return workflow.compile()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def run_blog_post_workflow(
    batch_size: int = 30,
    search_days_back: int = 7,
    model: str = "gpt-4",
    use_placeholder_images: bool = False,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the complete blog post generation workflow using LangGraph.
    
    Args:
        batch_size: Number of articles to search
        search_days_back: How far back to search
        model: OpenAI model for generation
        use_placeholder_images: Use placeholder images instead of Gemini
        
    Returns:
        Final workflow state with results
    """
    print("=" * 60, file=sys.stderr)
    print("LANGGRAPH BLOG POST GENERATION WORKFLOW", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Create the graph
    app = create_blog_post_graph()
    
    # Create initial state
    initial_state = create_initial_state(
        batch_size=batch_size,
        search_days_back=search_days_back,
        model=model,
        use_placeholder_images=use_placeholder_images,
        job_id=job_id,
    )
    
    # Run the workflow
    final_state = app.invoke(initial_state)
    
    # Print logs to stderr to avoid contaminating JSON output
    for log in final_state.get("logs", []):
        print(log, file=sys.stderr)

    # Print errors to stderr
    if final_state.get("errors"):
        print("\n⚠️ Errors:", file=sys.stderr)
        for error in final_state["errors"]:
            print(f"  - {error}", file=sys.stderr)

    # Calculate duration
    start_time_str = final_state.get("start_time") or datetime.now().isoformat()
    end_time_str = final_state.get("end_time") or datetime.now().isoformat()
    start_time = datetime.fromisoformat(start_time_str)
    end_time = datetime.fromisoformat(end_time_str)
    duration = (end_time - start_time).total_seconds()

    # Print summary to stderr
    print("\n" + "=" * 60, file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Posts generated: {len(final_state.get('final_posts', []))}", file=sys.stderr)
    print(f"Files saved: {len(final_state.get('saved_files', []))}", file=sys.stderr)
    print(f"Errors: {len(final_state.get('errors', []))}", file=sys.stderr)
    print(f"Duration: {duration:.2f} seconds", file=sys.stderr)
    print(f"Output: {BLOG_POSTS_DIR}/", file=sys.stderr)
    
    # Count posts by category
    final_posts = final_state.get("final_posts", [])
    shoppers_count = sum(1 for p in final_posts if p.get("category", "").upper() == "SHOPPERS")
    recall_count = sum(1 for p in final_posts if p.get("category", "").upper() == "RECALL")

    # Return summary
    return {
        "success": len(final_state.get("errors", [])) == 0,
        "posts_generated": len(final_posts),
        "shoppers_count": shoppers_count,
        "recall_count": recall_count,
        "files_saved": final_state.get("saved_files", []),
        "errors": final_state.get("errors", []),
        "duration_seconds": round(duration, 2),
        "output_directory": BLOG_POSTS_DIR,
        "final_state": final_state
    }


# For testing and CLI usage
if __name__ == "__main__":
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="Run LangGraph blog post workflow")
    parser.add_argument("--model", default="gpt-4", help="OpenAI model to use")
    parser.add_argument("--placeholder-images", action="store_true", help="Use placeholder images")
    parser.add_argument("--batch-size", type=int, default=30, help="Number of articles to search")
    parser.add_argument("--days-back", type=int, default=7, help="Search window in days")
    
    args = parser.parse_args()
    
    result = run_blog_post_workflow(
        batch_size=args.batch_size,
        search_days_back=args.days_back,
        model=args.model,
        use_placeholder_images=args.placeholder_images
    )
    
    # Print result (excluding full state for readability)
    result_summary = {k: v for k, v in result.items() if k != "final_state"}
    print("\nResult:")
    print(json.dumps(result_summary, indent=2, default=str))


