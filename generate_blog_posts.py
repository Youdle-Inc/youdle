#!/usr/bin/env python3
# generate_blog_posts.py
# Main entry point for the blog post generation workflow

import os
import sys
import json
import argparse
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def check_environment(quiet=False):
    """Check that required environment variables are set."""
    required_vars = [
        ("EXA_API_KEY", "Exa search API"),
        ("OPENAI_API_KEY", "OpenAI blog generation")
    ]

    optional_vars = [
        ("GEMINI_API_KEY", "Gemini image generation"),
        ("SUPABASE_URL", "Supabase storage"),
    ]

    missing_required = []
    missing_optional = []

    for var, description in required_vars:
        if not os.getenv(var):
            missing_required.append(f"  - {var}: {description}")

    for var, description in optional_vars:
        if not os.getenv(var):
            missing_optional.append(f"  - {var}: {description}")

    if not (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    ):
        missing_optional.append(
            "  - SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY): Supabase storage"
        )

    if missing_required:
        if not quiet:
            print("ERROR: Missing required environment variables:", file=sys.stderr)
            for var in missing_required:
                print(var, file=sys.stderr)
            print("\nPlease set these variables in your .env file or environment.", file=sys.stderr)
        return False

    if missing_optional and not quiet:
        print("WARNING: Missing optional environment variables:", file=sys.stderr)
        for var in missing_optional:
            print(var, file=sys.stderr)
        print("\nSome features may be limited.\n", file=sys.stderr)

    return True


def main():
    """Main entry point for blog post generation."""
    parser = argparse.ArgumentParser(
        description="Generate blog posts from news articles using AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_blog_posts.py                    # Run with defaults
  python generate_blog_posts.py --model gpt-3.5-turbo  # Use faster model
  python generate_blog_posts.py --placeholder-images   # Skip image generation
  python generate_blog_posts.py --batch-size 50        # Search more articles
        """
    )
    
    parser.add_argument(
        "--model", "-m",
        default="gpt-4",
        help="OpenAI model to use (default: gpt-4)"
    )
    
    parser.add_argument(
        "--placeholder-images", "-p",
        action="store_true",
        help="Use placeholder images instead of Gemini (faster for testing)"
    )
    
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=30,
        help="Number of articles to search (default: 30)"
    )
    
    parser.add_argument(
        "--days-back", "-d",
        type=int,
        default=7,
        help="How far back to search for articles in days (default: 7)"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="blog_posts",
        help="Output directory for generated posts (default: blog_posts)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually generating posts"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use legacy async orchestration instead of LangGraph"
    )
    
    args = parser.parse_args()

    # Check environment
    if not check_environment(quiet=args.json):
        if args.json:
            error_result = {
                "success": False,
                "error": "Missing required environment variables",
                "posts_generated": 0,
                "posts_failed": 0,
                "duration_seconds": 0
            }
            print(json.dumps(error_result, indent=2), flush=True)
        sys.exit(1)

    # Import after environment check (wrapped in try/except for JSON mode)
    try:
        from blog_post_generator import BlogPostOrchestrator, run_generation
    except Exception as e:
        if args.json:
            error_result = {
                "success": False,
                "error": f"Import error: {e}",
                "posts_generated": 0,
                "posts_failed": 0,
                "duration_seconds": 0
            }
            print(json.dumps(error_result, indent=2), flush=True)
        else:
            print(f"\nERROR: Failed to import blog_post_generator: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("DRY RUN MODE - No posts will be generated")
        print(f"\nConfiguration:")
        print(f"  Model: {args.model}")
        print(f"  Batch size: {args.batch_size}")
        print(f"  Days back: {args.days_back}")
        print(f"  Output: {args.output}")
        print(f"  Placeholder images: {args.placeholder_images}")
        
        # Just search and show what would be processed
        from zap_exa_ranker import main as search_articles
        
        print("\nSearching for articles...")
        results = search_articles({
            "batch_size": args.batch_size,
            "search_days_back": args.days_back
        })
        
        items = results.get("items", [])
        recall_items = results.get("recall_items", [])
        
        print(f"\nFound {len(items)} articles, {len(recall_items)} recall items")
        
        print("\nTop shoppers articles:")
        for i, item in enumerate(items[:6], 1):
            print(f"  {i}. {item.get('title', 'Unknown')[:60]}...")
        
        if recall_items:
            print("\nRecall articles:")
            for i, item in enumerate(recall_items[:3], 1):
                print(f"  {i}. {item.get('title', 'Unknown')[:60]}...")
        
        return

    # Run the generation workflow
    if not args.json:
        print("\n" + "=" * 60)
        print("YOUDLE BLOG POST GENERATOR")
        print("=" * 60)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Model: {args.model}")
        print(f"Output: {args.output}/")
        print()

    try:
        result = run_generation(
            model=args.model,
            use_placeholder_images=args.placeholder_images,
            batch_size=args.batch_size,
            search_days_back=args.days_back,
            use_langgraph=not args.legacy
        )

        if args.json:
            # Exclude full state from JSON output for readability
            result_output = {k: v for k, v in result.items() if k != "final_state"}
            print(json.dumps(result_output, indent=2, default=str), flush=True)
        else:
            print("\n" + "=" * 60)
            print("COMPLETE")
            print("=" * 60)

            if result.get("success"):
                # Handle both LangGraph and legacy result formats
                posts_generated = result.get("posts_generated", 0)
                files_saved = result.get("files_saved", result.get("saved_files", []))
                posts_failed = result.get("posts_failed", len(result.get("errors", [])))
                duration = result.get("duration_seconds", 0)
                output_dir = result.get("output_directory", args.output)

                print(f"✓ Generated {posts_generated} blog posts")
                if posts_failed:
                    print(f"✗ Failed: {posts_failed}")
                print(f"⏱ Duration: {duration} seconds")
                print(f"\nFiles saved:")
                for f in files_saved[:5]:
                    print(f"  - {f}")
                if len(files_saved) > 5:
                    print(f"  ... and {len(files_saved) - 5} more")
                print(f"\nNext steps:")
                print(f"  1. Review posts in {output_dir}/")
                print(f"  2. Run: python collect_feedback.py -d {output_dir}")
                print(f"  3. Publish approved posts to Blogger")
            else:
                errors = result.get("errors", [result.get("error", "Unknown error")])
                print(f"✗ Workflow failed:")
                for error in errors[:5]:
                    print(f"  - {error}")
                sys.exit(1)

    except KeyboardInterrupt:
        if args.json:
            # Output valid JSON even on interrupt
            error_result = {
                "success": False,
                "error": "Interrupted by user",
                "posts_generated": 0,
                "posts_failed": 0,
                "duration_seconds": 0
            }
            print(json.dumps(error_result, indent=2), flush=True)
        else:
            print("\n\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        if args.json:
            # Output valid JSON even on error
            error_result = {
                "success": False,
                "error": str(e),
                "posts_generated": 0,
                "posts_failed": 0,
                "duration_seconds": 0
            }
            print(json.dumps(error_result, indent=2), flush=True)
        else:
            print(f"\nERROR: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


