# image_generator.py
# Google Gemini-powered image generation for Youdle blog posts
# Uses the new google-genai SDK for image generation

import os
import base64
import hashlib
import re
from typing import Optional, Dict, Any, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import the new google-genai SDK
genai_client = None
genai_types = None
try:
    from google import genai
    from google.genai import types as genai_types
    genai_client = genai
except ImportError:
    pass


# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_IMAGE_SIZE = "1K"  # Options: "1K", "2K", "4K"
DEFAULT_ASPECT_RATIO = "16:9"

IMAGE_PROMPT_TEMPLATE = """Photograph for a grocery news article.

Headline: "{title}"

What to show: {theme}

Render that subject with unbranded packaging and no logos or wordmarks, even if
the line above names a brand.

Treatment: {look}

Hard rules:
- No recognisable people. A hand or a silhouette is fine; no faces.
- No real brand names, logos or wordmarks. Packaging is generic.
- Any text in frame is English, short, and plausible: a shelf label, a price, a
  receipt line. No paragraphs, no invented statistics.
- One subject. A reader should know what the story is about at a glance.

Leave room to be interesting: negative space, an off-centre crop, hard light or
deep shadow are all welcome where they suit the subject. Do not default to a
glossy catalogue shot.
"""



class ImageGenerator:
    """Google Gemini-powered image generator using the new google-genai SDK."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the image generator.

        Args:
            api_key: Google Gemini API key (defaults to GEMINI_API_KEY env var)
        """
        if genai_client is None:
            raise ImportError(
                "google-genai SDK not available. "
                "Install it with `pip install google-genai`"
            )

        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")

        # Initialize the new client
        self.client = genai_client.Client(api_key=self.api_key)
        self.model_name = "gemini-3-pro-image-preview"

    # One fixed style block gave every image the same hero-object-on-a-board
    # look, so a week of posts read as a set even where subjects differed.
    # Each article draws a deterministic variant: the same article always
    # renders the same way, neighbours in a batch do not.
    # Six whole looks, not three dropdowns.
    #
    # The previous version mixed a surface, a light and an angle at random,
    # which produced a setting but never an idea: ninety-six combinations of
    # "soft diffused daylight on a weathered board" are ninety-six bland
    # photographs. Each entry here is one coherent treatment a photo editor
    # would recognise, and the model that reads the article is asked to come up
    # with a specific image inside it.
    STYLE_LOOKS = (
        "Documentary, shelf level. Shot in a real store aisle on an ordinary "
        "day, available light, slight imperfection welcome. Nothing styled.",

        "Studio product hero. Single subject on a seamless backdrop, one hard "
        "key light, a defined shadow, generous empty space around it.",

        "Overhead flat-lay. Looking straight down, objects arranged "
        "deliberately with a few supporting props, even light, tight crop.",

        "Macro texture. Very close on the surface of the subject so the "
        "material fills the frame, shallow focus, the object barely "
        "identifiable at first glance.",

        "Wide and quiet. The subject small in a large frame, a lot of empty "
        "space, cool even light. Scale and absence do the work.",

        "Graphic still life. Strong colour blocking, geometric arrangement, "
        "high contrast, a price tag or receipt used as a compositional "
        "element rather than a label.",
    )

    @classmethod
    def look_for(cls, index: int, seed: str = "") -> str:
        """Pick a treatment for position ``index`` in a batch.

        Rotating by position rather than hashing each title independently is
        what stops two posts in the same run sharing a look by chance: a batch
        of six gets six different treatments. The seed offsets where the
        rotation starts, so consecutive weeks do not open the same way.
        """
        offset = 0
        if seed:
            offset = hashlib.sha1(seed.encode("utf-8", "ignore")).digest()[0]
        return cls.STYLE_LOOKS[(offset + index) % len(cls.STYLE_LOOKS)]


    def _create_image_prompt(
        self,
        title: str,
        theme: str = "",
        look: Optional[str] = None,
    ) -> str:
        """Create the prompt for one image."""
        effective_theme = theme
        if not effective_theme:
            effective_theme = (
                f"Whatever this headline is about, shown concretely: {title}"
            )
        return IMAGE_PROMPT_TEMPLATE.format(
            title=title,
            theme=effective_theme,
            look=look or self.look_for(0, title),
        )


    def generate_image(
        self,
        title: str,
        theme: str = "",
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        image_size: str = DEFAULT_IMAGE_SIZE,
        look: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate an image for a blog post.

        Args:
            title: Blog post title
            theme: Additional theme/context for the image
            aspect_ratio: Image aspect ratio (e.g., "16:9", "1:1")
            image_size: Resolution ("1K", "2K", "4K")

        Returns:
            Dictionary with image_data (base64), format, and metadata
        """
        prompt = self._create_image_prompt(title, theme, look)

        try:
            print(f"[ImageGenerator] Generating image with model: {self.model_name}", flush=True)
            print(f"[ImageGenerator] Prompt: {prompt[:80]}...", flush=True)

            # Use the new google-genai API
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=genai_types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size
                    )
                )
            )

            # Debug: Print response structure
            part_types = []
            if hasattr(response, 'parts') and response.parts:
                for part in response.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        part_types.append("IMAGE")
                    elif hasattr(part, 'text') and part.text:
                        part_types.append("TEXT")
            print(f"[ImageGenerator] Response parts: {part_types if part_types else 'none'}", flush=True)

            # Extract image from response parts
            if hasattr(response, 'parts') and response.parts:
                for part in response.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        # Get the image bytes from inline_data
                        image_bytes = part.inline_data.data
                        # Handle if already bytes or needs encoding
                        if isinstance(image_bytes, bytes):
                            image_data = base64.b64encode(image_bytes).decode('utf-8')
                        else:
                            image_data = image_bytes  # Already base64 string

                        mime_type = getattr(part.inline_data, "mime_type", "image/png")
                        print(f"[ImageGenerator] ✓ Image generated successfully ({mime_type})", flush=True)

                        return {
                            "success": True,
                            "image_data": image_data,
                            "format": mime_type,
                            "metadata": {"model": self.model_name}
                        }

            # If no inline image found, return failure
            print("[ImageGenerator] ✗ No image data in response", flush=True)
            return {
                "success": False,
                "error": "No image data in response",
                "image_data": None,
                "format": None,
                "metadata": {"model": self.model_name}
            }

        except Exception as e:
            print(f"[ImageGenerator] ✗ Image generation failed: {str(e)}", flush=True)
            return {
                "success": False,
                "error": str(e),
                "image_data": None
            }

    def generate_image_for_article(
        self,
        article: Dict[str, Any],
        theme_override: Optional[str] = None,
        look: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate an image for an article.

        ``theme_override`` is what the model that read the article said the
        photograph should show, and ``look`` is the treatment chosen for this
        position in the batch. The keyword table below is the fallback for a
        failed or unusable answer, and for any caller that passes neither.
        """
        title = article.get("title", "Article Image")

        theme = (theme_override or "").strip()
        if not theme:
            theme = self._extract_article_theme(article)

        return self.generate_image(title=title, theme=theme, look=look)


    def _extract_article_theme(self, article: Dict[str, Any]) -> str:
        """
        Extract a meaningful theme from the article for image generation.
        Issue #859: This replaces generic category themes with content-specific themes.
        """
        title = article.get("title", "").lower()
        content = (
            article.get("content") or article.get("description") or ""
        ).lower()
        category = article.get("category", "").upper()
        
        # Food/product-specific keywords to look for
        food_keywords = {
            # Beverages
            "coffee": "coffee beans, coffee cups, or coffee brewing equipment",
            "tea": "tea leaves, tea bags, or steaming tea cups", 
            "juice": "fresh fruit juice glasses or fruit being juiced",
            "soda": "soda bottles or cans with bubbles",
            "water": "clear water bottles or glasses of water",
            "wine": "wine bottles and grapes",
            "beer": "beer bottles or glasses with foam",
            
            # Produce
            "apple": "fresh red and green apples",
            "banana": "ripe yellow bananas",
            "orange": "bright orange citrus fruits",
            "strawberr": "fresh red strawberries", 
            "lettuce": "fresh green lettuce heads",
            "tomato": "ripe red tomatoes",
            "potato": "russet and red potatoes",
            "onion": "yellow and red onions",
            "carrot": "fresh orange carrots",
            "produce": "colorful fresh fruits and vegetables",
            "organic": "fresh organic produce with natural lighting",
            
            # Meat & Dairy
            "meat": "raw cuts of meat on butcher paper",
            "chicken": "raw chicken pieces or cooked chicken dishes",
            "beef": "raw beef cuts or grilled beef",
            "pork": "pork chops or bacon strips",
            "fish": "fresh fish fillets or whole fish",
            "salmon": "fresh salmon fillets",
            "milk": "glasses of milk or milk cartons",
            "cheese": "various cheese blocks and wheels",
            "yogurt": "yogurt cups or bowls",
            "eggs": "fresh eggs in cartons or bowls",
            
            # Pantry Items
            "bread": "fresh loaves of bread or sliced bread",
            "pasta": "uncooked pasta shapes or pasta dishes",
            "rice": "grains of rice or rice in bowls",
            "cereal": "cereal boxes or bowls of cereal with milk",
            "cracker": "stacked crackers and a bowl of them",
            "cookie": "stacked cookies with crumbs",
            "doughnut": "glazed doughnuts on a rack",
            "donut": "glazed doughnuts on a rack",
            "chip": "a bowl of tortilla or potato chips",
            "snack": "assorted packaged snacks, generic packaging",
            "chocolate": "chocolate bars and broken pieces",
            "candy": "colourful wrapped candy",
            "oil": "cooking oil bottles",
            "sugar": "white sugar or sugar cubes",
            "flour": "flour bags or flour being sifted",
            
            # Price/Economic themes
            "price": "shopping cart, price tags, or receipts",
            "price": "price tags, a till receipt, or a shopping cart",
            "expensive": "price tags with high dollar amounts",
            "cheap": "discount tags or sale signs",
            "inflation": "rising price charts or expensive shopping cart",
            "cost": "calculator with grocery receipts",
            "sale": "sale tags and discount signs",
            "deal": "promotional pricing and shopping bags",
            
            # Store/Shopping themes
            "walmart": "generic supermarket shopping cart and bags",
            "target": "red shopping cart and retail bags", 
            "kroger": "grocery shopping cart with fresh produce",
            "safeway": "shopping basket with groceries",
            "costco": "bulk shopping with large quantities",
            "grocery": "shopping cart filled with various groceries",
            "shopping": "shopping cart or grocery bags",
            
            # Recall themes (if not handled by default image)
            "recall": "warning signs with food safety imagery",
            "contaminated": "food safety warning symbols",
            "bacteria": "microscopic imagery with warning symbols"
        }
        
        # Economic/trend keywords
        trend_keywords = {
            "rising": "upward trending arrows with food items",
            "falling": "downward trending arrows with discounted food",
            "shortage": "empty shelves or scarce food items", 
            "surplus": "abundant food items or overflowing baskets"
        }
        
        # Match on a word start, never mid-word, and read the headline before
        # the body.
        #
        # Both of those were doing real damage. A plain substring test put
        # "rice" inside "price", so ten of twenty-five grocery posts were
        # illustrated with bowls of rice; "fish" inside "Goldfish" gave a
        # cracker launch a salmon fillet; "tea" inside "instead" and "steak"
        # served tea with an article about Beyond Steak. And because the whole
        # body was searched, a 400-word piece always matched something early,
        # so the subject followed this dictionary's order rather than the
        # story.
        #
        # The boundary is start-only, so the stems in the table still work:
        # "strawberr" has to match "strawberries".
        def pattern_for(keyword):
            escaped = re.escape(keyword)
            if len(keyword) < 6:
                # Whole word, optionally pluralised: "tea" must not match
                # "team", nor "oil" "oilseed", nor "rice" "price".
                return r"\b" + escaped + r"(?:s|es)?\b"
            # Long enough to be safe as a prefix, which the stems rely on:
            # "strawberr" has to reach "strawberries".
            return r"\b" + escaped

        def first_match(text, table):
            if not text:
                return None
            for keyword, theme in table.items():
                if re.search(pattern_for(keyword), text):
                    return theme
            return None

        for source in (title, content):
            theme = first_match(source, food_keywords)
            if theme:
                return f"Focus on {theme}. Make it appetizing and clearly recognizable."

            theme = first_match(source, trend_keywords)
            if theme:
                return f"Show {theme} in a grocery context."


        # Category-based fallbacks with more specific guidance
        if category == "RECALL":
            return "Food safety warning imagery with the affected product type visible"
        elif category == "SHOPPERS":
            return "Shopping-related imagery focused on the specific product mentioned in the title"
        
        # Final fallback - use title analysis for completely custom themes
        return f"Create an image that visually represents the main topic from: '{article.get('title', '')}'. Focus on the key subject matter, not generic grocery aisles."


class PlaceholderImageGenerator:
    """
    Fallback image generator that creates placeholder images.
    Use this for testing or when Gemini API is unavailable.
    """

    def __init__(self):
        """Initialize the placeholder generator."""
        pass

    def generate_image(
        self,
        title: str,
        theme: str = "",
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        image_size: str = DEFAULT_IMAGE_SIZE,
        look: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a placeholder image."""
        # Create a simple SVG placeholder
        svg = f'''<svg width="600" height="338" xmlns="http://www.w3.org/2000/svg">
            <rect width="100%" height="100%" fill="#f0f0f0"/>
            <text x="50%" y="50%" text-anchor="middle" fill="#888" font-size="20">
                {title[:30]}...
            </text>
        </svg>'''

        image_data = base64.b64encode(svg.encode('utf-8')).decode('utf-8')

        return {
            "success": True,
            "image_data": image_data,
            "format": "svg",
            "placeholder": True,
            "title": title
        }

    def generate_image_for_article(
        self,
        article: Dict[str, Any],
        theme_override: Optional[str] = None,
        look: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a placeholder image for an article."""
        # Use same theme extraction as the main generator for consistency
        title = article.get("title", "Article Image")
        
        # For placeholder, just show the key subject from title
        return self.generate_image(
            title=title,
            theme=f"Placeholder for: {title}"
        )

    async def generate_images_concurrent(
        self,
        articles: List[Dict[str, Any]],
        max_workers: int = 4
    ) -> List[Dict[str, Any]]:
        """Generate placeholder images for multiple articles."""
        results = []
        for article in articles:
            result = self.generate_image_for_article(article)
            result["article"] = article
            results.append(result)
        return results


def get_image_generator(use_placeholder: bool = False) -> ImageGenerator:
    """
    Get an image generator instance.

    Args:
        use_placeholder: Use placeholder generator instead of Gemini

    Returns:
        ImageGenerator or PlaceholderImageGenerator instance
    """
    if use_placeholder:
        return PlaceholderImageGenerator()

    try:
        return ImageGenerator()
    except (ImportError, ValueError) as e:
        print(f"Warning: Cannot initialize ImageGenerator ({e}), using placeholder images")
        return PlaceholderImageGenerator()
