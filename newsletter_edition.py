"""Accumulate a week's published stories in its existing, unsent edition."""
from datetime import datetime, timedelta, timezone
from html import unescape
from uuid import uuid4
from zoneinfo import ZoneInfo
import re

RECALL_POSITION = 2_000_000_000


def week_bounds(now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/Chicago'))
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=7)).astimezone(timezone.utc)


def existing_images(body):
    """Preserve an editor's newsletter photo when the article has no hero field."""
    images = {}
    for match in re.finditer(r'<a\b([^>]*)>\s*<img\b([^>]*)>', body or '', re.I):
        href = re.search(r'''\bhref\s*=\s*(["'])(.*?)\1''', match[1], re.I)
        src = re.search(r'''\bsrc\s*=\s*(["'])(.*?)\1''', match[2], re.I)
        if href and src:
            images[unescape(href[2])] = unescape(src[2])
    return images


def preview_subject(posts):
    """Use actual article headlines, without generic counts or invented urgency."""
    titles = [" ".join(str(p.get("title") or "").split()) for p in posts if p.get("title")]
    if not titles:
        raise ValueError("Published article titles are required for the newsletter subject")
    clauses = [re.split(r"(?<=[.!?])\s+", t, maxsplit=1)[0].strip().rstrip('.') for t in titles]
    lead = clauses[0]
    if len(lead) > 68:
        lead = lead[:68].rsplit(' ', 1)[0].rstrip(' ,;:')
    for other in clauses[1:]:
        if other and len(lead) + len(other) + 3 <= 85:
            return lead + ' / ' + other
    return lead


def _links(db, newsletter_id):
    return db.table('newsletter_posts').select('*').eq('newsletter_id', newsletter_id).order('position').execute().data or []


def _find_edition(db, start, end):
    rows = db.table('newsletters').select('*').gte('created_at', start.isoformat()).lt('created_at', end.isoformat()).order('created_at').limit(1).execute().data or []
    return rows[0] if rows else None


