# supabase_storage.py
# Supabase integration for image storage and database operations

import os
import base64
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client, Client

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================================
# CONFIGURATION
# ============================================================================

STORAGE_BUCKET = "blog-images"
DEFAULT_FOLDER = "newsletter"

BLOG_FEEDBACK_TYPES = frozenset({
    "structure",
    "content",
    "tone",
    "completeness",
    "general",
})
FEEDBACK_PATTERN_TYPES = BLOG_FEEDBACK_TYPES | frozenset({"formatting", "accuracy"})
LEARNING_INSIGHT_TYPES = frozenset({
    "common_mistake",
    "improvement_pattern",
    "best_practice",
    "user_preference",
    "general",
})


def normalize_feedback_type(feedback_type: str) -> str:
    """Return a feedback type accepted by the ``blog_feedback`` schema."""
    normalized = str(feedback_type or "").strip().lower()
    if normalized == "overall":
        normalized = "general"
    return normalized if normalized in BLOG_FEEDBACK_TYPES else "general"


def normalize_feedback_pattern_type(feedback_type: str) -> str:
    """Normalize feedback read from either supported feedback table."""
    normalized = str(feedback_type or "").strip().lower()
    if normalized == "overall":
        normalized = "general"
    return normalized if normalized in FEEDBACK_PATTERN_TYPES else "general"


def normalize_insight_type(insight_type: str) -> str:
    """Return an insight type accepted by the ``learning_insights`` schema."""
    normalized = str(insight_type or "").strip().lower()
    if normalized == "problem":
        normalized = "common_mistake"
    return normalized if normalized in LEARNING_INSIGHT_TYPES else "general"


