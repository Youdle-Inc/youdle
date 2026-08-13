# generate_blog_posts.py
# Main orchestrator for blog post generation with learning integration
#
# This module now uses LangGraph StateGraph for workflow orchestration.
# The LangGraph implementation is in blog_post_graph.py.
#
# This file provides:
# - BlogPostOrchestrator: Legacy class (still functional as fallback)
# - run_generation(): Main entry point that uses LangGraph
# - run_generation_legacy(): Fallback to async orchestration

import os
import sys
import json
import asyncio
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import LangGraph workflow
try:
    from blog_post_graph import run_blog_post_workflow, create_blog_post_graph
    LANGGRAPH_AVAILABLE = True
except ImportError as e:
    print(f"Warning: LangGraph not available ({e}), using legacy orchestration", file=sys.stderr)
    LANGGRAPH_AVAILABLE = False

# Import components
from zap_exa_ranker import main as search_articles
from langchain_blog_agent import BlogPostGenerator
from image_generator import get_image_generator
from supabase_storage import get_supabase_storage
from example_store import ExampleStore, retrieve_similar_examples
from reflection_agent import ReflectionAgent
from prompt_refiner import PromptRefiner
from learning_memory import LearningMemory, load_learning_memory

# ============================================================================
# CONFIGURATION
# ============================================================================
BLOG_POSTS_DIR = os.getenv(
    "BLOG_POSTS_DIR",
    "/tmp/blog_posts" if os.getenv("VERCEL") else "blog_posts",
)
MAX_SHOPPERS_ARTICLES = 5
MAX_WORKERS = 4
CACHE_FILE = os.getenv(
    "BLOG_CACHE_FILE",
    "/tmp/.blog_cache.json" if os.getenv("VERCEL") else ".blog_cache.json",
)
USE_LANGGRAPH = True  # Set to False to use legacy orchestration


