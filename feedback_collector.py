# feedback_collector.py
# Collect and store human feedback on generated blog posts

import os
from typing import Dict, Any, List, Optional
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase_storage import (
    SupabaseStorage,
    get_supabase_storage,
    normalize_feedback_type,
)
from example_store import ExampleStore


class FeedbackCollector:
    """
    Collect and store human feedback on generated blog posts.
    Integrates with the learning system.
    """
    
    FEEDBACK_TYPES = ["structure", "content", "tone", "completeness", "general"]
    
    def __init__(self, supabase_client: Optional[SupabaseStorage] = None):
        """
        Initialize the feedback collector.
        
        Args:
            supabase_client: Optional SupabaseStorage instance
        """
        self.client = (
            supabase_client
            if supabase_client is not None
            else get_supabase_storage()
        )
        self.example_store = ExampleStore(self.client)
        self._local_feedback: List[Dict] = []
    
    def collect_feedback(
        self,
        blog_post_id: str,
        blog_post_html: str,
        article_data: Dict[str, Any],
        score: int,
        approved: bool,
        feedback_type: str = "overall",
        comments: str = "",
        reviewer_notes: str = ""
    ) -> Dict[str, Any]:
        """
        Collect feedback on a blog post.
        
        Args:
            blog_post_id: Unique ID of the blog post
            blog_post_html: The generated HTML content
            article_data: Original article data
            score: Quality score (1-5)
            approved: Whether the post was approved for publication
            feedback_type: Type of feedback
            comments: Feedback comments
            reviewer_notes: Additional notes from reviewer
            
        Returns:
            Result dictionary
        """
        feedback_type = normalize_feedback_type(feedback_type)
        
        category = article_data.get("category", "shoppers").lower()

        # Store feedback
        feedback_result = self._store_feedback(
            blog_post_id=blog_post_id,
            feedback_type=feedback_type,
            score=score,
            comments=comments,
            approved=approved,
            reviewer_notes=reviewer_notes,
            category=category,
        )
        
        # Store as example for learning
        is_good = score >= 4 and approved
        
        example_result = self.example_store.store_example(
            original_article_url=article_data.get("link", ""),
            original_article_title=article_data.get("title", ""),
            generated_html=blog_post_html,
            category=category,
            feedback_score=score,
            feedback_comments=comments,
            is_good_example=is_good
        )
        
        feedback_stored = feedback_result.get("success", False)
        example_stored = example_result.get("success", False)
        response = {
            "success": feedback_stored and example_stored,
            "feedback_stored": feedback_stored,
            "example_stored": example_stored,
            "is_good_example": is_good,
            "approved": approved
        }
        errors = [
            result.get("error", "Learning data was not stored")
            for result in (feedback_result, example_result)
            if not result.get("success", False)
        ]
        if errors:
            response["errors"] = errors
        return response
    
    def _store_feedback(
        self,
        blog_post_id: str,
        feedback_type: str,
        score: int,
        comments: str,
        approved: bool,
        reviewer_notes: str,
        category: str,
    ) -> Dict[str, Any]:
        """Store feedback in database or local cache."""
        if self.client:
            return self.client.save_feedback(
                blog_post_id=blog_post_id,
                feedback_type=feedback_type,
                score=score,
                comments=comments,
                approved=approved,
                reviewer_notes=reviewer_notes,
                category=category,
            )
        else:
            feedback = {
                "blog_post_id": blog_post_id,
                "feedback_type": feedback_type,
                "score": score,
                "comments": comments,
                "approved": approved,
                "reviewer_notes": reviewer_notes,
                "category": category,
                "created_at": datetime.now().isoformat()
            }
            self._local_feedback.append(feedback)
            return {"success": True, "cached": True}
    
    def get_feedback_summary(
        self,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get a summary of collected feedback.
        
        Args:
            category: Filter by category (optional)
            
        Returns:
            Summary dictionary with counts and averages
        """
        if self.client:
            patterns = self.client.get_feedback_patterns(category=category)
        else:
            patterns = self._analyze_local_feedback()
        
        total_feedback = sum(p.get("count", 0) for p in patterns)
        avg_score = (
            sum(p.get("avg_score", 0) * p.get("count", 0) for p in patterns) / total_feedback
            if total_feedback > 0 else 0
        )
        
        return {
            "total_feedback": total_feedback,
            "average_score": round(avg_score, 2),
            "patterns": patterns,
            "common_issues": self._extract_common_issues(patterns)
        }
    
    def _analyze_local_feedback(self) -> List[Dict[str, Any]]:
        """Analyze local feedback cache."""
        patterns = {}
        for feedback in self._local_feedback:
            ftype = feedback.get("feedback_type", "unknown")
            if ftype not in patterns:
                patterns[ftype] = {
                    "type": ftype,
                    "count": 0,
                    "avg_score": 0,
                    "comments": []
                }
            patterns[ftype]["count"] += 1
            patterns[ftype]["avg_score"] += feedback.get("score", 0)
            if feedback.get("comments"):
                patterns[ftype]["comments"].append(feedback["comments"])
        
        # Calculate averages
        for ftype, data in patterns.items():
            if data["count"] > 0:
                data["avg_score"] = data["avg_score"] / data["count"]
        
        return list(patterns.values())
    
    def _extract_common_issues(
        self,
        patterns: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract common issues from feedback patterns."""
        issues = []
        
        for pattern in patterns:
            if pattern.get("avg_score", 5) < 3:
                issues.append(f"Low score in {pattern.get('type', 'unknown')}")
            
            # Analyze comments for common keywords
            comments = pattern.get("comments", [])
            for comment in comments:
                comment_lower = comment.lower()
                if "missing" in comment_lower:
                    issues.append(f"Missing elements: {comment}")
                if "structure" in comment_lower:
                    issues.append(f"Structure issue: {comment}")
                if "link" in comment_lower:
                    issues.append(f"Link issue: {comment}")
        
        # Deduplicate
        return list(set(issues))[:10]
    
    def get_approval_rate(self) -> float:
        """
        Get the overall approval rate.
        
        Returns:
            Approval rate as percentage (0-100)
        """
        if self.client:
            # Would need a specific query for this
            # For now, use patterns
            patterns = self.client.get_feedback_patterns()
            total = sum(p.get("count", 0) for p in patterns)
            # Approximate based on average scores
            approved = sum(
                p.get("count", 0) for p in patterns 
                if p.get("avg_score", 0) >= 4
            )
            return (approved / total * 100) if total > 0 else 0
        else:
            total = len(self._local_feedback)
            approved = sum(1 for f in self._local_feedback if f.get("approved", False))
            return (approved / total * 100) if total > 0 else 0


# For testing
if __name__ == "__main__":
    collector = FeedbackCollector()
    
    print("Testing feedback collector...")
    
    # Collect test feedback
    result = collector.collect_feedback(
        blog_post_id="test-123",
        blog_post_html="<div><h2>Test</h2><p>Content</p></div>",
        article_data={
            "title": "Test Article",
            "link": "https://example.com/article",
            "category": "shoppers"
        },
        score=4,
        approved=True,
        feedback_type="overall",
        comments="Good structure"
    )
    
    print(f"Collection result: {result}")
    
    # Get summary
    summary = collector.get_feedback_summary()
    print(f"Feedback summary: {summary}")