class SupabaseStorage:
    """Supabase client for image storage and database operations."""
    
    def __init__(
        self, 
        url: Optional[str] = None, 
        key: Optional[str] = None
    ):
        """
        Initialize Supabase client.
        
        Args:
            url: Supabase project URL (defaults to SUPABASE_URL env var)
            key: Server-side Supabase key (defaults to
                SUPABASE_SERVICE_ROLE_KEY, then legacy SUPABASE_KEY)
        """
        self.url = url or os.getenv("SUPABASE_URL")
        # Prefer a server-only service-role credential. SUPABASE_KEY remains a
        # compatibility fallback for existing deployments.
        self.key = (
            key
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_KEY")
        )
        
        if not self.url or not self.key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set"
            )
        
        self.client: Client = create_client(self.url, self.key)
        self.bucket = STORAGE_BUCKET
        self._bucket_ready = False
    
    def _ensure_bucket_exists(self) -> bool:
        """Ensure the storage bucket exists."""
        if self._bucket_ready:
            return True
        try:
            # List buckets to check if ours exists
            buckets = self.client.storage.list_buckets()
            bucket_names = [b.name for b in buckets]
            
            if self.bucket not in bucket_names:
                # Create bucket
                self.client.storage.create_bucket(
                    self.bucket,
                    options={"public": True}
                )
            self._bucket_ready = True
            return True
        except Exception as e:
            print(f"Error ensuring bucket exists: {e}")
            return False
    
    def upload_image(
        self,
        image_data: str,
        filename: str,
        folder: str = DEFAULT_FOLDER,
        content_type: str = "image/png"
    ) -> Dict[str, Any]:
        """
        Upload an image to Supabase storage.
        
        Args:
            image_data: Base64 encoded image data
            filename: Name for the file
            folder: Folder path in bucket
            content_type: MIME type of the image
            
        Returns:
            Dictionary with success status and public URL
        """
        try:
            # Ensure bucket exists
            if not self._ensure_bucket_exists():
                raise RuntimeError(f"Storage bucket '{self.bucket}' is unavailable")
            
            # Decode base64 data
            image_bytes = base64.b64decode(image_data)
            
            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            full_path = f"{folder}/{timestamp}_{filename}"
            
            # Upload to storage
            result = self.client.storage.from_(self.bucket).upload(
                path=full_path,
                file=image_bytes,
                file_options={"content-type": content_type}
            )
            
            # Get public URL
            public_url = self.client.storage.from_(self.bucket).get_public_url(full_path)
            
            return {
                "success": True,
                "url": public_url,
                "path": full_path,
                "filename": filename
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "filename": filename
            }
    
    async def upload_images_concurrent(
        self,
        images: List[Dict[str, Any]],
        folder: str = DEFAULT_FOLDER,
        max_workers: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Upload multiple images concurrently.
        
        Args:
            images: List of dicts with image_data, filename, and optional content_type
            folder: Folder path in bucket
            max_workers: Maximum concurrent uploads
            
        Returns:
            List of upload results
        """
        loop = asyncio.get_event_loop()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            tasks = [
                loop.run_in_executor(
                    executor,
                    lambda img=img: self.upload_image(
                        image_data=img["image_data"],
                        filename=img["filename"],
                        folder=folder,
                        content_type=img.get("content_type", "image/png")
                    )
                )
                for img in images
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "success": False,
                    "error": str(result),
                    "filename": images[i].get("filename", f"image_{i}")
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    # ========================================================================
    # DATABASE OPERATIONS FOR LEARNING SYSTEM
    # ========================================================================
    
    def save_blog_example(
        self,
        original_article_url: str,
        original_article_title: str,
        generated_html: str,
        category: str,
        feedback_score: int = 0,
        feedback_comments: str = "",
        is_good_example: bool = True
    ) -> Dict[str, Any]:
        """
        Save a blog post example to the database for learning.
        
        Args:
            original_article_url: URL of the source article
            original_article_title: Title of the source article
            generated_html: Generated HTML blog post
            category: 'shoppers' or 'recall'
            feedback_score: Quality score (1-5)
            feedback_comments: Reviewer comments
            is_good_example: Whether this is a good example to learn from
            
        Returns:
            Result dictionary
        """
        try:
            data = {
                "original_article_url": original_article_url,
                "original_article_title": original_article_title,
                "generated_html": generated_html,
                "category": category.lower(),
                "feedback_score": feedback_score,
                "feedback_comments": feedback_comments,
                "is_good_example": is_good_example,
                "created_at": datetime.now().isoformat()
            }
            
            result = self.client.table("blog_examples").insert(data).execute()

            if not result.data:
                return {
                    "success": False,
                    "error": "Supabase did not return the saved blog example row",
                }
            
            return {
                "success": True,
                "id": result.data[0]["id"] if result.data else None,
                "data": result.data
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_examples_by_category(
        self,
        category: str,
        is_good: Optional[bool] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve blog post examples by category.
        
        Args:
            category: 'shoppers' or 'recall'
            is_good: Filter by good/bad examples (None for all)
            limit: Maximum number of examples to return
            
        Returns:
            List of example records
        """
        try:
            query = self.client.table("blog_examples").select("*").eq(
                "category", category.lower()
            )
            
            if is_good is not None:
                query = query.eq("is_good_example", is_good)
            
            result = query.order(
                "feedback_score", desc=True
            ).limit(limit).execute()
            
            return result.data or []
            
        except Exception as e:
            print(f"Error fetching examples: {e}")
            return []
    
    def save_feedback(
        self,
        blog_post_id: str,
        feedback_type: str,
        score: int,
        comments: str = "",
        approved: bool = False,
        reviewer_notes: str = "",
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Save feedback for a blog post.
        
        Args:
            blog_post_id: ID of the blog post
            feedback_type: Type of feedback (structure, content, tone, completeness)
            score: Quality score (1-5)
            comments: Feedback comments
            approved: Whether the post was approved
            reviewer_notes: Additional reviewer notes
            category: Optional shoppers/recall category for scoped learning
            
        Returns:
            Result dictionary
        """
        try:
            normalized_feedback_type = normalize_feedback_type(feedback_type)
            data = {
                "blog_post_id": blog_post_id,
                "feedback_type": normalized_feedback_type,
                "score": score,
                "comments": comments,
                "approved": approved,
                "reviewer_notes": reviewer_notes,
                "created_at": datetime.now().isoformat()
            }
            if category:
                data["category"] = category.lower()
            
            result = self.client.table("blog_feedback").insert(data).execute()

            if not result.data:
                return {
                    "success": False,
                    "error": "Supabase did not return the saved blog feedback row",
                }
            
            return {
                "success": True,
                "id": result.data[0]["id"] if result.data else None,
                "data": result.data
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_feedback_patterns(
        self,
        category: Optional[str] = None,
        min_count: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Get common feedback patterns for learning.
        
        Args:
            category: Filter by category (optional)
            min_count: Minimum occurrences to be considered a pattern
            
        Returns:
            List of feedback patterns
        """
        try:
            # Detailed CLI feedback lives in blog_feedback, while dashboard
            # reviews live in feedback. Read both so the learning workflow sees
            # every human review instead of silently ignoring dashboard input.
            feedback_rows = []
            query_errors = []
            for table_name in ("blog_feedback", "feedback"):
                try:
                    query = self.client.table(table_name).select("*")
                    if category:
                        query = query.eq("category", category.lower())
                    result = query.order(
                        "created_at", desc=True
                    ).limit(100).execute()
                    feedback_rows.extend(result.data or [])
                except Exception as query_error:
                    query_errors.append(f"{table_name}: {query_error}")

            if not feedback_rows and len(query_errors) == 2:
                raise RuntimeError("; ".join(query_errors))

            patterns = {}
            for feedback in feedback_rows:
                ftype = normalize_feedback_pattern_type(
                    feedback.get("feedback_type", "general")
                )
                if ftype not in patterns:
                    patterns[ftype] = {
                        "type": ftype,
                        "count": 0,
                        "avg_score": 0,
                        "comments": []
                    }
                patterns[ftype]["count"] += 1
                patterns[ftype]["avg_score"] += feedback.get(
                    "score", feedback.get("rating", 0)
                )
                comment_text = feedback.get("comments", feedback.get("comment", ""))
                if comment_text:
                    patterns[ftype]["comments"].append(comment_text)
            
            # Calculate averages and filter by min_count
            result_patterns = []
            for ftype, data in patterns.items():
                if data["count"] >= min_count:
                    data["avg_score"] = data["avg_score"] / data["count"]
                    result_patterns.append(data)
            
            return result_patterns
            
        except Exception as e:
            print(f"Error fetching feedback patterns: {e}")
            raise RuntimeError("Could not load feedback patterns") from e
    
    def save_learning_insight(
        self,
        insight_type: str,
        description: str,
        category: str = "",
        frequency: int = 1
    ) -> Dict[str, Any]:
        """
        Save a learning insight.
        
        Args:
            insight_type: Type of insight (common_mistake, improvement_pattern, etc.)
            description: Description of the insight
            category: Related category
            frequency: How often this pattern occurs
            
        Returns:
            Result dictionary
        """
        try:
            normalized_insight_type = normalize_insight_type(insight_type)
            data = {
                "insight_type": normalized_insight_type,
                "description": description,
                "category": category,
                "frequency": max(1, int(frequency)),
                "created_at": datetime.now().isoformat()
            }
            
            result = self.client.table("learning_insights").insert(data).execute()

            if not result.data:
                return {
                    "success": False,
                    "error": "Supabase did not return the saved learning insight row",
                }
            
            return {
                "success": True,
                "id": result.data[0]["id"] if result.data else None
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_learning_insights(
        self,
        insight_type: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get learning insights.
        
        Args:
            insight_type: Filter by insight type
            category: Filter by category
            limit: Maximum number of insights
            
        Returns:
            List of insights
        """
        try:
            query = self.client.table("learning_insights").select("*")
            
            if insight_type:
                query = query.eq("insight_type", insight_type)
            if category:
                query = query.eq("category", category)
            
            result = query.order(
                "frequency", desc=True
            ).limit(limit).execute()
            
            return result.data or []
            
        except Exception as e:
            print(f"Error fetching insights: {e}")
            return []


def get_supabase_client() -> Optional[Client]:
    """
    Get a Supabase client instance.

    Returns:
        Supabase Client instance or None if credentials not set
    """
    try:
        storage = SupabaseStorage()
        return storage.client
    except ValueError as e:
        print(f"Warning: {e}")
        return None


def get_supabase_storage() -> Optional[SupabaseStorage]:
    """
    Get a Supabase storage client instance.

    Returns:
        SupabaseStorage instance or None if credentials not set
    """
    try:
        return SupabaseStorage()
    except ValueError as e:
        print(f"Warning: {e}")
        return None


# For testing
if __name__ == "__main__":
    # Test the Supabase client
    client = get_supabase_client()
    
    if client:
        print("Supabase client initialized successfully")
        
        # Test upload with a simple placeholder
        test_data = base64.b64encode(b"test image data").decode('utf-8')
        result = client.upload_image(
            image_data=test_data,
            filename="test_image.txt"
        )
        
        print(f"Upload result: {result}")
    else:
        print("Could not initialize Supabase client")



