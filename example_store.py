# example_store.py
# Store and retrieve blog post examples for few-shot learning

import os
from typing import List, Dict, Any, Optional
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase_storage import get_supabase_storage, SupabaseStorage


class ExampleStore:
    """
    Store and retrieve blog post examples for few-shot learning.
    Uses Supabase for persistence.
    """
    
    def __init__(self, supabase_client: Optional[SupabaseStorage] = None):
        """
        Initialize the example store.
        
        Args:
            supabase_client: Optional Supabase client (creates one if not provided)
        """
        self.client = (
            supabase_client
            if supabase_client is not None
            else get_supabase_storage()
        )
        self._local_cache: Dict[str, List[Dict]] = {
            "shoppers_good": [],
            "shoppers_bad": [],
            "recall_good": [],
            "recall_bad": []
        }
    
    def store_example(
        self,
        original_article_url: str,
        original_article_title: str,
        generated_html: str,
        category: str,
        feedback_score: int,
        feedback_comments: str = "",
        is_good_example: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Store a blog post example.
        
        Args:
            original_article_url: URL of source article
            original_article_title: Title of source article
            generated_html: Generated HTML blog post
            category: 'shoppers' or 'recall'
            feedback_score: Quality score (1-5)
            feedback_comments: Reviewer comments
            is_good_example: Whether this is a good example (auto-determined if None)
            
        Returns:
            Result dictionary
        """
        # Auto-determine if good example based on score
        if is_good_example is None:
            is_good_example = feedback_score >= 4
        
        if self.client:
            return self.client.save_blog_example(
                original_article_url=original_article_url,
                original_article_title=original_article_title,
                generated_html=generated_html,
                category=category,
                feedback_score=feedback_score,
                feedback_comments=feedback_comments,
                is_good_example=is_good_example
            )
        else:
            # Use local cache if no Supabase client
            cache_key = f"{category.lower()}_{'good' if is_good_example else 'bad'}"
            example = {
                "original_article_url": original_article_url,
                "original_article_title": original_article_title,
                "generated_html": generated_html,
                "category": category.lower(),
                "feedback_score": feedback_score,
                "feedback_comments": feedback_comments,
                "is_good_example": is_good_example,
                "created_at": datetime.now().isoformat()
            }
            self._local_cache[cache_key].append(example)
            return {"success": True, "cached": True}
    
    def get_good_examples(
        self,
        category: str,
        limit: int = 3
    ) -> List[str]:
        """
        Get good examples for a category.
        
        Args:
            category: 'shoppers' or 'recall'
            limit: Maximum number of examples
            
        Returns:
            List of HTML blog post examples
        """
        if self.client:
            examples = self.client.get_examples_by_category(
                category=category,
                is_good=True,
                limit=limit
            )
            return [e["generated_html"] for e in examples]
        else:
            cache_key = f"{category.lower()}_good"
            return [
                e["generated_html"] 
                for e in self._local_cache[cache_key][:limit]
            ]
    
    def get_bad_examples(
        self,
        category: str,
        limit: int = 2
    ) -> List[str]:
        """
        Get bad examples for a category (to avoid).
        
        Args:
            category: 'shoppers' or 'recall'
            limit: Maximum number of examples
            
        Returns:
            List of HTML blog post examples to avoid
        """
        if self.client:
            examples = self.client.get_examples_by_category(
                category=category,
                is_good=False,
                limit=limit
            )
            return [e["generated_html"] for e in examples]
        else:
            cache_key = f"{category.lower()}_bad"
            return [
                e["generated_html"] 
                for e in self._local_cache[cache_key][:limit]
            ]
    
    def get_examples_for_generation(
        self,
        category: str,
        good_limit: int = 3,
        bad_limit: int = 2
    ) -> Dict[str, List[str]]:
        """
        Get both good and bad examples for blog post generation.
        
        Args:
            category: 'shoppers' or 'recall'
            good_limit: Maximum good examples
            bad_limit: Maximum bad examples
            
        Returns:
            Dictionary with 'good' and 'bad' example lists
        """
        return {
            "good": self.get_good_examples(category, good_limit),
            "bad": self.get_bad_examples(category, bad_limit)
        }
    
    def has_examples(self, category: str) -> bool:
        """
        Check if examples exist for a category.
        
        Args:
            category: 'shoppers' or 'recall'
            
        Returns:
            True if examples exist
        """
        if self.client:
            examples = self.client.get_examples_by_category(category, limit=1)
            return len(examples) > 0
        else:
            good_key = f"{category.lower()}_good"
            bad_key = f"{category.lower()}_bad"
            return len(self._local_cache[good_key]) > 0 or len(self._local_cache[bad_key]) > 0


def retrieve_similar_examples(
    article: Dict[str, Any],
    category: str = "shoppers",
    good_limit: int = 3,
    bad_limit: int = 2
) -> Dict[str, List[str]]:
    """
    Retrieve similar examples for an article.
    
    This is a convenience function for use in the blog generation chain.
    
    Args:
        article: Article dictionary (not currently used for similarity)
        category: 'shoppers' or 'recall'
        good_limit: Maximum good examples
        bad_limit: Maximum bad examples
        
    Returns:
        Dictionary with 'good' and 'bad' example lists
    """
    store = ExampleStore()
    return store.get_examples_for_generation(
        category=category,
        good_limit=good_limit,
        bad_limit=bad_limit
    )


# For testing
if __name__ == "__main__":
    store = ExampleStore()
    
    print("Testing example store...")
    
    # Store a test example
    result = store.store_example(
        original_article_url="https://example.com/article",
        original_article_title="Test Article",
        generated_html="<div><h2>Test</h2><p>Content</p></div>",
        category="shoppers",
        feedback_score=5,
        feedback_comments="Great example"
    )
    
    print(f"Store result: {result}")
    
    # Retrieve examples
    examples = store.get_examples_for_generation("shoppers")
    print(f"Good examples: {len(examples['good'])}")
    print(f"Bad examples: {len(examples['bad'])}")



