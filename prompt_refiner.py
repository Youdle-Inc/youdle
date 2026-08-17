# prompt_refiner.py
# Automatically refine prompts based on feedback patterns

import os
from typing import Dict, Any, List, Optional
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase_storage import get_supabase_storage, SupabaseStorage


class PromptRefiner:
    """
    Automatically refine prompts based on feedback patterns.
    Tracks prompt versions and their performance.
    """
    
    # Base prompts (these will be refined over time)
    BASE_SHOPPERS_ADDITIONS = []
    BASE_RECALL_ADDITIONS = []
    
    def __init__(self, supabase_client: Optional[SupabaseStorage] = None):
        """
        Initialize the prompt refiner.
        
        Args:
            supabase_client: Optional Supabase client
        """
        self.client = supabase_client or get_supabase_storage()
        self._prompt_versions: Dict[str, List[Dict]] = {
            "shoppers": [],
            "recall": []
        }
        self._current_additions: Dict[str, List[str]] = {
            "shoppers": [],
            "recall": []
        }
    
    def analyze_feedback_patterns(
        self,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze feedback patterns to identify common issues.
        
        Args:
            category: Filter by category (optional)
            
        Returns:
            Analysis results with common issues
        """
        if self.client:
            patterns = self.client.get_feedback_patterns(category=category)
        else:
            patterns = []
        
        common_issues = []
        improvement_suggestions = []
        
        for pattern in patterns:
            avg_score = pattern.get("avg_score", 5)
            ftype = pattern.get("type", "unknown")
            comments = pattern.get("comments", [])
            
            if avg_score < 3:
                common_issues.append({
                    "type": ftype,
                    "severity": "high",
                    "description": f"Low scores in {ftype}"
                })
            elif avg_score < 4:
                common_issues.append({
                    "type": ftype,
                    "severity": "medium",
                    "description": f"Room for improvement in {ftype}"
                })
            
            # Analyze comments for specific issues
            for comment in comments:
                suggestion = self._extract_improvement_suggestion(comment)
                if suggestion:
                    improvement_suggestions.append(suggestion)
        
        return {
            "common_issues": common_issues,
            "improvement_suggestions": list(set(improvement_suggestions)),
            "patterns": patterns
        }
    
    def _extract_improvement_suggestion(self, comment: str) -> Optional[str]:
        """Extract improvement suggestions from feedback comments."""
        comment_lower = comment.lower()
        
        # Common patterns and their fixes
        patterns = {
            "missing link": "Include all four required closing links: Youdle Search, Community, Blog, and the original source",
            "wrong structure": "CRITICAL: Follow the exact HTML structure with <div>, <h2>, <p>, <ul>/<li>",
            "missing image": "Place <img src=\"{IMAGE_HERE}\" alt=\"article image\"/> first inside the outer <div>",
            "word count": "Keep content within the required 400-600 word range",
            "memphis": "Begin first paragraph with: MEMPHIS, Tenn. (Youdle) –",
            "community": "Include the Youdle Community link naturally within the required four-part closing paragraph",
            "list": "Include a <ul> list with <li> items for key details",
            "headline": "Use a single <h2> headline that is punchy and shopper-centric"
        }
        
        for pattern, suggestion in patterns.items():
            if pattern in comment_lower:
                return suggestion
        
        return None
    
    def generate_prompt_additions(
        self,
        category: str = "shoppers"
    ) -> List[str]:
        """
        Generate prompt additions based on feedback analysis.
        
        Args:
            category: 'shoppers' or 'recall'
            
        Returns:
            List of additions to include in prompts
        """
        analysis = self.analyze_feedback_patterns(category)
        
        additions = []
        
        # Add suggestions based on common issues
        for issue in analysis.get("common_issues", []):
            if issue.get("severity") == "high":
                additions.append(f"CRITICAL: Pay special attention to {issue.get('type', 'quality')}")
        
        # Add specific improvement suggestions
        for suggestion in analysis.get("improvement_suggestions", []):
            additions.append(suggestion)
        
        # Get learning insights
        if self.client:
            insights = self.client.get_learning_insights(category=category)
            for insight in insights:
                if insight.get("insight_type") == "common_mistake":
                    additions.append(f"AVOID: {insight.get('description', '')}")
        
        # Cache the additions
        self._current_additions[category.lower()] = additions
        
        return additions
    
    def get_refined_prompt_section(
        self,
        category: str = "shoppers"
    ) -> str:
        """
        Get a refined prompt section to add to base prompts.
        
        Args:
            category: 'shoppers' or 'recall'
            
        Returns:
            String to append to the base prompt
        """
        additions = self._current_additions.get(category.lower(), [])
        
        if not additions:
            additions = self.generate_prompt_additions(category)
        
        if not additions:
            return ""
        
        section = "\n\n--- ADDITIONAL GUIDELINES (Based on Past Feedback) ---\n"
        for i, addition in enumerate(additions[:5], 1):  # Limit to 5
            section += f"{i}. {addition}\n"
        section += "--- END ADDITIONAL GUIDELINES ---\n"
        
        return section
    
    def save_prompt_version(
        self,
        category: str,
        prompt_text: str,
        performance_metrics: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Save a prompt version for tracking.
        
        Args:
            category: 'shoppers' or 'recall'
            prompt_text: The full prompt text
            performance_metrics: Optional metrics (approval_rate, avg_score, etc.)
            
        Returns:
            Result dictionary
        """
        version = len(self._prompt_versions.get(category.lower(), [])) + 1
        
        version_data = {
            "prompt_type": category.lower(),
            "prompt_text": prompt_text,
            "version": version,
            "performance_metrics": performance_metrics or {},
            "created_at": datetime.now().isoformat(),
            "is_active": True
        }
        
        # Deactivate previous versions
        for v in self._prompt_versions.get(category.lower(), []):
            v["is_active"] = False
        
        self._prompt_versions[category.lower()].append(version_data)
        
        # Save to database if available
        if self.client:
            try:
                self.client.client.table("prompt_versions").insert(version_data).execute()
            except Exception as e:
                print(f"Error saving prompt version: {e}")
        
        return {
            "success": True,
            "version": version,
            "category": category
        }
    
    def get_active_prompt_version(
        self,
        category: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the currently active prompt version.
        
        Args:
            category: 'shoppers' or 'recall'
            
        Returns:
            Active prompt version or None
        """
        versions = self._prompt_versions.get(category.lower(), [])
        for v in reversed(versions):
            if v.get("is_active", False):
                return v
        return None
    
    def get_prompt_performance_trend(
        self,
        category: str
    ) -> Dict[str, Any]:
        """
        Get performance trend across prompt versions.
        
        Args:
            category: 'shoppers' or 'recall'
            
        Returns:
            Trend data
        """
        versions = self._prompt_versions.get(category.lower(), [])
        
        if len(versions) < 2:
            return {"trend": "insufficient_data", "versions": len(versions)}
        
        # Calculate trend from metrics
        metrics_over_time = []
        for v in versions:
            metrics = v.get("performance_metrics", {})
            if "avg_score" in metrics:
                metrics_over_time.append(metrics["avg_score"])
        
        if len(metrics_over_time) < 2:
            return {"trend": "no_metrics", "versions": len(versions)}
        
        # Simple trend: compare first half to second half
        mid = len(metrics_over_time) // 2
        first_half_avg = sum(metrics_over_time[:mid]) / mid
        second_half_avg = sum(metrics_over_time[mid:]) / len(metrics_over_time[mid:])
        
        if second_half_avg > first_half_avg + 0.2:
            trend = "improving"
        elif second_half_avg < first_half_avg - 0.2:
            trend = "declining"
        else:
            trend = "stable"
        
        return {
            "trend": trend,
            "versions": len(versions),
            "first_half_avg": round(first_half_avg, 2),
            "second_half_avg": round(second_half_avg, 2)
        }


# For testing
if __name__ == "__main__":
    refiner = PromptRefiner()
    
    print("Testing prompt refiner...")
    
    # Generate additions
    additions = refiner.generate_prompt_additions("shoppers")
    print(f"Generated {len(additions)} prompt additions")
    
    # Get refined section
    section = refiner.get_refined_prompt_section("shoppers")
    print(f"Refined section:\n{section}")
    
    # Save a prompt version
    result = refiner.save_prompt_version(
        category="shoppers",
        prompt_text="Test prompt text",
        performance_metrics={"avg_score": 4.2, "approval_rate": 85}
    )
    print(f"Save result: {result}")



