# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Youdle is a full-stack AI blog generation platform that automatically generates blog posts from news articles, creates images, and sends newsletters. It uses LangGraph for workflow orchestration with a Python backend, FastAPI API server, and Next.js dashboard.

## Development Commands

### Python Core (Root)
```bash
pip install -r requirements.txt           # Install Python dependencies
python generate_blog_posts.py             # Main CLI - generate blog posts
python generate_blog_posts.py --dry-run   # Preview without generating
python collect_feedback.py                # Interactive feedback CLI
python mailchimp_campaign.py --preview    # Preview newsletter
```

### FastAPI Backend
```bash
cd api && pip install -r requirements.txt
uvicorn main:app --reload --port 8000     # Start API server (http://localhost:8000/docs)
```

### Next.js Frontend
```bash
cd frontend && npm install
npm run dev      # Development server (http://localhost:3000)
npm run build    # Production build
npm run lint     # ESLint
```

## Architecture

### Three-Layer Structure
1. **Python Core** (root): LangGraph workflow orchestration, AI generation, external API integrations
2. **FastAPI API** (`/api`): REST endpoints, job queue management, Blogger publishing
3. **Next.js Dashboard** (`/frontend`): React UI for monitoring and review

### Key Workflow Components (LangGraph StateGraph in `blog_post_graph.py`)
```
search_articles → select_articles → hydrate_articles → load_learning → generate_posts
                                                                              ↓
                                                        proofread_posts → generate_images
                                                                              ↓
              upload_images → assemble_html → save_posts → push_drafts_to_blogger
```
Every article is generated exactly once. `assemble_html` runs the deterministic
editorial checklist (`ReflectionAgent`) and records what failed it as job
warnings; it does not rewrite. A regeneration loop used to retry rejected drafts
here, but across every observed run it never turned a single rejected draft into
a valid one, so it only tripled the generation bill.

### Data Flow
- **State Management**: `BlogPostState` TypedDict flows through LangGraph nodes
- **Database**: Supabase (PostgreSQL) with tables: `job_queue`, `blog_posts`, `feedback`, `newsletters`, `newsletter_posts`, `settings`
- **Realtime**: Supabase subscriptions for live job/post updates in frontend

### External APIs
- Exa AI: Article search (`zap_exa_ranker.py`)
- OpenAI: Blog generation (`langchain_blog_agent.py`)
- Google Gemini: Image generation (`image_generator.py`)
- Google Blogger: Post publishing (`api/blogger_client.py`)
- Mailchimp: Newsletter campaigns (`mailchimp_campaign.py`)

## Key Patterns

### Blog Categories
Two main categories: `SHOPPERS` (grocery articles) and `RECALL` (recall alerts)

### Post/Job Status Flow
- Posts: `draft` → `reviewed` → `published`
- Jobs: `pending` → `running` → `completed` | `failed` | `cancelled`

### Frontend Conventions
- Path alias: `@/*` maps to `./src/*`
- Custom Tailwind colors: `youdle-*` and `midnight-*` prefixes
- State: React Query for server state, Supabase for realtime

### Environment Variables
- Backend: `.env` in root (EXA_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY, MAILCHIMP_*, BLOGGER_*)
- Frontend: `frontend/.env.local` with `NEXT_PUBLIC_*` prefix

## API Endpoints (localhost:8000)
- `GET /api/health` - Health check
- `GET /api/stats` - System statistics
- `POST /api/search/preview` - Article search
- `POST /api/generate/run` - Start generation job
- `GET/POST /api/generate/posts` - Blog posts CRUD
- `POST /api/generate/posts/{id}/publish` - Publish to Blogger
- `GET /api/jobs` - Job queue management

### Newsletter Endpoints
- `GET /api/newsletters` - List all newsletters
- `POST /api/newsletters` - Create newsletter from post IDs
- `GET /api/newsletters/{id}` - Get newsletter by ID
- `GET /api/newsletters/{id}/preview` - Preview newsletter HTML
- `POST /api/newsletters/{id}/schedule` - Schedule for Thursday 9 AM CST
- `POST /api/newsletters/{id}/send` - Send immediately via Mailchimp
- `POST /api/newsletters/{id}/unschedule` - Cancel scheduled send
- `GET /api/newsletters/status` - Check Mailchimp configuration
- `GET /api/newsletters/audiences` - List Mailchimp audiences
- `POST /api/newsletters/audiences/set` - Set active audience

## Newsletter System

### Workflow
1. **Create**: Select published blog posts → auto-generates HTML email
2. **Preview**: View rendered newsletter in modal
3. **Schedule/Send**: Schedule for Thursday 9 AM CST or send immediately

### Mailchimp Integration
- **Configuration**: Set `MAILCHIMP_API_KEY`, `MAILCHIMP_LIST_ID`, `MAILCHIMP_SERVER_PREFIX` in `.env`
- **Sender Email**: Default `info@getyoudle.com` (configured in `mailchimp_campaign.py`)
- **Audience Selection**: Stored in `settings` table, changeable via dashboard

### Newsletter Status Flow
- `draft` → `scheduled` → `sent`
- `draft` → `sent` (immediate send)
- `draft/scheduled` → `failed` (on error)

### Database Tables
- `newsletters`: Stores newsletter content, Mailchimp campaign IDs, stats
- `newsletter_posts`: Junction table linking newsletters to blog posts
- `settings`: Key-value store for app config (e.g., active Mailchimp audience)

## Prompt Customization
- Blog templates: `SHOPPERS_BLOG_PROMPT` and `RECALL_BLOG_PROMPT` in `langchain_blog_agent.py`
- Newsletter template: `NEWSLETTER_TEMPLATE` in `mailchimp_campaign.py`
- Image prompts: `IMAGE_PROMPT_TEMPLATE` in `image_generator.py`
