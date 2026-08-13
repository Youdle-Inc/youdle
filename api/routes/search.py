"""
Search API Routes
Endpoints for article search and preview.
"""
import sys
import os
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

router = APIRouter()


class ArticleItem(BaseModel):
    """Article search result item"""
    title: str
    description: str
    link: str
    pubDate: str
    category: str
    subcategory: Optional[str] = None
    score: float
    feedIndex: int


class SearchResponse(BaseModel):
    """Search results response"""
    items: List[ArticleItem]
    recall_items: List[ArticleItem]
    processed_count: int
    total_ranked_count: int
    shoppers_count: int
    recall_count: int
    timestamp: str


@router.get("/preview", response_model=SearchResponse)
async def preview_search(
    batch_size: int = Query(default=10, ge=1, le=50, description="Number of articles to return"),
    days_back: int = Query(default=30, ge=1, le=90, description="Search articles from the last N days"),
    category: Optional[str] = Query(default=None, description="Filter by category: SHOPPERS or RECALL")
):
    """
    Preview article search results without generating blog posts.
    Useful for testing and viewing what articles would be selected.
    """
    try:
        from zap_exa_ranker import main as search_articles

        result = search_articles({
            "batch_size": batch_size,
            "search_days_back": days_back
        })
        
        # Filter by category if specified
        if category:
            category = category.upper()
            if category in ["SHOPPERS", "RECALL"]:
                result["items"] = [
                    item for item in result["items"] 
                    if item.get("category") == category
                ]
        
        result["timestamp"] = datetime.utcnow().isoformat()
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/article/{article_id}")
async def get_article(article_id: str):
    """
    Get a specific article by ID from the database.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if supabase is None:
            raise HTTPException(status_code=503, detail="Database not configured")
        
        result = supabase.table("articles").select("*").eq("id", article_id).maybe_single().execute()
        
        if result is None or not result.data:
            raise HTTPException(status_code=404, detail="Article not found")
        
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get article: {str(e)}")


@router.get("/recent")
async def get_recent_articles(
    limit: int = Query(default=20, ge=1, le=100),
    category: Optional[str] = Query(default=None)
):
    """
    Get recently searched/processed articles from the database.
    """
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()
        
        query = supabase.table("articles").select("*").order("created_at", desc=True).limit(limit)
        
        if category:
            query = query.eq("category", category.upper())
        
        result = query.execute()
        
        return {
            "articles": result.data if result.data else [],
            "count": len(result.data) if result.data else 0
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get recent articles: {str(e)}")


@router.post("/test-query")
async def test_search_query(
    query: str = Query(..., description="Custom search query to test"),
    num_results: int = Query(default=5, ge=1, le=20)
):
    """
    Test a custom search query against Exa API.
    Useful for debugging and refining search queries.
    """
    try:
        from exa_py import Exa
        import os
        
        exa = Exa(os.getenv("EXA_API_KEY"))
        
        result = exa.search_and_contents(
            query,
            num_results=num_results,
            use_autoprompt=True,
            start_published_date=(datetime.now().replace(day=1)).strftime("%Y-%m-%d"),
            text={"max_characters": 1000}
        )
        
        return {
            "query": query,
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "published_date": r.published_date,
                    "text_preview": r.text[:500] if r.text else None
                }
                for r in result.results
            ],
            "count": len(result.results)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Test query failed: {str(e)}")


