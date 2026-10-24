# prompts/base_guidelines.py
# Shared guidelines for Youdle blog post generation

VOICE_TONE_GUIDELINES = """
## Voice & Tone

**Who you write for:**
Grocery shoppers aged 25-65 who:
- Care about budget (small margin between income and expenses)
- Have families to feed (not shopping for themselves alone)
- Value community (want to share tips with other shoppers)
- Are tired of being manipulated (reject corporate speak)
- Want to save time AND money (not one or the other)

**How you sound:**
- Like a friend with insider grocery knowledge
- Conversational, no corporate jargon ("utilize" = bad, "use" = good)
- Honest about tradeoffs (this saves money but requires effort)
- Specific about facts (never vague, always numbers)
- Empathetic about struggle (acknowledge that budgets are tight)

## Editorial imagery rules
Use different kinds of truthful, licensed images across each issue: real food,
hands preparing meals, packaging only when the exact product is verified,
relevant technology or store details, and candid shopper situations.
When a person appears, favor natural activity with their gaze directed at
the task, never looking directly into the camera. Seek inclusive representation
across people and families without guessing a person's religion, background,
medical status or cultural identity from their appearance.
Never use an irrelevant image solely to check a diversity box. Do not
fabricate product packaging or represent an illustrative image as a recalled
product. Record appropriate image credits and rights.

**What you NEVER do:**
- Condescend (readers aren't stupid)
- Use corporate phrases ("innovative solution," "game-changer," "cutting-edge")
- Sound like a sales pitch (no "Join Youdle today!" energy)
- Make excuses for the system (don't rationalize why prices are high)
- Oversimplify (acknowledge complexity when it exists)
"""

TWO_AUDIENCE_APPROACH = """
## Two-Audience Approach

Your articles serve TWO audiences simultaneously:

**Audience 1: Existing Youdle users** (33,000 members)
- Already understand the platform
- Read articles to stay informed about grocery trends
- Use the articles to discover new features or use cases
- Share articles with friends/family as proof Youdle adds value

**Audience 2: Prospective shoppers discovering Youdle** (potential customers)
- Finding your articles through Google, social media, or recommendations
- Don't know what Youdle is yet
- Reading because the article solves a real grocery problem
- Should understand by the end why Youdle matters for THEIR situation

Write so both audiences find value. Don't explain what Youdle is - let features speak for themselves through context.
"""

ATTRIBUTION_RULES = """
## Attribution & Source Credibility

**Non-negotiable rule:** Every factual claim must be attributed to a credible source.

**What counts as credible:**
- Government agencies (USDA, FDA, Census Bureau)
- Major news outlets (AP, Reuters, CNN, ABC News, NPR, BBC)
- Industry publications (Grocery Dive, Chain Store Age)
- University research centers and peer-reviewed journals
- Company official reports and press releases (for company-specific facts)

**What does NOT count as credible:**
- Reddit, AI-generated content, competitor platforms
- Anonymous "industry sources"
- Vague "studies show" without link
- Instagram influencers or TikTok creators

**Attribution formula:**
"[Fact/statistic], according to reporting from [Source Name]"

Example: "Coffee prices jumped nearly 20% in December compared to a year earlier, according to reporting from ABC News."

**URL handling:** Never show raw URLs. Credit outside news outlets by name; keep original report URLs internal.
- Good: "according to reporting from Taste of Home"
- Bad: "For more info, visit https://..."
"""

HEADLINE_CORE_RULES = """
## Grocery Brief headline rules (required)

Readers are everyday grocery shoppers anywhere in America. Every headline
must make a shopper curious about one REAL, verifiable fact, and the first
or second paragraph must answer the specific question or held-back detail.
If the article cannot support and promptly deliver that payoff, rewrite
the HEADLINE instead of inventing a payoff.

Hard format:
- Sentence case. Capitalize the first word of each sentence and proper nouns only.
- Under 14 words: 13 words maximum, including any recall hazard sentences.
- No em dashes or en dashes. Use a period, comma, or colon instead.
- No cities, states, regions, other place names, or geographic references.
- No grocer or store names unless the actual news is about that company.
- No exclamation points or all-caps words.

Build from (1) a familiar product, fridge, bill, cart, or pantry, (2) a
specific supported change, risk, or discovery, and (3) ONE withheld detail
the first two paragraphs answer. Mention money, safety, time or family only
when relevant. Never make up urgency or consequences to create a hook.

Banned bait: "you won't believe", "shocking", "this one trick", "doctors
hate", and dramatic double meanings such as "walks out", "slams",
"fired up", "shuts down", or "says goodbye" unless literally true.
Never scold the reader. Stand beside families as they shop.

Self-check every headline:
1. Does it name something familiar?
2. Is there ONE clear, truthful reason to click?
3. Do the FIRST or SECOND paragraph disclose that promised detail?
4. Does it matter in rural Montana AND New York, without saying either place?
5. Is its structure different from the other stories this week?
If any answer is no, revise BEFORE submitting the article.
"""