def sync_weekly_draft(db, render, *, post_ids=None, title=None, subject=None, require_complete=False, now=None):
    """Reuse the current edition and append memberships; never send or schedule.

    The existing weekly unique index prevents concurrent edition creation.
    Memberships are appended rather than deleted, so concurrent publish callbacks
    cannot discard each other's stories. HTML writes use an optimistic lease and
    re-read memberships after a competing callback updates the same draft.
    """
    start, end = week_bounds(now)
    edition = _find_edition(db, start, end)
    if edition and edition['status'] != 'draft':
        return {'newsletter': edition, 'created': False, 'changed': False, 'locked': True}

    query = db.table('blog_posts').select('id,title,category,blogger_url,image_url,html_content,blogger_published_at').eq('status', 'published').not_.is_('blogger_url', 'null').is_('archived_at', 'null').gte('blogger_published_at', start.isoformat()).lt('blogger_published_at', end.isoformat()).order('blogger_published_at').limit(200)
    if post_ids is not None:
        query = query.in_('id', list(dict.fromkeys(post_ids)))
    candidates = query.execute().data or []
    if candidates:
        usage = db.table('newsletter_posts').select('newsletter_id,blog_post_id').in_('blog_post_id', [p['id'] for p in candidates]).execute().data or []
        elsewhere = {str(p['blog_post_id']) for p in usage if not edition or str(p['newsletter_id']) != str(edition['id'])}
        candidates = [p for p in candidates if str(p['id']) not in elsewhere]
    if not candidates and not edition:
        return None
    if not edition and require_complete:
        if sum(p.get('category') == 'SHOPPERS' for p in candidates) < 6 or not any(p.get('category') == 'RECALL' for p in candidates):
            return None

    created = False
    if not edition:
        stamp = (now or datetime.now(timezone.utc)).isoformat()
        edition = {'id': str(uuid4()), 'title': title or f'Youdle Grocery News - Week of {start.astimezone(ZoneInfo("America/Chicago")).date().isoformat()}', 'subject': subject or preview_subject(candidates), 'html_content': '', 'status': 'draft', 'created_at': stamp, 'updated_at': stamp}
        try:
            saved = db.table('newsletters').insert(edition).execute().data
            if not saved:
                raise RuntimeError('Newsletter creation returned no record')
            edition = saved[0]
            created = True
        except Exception as exc:
            if '23505' not in str(exc) and 'newsletters_single_editorial_week' not in str(exc):
                raise
            edition = _find_edition(db, start, end)
            if not edition or edition['status'] != 'draft':
                return {'newsletter': edition, 'created': False, 'changed': False, 'locked': True}

    # Move existing recall memberships behind shopper stories without deleting them.
    links = _links(db, edition['id'])
    if links:
        posts = db.table('blog_posts').select('id,category').in_('id', [p['blog_post_id'] for p in links]).execute().data or []
        recall_ids = {str(p['id']) for p in posts if p.get('category') == 'RECALL'}
        for link in links:
            if str(link['blog_post_id']) in recall_ids and link['position'] < RECALL_POSITION:
                for attempt in range(4):
                    fresh = _links(db, edition['id'])
                    if any(p['blog_post_id'] == link['blog_post_id'] and p['position'] >= RECALL_POSITION for p in fresh):
                        break
                    position = max([RECALL_POSITION - 1] + [p['position'] for p in fresh if p['position'] >= RECALL_POSITION]) + 1
                    try:
                        db.table('newsletter_posts').update({'position': position}).eq('id', link['id']).execute()
                        break
                    except Exception as exc:
                        if '23505' not in str(exc) or attempt == 3:
                            raise

    for post in candidates:
        for attempt in range(4):
            fresh = _links(db, edition['id'])
            if any(str(p['blog_post_id']) == str(post['id']) for p in fresh):
                break
            if post.get('category') == 'RECALL':
                position = max([RECALL_POSITION - 1] + [p['position'] for p in fresh if p['position'] >= RECALL_POSITION]) + 1
            else:
                position = max([-1] + [p['position'] for p in fresh if p['position'] < RECALL_POSITION]) + 1
            try:
                db.table('newsletter_posts').insert({'id': str(uuid4()), 'newsletter_id': edition['id'], 'blog_post_id': post['id'], 'position': position}).execute()
                break
            except Exception as exc:
                if '23505' not in str(exc) or attempt == 3:
                    raise

    for attempt in range(4):
        fresh = db.table('newsletters').select('*').eq('id', edition['id']).maybe_single().execute().data
        if not fresh or fresh['status'] != 'draft':
            return {'newsletter': fresh or edition, 'created': created, 'changed': False, 'locked': True}
        ordered = [p['blog_post_id'] for p in _links(db, edition['id'])]
        chosen_subject = subject if subject is not None else fresh.get('subject')
        if not chosen_subject or chosen_subject.startswith(('Youdle Weekly -', 'Youdle Grocery News: this week')):
            current_posts = db.table('blog_posts').select('id,title').in_('id', ordered).execute().data or []
            by_id = {p['id']: p for p in current_posts}
            chosen_subject = preview_subject([by_id[i] for i in ordered if i in by_id])
        body = render(db, ordered, chosen_subject, image_overrides=existing_images(fresh.get('html_content')))
        if body == fresh.get('html_content') and chosen_subject == fresh.get('subject') and (title is None or title == fresh.get('title')):
            return {'newsletter': fresh, 'created': created, 'changed': created, 'locked': False}
        updates = {'html_content': body, 'subject': chosen_subject, 'updated_at': (now or datetime.now(timezone.utc)).isoformat()}
        if title is not None:
            updates['title'] = title
        saved = db.table('newsletters').update(updates).eq('id', fresh['id']).eq('status', 'draft').eq('updated_at', fresh['updated_at']).execute().data
        if saved:
            return {'newsletter': saved[0], 'created': created, 'changed': True, 'locked': False}
    raise RuntimeError('The newsletter changed repeatedly; reload the existing draft')
