# reflection_agent.py
# Self-reflection agent for evaluating generated blog posts

import os
import re
from typing import Dict, Any, List, Optional

from html_safety import find_unsafe_html_issues

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class ReflectionAgent:
    """
    Self-reflection agent that evaluates generated blog posts
    for compliance with structure and content requirements.
    """
    
    # Required elements for validation
    REQUIRED_ELEMENTS = {
        "div_wrapper": {
            "pattern": r"^\s*<div[^>]*>.*</div>\s*$",
            "description": "Must be wrapped in <div>...</div>",
            "flags": re.DOTALL
        },
        "image_tag": {
            "pattern": r'<img[^>]+src=["\'][^"\']*IMAGE_HERE[^"\']*["\'][^>]*>',
            "description": "Must have image tag with {IMAGE_HERE} placeholder"
        },
        "news_blog_link": {
            "pattern": r'<a[^>]+href=["\']https://news\.youdle\.io/?["\'][^>]*>[^<]*Back\s+to\s+News\s+Blog[^<]*</a>',
            "description": "Must include a Back to News Blog link to news.youdle.io",
            "flags": re.IGNORECASE
        },
        "h2_headline": {
            "pattern": r"<h2[^>]*>.+</h2>",
            "description": "Must have exactly one <h2> headline"
        },
        "memphis_opener": {
            "pattern": r"MEMPHIS,\s*Tenn\.\s*\(Youdle\)\s*[–-]",
            "description": "First paragraph must start with 'MEMPHIS, Tenn. (Youdle) –'"
        },
        "list_elements": {
            "pattern": r"<ul[^>]*>.*<li[^>]*>.*</li>.*</ul>",
            "description": "Must have <ul> with <li> elements",
            "flags": re.DOTALL
        },
        "youdle_link": {
            "pattern": r'<a[^>]+href=["\']https?://(?:www\.)?youdle\.io/?["\'][^>]*>',
            "description": "Must include link to Youdle.io"
        },
        "source_link": {
            "pattern": r'<a[^>]+href=["\'][^"\']+["\'][^>]*>Read the full story</a>',
            "description": "Must include 'Read the full story' source link",
            "flags": re.IGNORECASE
        },
        "community_link": {
            "pattern": r'<a[^>]+href=["\']https?://(?:www\.)?youdle\.io/community["\'][^>]*>.*Community.*</a>',
            "description": "Must include Youdle Community link",
            "flags": re.IGNORECASE | re.DOTALL
        },
        "blog_link": {
            "pattern": r'<a[^>]+href=["\']https?://getyoudle\.com/blog["\'][^>]*>',
            "description": "Must include Youdle Blog link"
        }
    }
    
    # Word count target (updated for 400-600 word requirement)
    TARGET_WORD_COUNT = 500  # Center of 400-600 range
    WORD_COUNT_TOLERANCE = 100  # ±100 words allows 400-600
    
    # Words to never flag as misspelled (brands, proper nouns, abbreviations)
    PRESERVE_WORDS = {
        'youdle', 'getyoudle', 'kroger', 'walmart', 'target', 'costco', 'aldi',
        'publix', 'safeway', 'albertsons', 'wegmans', 'heb', 'meijer', 'trader',
        'instacart', 'doordash', 'grubhub', 'shipt', 'gopuff', 'memphis', 'tenn',
        'fda', 'usda', 'cdc', 'epa', 'snap', 'wic', 'gmo', 'upc', 'upcs',
        'cta', 'html', 'href', 'src', 'alt', 'img', 'div', 'prebiotic',
        'prebiotics', 'probiotic', 'probiotics', 'listeria', 'salmonella',
        'e.coli', 'roundup', 'reformulating', 'reformulated',
    }

    def __init__(self):
        """Initialize the reflection agent."""
        self._spell = None

    def _get_spellchecker(self):
        """Lazy-load the spellchecker."""
        if self._spell is None:
            try:
                from spellchecker import SpellChecker
                self._spell = SpellChecker()
                self._spell.word_frequency.load_words(self.PRESERVE_WORDS)
            except ImportError:
                self._spell = False  # Sentinel: not available
        return self._spell if self._spell is not False else None
    
    def validate_structure(self, html_content: str) -> Dict[str, Any]:
        """
        Validate the HTML structure of a blog post.
        
        Args:
            html_content: Generated HTML blog post
            
        Returns:
            Dictionary with validation results
        """
        results = {
            "is_valid": True,
            "passed": [],
            "failed": [],
            "warnings": []
        }
        
        for element_name, config in self.REQUIRED_ELEMENTS.items():
            pattern = config["pattern"]
            flags = config.get("flags", 0)
            description = config["description"]
            
            if re.search(pattern, html_content, flags):
                results["passed"].append({
                    "element": element_name,
                    "description": description
                })
            else:
                results["failed"].append({
                    "element": element_name,
                    "description": description,
                    "suggestion": f"Add: {description}"
                })
                results["is_valid"] = False
        
        return results
    
    def validate_word_count(self, html_content: str) -> Dict[str, Any]:
        """
        Validate the word count of the blog post.
        
        Args:
            html_content: Generated HTML blog post
            
        Returns:
            Dictionary with word count validation
        """
        # Strip HTML tags to get text content
        text = re.sub(r'<[^>]+>', ' ', html_content)
        text = re.sub(r'\s+', ' ', text).strip()
        word_count = len(text.split())
        
        min_words = self.TARGET_WORD_COUNT - self.WORD_COUNT_TOLERANCE
        max_words = self.TARGET_WORD_COUNT + self.WORD_COUNT_TOLERANCE
        
        is_valid = min_words <= word_count <= max_words
        
        result = {
            "word_count": word_count,
            "target": self.TARGET_WORD_COUNT,
            "min_acceptable": min_words,
            "max_acceptable": max_words,
            "is_valid": is_valid
        }
        
        if not is_valid:
            if word_count < min_words:
                result["suggestion"] = f"Add more content (current: {word_count}, target: ~{self.TARGET_WORD_COUNT})"
            else:
                result["suggestion"] = f"Reduce content (current: {word_count}, target: ~{self.TARGET_WORD_COUNT})"
        
        return result
    
    def check_common_mistakes(
        self,
        html_content: str,
        bad_examples: List[str] = None
    ) -> List[str]:
        """
        Check for common mistakes based on bad examples.
        
        Args:
            html_content: Generated HTML blog post
            bad_examples: List of bad example HTML posts
            
        Returns:
            List of detected issues
        """
        issues = []
        
        # Check for markdown artifacts
        if "```" in html_content:
            issues.append("Contains markdown code block markers")
        if "**" in html_content:
            issues.append("Contains markdown bold markers")
        
        # Check for unwanted HTML elements
        if "<html" in html_content.lower():
            issues.append("Contains <html> tag (should only have <div>)")
        if "<body" in html_content.lower():
            issues.append("Contains <body> tag (should only have <div>)")
        if "<head" in html_content.lower():
            issues.append("Contains <head> tag (should only have <div>)")
        
        # Check for placeholder issues
        if "{original_link}" in html_content:
            issues.append("Contains unreplaced {original_link} placeholder")
        if "{{" in html_content and "}}" in html_content:
            # Check for unintended template variables (except IMAGE_HERE)
            if re.search(r'\{\{(?!IMAGE_HERE)[^}]+\}\}', html_content):
                issues.append("Contains unreplaced template variables")
        
        # Check for empty required elements
        if re.search(r'<h2[^>]*>\s*</h2>', html_content):
            issues.append("Empty <h2> headline")
        if re.search(r'<li[^>]*>\s*</li>', html_content):
            issues.append("Empty <li> elements")
        
        # Check image tag format
        img_match = re.search(r'<img[^>]+>', html_content)
        if img_match:
            img_tag = img_match.group()
            if 'alt=' not in img_tag:
                issues.append("Image tag missing alt attribute")

        news_blog_link = re.search(
            r'<a[^>]+href=["\']https://news\.youdle\.io/?["\'][^>]*>[^<]*Back\s+to\s+News\s+Blog[^<]*</a>',
            html_content,
            re.IGNORECASE,
        )
        if img_match and news_blog_link and news_blog_link.start() > img_match.start():
            issues.append("Back to News Blog link must appear above the article image")

        # Check for duplicate headline text in body (Issue: headline appearing twice)
        h2_match = re.search(r'<h2[^>]*>(.*?)</h2>', html_content, re.DOTALL)
        if h2_match:
            headline_text = re.sub(r'<[^>]+>', '', h2_match.group(1)).strip().lower()
            # Remove the h2 tag from content and check if headline text appears again
            content_without_h2 = html_content[:h2_match.start()] + html_content[h2_match.end():]
            # Strip HTML tags from remaining content for text comparison
            body_text = re.sub(r'<[^>]+>', ' ', content_without_h2).lower()
            if headline_text and len(headline_text) > 10 and headline_text in body_text:
                issues.append("Headline text is repeated in the article body")

        # Check for forbidden "subscribe" / "subscription" language
        if re.search(r'\bsubscri(be|ption|bing)\b', html_content, re.IGNORECASE):
            issues.append("Contains 'subscribe/subscription' — Youdle Blog is a landing page, not a subscription")

        issues.extend(find_unsafe_html_issues(html_content))

        return issues
    
    def check_spelling(self, html_content: str) -> List[str]:
        """
        Check spelling in the text content of an HTML blog post.

        Args:
            html_content: Generated HTML blog post

        Returns:
            List of spelling issue descriptions
        """
        spell = self._get_spellchecker()
        if spell is None:
            return []

        # Strip HTML tags to get text content
        text = re.sub(r'<[^>]+>', ' ', html_content)
        # Remove URLs
        text = re.sub(r'https?://\S+', ' ', text)
        # Extract words (letters and apostrophes only)
        words = re.findall(r"[a-zA-Z']+", text)

        issues = []
        for word in words:
            lower = word.lower()
            # Skip short words, preserve words, and all-caps abbreviations
            if len(lower) <= 2 or lower in self.PRESERVE_WORDS or word.isupper():
                continue
            if lower not in spell:
                correction = spell.correction(lower)
                if correction and correction != lower:
                    issues.append(f"'{word}' → '{correction}'")

        return issues

    def reflect(
        self,
        html_content: str,
        bad_examples: List[str] = None
    ) -> Dict[str, Any]:
        """
        Perform full reflection on a generated blog post.
        
        Args:
            html_content: Generated HTML blog post
            bad_examples: List of bad example HTML posts to avoid
            
        Returns:
            Complete reflection result
        """
        # Validate structure
        structure_result = self.validate_structure(html_content)
        
        # Validate word count
        word_count_result = self.validate_word_count(html_content)
        
        # Check common mistakes
        common_mistakes = self.check_common_mistakes(html_content, bad_examples)

        # Check spelling
        spelling_issues = self.check_spelling(html_content)

        # Compile issues and suggestions
        issues = []
        suggestions = []

        for failed in structure_result["failed"]:
            issues.append(failed["description"])
            suggestions.append(failed["suggestion"])

        if not word_count_result["is_valid"]:
            issues.append(f"Word count issue: {word_count_result['word_count']} words")
            suggestions.append(word_count_result.get("suggestion", ""))

        issues.extend(common_mistakes)

        if spelling_issues:
            issues.append(f"Spelling errors found: {'; '.join(spelling_issues)}")
            suggestions.append(f"Fix spelling: {'; '.join(spelling_issues)}")

        # Determine overall validity
        is_valid = (
            structure_result["is_valid"] and
            word_count_result["is_valid"] and
            len(common_mistakes) == 0 and
            len(spelling_issues) == 0
        )

        return {
            "is_valid": is_valid,
            "structure": structure_result,
            "word_count": word_count_result,
            "common_mistakes": common_mistakes,
            "spelling_issues": spelling_issues,
            "issues": issues,
            "suggestions": suggestions,
            "summary": self._create_summary(is_valid, issues)
        }
    
    def _create_summary(self, is_valid: bool, issues: List[str]) -> str:
        """Create a human-readable summary of the reflection."""
        if is_valid:
            return "Blog post meets all requirements."
        else:
            issue_count = len(issues)
            return f"Blog post has {issue_count} issue(s): {'; '.join(issues[:3])}"
    
    def should_regenerate(self, reflection_result: Dict[str, Any]) -> bool:
        """
        Determine if the blog post should be regenerated.
        
        Args:
            reflection_result: Result from reflect()
            
        Returns:
            True if regeneration is recommended
        """
        # The reflection result already combines structure, the canonical
        # 400-600 word range, deterministic mistakes, and spelling. Keep the
        # retry decision aligned with that single validity contract.
        return not reflection_result.get("is_valid", False)
    
    def get_regeneration_hints(
        self,
        reflection_result: Dict[str, Any]
    ) -> str:
        """
        Get hints for regeneration based on reflection.
        
        Args:
            reflection_result: Result from reflect()
            
        Returns:
            String of hints to include in regeneration prompt
        """
        hints = []
        
        for issue in reflection_result["issues"]:
            hints.append(f"- Fix: {issue}")
        
        for suggestion in reflection_result["suggestions"]:
            if suggestion:
                hints.append(f"- {suggestion}")
        
        return "\n".join(hints) if hints else "No specific hints."


# For testing
if __name__ == "__main__":
    agent = ReflectionAgent()
    
    # Test with a sample blog post
    test_html = """
    <div>
        <img src="{IMAGE_HERE}" alt="article image"/>
        <h2>Test Headline</h2>
        <p>MEMPHIS, Tenn. (Youdle) – This is a test paragraph with some content about grocery shopping and products.</p>
        <p>More content here to pad out the word count for testing purposes.</p>
        <ul>
            <li>Item 1</li>
            <li>Item 2</li>
        </ul>
        <p>Check out <a href="https://www.youdle.io/">Youdle</a> for more.</p>
        <p><a href="https://example.com/article">More information</a></p>
        <p>Share your thoughts in the <a href="https://www.youdle.io/community">Youdle Community!</a></p>
    </div>
    """
    
    print("Testing reflection agent...")
    result = agent.reflect(test_html)
    
    print(f"\nIs Valid: {result['is_valid']}")
    print(f"Summary: {result['summary']}")
    print(f"\nWord Count: {result['word_count']['word_count']}")
    print(f"Issues: {result['issues']}")
    print(f"Should Regenerate: {agent.should_regenerate(result)}")