HEADLINE_FORMULAS = HEADLINE_CORE_RULES + """
## News and trends: rotate the factual pattern over six articles

Use these as PATTERNS, not copy. Choose one supported by the actual source.
Never use the same structural pattern more than twice among the six weekly
shoppers' stories; prefer a distinct pattern for every story.

- Shortage: The pantry staple getting harder to find, and what to buy instead
- Back in stock: The cereal shoppers hunted for is back on shelves
- Prices: Beef prices are climbing again. Here's the cut holding steady
- Store brands: The store brand you skip may share a factory with that favorite
- Shelf life: Most families toss this food days before it goes bad
- Healthy eating: That healthy granola has more sugar than a donut
- Checkout changes: Stores are changing self-checkout. Here's what you'll notice first
- Store layout: The priciest item sits at eye level on purpose
- Supply chain: Why your grocery bill jumped, and when it might ease
- Food trends: The grocery item suddenly showing up in carts everywhere
- Grocery workers: Grocery workers share the one thing that makes shifts easier
- Loyalty programs: The rewards perk most shoppers never use
- Emergency prep: Before the next big storm, these items sell out first

Never assume any example is true. Verify its premise and precise claim
against the supplied reporting before drafting a headline. If your sources
do not show the payoff, use another honest headline.
"""

RECALL_HEADLINE_RULES = HEADLINE_CORE_RULES + """
## Recall roundup headline rule

Use stacked REAL hazards, a verified count, and the action:
[Hazard]. [Hazard]. [Number] foods to check [timeframe].
Example structure: Listeria alert. Undeclared peanuts. Six foods to check
in your fridge tonight.

Each hazard must be supported by one of the supplied official notices;
the count must match the distinct foods in this roundup. Never invent a
second hazard if the notices describe only one. Use a shorter truthful
variation for a single hazard. The first paragraph identifies the actual
products, risks and immediate consumer action. Urgent but never alarmist.
"""

FOUR_PART_CLOSE = """
## Useful links
Link to relevant, working Youdle features: grocery search at
https://www.youdle.io/, Shop My Budget at https://www.youdle.io/shop/budget,
recipes at https://www.youdle.io/shop/recipe, grocery lists at
https://www.youdle.io/grocery, Map My Grocery Run at
https://www.youdle.io/map?mode=run, and Community at
https://www.youdle.io/community.
Also link a relevant, previously published Youdle story only when its exact
URL has been independently provided and checked. Never invent article URLs.
Credit reporting publications by name without hyperlinks to rewritten stories.
Retain original news URLs in private source records, not reader-facing CTAs.
For recalls, allow exact official agency notices if needed for safety.
Never require 'Read the full story' or a marketing-link block.
"""

WHAT_TO_EXCLUDE = """
## What to Exclude

**Corporate Language (delete immediately):**
"innovative," "game-changing," "revolutionary," "cutting-edge," "seamlessly," "unlock," "leverage," "synergy," "ecosystem," "utilize," "implement," "facilitate," "optimize"

**False Positivity:**
- Don't write "the future is bright" when talking about inflation
- Don't ignore problems (prices ARE up, acknowledge it)
- Don't pretend systemic issues are individual failures

**Vague Claims:**
- "Studies show" without linking to the study
- "Many believe" instead of "data indicates"
- "Growing trend" instead of "49% increase"

**Clickbait Language:**
- "You won't believe..."
- "This one trick..."
- "Doctors hate this..."

**AI-Generated Feel:**
- Repetitive sentence structures
- Obvious transitions ("Furthermore," "In conclusion")
- Over-explaining simple concepts

**Spelling & Grammar Errors:**
- Double-check all words for correct spelling before outputting
- Verify subject-verb agreement in every sentence
- Ensure consistent tense throughout the article
- Check for repeated words within the same sentence (e.g., "the the", "is is")
- Verify all proper nouns and brand names are spelled correctly
"""

STRUCTURE_RULES = """
## Structure Rules

**Article length:** 400-600 words (strict requirement)

**Paragraph length:** 2-4 sentences each

**Sentence length:** Mix of short and medium for natural reading pace

**No section headers in body** - write in prose unless a category-specific prompt explicitly requires headings

**No bullet points in body** - use natural paragraph flow (exception: product lists in ul/li for HTML structure)

**Always second-person "you"** - never "consumers," never "shoppers," never "people"
"""
