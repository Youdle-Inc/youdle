# prompts/reflection_prompt.py
# Updated REFLECTION_PROMPT for validating blog posts

REFLECTION_PROMPT = """Review this generated blog post and check for compliance with ALL requirements:

## Structure Validation
1. HTML structure: Must start with <div> and end with </div>
2. Image tag: The first element inside the outer <div> must be <img src="{{IMAGE_HERE}}" alt="article image"/>
3. Headline: Exactly one <h2> in sentence case with 13 words or fewer, no em/en dash, exclamation, all-caps words, region/place names or unsupported store names
4. First paragraph: Must open on the national shopper impact, without a Memphis dateline
5. List: Must have a <ul> with <li> items

## Mandatory headline/promise review
- The headline must name something familiar (cart, bill, fridge, pantry or a real product)
- It must offer one supported change, risk or discovery and ONE specific curiosity gap
- Read the FIRST TWO paragraphs and identify the actual answer to that gap
- If there is NO explicit payoff in those paragraphs, mark is_valid false
- If the source does not support the headline promise, mark is_valid false
- No misleading dramatic double meanings, bait, scolding, invented urgency or unsupported promises
- For a recall roundup, validate every named hazard and the food count against the article facts.
- For other stories, assess variety and topic-appropriate patterns; do not copy stock examples
- Require headline and lead to be nationally useful without geographic mentions
- If invalid, identify what was falsely implied and suggest a new truthful headline. Do not invent supporting facts

## Word Count Validation
6. Word count: Must be 400-600 words

## Link Validation
7. Attribute reporting sources by name without hyperlinking external publishers
8. Include zero or one relevant Youdle feature link when naturally useful
9. No outbound news-source article links; official government recall notices are an exception for safety
10. No generic Grocery Brief or repeated marketing closes

## Quality Validation
11. Attribution: Factual claims should be attributed to credible sources
12. No corporate language: No "innovative," "game-changing," "leverage," etc.
13. Second-person voice: Uses "you" not "consumers" or "shoppers"
14. No "subscribe"/"subscription" language anywhere — the Youdle Blog is a landing page
15. Headline text must NOT be repeated in the article body
16. Must NOT read like a brand press release or store promotion — focus on reader impact

## Spelling & Grammar Validation
17. Check for spelling errors in ALL text content (headlines, body, CTAs)
18. Check for grammar mistakes (subject-verb agreement, tense consistency, missing articles)
19. Check for repeated words or phrases within the same sentence
20. Check for awkward AI-generated phrasing (e.g., "navigate the landscape of", "in the realm of")
21. Verify proper nouns and brand names are spelled correctly (Youdle, Kroger, Walmart, etc.)
22. Check for missing or extra punctuation

Blog post to review:
{blog_post}

Respond with a JSON object:
{{
    "is_valid": true/false,
    "word_count": <actual word count>,
    "has_contextual_youdle_link": true/false,
    "has_unwanted_source_article_link": true/false,
    "headline_payoff_in_first_two_paragraphs": true/false,
    "headline_truthful_and_compliant": true/false,
    "spelling_errors": ["list of misspelled words with corrections, e.g. 'recieved → received'"],
    "grammar_errors": ["list of grammar issues with corrections"],
    "issues": ["list of specific issues found"],
    "suggestions": ["how to fix each issue"]
}}
"""
