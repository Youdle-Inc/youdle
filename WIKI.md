# Youdle Wiki

Youdle is a full-stack AI blog generation platform that automatically generates blog posts from news articles, creates images, publishes to Blogger, and sends weekly newsletters via Mailchimp.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Python Core](#python-core)
4. [FastAPI Backend](#fastapi-backend)
5. [Next.js Frontend](#nextjs-frontend)
6. [GitHub Actions](#github-actions)
7. [Newsletter System](#newsletter-system)
8. [Database Schema](#database-schema)
9. [External APIs](#external-apis)
10. [Configuration](#configuration)
11. [Weekly Schedule](#weekly-schedule)

---

## Architecture Overview

Youdle uses a three-layer architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Next.js Dashboard (port 3000)               │
│                    React Query + Supabase Realtime              │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (port 8000)                  │
│              REST API, Job Queue, Blogger Publishing            │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Python Core (root)                        │
│           LangGraph Workflow, AI Generation, Integrations       │
└─────────────────────────────────────────────────────────────────┘
```

**Data Flow:**
- Articles are searched via Exa AI
- Blog posts generated via OpenAI (LangChain)
- Images generated via Google Gemini
- Posts published to Google Blogger
- Newsletters sent via Mailchimp
- All data stored in Supabase (PostgreSQL)

---

## Project Structure

```
youdle/
├── api/                    # FastAPI backend
│   ├── routes/             # API endpoints
│   │   ├── generate.py     # Blog post CRUD, Blogger sync
│   │   ├── jobs.py         # Job queue management
│   │   ├── newsletters.py  # Newsletter endpoints
│   │   ├── search.py       # Article search
│   │   └── media.py        # Media uploads
│   ├── blogger_client.py   # Blogger API integration
│   └── main.py             # FastAPI app entry
│
├── frontend/               # Next.js dashboard
│   └── src/
│       ├── app/            # Pages (posts, newsletters, jobs, etc.)
│       ├── components/     # React components
│       └── lib/            # API client, utilities
│
├── .github/workflows/      # GitHub Actions automation
│   ├── generate-blog-posts.yml
│   ├── create-newsletter.yml
│   └── reminder-emails.yml
│
├── prompts/                # Blog generation prompt templates
├── tests/                  # Python test suite
├── blog_posts/             # Generated post output
│
├── generate_blog_posts.py  # Main CLI entry point
├── blog_post_graph.py      # LangGraph workflow
├── langchain_blog_agent.py # Blog generation agent
├── zap_exa_ranker.py       # Article search & ranking
├── reflection_agent.py     # Post validation
├── image_generator.py      # Gemini image generation
├── mailchimp_campaign.py   # Newsletter creation
├── check_blog_status.py    # Weekly publish status
├── fetch_published_posts.py# Fetch posts for newsletter
└── email_notifier.py       # Email notifications (SMTP)
```

---

## Python Core

### LangGraph Workflow

The blog generation workflow is orchestrated by LangGraph in `blog_post_graph.py`:

```
search_articles → select_articles → load_learning → generate_posts → reflect_posts
                                                                          │
                                              [regenerate if failed] ◄────┤
                                                                          ▼
                                    generate_images → upload_images → assemble_html → save_posts
                                                                                          │
                                                                                          ▼
                                                                           push_drafts_to_blogger
```

**State (BlogPostState):**
- `search_results`, `articles` - Found articles
- `shoppers_articles`, `recall_articles` - Categorized articles
- `generated_posts`, `reflection_results` - Generation output
- `images`, `uploaded_urls` - Generated images
- `final_posts`, `saved_files` - Final output

### Key Components

| File | Purpose |
|------|---------|
| `langchain_blog_agent.py` | OpenAI-powered blog generation with LangChain |
| `zap_exa_ranker.py` | Exa AI article search with scoring algorithm |
| `reflection_agent.py` | HTML validation, word count, quality checks |
| `image_generator.py` | Google Gemini image generation |
| `imgbb_upload.py` | Image CDN upload |
| `learning_memory.py` | Session memory for generation improvements |
| `example_store.py` | Few-shot examples from Supabase |
| `prompt_refiner.py` | Dynamic prompt enhancement |

### Article Search & Ranking

`zap_exa_ranker.py` uses Exa AI with a scoring algorithm:

- **Keyword boost:** +100 for recall signals (contamination, salmonella, etc.)
- **Position boost:** +10 for first entry per query
- **Length score:** Optimal 600-1200 characters
- **Age score:** Recency bonus
- **Category boost:** +50 for RECALL

Output: 80% SHOPPERS, 20% RECALL

### Blog Categories

| Category | Description | Requirements |
|----------|-------------|--------------|
| SHOPPERS | Grocery deals, trends, tips | 6 per week |
| RECALL | FDA/USDA food safety alerts | 1 per week |

---

## FastAPI Backend

### Endpoints

**Blog Posts (`/api/generate`)**
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/run` | Start generation job |
| GET | `/posts` | List posts (filter: status, category) |
| GET | `/posts/{id}` | Get single post |
| PATCH | `/posts/{id}` | Update post (syncs to Blogger) |
| DELETE | `/posts/{id}` | Delete post |
| POST | `/posts/{id}/publish` | Publish to Blogger |
| POST | `/posts/{id}/unpublish` | Revert to draft |
| POST | `/blogger/sync` | Full Blogger sync |
| POST | `/blogger/sync-light` | Non-destructive sync |

**Jobs (`/api/jobs`)**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List jobs |
| GET | `/{id}` | Job status |
| GET | `/{id}/logs` | Job logs |
| DELETE | `/{id}` | Cancel job |

**Newsletters (`/api/newsletters`)**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List newsletters |
| POST | `/` | Create newsletter |
| GET | `/{id}/preview` | Preview HTML |
| POST | `/{id}/schedule` | Schedule for Thursday 9 AM CST |
| POST | `/{id}/send` | Send immediately |
| GET | `/audiences` | List Mailchimp audiences |

### Blogger Client

`api/blogger_client.py` handles Google Blogger API:

- OAuth2 authentication with refresh token
- `publish_post()` - Create new or update existing
- `publish_draft()` / `revert_to_draft()` - Status changes
- `list_posts()` - Fetch by status (LIVE/DRAFT)

**Sync Modes:**
- **Full sync:** 4-phase (discovery, verification, auto-fix, import)
- **Light sync:** Non-destructive, only adds data when post is LIVE

---

## Next.js Frontend

### Pages

| Page | Path | Description |
|------|------|-------------|
| Dashboard | `/` | Stats, quick actions, newsletter readiness |
| Posts | `/posts` | Blog post management |
| Newsletters | `/newsletters` | Create, schedule, send newsletters |
| Articles | `/articles` | Preview article search |
| Jobs | `/jobs` | Monitor generation jobs |
| Review | `/review` | Review and approve posts |
| Settings | `/settings` | Configuration |

### Key Components

| Component | Purpose |
|-----------|---------|
| `BlogPostPreview` | Post card with edit/publish/delete |
| `NewsletterCard` | Newsletter with schedule/send/preview |
| `NewsletterReadinessCard` | Publish progress widget |
| `RichTextEditor` | TipTap WYSIWYG editor |
| `CreateNewsletterModal` | Newsletter creation |
| `EditBlogPostModal` | Post editing |

### State Management

- **React Query:** Server state, caching, mutations
- **Supabase Realtime:** Live updates for jobs/posts/newsletters

---

## GitHub Actions

### Weekly Schedule (all times CST)

| Day | Time | Workflow | Action |
|-----|------|----------|--------|
| Tuesday | 9:00 AM | `generate-blog-posts.yml` | Generate blog posts |
| Tuesday | 8:00 PM | `reminder-emails.yml` | First reminder email |
| Wednesday | 10:00 AM | `reminder-emails.yml` | Second reminder |
| Wednesday | 8:00 PM | `reminder-emails.yml` | Final warning |
| Thursday | 9:00 AM | `create-newsletter.yml` | Create & send newsletter |

### generate-blog-posts.yml

1. Setup Python 3.11
2. Verify secrets
3. Run `generate_blog_posts.py --json`
4. Upload artifacts

### create-newsletter.yml

1. **check-publish-status job:**
   - Run `check_blog_status.py --json`
   - Verify: 6 SHOPPERS + 1 RECALL published
   - Send notification

2. **create-campaign job** (if requirements met):
   - Fetch posts with `fetch_published_posts.py`
   - Create Mailchimp campaign
   - Send newsletter

### reminder-emails.yml

- Sends reminders over SMTP
- Shows current publish status
- Final warning on Wednesday 8 PM

---

## Newsletter System

### Workflow

```
Select Posts → Create Newsletter → Preview → Schedule/Send
                    │
                    ▼
            Generate HTML from template
                    │
                    ▼
            Create Mailchimp Campaign
                    │
                    ▼
            Schedule (Thu 9 AM) or Send Now
```

### Status Flow

```
draft → scheduled → sent
  │
  └──→ sent (immediate)
  │
  └──→ failed (on error)
```

### Mailchimp Integration

`mailchimp_campaign.py` handles:
- `create_campaign()` - Create with HTML content
- `send_campaign()` - Immediate send
- `schedule_campaign()` - Schedule for specific time
- `get_campaign_status()` - Fetch stats

**Sender:** "Youdle" <info@getyoudle.com>

---

## Database Schema

### Core Tables

**blog_posts**
```sql
id, title, html_content, image_url, category
status (draft/reviewed/published)
article_url, blogger_post_id, blogger_url, blogger_published_at
job_id, created_at, updated_at, last_synced_at
```

**job_queue**
```sql
id, status (pending/running/completed/failed/cancelled)
config, started_at, completed_at, result, error
```

**newsletters**
```sql
id, title, subject, html_content
status (draft/scheduled/sent/failed)
mailchimp_campaign_id, scheduled_for, sent_at
emails_sent, open_rate, click_rate
```

**newsletter_posts** (junction table)
```sql
id, newsletter_id, blog_post_id, position
```

**settings** (key-value config)
```sql
key, value
```

### Learning System Tables

- **blog_examples** - Good/bad post examples for few-shot learning
- **blog_feedback** - User feedback on posts
- **learning_insights** - Patterns extracted from feedback

---

## External APIs

| Service | Purpose | Key Variables |
|---------|---------|---------------|
| Exa AI | Article search | `EXA_API_KEY` |
| OpenAI | Blog generation | `OPENAI_API_KEY` |
| Google Gemini | Image generation | `GEMINI_API_KEY` |
| Google Blogger | Post publishing | `BLOGGER_*` credentials |
| Mailchimp | Newsletters | `MAILCHIMP_*` credentials |
| imgBB | Image CDN | `IMGBB_API_KEY` |
| Google Workspace SMTP | Email notifications | `SMTP_USERNAME`, `SMTP_PASSWORD` |
| Supabase | Database & storage | `SUPABASE_URL`, `SUPABASE_KEY` |

---

## Configuration

### Environment Variables (.env)

```bash
# AI Services
EXA_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=

# Database
SUPABASE_URL=
SUPABASE_KEY=

# Image Hosting
IMGBB_API_KEY=

# Newsletter
MAILCHIMP_API_KEY=
MAILCHIMP_LIST_ID=
MAILCHIMP_SERVER_PREFIX=

# Blogger
BLOGGER_BLOG_ID=
BLOGGER_CLIENT_ID=
BLOGGER_CLIENT_SECRET=
BLOGGER_REFRESH_TOKEN=

# Notifications
SMTP_USERNAME=
SMTP_PASSWORD=
ADMIN_NOTIFICATION_EMAIL=
```

### Frontend (.env.local)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Customization

| File | Customizes |
|------|------------|
| `prompts/SHOPPERS_BLOG_PROMPT` | Shoppers post template |
| `prompts/RECALL_BLOG_PROMPT` | Recall post template |
| `mailchimp_campaign.py` → `NEWSLETTER_TEMPLATE` | Email template |
| `image_generator.py` → `IMAGE_PROMPT_TEMPLATE` | Image prompts |

---

## Weekly Schedule

### Timeline (CST)

```
TUESDAY
  └─ 9:00 AM  → Generate blog posts (auto)
  └─ 8:00 PM  → First reminder email

WEDNESDAY
  └─ 10:00 AM → Second reminder email
  └─ 8:00 PM  → Final warning email

THURSDAY
  └─ 9:00 AM  → Newsletter created & sent (if requirements met)
```

### Requirements for Newsletter

- **6 SHOPPERS** articles published this week
- **1 RECALL** article published this week
- Posts must have `blogger_published_at` within current week
- Week starts: **Tuesday midnight CST**

---

## Development Commands

### Python Core
```bash
pip install -r requirements.txt
python generate_blog_posts.py              # Generate posts
python generate_blog_posts.py --dry-run    # Preview only
python mailchimp_campaign.py --preview     # Preview newsletter
```

### FastAPI Backend
```bash
cd api && pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Next.js Frontend
```bash
cd frontend && npm install
npm run dev      # http://localhost:3000
npm run build    # Production build
```

### Testing
```bash
pytest tests/
```

---

## Status Flows

### Post Status
```
draft → reviewed → published
```

### Job Status
```
pending → running → completed
                 → failed
                 → cancelled
```

### Newsletter Status
```
draft → scheduled → sent
     → sent (immediate)
     → failed
```

---

## Key Patterns

### Date/Time
- All times in **CST (America/Chicago)**
- Database stores UTC
- Week starts Tuesday midnight CST

### Blogger Sync
- `blogger_published_at` is the reliable published timestamp
- Light sync is non-destructive (only adds data)
- Full sync does title matching with 0.85 similarity threshold

### Newsletter Readiness
- Single source of truth: `check_blog_status.py`
- Filters by `blogger_published_at >= week_start`
- Old imports (pre-2026) excluded from counts
