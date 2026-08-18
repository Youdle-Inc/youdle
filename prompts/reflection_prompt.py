# prompts/reflection_prompt.py
# Updated REFLECTION_PROMPT for validating blog posts

REFLECTION_PROMPT = """Review this generated blog post and check for compliance with ALL requirements:

## Structure Validation
1. HTML structure: Must start with <div> and end with </div>
2. News Blog navigation: The first element inside the outer <div> must link to https://news.youdle.io/ with the text "Back to News Blog"
3. Image tag: Immediately after the News Blog navigation block, include <img src="{{IMAGE_HERE}}" alt="article image"/>
4. Headline: Must have exactly one <h2> tag (sentence case, not Title Case)
5. First paragraph: Must begin with "MEMPHIS, Tenn. (Youdle)" followed by a dash (â€“ preferred; - accepted)
6. List: Must have a <ul> with <li> items

## Word Count Validation
7. Word count: Must be 400-600 words

## Four-Part Close Validation (ALL FOUR required)
8. Youdle Search CTA: Must include link to youdle.io with product/search mention
9. Youdle Community CTA: Must include link to youdle.io/community
10. Blog CTA: Must include link to getyoudle.com/blog (do NOT use the word "subscribe" or "subscription")
11. Original source link: Must include "Read the full story" link to source

## Quality Validation
12. Attribution: Factual claims should be attributed to credible sources
13. No corporate language: No "innovative," "game-changing," "leverage," etc.
14. Second-person voice: Uses "you" not "consumers" or "shoppers"
15. No "subscribe"/"subscription" language anywhere — the Youdle Blog is a landing page
16. Headline text must NOT be repeated in the article body
17. Must NOT read like a brand press release or store promotion — focus on reader impact

## Spelling & Grammar Validation
18. Check for spelling errors in ALL text content (headlines, body, CTAs)
19. Check for grammar mistakes (subject-verb agreement, tense consistency, missing articles)
20. Check for repeated words or phrases within the same sentence
21. Check for awkward AI-generated phrasing (e.g., "navigate the landscape of", "in the realm of")
22. Verify proper nouns and brand names are spelled correctly (Youdle, Kroger, Walmart, etc.)
23. Check for missing or extra punctuation

Blog post to review:
{blog_post}

Respond with a JSON object:
{{
    "is_valid": true/false,
    "word_count": <actual word count>,
    "has_four_part_close": {{
        "youdle_search": true/false,
        "youdle_community": true/false,
        "youdle_blog": true/false,
        "source_link": true/false
    }},
    "spelling_errors": ["list of misspelled words with corrections, e.g. 'recieved → received'"],
    "grammar_errors": ["list of grammar issues with corrections"],
    "issues": ["list of specific issues found"],
    "suggestions": ["how to fix each issue"]
}}
"""