class BlogPostOrchestrator:
    """
    Main orchestrator for the blog post generation workflow.
    Integrates all components: search, generation, images, and learning.
    """

    def __init__(
        self,
        model: str = "gpt-4",
        use_placeholder_images: bool = False
    ):
        """
        Initialize the orchestrator.

        Args:
            model: OpenAI model for blog generation
            use_placeholder_images: Use placeholder images instead of Gemini
        """
        self.generator = BlogPostGenerator(model=model)
        self.image_generator = get_image_generator(use_placeholder=use_placeholder_images)
        self.supabase = get_supabase_storage()
        self.example_store = ExampleStore(self.supabase)
        self.reflection_agent = ReflectionAgent()
        self.prompt_refiner = PromptRefiner(self.supabase)
        self.learning_memory = LearningMemory(self.supabase)

        self._cache = self._load_cache()

        # Ensure output directory exists
        os.makedirs(BLOG_POSTS_DIR, exist_ok=True)

    def _load_cache(self) -> Dict[str, Any]:
        """Load the processing cache."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"processed_urls": {}}

    def _save_cache(self):
        """Save the processing cache."""
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}", file=sys.stderr)

    def _get_url_hash(self, url: str) -> str:
        """Generate a hash for a URL."""
        return hashlib.md5(url.encode()).hexdigest()[:12]

    def _is_cached(self, url: str) -> bool:
        """Check if a URL has been processed today."""
        url_hash = self._get_url_hash(url)
        cached = self._cache.get("processed_urls", {}).get(url_hash)

        if cached:
            cached_date = cached.get("date", "")
            today = datetime.now().strftime("%Y-%m-%d")
            return cached_date == today

        return False

    def _mark_cached(self, url: str, blog_post_id: str):
        """Mark a URL as processed."""
        url_hash = self._get_url_hash(url)
        self._cache.setdefault("processed_urls", {})[url_hash] = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "blog_post_id": blog_post_id
        }
        self._save_cache()

    def search_and_rank_articles(
        self,
        batch_size: int = 30,
        search_days_back: int = 30
    ) -> Dict[str, Any]:
        """
        Search for articles using Exa.

        Args:
            batch_size: Number of articles to fetch
            search_days_back: How far back to search

        Returns:
            Search results with ranked items
        """
        input_data = {
            "batch_size": batch_size,
            "batch_index": 0,
            "search_days_back": search_days_back
        }

        return search_articles(input_data)

    def select_articles(
        self,
        search_results: Dict[str, Any]
    ) -> Dict[str, List[Dict]]:
        """
        Select top articles for blog post generation.

        Args:
            search_results: Results from search_and_rank_articles

        Returns:
            Dictionary with 'shoppers' and 'recall' article lists
        """
        items = search_results.get("items", [])
        recall_items = search_results.get("recall_items", [])

        # Filter out already cached articles
        shoppers_articles = [
            item for item in items
            if item.get("category", "").upper() != "RECALL"
            and not self._is_cached(item.get("link", ""))
        ][:MAX_SHOPPERS_ARTICLES]

        recall_articles = [
            item for item in recall_items
            if not self._is_cached(item.get("link", ""))
        ][:1]  # Just one recall post

        return {
            "shoppers": shoppers_articles,
            "recall": recall_articles
        }

    def _load_learning_context(
        self,
        category: str
    ) -> Dict[str, Any]:
        """
        Load learning context for generation.

        Args:
            category: 'shoppers' or 'recall'

        Returns:
            Learning context with examples and patterns
        """
        # Load memory
        memory = self.learning_memory.load_session_memory(category)

        # Get examples
        examples = self.example_store.get_examples_for_generation(category)

        # Get prompt refinements
        prompt_additions = self.prompt_refiner.get_refined_prompt_section(category)

        return {
            "memory": memory,
            "good_examples": examples.get("good", []),
            "bad_examples": examples.get("bad", []),
            "prompt_additions": prompt_additions,
            "common_mistakes": memory.get("common_mistakes", [])
        }

    def generate_blog_post(
        self,
        article: Dict[str, Any],
        learning_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate a single blog post with learning integration.

        Args:
            article: Article data
            learning_context: Learning context from _load_learning_context

        Returns:
            Generation result
        """
        category = article.get("category", "SHOPPERS").lower()

        # Generate with reflection
        result = self.generator.generate_with_reflection(
            title=article.get("title", ""),
            content=article.get("description", ""),
            original_link=article.get("link", ""),
            category=category,
            good_examples=learning_context.get("good_examples"),
            bad_examples=learning_context.get("bad_examples")
        )

        # Additional reflection using our agent
        if result.get("blog_post"):
            reflection = self.reflection_agent.reflect(
                result["blog_post"],
                learning_context.get("bad_examples")
            )
            result["detailed_reflection"] = reflection

        result["article"] = article
        result["category"] = category

        return result

    def generate_image_for_post(
        self,
        blog_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate an image for a blog post.

        Args:
            blog_result: Result from generate_blog_post

        Returns:
            Image generation result
        """
        article = blog_result.get("article", {})

        return self.image_generator.generate_image_for_article(article)

    def upload_image(
        self,
        image_result: Dict[str, Any],
        filename: str
    ) -> Dict[str, Any]:
        """
        Upload an image to Supabase.

        Args:
            image_result: Result from generate_image_for_post
            filename: Filename for the image

        Returns:
            Upload result with public URL
        """
        if not image_result.get("success") or not self.supabase:
            return {"success": False, "error": "No image or Supabase client"}

        content_type = f"image/{image_result.get('format', 'png')}"

        return self.supabase.upload_image(
            image_data=image_result.get("image_data", ""),
            filename=filename,
            content_type=content_type
        )

    def assemble_final_html(
        self,
        blog_post: str,
        image_url: str,
        original_link: str
    ) -> str:
        """
        Assemble the final HTML with image URL.

        Args:
            blog_post: Generated HTML blog post
            image_url: Public URL of the uploaded image
            original_link: Original article link

        Returns:
            Final HTML with placeholders replaced
        """
        html = blog_post

        # Replace image placeholder
        html = html.replace("{IMAGE_HERE}", image_url)
        html = html.replace("{{IMAGE_HERE}}", image_url)

        # Replace link placeholder
        html = html.replace("{original_link}", original_link)

        return html

    def save_blog_post(
        self,
        html_content: str,
        metadata: Dict[str, Any],
        post_id: str
    ) -> str:
        """
        Save a blog post to file.

        Args:
            html_content: Final HTML content
            metadata: Post metadata
            post_id: Unique post ID

        Returns:
            Path to saved file
        """
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(
            c for c in metadata.get("title", "post")[:30]
            if c.isalnum() or c in " -_"
        ).strip().replace(" ", "_")

        filename = f"{timestamp}_{safe_title}_{post_id}"

        # Save HTML
        html_path = os.path.join(BLOG_POSTS_DIR, f"{filename}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Save metadata
        metadata_path = os.path.join(BLOG_POSTS_DIR, f"{filename}.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, default=str)

        return html_path

    async def process_article(
        self,
        article: Dict[str, Any],
        learning_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single article through the full pipeline.

        Args:
            article: Article data
            learning_context: Learning context

        Returns:
            Processing result
        """
        url = article.get("link", "")

        try:
            # Generate blog post
            blog_result = self.generate_blog_post(article, learning_context)

            if not blog_result.get("success") and not blog_result.get("blog_post"):
                return {
                    "success": False,
                    "error": "Blog post generation failed",
                    "article": article
                }

            blog_post = blog_result.get("blog_post", "")

            # Generate image
            image_result = self.generate_image_for_post(blog_result)

            # Upload image
            post_id = self._get_url_hash(url)
            image_filename = f"{post_id}.png"

            if image_result.get("success"):
                upload_result = self.upload_image(image_result, image_filename)
                image_url = upload_result.get("url", "{IMAGE_HERE}")
            else:
                image_url = "{IMAGE_HERE}"

            # Assemble final HTML
            final_html = self.assemble_final_html(blog_post, image_url, url)

            # Save blog post
            metadata = {
                "title": article.get("title", ""),
                "category": article.get("category", "SHOPPERS"),
                "original_link": url,
                "image_url": image_url,
                "generated_at": datetime.now().isoformat(),
                "article": article,
                "reflection": blog_result.get("detailed_reflection", {}),
                "attempts": blog_result.get("attempts", 1)
            }

            file_path = self.save_blog_post(final_html, metadata, post_id)

            # Mark as cached
            self._mark_cached(url, post_id)

            return {
                "success": True,
                "post_id": post_id,
                "file_path": file_path,
                "html": final_html,
                "title": article.get("title", ""),
                "category": article.get("category", "SHOPPERS"),
                "original_link": url,
                "image_url": image_url,
                "attempts": blog_result.get("attempts", 1),
                "reflection": blog_result.get("detailed_reflection", {})
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "article": article
            }

    async def run(
        self,
        batch_size: int = 30,
        search_days_back: int = 30
    ) -> Dict[str, Any]:
        """
        Run the full blog post generation workflow.

        Args:
            batch_size: Number of articles to search
            search_days_back: How far back to search

        Returns:
            Workflow results
        """
        start_time = datetime.now()

        print("=" * 60)
        print("BLOG POST GENERATION WORKFLOW")
        print("=" * 60)

        # Step 1: Search and rank articles
        print("\n[1/6] Searching for articles...")
        search_results = self.search_and_rank_articles(batch_size, search_days_back)

        if search_results.get("error"):
            return {
                "success": False,
                "error": search_results["error"]
            }

        # Step 2: Select articles
        print("[2/6] Selecting top articles...")
        selected = self.select_articles(search_results)

        all_articles = selected["shoppers"] + selected["recall"]
        print(f" - Shoppers articles: {len(selected['shoppers'])}")
        print(f" - Recall articles: {len(selected['recall'])}")

        if not all_articles:
            return {
                "success": True,
                "message": "No new articles to process",
                "posts_generated": 0
            }

        # Step 3: Load learning context
        print("[3/6] Loading learning context...")
        shoppers_context = self._load_learning_context("shoppers")
        recall_context = self._load_learning_context("recall")

        print(f" - Good examples: {len(shoppers_context['good_examples'])}")
        print(f" - Common mistakes: {len(shoppers_context['common_mistakes'])}")

        # Step 4: Generate blog posts
        print("[4/6] Generating blog posts...")
        results = []

        for article in all_articles:
            category = article.get("category", "SHOPPERS").lower()
            context = recall_context if category == "recall" else shoppers_context

            result = await self.process_article(article, context)
            results.append(result)

            status = "✓" if result.get("success") else "✗"
            print(f" {status} {article.get('title', 'Unknown')[:50]}...")

        # Step 5: Save learning insights
        print("[5/6] Saving learning insights...")
        successful = [r for r in results if r.get("success")]
        failed = [r for r in results if not r.get("success")]

        # Calculate session metrics
        total_attempts = sum(r.get("attempts", 1) for r in successful)
        avg_attempts = total_attempts / len(successful) if successful else 0

        session_data = {
            "posts_generated": len(successful),
            "posts_failed": len(failed),
            "approval_rate": None,  # Unknown until human review
            "avg_attempts": avg_attempts,
            "new_insights": []
        }

        # Analyze reflections for insights
        for result in successful:
            reflection = result.get("reflection", {})
            if reflection.get("common_mistakes"):
                for mistake in reflection["common_mistakes"]:
                    session_data["new_insights"].append({
                        "type": "common_mistake",
                        "description": mistake
                    })

        memory_result = self.learning_memory.save_session_memory("shoppers", session_data)
        if not memory_result.get("success", False):
            print(
                "Warning: Learning memory was not fully saved: "
                + "; ".join(memory_result.get("errors", ["unknown error"])),
                file=sys.stderr,
            )

        # Step 6: Summary
        print("[6/6] Generating summary...")

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        summary = {
            "success": True,
            "posts_generated": len(successful),
            "posts_failed": len(failed),
            "duration_seconds": round(duration, 2),
            "results": results,
            "learning_memory": memory_result,
            "output_directory": BLOG_POSTS_DIR,
            "generated_at": start_time.isoformat()
        }

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Posts generated: {len(successful)}")
        print(f"Posts failed: {len(failed)}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Output: {BLOG_POSTS_DIR}/")

        return summary


def run_generation(
    model: str = "gpt-4",
    use_placeholder_images: bool = False,
    batch_size: int = 30,
    search_days_back: int = 30,
    use_langgraph: bool = True,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the blog post generation workflow.

    Uses LangGraph StateGraph for orchestration by default.
    Falls back to legacy async orchestration if LangGraph is unavailable.
    """
    # Use LangGraph if available and enabled
    if use_langgraph and LANGGRAPH_AVAILABLE and USE_LANGGRAPH:
        return run_blog_post_workflow(
            batch_size=batch_size,
            search_days_back=search_days_back,
            model=model,
            use_placeholder_images=use_placeholder_images,
            job_id=job_id,
        )

    # Fallback to legacy orchestration
    return run_generation_legacy(
        model=model,
        use_placeholder_images=use_placeholder_images,
        batch_size=batch_size,
        search_days_back=search_days_back
    )


def run_generation_legacy(
    model: str = "gpt-4",
    use_placeholder_images: bool = False,
    batch_size: int = 30,
    search_days_back: int = 30
) -> Dict[str, Any]:
    """
    Run the blog post generation workflow using legacy async orchestration.

    This is the fallback method when LangGraph is not available.
    """
    orchestrator = BlogPostOrchestrator(
        model=model,
        use_placeholder_images=use_placeholder_images
    )

    return asyncio.run(orchestrator.run(batch_size, search_days_back))


# For CLI usage / GitHub Actions
if __name__ == "__main__":
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Generate blog posts from articles")
    parser.add_argument("--model", default="gpt-4", help="OpenAI model to use")
    parser.add_argument("--placeholder-images", action="store_true", help="Use placeholder images")
    parser.add_argument("--batch-size", type=int, default=30, help="Number of articles to search")
    parser.add_argument("--days-back", type=int, default=30, help="Search window in days")
    parser.add_argument("--legacy", action="store_true", help="Use legacy orchestration (skip LangGraph)")
    parser.add_argument("--json", action="store_true", help="Output only clean JSON summary (for GitHub Actions)")

    args = parser.parse_args()

    # === CRITICAL: Silence all verbose logging in CI mode ===
    if args.json:
        # Redirect all prints to nowhere during execution
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')

    try:
        result = run_generation(
            model=args.model,
            use_placeholder_images=args.placeholder_images,
            batch_size=args.batch_size,
            search_days_back=args.days_back,
            use_langgraph=not args.legacy
        )
    finally:
        # Always restore stdout so we can print the final JSON
        if args.json:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            # Print ONLY the clean summary
            summary = {
                "posts_generated": result.get("posts_generated", 0),
                "posts_failed": result.get("posts_failed", 0),
                "duration_seconds": result.get("duration_seconds", 0)
            }
            print(json.dumps(summary))
            sys.exit(0)  # Ensure clean exit

    # For local runs (no --json): pretty output
    if "final_state" in result:
        clean_result = {k: v for k, v in result.items() if k != "final_state"}
        print(json.dumps(clean_result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, default=str))
